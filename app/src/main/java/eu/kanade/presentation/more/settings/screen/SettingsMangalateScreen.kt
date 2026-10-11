package eu.kanade.presentation.more.settings.screen

import android.text.format.Formatter
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.animateColorAsState
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Slider
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import app.mangalate.translate.MangalateSettings
import app.mangalate.translate.MangalateTranslator
import app.mangalate.translate.QualityProfile
import app.mangalate.translate.TargetLanguage
import app.mangalate.translate.TranslatorEngine
import app.mangalate.translate.TypesetMode
import eu.kanade.presentation.components.AppBar
import eu.kanade.presentation.util.LocalBackPress
import eu.kanade.presentation.util.Screen
import kotlinx.coroutines.launch
import mihon.icons.materialsymbols.MaterialSymbols
import mihon.icons.materialsymbols.rounded.AutoAwesome
import mihon.icons.materialsymbols.rounded.Brush as BrushIcon
import mihon.icons.materialsymbols.rounded.Dns
import mihon.icons.materialsymbols.rounded.Language
import mihon.icons.materialsymbols.rounded.Translate
import mihon.icons.materialsymbols.rounded.Tune
import tachiyomi.presentation.core.components.material.Scaffold

private const val SERVER_GUIDE_URL = "https://github.com/delkrusty/Mangalate/blob/main/server/README.md"

/**
 * Tela de configurações do Mangalate (Configurações › Mangalate).
 */
class SettingsMangalateScreen : Screen() {

    @Composable
    override fun Content() {
        val context = LocalContext.current
        val handleBack = LocalBackPress.current
        remember { MangalateTranslator.init(context) }
        val settings by MangalateTranslator.settings.collectAsState()
        val enabled by MangalateTranslator.enabled.collectAsState()

        fun update(block: (MangalateSettings) -> MangalateSettings) =
            MangalateTranslator.updateSettings(context, block)

        Scaffold(
            topBar = { scrollBehavior ->
                AppBar(
                    title = "Mangalate",
                    navigateUp = if (handleBack != null) handleBack::invoke else null,
                    scrollBehavior = scrollBehavior,
                )
            },
        ) { contentPadding ->
            LazyColumn(
                contentPadding = contentPadding,
                verticalArrangement = Arrangement.spacedBy(14.dp),
            ) {
                item {
                    HeroCard(
                        enabled = enabled,
                        settings = settings,
                        onToggle = { MangalateTranslator.setEnabled(context, it) },
                    )
                }
                item { ServerSection(settings = settings, onChange = ::update) }
                item { LanguageSection(settings = settings, onChange = ::update) }
                item { EngineSection(settings = settings, onChange = ::update) }
                item { QualitySection(settings = settings, onChange = ::update) }
                item { TypesetSection(settings = settings, onChange = ::update) }
                item { CacheSection() }
                item { Spacer(Modifier.height(24.dp)) }
            }
        }
    }
}

@Composable
private fun HeroCard(
    enabled: Boolean,
    settings: MangalateSettings,
    onToggle: (Boolean) -> Unit,
) {
    val cs = MaterialTheme.colorScheme
    Box(
        modifier = Modifier
            .padding(horizontal = 16.dp)
            .padding(top = 8.dp)
            .fillMaxWidth()
            .clip(RoundedCornerShape(28.dp))
            .background(
                Brush.linearGradient(
                    listOf(cs.primary, cs.tertiary),
                ),
            )
            .padding(20.dp),
    ) {
        Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(
                    modifier = Modifier
                        .size(52.dp)
                        .clip(CircleShape)
                        .background(cs.onPrimary.copy(alpha = 0.18f)),
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(
                        imageVector = MaterialSymbols.Rounded.Translate,
                        contentDescription = null,
                        tint = cs.onPrimary,
                        modifier = Modifier.size(28.dp),
                    )
                }
                Spacer(Modifier.width(14.dp))
                Column(Modifier.weight(1f)) {
                    Text(
                        text = "Tradução automática",
                        style = MaterialTheme.typography.titleLarge,
                        fontWeight = FontWeight.SemiBold,
                        color = cs.onPrimary,
                    )
                    Text(
                        text = if (settings.isConfigured) {
                            "${settings.engine.label} → ${settings.targetLanguage.label}"
                        } else {
                            "Configure o servidor para começar"
                        },
                        style = MaterialTheme.typography.bodyMedium,
                        color = cs.onPrimary.copy(alpha = 0.85f),
                    )
                }
                Switch(
                    checked = enabled,
                    onCheckedChange = onToggle,
                    enabled = settings.isConfigured,
                )
            }
            Text(
                text = "Detecta os balões, apaga o texto original, reconstrói a arte e " +
                    "diagrama a tradução no lugar. Use o botão de tradução na barra do leitor " +
                    "para alternar entre original e traduzido a qualquer momento.",
                style = MaterialTheme.typography.bodySmall,
                color = cs.onPrimary.copy(alpha = 0.85f),
            )
        }
    }
}

