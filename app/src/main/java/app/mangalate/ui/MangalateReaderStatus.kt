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
import app.mangalate.translate.MangalateTranslator
import mihon.icons.materialsymbols.MaterialSymbols
import mihon.icons.materialsymbols.rounded.Translate

/**
 * Pílula discreta exibida no canto do leitor enquanto páginas estão sendo traduzidas.
 */
@Composable
fun MangalateReaderStatus(modifier: Modifier = Modifier) {
    val enabled by MangalateTranslator.enabled.collectAsState()
    val jobs by MangalateTranslator.activeJobs.collectAsState()
    val status by MangalateTranslator.status.collectAsState()

    AnimatedVisibility(
        visible = enabled && jobs > 0,
        modifier = modifier,
        enter = fadeIn() + slideInVertically { -it },
        exit = fadeOut() + slideOutVertically { -it },
    ) {
        Surface(
            shape = RoundedCornerShape(50),
            color = MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.94f),
            contentColor = MaterialTheme.colorScheme.onPrimaryContainer,
            tonalElevation = 3.dp,
            shadowElevation = 4.dp,
        ) {
            Row(
                modifier = Modifier.padding(horizontal = 12.dp, vertical = 7.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Icon(
                    imageVector = MaterialSymbols.Rounded.Translate,
                    contentDescription = null,
                    modifier = Modifier.size(16.dp),
                )
                Text(
                    text = status ?: if (jobs == 1) "Traduzindo página…" else "Traduzindo $jobs páginas…",
                    style = MaterialTheme.typography.labelMedium,
                )
                CircularProgressIndicator(
                    modifier = Modifier.size(14.dp),
                    strokeWidth = 2.dp,
                    color = MaterialTheme.colorScheme.onPrimaryContainer,
                )
            }
        }
    }
}
