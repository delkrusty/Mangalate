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
import app.mangalate.translate.TargetLanguage
import eu.kanade.tachiyomi.R
import java.util.ArrayDeque
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

/**
 * Limpa o texto original e diagrama a tradução no lugar.
 *
 * Balões fechados e lisos: segmenta todo o interior e limpa inclusive caracteres
 * que o OCR não localizou, preservando o contorno. Regiões incertas usam limpeza local.
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
        val wholeBubble: Boolean = false,
    )

    @Volatile
    private var typeface: Typeface? = null

    @Volatile
    private var dictionary: PortugueseHyphenator? = null

    private fun hyphenator(context: Context): PortugueseHyphenator = dictionary ?: synchronized(this) {
        dictionary ?: context.assets.open("lettering/hyph_pt_BR.dic").bufferedReader().use { reader ->
            PortugueseHyphenator(reader.lineSequence()).also { dictionary = it }
        }
    }

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
            val previous = plans.indexOfFirst { existing ->
                if (!plan.wholeBubble || !existing.wholeBubble) {
                    false
                } else {
                    val intersection = RectF(plan.layout)
                    intersection.intersect(existing.layout) &&
                        intersection.width() * intersection.height() >
                        min(plan.layout.width() * plan.layout.height(), existing.layout.width() * existing.layout.height()) * 0.85f
                }
            }
            if (previous < 0) {
                plans += plan
            } else {
                // Vários blocos de OCR no mesmo balão viram uma fala, sem duas legendas sobrepostas.
                val old = plans[previous]
                val merged = old.region.copy(
                    original = old.region.original + " " + plan.region.original,
                    translation = old.region.translation + " " + plan.region.translation,
                )
                plans[previous] = Plan(merged, old.layout, old.textColor, old.strokeColor, true)
            }
        }
        // 2) diagramar
        val canvas = Canvas(page)
        val paint = TextPaint(Paint.ANTI_ALIAS_FLAG or Paint.SUBPIXEL_TEXT_FLAG).apply {
            typeface = typeface(context)
        }
        for (plan in plans) {
            var text = plan.region.translation.replace(Regex("\\s+"), " ").trim()
            if (s.uppercase) text = text.uppercase()
            if (text.isEmpty()) continue
            letter(context, canvas, page.width, text, plan, paint, s)
        }
    }

    // region Limpeza

    private fun clean(page: Bitmap, region: TextRegion, s: MangalateSettings): Plan? {
        val pw = page.width
        val ph = page.height
        val r = Rect(region.rect).apply { intersect(0, 0, pw, ph) }
        if (r.width() < 3 || r.height() < 3) return null

        val grow = max(48, (max(r.width(), r.height()) * 1.5f).toInt())
        val e = Rect(r.left - grow, r.top - grow, r.right + grow, r.bottom + grow).apply { intersect(0, 0, pw, ph) }
        val ew = e.width()
        val eh = e.height()
        val px = IntArray(ew * eh)
        page.getPixels(px, 0, ew, e.left, e.top, ew, eh)

        if (!region.overArt) {
            val segmented = BubbleSegmenter.identify(
                px,
                ew,
                eh,
                BubbleGeometry.Box(r.left - e.left, r.top - e.top, r.right - e.left, r.bottom - e.top),
            )
            if (segmented != null) {
                val safe = BubbleGeometry.fit(segmented.interior, ew, eh, r.centerX() - e.left, r.centerY() - e.top)
                if (safe != null) {
                    for (i in px.indices) if (segmented.interior[i]) px[i] = segmented.background
                    page.setPixels(px, 0, ew, e.left, e.top, ew, eh)
                    val box = RectF(
                        safe.left + e.left.toFloat(),
                        safe.top + e.top.toFloat(),
                        safe.right + e.left.toFloat(),
                        safe.bottom + e.top.toFloat(),
                    )
                    val color = if (luma(segmented.background) < 110) Color.WHITE else Color.rgb(20, 20, 20)
                    return Plan(region, box, color, null, wholeBubble = true)
                }
            }
        }

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
            while (queue.isNotEmpty()) {
                val i = queue.poll()!!
                val x = i % ew
                val y = i / ew
                area++
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
            val leaked = touches > 0 || area > ew.toLong() * eh * 0.92

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
                BubbleGeometry.fit(inside, ew, eh, r.centerX() - e.left, r.centerY() - e.top)
                    ?.let { RectF(it.left + e.left.toFloat(), it.top + e.top.toFloat(), it.right + e.left.toFloat(), it.bottom + e.top.toFloat()) }
                    ?: RectF(r)
            } else {
                // Área incerta: não cresce para fora da caixa original.
                RectF(r)
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

    private fun letter(
        context: Context,
        canvas: Canvas,
        pageWidth: Int,
        text: String,
        plan: Plan,
        paint: TextPaint,
        settings: MangalateSettings,
    ) {
        val box = RectF(plan.layout)
        // Limita a fonte pelo tamanho da página; um balão pequeno não recebe letras gigantes.
        box.inset(min(2f, box.width() * 0.04f), min(2f, box.height() * 0.04f))
        if (box.width() < 1f || box.height() < 1f) return
        val maxSize = min(box.height() * 0.5f, pageWidth / 40f).coerceAtLeast(1f)
        val width = box.width().toInt().coerceAtLeast(1)
        val portuguese = settings.targetLanguage == TargetLanguage.PT_BR
        val breaks: (String) -> List<Int> = if (portuguese) {
            hyphenator(context)::breaks
        } else {
            { emptyList() }
        }

        fun fits(size: Float): StaticLayout? {
            paint.textSize = size
            paint.style = Paint.Style.FILL
            val prepared = if (settings.targetLanguage.latin || settings.targetLanguage == TargetLanguage.RU) {
                BubbleTextWrapper.wrap(text, width.toFloat(), { paint.measureText(it) }, breaks)
                    ?.joinToString("\n") ?: return null
            } else {
                text
            }
            val layout = build(prepared, paint, width)
            if (layout.height > box.height()) return null
            for (line in 0 until layout.lineCount) {
                if (layout.getLineWidth(line) > width + 0.5f) return null
            }
            return layout
        }

        // Não existe mais o fallback que ampliava a caixa e cortava palavras arbitrariamente.
        var lo = 0.5f
        var hi = maxSize
        var best = lo
        var selected = fits(lo) ?: return
        repeat(14) {
            val mid = (lo + hi) / 2
            val candidate = fits(mid)
            if (candidate != null) {
                best = mid
                selected = candidate
                lo = mid
            } else {
                hi = mid
            }
        }
        // Ajuste manual pode diminuir a fonte, nunca passar do tamanho que cabe.
        val size = (best * (1f + settings.fontSizeOffset * 0.07f)).coerceIn(0.5f, best)
        val layout = fits(size) ?: selected
        // StaticLayout retém o TextPaint: restaura a fonte efetiva antes de desenhar.
        paint.textSize = if (layout === selected) best else size

        canvas.save()
        canvas.clipRect(box)
        canvas.translate(box.left, box.centerY() - layout.height / 2f)
        if (plan.strokeColor != null) {
            paint.style = Paint.Style.STROKE
            paint.strokeJoin = Paint.Join.ROUND
            paint.strokeWidth = max(1f, paint.textSize * 0.15f)
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
            .setLineSpacing(0f, 1.05f)
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
