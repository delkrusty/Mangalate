package app.mangalate.translate

import java.net.URLDecoder

/**
 * O QR code que o `parear.py` mostra no computador: endereço do servidor e Chave Mangalate.
 * Formato: `mangalate://parear?url=http%3A%2F%2FIP%3A5003&chave=...`.
 */
object MangalatePairing {

    private const val PREFIX = "mangalate://parear?"
    private const val MIN_KEY = 24

    data class Pairing(val url: String, val key: String)

    /** Endereço e chave lidos do QR code; null se o texto não é um QR code do Mangalate. */
    fun parse(text: String?): Pairing? {
        val value = text?.trim() ?: return null
        if (!value.startsWith(PREFIX)) return null
        val fields = value.removePrefix(PREFIX).split('&').mapNotNull { part ->
            val name = part.substringBefore('=', "")
            if (name.isEmpty()) return@mapNotNull null
            name to runCatching { URLDecoder.decode(part.substringAfter('='), "UTF-8") }.getOrNull()
        }.toMap()
        val url = fields["url"]?.trim().orEmpty()
        val key = fields["chave"]?.trim().orEmpty()
        if (!(url.startsWith("http://") || url.startsWith("https://")) || url.any { it.isWhitespace() }) return null
        if (key.length < MIN_KEY || key.any { it.isWhitespace() }) return null
        return Pairing(url, key)
    }
}
