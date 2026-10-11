package app.mangalate.local

import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min

/**
 * Segmenta um balão de fundo uniforme e contorno fechado. Não usa a caixa do OCR
 * como máscara de limpeza: ela serve somente para encontrar uma semente interna.
 *
 * Fecha falhas pequenas no contorno e preenche as ilhas internas (letras que o OCR
 * não leu também). Vazamentos até a borda ou interiores muito texturizados são
 * rejeitados, mantendo o fallback conservador.
 */
internal object BubbleSegmenter {
    data class Result(
        val interior: BooleanArray,
        val background: Int,
        val bounds: BubbleGeometry.Box,
    )

    fun identify(
        pixels: IntArray,
        width: Int,
        height: Int,
        text: BubbleGeometry.Box,
        closureRadius: Int = 1,
    ): Result? {
        require(pixels.size == width * height)
        if (width < 12 || height < 12 || text.width < 2 || text.height < 2) return null
        val x0 = text.left.coerceIn(1, width - 2)
        val y0 = text.top.coerceIn(1, height - 2)
        val x1 = text.right.coerceIn(x0 + 1, width - 1)
        val y1 = text.bottom.coerceIn(y0 + 1, height - 1)

        // Cor dominante nas proximidades do texto; letras pretas não dominam o branco.
        val buckets = HashMap<Int, MutableList<Int>>()
        val pad = max(3, min(text.width, text.height) / 8)
        val step = max(1, max(text.width, text.height) / 100)
        for (y in max(1, y0 - pad) until min(height - 1, y1 + pad) step step) {
            for (x in max(1, x0 - pad) until min(width - 1, x1 + pad) step step) {
                val color = pixels[y * width + x]
                val red = (color ushr 16) and 255
                val green = (color ushr 8) and 255
                val blue = color and 255
                val key = (red / 24 shl 8) or (green / 24 shl 4) or (blue / 24)
                buckets.getOrPut(key) { ArrayList() }.add(color)
            }
        }
        val dominant = buckets.values.maxByOrNull { it.size } ?: return null
        val sampleCount = buckets.values.sumOf { it.size }
        if (dominant.size < sampleCount * 0.50) return null
        val background = median(dominant)
        // Tons médios e retículas pedem reconstrução, não um preenchimento liso.
        val brightness = luma(background)
        if (brightness in 75..179) return null
        val open = BooleanArray(pixels.size) { distance(pixels[it], background) < 55 }
        val radius = closureRadius.coerceIn(1, 2)
        val closed = closeContour(open, width, height, radius)

        val cx = (x0 + x1) / 2
        val cy = (y0 + y1) / 2
        var seed = -1
        var bestDistance = Int.MAX_VALUE
        for (y in y0 until y1) for (x in x0 until x1) {
            val i = y * width + x
            if (!closed[i]) continue
            val distance = abs(x - cx) + abs(y - cy)
            if (distance < bestDistance) {
                seed = i
                bestDistance = distance
            }
        }
        if (seed < 0) return null

        val interior = BooleanArray(pixels.size)
        val queue = IntArray(pixels.size)
        var head = 0
        var tail = 1
        queue[0] = seed
        interior[seed] = true
        var left = width
        var right = 0
        var top = height
        var bottom = 0
        fun visit(i: Int) {
            if (!interior[i] && closed[i]) {
                interior[i] = true
                queue[tail++] = i
            }
        }
        while (head < tail) {
            val i = queue[head++]
            val x = i % width
            val y = i / width
            // Inclui também bordas de página: não apagamos uma região sem contorno completo.
            if (x <= radius || x >= width - 1 - radius || y <= radius || y >= height - 1 - radius) return null
            left = min(left, x)
            right = max(right, x)
            top = min(top, y)
            bottom = max(bottom, y)
            visit(i - 1)
            visit(i + 1)
            visit(i - width)
            visit(i + width)
        }
        val textArea = (x1 - x0).toLong() * (y1 - y0)
        if (tail < textArea * 0.30 || tail > pixels.size * 0.60 || tail > textArea * 18) return null
        if (right - left < text.width * 0.55 || bottom - top < text.height * 0.55) return null
        if (right - left > text.width * 4.5 + 12 || bottom - top > text.height * 4.5 + 12) return null

        // O complemento conectado ao exterior contém contorno e arte. Apenas
        // buracos inteiramente dentro do balão (letras) são incorporados à máscara.
        val exterior = BooleanArray(pixels.size)
        head = 0
        tail = 0
        fun exteriorVisit(i: Int) {
            if (!interior[i] && !exterior[i]) {
                exterior[i] = true
                queue[tail++] = i
            }
        }
        for (x in 0 until width) {
            exteriorVisit(x)
            exteriorVisit((height - 1) * width + x)
        }
        for (y in 1 until height - 1) {
            exteriorVisit(y * width)
            exteriorVisit(y * width + width - 1)
        }
        while (head < tail) {
            val i = queue[head++]
            val x = i % width
            val y = i / width
            if (x > 0) exteriorVisit(i - 1)
            if (x < width - 1) exteriorVisit(i + 1)
            if (y > 0) exteriorVisit(i - width)
            if (y < height - 1) exteriorVisit(i + width)
        }
        for (y in top..bottom) for (x in left..right) {
            val i = y * width + x
            if (!exterior[i]) {
                interior[i] = true
            }
        }
        // Letras encostadas no contorno podem ficar conectadas ao "exterior" preto.
        // Fechamos apenas os intervalos entre pixels internos já confirmados, pelas
        // linhas e colunas do balão. Não usamos o retângulo de OCR nem o retângulo
        // externo do balão como área de pintura.
        val silhouette = interior.copyOf()
        for (y in top..bottom) {
            var first = -1
            var last = -1
            for (x in left..right) if (interior[y * width + x]) {
                if (first < 0) first = x
                last = x
            }
            if (first >= 0) for (x in first..last) silhouette[y * width + x] = true
        }
        for (x in left..right) {
            var first = -1
            var last = -1
            for (y in top..bottom) if (interior[y * width + x]) {
                if (first < 0) first = y
                last = y
            }
            if (first >= 0) for (y in first..last) silhouette[y * width + x] = true
        }
        var filled = 0
        var uniform = 0
        for (i in silhouette.indices) if (silhouette[i]) {
            filled++
            if (distance(pixels[i], background) < 40) uniform++
        }
        if (filled == 0 || uniform < filled * 0.78 || filled > textArea * 20 || filled > pixels.size * 0.65) return null
        return Result(silhouette, background, BubbleGeometry.Box(left, top, right + 1, bottom + 1))
    }

