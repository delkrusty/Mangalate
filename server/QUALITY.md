# Qualidade do servidor

O resultado automático é uma versão para revisar, não um scan final. Compare o original e a tradução antes de compartilhar.

## Como cada página é feita

1. **Detecção:** o detector CTD marca as linhas de texto. Se não achar nada, o detector padrão tenta de novo, para balões com letra serifada ou de explosão.
2. **Reparo de linhas (0.5.3):** linhas que a máscara do detector cobre, mas que ficaram sem caixa ou dividindo uma caixa com outra, ganham caixa própria. Linhas que o OCR descartou por baixa confiança no meio de um parágrafo são lidas de novo. Sem isso, essas linhas ficavam em inglês.
3. **OCR:** leitura das linhas (modelo 48px).
4. **Balão ou arte:** cada fala é classificada pelo fundo ao redor das linhas. Fundo liso ou em degradê é balão: a fala é limpa e traduzida. Fundo com desenho é arte: a fala fica no original e a página é marcada para revisão. Assim, a arte nunca é apagada para receber texto.
5. **Tradução:** pela IA escolhida. No capítulo inteiro (`batch.py`), as duas páginas anteriores e o glossário opcional entram como contexto; na leitura pelo app, cada página é traduzida sozinha. Uma resposta incompleta ou fora do formato não é aceita como tradução.
6. **Limpeza:** LaMa, Large no modo Qualidade e MPE no Rápido. As dimensões da página são preservadas.
7. **Escrita:** fonte horizontal, sem cortar palavras e com espaço após a pontuação.
8. **Emendas (webtoon):** um balão cortado entre duas páginas é traduzido inteiro, usando os pedaços das páginas vizinhas, e as duas metades combinam.

O `batch.py` gera um relatório de cada página (`review.json` e `revisao.md`). Com `--diagnostics`, salva também as máscaras, as regiões e as linhas reparadas ou relidas.

## O que ainda falha

- Onomatopeias e letras muito estilizadas podem ser lidas errado ou ignoradas.
- Fala sobre o desenho fica no original, de propósito.
- A IA às vezes erra gírias ou deixa um termo em inglês. Use o glossário para nomes e termos fixos.
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
