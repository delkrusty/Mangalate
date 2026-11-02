package app.mangalate.translate

import android.content.SharedPreferences
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import org.json.JSONObject
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * Onde os ajustes do Mangalate ficam guardados: um JSON só, na chave [SETTINGS], e a Chave
 * Mangalate à parte, cifrada com uma chave do Android Keystore.
 *
 * Até a 0.6.0 cada ajuste era uma preferência solta e a Chave Mangalate ficava em texto puro.
 * Na primeira leitura esses valores são migrados e as preferências antigas, apagadas.
 */
object MangalateSettingsStore {

    const val SETTINGS = "settings"
    private const val ACCESS_KEY = "access_key_protected"
    private const val ACCESS_KEY_PLAIN = "access_key"
    private const val KEYSTORE_ALIAS = "mangalate_access_key"

    /** Preferências da 0.6.0 que viram parte do JSON. "enabled" continua solta. */
    private val LEGACY_KEYS = listOf(
        "mode", "source_lang", "setup_done", "translate_on_download", "server_url", "target_lang",
        "preserve_art_text", "ignore_outside_bubbles", "uppercase", "font_size_offset",
        // Opções que saíram do app: chaves do Gemini e do DeepL e ajustes que o servidor ignorava.
        "gemini_key", "gemini_model", "gemini_fast", "deepl_key",
        "engine", "quality", "typeset", "mask_dilation",
    )

    fun read(p: SharedPreferences, cipher: KeyCipher = KeystoreCipher): MangalateSettings {
        val json = p.getString(SETTINGS, null)
        if (json != null) {
            return fromJson(json).copy(accessKey = readAccessKey(p, cipher))
        }
        // Primeira leitura depois da atualização: migra as preferências soltas.
        val migrated = fromLegacy(p.all)
        write(p, migrated, cipher)
        p.edit().apply { LEGACY_KEYS.forEach(::remove) }.apply()
        return migrated
    }

    /** A última chave cifrada: mexer em outro ajuste não cifra a chave de novo. */
    @Volatile
    private var savedKey: Pair<String, String>? = null

    fun write(p: SharedPreferences, s: MangalateSettings, cipher: KeyCipher = KeystoreCipher) {
        val editor = p.edit().putString(SETTINGS, toJson(s))
        val stored = p.getString(ACCESS_KEY, null)
        if (stored != null && savedKey == (s.accessKey to stored)) {
            editor.apply()
            return
        }
        val protected = s.accessKey.takeIf { it.isNotEmpty() }?.let { runCatching { cipher.encrypt(it) }.getOrNull() }
        when {
            s.accessKey.isEmpty() -> editor.remove(ACCESS_KEY).remove(ACCESS_KEY_PLAIN)
            // Sem Keystore (aparelho com defeito), a chave fica como antes para ninguém perdê-la.
            protected == null -> editor.remove(ACCESS_KEY).putString(ACCESS_KEY_PLAIN, s.accessKey)
            else -> {
                editor.putString(ACCESS_KEY, protected).remove(ACCESS_KEY_PLAIN)
                savedKey = s.accessKey to protected
            }
        }
        editor.apply()
    }

    private fun readAccessKey(p: SharedPreferences, cipher: KeyCipher): String {
        p.getString(ACCESS_KEY, null)?.let { stored ->
            runCatching { cipher.decrypt(stored) }.getOrNull()?.let {
                savedKey = it to stored
                return it
            }
        }
        return p.getString(ACCESS_KEY_PLAIN, null).orEmpty()
    }

    /** Ajustes sem a Chave Mangalate, que nunca entra no JSON. */
    fun toJson(s: MangalateSettings): String = JSONObject().apply {
        put("version", 1)
        put("mode", s.mode.name)
        put("source_lang", s.sourceLanguage.name)
        put("setup_done", s.setupDone)
        put("translate_on_download", s.translateOnDownload)
        put("server_url", s.serverUrl)
        put("target_lang", s.targetLanguage.code)
        s.preserveArtText?.let { put("preserve_art_text", it) }
        put("uppercase", s.uppercase)
        put("font_size_offset", s.fontSizeOffset.coerceIn(MangalateSettings.FONT_OFFSETS))
    }.toString()

    fun fromJson(json: String): MangalateSettings {
        val o = runCatching { JSONObject(json) }.getOrElse { JSONObject() }
        return MangalateSettings(
            mode = TranslateMode.fromName(o.optString("mode", "")),
            sourceLanguage = SourceLanguage.fromName(o.optString("source_lang", "")),
            setupDone = o.optBoolean("setup_done", false),
            translateOnDownload = o.optBoolean("translate_on_download", false),
            serverUrl = o.optString("server_url", ""),
            targetLanguage = TargetLanguage.fromCode(o.optString("target_lang", "")),
            preserveArtText = if (o.has("preserve_art_text")) o.optBoolean("preserve_art_text") else null,
            uppercase = o.optBoolean("uppercase", false),
            fontSizeOffset = o.optInt("font_size_offset", 0).coerceIn(MangalateSettings.FONT_OFFSETS),
        )
    }

    /** Lê os ajustes no formato da 0.6.0, uma preferência por ajuste. */
    fun fromLegacy(all: Map<String, *>): MangalateSettings {
        fun string(key: String) = all[key] as? String
        fun bool(key: String) = all[key] as? Boolean
        return MangalateSettings(
            mode = TranslateMode.fromName(string("mode")),
            sourceLanguage = SourceLanguage.fromName(string("source_lang")),
            setupDone = bool("setup_done") ?: false,
            translateOnDownload = bool("translate_on_download") ?: false,
            serverUrl = string("server_url").orEmpty(),
            accessKey = string(ACCESS_KEY_PLAIN).orEmpty(),
            targetLanguage = TargetLanguage.fromCode(string("target_lang")),
            // A opção antiga "Só traduzir texto dentro de balões", se ligada, vira "Preservar a arte".
            preserveArtText = bool("preserve_art_text") ?: if (bool("ignore_outside_bubbles") == true) true else null,
            uppercase = bool("uppercase") ?: false,
            fontSizeOffset = ((all["font_size_offset"] as? Int) ?: 0).coerceIn(MangalateSettings.FONT_OFFSETS),
        )
    }

    interface KeyCipher {
        fun encrypt(plain: String): String
        fun decrypt(stored: String): String
    }

    /** AES-GCM com chave que não sai do Android Keystore; o IV vai junto, antes do texto cifrado. */
    private object KeystoreCipher : KeyCipher {
        private const val TRANSFORMATION = "AES/GCM/NoPadding"

        private fun key(): SecretKey {
            val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
            (store.getKey(KEYSTORE_ALIAS, null) as? SecretKey)?.let { return it }
            val spec = KeyGenParameterSpec.Builder(
                KEYSTORE_ALIAS,
                KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
            )
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .build()
            return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
                .apply { init(spec) }
                .generateKey()
        }

        override fun encrypt(plain: String): String {
            val cipher = Cipher.getInstance(TRANSFORMATION).apply { init(Cipher.ENCRYPT_MODE, key()) }
            val data = cipher.iv + cipher.doFinal(plain.toByteArray())
            return Base64.encodeToString(data, Base64.NO_WRAP)
        }

        override fun decrypt(stored: String): String {
            val data = Base64.decode(stored, Base64.NO_WRAP)
            val cipher = Cipher.getInstance(TRANSFORMATION)
            cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, data, 0, 12))
            return String(cipher.doFinal(data, 12, data.size - 12))
        }
    }
}
