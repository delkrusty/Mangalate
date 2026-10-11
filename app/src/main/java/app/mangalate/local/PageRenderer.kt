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
import kotlin.math.max
import kotlin.math.min

/**
 * Balão confirmado: interior completo. Fora dele: só componentes de letras
 * validados, sem preenchimento retangular nem difusão sobre rostos/arte.
 * Toda detecção usa a imagem original imutável, nunca uma página já apagada.
 */
object PageRenderer {
    private class Plan(
        val region: TextRegion,
        val layout: RectF,
        val textColor: Int,
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

    fun render(context: Context, page: Bitmap, regions: List<TextRegion>, settings: MangalateSettings) {
        val source = page.copy(Bitmap.Config.ARGB_8888, false) ?: return
        val plans = ArrayList<Plan>()
        try {
            for (region in regions) {
                if (!SoundEffectPolicy.shouldTranslate(region.kind, region.original, settings.translateSoundEffects)) continue
                if (region.overArt && settings.ignoreOutsideBubbles) continue
                val plan = clean(page, source, region) ?: continue
                val previous = plans.indexOfFirst { existing ->
                    val intersection = RectF(plan.layout)
                    plan.wholeBubble && existing.wholeBubble && intersection.intersect(existing.layout) &&
                        intersection.width() * intersection.height() >
                        min(plan.layout.width() * plan.layout.height(), existing.layout.width() * existing.layout.height()) * 0.85f
                }
                if (previous < 0) {
                    plans += plan
                } else {
                    val old = plans[previous]
                    plans[previous] = Plan(
                        old.region.copy(
                            original = old.region.original + " " + region.original,
                            translation = old.region.translation + " " + region.translation,
                        ),
                        old.layout, old.textColor, true,
                    )
                }
            }
        } finally {
            source.recycle()
        }
        val canvas = Canvas(page)
        val paint = TextPaint(Paint.ANTI_ALIAS_FLAG or Paint.SUBPIXEL_TEXT_FLAG).apply { typeface = typeface(context) }
        for (plan in plans) {
            var text = plan.region.translation.replace(Regex("\\s+"), " ").trim()
            if (settings.uppercase) text = text.uppercase()
            if (text.isNotEmpty()) letter(context, canvas, page.width, text, plan, paint, settings)
        }
    }

    private fun clean(page: Bitmap, source: Bitmap, region: TextRegion): Plan? {
        val r = Rect(region.rect)
        if (!r.intersect(0, 0, page.width, page.height) || r.width() < 3 || r.height() < 3) return null
        // Uma caixa da IA quase do tamanho do quadro não autoriza apagar o quadro.
        if (r.width() > page.width * 0.65 && r.height() > page.height * 0.30) return null
        val grow = min(max(48, (max(r.width(), r.height()) * 1.5f).toInt()), max(48, page.width / 3))
        val e = Rect(r.left - grow, r.top - grow, r.right + grow, r.bottom + grow)
        e.intersect(0, 0, page.width, page.height)
        val w = e.width()
        val h = e.height()
        val pixels = IntArray(w * h)
        source.getPixels(pixels, 0, w, e.left, e.top, w, h)
        val localText = BubbleGeometry.Box(r.left - e.left, r.top - e.top, r.right - e.left, r.bottom - e.top)

        // Narração sem caixa e efeitos soltos jamais viram candidatos a balão.
        if (!region.overArt && region.kind != TextKind.SOUND_EFFECT) {
            val segmented = BubbleSegmenter.identify(pixels, w, h, localText)
                ?: BubbleSegmenter.identify(pixels, w, h, localText, closureRadius = 2)
            if (segmented != null &&
                BubbleBoundsGuard.accepts(localText, segmented.bounds, page.width, page.height)
            ) {
                val safe = BubbleGeometry.fit(segmented.interior, w, h, r.centerX() - e.left, r.centerY() - e.top)
                if (safe != null) {
                    applyMask(page, e, segmented.interior, segmented.background)
                    return Plan(
                        region,
                        RectF(safe.left + e.left.toFloat(), safe.top + e.top.toFloat(), safe.right + e.left.toFloat(), safe.bottom + e.top.toFloat()),
                        if (luma(segmented.background) < 110) Color.WHITE else Color.rgb(20, 20, 20),
                        true,
                    )
                }
            }
        }
        // Se a caixa sobre arte não foi confirmada pelo OCR, melhor preservar o
        // original do que inventar uma faixa branca ou escrever sobre um rosto.
        if (region.glyphBoxes.isEmpty()) return null
        val boxes = region.glyphBoxes.map {
            BubbleGeometry.Box(it.left - e.left, it.top - e.top, it.right - e.left, it.bottom - e.top)
        }
        val glyphs = GlyphCleaner.identify(pixels, w, h, boxes, page.width) ?: return null
        applyMask(page, e, glyphs.mask, glyphs.background)
        return Plan(region, RectF(r), if (luma(glyphs.background) < 110) Color.WHITE else Color.rgb(20, 20, 20))
    }

    private fun applyMask(page: Bitmap, crop: Rect, mask: BooleanArray, background: Int) {
        val pixels = IntArray(mask.size)
        page.getPixels(pixels, 0, crop.width(), crop.left, crop.top, crop.width(), crop.height())
        for (i in mask.indices) if (mask[i]) pixels[i] = background
        page.setPixels(pixels, 0, crop.width(), crop.left, crop.top, crop.width(), crop.height())
    }

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
        box.inset(min(2f, box.width() * 0.04f), min(2f, box.height() * 0.04f))
        if (box.width() < 1f || box.height() < 1f) return
        val maxSize = min(box.height() * 0.5f, pageWidth / 40f).coerceAtLeast(1f)
        val width = box.width().toInt().coerceAtLeast(1)
        val breaks: (String) -> List<Int> = if (settings.targetLanguage == TargetLanguage.PT_BR) {
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
            for (line in 0 until layout.lineCount) if (layout.getLineWidth(line) > width + 0.5f) return null
            return layout
        }
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
        val size = (best * (1f + settings.fontSizeOffset * 0.07f)).coerceIn(0.5f, best)
        val layout = fits(size) ?: selected
        paint.textSize = if (layout === selected) best else size
        paint.color = plan.textColor
        canvas.save()
        canvas.clipRect(box)
        canvas.translate(box.left, box.centerY() - layout.height / 2f)
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

    private fun luma(c: Int) =
        (((c ushr 16) and 255) * 299 + ((c ushr 8) and 255) * 587 + (c and 255) * 114) / 1000
}
