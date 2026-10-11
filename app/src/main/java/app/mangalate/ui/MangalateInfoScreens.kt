package app.mangalate.ui

import android.os.Build
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import cafe.adriel.voyager.navigator.LocalNavigator
import cafe.adriel.voyager.navigator.currentOrThrow
import eu.kanade.presentation.components.AppBar
import eu.kanade.presentation.more.settings.screen.SettingsMangalateScreen
import eu.kanade.presentation.more.settings.screen.about.OpenSourceLicensesScreen
import eu.kanade.presentation.more.settings.widget.TextPreferenceWidget
import eu.kanade.presentation.util.LocalBackPress
import eu.kanade.presentation.util.Screen
import eu.kanade.tachiyomi.BuildConfig
import eu.kanade.tachiyomi.util.system.copyToClipboard
import mihon.icons.materialsymbols.MaterialSymbols
import mihon.icons.materialsymbols.rounded.KeyboardArrowDown
import mihon.icons.materialsymbols.rounded.KeyboardArrowUp
import mihon.icons.materialsymbols.rounded.Translate
import tachiyomi.presentation.core.components.material.Scaffold

internal const val MANGALATE_REPO = "https://github.com/delkrusty/Mangalate"
internal const val MANGALATE_RELEASES = "https://github.com/delkrusty/Mangalate/releases/latest"
internal const val MANGALATE_ISSUES = "https://github.com/delkrusty/Mangalate/issues"

enum class MangalateInfoPage(val title: String) {
    HELP("Ajuda do Mangalate"),
    PRIVACY("Privacidade do Mangalate"),
    CHANGES("Novidades do Mangalate"),
}

class MangalateHelpScreen : Screen() {
    @Composable
    override fun Content() = MangalateGuideContent(MangalateInfoPage.HELP)
}

class MangalateArticleScreen(private val page: MangalateInfoPage) : Screen() {
    @Composable
    override fun Content() = MangalateGuideContent(page)
}

