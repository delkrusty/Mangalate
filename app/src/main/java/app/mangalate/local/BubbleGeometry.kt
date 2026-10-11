package app.mangalate.local

import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min

/** Geometria pura, testável sem Android: retângulo totalmente dentro do balão. */
internal object BubbleGeometry {
    data class Box(val left: Int, val top: Int, val right: Int, val bottom: Int) {
        val width get() = right - left
        val height get() = bottom - top
    }

    fun fit(mask: BooleanArray, width: Int, height: Int, anchorX: Int, anchorY: Int): Box? {
        require(mask.size == width * height)
        if (width < 5 || height < 5) return null
        val seedX = anchorX.coerceIn(0, width - 1)
        val lefts = IntArray(height) { -1 }
        val rights = IntArray(height) { -1 }
        var weightedY = 0.0
        var weightSum = 0.0
        for (y in 0 until height) {
            if (!mask[y * width + seedX]) continue
            var left = seedX
            var right = seedX
            while (left > 0 && mask[y * width + left - 1]) left--
            while (right + 1 < width && mask[y * width + right + 1]) right++
            lefts[y] = left
            rights[y] = right + 1
            val weight = (right - left + 1).toDouble().let { it * it }
            weightedY += weight * y
            weightSum += weight
        }
        if (weightSum == 0.0) return null
        // A largura ao quadrado dá mais peso ao corpo do balão do que à cauda.
        val bodyY = (weightedY / weightSum).toInt()
        val centers = listOf(bodyY, anchorY.coerceIn(0, height - 1)).distinct()
        var best: Box? = null
        var bestScore = 0.0
        for (cy in centers) {
            var left = 0
            var right = width
            for (halfHeight in 0 until min(cy + 1, height - cy)) {
                val top = cy - halfHeight
                val bottom = cy + halfHeight
                if (lefts[top] < 0 || lefts[bottom] < 0) break
                left = max(left, max(lefts[top], lefts[bottom]))
                right = min(right, min(rights[top], rights[bottom]))
                if (right - left < 6) break
                val marginX = max(2, ((right - left) * 0.045f).toInt())
                val marginY = max(2, ((bottom - top + 1) * 0.045f).toInt())
                val box = Box(left + marginX, top + marginY, right - marginX, bottom + 1 - marginY)
                if (box.width <= 3 || box.height <= 3) continue
                val distance = abs(cy - bodyY).toDouble() / height
                val score = box.width.toDouble() * box.height / (1.0 + distance)
                if (score > bestScore) {
                    best = box
                    bestScore = score
                }
            }
        }
        return best
    }
}
