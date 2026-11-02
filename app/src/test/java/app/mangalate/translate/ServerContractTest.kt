package app.mangalate.translate

import org.json.JSONObject
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import java.io.File

/**
 * O que o app manda ao servidor, conferido com o mesmo arquivo que `server/tests/test_contract.py` lê.
 */
class ServerContractTest {

    private fun contract(): JSONObject {
        val path = "server/tests/app_config_contract.json"
        val file = generateSequence(File("").absoluteFile) { it.parentFile }
            .map { File(it, path) }
            .first { it.exists() }
        return JSONObject(file.readText())
    }

    /** Objeto JSON como mapa ordenado, com números como texto; só usa a API que o Android também tem. */
    private fun plain(json: JSONObject): Map<String, Any> = json.keys().asSequence().sorted().associateWith { key ->
        when (val value = json.get(key)) {
            is JSONObject -> plain(value)
            is Number -> value.toString()
            else -> value
        }
    }

    private fun settingsOf(json: JSONObject) = MangalateSettings(
        mode = TranslateMode.SERVER,
        targetLanguage = TargetLanguage.fromCode(json.optString("targetLanguage", "PTB")),
        fontSizeOffset = json.optInt("fontSizeOffset", 0),
        uppercase = json.optBoolean("uppercase", false),
        preserveArtText = if (json.has("preserveArtText")) json.getBoolean("preserveArtText") else null,
    )

    @Test
    fun appSendsWhatTheContractSays() {
        val cases = contract().getJSONArray("cases")
        for (i in 0 until cases.length()) {
            val case = cases.getJSONObject(i)
            val sent = JSONObject(settingsOf(case.getJSONObject("settings")).toServerConfig())
            assertEquals(plain(case.getJSONObject("sent")), plain(sent), case.getString("name"))
        }
    }

    @Test
    fun cacheOfReadersWhoNeverTouchedTheRetiredOptionsIsKept() {
        // A configuração que a 0.6.0 mandava com os padrões: a assinatura do cache não pode mudar.
        val before060 = JSONObject(
            """
            {"detector":{"detector":"ctd","detection_size":2048,"text_threshold":0.5,"box_threshold":0.6,"unclip_ratio":2.3},
             "ocr":{"ocr":"48px","min_text_length":0},
             "inpainter":{"inpainter":"lama_large","inpainting_size":2048,"inpainting_precision":"fp32"},
             "translator":{"translator":"nllb","target_lang":"PTB","enable_post_translation_check":true,"post_check_max_retry_attempts":2},
             "render":{"renderer":"manga2eng","alignment":"center","direction":"horizontal","font_size_offset":2,"uppercase":true,
                       "disable_font_border":false,"no_hyphenation":false,"rtl":true},
             "arte":"traduzir","kernel_size":3,"mask_dilation_offset":30}
            """,
        )
        val signature = MangalateSettings(
            mode = TranslateMode.SERVER,
            fontSizeOffset = 2,
            uppercase = true,
            preserveArtText = false,
        ).cacheSignature()
        assertTrue(signature.startsWith("server-scan-v2|"))
        // Compara chaves e valores; a ordem dos `put` (que também entra na assinatura no Android)
        // é conferida à mão: não mude `legacyServerConfig()` sem subir o "server-scan-v2".
        assertEquals(plain(before060), plain(JSONObject(signature.removePrefix("server-scan-v2|"))))
    }

    @Test
    fun onDeviceSignatureKeepsItsFormer060Shape() {
        assertEquals(
            "sdk-translation-v5.1|ON_DEVICE|JA|PTB||false|false|0",
            MangalateSettings().cacheSignature(),
        )
    }
}
