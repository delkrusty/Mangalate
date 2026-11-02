package app.mangalate.ui

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.animateContentSize
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
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
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import app.mangalate.translate.MangalateReaderPages
import app.mangalate.translate.MangalateReaderPages.Problem
import app.mangalate.translate.MangalateTranslator
import app.mangalate.translate.PageReview
import eu.kanade.tachiyomi.ui.reader.model.ReaderPage
import kotlinx.coroutines.delay
import mihon.icons.materialsymbols.MaterialSymbols
import mihon.icons.materialsymbols.rounded.CloudOff
import mihon.icons.materialsymbols.rounded.Error
import mihon.icons.materialsymbols.rounded.Info
import mihon.icons.materialsymbols.rounded.Schedule
import mihon.icons.materialsymbols.rounded.Translate

/**
 * Canto do leitor: a pílula de progresso e falhas e, embaixo, o selo da página aberta
 * quando o servidor pediu para conferir alguma fala.
 */
@Composable
fun MangalateReaderStatus(page: ReaderPage?, modifier: Modifier = Modifier) {
    Column(
        modifier = modifier,
        horizontalAlignment = Alignment.End,
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        MangalateProgressPill()
        MangalateReviewBadge(page)
    }
}

/**
 * Selo discreto da página aberta: falas que ficaram no original ou foram traduzidas sobre
 * o desenho. Um toque mostra o original desta página, para comparar.
 */
@Composable
private fun MangalateReviewBadge(page: ReaderPage?) {
    val enabled by MangalateTranslator.enabled.collectAsState()
    val reviews by MangalateReaderPages.reviews.collectAsState()
    val original by MangalateReaderPages.original.collectAsState()
    val key = page?.let(MangalateReaderPages::keyOf)
    val review = key?.let { reviews[it] }
    val showingOriginal = key != null && key in original
    // O texto aparece ao chegar na página e depois vira só o ícone, para não cobrir um balão.
    var expanded by remember(key) { mutableStateOf(true) }
    LaunchedEffect(key, review) {
        expanded = true
        delay(4_000)
        expanded = false
    }

    AnimatedVisibility(
        visible = enabled && page != null && (review != null || showingOriginal),
        enter = fadeIn(),
        exit = fadeOut(),
    ) {
        Surface(
            onClick = { page?.let(MangalateReaderPages::toggleOriginal) },
            shape = RoundedCornerShape(50),
            color = MaterialTheme.colorScheme.surfaceContainerHigh.copy(alpha = 0.9f),
            contentColor = MaterialTheme.colorScheme.onSurfaceVariant,
            tonalElevation = 2.dp,
        ) {
            val text = if (showingOriginal) "Original · tocar para voltar" else reviewText(review)
            Row(
                modifier = Modifier
                    .animateContentSize()
                    .padding(horizontal = if (expanded || showingOriginal) 10.dp else 5.dp, vertical = 5.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                Icon(MaterialSymbols.Rounded.Info, contentDescription = text, modifier = Modifier.size(14.dp))
                if (expanded || showingOriginal) {
                    Text(text = text, style = MaterialTheme.typography.labelSmall)
                }
            }
        }
    }
}

/** Texto do selo; [review] nulo só acontece enquanto a página mostra o original. */
internal fun reviewText(review: PageReview?): String {
    val preserved = review?.preserved ?: 0
    val parts = buildList {
        if (preserved > 0) add(if (preserved == 1) "1 fala ficou no original" else "$preserved falas ficaram no original")
        if ((review?.overArt ?: 0) > 0) add("fala sobre o desenho")
    }
    return parts.joinToString(" · ").ifEmpty { "Conferir" } + " · tocar para comparar"
}

@Composable
private fun MangalateProgressPill() {
    val enabled by MangalateTranslator.enabled.collectAsState()
    val jobs by MangalateTranslator.activeJobs.collectAsState()
    val status by MangalateTranslator.status.collectAsState()
    val failures by MangalateReaderPages.failures.collectAsState()

    AnimatedVisibility(
        visible = enabled && (jobs > 0 || failures.isNotEmpty()),
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
