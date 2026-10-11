package app.mangalate.local

import app.mangalate.translate.SourceLanguage
import app.mangalate.translate.TargetLanguage
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.TimeUnit

object DeepLClient {
    private val api = DeepLApi()

    suspend fun translate(key: String, texts: List<String>, source: SourceLanguage, target: TargetLanguage) =
        api.translate(key, texts, source, target)

    suspend fun usage(key: String): Result<Pair<Long, Long>> = try {
        Result.success(api.usage(key))
    } catch (e: CancellationException) {
        throw e
    } catch (e: Exception) {
        Result.failure(e)
    }

    /** Teste real de permissão de tradução, não só consulta da cota. */
    suspend fun testTranslation(key: String): String =
        api.translate(key, listOf("Hello"), SourceLanguage.EN, TargetLanguage.PT_BR).single()
}

/** Transporte testável; a produção só usa os endpoints HTTPS oficiais. */
internal class DeepLApi(
    private val client: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(20, TimeUnit.SECONDS)
        .readTimeout(90, TimeUnit.SECONDS)
        .callTimeout(120, TimeUnit.SECONDS)
        .build(),
    private val endpoint: (String) -> String = ::officialEndpoint,
    private val retryDelay: suspend (Long) -> Unit = { delay(it) },
) {
    companion object {
        fun officialEndpoint(key: String) =
            if (key.trim().endsWith(":fx")) "https://api-free.deepl.com" else "https://api.deepl.com"
    }

    private fun target(language: TargetLanguage) = when (language) {
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

    suspend fun translate(key: String, texts: List<String>, source: SourceLanguage, to: TargetLanguage): List<String> {
        requireKey(key)
        if (texts.isEmpty()) return emptyList()
        val translated = ArrayList<String>(texts.size)
        val context = texts.joinToString("\n").take(4000)
        for (chunk in texts.chunked(50)) {
            val body = JSONObject().apply {
                put("text", JSONArray(chunk))
                put("source_lang", source.name)
                put("target_lang", target(to))
                put("context", context)
                put("preserve_formatting", false)
            }.toString()
            if (body.toByteArray(Charsets.UTF_8).size > 128 * 1024) {
                throw FriendlyException("Página com texto grande demais para a API do DeepL.")
            }
            val response = call(key, "/v2/translate", body)
            val array = JSONObject(response).optJSONArray("translations")
                ?: throw FriendlyException("DeepL retornou uma resposta sem traduções.")
            if (array.length() != chunk.size) {
                throw FriendlyException("DeepL retornou uma quantidade inesperada de falas. Nenhuma fala será trocada de balão.")
            }
            for (i in chunk.indices) {
                val text = array.getJSONObject(i).optString("text")
                if (text.isBlank() && chunk[i].isNotBlank()) throw FriendlyException("DeepL retornou uma tradução vazia.")
                translated += text
            }
        }
        return translated
    }

    suspend fun usage(key: String): Pair<Long, Long> {
        requireKey(key)
        val body = JSONObject(call(key, "/v2/usage", null))
        return body.optLong("character_count") to body.optLong("character_limit")
    }

    private fun requireKey(key: String) {
        if (key.isBlank()) throw FriendlyException("Cole uma chave do DeepL API Free ou Pro. A assinatura do tradutor web não substitui a chave de API.")
    }

    private suspend fun call(key: String, path: String, body: String?): String {
        for (attempt in 1..4) {
            val (code, response) = withContext(Dispatchers.IO) {
                val request = Request.Builder()
                    .url(endpoint(key).trimEnd('/') + path)
                    .header("Authorization", "DeepL-Auth-Key ${key.trim()}")
                    .apply {
                        if (body == null) get() else post(body.toRequestBody("application/json".toMediaType()))
                    }
                    .build()
                try {
                    client.newCall(request).execute().use { it.code to it.body?.string().orEmpty() }
                } catch (e: IOException) {
                    throw FriendlyException("Não foi possível conectar à API do DeepL. Confira a internet e tente novamente.")
                }
            }
            when {
                code in 200..299 -> return response
                code == 401 || code == 403 -> throw FriendlyException("DeepL recusou a chave. Use uma chave de DeepL API Free ou API Pro e confira se copiou inteira.")
                code == 456 -> throw FriendlyException("A cota do DeepL ou o limite configurado para a chave foi esgotado.")
                (code == 429 || code >= 500) && attempt < 4 -> retryDelay(1500L * attempt)
                code == 429 -> throw FriendlyException("DeepL ocupado ou com limite de pedidos. Aguarde e tente novamente.")
                code == 400 -> throw FriendlyException("DeepL recusou os parâmetros da tradução (HTTP 400). Confira os idiomas selecionados.")
                else -> throw FriendlyException("A API do DeepL respondeu HTTP $code. Tente novamente.")
            }
        }
        throw FriendlyException("DeepL indisponível no momento.")
    }
}
