package app.mangalate.translate

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

    private val titles = ConcurrentHashMap<Long, String>()

    /** Chamado pelo leitor ao abrir uma obra. */
    fun remember(mangaId: Long, title: String) {
        if (title.isNotBlank()) titles[mangaId] = title
    }

    fun of(page: ReaderPage): PageWork? {
        if (page is InsertPage) return null
        val chapter = runCatching { page.chapter.chapter }.getOrNull() ?: return null
        val title = titles[chapter.mangaId] ?: return null
        return PageWork(title, chapter.name, page.index + 1)
    }
}
