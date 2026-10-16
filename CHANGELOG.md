# Novidades do Mangalate

As mudanças do leitor herdadas do Mihon estão no [changelog do Mihon](https://github.com/mihonapp/mihon/blob/main/CHANGELOG.md).

## Em teste (próxima versão)

### Letreiramento
- A tradução é escrita numa fonte de quadrinhos (Comic Neue Bold, licença livre) em vez da Arial, com contorno branco fino.
- As linhas seguem o formato do balão: curtas no topo e no pé de um balão oval, largas no meio, o bloco centrado no balão e sem encostar na borda. As linhas ficam equilibradas, sem uma linha comprida seguida de uma palavra sozinha, e um "um", "de" ou "que" nunca fica sozinho numa linha.
- Quando o balão tem espaço, a letra pode ficar um pouco maior que a original, porque minúsculas no tamanho das maiúsculas do inglês parecem menores.
- Uma frase que termina no meio de uma linha passa para a linha seguinte quando a letra continua do tamanho do original ("E se eles / levarem ela? / Por favor, vem.").
- Mais espaço entre o texto e a borda de legendas e balões.
- Balão que fura a borda do quadro e encosta na margem branca da página é reconhecido inteiro, em vez de o texto ficar espremido no tamanho da caixa original.
- MANGALATE_FONT=simples volta para a Arial do motor.

### Tradução e balões
- Um balão de várias linhas que o detector marcou mas não separou em linhas ("--THOUGH I / MAY OFFER SOME / SUGGESTIONS...") agora é lido e traduzido em vez de ficar em inglês.
- Quando a tradução perde o "não" do original ("I'm not..." virando afirmação), o servidor pede de novo apontando o problema.
- Instruções da IA: o OCR costuma ler U como LI ("LINEAMILIAR" = UNFAMILIAR), e um nome entre vírgulas é com quem se fala ("E, General Arthur, você vai...").
- Reticências no começo da fala ficam coladas na palavra ("…mas", não "… mas").
- Letras que o OCR troca nas maiúsculas de quadrinhos são corrigidas antes da tradução, com uma lista de palavras do inglês: "TM LINEAMILIAR" vira "I'M UNFAMILIAR" (antes saía "Estou familiarizado", o contrário), "PULLEO" vira "PULLED", "L/TTLE" vira "LITTLE". Nomes da obra e palavras que a lista não resolve com certeza ficam como estão.
- Uma segunda leitura pior das mesmas letras ("GOT IT!" lido também como "8E") é descartada, em vez de escrever "Be" por cima de "Entendi!"; fica a leitura com mais letras para o espaço que ocupa.
- Onomatopeia em inglês desenhada na arte ("SPLOOSH", lida como "VLOOSH") fica como está, em vez de ser apagada e trocada por "Vluuuf". A marca de gênero da memória ("Bob (m)") nunca vai para a página.
- Gagueira mantém a palavra em minúscula ("E-eu tô com medo", não "E-Eu").
- "Você deve estar preocupada" sem nenhuma mulher na página também pede a tradução de novo.
- Quando a tradução diz "não" e o original não tem negação ("I WANT TO FIGHT IN THE WAR!" virando "Eu não quero lutar na guerra!"), o servidor pede de novo. A checagem de negação também deixou de confundir palavras como "WANT" com "N'T".
- Balões brancos pequenos que o detector não viu ("MUSCLE?", "I SEE.", "HOW'S THAT?") são achados pelo formato: área branca fechada com linhas de letras no meio. Eles são traduzidos e limpos como os outros. Um som desenhado num contorno fechado ("GRAB") fica na arte.
- Duas falas lado a lado no mesmo balão ("YOU / GOTTA / RELAX." ao lado de "THERE'S NO POINT...") não são mais lidas intercaladas linha a linha: a caixa que atravessa as duas colunas é cortada no vão entre elas e cada fala é traduzida sozinha.
- Uma linha que ganhou caixa própria dentro de outra fala ("LOOKS / LIKE / IORI...") volta para a fala no lugar certo, em vez de virar um "Tipo..." escrito por cima do balão.
- Uma linha que a caixa do detector só pegou pela metade ("DON'T / TELL ME") é separada e lida, em vez de ficar meio apagada.
- Um balão partido em dois pelo detector, com caixas de linha de alturas diferentes, volta a ser uma fala só ("I'M SURE AZUSA-SAN / APPRECIATED THAT!").
- Uma letra solta de onomatopeia ("R" de "KRRK") fica na arte, em vez de virar "É.".
- Palavra que o letrista partiu entre linhas é juntada antes da tradução: "ART- ISTRY" vira "ARTISTRY" (antes saía "arte-ístria"), "STRAIN- ING", "CONVINC ING", "BOY- FRIEND". Tratamentos japoneses ficam ligados ao nome ("AZUSA-SAN").
- Correção do OCR também em palavras de 3 letras ("IWO BODIES" vira "TWO BODIES", antes saía "Iwo corpos") e com I lido no lugar de T ("RIGHI" vira "RIGHT"). Gírias de quadrinho ("LIL", "GOTTA") não são mexidas.
- Um pedaço de código da IA que vazava na tradução ("Kouhei: 5 pts. <|10|") é removido antes de ir para a página.
- Balão achado pelo formato com duas linhas de letras é traduzido mesmo quando o OCR só leu uma palavra ("ASS- / HOLE...").

### IAs
- Mistral e GitHub Models saíram da lista. Num teste com as chaves reais, o plano grátis da Mistral responde "limite" com zero pedidos permitidos para os modelos small e medium (o único que respondeu foi um modelo pequeno que conversa em vez de traduzir), e o GitHub Models devolveu só "OK" em vez de uma tradução. Nos 7 capítulos de teste nenhum dos dois traduziu uma página. Chaves já salvas deles são ignoradas; as outras IAs continuam.
- O Groq (GPT-OSS) pensa menos antes de responder: na mesma página, o segundo modelo gastou 290 tokens de resposta em vez de 631, com a mesma tradução ou melhor. O limite grátis do Groq é de 200 mil tokens por dia por modelo, então isso deixa mais páginas por dia.

## 0.5.6

### Tradução e balões
- Uma fala que o detector partia em dois pedaços no mesmo balão (a última linha separada) volta a ser uma fala só: traduzida inteira e escrita uma vez, sem um texto por cima do outro.
- Linhas de créditos como "Original Art by:", "TL:" e "Editor:" ficam no original, como as marcas d'água.
- "--" na tradução vira travessão (—), no servidor e no modo no celular.
- A última palavra de uma fala lida ao lado da última linha ("THE REAL" | "TRAINING") também volta para a fala.
- Nome que a IA manteve numa resposta em maiúsculas continua com inicial maiúscula ("Rainha Merial", não "Rainha merial").
- A linha logo abaixo de um crédito ("Original Art by:" / nomes) também fica no original.
- Página de créditos do fim do capítulo (dois ou mais créditos de equipe) fica inteira no original: logo, selo da plataforma e nomes.
- Começo da tradução arrumado: "M-ME LIGA assim que" vira "M-me liga assim que", e uma fala que continua com reticências ("..DREAM") começa em minúscula.
- Quando a IA some com um nome do original ("Arthur. Eleanor. Sylvie." virando "Arthur. E Sylvie.") ou usa feminino sem nenhuma mulher na página nem nas anteriores ("eu disse a mim mesma" com o Arthur narrando), o servidor pede a tradução de novo apontando o problema e fica com a melhor.
- A memória da obra guarda o gênero de cada personagem quando a página mostra, e a IA usa isso nas páginas seguintes, inclusive quando o personagem narra. No lote, o glossário CSV aceita a coluna `gender` (m ou f).
- Legenda em escada com uma palavra riscada que encosta na linha de baixo ("THAT ENOUGH, ~~GREY~~" / "ARTHUR, AND") tem as duas linhas lidas e traduzidas, e a legenda inteira deixa de ser confundida com desenho por causa dos cantos vazios da escada.
- Uma hesitação curta em maiúsculas ("EU...") volta para "Eu...".
- Instruções da IA: todo nome do original aparece na tradução, sem troca nem sobrenome inventado; gênero só com evidência (pronome, título, nome já conhecido), senão frase neutra; título ou apelido segue o gênero de quem ele nomeia.

### IAs e velocidade
- Novas IAs gratuitas na instalação: Mistral, um segundo modelo do Groq (GPT-OSS 20B, usa a mesma chave e tem limite separado) e GitHub Models (GPT-4.1 mini, com um token do GitHub).
- Com mais de uma IA configurada, as páginas se revezam entre elas (uma página vai para a primeira, a seguinte para a segunda), então o limite gratuito de cada uma demora mais para acabar. O segundo Groq e o GitHub Models ficam só de reserva (entram quando as outras estão no limite), porque traduzem pior. O log diz qual IA traduziu cada página. MANGALATE_ROTATION=ordem volta ao jeito antigo (sempre a primeira, as outras só de reserva).
- Uma IA que demora mais de 45 segundos é deixada de lado e a página vai para a próxima.
- O servidor traduz 2 páginas ao mesmo tempo: enquanto uma espera a IA, a outra é lida e limpa. O app manda 2 páginas por vez e, num servidor antigo que só aceita uma, espera a vez em vez de dar erro. MANGALATE_PAGES_AT_ONCE muda o número (1 a 4).

### Servidor
- A instalação para placa NVIDIA voltou a compilar (a imagem base do PyTorch passou a recusar o pip) e agora é conferida a cada mudança.

## 0.5.5

### Modo no celular
- Créditos e marcas d'água de scan (sites, Discord, Patreon) e onomatopeias em japonês que sobraram em scans em inglês ficam no original, sem tradução.
- Em páginas longas de webtoon, uma linha cortada entre duas faixas de leitura agora é lida inteira.
- Tradução com espaços e pontuação arrumados (sem espaço antes de "?" nem vírgula antes de ponto).

### Servidor: velocidade
- A limpeza da página começa enquanto a IA traduz, em vez de esperar a resposta.
- Texto em balão liso é apagado com a própria cor do balão, sem passar pelo modelo de limpeza; o modelo só roda no texto sobre o desenho, e só na parte da página ao redor dele.
- O servidor mostra quanto tempo cada etapa da página levou.

### Servidor: placa de vídeo
- Nova opção experimental na instalação guiada para quem tem Radeon RX 7000 ou mais nova no Windows: o servidor roda no WSL2 e usa a placa pelo ROCm da AMD. Placas AMD mais antigas continuam no processador.
- Ao iniciar, o servidor diz qual placa de vídeo está usando, ou avisa que caiu para o processador.

## 0.5.4

### Tradução e limpeza
- O texto traduzido ocupa o balão, não só a caixa do texto original: letras maiores e mais espaço entre as linhas.
- Pedaços de letras em itálico que sobravam como risquinhos depois da limpeza agora são apagados, e linhas que o detector não via dentro do balão são lidas e traduzidas.
- Falas que aparecem só na emenda com a página vizinha não são mais mandadas para a IA nessa página.
- Instruções da IA reforçadas para expressões e interjeições brasileiras ("Cuidado!", "Pode vir!") e sem palavras em inglês esquecidas.
- Memória da obra: o servidor aprende os nomes e termos de cada obra (glossário) e manda à IA as falas das páginas anteriores do capítulo. Um termo sai igual em todas as páginas e capítulos, e frases cortadas entre páginas ganham contexto. Vale na leitura pelo app e no capítulo inteiro no PC.
- Onomatopeias em japonês, títulos, créditos e avisos do site do scan ficam como foram desenhados.
- Fala que a IA devolvia toda em maiúsculas volta para a caixa normal; vírgula antes do ponto é removida.
- Palavra lida errado pelo OCR ("HARI" por "HARD") não é mais tratada como nome, e a IA não chuta o gênero de quem fala.

## 0.5.3

### Servidor + IA
- O instalador vai direto ao menu de IAs e configura uma de cada vez, oferecendo uma reserva: Groq, Gemini, OpenRouter, Ollama ou outra compatível com OpenAI.
- Quando uma IA chega ao limite grátis, a próxima assume sozinha. Se todas estiverem no limite, o app mostra a mensagem.
- No Windows, a chave da IA é lida da área de transferência, porque Ctrl+V não funciona no campo oculto.
- Velocidade Rápido (padrão em CPU, cerca de 3 vezes mais rápido) ou Qualidade (padrão com placa NVIDIA).
- `py rebuild.py` atualiza o servidor sem depender do "bake" do Docker Compose e confere se a versão nova está rodando.

### Tradução e limpeza
- Corrigido: a tradução em português ficava escrita por cima do texto em inglês que não tinha sido apagado.
- Corrigido: palavras cortadas no meio e espaço sumindo depois da vírgula.
- Fala sobre o desenho fica no original, e a página é marcada para revisão, em vez de a arte ser apagada.
- Corrigido: linhas que ficavam em inglês no meio de uma fala, sem caixa do detector ou descartadas pelo OCR.
- Balões cortados entre páginas de webtoon são traduzidos inteiros e as duas metades combinam.
- Texto em caixa normal (não tudo em maiúsculas) e correção de pequenos erros de leitura.

### Removido
- Perfil Básico (tradução NLLB): o português saía com cara de Portugal e havia falas perdidas. Instalações antigas continuam funcionando até você rodar o instalador de novo.

## 0.5.2
- Gemini e DeepL diretos saíram da seleção; quem usava esses modos passa para No celular.
- Servidor Docker com instalação guiada, perfis Básico e BYOK e diagnóstico.
- Notebook Colab para traduzir um capítulo inteiro e exportar CBZ e pacote de revisão.

## 0.5.1
- Volta à base da 0.5.0, mantendo a limpeza e a diagramação.
- Preparação dos idiomas offline e teste de OCR no app.
- Falhas de tradução não aparecem mais como se fossem o texto original.

## 0.5.0
- Limpeza do interior inteiro de balões de fundo uniforme e contorno fechado, com limpeza conservadora para arte e contornos incertos.
- Falas do mesmo balão compostas como uma só.
- Ajuda e "Sobre" próprios do Mangalate, com manuais pesquisáveis offline.

## 0.4.0
- Texto encaixado no balão com margens e limite de fonte.
- Divisão silábica em português (DivSilab), sem cortes arbitrários dentro de palavras.

## 0.1.0 a 0.3.0
- Primeiras versões: tradução das páginas no leitor com o botão 文A.
