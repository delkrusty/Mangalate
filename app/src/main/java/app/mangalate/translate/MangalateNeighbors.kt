package app.mangalate.translate

import eu.kanade.tachiyomi.source.model.Page
import eu.kanade.tachiyomi.ui.reader.model.InsertPage
import eu.kanade.tachiyomi.ui.reader.model.ReaderPage
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull

/**
 * Páginas vizinhas (anterior e seguinte) de uma página do leitor.
 *
 * Em webtoons, um balão pode ser cortado entre duas fatias. O servidor usa as
 * vizinhas para traduzir o balão inteiro; ele só emenda quando as bordas são de
 * fato contínuas, então mandar vizinhas de páginas comuns não muda o resultado.
 */
object MangalateNeighbors {

    private const val WAIT_MS = 4_000L

    suspend fun of(page: ReaderPage): Pair<ByteArray?, ByteArray?> {
        if (page is InsertPage) return null to null
        val pages = runCatching { page.chapter.pages }.getOrNull() ?: return null to null
        val position = pages.indexOf(page)
        if (position < 0) return null to null
        return bytesOf(pages.getOrNull(position - 1)) to bytesOf(pages.getOrNull(position + 1))
    }

    /** Lê a vizinha se já estiver pronta; espera um pouco só se ela já estiver carregando. */
    private suspend fun bytesOf(page: ReaderPage?): ByteArray? {
        if (page == null || page is InsertPage) return null
        return try {
            when (page.status) {
                Page.State.Ready -> Unit
                Page.State.Queue, is Page.State.Error -> return null
                else -> withTimeoutOrNull(WAIT_MS) {
                    page.statusFlow.first { it == Page.State.Ready || it is Page.State.Error }
                }
            }
            if (page.status != Page.State.Ready) return null
            val stream = page.stream ?: return null
            withContext(Dispatchers.IO) { stream().use { it.readBytes() } }.takeIf { it.size >= 2048 }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Throwable) {
            null
        }
    }

    /** Vizinhas de um arquivo numa lista ordenada (capítulo baixado). */
    fun ofList(files: List<() -> ByteArray?>, index: Int): Pair<ByteArray?, ByteArray?> {
        fun read(i: Int) = files.getOrNull(i)?.let { runCatching { it() }.getOrNull() }
        return read(index - 1) to read(index + 1)
    }
}
