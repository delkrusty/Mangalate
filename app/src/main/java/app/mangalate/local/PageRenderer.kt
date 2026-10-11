package app.mangalate.local

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Rect
import android.graphics.RectF
import android.graphics.Typeface
import android.text.Layout
import android.text.StaticLayout
import android.text.TextPaint
import androidx.core.content.res.ResourcesCompat
import app.mangalate.translate.MangalateSettings
import eu.kanade.tachiyomi.R
import java.util.ArrayDeque
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

/**
 * Limpa o texto original e diagrama a tradução no lugar.
 *
 * Balões lisos: a cor do fundo é estimada pela borda da área do texto, os traços das letras
 * são detectados pela diferença de cor e repintados; um preenchimento por inundação encontra
 * o interior do balão para descobrir quanto espaço há para o texto traduzido.
 *
 * Texto sobre a arte: a área é reconstruída de fora para dentro (difusão a partir das bordas)
 * e o texto é desenhado com contorno para ficar legível.
 */
object PageRenderer {

    private class Plan(
        val region: TextRegion,
        val layout: RectF,
        val textColor: Int,
        val strokeColor: Int?,
    )

    @Volatile
    private var typeface: Typeface? = null

    private fun typeface(context: Context): Typeface = typeface ?: run {
        val tf = runCatching { ResourcesCompat.getFont(context, R.font.mangalate_comic_bold) }.getOrNull()
            ?: Typeface.DEFAULT_BOLD
        typeface = tf
        tf
    }

    fun render(context: Context, page: Bitmap, regions: List<TextRegion>, s: MangalateSettings) {
        val plans = ArrayList<Plan>()
        // 1) limpar tudo primeiro, para uma limpeza não apagar o texto de outro balão
        for (region in regions) {
            val plan = clean(page, region, s) ?: continue
            plans += plan
        }
        // 2) diagramar
        val canvas = Canvas(page)
        val paint = TextPaint(Paint.ANTI_ALIAS_FLAG or Paint.SUBPIXEL_TEXT_FLAG).apply {
            typeface = typeface(context)
        }
        for (plan in plans) {
            var text = plan.region.translation.trim()
            if (s.uppercase) text = text.uppercase()
            if (text.isEmpty()) continue
            letter(canvas, page.width, text, plan, paint, s.fontSizeOffset)
        }
    }

    // region Limpeza

