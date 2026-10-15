package app.mangalate.translate

import android.content.Context
import com.hippo.unifile.UniFile
import eu.kanade.tachiyomi.data.notification.Notifications
import eu.kanade.tachiyomi.util.system.notify
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.withContext
import java.util.concurrent.atomic.AtomicInteger

/**
 * Traduz as páginas de um capítulo assim que ele termina de baixar, para ler offline.
 * As páginas traduzidas ficam guardadas e são usadas pelo leitor sem internet.
 */
object MangalateDownloadTranslator {

    private const val NOTIFICATION_ID = 0x4D41_4E47
    private val imageExt = setOf("jpg", "jpeg", "png", "webp", "gif", "bmp", "avif", "jxl", "heif", "heic")

    fun shouldTranslate(context: Context): Boolean {
        MangalateTranslator.init(context)
        val s = MangalateTranslator.settings.value
        return s.translateOnDownload && s.isConfigured
    }

    /** Nunca lança erro: se algo falhar, a página é traduzida depois, na hora da leitura. */
    suspend fun translateFolder(context: Context, dir: UniFile, chapterName: String, mangaTitle: String) {
        if (!shouldTranslate(context)) return
        val files = withContext(Dispatchers.IO) {
            dir.listFiles().orEmpty()
                .filter { f -> f.name?.substringAfterLast('.', "")?.lowercase() in imageExt }
                .sortedBy { it.name }
        }
        if (files.isEmpty()) return
        val total = files.size
        val done = AtomicInteger(0)
        val failed = AtomicInteger(0)
        progress(context, mangaTitle, chapterName, 0, total)
        try {
            coroutineScope {
                // Leitores das páginas em ordem: as vizinhas permitem traduzir balões cortados entre fatias.
                val readers = files.map { f -> { f.openInputStream().use { it.readBytes() } } }
                files.mapIndexed { index, file ->
                    async(Dispatchers.IO) {
                        try {
                            val bytes = file.openInputStream().use { it.readBytes() }
                            MangalateTranslator.translate(
                                context,
                                bytes,
                                keepOffline = true,
                                neighbors = { MangalateNeighbors.ofList(readers, index) },
                            )
                        } catch (e: CancellationException) {
                            throw e
                        } catch (e: Throwable) {
                            failed.incrementAndGet()
                        }
                        progress(context, mangaTitle, chapterName, done.incrementAndGet(), total)
                    }
                }.awaitAll()
            }
        } catch (e: CancellationException) {
            context.notify(NOTIFICATION_ID, Notifications.CHANNEL_DOWNLOADER_PROGRESS) {
                setSmallIcon(android.R.drawable.stat_sys_download_done)
                setContentTitle("Tradução interrompida")
                setContentText("$chapterName: o restante será traduzido na leitura")
                setAutoCancel(true)
            }
            throw e
        }
        val fails = failed.get()
        context.notify(NOTIFICATION_ID, Notifications.CHANNEL_DOWNLOADER_PROGRESS) {
            setSmallIcon(android.R.drawable.stat_sys_download_done)
            setContentTitle(if (fails == 0) "Pronto para ler offline" else "Capítulo baixado")
            setContentText(
                if (fails == 0) {
                    "$mangaTitle · $chapterName traduzido"
                } else {
                    "$chapterName: $fails de $total páginas não foram traduzidas (serão na leitura)"
                },
            )
            setAutoCancel(true)
        }
    }

    private fun progress(context: Context, manga: String, chapter: String, done: Int, total: Int) {
        context.notify(NOTIFICATION_ID, Notifications.CHANNEL_DOWNLOADER_PROGRESS) {
            setSmallIcon(android.R.drawable.stat_sys_download)
            setContentTitle("Traduzindo para ler offline · $done/$total")
            setContentText("$manga · $chapter")
            setProgress(total, done, false)
            setOnlyAlertOnce(true)
            setOngoing(true)
        }
    }
}
