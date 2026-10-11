package app.mangalate.local

import android.graphics.Bitmap
import android.graphics.Rect
import app.mangalate.translate.SourceLanguage
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.text.TextRecognition
import com.google.mlkit.vision.text.TextRecognizer
import com.google.mlkit.vision.text.chinese.ChineseTextRecognizerOptions
import com.google.mlkit.vision.text.japanese.JapaneseTextRecognizerOptions
import com.google.mlkit.vision.text.korean.KoreanTextRecognizerOptions
import com.google.mlkit.vision.text.latin.TextRecognizerOptions
import kotlin.math.max
import kotlin.math.min

/**
 * OCR no próprio celular com ML Kit. Agrupa as linhas em blocos de fala.
 */
object OnDeviceOcr {

    private val recognizers = HashMap<SourceLanguage, TextRecognizer>()
    private val mutex = kotlinx.coroutines.sync.Mutex()

    private fun recognizer(lang: SourceLanguage): TextRecognizer = synchronized(recognizers) {
        recognizers.getOrPut(lang) {
            when (lang) {
                SourceLanguage.JA -> TextRecognition.getClient(JapaneseTextRecognizerOptions.Builder().build())
                SourceLanguage.KO -> TextRecognition.getClient(KoreanTextRecognizerOptions.Builder().build())
                SourceLanguage.ZH -> TextRecognition.getClient(ChineseTextRecognizerOptions.Builder().build())
                SourceLanguage.EN -> TextRecognition.getClient(TextRecognizerOptions.DEFAULT_OPTIONS)
            }
        }
    }

    private class Line(val rect: Rect, val text: String)

    suspend fun detect(page: Bitmap, lang: SourceLanguage): List<TextRegion> {
        mutex.lock()
        try {
            return detectLocked(page, lang)
        } finally {
            mutex.unlock()
        }
    }

    /** Confere o mesmo cliente de OCR, com uma imagem sintética que não sai do celular. */
    suspend fun verify(lang: SourceLanguage) {
        val page = Bitmap.createBitmap(1000, 300, Bitmap.Config.ARGB_8888)
        try {
            val canvas = android.graphics.Canvas(page)
            canvas.drawColor(android.graphics.Color.WHITE)
            val paint = android.graphics.Paint(android.graphics.Paint.ANTI_ALIAS_FLAG).apply {
                color = android.graphics.Color.BLACK
                textSize = 70f
            }
            canvas.drawText("HELLO WORLD", 80f, 160f, paint)
            if (detect(page, lang).isEmpty()) throw FriendlyException("OCR não reconheceu o texto de teste. Reinicie o app e tente novamente.")
        } finally {
            page.recycle()
        }
    }

    private suspend fun detectLocked(page: Bitmap, lang: SourceLanguage): List<TextRegion> {
        val lines = ArrayList<Line>()
        for (tile in PageTiles.split(page.width, page.height)) {
            val bmp = if (tile.top == 0 && tile.height() == page.height) {
                page
            } else {
                Bitmap.createBitmap(page, 0, tile.top, page.width, tile.height())
            }
            val result = recognizer(lang).process(InputImage.fromBitmap(bmp, 0)).awaitTask()
            for (block in result.textBlocks) {
                for (line in block.lines) {
                    val r = line.boundingBox ?: continue
                    r.offset(0, tile.top)
                    lines += Line(Rect(r), line.text)
                }
            }
            if (bmp !== page) bmp.recycle()
        }
        return group(lines, lang)
    }

    /**
     * Junta linhas próximas no mesmo bloco (um balão costuma ter várias linhas).
     */
    private fun group(lines: List<Line>, lang: SourceLanguage): List<TextRegion> {
        val useful = lines.filter { l -> l.text.count { it.isLetter() } >= 1 && l.rect.width() > 2 && l.rect.height() > 2 }
        if (useful.isEmpty()) return emptyList()
        val cjk = lang != SourceLanguage.EN && lang != SourceLanguage.KO
        val parent = IntArray(useful.size) { it }
        fun find(i: Int): Int {
            var x = i
            while (parent[x] != x) {
                parent[x] = parent[parent[x]]
                x = parent[x]
            }
            return x
        }
        for (i in useful.indices) {
            for (j in i + 1 until useful.size) {
                if (close(useful[i].rect, useful[j].rect)) parent[find(i)] = find(j)
            }
        }
        val groups = useful.indices.groupBy { find(it) }.values
        return groups.map { idx ->
            val members = idx.map { useful[it] }
            val rect = Rect(members[0].rect)
            members.forEach { rect.union(it.rect) }
            val vertical = cjk && members.count { it.rect.height() > it.rect.width() * 1.3f } * 2 > members.size
            val ordered = if (vertical) {
                members.sortedByDescending { it.rect.centerX() }
            } else {
                members.sortedBy { it.rect.top }
            }
            val sep = if (cjk) "" else " "
            TextRegion(
                rect = rect,
                original = ordered.joinToString(sep) { it.text.trim() }.let(::normalizeCaps),
                vertical = vertical,
            )
        }.filter { it.original.isNotBlank() }
    }

    private fun close(a: Rect, b: Rect): Boolean {
        val unit = max(8, min(min(a.width(), a.height()), min(b.width(), b.height())))
        val gap = (unit * 0.9f).toInt()
        val ea = Rect(a.left - gap, a.top - gap, a.right + gap, a.bottom + gap)
        if (!Rect.intersects(ea, b)) return false
        // Evita juntar blocos lado a lado de tamanhos muito diferentes (balões vizinhos)
        val ha = min(a.width(), a.height()).toFloat()
        val hb = min(b.width(), b.height()).toFloat()
        return max(ha, hb) / max(1f, min(ha, hb)) < 2.2f
    }

    /** "WHAT ARE YOU DOING?!" -> "What are you doing?!" (traduz melhor). */
    private fun normalizeCaps(text: String): String {
        val letters = text.filter { it.isLetter() && it.code < 0x3000 }
        if (letters.length < 4 || letters.any { it.isLowerCase() }) return text
        val lower = text.lowercase()
        val sb = StringBuilder(lower.length)
        var capNext = true
        for (c in lower) {
            if (capNext && c.isLetter()) {
                sb.append(c.uppercaseChar())
                capNext = false
            } else {
                sb.append(c)
            }
            if (c == '.' || c == '!' || c == '?') capNext = true
        }
        return sb.toString().replace(Regex("\\bi\\b"), "I")
    }
}

/**
 * Divide páginas muito altas (webtoon) em faixas para OCR/IA.
 */
object PageTiles {
    fun split(width: Int, height: Int): List<Rect> {
        val maxH = max((width * 1.6f).toInt(), 1600)
        if (height <= maxH * 1.15f) return listOf(Rect(0, 0, width, height))
        val count = (height + maxH - 1) / maxH
        val h = (height + count - 1) / count
        return (0 until count).map { i -> Rect(0, i * h, width, min(height, (i + 1) * h)) }
    }
}
