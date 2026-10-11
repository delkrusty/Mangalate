package app.mangalate.local

/**
 * Decide as quebras antes de entregar o texto ao Android. Nunca usa um corte de
 * emergência no meio da palavra: reduzimos a fonte se nenhuma quebra legal couber.
 */
internal object BubbleTextWrapper {
    fun wrap(
        text: String,
        width: Float,
        measure: (String) -> Float,
        breaks: (String) -> List<Int>,
    ): List<String>? {
        if (width <= 0f) return null
        val words = text.replace("\u00AD", "").trim().split(Regex("\\s+")).filter { it.isNotEmpty() }
        val lines = ArrayList<String>()
        var current = ""
        for (rawWord in words) {
            var word = rawWord
            val candidate = if (current.isEmpty()) word else "$current $word"
            if (measure(candidate) <= width) {
                current = candidate
                continue
            }
            if (current.isNotEmpty()) {
                lines += current
                current = ""
            }
            while (measure(word) > width) {
                val start = word.indexOfFirst { it.isLetter() }
                val end = word.indexOfLast { it.isLetter() } + 1
                if (start < 0 || end <= start) return null
                val core = word.substring(start, end)
                val cut = breaks(core).asReversed().firstOrNull { point ->
                    measure(word.substring(0, start + point) + "-") <= width
                } ?: return null
                lines += word.substring(0, start + cut) + "-"
                word = word.substring(start + cut)
            }
            current = word
        }
        if (current.isNotEmpty()) lines += current

        // Evita uma última linha com uma palavrinha isolada quando há espaço para equilibrar.
        if (lines.size > 1 && !lines[lines.lastIndex - 1].endsWith('-')) {
            val previous = lines[lines.lastIndex - 1]
            val split = previous.lastIndexOf(' ')
            if (split > 0) {
                val moved = previous.substring(split + 1) + " " + lines.last()
                val remaining = previous.substring(0, split)
                if (measure(moved) <= width &&
                    kotlin.math.abs(measure(remaining) - measure(moved)) <
                    kotlin.math.abs(measure(previous) - measure(lines.last()))
                ) {
                    lines[lines.lastIndex - 1] = remaining
                    lines[lines.lastIndex] = moved
                }
            }
        }
        return lines
    }
}
