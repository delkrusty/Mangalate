package app.mangalate.local

import app.mangalate.translate.SourceLanguage

/**
 * Regras de texto do modo no celular, as mesmas que o servidor já usa:
 * o que fica no original e a arrumação da tradução.
 */
object OfflineText {

    /** Créditos e marcas d'água de scan: ficam como estão, sem tradução. */
    private val credit = Regex(
        "[™©®]|\\b\\w{3,}scans?\\b|discord|patreon|ko-?fi|www\\.|\\.(?:com|net|org|gg)\\b" +
            "|by\\s*:|\\b(?:tl|pr|ts|qc|raws?|editor|proofreader|typesetter|translator|cleaner|redrawer)\\s*:" +
            "|\\btapa\\w*\\W{0,3}origin" +
            "|read (?:the |this |more |latest )?chapters? (?:at|on)|support us|our (?:web)?site",
        RegexOption.IGNORE_CASE,
    )
    private val cjk = Regex("[\\u3040-\\u30ff\\u3400-\\u9fff\\uac00-\\ud7af]")

    fun isCredit(text: String): Boolean = credit.containsMatchIn(text)

    /** Onomatopeia em japonês/coreano/chinês que sobrou num scan em inglês. */
    fun isSoundEffect(text: String, source: SourceLanguage): Boolean =
        source == SourceLanguage.EN && cjk.containsMatchIn(text) && text.count { it in 'a'..'z' || it in 'A'..'Z' } < 12

    fun keep(text: String, source: SourceLanguage): Boolean = !isCredit(text) && !isSoundEffect(text, source)

    /** Espaços e pontuação da tradução; resposta vazia fica com o original. */
    fun tidy(translation: String, original: String): String {
        val text = translation
            .replace(Regex("\\s+"), " ")
            .replace(Regex("(?<!-)--(?!-)"), "—")
            .replace(Regex(" +([,.!?;:…])"), "$1")
            .replace(Regex("[,;:]+(?=[.!?…])"), "")
            .replace(Regex("([¿¡]) +"), "$1")
            .trim()
        return text.ifEmpty { original }
    }
}

/**
 * Faixas de uma página alta (webtoon) com sobreposição: uma linha cortada na borda
 * de uma faixa aparece inteira na vizinha. Cada linha vale só na faixa "dona" do
 * seu centro, então nada é lido duas vezes.
 */
object OverlappingTiles {
    data class Tile(val top: Int, val bottom: Int, val ownTop: Int, val ownBottom: Int) {
        val height get() = bottom - top
        fun owns(centerY: Int) = centerY in ownTop until ownBottom
    }

    fun split(width: Int, height: Int): List<Tile> {
        val maxH = maxOf((width * 1.6f).toInt(), 1600)
        if (height <= maxH * 1.15f) return listOf(Tile(0, height, 0, height))
        val overlap = maxOf(160, maxH / 8)
        val count = (height + maxH - 1) / maxH
        val h = (height + count - 1) / count
        return (0 until count).map { i ->
            val ownTop = i * h
            val ownBottom = minOf(height, (i + 1) * h)
            Tile(maxOf(0, ownTop - overlap), minOf(height, ownBottom + overlap), ownTop, ownBottom)
        }
    }
}
