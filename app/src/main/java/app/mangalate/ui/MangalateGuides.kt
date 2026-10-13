package app.mangalate.ui

internal data class GuideArticle(val title: String, val text: String)

/** Manuais básicos, privacidade e novidades disponíveis sem internet. */
internal object MangalateGuides {
    val help = listOf(
        GuideArticle(
            "Começar a ler e traduzir",
            "Abra um capítulo da biblioteca, toque no centro e depois em 文A. Escolha o idioma do texto visível " +
                "e Português (Brasil), não o país de origem do mangá. No celular funciona sem servidor depois de preparar idiomas. " +
                "Servidor exige endereço e chave Mangalate. Toque novamente em 文A para ver o original.",
        ),
        GuideArticle(
            "Preparar tradução offline",
            "Mais › Tradução (Mangalate) › No celular › Preparar idiomas. Na primeira vez, fique conectado até concluir " +
                "o download. Depois pode traduzir sem internet. Inglês nos balões significa escolher Inglês como idioma original. " +
                "Letras estilizadas e japonês vertical podem exigir o servidor.",
        ),
        GuideArticle(
            "Instalar Docker e encontrar a chave Mangalate",
            "Abra o manual do servidor pelo botão Como montar. Instale Docker e Python e rode python setup.py dentro " +
                "da pasta server do projeto. O assistente pergunta Básico ou BYOK, CPU ou GPU e gera sua senha. " +
                "A chave Mangalate fica em server/secrets/mangalate_key.txt. Copie o conteúdo, não o nome do arquivo, " +
                "para a Chave Mangalate no app. Ela não é a chave da API de IA.",
        ),
        GuideArticle(
            "Servidor Básico e BYOK",
            "Básico usa NLLB no seu servidor sem API paga, para uso pessoal não comercial conforme licença do modelo. " +
                "BYOK usa um modelo Chat Completions compatível escolhido por você, em servidor que você administra. " +
                "Servidor e API são pagos diretamente aos fornecedores. Mangalate não cobra nem recebe comissão. " +
                "A chave da API fica só em server/secrets/provider_key.txt; nunca cole essa chave no celular. " +
                "A qualidade e o motor são definidos no servidor pelo instalador.",
        ),
        GuideArticle(
            "Conectar o celular ao computador",
            "Use a mesma rede Wi-Fi. No instalador, permita rede local. No Windows, ipconfig mostra o IPv4 do PC. " +
                "No app informe http://IP-DO-PC:5003, a chave Mangalate e toque Testar conexão. " +
                "localhost no celular aponta ao próprio celular, não ao PC. Não abra a porta no roteador. " +
                "Para servidor na internet, use HTTPS com domínio e firewall.",
        ),
        GuideArticle(
            "Conectou, mas ainda não traduz",
            "O teste de conexão não garante que os modelos já foram baixados. No PC rode python check.py --warmup " +
                "na pasta server e abra a página de teste gerada. A primeira tradução prepara modelos. " +
                "No BYOK, confira chave, nome do modelo, saldo e limite de gastos na conta do provedor. " +
                "Veja docker compose --profile cpu logs --tail=80 (ou gpu). Não envie logs que contenham chaves.",
        ),
        GuideArticle(
            "Google Colab e capítulos offline",
            "O notebook oficial do projeto trabalha interativamente com um capítulo ZIP/CBZ e gera um CBZ e um pacote " +
                "de revisão para baixar. Ele não abre túnel nem mantém servidor ligado. GPU e continuidade da sessão não são garantidas. " +
                "Para leitura ao vivo no app, use Docker ou sua própria máquina na nuvem. Confira o manual para importar arquivos locais.",
        ),
        GuideArticle(
            "Downloads para ler traduzido offline",
            "Ligue Traduzir capítulos ao baixar e espere o download e a tradução terminarem. Confira falhas na fila de Downloads. " +
                "O servidor precisa estar acessível durante a preparação, não durante a leitura das páginas já salvas. " +
                "Mudanças no idioma ou no modo podem exigir nova tradução. O CBZ gerado no Colab também pode ser lido como arquivo local.",
        ),
        GuideArticle(
            "Balão, painel, limpeza e revisão",
            "A limpeza local mantém a base aprovada da 0.5.0. O servidor usa OCR, máscara e reconstrução; texto sobre arte " +
                "é ignorado por padrão por uma heurística que pode falhar. O pacote BYOK inclui original, tradução e texto reconhecido " +
                "para revisão. Nenhuma IA garante acabamento de scan humano em toda página. Compare contornos, rostos, balão e ordem " +
                "dos painéis. Resultados com enquadramento alterado ou mudança global excessiva são bloqueados.",
        ),
        GuideArticle(
            "Fonte pequena ou palavras cortadas",
            "No celular, a fonte se adapta ao balão e usa divisão silábica em português. No servidor, palavras são preservadas " +
                "inteiras por padrão para não aplicar hifenização inglesa ao português. Use zoom e compare com o original. " +
                "Traduções longas podem exigir revisão manual. Não aumente a fonte até invadir a arte.",
        ),
        GuideArticle(
            "Biblioteca, extensões e arquivos locais",
            "O Mangalate não fornece mangás. Use conteúdo próprio ou autorizado e extensões confiáveis. Configure a pasta " +
                "de armazenamento em Dados e armazenamento. Arquivos locais devem seguir a estrutura manga/título/capítulo.cbz " +
                "dentro dessa pasta; atualize a fonte Local para encontrar o capítulo. Verifique os direitos de uso.",
        ),
        GuideArticle(
            "Backup, armazenamento e problemas",
            "Faça backup em Configurações › Dados e armazenamento antes de trocar de aparelho ou desinstalar. Limpar cache " +
                "remove traduções temporárias, não a biblioteca. Desinstalar pode apagar traduções salvas. " +
                "Ao relatar um problema, informe versão, modo, idiomas e prints do original e resultado sem senhas.",
        ),
    )
    val privacy = listOf(
        GuideArticle("No celular", "OCR, tradução e limpeza são locais; o download inicial dos modelos precisa de internet. As páginas não são enviadas ao servidor de tradução nesse modo."),
        GuideArticle("Servidor Básico", "Páginas são enviadas somente ao servidor configurado por você. OCR e NLLB rodam nele. Use HTTPS fora da rede local. Modelos e bibliotecas têm licenças próprias."),
        GuideArticle("Servidor BYOK", "OCR e reconstrução rodam no seu servidor. Textos, contexto e glossário podem ser enviados à API contratada por você. Custos, retenção e tratamento de dados seguem os termos desse provedor."),
        GuideArticle("Duas chaves diferentes", "A chave Mangalate autentica o aplicativo e fica nas configurações privadas do Android. A chave de IA fica no arquivo privado do seu servidor, fora do APK e do repositório. Não há chave compartilhada do Mangalate. Nunca publique senhas."),
        GuideArticle("Arquivos e serviços externos", "Traduções e revisões ficam no aparelho, computador ou runtime que você utiliza. Downloads acessam fontes configuradas por você. A Ajuda funciona offline; links de instalação abrem serviços externos com termos próprios."),
    )
    val changes = listOf(
        GuideArticle("0.5.2: offline e servidor", "Dois modos principais: No celular e Servidor. Gemini e DeepL diretos saíram da seleção. Limpeza local da 0.5.0 preservada. Docker com assistente e caminhos explícitos das chaves. Perfis Básico e BYOK, sem cobrança Mangalate. Colab interativo por capítulo, sem túnel."),
        GuideArticle("Acabamento com revisão", "Servidor com limites de máscara, enquadramento preservado e texto sobre arte filtrado por padrão. BYOK em lote usa contexto das páginas anteriores e glossário opcional. Exporta original, resultado e relatório para revisar, sem prometer perfeição humana automática."),
        GuideArticle("0.5.1: ML Kit corrigido", "Preservação dos componentes ML Kit no APK minificado, acesso serializado aos clientes e remoção de falhas locais ocultadas como texto original. Não adicionar inicialização duplicada do SDK."),
        GuideArticle("Limpeza da 0.5.0", "Balões uniformes e fechados podem ser limpos por inteiro, preservando o contorno. Regiões incertas seguem tratamento conservador. Mantidos o agrupamento por balão, margens e hifenização em português no celular."),
    )
}