    private fun clean(page: Bitmap, region: TextRegion, s: MangalateSettings): Plan? {
        val pw = page.width
        val ph = page.height
        val r = Rect(region.rect).apply { intersect(0, 0, pw, ph) }
        if (r.width() < 3 || r.height() < 3) return null

        val grow = max(24, (max(r.width(), r.height()) * 0.85f).toInt())
        val e = Rect(r.left - grow, r.top - grow, r.right + grow, r.bottom + grow).apply { intersect(0, 0, pw, ph) }
        val ew = e.width()
        val eh = e.height()
        val px = IntArray(ew * eh)
        page.getPixels(px, 0, ew, e.left, e.top, ew, eh)

        // área do texto (com folga) em coordenadas locais
        val pad = max(3, (min(r.width(), r.height()) * 0.06f).toInt())
        val tx0 = (r.left - pad - e.left).coerceAtLeast(0)
        val ty0 = (r.top - pad - e.top).coerceAtLeast(0)
        val tx1 = (r.right + pad - e.left).coerceAtMost(ew - 1)
        val ty1 = (r.bottom + pad - e.top).coerceAtMost(eh - 1)

        // cor de fundo = mediana do anel em volta do texto
        val ring = ArrayList<Int>()
        val rx0 = (tx0 - 2).coerceAtLeast(0)
        val ry0 = (ty0 - 2).coerceAtLeast(0)
        val rx1 = (tx1 + 2).coerceAtMost(ew - 1)
        val ry1 = (ty1 + 2).coerceAtMost(eh - 1)
        for (x in rx0..rx1) {
            ring += px[ry0 * ew + x]
            ring += px[ry1 * ew + x]
        }
        for (y in ry0..ry1) {
            ring += px[y * ew + rx0]
            ring += px[y * ew + rx1]
        }
        val bg = median(ring)
        val uniform = ring.count { dist(it, bg) <= 48 }.toFloat() / ring.size
        val plain = uniform >= 0.72f && !region.overArt

        if (!plain && s.ignoreOutsideBubbles) return null

        val textColor: Int
        val strokeColor: Int?
        val layout: RectF

        if (plain) {
            // máscara dos traços das letras
            val mask = BooleanArray(ew * eh)
            for (y in ty0..ty1) {
                for (x in tx0..tx1) {
                    val i = y * ew + x
                    if (dist(px[i], bg) > 56) mask[i] = true
                }
            }
            // interior do balão por inundação
            val inside = BooleanArray(ew * eh)
            val queue = ArrayDeque<Int>()
            for (y in ty0..ty1) {
                for (x in tx0..tx1) {
                    val i = y * ew + x
                    inside[i] = true
                    queue.add(i)
                }
            }
            var touches = 0
            var minX = tx0
            var minY = ty0
            var maxX = tx1
            var maxY = ty1
            var area = 0L
            var sumX = 0L
            var sumY = 0L
            while (queue.isNotEmpty()) {
                val i = queue.poll()!!
                val x = i % ew
                val y = i / ew
                area++
                sumX += x
                sumY += y
                if (x < minX) minX = x
                if (x > maxX) maxX = x
                if (y < minY) minY = y
                if (y > maxY) maxY = y
                if (x > 0) visit(i - 1, px, inside, queue, bg)
                if (x < ew - 1) visit(i + 1, px, inside, queue, bg)
                if (y > 0) visit(i - ew, px, inside, queue, bg)
                if (y < eh - 1) visit(i + ew, px, inside, queue, bg)
            }
            if (minX == 0 && e.left > 0) touches++
            if (minY == 0 && e.top > 0) touches++
            if (maxX == ew - 1 && e.right < pw) touches++
            if (maxY == eh - 1 && e.bottom < ph) touches++
            val leaked = touches >= 2 || area > ew.toLong() * eh * 0.92

            // pinta as letras (dilatadas) com a cor do fundo
            val d = max(2, (min(r.width(), r.height()) / 45f).roundToInt()).coerceAtMost(5)
            val paintMask = BooleanArray(ew * eh)
            for (y in ty0..ty1) {
                for (x in tx0..tx1) {
                    if (!mask[y * ew + x]) continue
                    for (yy in max(0, y - d)..min(eh - 1, y + d)) {
                        for (xx in max(0, x - d)..min(ew - 1, x + d)) paintMask[yy * ew + xx] = true
                    }
                }
            }
            for (i in px.indices) {
                // não pinta sobre o contorno do balão: só dentro da área do texto ou do interior encontrado
                if (paintMask[i] && (!leaked && inside[i] || inTextBox(i, ew, tx0, ty0, tx1, ty1))) {
                    px[i] = bg
                } else if (!leaked && inside[i] && inTextBox(i, ew, tx0, ty0, tx1, ty1)) {
                    px[i] = bg
                }
            }

            layout = if (!leaked && area > 0) {
                inscribed(inside, ew, eh, (sumX / area).toInt(), (sumY / area).toInt(), minX, minY, maxX, maxY)
                    ?.let { RectF(it.left + e.left.toFloat(), it.top + e.top.toFloat(), it.right + e.left.toFloat(), it.bottom + e.top.toFloat()) }
                    ?.takeIf { it.width() * it.height() >= r.width() * r.height() * 0.7f }
                    ?: RectF(r)
            } else {
                RectF(r).apply { inset(-r.width() * 0.04f, -r.height() * 0.04f) }
            }
            val dark = luma(bg) < 110
            textColor = if (dark) Color.WHITE else Color.rgb(20, 20, 20)
            strokeColor = null
        } else {
            inpaint(px, ew, eh, tx0, ty0, tx1, ty1)
            layout = RectF(r)
            val avg = averageLuma(px, ew, tx0, ty0, tx1, ty1)
            if (avg < 110) {
                textColor = Color.WHITE
                strokeColor = Color.rgb(15, 15, 15)
            } else {
                textColor = Color.rgb(15, 15, 15)
                strokeColor = Color.WHITE
            }
        }

        page.setPixels(px, 0, ew, e.left, e.top, ew, eh)
        return Plan(region, layout, textColor, strokeColor)
    }

