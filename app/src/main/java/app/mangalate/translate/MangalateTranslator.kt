package app.mangalate.translate

import android.content.Context
import android.content.SharedPreferences
import android.os.Handler
import android.os.Looper
import android.widget.Toast
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Deferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.async
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withPermit
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import app.mangalate.local.LocalPipeline
import okio.Buffer
import okio.BufferedSource
import java.io.File
import java.io.IOException
import java.security.MessageDigest
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.TimeUnit

/**
 * Núcleo do Mangalate: envia a página ao servidor de tradução, recebe a página
 * já limpa, reconstruída e diagramada, e guarda o resultado em cache.
 *
 * O servidor (manga-image-translator) faz: detecção de texto/balões, OCR, máscara
 * dos caracteres, reconstrução do fundo (LaMa), tradução com contexto da página e
 * renderização tipográfica dentro do balão.
 */
object MangalateTranslator {

    private const val PREFS_NAME = "mangalate"
    private const val CACHE_DIR = "mangalate_translations"
    private const val MAX_CACHE_BYTES = 600L * 1024 * 1024
    private const val ENDPOINT = "/translate/with-form/image"

    @Volatile
    private var prefs: SharedPreferences? = null

    private val _enabled = MutableStateFlow(false)

    /** Quando verdadeiro, o leitor substitui as páginas pela versão traduzida. */
    val enabled: StateFlow<Boolean> = _enabled.asStateFlow()

    private val _activeJobs = MutableStateFlow(0)

    /** Número de páginas sendo traduzidas agora (para o indicador do leitor). */
    val activeJobs: StateFlow<Int> = _activeJobs.asStateFlow()

    private val _status = MutableStateFlow<String?>(null)

    /** Mensagem extra para o indicador do leitor (ex.: baixando o tradutor). */
    val status: StateFlow<String?> = _status.asStateFlow()

    private val _settings = MutableStateFlow(MangalateSettings())
    val settings: StateFlow<MangalateSettings> = _settings.asStateFlow()

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val inFlight = ConcurrentHashMap<String, Deferred<ByteArray>>()

    // Páginas traduzidas ao mesmo tempo, por modo (o Gemini grátis tem limite por minuto).
    private val semaphores = mapOf(
        TranslateMode.ON_DEVICE to Semaphore(2),
        TranslateMode.GEMINI to Semaphore(3),
        TranslateMode.DEEPL to Semaphore(3),
        TranslateMode.SERVER to Semaphore(1),
    )

    private val mainHandler = Handler(Looper.getMainLooper())

    @Volatile
    private var lastErrorToastAt = 0L

    private val client: OkHttpClient by lazy {
        OkHttpClient.Builder()
            .connectTimeout(20, TimeUnit.SECONDS)
            .writeTimeout(90, TimeUnit.SECONDS)
            .readTimeout(15, TimeUnit.MINUTES)
            .callTimeout(20, TimeUnit.MINUTES)
            .retryOnConnectionFailure(true)
            .build()
    }

    fun init(context: Context) {
        if (prefs != null) return
        synchronized(this) {
            if (prefs != null) return
            val p = context.applicationContext.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            prefs = p
            _settings.value = read(p)
            _enabled.value = p.getBoolean("enabled", false) && _settings.value.isConfigured
        }
    }

    private fun read(p: SharedPreferences) = MangalateSettings(
        mode = TranslateMode.fromName(p.getString("mode", null)),
        sourceLanguage = SourceLanguage.fromName(p.getString("source_lang", null)),
        geminiKey = p.getString("gemini_key", "") ?: "",
        geminiModel = p.getString("gemini_model", null) ?: MangalateSettings.DEFAULT_GEMINI_MODEL,
        setupDone = p.getBoolean("setup_done", false),
        geminiFast = p.getBoolean("gemini_fast", true),
        deeplKey = p.getString("deepl_key", "") ?: "",
        translateOnDownload = p.getBoolean("translate_on_download", false),
        serverUrl = p.getString("server_url", "") ?: "",
        accessKey = p.getString("access_key", "") ?: "",
        targetLanguage = TargetLanguage.fromCode(p.getString("target_lang", null)),
        engine = TranslatorEngine.fromId(p.getString("engine", null)),
        quality = QualityProfile.fromName(p.getString("quality", null)),
        typeset = TypesetMode.fromName(p.getString("typeset", null)),
        ignoreOutsideBubbles = p.getBoolean("ignore_outside_bubbles", false),
        uppercase = p.getBoolean("uppercase", false),
        fontSizeOffset = p.getInt("font_size_offset", 0),
        maskDilation = p.getInt("mask_dilation", 0),
    )

