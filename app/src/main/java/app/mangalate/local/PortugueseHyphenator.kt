package app.mangalate.local

import java.text.Normalizer
import java.util.Locale

/**
 * Algoritmo de padrões de Liang. O dicionário DivSilab/LibreOffice fica nos assets,
 * separado do código, com autoria e licença preservadas.
 */
internal class PortugueseHyphenator(patterns: Sequence<String>) {
    private class Node {
        val children = HashMap<Char, Node>()
        var weights: IntArray? = null
    }

    private val root = Node()

    init {
        for (raw in patterns) {
            val pattern = raw.trim()
            if (pattern.isEmpty() || pattern == "UTF-8" || pattern.startsWith('%')) continue
            val letters = StringBuilder()
            val weights = ArrayList<Int>().apply { add(0) }
            for (c in pattern) {
                if (c in '0'..'9') {
                    weights[weights.lastIndex] = c - '0'
                } else {
                    letters.append(c)
                    weights.add(0)
                }
            }
            var node = root
            for (c in letters) node = node.children.getOrPut(c) { Node() }
            node.weights = weights.toIntArray()
        }
    }

    /** Pontos legais de translineação; evita deixar apenas uma letra de cada lado. */
    fun breaks(word: String): List<Int> {
        val normalized = Normalizer.normalize(word, Normalizer.Form.NFC).lowercase(Locale.forLanguageTag("pt-BR"))
        if (normalized != word.lowercase(Locale.forLanguageTag("pt-BR"))) return emptyList()
        if (word.length < 5 || word.any { !it.isLetter() }) return emptyList()
        val padded = ".$normalized."
        val weights = IntArray(padded.length + 1)
        for (start in padded.indices) {
            var node = root
            for (end in start until padded.length) {
                node = node.children[padded[end]] ?: break
                node.weights?.forEachIndexed { i, weight ->
                    weights[start + i] = maxOf(weights[start + i], weight)
                }
            }
        }
        return (2..word.length - 2).filter { weights[it + 1] % 2 == 1 }
    }
}