    private fun inTextBox(i: Int, ew: Int, x0: Int, y0: Int, x1: Int, y1: Int): Boolean {
        val x = i % ew
        val y = i / ew
        return x in x0..x1 && y in y0..y1
    }

    private fun visit(j: Int, px: IntArray, inside: BooleanArray, q: ArrayDeque<Int>, bg: Int) {
        if (inside[j]) return
        if (dist(px[j], bg) > 40) return
        inside[j] = true
        q.add(j)
    }

    /** Maior retângulo (aprox.) dentro do balão, centrado no centroide. */
    private fun inscribed(
        inside: BooleanArray,
        ew: Int,
        eh: Int,
        cx: Int,
        cy: Int,
        minX: Int,
        minY: Int,
        maxX: Int,
        maxY: Int,
    ): Rect? {
        var hw = (maxX - minX) * 0.40f
        var hh = (maxY - minY) * 0.40f
        repeat(16) {
            val rect = Rect(
                (cx - hw).toInt().coerceAtLeast(0),
                (cy - hh).toInt().coerceAtLeast(0),
                (cx + hw).toInt().coerceAtMost(ew - 1),
                (cy + hh).toInt().coerceAtMost(eh - 1),
            )
            var ok = 0
            var total = 0
            for (gy in 0..8) {
                for (gx in 0..8) {
                    val x = rect.left + rect.width() * gx / 8
                    val y = rect.top + rect.height() * gy / 8
                    total++
                    if (inside[y * ew + x]) ok++
                }
            }
            if (ok >= total * 0.95f) return rect
            hw *= 0.92f
            hh *= 0.92f
        }
        return null
    }

    /** Reconstrução por difusão: preenche a área de fora para dentro. */
    private fun inpaint(px: IntArray, ew: Int, eh: Int, x0: Int, y0: Int, x1: Int, y1: Int) {
        val w = x1 - x0 + 1
        val h = y1 - y0 + 1
        val known = BooleanArray(ew * eh) { true }
        for (y in y0..y1) for (x in x0..x1) known[y * ew + x] = false
        var remaining = w * h
        val next = ArrayList<Pair<Int, Int>>()
        var guard = 0
        while (remaining > 0 && guard++ < 4000) {
            next.clear()
            for (y in y0..y1) {
                for (x in x0..x1) {
                    val i = y * ew + x
                    if (known[i]) continue
                    var r = 0
                    var g = 0
                    var b = 0
                    var n = 0
                    for (dy in -1..1) {
                        val yy = y + dy
                        if (yy < 0 || yy >= eh) continue
                        for (dx in -1..1) {
                            val xx = x + dx
                            if (xx < 0 || xx >= ew || (dx == 0 && dy == 0)) continue
                            val j = yy * ew + xx
                            if (!known[j]) continue
                            val c = px[j]
                            r += (c shr 16) and 0xFF
                            g += (c shr 8) and 0xFF
                            b += c and 0xFF
                            n++
                        }
                    }
                    if (n >= 2 || (n == 1 && remaining < w + h)) {
                        next += i to (0xFF shl 24 or ((r / n) shl 16) or ((g / n) shl 8) or (b / n))
                    }
                }
            }
            if (next.isEmpty()) break
            for ((i, c) in next) {
                px[i] = c
                known[i] = true
            }
            remaining -= next.size
        }
    }