    /** Fechamento morfológico 3x3 do contorno (abertura da região clara). */
    private fun closeContour(open: BooleanArray, width: Int, height: Int, radius: Int): BooleanArray {
        val eroded = BooleanArray(open.size)
        for (y in radius until height - radius) for (x in radius until width - radius) {
            var allOpen = true
            loop@ for (dy in -radius..radius) for (dx in -radius..radius) {
                if (!open[(y + dy) * width + x + dx]) {
                    allOpen = false
                    break@loop
                }
            }
            eroded[y * width + x] = allOpen
        }
        val restored = BooleanArray(open.size)
        for (y in radius until height - radius) for (x in radius until width - radius) {
            var anyOpen = false
            loop@ for (dy in -radius..radius) for (dx in -radius..radius) {
                if (eroded[(y + dy) * width + x + dx]) {
                    anyOpen = true
                    break@loop
                }
            }
            restored[y * width + x] = anyOpen && open[y * width + x]
        }
        return restored
    }

    private fun distance(a: Int, b: Int) = max(
        abs(((a ushr 16) and 255) - ((b ushr 16) and 255)),
        max(abs(((a ushr 8) and 255) - ((b ushr 8) and 255)), abs((a and 255) - (b and 255))),
    )

    private fun luma(c: Int) =
        (((c ushr 16) and 255) * 299 + ((c ushr 8) and 255) * 587 + (c and 255) * 114) / 1000

    private fun median(colors: List<Int>): Int {
        val index = colors.size / 2
        val r = colors.map { (it ushr 16) and 255 }.sorted()[index]
        val g = colors.map { (it ushr 8) and 255 }.sorted()[index]
        val b = colors.map { it and 255 }.sorted()[index]
        return (255 shl 24) or (r shl 16) or (g shl 8) or b
    }
}