@Composable
fun MangalateAboutContent() {
    val context = LocalContext.current
    val uriHandler = LocalUriHandler.current
    val navigator = LocalNavigator.currentOrThrow
    val handleBack = LocalBackPress.current
    Scaffold(
        topBar = { scrollBehavior ->
            AppBar(
                title = "Sobre o Mangalate",
                navigateUp = { if (handleBack != null) handleBack() else navigator.pop() },
                scrollBehavior = scrollBehavior,
            )
        },
    ) { contentPadding ->
        LazyColumn(contentPadding = contentPadding) {
            item {
                MangalateBrandHeader(
                    subtitle = "Leia em outro idioma, sem sair da história.",
                )
            }
            item {
                TextPreferenceWidget(
                    title = "Versão instalada",
                    subtitle = "Mangalate ${BuildConfig.VERSION_NAME} · build ${BuildConfig.VERSION_CODE}",
                    onPreferenceClick = {
                        val info = "Mangalate ${BuildConfig.VERSION_NAME} (${BuildConfig.VERSION_CODE})\n" +
                            "Android ${Build.VERSION.RELEASE} (API ${Build.VERSION.SDK_INT})\n" +
                            "${Build.MANUFACTURER} ${Build.MODEL}\nCommit ${BuildConfig.COMMIT_SHA}"
                        context.copyToClipboard("Informações do Mangalate", info)
                    },
                )
            }
            item {
                TextPreferenceWidget(
                    title = "O que há de novo",
                    subtitle = "Melhorias da limpeza, tradução e interface",
                    onPreferenceClick = { navigator.push(MangalateArticleScreen(MangalateInfoPage.CHANGES)) },
                )
            }
            item {
                TextPreferenceWidget(
                    title = "Ajuda e manuais",
                    subtitle = "Aprenda a usar e resolva problemas comuns",
                    onPreferenceClick = { navigator.push(MangalateHelpScreen()) },
                )
            }
            item {
                TextPreferenceWidget(
                    title = "Atualizações e APKs",
                    subtitle = "Versões oficiais no repositório do Mangalate",
                    onPreferenceClick = { uriHandler.openUri(MANGALATE_RELEASES) },
                )
            }
            item {
                TextPreferenceWidget(
                    title = "Privacidade",
                    subtitle = "Entenda o que fica no aparelho e o que é enviado para tradução",
                    onPreferenceClick = { navigator.push(MangalateArticleScreen(MangalateInfoPage.PRIVACY)) },
                )
            }
            item {
                TextPreferenceWidget(
                    title = "Relatar um problema ou sugerir uma melhoria",
                    subtitle = "Abra um relato no projeto Mangalate, sem publicar suas chaves",
                    onPreferenceClick = { uriHandler.openUri(MANGALATE_ISSUES) },
                )
            }
            item {
                TextPreferenceWidget(
                    title = "Código-fonte do Mangalate",
                    subtitle = "Projeto aberto: delkrusty/Mangalate",
                    onPreferenceClick = { uriHandler.openUri(MANGALATE_REPO) },
                )
            }
            item {
                TextPreferenceWidget(
                    title = "Licenças de código aberto",
                    onPreferenceClick = { navigator.push(OpenSourceLicensesScreen()) },
                )
            }
            item {
                Card(
                    modifier = Modifier.padding(16.dp).fillMaxWidth(),
                    shape = RoundedCornerShape(20.dp),
                    colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainerLow),
                ) {
                    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text("Créditos", fontWeight = FontWeight.SemiBold)
                        Text(
                            "Mangalate é um projeto independente baseado no código aberto do Mihon (Apache 2.0). " +
                                "Não é uma versão oficial do Mihon. Preservamos os créditos e as licenças da base e das bibliotecas.\n\n" +
                                "OCR e tradução offline: Google ML Kit. Tradução online: Gemini. " +
                                "Fonte: Comic Neue (SIL OFL). Divisão silábica: DivSilab, Raimundo Santos Moura (MPL). " +
                                "Reconstrução por servidor compatível: manga-image-translator (serviço separado).",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }
            item { Spacer(Modifier.height(24.dp)) }
        }
    }
}

@Composable
fun MangalateBrandHeader(subtitle: String? = null) {
    val cs = MaterialTheme.colorScheme
    Column(
        modifier = Modifier.fillMaxWidth().padding(horizontal = 24.dp, vertical = 28.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Box(
            modifier = Modifier.size(80.dp)
                .clip(RoundedCornerShape(26.dp))
                .background(Brush.linearGradient(listOf(cs.primary, cs.tertiary))),
            contentAlignment = Alignment.Center,
        ) {
            Icon(MaterialSymbols.Rounded.Translate, contentDescription = "Mangalate", tint = cs.onPrimary, modifier = Modifier.size(42.dp))
        }
        Text("Mangalate", style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold)
        if (subtitle != null) {
            Text(
                subtitle,
                style = MaterialTheme.typography.bodyMedium,
                color = cs.onSurfaceVariant,
                textAlign = androidx.compose.ui.text.style.TextAlign.Center,
            )
        }
    }
}

@Composable
private fun MangalateGuideContent(page: MangalateInfoPage) {
    val navigator = LocalNavigator.currentOrThrow
    val handleBack = LocalBackPress.current
    var search by rememberSaveable { mutableStateOf("") }
    val articles = when (page) {
        MangalateInfoPage.HELP -> MangalateGuides.help
        MangalateInfoPage.PRIVACY -> MangalateGuides.privacy
        MangalateInfoPage.CHANGES -> MangalateGuides.changes
    }
    val matches = remember(search, articles) {
        articles.filter { search.isBlank() || it.title.contains(search, true) || it.text.contains(search, true) }
    }
    Scaffold(
        topBar = { scrollBehavior ->
            AppBar(
                title = page.title,
                navigateUp = { if (handleBack != null) handleBack() else navigator.pop() },
                scrollBehavior = scrollBehavior,
            )
        },
    ) { contentPadding ->
        LazyColumn(
            contentPadding = contentPadding,
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            item {
                Text(
                    when (page) {
                        MangalateInfoPage.HELP -> "Guias rápidos e soluções para o Mangalate. Todo este conteúdo funciona offline."
                        MangalateInfoPage.PRIVACY -> "Como funciona o tratamento das páginas, das chaves e das traduções."
                        MangalateInfoPage.CHANGES -> "Mangalate ${BuildConfig.VERSION_NAME}: melhorias desta versão."
                    },
                    modifier = Modifier.padding(horizontal = 16.dp).padding(top = 16.dp),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            if (page == MangalateInfoPage.HELP) {
                item {
                    OutlinedTextField(
                        value = search,
                        onValueChange = { search = it },
                        label = { Text("Buscar uma dúvida ou problema") },
                        modifier = Modifier.padding(horizontal = 16.dp).fillMaxWidth(),
                        singleLine = true,
                        shape = RoundedCornerShape(16.dp),
                    )
                }
                item {
                    TextPreferenceWidget(
                        title = "Abrir configurações de tradução",
                        subtitle = "Modos, idiomas, Gemini e preparação offline",
                        icon = MaterialSymbols.Rounded.Translate,
                        onPreferenceClick = { navigator.push(SettingsMangalateScreen()) },
                    )
                }
            }
            items(matches, key = { it.title }) { article ->
                GuideCard(article, initiallyExpanded = page != MangalateInfoPage.HELP || search.isNotBlank())
            }
            if (matches.isEmpty()) {
                item { Text("Nenhum tópico encontrado. Tente outra palavra.", modifier = Modifier.padding(16.dp)) }
            }
            item { Spacer(Modifier.height(24.dp)) }
        }
    }
}

@Composable
private fun GuideCard(article: GuideArticle, initiallyExpanded: Boolean) {
    var expanded by remember(article.title, initiallyExpanded) { mutableStateOf(initiallyExpanded) }
    Card(
        modifier = Modifier.padding(horizontal = 16.dp).fillMaxWidth(),
        shape = RoundedCornerShape(20.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainerLow),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth().clickable { expanded = !expanded }.padding(16.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(article.title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
            Icon(
                if (expanded) MaterialSymbols.Rounded.KeyboardArrowUp else MaterialSymbols.Rounded.KeyboardArrowDown,
                contentDescription = if (expanded) "Recolher" else "Ler tópico",
            )
        }
        AnimatedVisibility(expanded) {
            Text(
                article.text,
                modifier = Modifier.padding(horizontal = 16.dp).padding(bottom = 18.dp),
                style = MaterialTheme.typography.bodyMedium,
            )
        }
    }
}
