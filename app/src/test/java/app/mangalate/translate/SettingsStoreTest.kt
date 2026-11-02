package app.mangalate.translate

import android.content.SharedPreferences
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class SettingsStoreTest {

    /** Cifra de mentira: o teste só confere que a chave não fica em texto puro. */
    private object Reverse : MangalateSettingsStore.KeyCipher {
        override fun encrypt(plain: String) = "x" + plain.reversed()
        override fun decrypt(stored: String) = stored.drop(1).reversed()
    }

    private object Broken : MangalateSettingsStore.KeyCipher {
        override fun encrypt(plain: String): String = error("sem Keystore")
        override fun decrypt(stored: String): String = error("sem Keystore")
    }

    private fun legacy() = FakePrefs(
        mutableMapOf(
            "mode" to "SERVER",
            "source_lang" to "KO",
            "setup_done" to true,
            "translate_on_download" to true,
            "server_url" to "http://192.168.0.10:5003",
            "access_key" to "chave-de-teste",
            "target_lang" to "ESP",
            "ignore_outside_bubbles" to true,
            "uppercase" to true,
            "font_size_offset" to 7,
            "gemini_key" to "antiga",
            "quality" to "MAX",
            "enabled" to true,
        ),
    )

    @Test
    fun `migra os ajustes da 0_6_0 sem perder nada`() {
        val p = legacy()
        val s = MangalateSettingsStore.read(p, Reverse)

        assertEquals(TranslateMode.SERVER, s.mode)
        assertEquals(SourceLanguage.KO, s.sourceLanguage)
        assertTrue(s.setupDone)
        assertTrue(s.translateOnDownload)
        assertEquals("http://192.168.0.10:5003", s.serverUrl)
        assertEquals("chave-de-teste", s.accessKey)
        assertEquals(TargetLanguage.ES, s.targetLanguage)
        assertEquals(true, s.preserveArtText)
        assertTrue(s.uppercase)
        assertEquals(3, s.fontSizeOffset)

        // As preferências soltas saem; "enabled" fica, e a chave não fica em texto puro.
        assertEquals(setOf("settings", "access_key_protected", "enabled"), p.map.keys)
        assertFalse(p.map.values.any { it.toString().contains("chave-de-teste") })

        // A leitura seguinte vem do JSON e dá o mesmo resultado.
        assertEquals(s, MangalateSettingsStore.read(p, Reverse))
    }

    @Test
    fun `a assinatura do cache nao muda com a migracao`() {
        // A que a 0.6.0 montava para estes ajustes: as páginas já traduzidas continuam valendo.
        val p = legacy().apply { map["mode"] = "ON_DEVICE" }
        assertEquals(
            "sdk-translation-v5.1|ON_DEVICE|KO|ESP||true|true|3",
            MangalateSettingsStore.read(p, Reverse).cacheSignature(),
        )
    }

    @Test
    fun `sem Keystore a chave continua guardada como antes`() {
        val p = legacy()
        val s = MangalateSettingsStore.read(p, Broken)
        assertEquals("chave-de-teste", s.accessKey)
        assertEquals("chave-de-teste", MangalateSettingsStore.read(p, Broken).accessKey)
    }

    @Test
    fun `adiantar o proximo capitulo vem desligado e fica salvo`() {
        assertFalse(MangalateSettings().prefetchNextChapter)
        val p = FakePrefs(mutableMapOf())
        MangalateSettingsStore.write(p, MangalateSettings(prefetchNextChapter = true), Reverse)
        assertTrue(MangalateSettingsStore.read(p, Reverse).prefetchNextChapter)
    }

    @Test
    fun `instalacao nova fica com os padroes`() {
        val s = MangalateSettingsStore.read(FakePrefs(mutableMapOf()), Reverse)
        assertEquals(MangalateSettings(), s)
    }

    @Test
    fun `apagar a chave tira as duas copias`() {
        val p = legacy()
        val s = MangalateSettingsStore.read(p, Reverse)
        MangalateSettingsStore.write(p, s.copy(accessKey = ""), Reverse)
        assertFalse(p.map.containsKey("access_key_protected"))
        assertFalse(p.map.containsKey("access_key"))
        assertNull(MangalateSettingsStore.read(p, Reverse).accessKey.ifEmpty { null })
    }

    private class FakePrefs(val map: MutableMap<String, Any?>) : SharedPreferences {
        override fun getAll(): MutableMap<String, *> = map.toMutableMap()
        override fun getString(key: String, defValue: String?) = map[key] as? String ?: defValue
        override fun getStringSet(key: String, defValues: MutableSet<String>?) = defValues
        override fun getInt(key: String, defValue: Int) = map[key] as? Int ?: defValue
        override fun getLong(key: String, defValue: Long) = map[key] as? Long ?: defValue
        override fun getFloat(key: String, defValue: Float) = map[key] as? Float ?: defValue
        override fun getBoolean(key: String, defValue: Boolean) = map[key] as? Boolean ?: defValue
        override fun contains(key: String) = map.containsKey(key)
        override fun registerOnSharedPreferenceChangeListener(l: SharedPreferences.OnSharedPreferenceChangeListener?) = Unit
        override fun unregisterOnSharedPreferenceChangeListener(l: SharedPreferences.OnSharedPreferenceChangeListener?) = Unit

        override fun edit(): SharedPreferences.Editor = object : SharedPreferences.Editor {
            private val changes = mutableMapOf<String, Any?>()
            private val removed = mutableSetOf<String>()
            override fun putString(key: String, value: String?) = apply { changes[key] = value }
            override fun putStringSet(key: String, values: MutableSet<String>?) = apply { changes[key] = values }
            override fun putInt(key: String, value: Int) = apply { changes[key] = value }
            override fun putLong(key: String, value: Long) = apply { changes[key] = value }
            override fun putFloat(key: String, value: Float) = apply { changes[key] = value }
            override fun putBoolean(key: String, value: Boolean) = apply { changes[key] = value }
            override fun remove(key: String) = apply { removed += key }
            override fun clear() = apply { removed += map.keys }
            override fun commit(): Boolean {
                apply()
                return true
            }
            override fun apply() {
                removed.forEach { map.remove(it) }
                map.putAll(changes)
            }
        }
    }
}
