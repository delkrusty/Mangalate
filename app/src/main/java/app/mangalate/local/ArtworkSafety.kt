package app.mangalate.local

import java.util.Locale
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min

enum class TextKind {
    SPEECH, NARRATION, SOUND_EFFECT, UNKNOWN;

    companion object {
        fun parse(value: String?) = when (value?.lowercase(Locale.ROOT)) {
            "speech", "dialogue" -> SPEECH
            "narration", "caption" -> NARRATION
            "sfx", "sound_effect", "onomatopoeia" -> SOUND_EFFECT
            else -> UNKNOWN
        }
    }
}

internal object SoundEffectPolicy {
    private val latinSounds = setOf(
        "clap", "clapclap", "clop", "clopclop", "tap", "taptap", "knock", "knockknock",
        "bam", "bang", "boom", "thud", "thump", "slam", "swoosh", "whoosh", "swish",
        "click", "clack", "crack", "crash", "drip", "splash", "snap", "rustle", "creak",
        "beep", "buzz", "bzz", "vroom", "gasp", "gulp",
    )
    private val japaneseSounds = setOf(
        "ド", "ドッ", "ドン", "ドーン", "バン", "バタン", "パチ", "パチッ", "パチパチ", "パン", "ガン",
        "ガタン", "ガチャ", "カチ", "ザワ", "ザワザワ", "ゴゴゴ", "ゴゴゴゴ",
        "トン", "トントン", "ドキ", "ドキドキ", "ピン", "キラ", "キラキラ",
    )

    fun looksLikeEffect(text: String): Boolean {
        val normalized = text.filter { it.isLetter() }.lowercase(Locale.ROOT)
        if (normalized in latinSounds || normalized in japaneseSounds) return true
        val words = text.lowercase(Locale.ROOT).split(Regex("[^\\p{L}]+")).filter { it.isNotBlank() }
        return words.isNotEmpty() && words.all { it in latinSounds || it in japaneseSounds }
    }

    fun shouldTranslate(kind: TextKind, original: String, enabled: Boolean): Boolean =
        enabled || (kind != TextKind.SOUND_EFFECT && !looksLikeEffect(original))
}

/** Rejeita balões cujo tamanho não combina com o texto ou com a página. */
internal object BubbleBoundsGuard {
    fun accepts(text: BubbleGeometry.Box, bubble: BubbleGeometry.Box, pageWidth: Int, pageHeight: Int): Boolean {
        if (text.width <= 0 || text.height <= 0 || bubble.width <= 0 || bubble.height <= 0) return false
        if (bubble.width > text.width * 4.5 + 12 || bubble.height > text.height * 4.5 + 12) return false
        val area = bubble.width.toDouble() * bubble.height
        if (area > text.width.toDouble() * text.height * 20) return false
        if (area > pageWidth.toDouble() * pageHeight * 0.22) return false
        if (bubble.width > pageWidth * 0.60 && bubble.height > pageHeight * 0.32) return false
        val overlapW = max(0, min(text.right, bubble.right) - max(text.left, bubble.left))
        val overlapH = max(0, min(text.bottom, bubble.bottom) - max(text.top, bubble.top))
        return overlapW.toDouble() * overlapH >= text.width.toDouble() * text.height * 0.65
    }
}

/**
 * Máscara seletiva para texto sem balão confirmado. Rejeita componentes grandes
 * ou cortados na borda (rostos, cabelos, roupas, molduras). Nunca pinta um retângulo.
 */
internal object GlyphCleaner {
    data class Result(val mask: BooleanArray, val background: Int, val bounds: BubbleGeometry.Box)

