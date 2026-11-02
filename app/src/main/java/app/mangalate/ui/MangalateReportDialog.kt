package app.mangalate.ui

import android.content.ActivityNotFoundException
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import app.mangalate.translate.MangalateReport
import eu.kanade.tachiyomi.ui.reader.model.ReaderPage
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch

/**
 * "Reportar esta página": junta o original e a tradução num pacote e abre o e-mail para o
 * Mangalate. A pessoa vê o e-mail pronto e só ele envia.
 */
@Composable
fun MangalateReportDialog(page: ReaderPage, onDismissRequest: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var note by remember { mutableStateOf("") }
    var sending by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }

    AlertDialog(
        onDismissRequest = { if (!sending) onDismissRequest() },
        title = { Text("Reportar esta página") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(
                    "O original e a tradução desta página vão num e-mail para ${MangalateReport.ADDRESS}, " +
                        "para corrigir o Mangalate. Você confere o e-mail antes de enviar.",
                    style = MaterialTheme.typography.bodySmall,
                )
                OutlinedTextField(
                    value = note,
                    onValueChange = { note = it.take(500) },
                    label = { Text("O que ficou errado? (opcional)") },
                    minLines = 2,
                    modifier = Modifier.fillMaxWidth(),
                )
                error?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall) }
            }
        },
        confirmButton = {
            TextButton(
                enabled = !sending,
                onClick = {
                    sending = true
                    error = null
                    scope.launch {
                        try {
                            context.startActivity(MangalateReport.prepare(context, page, note))
                            onDismissRequest()
                        } catch (e: ActivityNotFoundException) {
                            error = "Nenhum app de e-mail encontrado no celular."
                        } catch (e: CancellationException) {
                            throw e
                        } catch (e: Throwable) {
                            error = e.message ?: "Não foi possível montar o relatório."
                        }
                        sending = false
                    }
                },
            ) { Text(if (sending) "Preparando…" else "Abrir e-mail") }
        },
        dismissButton = { TextButton(enabled = !sending, onClick = onDismissRequest) { Text("Cancelar") } },
    )
}
