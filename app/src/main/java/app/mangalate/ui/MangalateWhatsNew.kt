package app.mangalate.ui

/** Uma atualização contada para quem lê: frases curtas, sem termos técnicos. */
internal data class WhatsNewRelease(val version: String?, val items: List<String>)

/**
 * Novidades do Mangalate, a mais nova primeiro. A entrada sem versão junta o que entrou depois da
 * última versão publicada; quando a versão sobe, ela ganha o número e uma nova entrada sem versão
 * começa. Toda melhoria que o leitor percebe ganha uma linha aqui.
 */
internal object MangalateWhatsNew {
    val releases = listOf(
        WhatsNewRelease(
            null,
            listOf(
                "Depois de cada atualização, o Mangalate mostra o que mudou. A lista completa fica em Mais › Sobre o Mangalate › O que há de novo.",
                "Falas escritas por cima do desenho são traduzidas apagando só as letras, sem levar junto a arte em volta.",
                "Nova opção \"Preservar a arte\", no lugar de \"Só traduzir texto dentro de balões\", agora também no servidor. Ligada (o padrão no servidor), a maioria das falas escritas sobre o desenho fica no original. Desligada (experimental), elas também são traduzidas, com uma borda branca justa em volta do texto, mas o desenho atrás pode sair borrado e, às vezes, sobra um pedaço em inglês.",
                "Falas em balões cercados de linhas de efeito, que às vezes ficavam em inglês, agora são traduzidas.",
                "Falas sobre o desenho que eram lidas sem a primeira ou a última linha agora são traduzidas inteiras, com uma borda branca em volta; o desenho logo atrás das letras pode ficar manchado de cinza.",
                "Logotipos, títulos de capítulo e créditos ficam como foram desenhados.",
                "Duas falas lado a lado, no mesmo balão ou em dois balões colados, não se misturam mais, e legendas em colunas são lidas na ordem certa.",
                "Balões estreitos, com uma letra por linha ou falas curtas empilhadas, são traduzidos inteiros.",
                "Balões brancos saem mais limpos: sem sombra das letras originais, sem pedaço de letra e sem pontos de reticências sobrando.",
                "Desenhos dentro do balão (veia de raiva, coração, um rosto encostado no texto) e textos miúdos do cenário não são mais apagados nem confundidos com fala.",
                "Pontuação numa linha própria (\"?!\", \"...\") e linhas que ficavam de fora agora entram na fala traduzida.",
                "Gritos esticados como \"NOOOO\" e \"YEAAAH\" são traduzidos; gritos que se leem igual em português, como \"AAAAH\", ficam como desenhados.",
                "Falas curtas que a IA devolvia em inglês, como \"AH..\", risadas e sons, agora aparecem no balão.",
                "Português mais cuidadoso: a IA tenta de novo quando escreve em espanhol, erra o gênero, repete palavra ou erra o formato, e nomes de lugares ficam iguais no capítulo todo.",
                "Sinais e símbolos como \"⁈\", \"♡\" e \"★\" não aparecem mais como quadradinho, e marcas como \"<I>\" que a IA escrevia somem do balão.",
                "Menos erros de leitura: número no lugar de letra e palavra partida no fim da linha saem certos.",
                "Em balões estreitos, palavras longas podem ser partidas com hífen no fim da linha, e a letra fica maior.",
                "No servidor, a tradução pelo Ollama, com a IA rodando no próprio computador, agora funciona. Como erra mais, ele fica de reserva para quando Groq e Gemini chegam ao limite.",
            ),
        ),
        WhatsNewRelease(
            "0.5.8",
            listOf(
                "Balões brancos ficam limpos mesmo com o contorno perto do texto, sem sombra das letras originais.",
                "Falas em letra pequena na mesma página de um grito grande não ficam mais em inglês.",
                "Menos falas partidas ou lidas pela metade: cada linha é ajustada às letras antes da leitura.",
                "Letreiros claros com contorno sobre fundo escuro agora são traduzidos.",
                "A borda do quadro que passa pelo texto não some mais na limpeza.",
                "Palavras com hífen (\"enfrentá-los\") não saem mais com um quadrado no lugar do hífen.",
            ),
        ),
        WhatsNewRelease(
            "0.5.7",
            listOf(
                "Nova letra de quadrinhos, e o texto segue o formato do balão, sem palavra sozinha numa linha.",
                "Balões pequenos que passavam despercebidos agora são achados e traduzidos.",
                "Menos erros de leitura nas letras maiúsculas dos quadrinhos.",
                "O \"não\" da frase original não se perde mais na tradução.",
                "Onomatopeias desenhadas na arte ficam como estão.",
                "Mistral e GitHub Models saíram da lista de IAs, e o Groq rende mais páginas por dia.",
            ),
        ),
        WhatsNewRelease(
            "0.5.6",
            listOf(
                "Falas partidas em duas voltam a ser uma só, sem texto escrito por cima de texto.",
                "Créditos e páginas de créditos ficam no original.",
                "A memória da obra guarda o gênero dos personagens para acertar \"ele\" e \"ela\".",
                "Mais IAs gratuitas, que se revezam para a cota durar mais.",
                "O servidor traduz duas páginas ao mesmo tempo.",
            ),
        ),
        WhatsNewRelease(
            "0.5.5",
            listOf(
                "No celular, créditos, marcas d'água e onomatopeias japonesas ficam no original, e linhas cortadas em webtoon são lidas inteiras.",
                "Servidor mais rápido: a limpeza começa enquanto a IA traduz.",
                "Opção experimental para placas de vídeo Radeon RX 7000 no Windows.",
            ),
        ),
        WhatsNewRelease(
            "0.5.4",
            listOf(
                "O texto traduzido ocupa o balão inteiro, com letras maiores.",
                "Memória da obra: nomes e termos iguais em todas as páginas e capítulos.",
                "Onomatopeias japonesas, títulos e créditos ficam como foram desenhados.",
                "Expressões mais naturais em português do Brasil.",
            ),
        ),
        WhatsNewRelease(
            "0.5.3",
            listOf(
                "O servidor traduz com a IA que você escolher (Groq, Gemini, OpenRouter ou Ollama), e outra assume quando uma chega ao limite.",
                "O inglês não fica mais por baixo do português, e as palavras não são cortadas no meio.",
                "Fala sobre o desenho fica no original e a página é marcada para revisão, em vez de a arte ser apagada.",
                "Balões cortados entre páginas de webtoon são traduzidos inteiros.",
            ),
        ),
        WhatsNewRelease(
            "0.5.2",
            listOf(
                "Dois modos principais: No celular e Servidor.",
                "Servidor com instalação guiada e notebook do Colab para traduzir um capítulo inteiro.",
            ),
        ),
        WhatsNewRelease(
            "0.5.1",
            listOf(
                "Tradução no celular de volta, com preparação dos idiomas para usar offline.",
                "Falhas de tradução não aparecem mais como se fossem o texto original.",
            ),
        ),
        WhatsNewRelease(
            "0.5.0",
            listOf(
                "Limpeza do balão inteiro, preservando o contorno.",
                "Ajuda e manuais que funcionam offline.",
            ),
        ),
        WhatsNewRelease(
            "0.4.0",
            listOf("Texto encaixado no balão, com divisão silábica em português."),
        ),
        WhatsNewRelease(
            "0.1.0 a 0.3.0",
            listOf("Primeiras versões: tradução das páginas no leitor com o botão 文A."),
        ),
    )

    /**
     * Itens da atualização mais nova que ainda não foram mostrados. [seen] é o que já foi visto,
     * ou null quando nada foi guardado: numa instalação nova nada aparece, e quem atualizou de uma
     * versão sem este aviso vê a atualização inteira.
     */
    fun unseen(seen: Set<String>?, freshInstall: Boolean): List<String> {
        val latest = releases.first().items
        return when {
            seen == null && freshInstall -> emptyList()
            seen == null -> latest
            else -> latest.filter { key(it) !in seen }
        }
    }

    /** Tudo o que existe hoje, para guardar como visto. */
    fun allKeys(): Set<String> = releases.flatMap { it.items }.mapTo(mutableSetOf(), ::key)

    private fun key(item: String) = item.hashCode().toString()
}
