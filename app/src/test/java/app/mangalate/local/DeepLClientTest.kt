package app.mangalate.local

import app.mangalate.translate.SourceLanguage
import app.mangalate.translate.TargetLanguage
import kotlinx.coroutines.runBlocking
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.json.JSONObject
import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test

class DeepLClientTest {
    private fun response(body: String, code: Int = 200) = MockResponse().setResponseCode(code).setBody(body)

    @Test
    fun selectsOfficialEndpoint() {
        assertEquals("https://api-free.deepl.com", DeepLApi.officialEndpoint("test:fx "))
        assertEquals("https://api.deepl.com", DeepLApi.officialEndpoint("test"))
    }

    @Test
    fun sendsCorrectAuthLanguagesAndPreservesOrder() = runBlocking {
        MockWebServer().use { server ->
            server.enqueue(response("""{"translations":[{"text":"Olá"},{"text":"Como vai?"}]}"""))
            val api = DeepLApi(endpoint = { server.url("/").toString() })
            assertEquals(listOf("Olá", "Como vai?"), api.translate(" test:fx ", listOf("Hello", "How are you?"), SourceLanguage.EN, TargetLanguage.PT_BR))
            val request = server.takeRequest()
            assertEquals("/v2/translate", request.path)
            assertEquals("DeepL-Auth-Key test:fx", request.getHeader("Authorization"))
            val body = JSONObject(request.body.readUtf8())
            assertEquals("EN", body.getString("source_lang"))
            assertEquals("PT-BR", body.getString("target_lang"))
            assertEquals(2, body.getJSONArray("text").length())
        }
    }

    @Test
    fun retriesBusyServer() = runBlocking {
        MockWebServer().use { server ->
            server.enqueue(response("{}", 429))
            server.enqueue(response("""{"translations":[{"text":"Olá"}]}"""))
            val api = DeepLApi(endpoint = { server.url("/").toString() }, retryDelay = {})
            assertEquals(listOf("Olá"), api.translate("test", listOf("Hello"), SourceLanguage.EN, TargetLanguage.PT_BR))
            assertEquals(2, server.requestCount)
        }
    }

    @Test
    fun rejectsMissingTranslationsRatherThanMixingBalloons() {
        MockWebServer().use { server ->
            server.enqueue(response("""{"translations":[{"text":"Olá"}]}"""))
            val api = DeepLApi(endpoint = { server.url("/").toString() })
            assertThrows(FriendlyException::class.java) {
                runBlocking { api.translate("test", listOf("Hello", "Bye"), SourceLanguage.EN, TargetLanguage.PT_BR) }
            }
        }
    }

    @Test
    fun explainsInvalidKeyAndQuotaWithoutLeakingKey() {
        for ((code, fragment) in listOf(403 to "chave", 456 to "cota")) {
            MockWebServer().use { server ->
                server.enqueue(response("{}", code))
                val api = DeepLApi(endpoint = { server.url("/").toString() })
                val error = assertThrows(FriendlyException::class.java) {
                    runBlocking { api.translate("secret-test-key", listOf("Hello"), SourceLanguage.EN, TargetLanguage.PT_BR) }
                }
                assertTrue(error.message!!.contains(fragment))
                assertFalse(error.message!!.contains("secret-test-key"))
            }
        }
    }

    @Test
    fun handlesUsageAndChunksPagesOver50Texts() = runBlocking {
        MockWebServer().use { server ->
            server.enqueue(response("""{"character_count":42,"character_limit":500000}"""))
            server.enqueue(response("""{"translations":[${List(50) { """{"text":"Oi"}""" }.joinToString(",")}]}"""))
            server.enqueue(response("""{"translations":[{"text":"Fim"}]}"""))
            val api = DeepLApi(endpoint = { server.url("/").toString() })
            assertEquals(42L to 500000L, api.usage("test"))
            val translated = api.translate("test", List(51) { "Hello" }, SourceLanguage.EN, TargetLanguage.PT_BR)
            assertEquals(51, translated.size)
            assertEquals("Fim", translated.last())
            assertEquals(3, server.requestCount)
        }
    }
}
