# Novidades do Mangalate

As mudanças do leitor herdadas do Mihon estão no [changelog do Mihon](https://github.com/mihonapp/mihon/blob/main/CHANGELOG.md).

## Em teste (próxima versão)

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
