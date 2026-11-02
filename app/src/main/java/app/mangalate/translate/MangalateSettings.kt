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
    SERVER(
        "Servidor",
        "Groq, Gemini ou Ollama",
        "Docker no computador ou servidor próprio. A IA é escolhida no instalador do servidor.",
    ),
    ;

    companion object {
        val available = entries.toList()

        // Os modos Gemini e DeepL saíram do app; quem os tinha volta para o celular.
        fun fromName(name: String?) = entries.firstOrNull { it.name == name } ?: ON_DEVICE
    }
}

/**
 * Idioma em que o mangá está escrito (usado pelo OCR do celular).
 */
enum class SourceLanguage(val label: String) {
    JA("Japonês"),
    KO("Coreano"),
    ZH("Chinês"),
    EN("Inglês"),
    ;

    companion object {
        fun fromName(name: String?) = entries.firstOrNull { it.name == name } ?: JA

        /**
         * Idioma do texto das páginas a partir do idioma da extensão ("ja", "ko", "zh-Hans", "en").
         * Extensões de vários idiomas ("all") ou de outros idiomas não sugerem nada.
         */
        fun fromSourceLang(lang: String?): SourceLanguage? =
            when (lang.orEmpty().lowercase().substringBefore('-').substringBefore('_')) {
                "ja" -> JA
                "ko" -> KO
                "zh" -> ZH
                "en" -> EN
                else -> null
            }

        /** O escolhido para a obra vence; depois a extensão, o sugerido ao abrir a obra e o padrão. */
        fun pick(chosen: String?, sourceLang: String, suggested: SourceLanguage?, default: SourceLanguage) =
            entries.firstOrNull { it.name == chosen } ?: fromSourceLang(sourceLang) ?: suggested ?: default
    }
}

/**
 * Idiomas de destino suportados pelo servidor (códigos do manga-image-translator).
 */
enum class TargetLanguage(val code: String, val label: String, val latin: Boolean) {
    PT_BR("PTB", "Português (Brasil)", true),
    EN("ENG", "Inglês", true),
    ES("ESP", "Espanhol", true),
    FR("FRA", "Francês", true),
    DE("DEU", "Alemão", true),
    IT("ITA", "Italiano", true),
    RU("RUS", "Russo", false),
    JA("JPN", "Japonês", false),
    KO("KOR", "Coreano", false),
    ZH("CHS", "Chinês simplificado", false),
    ;

    companion object {
        fun fromCode(code: String?) = entries.firstOrNull { it.code == code } ?: PT_BR
    }
}

data class MangalateSettings(
    val mode: TranslateMode = TranslateMode.ON_DEVICE,
    val sourceLanguage: SourceLanguage = SourceLanguage.JA,
    val translateOnDownload: Boolean = false,
    val setupDone: Boolean = false,
    val serverUrl: String = "",
    val accessKey: String = "",
    val targetLanguage: TargetLanguage = TargetLanguage.PT_BR,
    /**
     * Fala escrita sobre o desenho fica no original; desligado, tudo é traduzido. Sem escolha
     * (null), vale o padrão do modo: preservar no servidor, traduzir no celular, como antes.
     */
    val preserveArtText: Boolean? = null,
    val uppercase: Boolean = false,
    /** De -3 a +3, o mesmo limite que o servidor aplica. */
    val fontSizeOffset: Int = 0,
) {
    val isConfigured: Boolean
        get() = when (mode) {
            TranslateMode.ON_DEVICE -> true
            TranslateMode.SERVER -> serverUrl.isNotBlank() && accessKey.isNotBlank()
        }

    val preservesArt: Boolean
        get() = preserveArtText ?: (mode == TranslateMode.SERVER)

    /** Resumo curto mostrado no app, ex.: "Japonês → Português (Brasil) · No celular". */
    val summary: String
        get() = "${sourceLanguage.label} → ${targetLanguage.label} · ${mode.label}"

    /** Identifica a configuração que afeta o resultado (para o cache). */
    fun cacheSignature(): String = when (mode) {
        // v2: limpeza, quebra de linha e balões cortados da 0.5.3; páginas antigas são refeitas.
        TranslateMode.SERVER -> "server-scan-v2|" + legacyServerConfig()
        TranslateMode.ON_DEVICE -> listOf(
            "sdk-translation-v5.1",
            mode.name, sourceLanguage.name, targetLanguage.code,
            "", // era o modelo do Gemini
            preservesArt, uppercase, fontSizeOffset,
        ).joinToString("|")
    }

    val normalizedUrl: String
        get() = serverUrl.trim().trimEnd('/').let {
            if (it.startsWith("http://") || it.startsWith("https://")) it else "http://$it"
        }

    /**
     * O que o servidor aceita do app: idioma de destino, tamanho e caixa da letra e a escolha
     * sobre a fala no desenho. Detecção, limpeza, IA e diagramação são do perfil do servidor.
     * O mesmo formato é conferido nos dois lados por `server/tests/app_config_contract.json`.
     */
    fun toServerConfig(): String = JSONObject().apply {
        put("translator", JSONObject().put("target_lang", targetLanguage.code))
        put(
            "render",
            JSONObject()
                .put("font_size_offset", fontSizeOffset.coerceIn(FONT_OFFSETS))
                .put("uppercase", uppercase),
        )
        // O servidor só traduz a fala sobre o desenho quando pedido, limpando só as letras.
        if (!preservesArt) put("arte", "traduzir")
    }.toString()

    /**
     * A configuração que o app mandava até a 0.6.0, com as opções que o servidor ignora nos
     * valores padrão. Só serve de assinatura do cache: assim quem não mexia nelas não perde
     * as páginas já traduzidas. Não mude nada aqui sem subir o "server-scan-v2".
     */
    private fun legacyServerConfig(): String {
        val latin = targetLanguage.latin
        return JSONObject().apply {
            put(
                "detector",
                JSONObject().apply {
                    put("detector", "ctd")
                    put("detection_size", 2048)
                    put("text_threshold", 0.5)
                    put("box_threshold", 0.6)
                    put("unclip_ratio", 2.3)
                },
            )
            put("ocr", JSONObject().put("ocr", "48px").put("min_text_length", 0))
            put(
                "inpainter",
                JSONObject().apply {
                    put("inpainter", "lama_large")
                    put("inpainting_size", 2048)
                    put("inpainting_precision", "fp32")
                },
            )
            put(
                "translator",
                JSONObject().apply {
                    put("translator", "nllb")
                    put("target_lang", targetLanguage.code)
                    put("enable_post_translation_check", true)
                    put("post_check_max_retry_attempts", 2)
                },
            )
            put(
                "render",
                JSONObject().apply {
                    put("renderer", if (latin) "manga2eng" else "default")
                    put("alignment", "center")
                    put("direction", if (latin) "horizontal" else "auto")
                    put("font_size_offset", fontSizeOffset.coerceIn(FONT_OFFSETS))
                    put("uppercase", uppercase)
                    put("disable_font_border", false)
                    put("no_hyphenation", false)
                    put("rtl", true)
                },
            )
            if (!preservesArt) put("arte", "traduzir")
            put("kernel_size", 3)
            put("mask_dilation_offset", 30)
        }.toString()
    }

    companion object {
        val FONT_OFFSETS = -3..3
    }
}
