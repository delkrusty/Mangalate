package app.mangalate.translate

import android.content.Context
import eu.kanade.tachiyomi.source.model.Page
import eu.kanade.tachiyomi.ui.reader.model.InsertPage
import eu.kanade.tachiyomi.ui.reader.model.ReaderChapter
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

    suspend fun prefetch(context: Context, chapter: ReaderChapter, currentIndex: Int) {
        if (!MangalateTranslator.isEnabled(context)) return
        val pages = chapter.pages ?: return
        val targets = pages.drop((currentIndex + 1).coerceAtLeast(0)).take(AHEAD).filter { it !is InsertPage }
        coroutineScope {
            for (page in targets) {
                launch(Dispatchers.IO) {
                    try {
                        // O leitor já baixa as próximas páginas sozinho; aqui só esperamos ficarem prontas.
                        withTimeoutOrNull(90_000) {
                            page.statusFlow.first { it == Page.State.Ready || it is Page.State.Error }
                        }
                        if (page.status != Page.State.Ready) return@launch
                        val stream = page.stream ?: return@launch
                        val bytes = stream().use { it.readBytes() }
                        if (bytes.size < 2048) return@launch
                        MangalateTranslator.translate(
                            context,
                            bytes,
                            work = MangalateWork.of(page),
                            neighbors = { MangalateNeighbors.of(page) },
                        )
                    } catch (e: CancellationException) {
                        throw e
                    } catch (e: Throwable) {
                        // falhas aparecem quando a página for aberta
                    }
                }
            }
        }
    }
}
