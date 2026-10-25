package app.mangalate.local

import app.mangalate.ui.MangalateWhatsNew
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class WhatsNewContentTest {
    private val releases = MangalateWhatsNew.releases

    @Test
    fun `every release has short public items and a unique version`() {
        assertTrue(releases.isNotEmpty())
        // Only the newest entry may still be waiting for its version number.
        assertTrue(releases.drop(1).all { it.version != null })
        assertEquals(releases.size, releases.map { it.version }.distinct().size)
        for (item in releases.flatMap { it.items }) {
            assertTrue(item.isNotBlank())
            assertTrue(item.length <= 200, "Too long for the update notice: $item")
            for (jargon in listOf("OCR", "regioes.json", "máscara", "detector", "mihon.app")) {
                assertFalse(item.contains(jargon), "Technical word in a public note: $item")
            }
        }
    }

    @Test
    fun `a fresh install shows nothing and an update from before the notice shows the newest release`() {
        assertEquals(emptyList<String>(), MangalateWhatsNew.unseen(null, freshInstall = true))
        assertEquals(releases.first().items, MangalateWhatsNew.unseen(null, freshInstall = false))
    }

    @Test
    fun `only items not seen yet are shown after an update`() {
        val all = MangalateWhatsNew.allKeys()
        assertEquals(emptyList<String>(), MangalateWhatsNew.unseen(all, freshInstall = false))
        val newest = releases.first().items
        val withoutLast = MangalateWhatsNew.allKeys().filterNot { it == newest.last().hashCode().toString() }.toSet()
        assertEquals(listOf(newest.last()), MangalateWhatsNew.unseen(withoutLast, freshInstall = false))
    }
}
