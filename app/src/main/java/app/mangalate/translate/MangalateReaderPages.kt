package app.mangalate.translate

import android.content.Context
import eu.kanade.tachiyomi.ui.reader.model.ReaderPage
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import okio.Buffer
import okio.BufferedSource
import java.net.ConnectException
import java.net.NoRouteToHostException
import java.net.UnknownHostException
import java.util.concurrent.ConcurrentHashMap

/**
 * Estado das páginas no leitor: quais mostram o original, quais devem ser refeitas
 * e quais falharam. Os leitores (paginado e webtoon) redesenham uma página quando
 * [refreshOf] muda, sem mexer nas outras.
 */
object MangalateReaderPages {

    /** Espera entre tentativas quando todas as IAs do servidor estão no limite gratuito. */
    private const val LIMIT_RETRY_MS = 60_000L
    private const val LIMIT_RETRY_MAX = 30

    enum class Problem {
        /** Todas as IAs no limite gratuito; a página é tentada de novo sozinha. */
        LIMIT,

        /** Sem internet ou servidor fora do ar. */
        OFFLINE,
        OTHER,
    }

    private val revisions = MutableStateFlow<Map<String, Int>>(emptyMap())

    private val _original = MutableStateFlow<Set<String>>(emptySet())

    /** Páginas que a pessoa pediu para ver no original, com a tradução ainda ligada. */
    val original: StateFlow<Set<String>> = _original.asStateFlow()

    private val redo = ConcurrentHashMap.newKeySet<String>()

    private val _failures = MutableStateFlow<Map<String, Problem>>(emptyMap())

    /** Páginas que ficaram sem tradução, com o motivo (para o indicador do leitor). */
    val failures: StateFlow<Map<String, Problem>> = _failures.asStateFlow()

    private val _reviews = MutableStateFlow<Map<String, PageReview>>(emptyMap())

    /** Páginas traduzidas que o servidor pediu para conferir (para o selo do leitor). */
    val reviews: StateFlow<Map<String, PageReview>> = _reviews.asStateFlow()

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    @Volatile
    private var limitRetry: Job? = null

    /** Novas tentativas das páginas paradas pelo limite das IAs, feitas em segundo plano. */
    private val limitRetries = ConcurrentHashMap<String, suspend () -> ByteArray>()

    fun keyOf(page: ReaderPage): String {
        val chapterId = runCatching { page.chapter.chapter.id }.getOrNull() ?: -1L
        return "$chapterId:${page.index}"
    }

    /** Muda quando a tradução liga ou desliga, ou quando só esta página precisa ser redesenhada. */
    fun refreshOf(page: ReaderPage): Flow<Any> {
        val key = keyOf(page)
        return combine(
            MangalateTranslator.enabled,
            revisions.map { it[key] ?: 0 }.distinctUntilChanged(),
        ) { enabled, revision -> enabled to revision }
    }

    /**
     * Gancho usado pelos leitores. Se a tradução estiver ativa, devolve a página traduzida;
     * em qualquer falha devolve a original, para a leitura nunca travar.
     */
    suspend fun maybeTranslate(context: Context, source: Buffer, page: ReaderPage): BufferedSource {
        if (!MangalateTranslator.isEnabled(context)) return source
        if (source.size < 2048) return source
        if (MangalateTranslator.isGifOrAnimated(source)) return source
        val key = keyOf(page)
        if (key in _original.value) return source
        return try {
            Buffer().write(translate(context, source.peek().readByteArray(), page, key))
        } catch (e: CancellationException) {
            throw e
        } catch (e: Throwable) {
            // O limite das IAs já aparece no indicador do leitor, sem repetir o aviso a cada tentativa.
            if (e !is ProviderLimitException) MangalateTranslator.notifyError(context, e)
            source
        }
    }

