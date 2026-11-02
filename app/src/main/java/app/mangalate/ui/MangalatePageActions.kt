package app.mangalate.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import app.mangalate.translate.MangalateReaderPages
import app.mangalate.translate.MangalateTranslator
import app.mangalate.translate.MangalateWork
import app.mangalate.translate.SourceLanguage
import app.mangalate.translate.TranslateMode
import eu.kanade.tachiyomi.ui.reader.model.ReaderPage
import mihon.icons.materialsymbols.MaterialSymbols
import mihon.icons.materialsymbols.rounded.Autorenew
import mihon.icons.materialsymbols.rounded.BugReport
import mihon.icons.materialsymbols.rounded.EditNote
import mihon.icons.materialsymbols.rounded.Image
import mihon.icons.materialsymbols.rounded.Refresh
import mihon.icons.materialsymbols.rounded.Translate
import tachiyomi.presentation.core.components.ActionButton
import tachiyomi.presentation.core.components.material.padding

/**
 * Ações de tradução no menu que abre ao segurar o dedo na página: ver o original só
 * desta página, refazer a página ou o capítulo, no servidor os nomes da obra e reportar
 * a página e, no celular, o idioma desta obra.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun MangalatePageActions(page: ReaderPage, onDismissRequest: () -> Unit) {
    val context = LocalContext.current
    val enabled by MangalateTranslator.enabled.collectAsState()
    val settings by MangalateTranslator.settings.collectAsState()
    val original by MangalateReaderPages.original.collectAsState()
    if (!enabled) return

    val showingOriginal = MangalateReaderPages.keyOf(page) in original
    Column(
        modifier = Modifier.padding(bottom = 16.dp),
        verticalArrangement = Arrangement.spacedBy(MaterialTheme.padding.small),
    ) {
        Row(horizontalArrangement = Arrangement.spacedBy(MaterialTheme.padding.small)) {
            ActionButton(
                modifier = Modifier.weight(1f),
                title = if (showingOriginal) "Ver tradução" else "Ver original",
                icon = if (showingOriginal) MaterialSymbols.Rounded.Translate else MaterialSymbols.Rounded.Image,
                onClick = {
                    MangalateReaderPages.toggleOriginal(page)
                    onDismissRequest()
                },
            )
            ActionButton(
                modifier = Modifier.weight(1f),
                title = "Refazer página",
                icon = MaterialSymbols.Rounded.Refresh,
                onClick = {
                    MangalateReaderPages.redoPage(page)
                    onDismissRequest()
                },
            )
            ActionButton(
                modifier = Modifier.weight(1f),
                title = "Refazer capítulo",
                icon = MaterialSymbols.Rounded.Autorenew,
                onClick = {
                    MangalateReaderPages.redoChapter(page)
                    onDismissRequest()
                },
            )
        }
        // Glossário e relatório ficam no servidor; no celular não há onde guardar.
        val work = MangalateWork.of(page)?.work
        if (settings.mode == TranslateMode.SERVER) {
            var showGlossary by remember { mutableStateOf(false) }
            var showReport by remember { mutableStateOf(false) }
            Row(horizontalArrangement = Arrangement.spacedBy(MaterialTheme.padding.small)) {
                if (work != null) {
                    ActionButton(
                        modifier = Modifier.weight(1f),
                        title = "Nomes da obra",
                        icon = MaterialSymbols.Rounded.EditNote,
                        onClick = { showGlossary = true },
                    )
                }
                ActionButton(
                    modifier = Modifier.weight(1f),
                    title = "Reportar página",
                    icon = MaterialSymbols.Rounded.BugReport,
                    onClick = { showReport = true },
                )
            }
            if (showGlossary && work != null) {
                MangalateGlossaryDialog(work, onDismissRequest = { showGlossary = false })
            }
            if (showReport) {
                MangalateReportDialog(page, onDismissRequest = { showReport = false })
            }
        }
        // Só o OCR do celular precisa saber o idioma; o servidor reconhece sozinho.
        if (settings.mode == TranslateMode.ON_DEVICE) {
            val mangaId = MangalateWork.mangaIdOf(page)
            if (mangaId != null) {
                var language by remember(mangaId) { mutableStateOf(MangalateWork.language(context, mangaId)) }
                Text(
                    "Esta obra está em",
                    style = MaterialTheme.typography.labelLarge,
                    modifier = Modifier.padding(horizontal = 16.dp),
                )
                FlowRow(
                    modifier = Modifier.padding(horizontal = 16.dp),
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    SourceLanguage.entries.forEach { lang ->
                        FilterChip(
                            selected = language == lang,
                            onClick = {
                                if (language != lang) {
                                    MangalateWork.setLanguage(context, mangaId, lang)
                                    language = lang
                                    MangalateReaderPages.refreshChapter(page)
                                }
                            },
                            label = { Text(lang.label) },
                        )
                    }
                }
            }
        }
    }
}
