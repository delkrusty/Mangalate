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
                "As configurações de tradução ficaram mais curtas: saíram opções que não mudavam nada, e as páginas já traduzidas continuam salvas.",
                "No modo No celular, cada obra guarda o seu idioma: o Mangalate já sugere o da fonte, sem trocar a configuração entre mangá e manhwa.",
                "Segure o dedo na página para ver o original só dela ou para refazer a tradução da página ou do capítulo.",
                "Quando uma página fica sem tradução, o aviso no canto do leitor diz o motivo, e um toque tenta de novo.",
                "Quando uma fala fica no original, um selo no canto avisa, e um toque mostra o original da página para comparar.",
                "No modo Servidor, segure o dedo na página para corrigir como sai o nome de um personagem na obra inteira, ou para guardar a página no computador e conferir depois.",
                "Para ligar o servidor, leia o QR code que aparece no computador: o endereço e a chave entram sozinhos.",
                "Nova opção para adiantar o próximo capítulo: perto do fim de um, o seguinte já vai sendo traduzido, só no Wi-Fi e com o celular carregando.",
                "A chave do servidor fica guardada de forma protegida no celular.",
            ),
        ),
        WhatsNewRelease(
            "0.6.0",
            listOf(
                "Mais falas escritas sobre o desenho são traduzidas, apagando só as letras. Com \"Preservar a arte\" desligado, todas são traduzidas, mas o fundo pode sair borrado.",
                "Janelas de sistema dos webtoons de jogo e falas em manchas pretas saem traduzidas, com letra parecida com a original.",
                "Balões mais limpos e completos: sem sobra de letra, sem fala pela metade em inglês e sem duas falas misturadas.",
                "Sons, gritos que se leem igual, logotipos, títulos e créditos ficam como foram desenhados.",
                "Português mais cuidadoso: nomes e termos iguais no capítulo todo, gênero certo e menos letras lidas erradas.",
                "Letra maior nos balões estreitos, com hífen quando precisa, e símbolos como \"♡\" e \"★\" sem quadradinho.",
                "No servidor, a instalação ficou mais curta e o Ollama funciona como IA de reserva no próprio computador.",
                "Depois de cada atualização, o Mangalate mostra o que mudou. A lista completa fica em Mais › Sobre o Mangalate › O que há de novo.",
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
