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

## Os dois modos

| Modo | Precisa de quê | Como funciona |
|---|---|---|
| **No celular** (padrão) | Baixar os modelos dos idiomas na primeira utilização | OCR, tradução e limpeza offline no aparelho; mantém a limpeza local da 0.5.0 |
| **Servidor** | Docker no seu PC ou servidor contratado, URL e chave Mangalate | OCR, tradução, reconstrução e diagramação executados fora do celular |

### Básico ou BYOK no servidor

1. Siga o [manual Docker, Colab e BYOK](server/README.md). O assistente `python setup.py` explica as escolhas e gera sua chave Mangalate.
2. **Básico:** modelos locais no servidor, sem chave de API paga. Confira as licenças para seu uso.
3. **BYOK:** você contrata sua infraestrutura e leva sua chave de API; o Mangalate só faz a integração, sem cobrança nem comissão. A chave paga fica no servidor, não no celular.
4. No app, selecione **Servidor**, informe a URL e copie o conteúdo de `server/secrets/mangalate_key.txt`. Toque em **Testar conexão**.

Gemini e DeepL diretos não fazem parte da seleção nesta versão. Quem tinha um modo antigo configurado começa em No celular; o servidor BYOK aceita provedores compatíveis com sua API configurada.

Para preparar um capítulo sem instalar Docker, use o [notebook Colab](https://colab.research.google.com/github/delkrusty/Mangalate/blob/main/server/colab/Mangalate_Colab.ipynb). Ele recebe ZIP/CBZ e exporta CBZ traduzido mais um pacote de revisão; não é um servidor permanente para o app e não exige chave Mangalate.

## Mais rápido e offline

- **Pré-tradução:** com a tradução ligada, o aplicativo prepara páginas seguintes enquanto você lê. A velocidade depende do aparelho, da infraestrutura, dos modelos e da API; no servidor, as páginas são processadas uma por vez para evitar filas descontroladas.
- **Baixar já traduzido:** ligue **Traduzir capítulos ao baixar** (em Mais › Tradução). Quando você baixar um capítulo pelo botão de download de sempre, o Mangalate traduz todas as páginas junto, com uma notificação de progresso. Depois dá para ler traduzido **sem internet**.
- As páginas traduzidas de capítulos baixados ficam guardadas até você apagá-las na mesma tela.

## O que acontece em cada página

1. O texto é localizado por OCR no celular ou no servidor.
2. As falas são traduzidas.
3. O modo local mantém a segmentação e limpeza da 0.5.0; o servidor reconstrói regiões de texto com seu próprio pipeline. A arte fora do texto deve ser preservada e precisa de revisão visual.
4. O texto traduzido é diagramado no balão em fonte de quadrinho, com tamanho e quebra de linha ajustados automaticamente.
5. A página fica salva no celular. As páginas seguintes já vão sendo traduzidas enquanto você lê.

## Diagramação local

- Texto centralizado na área útil do corpo do balão, com margens internas e sem aumentar a caixa para fora do balão.
- Fonte limitada pelo tamanho da página e reduzida até a fala caber; não há cortes arbitrários dentro de palavras.
- Divisão silábica em português brasileiro com hífen quando uma palavra não cabe inteira, usando o dicionário DivSilab.
- Mudanças de modo, idioma e motor podem invalidar traduções em cache. Prepare os capítulos novamente antes de sair para ler offline.

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

- OCR de japonês vertical, letras estilizadas, balões abertos e texto sobre arte podem errar em qualquer modo. Não há promessa de resultado automático impecável.
- O servidor usa LaMa e perfis de diagramação próprios, com controles para rejeitar alterações grosseiras. Isso não substitui revisão página a página; consulte [QUALITY.md](server/QUALITY.md).
- O perfil do servidor tenta evitar onomatopeias fora de balões por padrão; essa detecção é heurística e não uma classificação perfeita.
- CPU atende PCs de diferentes marcas. CUDA é um perfil separado; ROCm/AMD é experimental em Linux compatível. DirectML/OpenVINO não estão implementados.
- O renderizador WebGPU experimental do Mihon é trocado pelo leitor clássico enquanto a tradução está ligada.
- O app não inclui fontes de conteúdo; extensões são instaladas por você, como no Mihon.

## Créditos e licença

- Baseado no [Mihon](https://github.com/mihonapp/mihon) (Apache 2.0).
- OCR e tradução no celular: Google ML Kit. Fonte Comic Neue (SIL OFL 1.1).
- Modo servidor: [manga-image-translator](https://github.com/zyddnys/manga-image-translator) (GPL-3.0), executado como serviço separado.
- Ícones: Material Symbols (Apache 2.0).
- Padrões de divisão silábica: [DivSilab/LibreOffice](https://github.com/LibreOffice/dictionaries/tree/master/pt_BR), Raimundo Santos Moura. Arquivo original sem modificações, sob MPL; créditos e licença distribuídos em `app/src/main/assets/lettering/`.

O aplicativo e os arquivos próprios mantêm a licença Apache 2.0, ver [LICENSE](LICENSE). O motor separado inclui manga-image-translator sob GPL-3.0 e conserva seu código e licença em `/opt/manga-image-translator` nas imagens Docker. Modelos baixados têm licenças próprias; o NLLB Básico exige atenção ao uso não comercial, como explicado no manual do servidor.
