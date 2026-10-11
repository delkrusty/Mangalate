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
import app.mangalate.local.GeminiClient
import app.mangalate.translate.QualityProfile
import app.mangalate.translate.SourceLanguage
import app.mangalate.translate.TranslateMode
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
        var advanced by remember { mutableStateOf(false) }

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
                item { ModeSection(settings = settings, onChange = ::update) }
                if (settings.mode == TranslateMode.GEMINI) {
                    item { GeminiSection(settings = settings, onChange = ::update) }
                }
                item { OfflineSection(settings = settings, onChange = ::update) }
                item { LanguageSection(settings = settings, onChange = ::update) }
                item { ArtworkOptionsSection(settings = settings, onChange = ::update) }
                if (settings.mode == TranslateMode.SERVER) {
                    item { ServerSection(settings = settings, onChange = ::update) }
                    item { EngineSection(settings = settings, onChange = ::update) }
                    item { QualitySection(settings = settings, onChange = ::update) }
                }
                item {
                    AdvancedToggle(expanded = advanced, onClick = { advanced = !advanced })
                }
                if (advanced) {
                    item { TypesetSection(settings = settings, onChange = ::update) }
                    item { CacheSection() }
                }
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
                            settings.summary
                        } else if (settings.mode == TranslateMode.GEMINI) {
                            "Cole sua chave do Gemini abaixo"
                        } else {
                            "Informe o endereço do servidor"
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
                text = "Ligue aqui ou no botão 文A da barra do leitor. O Mangalate encontra os balões, " +
                    "apaga o texto original e escreve a tradução no lugar. Toque de novo para ver o original.",
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
        title = "Idiomas",
    ) {
        Text("O mangá está em", style = MaterialTheme.typography.labelLarge)
        FlowRow(
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            SourceLanguage.entries.forEach { lang ->
                FilterChip(
                    selected = settings.sourceLanguage == lang,
                    onClick = { onChange { it.copy(sourceLanguage = lang) } },
                    label = { Text(lang.label) },
                    shape = RoundedCornerShape(12.dp),
                )
            }
        }
        Text("Traduzir para", style = MaterialTheme.typography.labelLarge)
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
            subtitle = "Também ignora legendas de narração fora de balões",
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
        if (settings.mode == TranslateMode.SERVER) {
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
        }
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
        if (settings.mode != TranslateMode.SERVER) {
            SwitchRow(
                title = "Só traduzir texto dentro de balões",
                subtitle = "Também ignora legendas de narração fora de balões",
                checked = settings.ignoreOutsideBubbles,
                onChecked = { v -> onChange { it.copy(ignoreOutsideBubbles = v) } },
            )
        }
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
private fun ArtworkOptionsSection(
    settings: MangalateSettings,
    onChange: ((MangalateSettings) -> MangalateSettings) -> Unit,
) {
    SectionCard(
        icon = MaterialSymbols.Rounded.BrushIcon,
        title = "Preservar a arte",
        subtitle = "Diálogos traduzidos; efeitos sonoros mantidos como no original",
    ) {
        SwitchRow(
            title = "Traduzir onomatopeias",
            subtitle = "Opcional. Efeitos como CLAP, BANG e letras desenhadas podem alterar o visual da página.",
            checked = settings.translateSoundEffects,
            onChecked = { enabled -> onChange { it.copy(translateSoundEffects = enabled) } },
        )
        Text(
            if (settings.mode == TranslateMode.SERVER) {
                "No servidor, o padrão seguro aplica a imagem traduzida só dentro de balões confirmados pelo OCR local. " +
                    "Efeitos e textos soltos sobre a arte permanecem no original."
            } else {
                "A limpeza completa é aplicada só a balões confirmados. Fora deles, o app remove apenas letras " +
                    "identificadas; se a região for duvidosa, preserva o trecho original."
            },
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
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

@Composable
private fun ModeSection(
    settings: MangalateSettings,
    onChange: ((MangalateSettings) -> MangalateSettings) -> Unit,
) {
    SectionCard(
        icon = MaterialSymbols.Rounded.AutoAwesome,
        title = "Como traduzir",
        subtitle = "Pode trocar quando quiser",
    ) {
        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            TranslateMode.entries.forEach { mode ->
                ChoiceCard(
                    selected = settings.mode == mode,
                    title = mode.label,
                    badge = mode.badge,
                    description = mode.description,
                    onClick = { onChange { it.copy(mode = mode) } },
                )
            }
        }
    }
}

@Composable
private fun ChoiceCard(
    selected: Boolean,
    title: String,
    badge: String?,
    description: String,
    onClick: () -> Unit,
) {
    val border by animateColorAsState(
        if (selected) MaterialTheme.colorScheme.primary else Color.Transparent,
        label = "choiceBorder",
    )
    Surface(
        shape = RoundedCornerShape(18.dp),
        color = if (selected) {
            MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.5f)
        } else {
            MaterialTheme.colorScheme.surfaceContainerHigh
        },
        border = BorderStroke(2.dp, border),
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(18.dp))
            .clickable(onClick = onClick),
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 8.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            RadioButton(selected = selected, onClick = onClick)
            Column(Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                    if (badge != null) {
                        Spacer(Modifier.width(8.dp))
                        Surface(shape = RoundedCornerShape(8.dp), color = MaterialTheme.colorScheme.tertiaryContainer) {
                            Text(
                                badge,
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onTertiaryContainer,
                                modifier = Modifier.padding(horizontal = 8.dp, vertical = 3.dp),
                            )
                        }
                    }
                }
                Text(
                    description,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

@Composable
private fun GeminiSection(
    settings: MangalateSettings,
    onChange: ((MangalateSettings) -> MangalateSettings) -> Unit,
) {
    val scope = rememberCoroutineScope()
    val uriHandler = LocalUriHandler.current
    val context = LocalContext.current
    var key by remember { mutableStateOf(settings.geminiKey) }
    var test by remember { mutableStateOf<TestState>(TestState.Idle) }

    fun save(value: String) {
        key = value.trim()
        test = TestState.Idle
        onChange { it.copy(geminiKey = value.trim()) }
    }

    SectionCard(
        icon = MaterialSymbols.Rounded.Translate,
        title = "Chave grátis do Gemini",
        subtitle = "Leva 1 minuto e é feito uma única vez",
    ) {
        StepRow(1, "Toque em Pegar chave grátis e entre com sua conta Google.")
        StepRow(2, "Toque em Criar chave de API e depois em copiar.")
        StepRow(3, "Volte aqui e toque em Colar.")
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Button(onClick = { uriHandler.openUri("https://aistudio.google.com/apikey") }) {
                Text("Pegar chave grátis")
            }
            FilledTonalButton(
                onClick = {
                    val cm = context.getSystemService(android.content.Context.CLIPBOARD_SERVICE)
                        as android.content.ClipboardManager
                    cm.primaryClip?.getItemAt(0)?.coerceToText(context)?.toString()?.let(::save)
                },
            ) { Text("Colar") }
        }
        OutlinedTextField(
            value = key,
            onValueChange = ::save,
            label = { Text("Chave do Gemini") },
            placeholder = { Text("AIza…") },
            singleLine = true,
            visualTransformation = PasswordVisualTransformation(),
            shape = RoundedCornerShape(16.dp),
            modifier = Modifier.fillMaxWidth(),
        )
        OutlinedButton(
            enabled = key.isNotBlank() && test != TestState.Running,
            onClick = {
                test = TestState.Running
                scope.launch {
                    test = GeminiClient.testKey(key, settings.effectiveGeminiModel).fold(
                        onSuccess = { TestState.Ok(0) },
                        onFailure = { TestState.Fail(it.message ?: it.javaClass.simpleName) },
                    )
                }
            },
        ) {
            if (test == TestState.Running) {
                CircularProgressIndicator(Modifier.size(16.dp), strokeWidth = 2.dp)
                Spacer(Modifier.width(8.dp))
            }
            Text("Testar chave")
        }
        AnimatedVisibility(visible = test is TestState.Ok || test is TestState.Fail) {
            val ok = test is TestState.Ok
            Surface(
                shape = RoundedCornerShape(14.dp),
                color = if (ok) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.errorContainer,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(
                    text = when (val t = test) {
                        is TestState.Ok -> "Tudo certo. Pode abrir um capítulo e tocar em 文A."
                        is TestState.Fail -> t.message
                        else -> ""
                    },
                    modifier = Modifier.padding(12.dp),
                    style = MaterialTheme.typography.bodyMedium,
                )
            }
        }
        Text("Velocidade", style = MaterialTheme.typography.labelLarge)
        SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth()) {
            SegmentedButton(
                selected = settings.geminiFast,
                onClick = { onChange { it.copy(geminiFast = true) } },
                shape = SegmentedButtonDefaults.itemShape(index = 0, count = 2),
            ) { Text("Rápido") }
            SegmentedButton(
                selected = !settings.geminiFast,
                onClick = { onChange { it.copy(geminiFast = false) } },
                shape = SegmentedButtonDefaults.itemShape(index = 1, count = 2),
            ) { Text("Melhor qualidade") }
        }
        Text(
            if (settings.geminiFast) {
                "Usa o Gemini Flash-Lite: responde bem mais rápido e cabe melhor no limite grátis."
            } else {
                "Usa o Gemini Flash: tradução um pouco melhor, mas cada página demora mais."
            },
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Text(
            "A faixa grátis do Gemini tem limite por minuto; se aparecer aviso de limite, espere um pouco. " +
                "Páginas já traduzidas ficam salvas e não gastam de novo.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun StepRow(n: Int, text: String) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Box(
            modifier = Modifier
                .size(26.dp)
                .clip(CircleShape)
                .background(MaterialTheme.colorScheme.primary),
            contentAlignment = Alignment.Center,
        ) {
            Text("$n", color = MaterialTheme.colorScheme.onPrimary, style = MaterialTheme.typography.labelLarge)
        }
        Spacer(Modifier.width(12.dp))
        Text(text, style = MaterialTheme.typography.bodyMedium)
    }
}

@Composable
private fun AdvancedToggle(expanded: Boolean, onClick: () -> Unit) {
    TextButton(
        onClick = onClick,
        modifier = Modifier.padding(horizontal = 16.dp),
    ) {
        Icon(MaterialSymbols.Rounded.Tune, contentDescription = null, modifier = Modifier.size(18.dp))
        Spacer(Modifier.width(8.dp))
        Text(if (expanded) "Esconder ajustes avançados" else "Ajustes avançados")
    }
}

@Composable
private fun OfflineSection(
    settings: MangalateSettings,
    onChange: ((MangalateSettings) -> MangalateSettings) -> Unit,
) {
    val context = LocalContext.current
    var size by remember { mutableLongStateOf(MangalateTranslator.offlineSize(context)) }
    SectionCard(
        icon = MaterialSymbols.Rounded.Dns,
        title = "Ler offline",
        subtitle = "Baixe o capítulo e ele já vem traduzido",
    ) {
        SwitchRow(
            title = "Traduzir capítulos ao baixar",
            subtitle = "Ao baixar um capítulo, todas as páginas são traduzidas junto. " +
                "Depois é só ler, mesmo sem internet.",
            checked = settings.translateOnDownload,
            onChecked = { v -> onChange { it.copy(translateOnDownload = v) } },
        )
        Text(
            "Use o botão de download da lista de capítulos, como sempre. Uma notificação mostra o progresso " +
                "da tradução. Se você mudar o idioma ou o modo depois, as páginas são traduzidas de novo na leitura.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                "${Formatter.formatShortFileSize(context, size)} de páginas traduzidas guardadas",
                style = MaterialTheme.typography.bodyMedium,
                modifier = Modifier.weight(1f),
            )
            TextButton(
                onClick = {
                    MangalateTranslator.clearOffline(context)
                    size = MangalateTranslator.offlineSize(context)
                },
            ) { Text("Apagar") }
        }
    }
}
