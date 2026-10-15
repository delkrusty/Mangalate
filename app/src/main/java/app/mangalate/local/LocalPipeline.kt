package app.mangalate.local

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import app.mangalate.translate.MangalateSettings
import app.mangalate.translate.TranslateMode
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.withContext
import java.io.ByteArrayOutputStream
import java.io.IOException

/**
 * Pipeline que roda sem servidor: OCR/IA → tradução → limpeza → diagramação.
 */
object LocalPipeline {

    suspend fun process(
        context: Context,
        bytes: ByteArray,
        s: MangalateSettings,
        status: (String?) -> Unit,
    ): ByteArray = withContext(Dispatchers.Default) {
        val opts = BitmapFactory.Options().apply {
            inMutable = true
            inPreferredConfig = Bitmap.Config.ARGB_8888
        }
        val page = BitmapFactory.decodeByteArray(bytes, 0, bytes.size, opts)
            ?: throw IOException("Formato de imagem não suportado")
        try {
            val regions = when (s.mode) {
                TranslateMode.GEMINI -> GeminiClient.detectAndTranslate(page, s)
                else -> {
                    val found = stage("reconhecimento do texto (OCR)") {
                        OnDeviceOcr.detect(page, s.sourceLanguage)
                    }.filter { OfflineText.keep(it.original, s.sourceLanguage) }
                    if (found.isEmpty()) {
                        emptyList()
                    } else {
                        val texts = found.map { it.original }
                        val translated = if (s.mode == TranslateMode.DEEPL) {
                            DeepLClient.translate(s.deeplKey, texts, s.sourceLanguage, s.targetLanguage)
                        } else {
                            try {
                                stage("tradução no celular; confira os idiomas em Configurações > Mangalate") {
                                    OnDeviceTranslate.translate(texts, s.sourceLanguage, s.targetLanguage) {
                                        status("Baixando o tradutor (só na primeira vez)…")
                                    }
                                }
                            } finally {
                                status(null)
                            }
                        }
                        found.zip(translated) { r, t -> r.copy(translation = OfflineText.tidy(t, r.original)) }
                    }
                }
            }
            val kept = regions.filter { OfflineText.keep(it.original, s.sourceLanguage) }
            if (kept.isEmpty()) return@withContext bytes
            PageRenderer.render(context, page, kept, s)
            ByteArrayOutputStream(bytes.size).use {
                page.compress(Bitmap.CompressFormat.JPEG, 94, it)
                it.toByteArray()
            }
        } finally {
            page.recycle()
        }
    }

    private suspend fun <T> stage(name: String, block: suspend () -> T): T = try {
        block()
    } catch (e: CancellationException) {
        throw e
    } catch (e: Exception) {
        throw FriendlyException("Falha no $name: ${e.message ?: e.javaClass.simpleName}").apply { initCause(e) }
    }
}