    // endregion

    // region Diagramação

    private fun letter(canvas: Canvas, pageWidth: Int, text: String, plan: Plan, paint: TextPaint, offset: Int) {
        val box = RectF(plan.layout)
        val minSize = max(10f, pageWidth / 95f)
        val maxSize = max(minSize, min(box.height() * 0.8f, pageWidth / 13f))

        fun fits(size: Float, width: Int): StaticLayout? {
            paint.textSize = size
            val words = text.split(' ', '\n')
            if (words.any { paint.measureText(it) > width }) return null
            val l = build(text, paint, width)
            return if (l.height <= box.height()) l else null
        }

        var lo = minSize
        var hi = maxSize
        var best: Float? = null
        var width = box.width().toInt().coerceAtLeast(8)
        repeat(14) {
            val mid = (lo + hi) / 2
            if (fits(mid, width) != null) {
                best = mid
                lo = mid
            } else {
                hi = mid
            }
        }
        if (best == null) {
            // não coube: alarga um pouco a caixa e usa o tamanho mínimo
            val extra = box.width() * 0.25f
            box.inset(-extra / 2, -box.height() * 0.1f)
            width = box.width().toInt()
            best = minSize
        }
        val size = (best!! * (1f + offset * 0.07f)).coerceIn(minSize * 0.8f, maxSize * 1.3f)
        paint.textSize = size
        val layout = build(text, paint, width)

        canvas.save()
        canvas.translate(box.left, box.centerY() - layout.height / 2f)
        if (plan.strokeColor != null) {
            paint.style = Paint.Style.STROKE
            paint.strokeJoin = Paint.Join.ROUND
            paint.strokeWidth = max(2f, size * 0.2f)
            paint.color = plan.strokeColor
            layout.draw(canvas)
        }
        paint.style = Paint.Style.FILL
        paint.color = plan.textColor
        layout.draw(canvas)
        canvas.restore()
    }

    private fun build(text: String, paint: TextPaint, width: Int): StaticLayout =
        StaticLayout.Builder.obtain(text, 0, text.length, paint, width)
            .setAlignment(Layout.Alignment.ALIGN_CENTER)
            .setLineSpacing(0f, 0.92f)
            .setIncludePad(false)
            .setBreakStrategy(Layout.BREAK_STRATEGY_BALANCED)
            .setHyphenationFrequency(Layout.HYPHENATION_FREQUENCY_NONE)
            .build()

    // endregion

    // region Cores

    private fun dist(a: Int, b: Int): Int {
        val dr = abs(((a shr 16) and 0xFF) - ((b shr 16) and 0xFF))
        val dg = abs(((a shr 8) and 0xFF) - ((b shr 8) and 0xFF))
        val db = abs((a and 0xFF) - (b and 0xFF))
        return max(dr, max(dg, db))
    }

    private fun luma(c: Int): Int =
        (((c shr 16) and 0xFF) * 299 + ((c shr 8) and 0xFF) * 587 + (c and 0xFF) * 114) / 1000

    private fun median(colors: List<Int>): Int {
        if (colors.isEmpty()) return Color.WHITE
        val r = colors.map { (it shr 16) and 0xFF }.sorted()[colors.size / 2]
        val g = colors.map { (it shr 8) and 0xFF }.sorted()[colors.size / 2]
        val b = colors.map { it and 0xFF }.sorted()[colors.size / 2]
        return Color.rgb(r, g, b)
    }

    private fun averageLuma(px: IntArray, ew: Int, x0: Int, y0: Int, x1: Int, y1: Int): Int {
        var sum = 0L
        var n = 0
        for (y in y0..y1) for (x in x0..x1) {
            sum += luma(px[y * ew + x])
            n++
        }
        return if (n == 0) 255 else (sum / n).toInt()
    }

    // endregion
}
