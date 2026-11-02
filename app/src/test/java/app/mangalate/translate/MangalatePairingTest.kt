package app.mangalate.translate

import org.json.JSONObject
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Test
import java.io.File

/**
 * O QR code do `parear.py`, conferido com o mesmo arquivo que `server/tests/test_reader_loop.py` lê.
 */
class MangalatePairingTest {

    private fun contract(): JSONObject {
        val path = "server/tests/app_pairing_contract.json"
        val file = generateSequence(File("").absoluteFile) { it.parentFile }
            .map { File(it, path) }
            .first { it.exists() }
        return JSONObject(file.readText())
    }

    @Test
    fun readsTheLinkTheServerShows() {
        val contract = contract()
        val pairing = MangalatePairing.parse(contract.getString("link"))
        assertEquals(contract.getString("url"), pairing?.url)
        assertEquals(contract.getString("key"), pairing?.key)
    }

    @Test
    fun ignoresOtherCodes() {
        val key = "k".repeat(32)
        assertNull(MangalatePairing.parse(null))
        assertNull(MangalatePairing.parse("https://example.com/?url=http%3A%2F%2Fx&chave=$key"))
        assertNull(MangalatePairing.parse("mangalate://parear?url=ftp%3A%2F%2Fx&chave=$key"))
        assertNull(MangalatePairing.parse("mangalate://parear?url=http%3A%2F%2Fx%3A5003&chave=curta"))
        assertNull(MangalatePairing.parse("mangalate://parear?chave=$key"))
    }
}
