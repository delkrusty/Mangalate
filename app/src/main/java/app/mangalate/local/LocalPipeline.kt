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
                TranslateMode.GEMINI -> {
                    val detected = GeminiClient.detectAndTranslate(page, s).filter {
                        SoundEffectPolicy.shouldTranslate(it.kind, it.original, s.translateSoundEffects)
                    }
                    val local = runCatching { OnDeviceOcr.detect(page, s.sourceLanguage) }.getOrDefault(emptyList())
                    RegionRefiner.refine(detected, local)
                }
                else -> {
                    val found = OnDeviceOcr.detect(page, s.sourceLanguage).filter {
                        SoundEffectPolicy.shouldTranslate(it.kind, it.original, s.translateSoundEffects)
                    }
                    if (found.isEmpty()) {
                        emptyList()
                    } else {
                        val texts = found.map { it.original }
                        val translated = OnDeviceTranslate.translate(texts, s.sourceLanguage, s.targetLanguage) {
                            status("Baixando o tradutor (só na primeira vez)…")
                        }.also { status(null) }
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
