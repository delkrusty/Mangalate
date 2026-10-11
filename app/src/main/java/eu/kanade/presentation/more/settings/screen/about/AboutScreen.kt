package eu.kanade.presentation.more.settings.screen.about

import android.content.Context
import androidx.compose.runtime.Composable
import app.mangalate.ui.MangalateAboutContent
import eu.kanade.domain.ui.UiPreferences
import eu.kanade.presentation.util.Screen
import eu.kanade.tachiyomi.BuildConfig
import eu.kanade.tachiyomi.util.lang.toDateTimestampString
import kotlinx.datetime.TimeZone
import kotlinx.datetime.toLocalDateTime
import mihon.app.di.appGraph
import uy.kohesive.injekt.Injekt
import uy.kohesive.injekt.api.get
import kotlin.time.Instant

/** Mantém o destino de navegação e os helpers de versão, com conteúdo próprio. */
object AboutScreen : Screen() {
    @Composable
    override fun Content() = MangalateAboutContent()

    fun getVersionName(withBuildDate: Boolean): String {
        val version = "Mangalate v${BuildConfig.VERSION_NAME}" +
            if (BuildConfig.DEBUG) " (${BuildConfig.COMMIT_SHA})" else ""
        return if (withBuildDate) "$version (${getFormattedBuildTime()})" else version
    }

    internal fun getFormattedBuildTime(): String = try {
        Instant.parse(BuildConfig.BUILD_TIME)
            .toLocalDateTime(TimeZone.currentSystemDefault())
            .toDateTimestampString(
                UiPreferences.dateFormat(Injekt.get<Context>().appGraph.uiPreferences.dateFormat.get()),
            )
    } catch (_: Exception) {
        BuildConfig.BUILD_TIME
    }
}