    fun updateSettings(context: Context, transform: (MangalateSettings) -> MangalateSettings) {
        init(context)
        val new = transform(_settings.value)
        _settings.value = new
        prefs?.edit()
            ?.putString("mode", new.mode.name)
            ?.putString("source_lang", new.sourceLanguage.name)
            ?.putString("gemini_key", new.geminiKey)
            ?.putString("gemini_model", new.geminiModel)
            ?.putBoolean("setup_done", new.setupDone)
            ?.putBoolean("gemini_fast", new.geminiFast)
            ?.putString("deepl_key", new.deeplKey)
            ?.putBoolean("translate_on_download", new.translateOnDownload)
            ?.putString("server_url", new.serverUrl)
            ?.putString("access_key", new.accessKey)
            ?.putString("target_lang", new.targetLanguage.code)
            ?.putString("engine", new.engine.id)
            ?.putString("quality", new.quality.name)
            ?.putString("typeset", new.typeset.name)
            ?.putBoolean("ignore_outside_bubbles", new.ignoreOutsideBubbles)
            ?.putBoolean("uppercase", new.uppercase)
            ?.putInt("font_size_offset", new.fontSizeOffset)
            ?.putInt("mask_dilation", new.maskDilation)
            ?.apply()
        if (!new.isConfigured) setEnabled(context, false)
    }

    /** Liga/desliga a tradução. Retorna o novo estado. */
    fun setEnabled(context: Context, value: Boolean): Boolean {
        init(context)
        val effective = value && _settings.value.isConfigured
        _enabled.value = effective
        prefs?.edit()?.putBoolean("enabled", effective)?.apply()
        return effective
    }

    fun isEnabled(context: Context): Boolean {
        init(context)
        return _enabled.value
    }

    /**
     * Gancho usado pelos leitores (paginado e webtoon). Se a tradução estiver ativa,
     * devolve a página traduzida; em qualquer falha devolve a original, para a leitura
     * nunca travar.
     */
    suspend fun maybeTranslate(context: Context, source: Buffer): BufferedSource {
        if (!isEnabled(context)) return source
        if (source.size < 2048) return source
        if (isGifOrAnimated(source)) return source
        return try {
            val bytes = source.peek().readByteArray()
            val translated = translate(context, bytes)
            Buffer().write(translated)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Throwable) {
            notifyError(context, e)
            source
        }
    }

    private fun isGifOrAnimated(source: Buffer): Boolean {
        val head = source.peek().readByteArray(minOf(64L, source.size))
        val isGif = head.size > 3 && head[0] == 'G'.code.toByte() && head[1] == 'I'.code.toByte()
        // WebP animado: "RIFF....WEBPVP8X" com flag de animação
        val isAnimWebp = head.size > 21 &&
            String(head, 8, 4, Charsets.US_ASCII) == "WEBP" &&
            String(head, 12, 4, Charsets.US_ASCII) == "VP8X" &&
            (head[20].toInt() and 0x02) != 0
        return isGif || isAnimWebp
    }

