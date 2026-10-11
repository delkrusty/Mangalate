package app.mangalate.local

import app.mangalate.translate.SourceLanguage
import app.mangalate.translate.TargetLanguage
import com.google.mlkit.common.model.DownloadConditions
import com.google.mlkit.nl.translate.TranslateLanguage
import com.google.mlkit.nl.translate.Translation
import com.google.mlkit.nl.translate.Translator
import com.google.mlkit.nl.translate.TranslatorOptions
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.util.concurrent.ConcurrentHashMap

/**
 * Tradução offline do ML Kit. Os modelos de idioma são baixados uma única vez.
 */
object OnDeviceTranslate {

    private class ClientState(val translator: Translator) {
        val mutex = Mutex()
        var ready = false
    }
    private val translators = ConcurrentHashMap<String, ClientState>()

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
        val state = synchronized(translators) {
            translators.getOrPut(key) {
                ClientState(Translation.getClient(TranslatorOptions.Builder().setSourceLanguage(s).setTargetLanguage(d).build()))
            }
        }
        return state.mutex.withLock {
            if (!state.ready) {
                onDownload()
                state.translator.downloadModelIfNeeded(DownloadConditions.Builder().build()).awaitTask()
                state.ready = true
            }
            // Erros não viram texto original silenciosamente nem são salvos como sucesso.
            texts.map { text -> state.translator.translate(text).awaitTask() }
        }
    }

    suspend fun prepare(source: SourceLanguage, target: TargetLanguage) {
        translate(emptyList(), source, target) {}
    }
}