    fun identify(
        pixels: IntArray,
        width: Int,
        height: Int,
        boxes: List<BubbleGeometry.Box>,
        pageWidth: Int,
    ): Result? {
        if (boxes.isEmpty()) return null
        val allowed = BooleanArray(pixels.size)
        for (box in boxes) {
            val left = (box.left - 2).coerceIn(0, width - 1)
            val top = (box.top - 2).coerceIn(0, height - 1)
            val right = (box.right + 2).coerceIn(left + 1, width)
            val bottom = (box.bottom + 2).coerceIn(top + 1, height)
            for (y in top until bottom) for (x in left until right) allowed[y * width + x] = true
        }
        val samples = pixels.indices.filter { allowed[it] }.map { pixels[it] }
        if (samples.isEmpty()) return null
        val histogram = samples.groupBy { color ->
            (((color ushr 16) and 255) / 24 shl 8) or
                (((color ushr 8) and 255) / 24 shl 4) or ((color and 255) / 24)
        }
        val dominant = histogram.values.maxByOrNull { it.size } ?: return null
        if (dominant.size < samples.size * 0.52) return null
        val mid = dominant.size / 2
        val red = dominant.map { (it ushr 16) and 255 }.sorted()[mid]
        val green = dominant.map { (it ushr 8) and 255 }.sorted()[mid]
        val blue = dominant.map { it and 255 }.sorted()[mid]
        val bg = (255 shl 24) or (red shl 16) or (green shl 8) or blue
        val brightness = (red * 299 + green * 587 + blue * 114) / 1000
        if (brightness in 75..179) return null
        val ink = BooleanArray(pixels.size) { allowed[it] && difference(pixels[it], bg) > 65 }
        val visited = BooleanArray(pixels.size)
        val mask = BooleanArray(pixels.size)
        val queue = IntArray(pixels.size)
        val maxGlyph = max(4, (pageWidth * 0.05).toInt())
        var count = 0
        var minX = width
        var minY = height
        var maxX = 0
        var maxY = 0
        for (seed in ink.indices) {
            if (!ink[seed] || visited[seed]) continue
            var head = 0
            var tail = 1
            queue[0] = seed
            visited[seed] = true
            var left = width
            var top = height
            var right = 0
            var bottom = 0
            var cut = false
            while (head < tail) {
                val i = queue[head++]
                val x = i % width
                val y = i / width
                left = min(left, x)
                right = max(right, x)
                top = min(top, y)
                bottom = max(bottom, y)
                for (dy in -1..1) for (dx in -1..1) {
                    val xx = x + dx
                    val yy = y + dy
                    if (xx !in 0 until width || yy !in 0 until height) {
                        cut = true
                        continue
                    }
                    val j = yy * width + xx
                    if (!allowed[j]) cut = true
                    if (ink[j] && !visited[j]) {
                        visited[j] = true
                        queue[tail++] = j
                    }
                }
            }
            val componentW = right - left + 1
            val componentH = bottom - top + 1
            if (cut || componentH > maxGlyph || componentW > maxGlyph * 2 || tail > maxGlyph * maxGlyph * 1.4) continue
            for (q in 0 until tail) mask[queue[q]] = true
            count += tail
            minX = min(minX, left)
            minY = min(minY, top)
            maxX = max(maxX, right)
            maxY = max(maxY, bottom)
        }
        if (count == 0 || count > samples.size * 0.35) return null
        val expanded = mask.copyOf()
        for (i in mask.indices) if (mask[i]) {
            val x = i % width
            val y = i / width
            for (dy in -1..1) for (dx in -1..1) {
                val xx = x + dx
                val yy = y + dy
                if (xx !in 0 until width || yy !in 0 until height) continue
                val j = yy * width + xx
                // Não invade um componente de arte rejeitado, mesmo durante a dilatação.
                if (allowed[j] && (!ink[j] || mask[j])) expanded[j] = true
            }
        }
        return Result(expanded, bg, BubbleGeometry.Box(minX, minY, maxX + 1, maxY + 1))
    }

    private fun difference(a: Int, b: Int) = max(
        abs(((a ushr 16) and 255) - ((b ushr 16) and 255)),
        max(abs(((a ushr 8) and 255) - ((b ushr 8) and 255)), abs((a and 255) - (b and 255))),
    )
}
