package app.mangalate.local

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import app.mangalate.translate.MangalateSettings
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.ByteArrayOutputStream
import kotlin.math.max
import kotlin.math.min

/**
 * O backend devolve uma imagem pronta, sem classes semânticas. No padrão seguro,
 * só copiamos os pixels traduzidos que ficam em balões confirmados no ORIGINAL.
 * Efeitos e arte externa ficam literalmente como estavam, independentemente do backend.
 */
internal object ServerArtworkGuard {
    suspend fun preserve(
        originalBytes: ByteArray,
        translatedBytes: ByteArray,
        settings: MangalateSettings,
    ): ByteArray = withContext(Dispatchers.Default) {
        if (settings.translateSoundEffects && !settings.ignoreOutsideBubbles) return@withContext translatedBytes
        val original = BitmapFactory.decodeByteArray(originalBytes, 0, originalBytes.size) ?: return@withContext originalBytes
        val translated = BitmapFactory.decodeByteArray(translatedBytes, 0, translatedBytes.size)
        if (translated == null) {
            original.recycle()
            return@withContext originalBytes
        }
        try {
            if (translated.width != original.width || translated.height != original.height) return@withContext originalBytes
            val regions = OnDeviceOcr.detect(original, settings.sourceLanguage)
            val output = original.copy(Bitmap.Config.ARGB_8888, true) ?: return@withContext originalBytes
            var applied = false
            try {
                for (region in regions) {
                    if (!SoundEffectPolicy.shouldTranslate(region.kind, region.original, settings.translateSoundEffects)) continue
                    val r = region.rect
                    val grow = min(max(48, (max(r.width(), r.height()) * 1.5f).toInt()), max(48, original.width / 3))
                    val left = max(0, r.left - grow)
                    val top = max(0, r.top - grow)
                    val right = min(original.width, r.right + grow)
                    val bottom = min(original.height, r.bottom + grow)
                    val w = right - left
                    val h = bottom - top
                    val source = IntArray(w * h)
                    original.getPixels(source, 0, w, left, top, w, h)
                    val text = BubbleGeometry.Box(r.left - left, r.top - top, r.right - left, r.bottom - top)
                    val bubble = BubbleSegmenter.identify(source, w, h, text)
                        ?: BubbleSegmenter.identify(source, w, h, text, closureRadius = 2)
                        ?: continue
                    if (!BubbleBoundsGuard.accepts(text, bubble.bounds, original.width, original.height)) continue
                    val serverPixels = IntArray(w * h)
                    translated.getPixels(serverPixels, 0, w, left, top, w, h)
                    val destination = IntArray(w * h)
                    output.getPixels(destination, 0, w, left, top, w, h)
                    for (i in source.indices) if (bubble.interior[i]) destination[i] = serverPixels[i]
                    output.setPixels(destination, 0, w, left, top, w, h)
                    applied = true
                }
                if (!applied) return@withContext originalBytes
                ByteArrayOutputStream().use {
                    output.compress(Bitmap.CompressFormat.PNG, 100, it)
                    it.toByteArray()
                }
            } finally {
                output.recycle()
            }
        } finally {
            original.recycle()
            translated.recycle()
        }
    }
}
