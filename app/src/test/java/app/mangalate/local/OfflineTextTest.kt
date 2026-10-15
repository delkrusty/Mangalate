package app.mangalate.local

import app.mangalate.translate.SourceLanguage
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class OfflineTextTest {

    @Test
    fun creditsAndWatermarksStayInTheOriginal() {
        assertTrue(OfflineText.isCredit("Read the latest chapters at asurascans.com"))
        assertTrue(OfflineText.isCredit("Join our DISCORD"))
        assertTrue(OfflineText.isCredit("TOWER OF GOD™"))
        assertFalse(OfflineText.isCredit("IT SCANS THE AREA."))
        assertFalse(OfflineText.isCredit("Where are you going?"))
    }

    @Test
    fun leftoverSoundEffectsOnlyInEnglishScans() {
        assertTrue(OfflineText.isSoundEffect("ドドド", SourceLanguage.EN))
        assertFalse(OfflineText.isSoundEffect("ドドド", SourceLanguage.JA))
        assertFalse(OfflineText.isSoundEffect("He said 「ドドド」 and walked away from here", SourceLanguage.EN))
        assertFalse(OfflineText.keep("discord.gg/abc", SourceLanguage.EN))
        assertTrue(OfflineText.keep("Hello there!", SourceLanguage.EN))
    }

    @Test
    fun translationIsTidied() {
        assertEquals("Olá, tudo bem?", OfflineText.tidy("Olá ,  tudo bem ?", "Hi, how are you?"))
        assertEquals("Vamos!", OfflineText.tidy("Vamos,!", "Let's go,!"))
        assertEquals("¿Qué?", OfflineText.tidy("¿ Qué ?", "What?"))
        assertEquals("Hi.", OfflineText.tidy("   ", "Hi."))
    }

    @Test
    fun shortPagesAreOneTile() {
        assertEquals(listOf(OverlappingTiles.Tile(0, 1400, 0, 1400)), OverlappingTiles.split(900, 1400))
    }

    @Test
    fun tallPagesOverlapAndEveryRowHasExactlyOneOwner() {
        val height = 9000
        val tiles = OverlappingTiles.split(800, height)
        assertTrue(tiles.size > 1)
        for (i in 1 until tiles.size) {
            // Uma linha de até 160 px cortada na borda de uma faixa cabe inteira na vizinha.
            assertTrue(tiles[i - 1].bottom - tiles[i].top >= 2 * 160)
        }
        for (y in 0 until height) assertEquals(1, tiles.count { it.owns(y) }, "linha $y")
        tiles.forEach { assertTrue(it.top <= it.ownTop && it.ownBottom <= it.bottom) }
        assertEquals(0, tiles.first().top)
        assertEquals(height, tiles.last().bottom)
    }
}
