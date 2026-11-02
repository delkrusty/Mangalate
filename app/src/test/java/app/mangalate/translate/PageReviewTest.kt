package app.mangalate.translate

import app.mangalate.ui.reviewText
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

/** O selo de revisão do leitor, a partir dos cabeçalhos X-Mangalate-Preserved e X-Mangalate-Over-Art. */
class PageReviewTest {

    @Test
    fun readsTheServerCounts() {
        assertEquals(PageReview(2, 0), PageReview.of("2", "0"))
        assertFalse(PageReview.of("0", "0")!!.needsLook)
        assertTrue(PageReview.of("0", "1")!!.needsLook)
    }

    @Test
    fun anOlderServerWithoutCountsShowsNoBadge() {
        assertNull(PageReview.of(null, null))
        assertNull(PageReview.of("x; evil", "0"))
        assertNull(PageReview.of("-1", "0"))
        assertNull(PageReview.of("2", null))
    }

    @Test
    fun badgeText() {
        assertEquals("1 fala ficou no original · tocar para comparar", reviewText(PageReview(1, 0)))
        assertEquals("3 falas ficaram no original · tocar para comparar", reviewText(PageReview(3, 0)))
        assertEquals(
            "2 falas ficaram no original · fala sobre o desenho · tocar para comparar",
            reviewText(PageReview(2, 1)),
        )
        assertEquals("fala sobre o desenho · tocar para comparar", reviewText(PageReview(0, 4)))
    }
}
