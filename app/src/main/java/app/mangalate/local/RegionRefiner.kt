package app.mangalate.local

import android.graphics.Rect
import java.util.Locale

/**
 * Confirma a caixa enviada pela IA com o texto lido localmente. Em vez de confiar
 * em uma caixa grande que inclui um rosto, usa as linhas reais quando há correspondência.
 */
internal object RegionRefiner {
    fun refine(regions: List<TextRegion>, ocr: List<TextRegion>): List<TextRegion> = regions.map { region ->
        val a = normalize(region.original)
        if (a.length < 6) return@map region
        val matched = ocr.mapNotNull { candidate ->
            val b = normalize(candidate.original)
            if (b.length < 6) return@mapNotNull null
            val score = similarity(a, b)
            if (score < 0.72) return@mapNotNull null
            candidate to score
        }.maxByOrNull { (candidate, score) ->
            val distance = kotlin.math.abs(candidate.rect.centerX() - region.rect.centerX()) +
                kotlin.math.abs(candidate.rect.centerY() - region.rect.centerY())
            score - distance * 0.0001
        }?.first ?: return@map region
        region.copy(rect = Rect(matched.rect), glyphBoxes = matched.glyphBoxes)
    }

    private fun normalize(s: String) = s.filter { it.isLetterOrDigit() }.lowercase(Locale.ROOT)

    private fun similarity(a: String, b: String): Double {
        if (a == b) return 1.0
        if (a.length > 1200 || b.length > 1200) return 0.0
        var previous = IntArray(b.length + 1) { it }
        for (i in a.indices) {
            val next = IntArray(b.length + 1)
            next[0] = i + 1
            for (j in b.indices) {
                next[j + 1] = minOf(next[j] + 1, previous[j + 1] + 1, previous[j] + if (a[i] == b[j]) 0 else 1)
            }
            previous = next
        }
        return 1.0 - previous[b.length].toDouble() / maxOf(a.length, b.length)
    }
}
