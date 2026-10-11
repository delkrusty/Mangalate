package app.mangalate.local

import android.graphics.Bitmap
import android.graphics.Rect
import android.util.Base64
import app.mangalate.translate.MangalateSettings
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.util.concurrent.TimeUnit
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

class FriendlyException(message: String) : IOException(message)

/**
 * Gemini lê a página (inclusive texto vertical), localiza cada fala e traduz
 * considerando o contexto da página inteira.
 */
object GeminiClient {

    private const val BASE = "https://generativelanguage.googleapis.com/v1beta/models/"
    private val FAST_MODELS = listOf("gemini-flash-lite-latest", "gemini-3.5-flash-lite", "gemini-2.5-flash-lite", "gemini-flash-latest")
    private val QUALITY_MODELS = listOf("gemini-flash-latest", "gemini-2.5-flash", "gemini-flash-lite-latest")

    /** Modelos que recusaram thinkingConfig (não enviamos mais para eles). */
    private val noThinking = java.util.concurrent.ConcurrentHashMap.newKeySet<String>()

    private val client = OkHttpClient.Builder()
        .connectTimeout(20, TimeUnit.SECONDS)
        .readTimeout(3, TimeUnit.MINUTES)
        .callTimeout(4, TimeUnit.MINUTES)
        .build()

    suspend fun detectAndTranslate(page: Bitmap, s: MangalateSettings): List<TextRegion> {
        val out = ArrayList<TextRegion>()
        for (tile in PageTiles.split(page.width, page.height)) {
            val bmp = if (tile.height() == page.height) page else Bitmap.createBitmap(page, 0, tile.top, page.width, tile.height())
            val regions = requestTile(bmp, s)
            regions.forEach { it.rect.offset(0, tile.top) }
            out += regions
            if (bmp !== page) bmp.recycle()
        }
        return out
    }

    /** Verifica a chave com uma chamada mínima. */
    suspend fun testKey(key: String, model: String): Result<String> = withContext(Dispatchers.IO) {
        runCatching {
            val body = JSONObject()
                .put("contents", JSONArray().put(JSONObject().put("parts", JSONArray().put(JSONObject().put("text", "Responda apenas: ok")))))
            val (usedModel, _) = call(key.trim(), model, body)
            usedModel
        }
    }

    private suspend fun requestTile(bmp: Bitmap, s: MangalateSettings): List<TextRegion> {
        val scale = min(1f, 1400f / max(bmp.width, bmp.height))
        val send = if (scale < 1f) {
            Bitmap.createScaledBitmap(bmp, (bmp.width * scale).roundToInt(), (bmp.height * scale).roundToInt(), true)
        } else {
            bmp
        }
        val jpeg = ByteArrayOutputStream().use {
            send.compress(Bitmap.CompressFormat.JPEG, 88, it)
            it.toByteArray()
        }
        if (send !== bmp) send.recycle()

        val body = JSONObject().apply {
            put(
                "contents",
                JSONArray().put(
                    JSONObject().put(
                        "parts",
                        JSONArray()
                            .put(
                                JSONObject().put(
                                    "inline_data",
                                    JSONObject()
                                        .put("mime_type", "image/jpeg")
                                        .put("data", Base64.encodeToString(jpeg, Base64.NO_WRAP)),
                                ),
                            )
                            .put(JSONObject().put("text", prompt(s))),
                    ),
                ),
            )
            put(
                "generationConfig",
                JSONObject()
                    .put("temperature", 0.4)
                    .put("responseMimeType", "application/json"),
            )
        }
        val (_, text) = call(s.geminiKey.trim(), s.effectiveGeminiModel, body)
        return parse(text, bmp.width, bmp.height)
    }

    private fun prompt(s: MangalateSettings): String = buildString {
        append("You are an expert manga scanlation translator. Find EVERY piece of text in this ")
        append("${s.sourceLanguage.geminiName} comic page: speech bubbles, thought bubbles, narration boxes")
        if (s.ignoreOutsideBubbles) {
            append(". Skip sound effects and any text drawn directly over the artwork")
        } else {
            append(", sound effects and text written over the artwork")
        }
        append(". Ignore page numbers, watermarks and scanlator credits.\n")
        append("For each text return:\n")
        append("- kind: speech (dialogue), narration (captions), or sfx (sound effects/onomatopoeia)\n")
        append("- box_2d: [ymin, xmin, ymax, xmax] normalized 0-1000, tightly around the original characters only (not the whole bubble)\n")
        append("- original: the exact original text\n")
        append("- translation: a natural, fluent ${s.targetLanguage.englishName} translation, as a professional ")
        append("scanlator would letter it: keep each character's tone, slang and emotion, keep names consistent, ")
        append("use the whole page as context, and keep it short enough to fit the same bubble\n")
        append("- over_art: true if the text is NOT inside a bubble/box (drawn over the artwork)\n")
        append("- vertical: true if the original is written vertically\n")
        append("List items in reading order (manga: right-to-left, top-to-bottom).\n")
        append("Keep each translation as one plain paragraph: no manual line breaks, soft hyphens, ")
        append("or syllable splitting. The app will handle lettering. Never merge separate bubbles.\n")
        if (!s.translateSoundEffects) {
            append("Do NOT include sound effects, onomatopoeia, repeated CLAP/TAP, or stylized noises in blocks. ")
            append("Leave them untouched even if they have a verbal translation. Keep actual dialogue and narration captions.\n")
        }
        append("Coordinates must cover only the characters, not the panel, nearby faces or artwork. ")
        append("Mark unboxed captions over_art=true. Never create a balloon around unboxed text.\n")
        append("Reply only with JSON: {\"blocks\":[{\"kind\":\"speech\",\"box_2d\":[0,0,0,0],\"original\":\"\",\"translation\":\"\",\"over_art\":false,\"vertical\":false}]}")
    }

