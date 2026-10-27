# Qualidade do servidor

O resultado automático é uma versão para revisar, não um scan final. Compare o original e a tradução antes de compartilhar.

## Como cada página é feita

1. **Detecção:** o detector CTD marca as linhas de texto. Se não achar nada, o detector padrão tenta de novo, para balões com letra serifada ou de explosão.
2. **Reparo de linhas (0.5.3):** linhas que a máscara do detector cobre, mas que ficaram sem caixa ou dividindo uma caixa com outra, ganham caixa própria. Uma caixa que corta as letras é ajustada a elas, mesmo quando a linha encosta na vizinha por um pontinho (as duas são separadas onde a tinta quase some). A primeira ou a última linha de um bloco que a máscara pega só em parte (uma faixa da altura de meia linha, a linha inteira colada à de baixo, ou só uma fileira fina por cima das letras, quando elas formam uma fileira de letras inteiras da mesma altura) ganha caixa pelas letras escuras da página; o resto de uma linha que já tem caixa ("ONE" depois de "I'LL GET") alarga essa caixa. Ao alargar uma caixa pelas letras da página, só conta como letra uma peça cheia (um risco fino e inclinado não) e com papel em volta (o desenho ao lado da linha não). As linhas da borda e o corte no vale do segundo ajuste valem nos dois modos: no padrão, uma fala sobre o desenho com papel em volta que antes ficava no original por falta de uma linha passa a ser traduzida, e o fundo atrás das letras pode sair manchado (escolha do Lucas: fala em inglês pesa mais que a mancha atrás dela). Linhas que o OCR descartou por baixa confiança no meio de um parágrafo são lidas de novo. A releitura só vale com duas letras diferentes ou mais: uma letra repetida ("JJJJ") é um desenho no balão, e ele fica fora da limpeza. Sem isso, essas linhas ficavam em inglês.
3. **OCR:** leitura das linhas (modelo 48px).
4. **Balão ou arte:** cada fala é classificada pelo fundo ao redor das linhas. Fundo liso ou em degradê é balão: a fala é limpa e traduzida. Fundo com desenho é arte: a fala fica no original e a página é marcada para revisão. Texto escrito numa parte branca do desenho, com quatro ou mais traços finos (cabelo, linhas de velocidade) atravessando a margem até as letras, é traduzido, mas só as letras são limpas; o desenho em volta fica. O mesmo vale para uma fala com letras escuras sobre papel limpo que o desenho cruza tanto que a margem é classificada como arte, desde que pelo menos 45% da margem seja papel. Fala de letra escura com contorno branco (halo) escrita direto sobre o desenho também é traduzida: o modelo redesenha o fundo só onde estavam as letras e o halo, e a tradução ganha um halo branco justo, como o original. Ela fica no original quando falta uma linha (inclusive uma palavra em inglês que o agrupamento juntou a um efeito em kana), quando uma linha foi lida como sobra ("DP") ou quando a limpeza não cobre 85% da tinta das linhas. Assim, a arte em volta não é apagada para receber texto; só o fundo logo atrás das letras é refeito, e sobre desenho com detalhe (hachura, retícula, cabelo) ele pode sair manchado.
5. **Tradução:** pela IA escolhida. A IA recebe a memória da obra: os termos do glossário que aparecem na página e as falas das duas páginas anteriores do capítulo. Ela devolve, numa linha à parte, os nomes e termos da página; um termo só entra no glossário se estiver mesmo no texto lido, e a primeira tradução vale para as próximas. Isso vale no app (que manda o nome da obra, do capítulo e o número da página) e no `batch.py`. Uma resposta incompleta ou fora do formato não é aceita como tradução. Uma fala devolvida igual ao original é letreirada quando não tem palavra em inglês (interjeição, grito, som, nome); com palavra em inglês, a IA tenta de novo, e o que ainda voltar igual fica no original e aparece como preservado na revisão.
6. **Limpeza:** LaMa, Large no modo Qualidade e MPE no Rápido. As dimensões da página são preservadas.
7. **Escrita:** fonte horizontal, sem cortar palavras e com espaço após a pontuação. Uma fala limpa letra por letra num balão de retícula usa o balão inteiro, achado pelo contorno escuro, quando a área lisa da limpeza deixaria a letra com menos de 75% da original; a letra não passa do tamanho original, e um quadro com traços dentro não conta como balão. Uma fala com halo sobre o desenho cuja letra sairia com menos de 85% da original pode usar o espaço do contorno antigo das letras e as partes limpas do retângulo das linhas, sem cobrir um traço do desenho nem passar para o outro lado dele; o tamanho mira a altura da maiúscula original, medida nas letras, e não passa dela.
8. **Emendas (webtoon):** um balão cortado entre duas páginas é traduzido inteiro, usando os pedaços das páginas vizinhas, e as duas metades combinam.

O `batch.py` gera um relatório de cada página (`review.json` e `revisao.md`). Com `--diagnostics`, salva também as máscaras, as regiões e as linhas reparadas ou relidas.

## O que ainda falha

- Onomatopeias e letras muito estilizadas podem ser lidas errado ou ignoradas.
- Fala de letra escura com halo branco sobre o desenho: sobre desenho com detalhe, o fundo refeito atrás das letras sai borrado (escolha do Lucas: fala em inglês pesa mais que essa mancha), um detalhe pequeno cercado pelo halo pode ser apagado como letra, e uma linha que o OCR perdeu deixa a fala inteira no original. Hoje os dois modos ("preservar" e "traduzir") fazem o mesmo no servidor.
- A IA às vezes erra gírias ou deixa um termo em inglês. O glossário aprendido mantém nomes e termos iguais; para corrigir um termo, edite o `glossario.csv` do lote e passe com `--glossary`.
- O tamanho do texto nem sempre aproveita bem o balão.

## Como testar uma mudança

Use páginas próprias ou autorizadas, de mangá (preto e branco) e de webtoon (colorido). 10 a 15 páginas de cada bastam para um teste rápido. Rode com `--pages` e `--diagnostics` e compare, página a página:

| Critério | O que conferir |
|---|---|
| Arte | Nada apagado fora dos balões |
| Balões | Texto original todo limpo, contorno intacto |
| Texto | Nenhuma fala faltando, duplicada ou trocada |
| Português | Sentido, tom e nomes corretos |
| Escrita | Texto dentro do balão, legível, sem palavra cortada |

Uma mudança só está pronta quando melhora as páginas que motivaram a mudança sem piorar as outras. Compilar, passar nos testes ou receber HTTP 200 não basta.
