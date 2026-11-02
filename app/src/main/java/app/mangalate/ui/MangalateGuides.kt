package app.mangalate.ui

internal data class GuideArticle(val title: String, val text: String)

/** Manuais básicos e privacidade disponíveis sem internet; as novidades ficam em [MangalateWhatsNew]. */
internal object MangalateGuides {
    val help = listOf(
        GuideArticle(
            "Começar a ler e traduzir",
            "Abra um capítulo, toque no centro e depois em 文A. Escolha o idioma do texto que aparece nos balões " +
                "(não o país do mangá) e Português (Brasil). Toque em 文A de novo para ver o original. Segure o dedo na " +
                "página para ver o original só dela, refazer a tradução ou, no modo No celular, trocar o idioma da obra.",
        ),
        GuideArticle(
            "Modo No celular",
            "Mais › Tradução (Mangalate) › No celular › Preparar idiomas. Na primeira vez, fique conectado até o " +
                "download terminar; depois funciona offline. Letra estilizada e japonês vertical traduzem melhor no " +
                "servidor.",
        ),
        GuideArticle(
            "Montar o servidor",
            "Toque em Como montar para abrir o manual. Instale Docker e Python e rode py setup.py na pasta " +
                "server. O instalador pergunta a placa, a IA e a chave da IA, e no fim mostra a Chave Mangalate, que " +
                "vai no app. As duas chaves são diferentes: a da IA nunca vai no celular.",
        ),
        GuideArticle(
            "Servidor + IA",
            "O servidor no seu computador lê o texto, apaga o original e escreve a tradução. Só o texto das falas " +
                "vai para a IA, com a sua própria chave (BYOK). Groq e Gemini têm cota grátis e se revezam; o Ollama " +
                "roda no próprio computador e fica de reserva. O Mangalate não cobra nada.",
        ),
        GuideArticle(
            "Conectar o celular ao computador",
            "Use a mesma rede Wi-Fi. No Windows, ipconfig mostra o IPv4 do PC. No app, informe " +
                "http://IP-DO-PC:5003 e a Chave Mangalate e toque em Testar conexão. localhost no celular é o próprio " +
                "celular. Não abra a porta no roteador.",
        ),
        GuideArticle(
            "Conectou, mas não traduz",
            "Na primeira página o servidor ainda baixa modelos. No PC, rode py check.py --warmup na pasta server " +
                "e veja docker compose logs --tail=80. Se o limite grátis das IAs acabou, espere ou acrescente outra " +
                "IA com py setup.py. Não envie logs com chaves.",
        ),
        GuideArticle(
            "Ler offline e Downloads",
            "Ligue Traduzir capítulos ao baixar e espere a tradução terminar; falhas aparecem na fila de " +
                "Downloads. Mudar idioma, modo ou servidor pode exigir traduzir de novo; para refazer, segure o dedo na " +
                "página e toque em Refazer capítulo.",
        ),
        GuideArticle(
            "Balão, arte e revisão",
            "O texto é escrito dentro do balão, com hífen em português quando precisa. Com Preservar a arte " +
                "ligado, parte do texto sobre o desenho fica no original para não estragar a arte. Nenhuma tradução " +
                "automática é perfeita: segure o dedo na página e toque em Ver original para comparar.",
        ),
        GuideArticle(
            "Biblioteca, extensões e arquivos locais",
            "O Mangalate não fornece mangás. Use conteúdo próprio ou autorizado e extensões confiáveis. Arquivos " +
                "locais ficam em manga/título/capítulo.cbz na pasta de armazenamento; atualize a fonte Local para " +
                "encontrá-los.",
        ),
        GuideArticle(
            "Backup e problemas",
            "Faça backup em Configurações › Dados e armazenamento antes de trocar de aparelho. Limpar o cache " +
                "apaga traduções temporárias, não a biblioteca. Ao relatar um problema, mande versão, modo, idiomas e " +
                "prints do original e do resultado, sem chaves.",
        ),
    )
    val privacy = listOf(
        GuideArticle("No celular", "OCR, tradução e limpeza são locais; o download inicial dos modelos precisa de internet. As páginas não são enviadas ao servidor de tradução nesse modo."),
        GuideArticle("Servidor + IA", "As páginas vão só ao servidor configurado por você; leitura do texto e limpeza rodam nele. Use HTTPS fora da rede local. Apenas o texto das falas, o contexto e o glossário vão para a IA escolhida, ou ficam no computador com o Ollama. Retenção e uso dos dados seguem os termos do provedor; no plano grátis do Gemini, o Google pode usar o conteúdo enviado."),
        GuideArticle("Duas chaves diferentes", "A chave Mangalate autentica o aplicativo e fica nas configurações privadas do Android. A chave de IA fica no arquivo privado do seu servidor, fora do APK e do repositório. Não há chave compartilhada do Mangalate. Nunca publique senhas."),
        GuideArticle("Arquivos e serviços externos", "Traduções e revisões ficam no aparelho, computador ou runtime que você utiliza. Downloads acessam fontes configuradas por você. A Ajuda funciona offline; links de instalação abrem serviços externos com termos próprios."),
    )
}
