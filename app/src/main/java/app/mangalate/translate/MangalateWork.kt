package app.mangalate.translate

import android.content.Context
import eu.kanade.tachiyomi.ui.reader.model.InsertPage
import eu.kanade.tachiyomi.ui.reader.model.ReaderPage
import org.json.JSONObject
import java.util.concurrent.ConcurrentHashMap

/**
 * Obra, capítulo e número da página enviados ao servidor junto com a imagem.
 *
 * Com isso o servidor mantém a memória da obra: um glossário aprendido (nomes e
 * termos saem sempre iguais) e as falas das páginas anteriores do capítulo, que
 * dão contexto à IA. Só vale no modo servidor; não muda o cache da página.
 */
data class PageWork(val work: String, val chapter: String, val page: Int) {
    fun toJson(): String = JSONObject()
        .put("obra", work.take(200))
        .put("capitulo", chapter.take(200))
        .put("pagina", page)
        .toString()
}

object MangalateWork {

    private const val LANG_PREFS = "mangalate_work_lang"

    private val titles = ConcurrentHashMap<Long, String>()

    /** Idioma sugerido pela extensão de origem de cada obra aberta. */
    private val suggested = ConcurrentHashMap<Long, SourceLanguage>()

    /** Chamado pelo leitor ao abrir uma obra; [sourceLang] é o idioma da extensão (ex.: "ko"). */
    fun remember(mangaId: Long, title: String, sourceLang: String = "") {
        if (title.isNotBlank()) titles[mangaId] = title
        SourceLanguage.fromSourceLang(sourceLang)?.let { suggested[mangaId] = it }
        // Falhas e páginas no original de outra leitura não valem para esta.
        MangalateReaderPages.startReading()
    }

    fun of(page: ReaderPage): PageWork? {
        if (page is InsertPage) return null
        val chapter = runCatching { page.chapter.chapter }.getOrNull() ?: return null
        val title = titles[chapter.mangaId] ?: return null
        return PageWork(title, chapter.name, page.index + 1)
    }

    fun mangaIdOf(page: ReaderPage): Long? =
        runCatching { page.chapter.chapter.mangaId }.getOrNull()

    /**
     * Idioma em que a obra está escrita: o escolhido para ela, senão o da extensão,
     * senão o padrão das configurações. Só o OCR do celular usa; o servidor detecta sozinho.
     */
    fun language(context: Context, mangaId: Long?, sourceLang: String = ""): SourceLanguage =
        SourceLanguage.pick(
            chosen = mangaId?.let { prefs(context).getString(it.toString(), null) },
            sourceLang = sourceLang,
            suggested = mangaId?.let { suggested[it] },
            default = MangalateTranslator.settings.value.sourceLanguage,
        )

    /** Guarda o idioma escolhido para uma obra; vale também na leitura e no download. */
    fun setLanguage(context: Context, mangaId: Long, language: SourceLanguage) {
        prefs(context).edit().putString(mangaId.toString(), language.name).apply()
    }

    private fun prefs(context: Context) =
        context.applicationContext.getSharedPreferences(LANG_PREFS, Context.MODE_PRIVATE)
}
