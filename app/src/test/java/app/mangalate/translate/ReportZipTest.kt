package app.mangalate.translate

import org.json.JSONObject
import org.junit.jupiter.api.Assertions.assertArrayEquals
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Test
import java.io.ByteArrayInputStream
import java.util.zip.ZipInputStream

class ReportZipTest {

    private val png = byteArrayOf(0x89.toByte(), 'P'.code.toByte(), 'N'.code.toByte(), 'G'.code.toByte(), 1, 2, 3)
    private val jpg = byteArrayOf(0xFF.toByte(), 0xD8.toByte(), 0xFF.toByte(), 9, 9)

    private fun info(hasTranslation: Boolean) = MangalateReport.Info(
        work = PageWork("Obra Teste", "Capítulo 1", 4),
        note = "balão sem tradução",
        mode = TranslateMode.SERVER,
        sourceLanguage = SourceLanguage.KO,
        targetLanguage = TargetLanguage.PT_BR,
        appVersion = "0.7.0",
        hasTranslation = hasTranslation,
    )

    private fun entries(zip: ByteArray): Map<String, ByteArray> {
        val out = linkedMapOf<String, ByteArray>()
        ZipInputStream(ByteArrayInputStream(zip)).use { z ->
            while (true) {
                val e = z.nextEntry ?: break
                out[e.name] = z.readBytes()
            }
        }
        return out
    }

    @Test
    fun `pacote tem original traducao e informacoes`() {
        val files = entries(MangalateReport.zip(jpg, png, info(true)))
        assertEquals(listOf("original.jpg", "traduzida.png", "info.json"), files.keys.toList())
        assertArrayEquals(jpg, files["original.jpg"])
        val json = JSONObject(String(files.getValue("info.json")))
        assertEquals("Obra Teste", json.getString("obra"))
        assertEquals(4, json.getInt("pagina"))
        assertEquals("balão sem tradução", json.getString("nota"))
        assertEquals("SERVER", json.getString("modo"))
    }

    @Test
    fun `pagina sem traducao vai so com o original`() {
        val files = entries(MangalateReport.zip(png, null, info(false)))
        assertEquals(listOf("original.png", "info.json"), files.keys.toList())
    }

    @Test
    fun `pacote nunca leva chave nem endereco do servidor`() {
        val json = JSONObject(info(true).toJson())
        val keys = json.keys().asSequence().toSet()
        assertFalse(keys.any { "chave" in it || "key" in it || "url" in it || "servidor" in it })
    }
}
