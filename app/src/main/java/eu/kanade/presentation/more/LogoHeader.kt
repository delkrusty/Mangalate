package eu.kanade.presentation.more

import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import app.mangalate.ui.MangalateBrandHeader
import androidx.compose.foundation.layout.Box

@Composable
fun LogoHeader(
    iconPadding: PaddingValues = PaddingValues(),
) {
    Box(modifier = Modifier.padding(iconPadding)) {
        MangalateBrandHeader()
    }
}
