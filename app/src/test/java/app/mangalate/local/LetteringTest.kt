package app.mangalate.local

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNotNull
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import java.awt.Font
import java.awt.image.BufferedImage
import java.io.File

class LetteringTest {
    private fun asset(path: String): File =
        listOf(File("src/main/$path"), File("app/src/main/$path")).first { it.exists() }

    private fun dictionary() = asset("assets/lettering/hyph_pt_BR.dic").bufferedReader().use {
        PortugueseHyphenator(it.lineSequence())
    }

    @Test
    fun `especial has syllabic boundaries instead of esp ecial`() {
        assertEquals(listOf(2, 4, 6), dictionary().breaks("especial"))
        assertFalse(3 in dictionary().breaks("especial"))
    }

    @Test
    fun `importante keeps the syllables im por tan te`() {
        assertEquals(listOf(2, 5, 8), dictionary().breaks("importante"))
    }

    @Test
    fun `short words do not create one-letter fragments`() {
        val h = dictionary()
        for (word in listOf("miau", "bom", "dia", "tá", "eu")) assertTrue(h.breaks(word).isEmpty())
    }

    @Test
    fun `upper case preserves the same hyphenation`() {
        val h = dictionary()
        assertEquals(h.breaks("especial"), h.breaks("ESPECIAL"))
        assertEquals(h.breaks("gatinho"), h.breaks("GATINHO"))
    }

    @Test
    fun `accented words preserve all letters`() {
        val text = "É uma ocasião importante para nós."
        val wrapped = BubbleTextWrapper.wrap(text, 12f, { it.length.toFloat() }, dictionary()::breaks)!!
        assertEquals(
            text.filter { !it.isWhitespace() },
            wrapped.joinToString("").replace("-", "").filter { !it.isWhitespace() },
        )
    }

    @Test
    fun `word that fits stays whole`() {
        val lines = BubbleTextWrapper.wrap("Um dia especial", 10f, { it.length.toFloat() }, dictionary()::breaks)!!
        assertTrue(lines.none { it.endsWith('-') })
        assertTrue(lines.any { "especial" in it })
    }

    @Test
    fun `narrow balloon uses a visible hyphen at legal syllable boundary`() {
        val lines = BubbleTextWrapper.wrap("especial", 5f, { it.length.toFloat() }, dictionary()::breaks)!!
        assertEquals(listOf("espe-", "cial"), lines)
        assertTrue(lines.all { it.length <= 5 })
    }

    @Test
    fun `cannot fit a legal syllable means shrink font not split arbitrary letters`() {
        assertNull(BubbleTextWrapper.wrap("miau", 2f, { it.length.toFloat() }, dictionary()::breaks))
        assertNull(BubbleTextWrapper.wrap("especial", 2f, { it.length.toFloat() }, dictionary()::breaks))
    }

    @Test
    fun `line breaks from translation do not force narrow text columns`() {
        val lines = BubbleTextWrapper.wrap("Hoje\né um\ndia especial", 40f, { it.length.toFloat() }, dictionary()::breaks)
        assertEquals(listOf("Hoje é um dia especial"), lines)
    }

    @Test
    fun `punctuation stays attached to the word`() {
        val lines = BubbleTextWrapper.wrap("...importante!", 8f, { it.length.toFloat() }, dictionary()::breaks)!!
        assertEquals("...importante!", lines.joinToString("").replace("-", ""))
        assertTrue(lines.all { it.length <= 8 })
    }

    @Test
    fun `hyphenation is opt in per language`() {
        assertNull(BubbleTextWrapper.wrap("special", 4f, { it.length.toFloat() }, { emptyList() }))
    }

    @Test
    fun `ellipse safe rectangle contains no exterior pixels`() {
        val width = 180
        val height = 240
        val mask = BooleanArray(width * height) { i ->
            val x = (i % width - 90) / 64.0
            val y = (i / width - 110) / 92.0
            x * x + y * y < 1.0
        }
        val box = BubbleGeometry.fit(mask, width, height, 90, 105)
        assertNotNull(box)
        box!!
        for (y in box.top until box.bottom) for (x in box.left until box.right) {
            assertTrue(mask[y * width + x], "Exterior pixel $x,$y in $box")
        }
        assertTrue(box.width > 70)
        assertTrue(box.height > 90)
    }

    @Test
    fun `long tail does not pull text below balloon body`() {
        val w = 120
        val h = 240
        val mask = BooleanArray(w * h) { i ->
            val x = i % w
            val y = i / w
            val dx = (x - 60) / 48.0
            val dy = (y - 75) / 60.0
            dx * dx + dy * dy < 1 || (x in 58..62 && y in 75..220)
        }
        val box = BubbleGeometry.fit(mask, w, h, 60, 70)!!
        assertTrue((box.top + box.bottom) / 2 < 100)
        assertTrue(box.bottom < 140)
    }

    @Test
    fun `empty mask and tiny area fail safely`() {
        assertNull(BubbleGeometry.fit(BooleanArray(100), 10, 10, 5, 5))
        assertNull(BubbleGeometry.fit(BooleanArray(4) { true }, 2, 2, 1, 1))
    }

    @Test
    fun `real comic font wraps screenshot regression phrases without overflow`() {
        val font = Font.createFont(Font.TRUETYPE_FONT, asset("res/font/mangalate_comic_bold.ttf")).deriveFont(16f)
        val image = BufferedImage(200, 200, BufferedImage.TYPE_INT_RGB)
        val graphics = image.createGraphics()
        graphics.font = font
        val metrics = graphics.fontMetrics
        val phrases = listOf("Hoje será um dia especial.", "É um dia importante.", "Bom dia, gatinho.", "...Tá bom.", "Miau.")
        for (text in phrases) {
            val lines = BubbleTextWrapper.wrap(text, 80f, { metrics.stringWidth(it).toFloat() }, dictionary()::breaks)!!
            assertTrue(lines.all { metrics.stringWidth(it) <= 80 })
            assertEquals(
                text.filter { !it.isWhitespace() },
                lines.joinToString("").replace("-", "").filter { !it.isWhitespace() },
            )
        }
        graphics.dispose()
    }
}
