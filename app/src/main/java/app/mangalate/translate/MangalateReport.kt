package app.mangalate.translate

import android.content.Context
import android.content.Intent
import androidx.core.content.FileProvider
import eu.kanade.tachiyomi.BuildConfig
import eu.kanade.tachiyomi.ui.reader.model.ReaderPage
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.IOException
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

/**
 * "Reportar esta página": junta o original, a tradução guardada e uma nota num `.zip` e abre o
 * app de e-mail já endereçado ao Mangalate. A pessoa confere e envia; nada sai sem o toque dela.
 * O pacote nunca leva a Chave Mangalate nem o endereço do servidor.
 */
object MangalateReport {

    const val ADDRESS = "mangalate.report@gmail.com"

    /** Nomes fixos dentro do pacote, os mesmos que o servidor grava em `relatorios/`. */
    const val ORIGINAL = "original"
    const val TRANSLATED = "traduzida"
    const val INFO = "info.json"

    data class Info(
        val work: PageWork?,
        val note: String,
        val mode: TranslateMode,
        val sourceLanguage: SourceLanguage,
        val targetLanguage: TargetLanguage,
        val appVersion: String,
        val hasTranslation: Boolean,
    ) {
        fun toJson(): String = JSONObject()
            .put("obra", work?.work?.take(200) ?: "")
            .put("capitulo", work?.chapter?.take(200) ?: "")
            .put("pagina", work?.page ?: 0)
            .put("nota", note.take(500))
            .put("modo", mode.name)
            .put("idioma_origem", sourceLanguage.name)
            .put("idioma_destino", targetLanguage.code)
            .put("versao_app", appVersion)
            .put("tem_traducao", hasTranslation)
            .toString(2)
    }

    /** O pacote em si, sem nada de Android, para o teste conferir o conteúdo. */
    fun zip(original: ByteArray, translated: ByteArray?, info: Info): ByteArray {
        val out = ByteArrayOutputStream()
        ZipOutputStream(out).use { zip ->
            fun put(name: String, bytes: ByteArray) {
                zip.putNextEntry(ZipEntry(name))
                zip.write(bytes)
                zip.closeEntry()
            }
            put(ORIGINAL + extension(original), original)
            translated?.let { put(TRANSLATED + extension(it), it) }
            put(INFO, info.toJson().toByteArray())
        }
        return out.toByteArray()
    }

    fun subject(work: PageWork?): String =
        "Mangalate: página com erro" + (work?.let { " (${it.work.take(60)}, p. ${it.page})" } ?: "")

    /**
     * Monta o pacote e devolve o pedido para abrir o e-mail. A tradução vem só da que ficou
     * guardada: reportar nunca traduz de novo nem gasta a cota das IAs.
     */
    suspend fun prepare(context: Context, page: ReaderPage, note: String): Intent = withContext(Dispatchers.IO) {
        val s = MangalateTranslator.settings.value
        val stream = page.stream ?: throw IOException("A página ainda não carregou.")
        val original = stream().use { it.readBytes() }
        val language = MangalateWork.language(context, MangalateWork.mangaIdOf(page))
        val translated = MangalateTranslator.cached(context, original, sourceLanguage = language)
        val work = MangalateWork.of(page)
        val info = Info(
            work = work,
            note = note,
            mode = s.mode,
            sourceLanguage = language,
            targetLanguage = s.targetLanguage,
            appVersion = BuildConfig.VERSION_NAME,
            hasTranslation = translated != null,
        )

        // Só o último pacote fica guardado; o anterior já foi enviado ou desistido.
        val dir = File(context.cacheDir, "mangalate_report").apply {
            deleteRecursively()
            mkdirs()
        }
        val file = File(dir, "mangalate-relatorio-${System.currentTimeMillis()}.zip")
        file.writeBytes(zip(original, translated, info))
        val uri = FileProvider.getUriForFile(context, "${BuildConfig.APPLICATION_ID}.provider", file)

        val body = buildString {
            appendLine("Página reportada pelo Mangalate ${BuildConfig.VERSION_NAME}.")
            if (note.isNotBlank()) appendLine().appendLine(note.take(500))
            appendLine().append("O pacote anexado tem o original, a tradução e as informações da página.")
        }
        val send = Intent(Intent.ACTION_SEND).apply {
            type = "application/zip"
            putExtra(Intent.EXTRA_EMAIL, arrayOf(ADDRESS))
            putExtra(Intent.EXTRA_SUBJECT, subject(work))
            putExtra(Intent.EXTRA_TEXT, body)
            putExtra(Intent.EXTRA_STREAM, uri)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        Intent.createChooser(send, "Enviar relatório por e-mail").apply {
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
    }

    private fun extension(bytes: ByteArray): String = when {
        bytes.size >= 3 && bytes[0] == 0xFF.toByte() && bytes[1] == 0xD8.toByte() -> ".jpg"
        bytes.size >= 4 && bytes[0] == 0x89.toByte() && bytes[1] == 'P'.code.toByte() -> ".png"
        bytes.size >= 12 && String(bytes, 8, 4, Charsets.US_ASCII) == "WEBP" -> ".webp"
        bytes.size >= 3 && String(bytes, 0, 3, Charsets.US_ASCII) == "GIF" -> ".gif"
        else -> ".img"
    }
}
