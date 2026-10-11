package app.mangalate.local

import app.mangalate.translate.SourceLanguage
import app.mangalate.translate.TargetLanguage
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * Tradução de texto com a API do DeepL (Free ou Pro).
 * Todas as falas da página vão em um único pedido, com a página inteira como contexto.
 */
object DeepLClient {

    private val client = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(60, TimeUnit.SECONDS)
        .build()

    private fun base(key: String) =
        if (key.trim().endsWith(":fx")) "https://api-free.deepl.com" else "https://api.deepl.com"

    private fun target(l: TargetLanguage) = when (l) {
        TargetLanguage.PT_BR -> "PT-BR"
        TargetLanguage.EN -> "EN-US"
        TargetLanguage.ES -> "ES"
        TargetLanguage.FR -> "FR"
        TargetLanguage.DE -> "DE"
        TargetLanguage.IT -> "IT"
        TargetLanguage.RU -> "RU"
        TargetLanguage.JA -> "JA"
        TargetLanguage.KO -> "KO"
        TargetLanguage.ZH -> "ZH-HANS"
    }

    private fun source(l: SourceLanguage) = when (l) {
        SourceLanguage.JA -> "JA"
        SourceLanguage.KO -> "KO"
        SourceLanguage.ZH -> "ZH"
        SourceLanguage.EN -> "EN"
    }

    suspend fun translate(
        key: String,
        texts: List<String>,
        from: SourceLanguage,
        to: TargetLanguage,
    ): List<String> {
        if (key.isBlank()) throw FriendlyException("Cole sua chave do DeepL nas configurações do Mangalate")
        if (texts.isEmpty()) return texts
        val out = ArrayList<String>(texts.size)
        val context = "Dialogue from a ${from.geminiName} manga page: " + texts.joinToString(" / ")
        for (chunk in texts.chunked(50)) {
            val body = JSONObject().apply {
                put("text", JSONArray(chunk))
                put("source_lang", source(from))
                put("target_lang", target(to))
                put("context", context.take(4000))
                put("preserve_formatting", false)
                if (to == TargetLanguage.PT_BR || to == TargetLanguage.ES) put("formality", "prefer_less")
            }
            out += call(key, "/v2/translate", body.toString()) { raw ->
                val arr = JSONObject(raw).getJSONArray("translations")
                (0 until arr.length()).map { arr.getJSONObject(it).getString("text") }
            }
        }
        return out
    }

    /** Retorna "usado / limite" de caracteres do mês. */
    suspend fun usage(key: String): Result<Pair<Long, Long>> = runCatching {
        call(key, "/v2/usage", null) { raw ->
            val o = JSONObject(raw)
            o.optLong("character_count") to o.optLong("character_limit")
        }
    }

    private suspend fun <T> call(key: String, path: String, json: String?, parse: (String) -> T): T {
        for (attempt in 1..4) {
            val (code, raw) = withContext(Dispatchers.IO) {
                val req = Request.Builder()
                    .url(base(key) + path)
                    .header("Authorization", "DeepL-Auth-Key ${key.trim()}")
                    .apply {
                        if (json != null) post(json.toRequestBody("application/json".toMediaType())) else get()
                    }
                    .build()
                client.newCall(req).execute().use { it.code to it.body.string() }
            }
            when {
                code in 200..299 -> return parse(raw)
                code == 403 || code == 401 -> throw FriendlyException("Chave do DeepL inválida. Confira se copiou a chave inteira.")
                code == 456 -> throw FriendlyException("Cota mensal do DeepL esgotada.")
                (code == 429 || code >= 500) && attempt < 4 -> delay(2_000L * attempt)
                else -> throw FriendlyException("DeepL respondeu $code")
            }
        }
        throw FriendlyException("DeepL indisponível no momento. Tente de novo.")
    }
}
