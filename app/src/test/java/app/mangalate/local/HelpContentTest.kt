package app.mangalate.local

import app.mangalate.ui.MangalateGuides
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class HelpContentTest {
    @Test
    fun `manual covers use translation offline and troubleshooting`() {
        val content = MangalateGuides.help.joinToString(" ") { it.title + " " + it.text }
        for (topic in listOf("BYOK", "Docker", "offline", "balão", "biblioteca", "chave", "Downloads", "backup")) {
            assertTrue(content.contains(topic, ignoreCase = true), "Missing help topic $topic")
        }
    }

    @Test
    fun `embedded guides do not link to Mihon support`() {
        val all = MangalateGuides.help + MangalateGuides.privacy + MangalateGuides.changes
        for (article in all) {
            assertFalse(article.text.contains("mihon.app"))
            assertFalse(article.text.contains("mihonapp"))
            assertTrue(article.title.isNotBlank())
            assertTrue(article.text.isNotBlank())
        }
    }

    @Test
    fun `help article keys are unique`() {
        assertEquals(MangalateGuides.help.size, MangalateGuides.help.map { it.title }.distinct().size)
    }
}