@Composable
private fun SectionCard(
    icon: ImageVector,
    title: String,
    subtitle: String? = null,
    content: @Composable () -> Unit,
) {
    Card(
        modifier = Modifier
            .padding(horizontal = 16.dp)
            .fillMaxWidth(),
        shape = RoundedCornerShape(24.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainerLow),
    ) {
        Column(
            modifier = Modifier.padding(18.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(
                    modifier = Modifier
                        .size(36.dp)
                        .clip(RoundedCornerShape(12.dp))
                        .background(MaterialTheme.colorScheme.secondaryContainer),
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(
                        imageVector = icon,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.onSecondaryContainer,
                        modifier = Modifier.size(20.dp),
                    )
                }
                Spacer(Modifier.width(12.dp))
                Column {
                    Text(title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                    if (subtitle != null) {
                        Text(
                            subtitle,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }
            content()
        }
    }
}

private sealed interface TestState {
    data object Idle : TestState
    data object Running : TestState
    data class Ok(val queue: Int) : TestState
    data class Fail(val message: String) : TestState
}

@Composable
private fun ServerSection(
    settings: MangalateSettings,
    onChange: ((MangalateSettings) -> MangalateSettings) -> Unit,
) {
    val scope = rememberCoroutineScope()
    val uriHandler = LocalUriHandler.current
    var url by remember { mutableStateOf(settings.serverUrl) }
    var key by remember { mutableStateOf(settings.accessKey) }
    var showKey by remember { mutableStateOf(false) }
    var test by remember { mutableStateOf<TestState>(TestState.Idle) }

    SectionCard(
        icon = MaterialSymbols.Rounded.Dns,
        title = "Servidor de tradução",
        subtitle = "OCR, limpeza dos balões e reconstrução rodam aqui",
    ) {
        OutlinedTextField(
            value = url,
            onValueChange = {
                url = it
                test = TestState.Idle
                onChange { s -> s.copy(serverUrl = it.trim()) }
            },
            label = { Text("Endereço do servidor") },
            placeholder = { Text("http://192.168.0.10:5003") },
            singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
            shape = RoundedCornerShape(16.dp),
            modifier = Modifier.fillMaxWidth(),
        )
        OutlinedTextField(
            value = key,
            onValueChange = {
                key = it
                test = TestState.Idle
                onChange { s -> s.copy(accessKey = it.trim()) }
            },
            label = { Text("Chave de acesso (opcional)") },
            singleLine = true,
            visualTransformation = if (showKey) VisualTransformation.None else PasswordVisualTransformation(),
            trailingIcon = {
                TextButton(onClick = { showKey = !showKey }) { Text(if (showKey) "Ocultar" else "Mostrar") }
            },
            shape = RoundedCornerShape(16.dp),
            modifier = Modifier.fillMaxWidth(),
        )
        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Button(
                enabled = url.isNotBlank() && test != TestState.Running,
                onClick = {
                    test = TestState.Running
                    scope.launch {
                        val current = MangalateTranslator.settings.value
                        test = MangalateTranslator.testConnection(current).fold(
                            onSuccess = { TestState.Ok(it) },
                            onFailure = { TestState.Fail(it.message ?: it.javaClass.simpleName) },
                        )
                    }
                },
            ) {
                if (test == TestState.Running) {
                    CircularProgressIndicator(Modifier.size(16.dp), strokeWidth = 2.dp)
                    Spacer(Modifier.width(8.dp))
                }
                Text("Testar conexão")
            }
            OutlinedButton(onClick = { uriHandler.openUri(SERVER_GUIDE_URL) }) {
                Text("Como montar")
            }
        }
        AnimatedVisibility(visible = test is TestState.Ok || test is TestState.Fail) {
            val ok = test is TestState.Ok
            val bg by animateColorAsState(
                if (ok) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.errorContainer,
                label = "testBg",
            )
            Surface(shape = RoundedCornerShape(14.dp), color = bg, modifier = Modifier.fillMaxWidth()) {
                Text(
                    text = when (val t = test) {
                        is TestState.Ok -> "Conectado. Páginas na fila do servidor: ${t.queue}"
                        is TestState.Fail -> "Falhou: ${t.message}"
                        else -> ""
                    },
                    modifier = Modifier.padding(12.dp),
                    style = MaterialTheme.typography.bodyMedium,
                    color = if (ok) {
                        MaterialTheme.colorScheme.onPrimaryContainer
                    } else {
                        MaterialTheme.colorScheme.onErrorContainer
                    },
                )
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun LanguageSection(
    settings: MangalateSettings,
    onChange: ((MangalateSettings) -> MangalateSettings) -> Unit,
) {
    SectionCard(
        icon = MaterialSymbols.Rounded.Language,
        title = "Traduzir para",
        subtitle = "O idioma de origem é detectado automaticamente",
    ) {
        FlowRow(
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            TargetLanguage.entries.forEach { lang ->
                FilterChip(
                    selected = settings.targetLanguage == lang,
                    onClick = { onChange { it.copy(targetLanguage = lang) } },
                    label = { Text(lang.label) },
                    shape = RoundedCornerShape(12.dp),
                )
            }
        }
    }
}

@Composable
private fun EngineSection(
    settings: MangalateSettings,
    onChange: ((MangalateSettings) -> MangalateSettings) -> Unit,
) {
    SectionCard(
        icon = MaterialSymbols.Rounded.AutoAwesome,
        title = "Motor de tradução",
        subtitle = "As chaves de API ficam no servidor, nunca no celular",
    ) {
        Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
            TranslatorEngine.entries.forEach { engine ->
                val selected = settings.engine == engine
                val border by animateColorAsState(
                    if (selected) MaterialTheme.colorScheme.primary else Color.Transparent,
                    label = "engineBorder",
                )
                Surface(
                    shape = RoundedCornerShape(16.dp),
                    color = if (selected) {
                        MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.45f)
                    } else {
                        MaterialTheme.colorScheme.surfaceContainerHigh
                    },
                    border = BorderStroke(1.5.dp, border),
                    modifier = Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(16.dp))
                        .clickable { onChange { it.copy(engine = engine) } },
                ) {
                    Row(
                        modifier = Modifier.padding(horizontal = 8.dp, vertical = 6.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        RadioButton(selected = selected, onClick = { onChange { it.copy(engine = engine) } })
                        Column(Modifier.weight(1f)) {
                            Text(engine.label, style = MaterialTheme.typography.titleSmall)
                            Text(
                                engine.description,
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                        if (!engine.needsKey) {
                            Surface(
                                shape = RoundedCornerShape(8.dp),
                                color = MaterialTheme.colorScheme.tertiaryContainer,
                            ) {
                                Text(
                                    "sem chave",
                                    style = MaterialTheme.typography.labelSmall,
                                    color = MaterialTheme.colorScheme.onTertiaryContainer,
                                    modifier = Modifier.padding(horizontal = 8.dp, vertical = 3.dp),
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun QualitySection(
    settings: MangalateSettings,
    onChange: ((MangalateSettings) -> MangalateSettings) -> Unit,
) {
    SectionCard(
        icon = MaterialSymbols.Rounded.BrushIcon,
        title = "Limpeza e reconstrução",
        subtitle = "Como os balões sujos são detectados e restaurados",
    ) {
        val profiles = QualityProfile.entries
        SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth()) {
            profiles.forEachIndexed { index, profile ->
                SegmentedButton(
                    selected = settings.quality == profile,
                    onClick = { onChange { it.copy(quality = profile) } },
                    shape = SegmentedButtonDefaults.itemShape(index = index, count = profiles.size),
                ) {
                    Text(profile.label)
                }
            }
        }
        Text(
            settings.quality.description,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        HorizontalDivider()
        Text("Margem da máscara: ${signed(settings.maskDilation)} px", style = MaterialTheme.typography.bodyMedium)
        Text(
            "Aumente se sobrarem restos de letras; diminua se a limpeza estiver comendo a arte.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Slider(
            value = settings.maskDilation.toFloat(),
            onValueChange = { v -> onChange { it.copy(maskDilation = v.toInt()) } },
            valueRange = -20f..30f,
            steps = 9,
        )
        SwitchRow(
            title = "Só traduzir texto dentro de balões",
            subtitle = "Ignora onomatopeias e textos soltos sobre a arte",
            checked = settings.ignoreOutsideBubbles,
            onChecked = { v -> onChange { it.copy(ignoreOutsideBubbles = v) } },
        )
    }
}

@Composable
private fun TypesetSection(
    settings: MangalateSettings,
    onChange: ((MangalateSettings) -> MangalateSettings) -> Unit,
) {
    SectionCard(
        icon = MaterialSymbols.Rounded.Tune,
        title = "Tipografia",
        subtitle = "Encaixe do texto traduzido no balão",
    ) {
        val modes = TypesetMode.entries
        SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth()) {
            modes.forEachIndexed { index, mode ->
                SegmentedButton(
                    selected = settings.typeset == mode,
                    onClick = { onChange { it.copy(typeset = mode) } },
                    shape = SegmentedButtonDefaults.itemShape(index = index, count = modes.size),
                ) {
                    Text(mode.label, maxLines = 1)
                }
            }
        }
        Text(
            when (settings.typeset) {
                TypesetMode.AUTO -> "Diagramação de mangá para idiomas latinos, clássica para os demais."
                TypesetMode.MANGA -> "Quebra de linha e tamanho calculados para preencher o balão."
                TypesetMode.CLASSIC -> "Mantém a área e a direção do texto original."
            },
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Text("Ajuste do tamanho da fonte: ${signed(settings.fontSizeOffset)}", style = MaterialTheme.typography.bodyMedium)
        Slider(
            value = settings.fontSizeOffset.toFloat(),
            onValueChange = { v -> onChange { it.copy(fontSizeOffset = v.toInt()) } },
            valueRange = -10f..10f,
            steps = 19,
        )
        SwitchRow(
            title = "Letras maiúsculas",
            subtitle = "Estilo clássico de scanlation",
            checked = settings.uppercase,
            onChecked = { v -> onChange { it.copy(uppercase = v) } },
        )
    }
}

@Composable
private fun CacheSection() {
    val context = LocalContext.current
    var size by remember { mutableLongStateOf(MangalateTranslator.cacheSize(context)) }
    SectionCard(
        icon = MaterialSymbols.Rounded.Translate,
        title = "Páginas traduzidas",
        subtitle = "Ficam salvas para não gastar tradução de novo",
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                "${Formatter.formatShortFileSize(context, size)} em cache",
                style = MaterialTheme.typography.bodyMedium,
                modifier = Modifier.weight(1f),
            )
            FilledTonalButton(
                onClick = {
                    MangalateTranslator.clearCache(context)
                    size = MangalateTranslator.cacheSize(context)
                },
            ) { Text("Limpar") }
        }
    }
}

@Composable
private fun SwitchRow(
    title: String,
    subtitle: String,
    checked: Boolean,
    onChecked: (Boolean) -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .clickable { onChecked(!checked) }
            .padding(vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.bodyMedium)
            Text(subtitle, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        Switch(checked = checked, onCheckedChange = onChecked)
    }
}

private fun signed(v: Int) = if (v > 0) "+$v" else "$v"
