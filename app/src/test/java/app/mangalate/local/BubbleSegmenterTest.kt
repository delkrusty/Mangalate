package app.mangalate.local

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNotNull
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import kotlin.math.abs

class BubbleSegmenterTest {
    private val w = 160
    private val h = 200
    private val white = 0xFFFFFFFF.toInt()
    private val black = 0xFF111111.toInt()
    private val art = 0xFF666666.toInt()
    private val text = BubbleGeometry.Box(65, 70, 95, 115)

    private fun balloon(dark: Boolean = false, gap: Boolean = false): IntArray {
        val background = if (dark) black else white
        val contour = if (dark) white else black
        return IntArray(w * h) { i ->
            val x = i % w
            val y = i / w
            val ellipse = (x - 80) * (x - 80) / (56.0 * 56.0) + (y - 95) * (y - 95) / (72.0 * 72.0)
            when {
                gap && x in 74..86 && y < 32 -> background
                ellipse > 1.06 -> art
                ellipse > 0.94 -> contour
                else -> background
            }
        }.apply {
            // Letras dentro da caixa do OCR.
            for (y in 75..109 step 9) for (x in 70..91) this[y * w + x] = contour
            // Caracteres não identificados, longe da caixa do OCR.
            for (y in 125..135) for (x in 110..115) this[y * w + x] = contour
        }
    }

    @Test
    fun `whole interior includes letters outside OCR bounds`() {
        val result = BubbleSegmenter.identify(balloon(), w, h, text)
        assertNotNull(result)
        assertTrue(result!!.interior[130 * w + 112])
        assertTrue(result.interior[90 * w + 80])
        assertFalse(result.interior[0])
        assertEquals(white, result.background)
    }

    @Test
    fun `contour and external art remain untouched`() {
        val original = balloon()
        val result = BubbleSegmenter.identify(original, w, h, text)!!
        val cleaned = original.copyOf()
        for (i in cleaned.indices) if (result.interior[i]) cleaned[i] = result.background
        assertEquals(white, cleaned[130 * w + 112])
        for (i in original.indices) {
            val x = i % w
            val y = i / w
            val ellipse = (x - 80) * (x - 80) / (56.0 * 56.0) + (y - 95) * (y - 95) / (72.0 * 72.0)
            if (ellipse > 0.94) assertEquals(original[i], cleaned[i], "Changed outline or art at $x,$y")
        }
    }

    @Test
    fun `white letters on a dark balloon are cleaned`() {
        val result = BubbleSegmenter.identify(balloon(dark = true), w, h, text)!!
        assertEquals(black, result.background)
        assertTrue(result.interior[130 * w + 112])
    }

    @Test
    fun `unbounded white page is rejected`() {
        assertNull(BubbleSegmenter.identify(IntArray(w * h) { white }, w, h, text))
    }

    @Test
    fun `open contour that leaks onto white surroundings is rejected`() {
        val page = balloon(gap = true)
        for (i in page.indices) if (page[i] == art) page[i] = white
        assertNull(BubbleSegmenter.identify(page, w, h, text))
    }

    @Test
    fun `textured area must not be flattened`() {
        val page = balloon()
        for (y in 50..135) for (x in 45..115) {
            if ((x + y) % 4 <= 1 && page[y * w + x] == white) page[y * w + x] = art
        }
        assertNull(BubbleSegmenter.identify(page, w, h, text))
    }

    @Test
    fun `small break in antialiased outline can be closed`() {
        val page = balloon()
        for (y in 22..30) page[y * w + 80] = white
        val result = BubbleSegmenter.identify(page, w, h, text)
        assertNotNull(result)
        assertFalse(result!!.interior[10 * w + 80])
    }

    @Test
    fun `characters touching the border are removed inside but border stays`() {
        val page = balloon()
        for (x in 84..140) page[95 * w + x] = black
        val result = BubbleSegmenter.identify(page, w, h, text)!!
        assertTrue(result.interior[95 * w + 110])
        assertFalse(result.interior[95 * w + 139])
    }

    @Test
    fun `nearby balloon is not accidentally erased`() {
        val page = IntArray(320 * h) { white }
        for (y in 0 until h) for (x in 0 until 320) {
            val center = if (x < 160) 80 else 240
            val ellipse = (x - center) * (x - center) / (56.0 * 56.0) + (y - 95) * (y - 95) / (72.0 * 72.0)
            if (abs(ellipse - 1.0) < 0.07) page[y * 320 + x] = black
        }
        val result = BubbleSegmenter.identify(page, 320, h, text)!!
        assertTrue(result.interior[95 * 320 + 80])
        assertFalse(result.interior[95 * 320 + 240])
    }
}
