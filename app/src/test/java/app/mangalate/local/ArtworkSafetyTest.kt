package app.mangalate.local

import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNotNull
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class ArtworkSafetyTest {
    private val white = 0xFFFFFFFF.toInt()
    private val ink = 0xFF141414.toInt()

    @Test
    fun `huge false balloon on right half of page is rejected`() {
        assertFalse(
            BubbleBoundsGuard.accepts(
                BubbleGeometry.Box(195, 273, 237, 310),
                BubbleGeometry.Box(143, 148, 269, 450),
                270, 600,
            ),
        )
    }

    @Test
    fun `normal bubble retains full cleaning`() {
        assertTrue(
            BubbleBoundsGuard.accepts(
                BubbleGeometry.Box(94, 176, 126, 233),
                BubbleGeometry.Box(80, 159, 139, 244),
                270, 600,
            ),
        )
    }

    @Test
    fun `whole panel around tiny caption is not a balloon`() {
        assertFalse(
            BubbleBoundsGuard.accepts(
                BubbleGeometry.Box(188, 397, 224, 432),
                BubbleGeometry.Box(20, 383, 250, 461),
                270, 600,
            ),
        )
    }

    @Test
    fun `large AI box that looks plausible by ratio still fails page limit`() {
        assertFalse(
            BubbleBoundsGuard.accepts(
                BubbleGeometry.Box(50, 80, 210, 410),
                BubbleGeometry.Box(25, 40, 250, 480),
                270, 600,
            ),
        )
    }

    @Test
    fun `mask unrelated to detected text is rejected`() {
        assertFalse(
            BubbleBoundsGuard.accepts(
                BubbleGeometry.Box(10, 20, 40, 60),
                BubbleGeometry.Box(110, 120, 160, 200),
                270, 600,
            ),
        )
    }

    @Test
    fun `effects are off unless explicitly enabled`() {
        assertFalse(SoundEffectPolicy.shouldTranslate(TextKind.SOUND_EFFECT, "CLAP", false))
        assertFalse(SoundEffectPolicy.shouldTranslate(TextKind.UNKNOWN, "CLAP CLAP", false))
        assertFalse(SoundEffectPolicy.shouldTranslate(TextKind.UNKNOWN, "パチパチ", false))
        assertFalse(SoundEffectPolicy.shouldTranslate(TextKind.SPEECH, "CLAP", false))
        assertTrue(SoundEffectPolicy.shouldTranslate(TextKind.SOUND_EFFECT, "CLAP", true))
    }

    @Test
    fun `speech and narration remain translatable with effects disabled`() {
        assertTrue(SoundEffectPolicy.shouldTranslate(TextKind.SPEECH, "Today is a lucky day", false))
        assertTrue(SoundEffectPolicy.shouldTranslate(TextKind.NARRATION, "But my previous teacher...", false))
        assertTrue(SoundEffectPolicy.shouldTranslate(TextKind.UNKNOWN, "Clap your hands", false))
    }

    @Test
    fun `typing variations of sound effects are handled`() {
        for (text in listOf("CLAP!", "clap-clap", "Clop clop", "...BANG!", "ドーン")) {
            assertTrue(SoundEffectPolicy.looksLikeEffect(text), text)
        }
    }

    @Test
    fun `selective mask removes glyphs but preserves large portrait component`() {
        val w = 180
        val h = 100
        val pixels = IntArray(w * h) { white }
        // Portrait/hair entering the text box from the left.
        for (y in 10..85) for (x in 2..48) pixels[y * w + x] = ink
        // Letters: separate small components inside the text area.
        for (y in 25..30) for (x in 70..74) pixels[y * w + x] = ink
        for (y in 40..45) for (x in 90..94) pixels[y * w + x] = ink
        val result = GlyphCleaner.identify(
            pixels, w, h, listOf(BubbleGeometry.Box(10, 20, 130, 65)), 270,
        )
        assertNotNull(result)
        assertTrue(result!!.mask[27 * w + 72])
        assertTrue(result.mask[43 * w + 92])
        for (y in 10..85) for (x in 2..48) assertFalse(result.mask[y * w + x])
    }

    @Test
    fun `white background never becomes a rectangle mask`() {
        val w = 90
        val h = 50
        val pixels = IntArray(w * h) { white }
        for (y in 18..23) for (x in 35..39) pixels[y * w + x] = ink
        val result = GlyphCleaner.identify(pixels, w, h, listOf(BubbleGeometry.Box(20, 10, 65, 35)), 270)!!
        assertTrue(result.mask.count { it } < 100)
        assertFalse(result.mask[12 * w + 21])
        assertFalse(result.mask[33 * w + 60])
    }

    @Test
    fun `textured artwork is not whitened`() {
        val pixels = IntArray(90 * 50) { if (it % 2 == 0) ink else 0xFF888888.toInt() }
        assertNull(GlyphCleaner.identify(pixels, 90, 50, listOf(BubbleGeometry.Box(10, 10, 70, 40)), 270))
    }

    @Test
    fun `stronger contour closure cannot turn crop border into a balloon`() {
        val w = 100
        val h = 160
        assertNull(
            BubbleSegmenter.identify(
                IntArray(w * h) { white }, w, h, BubbleGeometry.Box(35, 50, 65, 90), closureRadius = 2,
            ),
        )
    }

    @Test
    fun `a giant closed frame with small text is rejected during segmentation`() {
        val w = 180
        val h = 300
        val pixels = IntArray(w * h) { white }
        for (y in 12..285) for (x in 12..167) {
            if (y == 12 || y == 285 || x == 12 || x == 167) pixels[y * w + x] = ink
        }
        assertNull(BubbleSegmenter.identify(pixels, w, h, BubbleGeometry.Box(60, 120, 95, 145)))
    }
}
