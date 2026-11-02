package app.mangalate.ui

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import app.mangalate.translate.MangalateReaderPages
import app.mangalate.translate.MangalateReaderPages.Problem
import app.mangalate.translate.MangalateTranslator
import mihon.icons.materialsymbols.MaterialSymbols
import mihon.icons.materialsymbols.rounded.CloudOff
import mihon.icons.materialsymbols.rounded.Error
import mihon.icons.materialsymbols.rounded.Schedule
import mihon.icons.materialsymbols.rounded.Translate

/**
 * Pílula discreta no canto do leitor: mostra as páginas sendo traduzidas e, quando
 * alguma fica sem tradução, o motivo, com toque para tentar de novo.
 */
@Composable
fun MangalateReaderStatus(modifier: Modifier = Modifier) {
    val enabled by MangalateTranslator.enabled.collectAsState()
    val jobs by MangalateTranslator.activeJobs.collectAsState()
    val status by MangalateTranslator.status.collectAsState()
    val failures by MangalateReaderPages.failures.collectAsState()

    AnimatedVisibility(
        visible = enabled && (jobs > 0 || failures.isNotEmpty()),
        modifier = modifier,
        enter = fadeIn() + slideInVertically { -it },
        exit = fadeOut() + slideOutVertically { -it },
    ) {
        val failed = jobs == 0 && failures.isNotEmpty()
        Surface(
            onClick = MangalateReaderPages::retryFailed,
            enabled = failures.isNotEmpty(),
            shape = RoundedCornerShape(50),
            color = if (failed) {
                MaterialTheme.colorScheme.errorContainer.copy(alpha = 0.94f)
            } else {
                MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.94f)
            },
            contentColor = if (failed) {
                MaterialTheme.colorScheme.onErrorContainer
            } else {
                MaterialTheme.colorScheme.onPrimaryContainer
            },
            tonalElevation = 3.dp,
            shadowElevation = 4.dp,
        ) {
            Row(
                modifier = Modifier.padding(horizontal = 12.dp, vertical = 7.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                val icon = when {
                    !failed -> MaterialSymbols.Rounded.Translate
                    Problem.LIMIT in failures.values -> MaterialSymbols.Rounded.Schedule
                    Problem.OFFLINE in failures.values -> MaterialSymbols.Rounded.CloudOff
                    else -> MaterialSymbols.Rounded.Error
                }
                Icon(imageVector = icon, contentDescription = null, modifier = Modifier.size(16.dp))
                Text(
                    text = if (failed) failureText(failures.values) else progressText(jobs, status, failures.size),
                    style = MaterialTheme.typography.labelMedium,
                )
                if (!failed) {
                    CircularProgressIndicator(
                        modifier = Modifier.size(14.dp),
                        strokeWidth = 2.dp,
                        color = MaterialTheme.colorScheme.onPrimaryContainer,
                    )
                }
            }
        }
    }
}

internal fun progressText(jobs: Int, status: String?, failed: Int): String {
    val base = status ?: if (jobs == 1) "Traduzindo página…" else "Traduzindo $jobs páginas…"
    return if (failed > 0) "$base · ${pages(failed)} sem tradução" else base
}

/** Texto para quando nenhuma página está sendo traduzida e alguma ficou sem tradução. */
internal fun failureText(problems: Collection<Problem>): String {
    val count = pages(problems.size)
    return when {
        Problem.LIMIT in problems -> "IA no limite grátis · tenta de novo sozinha"
        Problem.OFFLINE in problems -> "Sem conexão · $count sem tradução · tocar para tentar"
        else -> "$count sem tradução · tocar para tentar"
    }
}

private fun pages(n: Int) = if (n == 1) "1 página" else "$n páginas"
