package app.mangalate.local

import app.mangalate.translate.MangalateSettings
import app.mangalate.translate.TranslateMode
import app.mangalate.translate.TranslatorEngine
import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test

class ServerEditionsTest {
    @Test
    fun onlyOfflineAndServerAreSelectable() {
        assertEquals(listOf(TranslateMode.ON_DEVICE, TranslateMode.SERVER), TranslateMode.available)
    }

    @Test
    fun retiredDirectProviderPreferencesFallBackToOffline() {
        assertEquals(TranslateMode.ON_DEVICE, TranslateMode.fromName("GEMINI"))
        assertEquals(TranslateMode.ON_DEVICE, TranslateMode.fromName("DEEPL"))
    }

    @Test
    fun serverRequiresBothUrlAndOwnAccessKey() {
        val settings = MangalateSettings(mode = TranslateMode.SERVER, serverUrl = "https://example.com")
        assertFalse(settings.isConfigured)
        assertTrue(settings.copy(accessKey = "own-server-access").isConfigured)
    }

    @Test
    fun freshServerDefaultsNeverSelectAPaidTranslationProvider() {
        assertEquals(TranslatorEngine.OFFLINE, MangalateSettings().engine)
        assertEquals(TranslatorEngine.OFFLINE, TranslatorEngine.fromId(null))
        assertTrue(MangalateSettings(mode = TranslateMode.SERVER).cacheSignature().startsWith("server-scan-v1|"))
    }
}