    private fun parse(text: String, w: Int, h: Int): List<TextRegion> {
        val clean = text.trim().removePrefix("```json").removePrefix("```").removeSuffix("```").trim()
        val start = clean.indexOfFirst { it == '{' || it == '[' }
        if (start < 0) return emptyList()
        val json = clean.substring(start)
        val arr = if (json.startsWith("[")) JSONArray(json) else JSONObject(json).optJSONArray("blocks") ?: JSONArray()
        val result = ArrayList<TextRegion>()
        for (i in 0 until arr.length()) {
            val o = arr.optJSONObject(i) ?: continue
            val box = o.optJSONArray("box_2d") ?: continue
            if (box.length() != 4) continue
            val y0 = box.optDouble(0) / 1000.0 * h
            val x0 = box.optDouble(1) / 1000.0 * w
            val y1 = box.optDouble(2) / 1000.0 * h
            val x1 = box.optDouble(3) / 1000.0 * w
            val rect = Rect(
                min(x0, x1).toInt().coerceIn(0, w - 1),
                min(y0, y1).toInt().coerceIn(0, h - 1),
                max(x0, x1).toInt().coerceIn(1, w),
                max(y0, y1).toInt().coerceIn(1, h),
            )
            if (rect.width() < 4 || rect.height() < 4) continue
            val translation = o.optString("translation").trim()
            if (translation.isEmpty()) continue
            result += TextRegion(
                rect = rect,
                original = o.optString("original"),
                translation = translation,
                overArt = o.optBoolean("over_art", false),
                vertical = o.optBoolean("vertical", false),
                kind = TextKind.parse(o.optString("kind")),
            )
        }
        return result
    }

    /** Chama o Gemini com novas tentativas para limite de uso e troca de modelo se não existir. */
    private suspend fun call(key: String, model: String, body: JSONObject): Pair<String, String> {
        if (key.isBlank()) throw FriendlyException("Cole sua chave do Gemini nas configurações do Mangalate")
        val fallbacks = if (model.contains("lite")) FAST_MODELS else QUALITY_MODELS
        val models = (listOf(model.ifBlank { fallbacks[0] }) + fallbacks).distinct()
        var lastError: Exception? = null
        for (m in models) {
            var attempt = 0
            while (attempt < 4) {
                attempt++
                val payload = JSONObject(body.toString())
                if (m !in noThinking) {
                    val gen = payload.optJSONObject("generationConfig") ?: JSONObject().also { payload.put("generationConfig", it) }
                    gen.put("thinkingConfig", JSONObject().put("thinkingLevel", "low"))
                }
                val (code, text) = withContext(Dispatchers.IO) {
                    val req = Request.Builder()
                        .url("$BASE$m:generateContent")
                        .header("x-goog-api-key", key)
                        .post(payload.toString().toRequestBody("application/json".toMediaType()))
                        .build()
                    client.newCall(req).execute().use { it.code to it.body.string() }
                }
                when {
                    code in 200..299 -> {
                        val out = extractText(text)
                        return m to out
                    }
                    code == 429 || code == 503 || code == 500 -> {
                        lastError = FriendlyException(
                            if (code == 429) {
                                "Limite gratuito do Gemini atingido. Aguarde um minuto e tente de novo."
                            } else {
                                "Gemini ocupado no momento. Tentando de novo…"
                            },
                        )
                        delay(longArrayOf(6_000, 15_000, 30_000, 45_000)[attempt - 1])
                    }
                    code == 400 && m !in noThinking && text.contains("thinking", ignoreCase = true) -> {
                        // modelo não aceita nível de pensamento: tenta de novo sem
                        noThinking += m
                        attempt--
                    }
                    code == 404 -> {
                        lastError = FriendlyException("Modelo $m não disponível")
                        break
                    }
                    code == 400 && text.contains("API_KEY", ignoreCase = true) ||
                        code == 401 || code == 403 -> throw FriendlyException("Chave do Gemini inválida. Confira se copiou a chave inteira.")
                    else -> throw FriendlyException("Gemini respondeu $code: ${errorMessage(text)}")
                }
            }
            if (lastError?.message?.startsWith("Limite") == true) throw lastError!!
        }
        throw lastError ?: FriendlyException("Falha ao falar com o Gemini")
    }

    private fun extractText(raw: String): String {
        val root = JSONObject(raw)
        val parts = root.optJSONArray("candidates")?.optJSONObject(0)
            ?.optJSONObject("content")?.optJSONArray("parts") ?: return ""
        val sb = StringBuilder()
        for (i in 0 until parts.length()) {
            val p = parts.optJSONObject(i) ?: continue
            if (p.optBoolean("thought", false)) continue
            sb.append(p.optString("text"))
        }
        return sb.toString()
    }

    private fun errorMessage(raw: String): String = runCatching {
        JSONObject(raw).getJSONObject("error").getString("message")
    }.getOrDefault(raw.take(200))
}
