package app.mangalate.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import app.mangalate.translate.MangalateServerLoop
import app.mangalate.translate.MangalateServerLoop.Term
import app.mangalate.translate.MangalateTranslator
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch
import mihon.icons.materialsymbols.MaterialSymbols
import mihon.icons.materialsymbols.rounded.Add
import mihon.icons.materialsymbols.rounded.Delete

/**
 * Nomes e termos da obra que o servidor usa em todas as páginas: a pessoa corrige a
 * tradução de um nome uma vez e ela vale daqui em diante. Termo apagado não volta sozinho.
 */
@Composable
fun MangalateGlossaryDialog(work: String, onDismissRequest: () -> Unit) {
    val scope = rememberCoroutineScope()
    val terms = remember { mutableStateListOf<Term>() }
    // O que veio do servidor e o que a pessoa apagou: só as mudanças vão de volta, para não
    // bloquear um nome que outra página ensinou enquanto a lista estava aberta.
    var original by remember { mutableStateOf(emptyList<Term>()) }
    val removed = remember { mutableStateListOf<String>() }
    var loading by remember { mutableStateOf(true) }
    var loaded by remember { mutableStateOf(false) }
    var saving by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var newSource by remember { mutableStateOf("") }
    var newTarget by remember { mutableStateOf("") }

    LaunchedEffect(work) {
        try {
            original = MangalateServerLoop.glossary(MangalateTranslator.settings.value, work)
            terms.addAll(original)
            loaded = true
        } catch (e: CancellationException) {
            throw e
        } catch (e: Throwable) {
            error = e.message ?: "Não foi possível abrir o glossário."
        }
        loading = false
    }

    AlertDialog(
        onDismissRequest = onDismissRequest,
        title = { Text("Nomes e termos da obra") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(
                    "O servidor aprende os nomes enquanto traduz. Corrija aqui e a correção vale para as " +
                        "próximas páginas; para as já traduzidas, use Refazer.",
                    style = MaterialTheme.typography.bodySmall,
                )
                error?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall) }
                if (loading) {
                    CircularProgressIndicator(Modifier.size(24.dp).align(Alignment.CenterHorizontally))
                } else {
                    if (terms.isEmpty()) {
                        Text("Nenhum termo ainda.", style = MaterialTheme.typography.bodyMedium)
                    }
                    LazyColumn(
                        modifier = Modifier.heightIn(max = 320.dp),
                        verticalArrangement = Arrangement.spacedBy(6.dp),
                    ) {
                        itemsIndexed(terms, key = { _, t -> t.source }) { index, term ->
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Column(Modifier.weight(1f)) {
                                    Text(term.source, fontWeight = FontWeight.SemiBold, style = MaterialTheme.typography.labelLarge)
                                    OutlinedTextField(
                                        value = term.target,
                                        onValueChange = { terms[index] = term.copy(target = it.take(60)) },
                                        singleLine = true,
                                        modifier = Modifier.fillMaxWidth(),
                                    )
                                }
                                IconButton(
                                    onClick = {
                                        terms.removeAt(index)
                                        if (original.any { it.source == term.source }) removed.add(term.source)
                                    },
                                ) {
                                    Icon(MaterialSymbols.Rounded.Delete, contentDescription = "Apagar ${term.source}")
                                }
                            }
                        }
                    }
                    Text("Acrescentar", style = MaterialTheme.typography.labelLarge)
                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        OutlinedTextField(
                            value = newSource,
                            onValueChange = { newSource = it.take(60) },
                            label = { Text("No original") },
                            singleLine = true,
                            modifier = Modifier.weight(1f),
                        )
                        OutlinedTextField(
                            value = newTarget,
                            onValueChange = { newTarget = it.take(60) },
                            label = { Text("Na tradução") },
                            singleLine = true,
                            modifier = Modifier.weight(1f),
                        )
                        IconButton(
                            enabled = newSource.isNotBlank() && newTarget.isNotBlank(),
                            onClick = {
                                val source = newSource.trim()
                                terms.removeAll { it.source.equals(source, ignoreCase = true) }
                                removed.removeAll { it.equals(source, ignoreCase = true) }
                                terms.add(Term(source, newTarget.trim()))
                                newSource = ""
                                newTarget = ""
                            },
                        ) {
                            Icon(MaterialSymbols.Rounded.Add, contentDescription = "Acrescentar termo")
                        }
                    }
                }
            }
        },
        confirmButton = {
            TextButton(
                // Sem a lista do servidor não há o que corrigir: só depois de carregar.
                enabled = loaded && !saving,
                onClick = {
                    saving = true
                    scope.launch {
                        try {
                            // Tradução apagada sem escrever outra: o termo fica como estava.
                            MangalateServerLoop.saveGlossary(
                                MangalateTranslator.settings.value,
                                work,
                                terms.filter { it.target.isNotBlank() && it !in original },
                                removed.toList(),
                            )
                            onDismissRequest()
                        } catch (e: CancellationException) {
                            throw e
                        } catch (e: Throwable) {
                            error = e.message ?: "Não foi possível salvar."
                        }
                        saving = false
                    }
                },
            ) { Text(if (saving) "Salvando…" else "Salvar") }
        },
        dismissButton = { TextButton(onClick = onDismissRequest) { Text("Cancelar") } },
    )
}
