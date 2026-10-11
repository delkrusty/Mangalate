package app.mangalate.ui

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import app.mangalate.translate.MangalateTranslator
import app.mangalate.translate.SourceLanguage
import app.mangalate.translate.TargetLanguage
import app.mangalate.translate.TranslateMode
import mihon.icons.materialsymbols.MaterialSymbols
import mihon.icons.materialsymbols.rounded.Translate

/**
 * Assistente mostrado na primeira vez que o leitor toca em traduzir.
 * Com os padrões, basta tocar em "Traduzir".
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun MangalateQuickSetupDialog(
    onDismiss: () -> Unit,
    onStart: () -> Unit,
) {
    val context = LocalContext.current
    val uriHandler = LocalUriHandler.current
    val settings by MangalateTranslator.settings.collectAsState()

    AlertDialog(
        onDismissRequest = onDismiss,
        icon = { Icon(MaterialSymbols.Rounded.Translate, contentDescription = null) },
        title = { Text("Traduzir mangá") },
        text = {
            Column(
                modifier = Modifier.verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                Text("O mangá está em", style = MaterialTheme.typography.labelLarge)
                FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    SourceLanguage.entries.forEach { lang ->
                        FilterChip(
                            selected = settings.sourceLanguage == lang,
                            onClick = { MangalateTranslator.updateSettings(context) { it.copy(sourceLanguage = lang) } },
                            label = { Text(lang.label) },
                        )
                    }
                }
                Text("Traduzir para", style = MaterialTheme.typography.labelLarge)
                FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    listOf(TargetLanguage.PT_BR, TargetLanguage.EN, TargetLanguage.ES).forEach { lang ->
                        FilterChip(
                            selected = settings.targetLanguage == lang,
                            onClick = { MangalateTranslator.updateSettings(context) { it.copy(targetLanguage = lang) } },
                            label = { Text(lang.label) },
                        )
                    }
                }
                Text("Qualidade", style = MaterialTheme.typography.labelLarge)
                listOf(TranslateMode.ON_DEVICE, TranslateMode.GEMINI).forEach { mode ->
                    val selected = settings.mode == mode
                    Surface(
                        shape = RoundedCornerShape(16.dp),
                        color = if (selected) {
                            MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.5f)
                        } else {
                            MaterialTheme.colorScheme.surfaceContainerHigh
                        },
                        border = BorderStroke(2.dp, if (selected) MaterialTheme.colorScheme.primary else Color.Transparent),
                        modifier = Modifier
                            .fillMaxWidth()
                            .clickable { MangalateTranslator.updateSettings(context) { it.copy(mode = mode) } },
                    ) {
                        Row(Modifier.padding(6.dp), verticalAlignment = Alignment.CenterVertically) {
                            RadioButton(
                                selected = selected,
                                onClick = { MangalateTranslator.updateSettings(context) { it.copy(mode = mode) } },
                            )
                            Column {
                                Text(
                                    if (mode == TranslateMode.ON_DEVICE) "Grátis, no celular" else "Melhor, com Gemini",
                                    fontWeight = FontWeight.SemiBold,
                                )
                                Text(
                                    if (mode == TranslateMode.ON_DEVICE) {
                                        "Pronto para usar. Boa para inglês; razoável para japonês."
                                    } else {
                                        "Tradução natural com contexto. Precisa de uma chave grátis do Google."
                                    },
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                        }
                    }
                }
                if (settings.mode == TranslateMode.GEMINI) {
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        FilledTonalButton(onClick = { uriHandler.openUri("https://aistudio.google.com/apikey") }) {
                            Text("Pegar chave")
                        }
                        FilledTonalButton(
                            onClick = {
                                val cm = context.getSystemService(android.content.Context.CLIPBOARD_SERVICE)
                                    as android.content.ClipboardManager
                                val text = cm.primaryClip?.getItemAt(0)?.coerceToText(context)?.toString()?.trim()
                                if (!text.isNullOrBlank()) {
                                    MangalateTranslator.updateSettings(context) { it.copy(geminiKey = text) }
                                }
                            },
                        ) { Text("Colar chave") }
                    }
                    OutlinedTextField(
                        value = settings.geminiKey,
                        onValueChange = { v -> MangalateTranslator.updateSettings(context) { it.copy(geminiKey = v.trim()) } },
                        label = { Text("Chave do Gemini") },
                        singleLine = true,
                        visualTransformation = PasswordVisualTransformation(),
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
                Text(
                    "Você pode mudar tudo depois em Configurações › Mangalate.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        },
        confirmButton = {
            Button(
                enabled = settings.isConfigured,
                onClick = {
                    MangalateTranslator.updateSettings(context) { it.copy(setupDone = true) }
                    onStart()
                },
            ) { Text("Traduzir") }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("Agora não") }
        },
    )
}