    /** Traduz os bytes de uma imagem, usando cache em disco e deduplicação. */
    suspend fun translate(context: Context, image: ByteArray, keepOffline: Boolean = false): ByteArray {
        init(context)
        val s = _settings.value
        if (!s.isConfigured) throw IOException("Tradução não configurada")
        val signature = s.cacheSignature()
        val key = sha256(image) + "_" + sha256(signature.toByteArray()).take(16)
        val offlineFile = File(offlineDir(context), "$key.img")
        val cacheFile = if (keepOffline) offlineFile else File(cacheDir(context), "$key.img")

        if (offlineFile.exists() && offlineFile.length() > 0) {
            return withContext(Dispatchers.IO) { offlineFile.readBytes() }
        }
        val tempFile = File(cacheDir(context), "$key.img")
        if (tempFile.exists() && tempFile.length() > 0) {
            tempFile.setLastModified(System.currentTimeMillis())
            val bytes = withContext(Dispatchers.IO) { tempFile.readBytes() }
            if (keepOffline) withContext(Dispatchers.IO) { runCatching { offlineFile.writeBytes(bytes) } }
            return bytes
        }

        // A tarefa roda num escopo próprio: se o usuário passar a página antes do fim,
        // o resultado ainda é salvo no cache (funciona como pré-tradução).
        val deferred = inFlight.getOrPut(key) {
            scope.async {
                try {
                    semaphores.getValue(s.mode).withPermit {
                        _activeJobs.update { it + 1 }
                        try {
                            val result = when (s.mode) {
                                TranslateMode.SERVER -> request(s, s.toServerConfig(), image)
                                else -> LocalPipeline.process(context.applicationContext, image, s) { _status.value = it }
                            }
                            writeCache(context, cacheFile, result)
                            result
                        } finally {
                            _activeJobs.update { it - 1 }
                        }
                    }
                } finally {
                    inFlight.remove(key)
                }
            }
        }
        val result = deferred.await()
        if (keepOffline && !offlineFile.exists()) {
            withContext(Dispatchers.IO) { runCatching { offlineFile.writeBytes(result) } }
        }
        return result
    }

    private fun request(s: MangalateSettings, config: String, image: ByteArray): ByteArray {
        val mime = sniffMime(image)
        val ext = mime.substringAfter('/')
        val body = MultipartBody.Builder()
            .setType(MultipartBody.FORM)
            .addFormDataPart("image", "page.$ext", image.toRequestBody(mime.toMediaType()))
            .addFormDataPart("config", config)
            .build()
        val request = Request.Builder()
            .url(s.normalizedUrl + ENDPOINT)
            .post(body)
            .apply { authHeaders(s).forEach { (k, v) -> header(k, v) } }
            .build()
        client.newCall(request).execute().use { response ->
            val bytes = response.body.bytes()
            if (!response.isSuccessful) {
                val help = when (response.code) {
                    401, 403 -> "Chave Mangalate inválida. Copie o conteúdo de server/secrets/mangalate_key.txt; não use a chave da IA."
                    429 -> "O servidor já está traduzindo uma página. Aguarde antes de tentar de novo."
                    422 -> "Página bloqueada pela proteção de imagem ou configuração. Confira o original e os logs do seu servidor."
                    502 -> "O motor de tradução falhou. No BYOK, confira modelo, chave e saldo no servidor."
                    503 -> "O processo de tradução ainda está iniciando ou parou. Aguarde e rode check.py --warmup no computador."
                    504 -> "A tradução demorou demais. Prepare os modelos com check.py --warmup antes de abrir o capítulo."
                    else -> null
                }
                if (help != null) throw app.mangalate.local.FriendlyException(help)
                val msg = String(bytes.take(300).toByteArray()).ifBlank { response.message }
                throw IOException("Servidor respondeu ${response.code}: $msg")
            }
            val type = response.header("Content-Type").orEmpty()
            if (!type.startsWith("image/") && !looksLikeImage(bytes)) {
                throw IOException("Resposta inesperada do servidor: ${String(bytes.take(200).toByteArray())}")
            }
            return bytes
        }
    }

    private fun authHeaders(s: MangalateSettings): Map<String, String> =
        if (s.accessKey.isBlank()) {
            emptyMap()
        } else {
            mapOf(
                "X-Mangalate-Key" to s.accessKey.trim(),
                "Authorization" to "Bearer ${s.accessKey.trim()}",
            )
        }

