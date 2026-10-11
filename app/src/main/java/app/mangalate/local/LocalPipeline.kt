package app.mangalate.local

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import app.mangalate.translate.MangalateSettings
import app.mangalate.translate.TranslateMode
import kotlinx.coroutines.Dispatchers
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
                    val found = OnDeviceOcr.detect(page, s.sourceLanguage)
                    if (found.isEmpty()) {
                        emptyList()
                    } else {
                        val translated = OnDeviceTranslate.translate(
                            found.map { it.original },
                            s.sourceLanguage,
                            s.targetLanguage,
                        ) { status("Baixando o tradutor (só na primeira vez)…") }
                        status(null)
                        found.zip(translated) { r, t -> r.copy(translation = t) }
                    }
                }
            }
            if (regions.isEmpty()) return@withContext bytes
            PageRenderer.render(context, page, regions, s)
            ByteArrayOutputStream(bytes.size).use {
                page.compress(Bitmap.CompressFormat.JPEG, 94, it)
                it.toByteArray()
            }
        } finally {
            page.recycle()
        }
    }
}