    /** Traduz uma página do leitor, refazendo-a se foi pedido e registrando a falha. */
    suspend fun translate(context: Context, bytes: ByteArray, page: ReaderPage, key: String = keyOf(page)): ByteArray {
        val force = redo.remove(key)
        var done = false
        try {
            val result = MangalateTranslator.translate(
                context,
                bytes,
                work = MangalateWork.of(page),
                neighbors = { MangalateNeighbors.of(page) },
                force = force,
                sourceLanguage = MangalateWork.language(context, MangalateWork.mangaIdOf(page)),
                onReview = { review ->
                    _reviews.update { if (review?.needsLook == true) it + (key to review) else it - key }
                },
            )
            done = true
            _failures.update { it - key }
            limitRetries.remove(key)
            return result
        } catch (e: CancellationException) {
            throw e
        } catch (e: Throwable) {
            val problem = problemOf(e)
            _failures.update { it + (key to problem) }
            if (problem == Problem.LIMIT) {
                val app = context.applicationContext
                limitRetries[key] = { translate(app, bytes, page, key) }
                scheduleLimitRetry()
            } else {
                limitRetries.remove(key)
            }
            throw e
        } finally {
            // Refazer que falhou ou foi interrompido continua pendente: a próxima tentativa
            // também ignora a tradução guardada.
            if (force && !done) redo.add(key)
        }
    }

    internal fun problemOf(e: Throwable): Problem = when (e) {
        is ProviderLimitException -> Problem.LIMIT
        is UnknownHostException, is ConnectException, is NoRouteToHostException -> Problem.OFFLINE
        else -> Problem.OTHER
    }

    fun isOriginal(page: ReaderPage): Boolean = keyOf(page) in _original.value

    /** Alterna entre o original e a tradução só desta página. */
    fun toggleOriginal(page: ReaderPage) {
        val key = keyOf(page)
        _original.update { if (key in it) it - key else it + key }
        refresh(listOf(key))
    }

    /** Traduz a página de novo, sem usar a tradução guardada. */
    fun redoPage(page: ReaderPage) {
        val key = keyOf(page)
        redo.add(key)
        _original.update { it - key }
        refresh(listOf(key))
    }

    /** Traduz o capítulo de novo: a página aberta na hora e as outras quando forem abertas. */
    fun redoChapter(page: ReaderPage) {
        val pages = runCatching { page.chapter.pages }.getOrNull() ?: listOf(page)
        val keys = pages.map(::keyOf).distinct()
        redo.addAll(keys)
        _original.update { it - keys.toSet() }
        refresh(keys)
    }

    /** Redesenha o capítulo, por exemplo depois de trocar o idioma da obra. */
    fun refreshChapter(page: ReaderPage) {
        val pages = runCatching { page.chapter.pages }.getOrNull() ?: listOf(page)
        refresh(pages.map(::keyOf).distinct())
    }

    /** Tenta de novo as páginas que falharam; as que não estão na tela tentam ao serem abertas. */
    fun retryFailed() {
        val keys = _failures.value.keys.toList()
        _failures.value = emptyMap()
        refresh(keys)
    }

    /** Chamado ao abrir uma obra no leitor: cada leitura começa traduzida e sem falhas. */
    fun startReading() {
        _failures.value = emptyMap()
        _original.value = emptySet()
        _reviews.value = emptyMap()
        limitRetries.clear()
    }

    private fun refresh(keys: Collection<String>) {
        if (keys.isEmpty()) return
        revisions.update { current -> current + keys.associateWith { (current[it] ?: 0) + 1 } }
    }

    /**
     * Com as IAs no limite, as páginas paradas são tentadas de novo a cada minuto, em segundo
     * plano; só a que der certo é redesenhada. Desiste depois de [LIMIT_RETRY_MAX] tentativas.
     */
    private fun scheduleLimitRetry() {
        if (limitRetry?.isActive == true) return
        limitRetry = scope.launch {
            repeat(LIMIT_RETRY_MAX) {
                delay(LIMIT_RETRY_MS)
                if (!MangalateTranslator.enabled.value || limitRetries.isEmpty()) return@launch
                for ((key, retry) in limitRetries.entries.toList()) {
                    val ok = try {
                        retry()
                        true
                    } catch (e: CancellationException) {
                        throw e
                    } catch (e: Throwable) {
                        false
                    }
                    if (ok) refresh(listOf(key))
                    // Ainda no limite: as outras páginas esperam a próxima rodada.
                    if (!ok && Problem.LIMIT == _failures.value[key]) break
                }
            }
            // Desistiu: o indicador passa a pedir um toque, e os bytes das páginas são soltos.
            limitRetries.clear()
            _failures.update { failures ->
                failures.mapValues { if (it.value == Problem.LIMIT) Problem.OTHER else it.value }
            }
        }
    }
}
