package app.mangalate.ui

internal data class GuideArticle(val title: String, val text: String)

/** Conteúdo embarcado: manuais, novidades e privacidade funcionam sem internet. */
internal object MangalateGuides {
    val help = listOf(
        GuideArticle(
            "Começar a ler e traduzir",
            "Abra um mangá na biblioteca e escolha um capítulo. Toque no centro da página para mostrar " +
                "a barra do leitor e toque em 文A. Escolha o idioma em que o mangá foi escrito, o idioma de " +
                "destino e o modo de tradução. Toque em Traduzir.\n\n" +
                "Toque em 文A novamente para ver o original. Você pode mudar os idiomas em Mais › Tradução (Mangalate).",
        ),
        GuideArticle(
            "Qual modo devo escolher?",
            "No celular: não precisa de chave. O app baixa os modelos de idioma na primeira utilização; " +
                "depois a tradução pode funcionar sem internet. A leitura de letras estilizadas e japonês vertical " +
                "pode falhar.\n\nGemini: recebe a imagem da página e traduz usando o contexto das falas. " +
                "Precisa de internet e da sua chave do Google. Rápido usa Flash-Lite; Melhor qualidade usa Flash.\n\n" +
                "Servidor próprio: para quem tem um servidor compatível. Ele faz OCR, reconstrução e tradução. " +
                "Informe o endereço e a chave na configuração e use Testar conexão.",
        ),
        GuideArticle(
            "Configurar ou corrigir a chave do Gemini",
            "Em Mais › Tradução (Mangalate), escolha Gemini e toque em Pegar chave grátis. Entre com sua conta " +
                "Google, crie uma chave de API e copie. Volte ao Mangalate, toque em Colar e depois em Testar chave.\n\n" +
                "A conta e os limites são administrados pelo Google. Se não conseguir criar a chave, use o modo No celular.\n\n" +
                "Chave inválida: copie novamente a chave inteira, sem espaços. Não publique a chave em prints, comentários ou relatos de erro.",
        ),
        GuideArticle(
            "A tradução demora ou o Gemini atingiu o limite",
            "Na primeira utilização do modo No celular, espere o download dos modelos terminar. " +
                "Mantenha internet disponível durante esse download.\n\nNo Gemini, experimente Rápido e confira a conexão. " +
                "O app prepara páginas seguintes enquanto você lê, mas o limite da sua conta pode gerar espera. " +
                "Se aparecer aviso de limite, aguarde e tente de novo; novas tentativas também dependem da cota disponível.\n\n" +
                "Para uma leitura sem espera, baixe os capítulos já traduzidos antes. Não desinstale o app para resolver limites de API.",
        ),
        GuideArticle(
            "Baixar capítulos para ler traduzido offline",
            "Ligue Traduzir capítulos ao baixar em Mais › Tradução (Mangalate). Use o botão de download na " +
                "lista de capítulos. Espere o download e a tradução acabarem; acompanhe a notificação de progresso.\n\n" +
                "Depois, abra o capítulo baixado e deixe 文A ligado. A tradução salva é usada mesmo sem internet.\n\n" +
                "Se mudar o idioma, o modo, o modelo ou ajustes de fonte, as páginas podem precisar ser traduzidas novamente. " +
                "Atualizações do motor de limpeza também podem invalidar versões antigas. Abra o capítulo com internet antes de sair.\n\n" +
                "Se a notificação apontar páginas com falha, elas serão tentadas novamente na leitura. Capítulos que já estavam " +
                "baixados antes de ligar a opção não são preparados automaticamente.",
        ),
        GuideArticle(
            "Restos de letras ou balões mal limpos",
            "Nos modos No celular e Gemini, balões claros ou escuros de fundo uniforme e contorno fechado podem ser limpos por inteiro, inclusive " +
                "letras que o OCR não identificou. A borda do balão é preservada e a tradução é colocada depois.\n\n" +
                "Contornos abertos, retículas, sombras e texto sobre personagens exigem cuidado. Quando não há confiança, " +
                "o app remove apenas letras confirmadas pelo OCR ou preserva o trecho original para não apagar a arte. " +
                "Não há preenchimento de retângulos em volta de textos soltos. O servidor próprio pode oferecer reconstrução mais avançada.\n\n" +
                "Confira se o idioma original está correto. Para japonês vertical, experimente Gemini. Se o problema continuar, " +
                "registre a página e o modo usados; um print do original e outro do resultado ajudam a corrigir.",
        ),
        GuideArticle(
            "Texto pequeno, quebra de linha ou fala fora do balão",
            "O Mangalate ajusta a fonte ao espaço interno e usa divisão silábica em português quando uma palavra " +
                "não cabe inteira. Falas longas em balões pequenos podem ficar com fonte menor.\n\n" +
                "Em Mais › Tradução (Mangalate) › Ajustes avançados, volte o ajuste de fonte para zero e compare. " +
                "Aumentar a fonte não pode forçar o texto para fora da área segura. No modo servidor, a diagramação é feita pelo servidor.\n\n" +
                "O zoom do leitor ajuda a conferir o texto. Informe palavras cortadas ou letras sobrepostas ao relatar o problema.",
        ),
        GuideArticle(
            "Sem internet: o original aparece no lugar da tradução",
            "Se a tradução não estiver salva, Gemini e servidor próprio precisam de conexão. O app mostra o original " +
                "quando uma tradução falha, para não interromper a leitura.\n\n" +
                "Baixe o capítulo já traduzido e espere a conclusão. No modo No celular, os modelos dos idiomas também " +
                "precisam ter sido baixados. Confira se 文A está ligado e se você está usando a mesma configuração de antes.",
        ),
        GuideArticle(
            "Biblioteca, arquivos locais e extensões",
            "O Mangalate não fornece mangás nem instala fontes de conteúdo por conta própria. Adicione à biblioteca " +
                "títulos das fontes que você configurou ou use arquivos locais compatíveis, com os direitos necessários.\n\n" +
                "Extensões são instaladas separadamente. Use apenas repositórios e extensões em que confia; elas podem " +
                "executar código e acessar a rede. Se uma fonte falhar, confira se o site está disponível e se a extensão precisa de atualização.",
        ),
        GuideArticle(
            "Downloads pausados ou app fechado no meio",
            "Abra Mais › Fila de downloads para conferir a fila e retomar os itens. Verifique a conexão, o espaço livre " +
                "e a pasta de armazenamento em Configurações › Dados e armazenamento.\n\n" +
                "Para preparar a tradução offline, mantenha o app aberto até concluir. Se o Android interromper o processo " +
                "em segundo plano, revise as restrições de bateria do Mangalate nas configurações do aparelho. Páginas com falha podem ser traduzidas na leitura.",
        ),
        GuideArticle(
            "Sincronizar o progresso com rastreadores",
            "Em Configurações › Rastreamento, conecte um serviço que você usa. No mangá, vincule o título ao registro " +
                "correto do serviço e confira o progresso antes de sincronizar.\n\n" +
                "A tradução não altera a numeração dos capítulos nem o título no rastreador. " +
                "Falhas de login ou sincronização dependem da conexão e das regras do serviço. " +
                "Não publique senhas ou tokens ao relatar um problema.",
        ),
        GuideArticle(
            "Limpar espaço sem perder a biblioteca",
            "Em Mais › Tradução (Mangalate) › Ajustes avançados, Limpar remove o cache temporário de traduções. " +
                "Em Ler offline, Apagar remove as páginas traduzidas guardadas. Essas ações não apagam a biblioteca, " +
                "mas podem exigir uma nova tradução.\n\n" +
                "Os arquivos dos capítulos baixados ocupam espaço separadamente. Faça um backup em Dados e armazenamento " +
                "antes de reinstalar ou trocar de celular. Não conte com o backup da biblioteca para transportar todas as imagens traduzidas.",
        ),
        GuideArticle(
            "Atualizar o aplicativo e relatar um problema",
            "Em Mais › Sobre o Mangalate, toque em Atualizações e APKs. Baixe a nova versão no repositório do Mangalate " +
                "e instale por cima da atual. Não desinstale antes: isso pode apagar configurações e traduções locais.\n\n" +
                "Use APK arm64 para a maioria dos aparelhos atuais ou universal se a instalação não funcionar.\n\n" +
                "Para relatar um erro, informe a versão, o modo de tradução, os idiomas, o que esperava e o que aconteceu. " +
                "Inclua prints sem chaves de API, dados pessoais ou conteúdo que não possa compartilhar.",
        ),
    )

