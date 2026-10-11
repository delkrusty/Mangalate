package app.mangalate.translate

import org.json.JSONObject

/**
 * Como a página é traduzida.
 */
enum class TranslateMode(val label: String, val badge: String, val description: String) {
    ON_DEVICE(
        "No celular",
        "Grátis",
        "Funciona sem configurar nada. Na primeira vez baixa o tradutor (cerca de 30 MB).",
    ),
    GEMINI(
        "Gemini",
        "Melhor qualidade",
        "A IA do Google lê e traduz a página inteira com contexto. Precisa de uma chave grátis.",
    ),
    SERVER(
        "Servidor próprio",
        "Avançado",
        "Para quem roda o servidor do Mangalate no PC ou no Colab. Melhor reconstrução da arte.",
    ),
    ;

    companion object {
        fun fromName(name: String?) = entries.firstOrNull { it.name == name } ?: ON_DEVICE
    }
}

/**
 * Idioma em que o mangá está escrito (usado pelo OCR do celular).
 */
enum class SourceLanguage(val label: String, val geminiName: String) {
    JA("Japonês", "Japanese"),
    KO("Coreano", "Korean"),
    ZH("Chinês", "Chinese"),
    EN("Inglês", "English"),
    ;

    companion object {
        fun fromName(name: String?) = entries.firstOrNull { it.name == name } ?: JA
    }
}

/**
 * Idiomas de destino suportados pelo servidor (códigos do manga-image-translator).
 */
enum class TargetLanguage(val code: String, val label: String, val latin: Boolean, val englishName: String) {
    PT_BR("PTB", "Português (Brasil)", true, "Brazilian Portuguese"),
    EN("ENG", "Inglês", true, "English"),
    ES("ESP", "Espanhol", true, "Spanish"),
    FR("FRA", "Francês", true, "French"),
    DE("DEU", "Alemão", true, "German"),
    IT("ITA", "Italiano", true, "Italian"),
    RU("RUS", "Russo", false, "Russian"),
    JA("JPN", "Japonês", false, "Japanese"),
    KO("KOR", "Coreano", false, "Korean"),
    ZH("CHS", "Chinês simplificado", false, "Simplified Chinese"),
    ;

    companion object {
        fun fromCode(code: String?) = entries.firstOrNull { it.code == code } ?: PT_BR
    }
}

/**
 * Motores de tradução. A chave de API de cada motor fica no servidor, nunca no APK.
 */
enum class TranslatorEngine(
    val id: String,
    val label: String,
    val description: String,
    val needsKey: Boolean,
) {
    DEEPSEEK("deepseek", "DeepSeek", "Muito barato e bom com contexto. Recomendado.", true),
    GEMINI("gemini", "Gemini", "Google. Tem faixa gratuita nos modelos Flash.", true),
    DEEPL("deepl", "DeepL", "Plano Free: 500 mil caracteres/mês grátis.", true),
    OPENAI("chatgpt", "OpenAI", "Modelos GPT. Ótima qualidade, custo maior.", true),
    GROQ("groq", "Groq", "Rápido, com cota gratuita generosa.", true),
    CUSTOM("custom_openai", "Compatível OpenAI", "Ollama, LM Studio, OpenRouter etc.", false),
    OFFLINE("nllb", "Offline (NLLB)", "Roda no próprio servidor, sem chave.", false),
    ;

    companion object {
        fun fromId(id: String?) = entries.firstOrNull { it.id == id } ?: DEEPSEEK
    }
}

/**
 * Perfis de detecção + limpeza + reconstrução do fundo.
 */
enum class QualityProfile(val label: String, val description: String) {
    FAST("Rápida", "Detecção padrão, LaMa MPE. Ideal para CPU."),
    HIGH("Alta", "Detector de quadrinhos (CTD), máscara adaptativa e LaMa Large."),
    MAX("Máxima", "Tudo do Alta + super-resolução 2x antes da detecção. Precisa de GPU."),
    ;

    companion object {
        fun fromName(name: String?) = entries.firstOrNull { it.name == name } ?: HIGH
    }
}

enum class TypesetMode(val label: String) {
    AUTO("Automática"),
    MANGA("Diagramação de mangá"),
    CLASSIC("Clássica"),
    ;

    companion object {
        fun fromName(name: String?) = entries.firstOrNull { it.name == name } ?: AUTO
    }
}

