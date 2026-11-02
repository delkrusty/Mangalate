package app.mangalate.translate

import app.mangalate.translate.MangalateReaderPages.Problem
import app.mangalate.ui.failureText
import app.mangalate.ui.progressText
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

/**
 * Idioma da obra sugerido pela extensão e textos do indicador do leitor.
 */
class WorkLanguageTest {

    @Test
    fun `idioma da extensao vira o idioma da obra`() {
        assertEquals(SourceLanguage.JA, SourceLanguage.fromSourceLang("ja"))
        assertEquals(SourceLanguage.KO, SourceLanguage.fromSourceLang("ko"))
        assertEquals(SourceLanguage.ZH, SourceLanguage.fromSourceLang("zh-Hans"))
        assertEquals(SourceLanguage.ZH, SourceLanguage.fromSourceLang("zh_TW"))
        assertEquals(SourceLanguage.EN, SourceLanguage.fromSourceLang("EN"))
    }

    @Test
    fun `extensao de varios idiomas ou de outro idioma nao sugere nada`() {
        for (lang in listOf("all", "pt-BR", "es", "", null)) {
            assertNull(SourceLanguage.fromSourceLang(lang), "$lang")
        }
    }

    @Test
    fun `idioma escolhido vence a extensao, que vence o sugerido e o padrao`() {
        val ja = SourceLanguage.JA
        assertEquals(SourceLanguage.KO, SourceLanguage.pick("KO", "en", SourceLanguage.ZH, ja))
        assertEquals(SourceLanguage.EN, SourceLanguage.pick(null, "en", SourceLanguage.ZH, ja))
        assertEquals(SourceLanguage.ZH, SourceLanguage.pick(null, "all", SourceLanguage.ZH, ja))
        assertEquals(ja, SourceLanguage.pick("antigo", "", null, ja))
    }

    @Test
    fun `falha classificada pelo motivo`() {
        assertEquals(Problem.LIMIT, MangalateReaderPages.problemOf(ProviderLimitException("Limite gratuito")))
        assertEquals(Problem.OFFLINE, MangalateReaderPages.problemOf(java.net.UnknownHostException()))
        // Servidor lento não é falta de conexão.
        assertEquals(Problem.OTHER, MangalateReaderPages.problemOf(java.net.SocketTimeoutException()))
    }

    @Test
    fun `indicador explica o motivo da falha`() {
        assertTrue(failureText(listOf(Problem.OTHER, Problem.LIMIT)).startsWith("IA no limite"))
        assertEquals(
            "Sem conexão · 2 páginas sem tradução · tocar para tentar",
            failureText(listOf(Problem.OFFLINE, Problem.OTHER)),
        )
        assertEquals("1 página sem tradução · tocar para tentar", failureText(listOf(Problem.OTHER)))
    }

    @Test
    fun `indicador conta falhas enquanto traduz`() {
        assertEquals("Traduzindo 2 páginas…", progressText(2, null, 0))
        assertEquals("Traduzindo página… · 1 página sem tradução", progressText(1, null, 1))
    }
}