    val privacy = listOf(
        GuideArticle(
            "Modo No celular",
            "O OCR, a tradução e a limpeza da página são executados no aparelho. O serviço de tradução precisa baixar " +
                "os modelos de idioma inicialmente. Nesse modo, o Mangalate não envia a página ao Gemini nem ao servidor de tradução.",
        ),
        GuideArticle(
            "Gemini e servidor próprio",
            "Com Gemini selecionado, a imagem da página e as instruções de tradução são enviadas à API do Google usando " +
                "sua chave. O tratamento dos dados depende dos termos e das configurações da sua conta Google.\n\n" +
                "No modo Servidor próprio, a página e os ajustes são enviados ao endereço que você informou. O servidor pode " +
                "repassar texto ou imagens ao provedor de tradução que você escolheu. Use servidores confiáveis e conexões HTTPS ao acessar pela internet.",
        ),
        GuideArticle(
            "Chaves e arquivos locais",
            "A chave do Gemini e a chave do servidor ficam nas configurações privadas do aplicativo no Android. " +
                "Não há uma chave compartilhada embutida no APK. Nunca publique suas chaves.\n\n" +
                "Traduções temporárias são guardadas em cache; as preparadas para leitura offline ficam nos arquivos privados " +
                "do app. A remoção do aplicativo pode apagar esses arquivos. A tela de tradução oferece opções para limpar ambos.",
        ),
        GuideArticle(
            "Fontes, extensões e serviços externos",
            "Buscar e baixar capítulos acessa as fontes de conteúdo configuradas por você. Extensões e integrações externas " +
                "têm seus próprios comportamentos e políticas; esta descrição se refere ao fluxo de tradução do Mangalate, " +
                "não substitui os termos desses serviços.\n\nA Ajuda e os manuais do Mangalate ficam dentro do app e podem ser lidos offline. " +
                "Abrir GitHub ou o site de criação de chave usa o navegador e as políticas do site correspondente.",
        ),
    )

