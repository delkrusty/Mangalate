<div align="center">

<img src="server/assets/icon.png" width="120" alt="Mangalate"/>

# Mangalate

Leitor de mangá para Android, baseado no [Mihon](https://github.com/mihonapp/mihon), que **traduz as páginas automaticamente** para o idioma que você escolher, colocando o texto traduzido dentro dos próprios balões.

</div>

## Como usar (3 passos)

1. **Instale** o APK em [Releases](https://github.com/delkrusty/Mangalate/releases/latest) (`Mangalate-arm64-v8a.apk` serve na maioria dos celulares; se não instalar, use `Mangalate-universal.apk`).
2. **Abra um capítulo** e toque no botão **文A** na barra de baixo do leitor.
3. Escolha **o idioma do mangá** e **para qual idioma traduzir** e toque em **Traduzir**. Pronto.

Não precisa de servidor, conta nem configuração. Para desligar e ver o original, toque em 文A de novo.

## Os três modos

| Modo | Precisa de quê | Qualidade |
|---|---|---|
| **No celular** (padrão) | Nada. Baixa o tradutor uma vez (~30 MB) | Boa para inglês; razoável para japonês, coreano e chinês |
| **Gemini** | Uma chave grátis do Google, colada no app em 1 minuto | Tradução natural, com contexto, lê texto vertical. Modo Rápido (Flash-Lite) ou Melhor qualidade (Flash) |
| **Servidor próprio** | Rodar o servidor no PC ou no Colab ([guia](server/README.md)) | Melhor reconstrução da arte |

### Como pegar a chave grátis do Gemini

1. No app: **Mais › Tradução (Mangalate)** e escolha **Gemini**.
2. Toque em **Pegar chave grátis**, entre com sua conta Google e toque em **Criar chave de API**. Copie a chave.
3. Volte ao app, toque em **Colar** e depois em **Testar chave**.

A faixa grátis tem limite de pedidos por minuto. Se aparecer aviso de limite, espere um pouco. As páginas já traduzidas ficam salvas e não contam de novo.

## Mais rápido e offline

- **Pré-tradução:** com a tradução ligada, as próximas 6 páginas já vão sendo traduzidas enquanto você lê a atual. Ao virar a página, ela já está pronta.
- **Baixar já traduzido:** ligue **Traduzir capítulos ao baixar** (em Mais › Tradução). Quando você baixar um capítulo pelo botão de download de sempre, o Mangalate traduz todas as páginas junto, com uma notificação de progresso. Depois dá para ler traduzido **sem internet**.
- As páginas traduzidas de capítulos baixados ficam guardadas até você apagá-las na mesma tela.

## O que acontece em cada página

1. O texto é localizado (OCR no celular ou leitura pelo Gemini).
2. As falas são traduzidas.
3. Nos balões, a cor do fundo é estimada, só os traços das letras são repintados e o app mede o interior do balão para saber quanto espaço tem.
4. O texto traduzido é diagramado no balão em fonte de quadrinho, com tamanho e quebra de linha ajustados automaticamente.
5. A página fica salva no celular. As páginas seguintes já vão sendo traduzidas enquanto você lê.

## Diagramação na versão 0.4.0

- Texto centralizado na área útil do corpo do balão, com margens internas e sem aumentar a caixa para fora do balão.
- Fonte limitada pelo tamanho da página e reduzida até a fala caber; não há cortes arbitrários dentro de palavras.
- Divisão silábica em português brasileiro com hífen quando uma palavra não cabe inteira, usando o dicionário DivSilab.
- As páginas antigas em cache não são reutilizadas pela nova diagramação. Nos modos online, abra novamente os capítulos com internet antes de ler offline.
- DeepL removido, inclusive a chave antiga salva no aparelho. Quem usava esse modo migra para Gemini se já tiver uma chave, ou para o modo offline.

## Limpeza e identidade na versão 0.5.0

- Segmentação do interior completo de balões de fundo uniforme e contorno fechado. Remove inclusive caracteres fora da caixa do OCR e preserva a borda e a arte externa.
- Blocos detectados no mesmo balão são compostos como uma única fala para evitar sobreposição.
- Sobre, novidades e privacidade próprios do Mangalate; os créditos legais da base continuam preservados.
- Ajuda pesquisável dentro do app, com manuais e soluções de problemas disponíveis offline. Consulte também [HELP.md](HELP.md).
- Regiões com contorno aberto, textura ou baixa confiança usam a limpeza conservadora. A limpeza total não é aplicada indiscriminadamente à arte.

## Compilar

O GitHub Actions compila a cada push em `main` e publica o APK em Releases. Para compilar localmente: JDK 21 e Android SDK, depois:

```bash
./gradlew :app:assembleRelease -Pdist=local
```

## Limitações conhecidas

- No modo **No celular**, o OCR de japonês vertical e de letras estilizadas pode errar; para raws japonesas, o modo **Gemini** é bem melhor.
- Nos modos do celular e Gemini, texto sobre a arte é reconstruído por difusão (fica suavizado); o modo servidor usa LaMa e fica melhor.
- Onomatopeias desenhadas sobre rostos, cabelos ou cenários muito detalhados podem ficar com área suavizada.
- O renderizador WebGPU experimental do Mihon é trocado pelo leitor clássico enquanto a tradução está ligada.
- O app não inclui fontes de conteúdo; extensões são instaladas por você, como no Mihon.

## Créditos e licença

- Baseado no [Mihon](https://github.com/mihonapp/mihon) (Apache 2.0).
- OCR e tradução no celular: Google ML Kit. Fonte Comic Neue (SIL OFL 1.1).
- Modo servidor: [manga-image-translator](https://github.com/zyddnys/manga-image-translator) (GPL-3.0), executado como serviço separado.
- Ícones: Material Symbols (Apache 2.0).
- Padrões de divisão silábica: [DivSilab/LibreOffice](https://github.com/LibreOffice/dictionaries/tree/master/pt_BR), Raimundo Santos Moura. Arquivo original sem modificações, sob MPL; créditos e licença distribuídos em `app/src/main/assets/lettering/`.

Distribuído sob a licença Apache 2.0, ver [LICENSE](LICENSE).
