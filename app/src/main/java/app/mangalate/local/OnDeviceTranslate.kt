package app.mangalate.local

import app.mangalate.translate.SourceLanguage
import app.mangalate.translate.TargetLanguage
import com.google.mlkit.common.model.DownloadConditions
import com.google.mlkit.nl.translate.TranslateLanguage
import com.google.mlkit.nl.translate.Translation
import com.google.mlkit.nl.translate.Translator
import com.google.mlkit.nl.translate.TranslatorOptions

/**
 * Tradução offline do ML Kit. Os modelos de idioma são baixados uma única vez.
 */
object OnDeviceTranslate {

    private val translators = HashMap<String, Translator>()
    private val ready = HashSet<String>()

    private fun src(l: SourceLanguage) = when (l) {
        SourceLanguage.JA -> TranslateLanguage.JAPANESE
        SourceLanguage.KO -> TranslateLanguage.KOREAN
        SourceLanguage.ZH -> TranslateLanguage.CHINESE
        SourceLanguage.EN -> TranslateLanguage.ENGLISH
    }

    private fun dst(l: TargetLanguage) = when (l) {
        TargetLanguage.PT_BR -> TranslateLanguage.PORTUGUESE
        TargetLanguage.EN -> TranslateLanguage.ENGLISH
        TargetLanguage.ES -> TranslateLanguage.SPANISH
        TargetLanguage.FR -> TranslateLanguage.FRENCH
        TargetLanguage.DE -> TranslateLanguage.GERMAN
        TargetLanguage.IT -> TranslateLanguage.ITALIAN
        TargetLanguage.RU -> TranslateLanguage.RUSSIAN
        TargetLanguage.JA -> TranslateLanguage.JAPANESE
        TargetLanguage.KO -> TranslateLanguage.KOREAN
        TargetLanguage.ZH -> TranslateLanguage.CHINESE
    }

    suspend fun translate(
        texts: List<String>,
        source: SourceLanguage,
        target: TargetLanguage,
        onDownload: () -> Unit,
    ): List<String> {
        val s = src(source)
        val d = dst(target)
        if (s == d) return texts
        val key = "$s>$d"
        val translator = synchronized(translators) {
            translators.getOrPut(key) {
                Translation.getClient(TranslatorOptions.Builder().setSourceLanguage(s).setTargetLanguage(d).build())
            }
        }
        if (key !in ready) {
            onDownload()
            translator.downloadModelIfNeeded(DownloadConditions.Builder().build()).awaitTask()
            synchronized(ready) { ready += key }
        }
        return texts.map { t -> runCatching { translator.translate(t).awaitTask() }.getOrDefault(t) }
    }
}
