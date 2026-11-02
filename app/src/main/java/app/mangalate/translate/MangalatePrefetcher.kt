package app.mangalate.translate

import android.content.Context
import android.os.BatteryManager
import eu.kanade.tachiyomi.source.model.Page
import eu.kanade.tachiyomi.ui.reader.model.InsertPage
import eu.kanade.tachiyomi.ui.reader.model.ReaderChapter
import eu.kanade.tachiyomi.ui.reader.model.ReaderPage
import eu.kanade.tachiyomi.util.system.activeNetworkState
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull

/**
 * Traduz as próximas páginas do capítulo enquanto a pessoa lê a atual,
 * para que já estejam prontas ao virar a página.
 */
object MangalatePrefetcher {

    private const val AHEAD = 6

    /** Faltando estas páginas para o fim do capítulo, começa o próximo (opção desligada por padrão). */
    private const val NEXT_CHAPTER_FROM_END = 5

    suspend fun prefetch(context: Context, chapter: ReaderChapter, currentIndex: Int, next: ReaderChapter? = null) {
        if (!MangalateTranslator.isEnabled(context)) return
        val pages = chapter.pages ?: return
        val targets = pages.drop((currentIndex + 1).coerceAtLeast(0)).take(AHEAD).filter { it !is InsertPage }
        coroutineScope {
            for (page in targets) {
                launch(Dispatchers.IO) { translateWhenReady(context, page) }
            }
        }
        if (next != null && currentIndex >= pages.size - NEXT_CHAPTER_FROM_END && canPrefetchNextChapter(context)) {
            prefetchChapter(context, next)
        }
    }

    /**
     * Traduz o capítulo seguinte inteiro, uma página por vez, na ordem em que o Mihon já o baixa
     * sozinho (uma imagem por vez, depois de carregar o capítulo atual). Páginas já traduzidas vêm
     * do cache. Para na primeira falha: com a IA no limite ou sem rede, insistir só gasta a cota, e
     * uma página que ninguém está vendo não entra no indicador do leitor.
     */
    private suspend fun prefetchChapter(context: Context, chapter: ReaderChapter) {
        // O leitor carrega o próximo capítulo logo depois do atual (só no Wi-Fi, se configurado).
        val state = withTimeoutOrNull(60_000) {
            chapter.stateFlow.first { it is ReaderChapter.State.Loaded || it is ReaderChapter.State.Error }
        }
        val pages = (state as? ReaderChapter.State.Loaded)?.pages ?: return
        for (page in pages) {
            if (page is InsertPage) continue
            if (!canPrefetchNextChapter(context)) return
            withTimeoutOrNull(90_000) {
                page.statusFlow.first { it == Page.State.Ready || it is Page.State.Error }
            }
            if (page.status != Page.State.Ready) return
            try {
                val bytes = page.stream?.invoke()?.use { it.readBytes() } ?: return
                if (bytes.size < 2048) continue
                MangalateTranslator.translate(
                    context,
                    bytes,
                    work = MangalateWork.of(page),
                    neighbors = { MangalateNeighbors.of(page) },
                    sourceLanguage = MangalateWork.language(context, MangalateWork.mangaIdOf(page)),
                )
            } catch (e: CancellationException) {
                throw e
            } catch (e: Throwable) {
                return
            }
        }
    }

    private suspend fun translateWhenReady(context: Context, page: ReaderPage) {
        try {
            // O leitor já baixa as próximas páginas sozinho; aqui só esperamos ficarem prontas.
            withTimeoutOrNull(90_000) {
                page.statusFlow.first { it == Page.State.Ready || it is Page.State.Error }
            }
            if (page.status != Page.State.Ready) return
            val stream = page.stream ?: return
            val bytes = stream().use { it.readBytes() }
            if (bytes.size < 2048) return
            MangalateReaderPages.translate(context, bytes, page)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Throwable) {
            // A falha fica registrada e aparece no indicador do leitor.
        }
    }

    /** Só com a opção ligada, no Wi-Fi e com o celular carregando. */
    private fun canPrefetchNextChapter(context: Context): Boolean {
        if (!MangalateTranslator.settings.value.prefetchNextChapter) return false
        if (!context.activeNetworkState().isWifi) return false
        val battery = context.getSystemService(Context.BATTERY_SERVICE) as? BatteryManager ?: return false
        return battery.isCharging
    }
}
