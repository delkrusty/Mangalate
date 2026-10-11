package app.mangalate.local

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import app.mangalate.translate.SourceLanguage
import app.mangalate.translate.TargetLanguage
import androidx.test.ext.junit.runners.AndroidJUnit4
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/** Testa o runtime real do ML Kit no APK release minificado, com texto sintético. */
@RunWith(AndroidJUnit4::class)
class MlKitRuntimeTest {
    private fun page(): Bitmap = Bitmap.createBitmap(1000, 360, Bitmap.Config.ARGB_8888).apply {
        val canvas = Canvas(this)
        canvas.drawColor(Color.WHITE)
        val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = Color.BLACK
            textSize = 60f
        }
        canvas.drawText("HELLO WORLD", 90f, 130f, paint)
        canvas.drawText("HOW ARE YOU TODAY?", 90f, 230f, paint)
    }

    @Test
    fun englishOcrWorksInRelease() = runBlocking {
        val image = page()
        try {
            val regions = withTimeout(90_000) { OnDeviceOcr.detect(image, SourceLanguage.EN) }
            assertFalse("OCR retornou vazio no APK release", regions.isEmpty())
            assertTrue(regions.joinToString { it.original }.contains("hello", ignoreCase = true))
        } finally {
            image.recycle()
        }
    }

    @Test
    fun japaneseKoreanAndChineseClientsInitializeInRelease() = runBlocking {
        val image = page()
        try {
            for (language in listOf(SourceLanguage.JA, SourceLanguage.KO, SourceLanguage.ZH)) {
                val regions = withTimeout(90_000) { OnDeviceOcr.detect(image, language) }
                assertFalse("OCR ${language.name} retornou vazio", regions.isEmpty())
            }
        } finally {
            image.recycle()
        }
    }

    @Test
    fun offlineModelDownloadsAndTranslatesInRelease() = runBlocking {
        val original = "Hello, how are you?"
        val result = withTimeout(300_000) {
            OnDeviceTranslate.translate(listOf(original), SourceLanguage.EN, TargetLanguage.PT_BR) {}
        }
        assertTrue(result.isNotEmpty())
        assertNotEquals("SDK devolveu o original em vez de traduzir", original, result.first())
        assertTrue(result.first().isNotBlank())
    }
}
