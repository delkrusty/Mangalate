# Ajuda do Mangalate

O manual completo está dentro do aplicativo em **Mais › Ajuda do Mangalate**, com busca por dúvidas e problemas. Ele funciona offline e não encaminha para o suporte de outro aplicativo.

## Começar

- **Ler:** adicione um título à biblioteca pelas fontes configuradas por você ou use arquivos locais compatíveis. Abra um capítulo.
- **Traduzir:** toque no centro da página para mostrar os controles e no botão 文A. Selecione os idiomas e toque em Traduzir.
- **Ver o original:** toque novamente em 文A.
- **Mudar ajustes:** abra Mais › Tradução (Mangalate).

## Modos de tradução

- **No celular:** OCR, limpeza e tradução no dispositivo. Os modelos dos idiomas são baixados na primeira utilização; depois podem ser usados offline.
- **Servidor:** envie as páginas para seu Docker no PC ou servidor contratado. Ele pode ser Básico, com modelos locais, ou BYOK, com a API que você paga diretamente. Consulte o [manual do servidor](server/README.md).

Gemini e DeepL diretos saíram da seleção. Configurações antigas desses modos passam para No celular. A limpeza local da 0.5.0 foi mantida.

## Onde encontro a chave Mangalate?

Dentro da pasta `server`, execute `python setup.py`. O assistente gera a chave e mostra o caminho completo de `server/secrets/mangalate_key.txt`; copie o conteúdo para o campo Chave Mangalate no app. Ela é a senha de acesso ao seu servidor, não uma chave que você compra ou pega de outra empresa.

No BYOK, sua chave de API é outra credencial e fica em `server/secrets/provider_key.txt`, somente no servidor. Não cole essa chave no celular ou em relatos de problemas.

## Ler offline

Ligue **Traduzir capítulos ao baixar** antes de baixar os capítulos e espere o progresso da tradução terminar. A tradução precisa estar ligada no leitor para exibir as imagens traduzidas guardadas.

Mudar o idioma, o modo, o modelo ou ajustes de fonte pode exigir nova tradução. Atualizações do motor também podem invalidar imagens antigas. Prepare os capítulos com internet antes de sair.

O notebook Colab também prepara ZIP/CBZ para leitura offline e exporta um pacote de revisão com originais e resultados. Ele não exige chave Mangalate e não oferece um endereço permanente para conectar o app.

## Limpeza dos balões

Balões de fundo uniforme e contorno fechado têm o interior segmentado e limpo antes de aplicar a tradução. Caracteres perdidos pelo OCR também podem ser removidos.

Se o balão não for identificado com segurança, o app usa limpeza local para preservar a arte. Contornos abertos, sombras, retículas e textos sobre personagens podem precisar de reconstrução mais avançada.

## Problemas comuns

- **Chave inválida / HTTP 401:** copie o conteúdo inteiro de `server/secrets/mangalate_key.txt`, sem espaços extras. Não use a chave paga de IA.
- **Motor iniciando / HTTP 503:** aguarde e confira no computador `docker compose logs --tail=80`; a primeira página ainda pode precisar baixar modelos.
- **Servidor ocupado / HTTP 429:** espere a página atual terminar e tente novamente.
- **Falha de motor / HTTP 502:** veja os logs no servidor e, no BYOK, confira modelo, chave, cota e saldo com o próprio provedor. A chave Mangalate é independente dessas configurações.
- **Celular não conecta:** use o IP do computador, não localhost; confira se ambos estão no mesmo Wi-Fi e se o firewall permite a porta. Para internet pública, use o guia HTTPS, sem expor portas internas.
- **Página não traduzida offline:** confira se o capítulo e a tradução terminaram de baixar e se está usando os mesmos ajustes.
- **Letras restantes:** compare original e tradução; informe o idioma, o modo e a página ao relatar o problema.
- **Downloads interrompidos:** confira a fila, conexão, armazenamento e restrições de bateria. Mantenha o app aberto durante a preparação offline.
- **Fonte de conteúdo não abre:** confira se o site está disponível e se a extensão é confiável e atualizada. O Mangalate não fornece conteúdo ou repositórios de fontes.
- **Texto pequeno:** falas longas em balões pequenos exigem redução da fonte. Volte o ajuste de fonte para zero e use zoom para conferir.

## Armazenamento e backup

Cache de traduções, páginas traduzidas offline e capítulos originais são armazenados separadamente. Limpar traduções pode exigir novo processamento e, no BYOK, novos pedidos pagos à sua API. Faça um backup da biblioteca antes de trocar de celular ou reinstalar; ele não substitui uma cópia de todas as imagens traduzidas.

## Rastreamento

Conecte um serviço em Configurações › Rastreamento e vincule cada mangá ao registro correto. A tradução não altera a numeração dos capítulos. Confira o progresso antes de sincronizar.

## Atualizar e pedir ajuda

Use **Mais › Sobre o Mangalate › Atualizações e APKs**, baixe a versão em [Releases](https://github.com/delkrusty/Mangalate/releases/latest) e instale por cima da atual. Não é necessário desinstalar.

Relate problemas em [Issues do Mangalate](https://github.com/delkrusty/Mangalate/issues), incluindo versão, modo de tradução, idiomas e passos para reproduzir. Prints do original e da tradução ajudam, mas devem estar livres de chaves de API e dados pessoais.