    /** Testa o servidor. Retorna null em caso de sucesso ou a mensagem de erro. */
    suspend fun testConnection(s: MangalateSettings): Result<Int> = withContext(Dispatchers.IO) {
        runCatching {
            val request = Request.Builder()
                .url(s.normalizedUrl + "/queue-size")
                .post(ByteArray(0).toRequestBody(null))
                .apply { authHeaders(s).forEach { (k, v) -> header(k, v) } }
                .build()
            client.newBuilder()
                .callTimeout(20, TimeUnit.SECONDS)
                .readTimeout(20, TimeUnit.SECONDS)
                .build()
                .newCall(request)
                .execute()
                .use { response ->
                    val text = response.body.string()
                    if (response.code == 401 || response.code == 403) {
                        throw IOException("Chave de acesso recusada (${response.code})")
                    }
                    if (!response.isSuccessful) throw IOException("HTTP ${response.code}")
                    text.trim().toIntOrNull() ?: 0
                }
        }
    }

    // region Cache

    private fun cacheDir(context: Context): File =
        File(context.applicationContext.cacheDir, CACHE_DIR).apply { mkdirs() }

    /** Páginas de capítulos baixados: não são apagadas automaticamente (leitura offline). */
    private fun offlineDir(context: Context): File =
        File(context.applicationContext.filesDir, "mangalate_offline").apply { mkdirs() }

    fun offlineSize(context: Context): Long =
        offlineDir(context).listFiles()?.sumOf { it.length() } ?: 0L

    fun clearOffline(context: Context) {
        offlineDir(context).listFiles()?.forEach { it.delete() }
    }

    private fun writeCache(context: Context, file: File, bytes: ByteArray) {
        file.parentFile?.mkdirs()
        runCatching {
            val tmp = File(file.parentFile, file.name + ".tmp")
            tmp.writeBytes(bytes)
            tmp.renameTo(file)
        }
        scope.launch { trimCache(context) }
    }

    private fun trimCache(context: Context) {
        val files = cacheDir(context).listFiles()?.filter { it.isFile } ?: return
        var total = files.sumOf { it.length() }
        if (total <= MAX_CACHE_BYTES) return
        for (f in files.sortedBy { it.lastModified() }) {
            if (total <= MAX_CACHE_BYTES * 8 / 10) break
            total -= f.length()
            f.delete()
        }
    }

    fun cacheSize(context: Context): Long =
        cacheDir(context).listFiles()?.sumOf { it.length() } ?: 0L

    fun clearCache(context: Context) {
        cacheDir(context).listFiles()?.forEach { it.delete() }
    }

    // endregion

    private fun notifyError(context: Context, e: Throwable) {
        val now = System.currentTimeMillis()
        if (now - lastErrorToastAt < 8_000) return
        lastErrorToastAt = now
        val app = context.applicationContext
        val msg = when (e) {
            is app.mangalate.local.FriendlyException -> "Mangalate: ${e.message}"
            is java.net.UnknownHostException -> "Mangalate: sem internet para traduzir esta página"
            else -> "Mangalate: não foi possível traduzir (${e.message ?: e.javaClass.simpleName})"
        }
        mainHandler.post { Toast.makeText(app, msg, Toast.LENGTH_LONG).show() }
    }

    private fun sniffMime(b: ByteArray): String = when {
        b.size > 3 && b[0] == 0xFF.toByte() && b[1] == 0xD8.toByte() -> "image/jpeg"
        b.size > 8 && b[0] == 0x89.toByte() && b[1] == 'P'.code.toByte() -> "image/png"
        b.size > 12 && String(b, 8, 4, Charsets.US_ASCII) == "WEBP" -> "image/webp"
        b.size > 3 && b[0] == 'G'.code.toByte() && b[1] == 'I'.code.toByte() -> "image/gif"
        b.size > 2 && b[0] == 'B'.code.toByte() && b[1] == 'M'.code.toByte() -> "image/bmp"
        else -> "image/png"
    }

    private fun looksLikeImage(b: ByteArray) = sniffMime(b) != "image/png" ||
        (b.size > 8 && b[0] == 0x89.toByte() && b[1] == 'P'.code.toByte())

    private fun sha256(data: ByteArray): String =
        MessageDigest.getInstance("SHA-256").digest(data).joinToString("") { "%02x".format(it) }
}