    val changes = listOf(
        GuideArticle(
            "Proteção contra balões gigantes e arte apagada",
            "A máscara precisa combinar com o tamanho do texto e da página. Regiões exageradas são rejeitadas. " +
                "A detecção usa sempre o original, sem deixar uma limpeza alterar a análise da próxima região. " +
                "Fora de balões seguros, só letras confirmadas são removidas; contornos de rostos e outros componentes grandes são preservados.",
        ),
        GuideArticle(
            "Onomatopeias ficam como no original",
            "Efeitos sonoros não são traduzidos por padrão. Você pode ativar Traduzir onomatopeias em " +
                "Mais › Tradução (Mangalate) › Preservar a arte. Diálogos e legendas de narração continuam traduzidos. " +
                "No modo servidor, o padrão seguro também pula textos soltos fora de balões.",
        ),
        GuideArticle(
            "Limpeza completa dos balões",
            "Nova identificação do interior dos balões de fundo uniforme e contorno fechado. " +
                "A limpeza remove também resíduos fora da caixa do OCR antes de aplicar a tradução. " +
                "Regiões incertas continuam com tratamento conservador para preservar a arte.",
        ),
        GuideArticle(
            "Um balão, uma composição",
            "Blocos de texto identificados dentro do mesmo balão são combinados para evitar traduções sobrepostas. " +
                "Continuam as margens internas, o ajuste automático da fonte e a divisão silábica em português.",
        ),
        GuideArticle(
            "Identidade e ajuda do Mangalate",
            "Sobre com nome e logo próprios, novidades e privacidade internas. Ajuda com busca e manuais de leitura, " +
                "Gemini, downloads, limpeza dos balões e soluções de problemas. Os links de suporte e atualização agora apontam ao Mangalate.",
        ),
        GuideArticle(
            "Sobre traduções salvas em versões anteriores",
            "O novo motor não reutiliza as páginas geradas pela limpeza anterior. Para aplicar as melhorias com Gemini " +
                "ou servidor, abra novamente os capítulos com internet. Depois prepare as páginas para leitura offline.",
        ),
    )
}