data class MangalateSettings(
    val mode: TranslateMode = TranslateMode.ON_DEVICE,
    val sourceLanguage: SourceLanguage = SourceLanguage.JA,
    val geminiKey: String = "",
    val geminiModel: String = DEFAULT_GEMINI_MODEL,
    val setupDone: Boolean = false,
    val serverUrl: String = "",
    val accessKey: String = "",
    val targetLanguage: TargetLanguage = TargetLanguage.PT_BR,
    val engine: TranslatorEngine = TranslatorEngine.DEEPSEEK,
    val quality: QualityProfile = QualityProfile.HIGH,
    val typeset: TypesetMode = TypesetMode.AUTO,
    val ignoreOutsideBubbles: Boolean = false,
    val uppercase: Boolean = false,
    val fontSizeOffset: Int = 0,
    val maskDilation: Int = 0,
) {
    val isConfigured: Boolean
        get() = when (mode) {
            TranslateMode.ON_DEVICE -> true
            TranslateMode.GEMINI -> geminiKey.isNotBlank()
            TranslateMode.SERVER -> serverUrl.isNotBlank()
        }

    /** Resumo curto mostrado no app, ex.: "Japonês → Português (Brasil) · No celular". */
    val summary: String
        get() = "${sourceLanguage.label} → ${targetLanguage.label} · ${mode.label}"

    /** Identifica a configuração que afeta o resultado (para o cache). */
    fun cacheSignature(): String = when (mode) {
        TranslateMode.SERVER -> "server|" + toServerConfig()
        else -> listOf(
            "v2", mode.name, sourceLanguage.name, targetLanguage.code,
            if (mode == TranslateMode.GEMINI) geminiModel else "",
            ignoreOutsideBubbles, uppercase, fontSizeOffset,
        ).joinToString("|")
    }

    companion object {
        const val DEFAULT_GEMINI_MODEL = "gemini-flash-latest"
    }

    val normalizedUrl: String
        get() = serverUrl.trim().trimEnd('/').let {
            if (it.startsWith("http://") || it.startsWith("https://")) it else "http://$it"
        }

    /**
     * Monta o JSON de configuração do pipeline enviado ao servidor.
     */
    fun toServerConfig(): String {
        val q = quality
        val detector = JSONObject().apply {
            put("detector", if (q == QualityProfile.FAST) "default" else "ctd")
            put("detection_size", if (q == QualityProfile.FAST) 1536 else 2048)
            put("text_threshold", 0.5)
            put("box_threshold", if (q == QualityProfile.FAST) 0.7 else 0.6)
            put("unclip_ratio", 2.3)
        }
        val ocr = JSONObject().apply {
            put("ocr", "48px")
            put("min_text_length", 0)
            if (ignoreOutsideBubbles) put("ignore_bubble", 8)
        }
        val inpainter = JSONObject().apply {
            put("inpainter", if (q == QualityProfile.FAST) "lama_mpe" else "lama_large")
            put("inpainting_size", if (q == QualityProfile.FAST) 1024 else 2048)
            put("inpainting_precision", "fp32")
        }
        val translator = JSONObject().apply {
            put("translator", engine.id)
            put("target_lang", targetLanguage.code)
            put("enable_post_translation_check", q != QualityProfile.FAST)
            put("post_check_max_retry_attempts", 2)
        }
        val renderer = when (typeset) {
            TypesetMode.MANGA -> "manga2eng"
            TypesetMode.CLASSIC -> "default"
            TypesetMode.AUTO -> if (targetLanguage.latin) "manga2eng" else "default"
        }
        val render = JSONObject().apply {
            put("renderer", renderer)
            put("alignment", "center")
            put("direction", if (targetLanguage.latin) "horizontal" else "auto")
            put("font_size_offset", fontSizeOffset)
            put("uppercase", uppercase)
            put("disable_font_border", false)
            put("no_hyphenation", targetLanguage == TargetLanguage.PT_BR)
            put("rtl", true)
        }
        return JSONObject().apply {
            put("detector", detector)
            put("ocr", ocr)
            put("inpainter", inpainter)
            put("translator", translator)
            put("render", render)
            if (q == QualityProfile.MAX) {
                put(
                    "upscale",
                    JSONObject().apply {
                        put("upscaler", "esrgan")
                        put("upscale_ratio", 2)
                        put("revert_upscaling", true)
                    },
                )
            }
            put("kernel_size", 3)
            val baseDilation = if (q == QualityProfile.FAST) 20 else 30
            put("mask_dilation_offset", (baseDilation + maskDilation).coerceIn(0, 80))
        }.toString()
    }
}
