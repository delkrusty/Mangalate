# Ajuda do Mangalate

O manual completo está dentro do aplicativo em **Mais › Ajuda do Mangalate**, com busca por dúvidas e problemas. Ele funciona offline e não encaminha para o suporte de outro aplicativo.

## Começar

- **Ler:** adicione um título à biblioteca pelas fontes configuradas por você ou use arquivos locais compatíveis. Abra um capítulo.
- **Traduzir:** toque no centro da página para mostrar os controles e no botão 文A. Selecione os idiomas e toque em Traduzir.
- **Ver o original:** toque novamente em 文A.
- **Mudar ajustes:** abra Mais › Tradução (Mangalate).

## Modos de tradução

- **No celular:** OCR, limpeza e tradução no dispositivo. Os modelos dos idiomas são baixados na primeira utilização; depois podem ser usados offline.
- **Gemini:** tradução com contexto da imagem, usando sua chave e conexão com a API do Google. Na tela de tradução, use Pegar chave grátis, Colar e Testar chave.
- **Servidor próprio:** envie as páginas para um servidor compatível configurado por você. Consulte o [manual do servidor](server/README.md).

## Ler offline

Ligue **Traduzir capítulos ao baixar** antes de baixar os capítulos e espere o progresso da tradução terminar. A tradução precisa estar ligada no leitor para exibir as imagens traduzidas guardadas.

Mudar o idioma, o modo, o modelo ou ajustes de fonte pode exigir nova tradução. Atualizações do motor também podem invalidar imagens antigas. Prepare os capítulos com internet antes de sair.

## Limpeza dos balões

Balões de fundo uniforme e contorno fechado têm o interior segmentado e limpo antes de aplicar a tradução. Caracteres perdidos pelo OCR também podem ser removidos.

Se o balão não for identificado com segurança, o app usa limpeza local para preservar a arte. Contornos abertos, sombras, retículas e textos sobre personagens podem precisar de reconstrução mais avançada.

## Problemas comuns

- **Chave inválida:** copie a chave do Gemini inteira, sem espaços, e teste novamente. Não compartilhe a chave.
- **Limite do Gemini:** aguarde; a disponibilidade depende da cota da sua conta. Tente Rápido ou o modo No celular.
- **Página não traduzida offline:** confira se o capítulo e a tradução terminaram de baixar e se está usando os mesmos ajustes.
- **Letras restantes:** compare original e tradução; informe o idioma, o modo e a página ao relatar o problema.
- **Downloads interrompidos:** confira a fila, conexão, armazenamento e restrições de bateria. Mantenha o app aberto durante a preparação offline.
- **Fonte de conteúdo não abre:** confira se o site está disponível e se a extensão é confiável e atualizada. O Mangalate não fornece conteúdo ou repositórios de fontes.
- **Texto pequeno:** falas longas em balões pequenos exigem redução da fonte. Volte o ajuste de fonte para zero e use zoom para conferir.

## Armazenamento e backup

Cache de traduções, páginas traduzidas offline e capítulos originais são armazenados separadamente. Limpar traduções pode exigir novos pedidos ao Gemini ou ao servidor. Faça um backup da biblioteca antes de trocar de celular ou reinstalar; ele não substitui uma cópia de todas as imagens traduzidas.

## Rastreamento

Conecte um serviço em Configurações › Rastreamento e vincule cada mangá ao registro correto. A tradução não altera a numeração dos capítulos. Confira o progresso antes de sincronizar.

## Atualizar e pedir ajuda

Use **Mais › Sobre o Mangalate › Atualizações e APKs**, baixe a versão em [Releases](https://github.com/delkrusty/Mangalate/releases/latest) e instale por cima da atual. Não é necessário desinstalar.

Relate problemas em [Issues do Mangalate](https://github.com/delkrusty/Mangalate/issues), incluindo versão, modo de tradução, idiomas e passos para reproduzir. Prints do original e da tradução ajudam, mas devem estar livres de chaves de API e dados pessoais.
