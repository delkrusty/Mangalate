# Novidades do Mangalate

As mudanças do leitor herdadas do Mihon estão no [changelog do Mihon](https://github.com/mihonapp/mihon/blob/main/CHANGELOG.md).

## Em teste (próxima versão)

### Tradução e limpeza
- O texto traduzido ocupa o balão, não só a caixa do texto original: letras maiores e mais espaço entre as linhas.
- Pedaços de letras em itálico que sobravam como risquinhos depois da limpeza agora são apagados, e linhas que o detector não via dentro do balão são lidas e traduzidas.
- Falas que aparecem só na emenda com a página vizinha não são mais mandadas para a IA nessa página.
- Instruções da IA reforçadas para expressões e interjeições brasileiras ("Cuidado!", "Pode vir!") e sem palavras em inglês esquecidas.
- Memória da obra: o servidor aprende os nomes e termos de cada obra (glossário) e manda à IA as falas das páginas anteriores do capítulo. Um termo sai igual em todas as páginas e capítulos, e frases cortadas entre páginas ganham contexto. Vale na leitura pelo app e no capítulo inteiro no PC.

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
