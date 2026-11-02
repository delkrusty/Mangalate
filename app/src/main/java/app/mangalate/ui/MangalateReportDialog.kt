package app.mangalate.ui

import android.widget.Toast
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
import app.mangalate.translate.MangalateServerLoop
import eu.kanade.tachiyomi.ui.reader.model.ReaderPage
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch

/**
 * "Reportar esta página": manda o original e a tradução para a pasta `relatorios` do
 * servidor, no computador, para conferir depois. Nada vai para a internet.
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
                    "O original e a tradução desta página vão para a pasta relatorios do servidor, no seu " +
                        "computador. Nada é enviado para a internet.",
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
                            val folder = MangalateServerLoop.report(context, page, note)
                            Toast.makeText(context, "Página salva no computador: relatorios/$folder", Toast.LENGTH_LONG).show()
                            onDismissRequest()
                        } catch (e: CancellationException) {
                            throw e
                        } catch (e: Throwable) {
                            error = e.message ?: "Não foi possível enviar."
                        }
                        sending = false
                    }
                },
            ) { Text(if (sending) "Enviando…" else "Enviar") }
        },
        dismissButton = { TextButton(enabled = !sending, onClick = onDismissRequest) { Text("Cancelar") } },
    )
}
