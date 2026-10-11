<div align="center">

<img src="server/assets/icon.png" width="120" alt="Mangalate"/>

# Mangalate

Leitor de mangá para Android, baseado no [Mihon](https://github.com/mihonapp/mihon), que **traduz as páginas automaticamente** para o idioma que você escolher, colocando o texto traduzido dentro dos próprios balões.

</div>

## Como funciona

1. Você lê normalmente: biblioteca, extensões, downloads e leitor do Mihon continuam iguais.
2. No leitor, toque no botão **de tradução** (ícone 文A na barra inferior).
3. Cada página é enviada ao **servidor do Mangalate**, que:
   - detecta textos e balões (detector de quadrinhos CTD ou DBNet);
   - faz OCR do texto original (modelo 48px, japonês/chinês/coreano/inglês);
   - cria uma máscara dos caracteres com margem adaptativa, sem apagar o balão inteiro;
   - reconstrói o fundo com LaMa (retículas, degradês e traços da arte);
   - traduz todas as falas da página juntas, com contexto e verificação pós-tradução;
   - diagrama o texto traduzido no balão, ajustando tamanho e quebra de linha.
4. A página traduzida fica em cache no celular. Toque no botão de novo para ver o original.

As páginas vizinhas são traduzidas em segundo plano enquanto você lê, então o capítulo vai ficando pronto à frente.

## Instalar

Baixe o APK mais recente em **[Releases](https://github.com/delkrusty/Mangalate/releases/latest)**:

- `Mangalate-arm64-v8a.apk` para a maioria dos celulares atuais;
- `Mangalate-universal.apk` se não souber qual escolher.

Todos os builds são assinados com a mesma chave, então dá para atualizar sem desinstalar.

## Servidor de tradução

O trabalho pesado (OCR, reconstrução e tradução) roda num servidor, não no celular. Há duas opções:

| Opção | Custo | Quando usar |
|---|---|---|
| [Google Colab](server/README.md#opção-a--google-colab-gpu-grátis) | Grátis (GPU T4) | Para testar ou ler algumas horas por dia |
| [Docker no PC](server/README.md#opção-b--docker-no-seu-pc) | Seu PC | Uso diário, rede de casa, GPU NVIDIA opcional |

Depois, no app: **Mais › Configurações › Mangalate**, cole o endereço e a chave, e toque em **Testar conexão**.

### Motores de tradução

| Motor | Observação |
|---|---|
| DeepSeek | Recomendado: muito barato e bom com contexto |
| Gemini | Faixa gratuita nos modelos Flash |
| DeepL | Plano Free com 500 mil caracteres/mês |
| OpenAI, Groq | Alternativas com chave |
| Compatível OpenAI | Ollama, LM Studio, OpenRouter |
| Offline (NLLB) | Roda no servidor, sem chave |

As chaves ficam **só no servidor** (`server/.env` ou Secrets do Colab), nunca dentro do APK.

## Configurações no app

- Idioma de destino (PT-BR, inglês, espanhol e outros);
- Qualidade da limpeza: **Rápida**, **Alta** (padrão) ou **Máxima** (super-resolução 2x);
- Margem da máscara: aumente se sobrarem restos de letras, diminua se estiver apagando arte;
- Traduzir só dentro de balões (ignora onomatopeias);
- Diagramação automática/mangá/clássica, tamanho da fonte e caixa alta;
- Cache das páginas traduzidas.

## Compilar

O GitHub Actions compila a cada push em `main` e publica o APK em Releases. Para compilar localmente: JDK 21 e Android SDK, depois:

```bash
./gradlew :app:assembleRelease -Pdist=local
```

## Limitações conhecidas

- Onomatopeias desenhadas sobre rostos, cabelos ou cenários muito detalhados podem ficar com área suavizada.
- O renderizador WebGPU experimental do Mihon é trocado pelo leitor clássico enquanto a tradução está ligada.
- O app não inclui fontes de conteúdo; extensões são instaladas por você, como no Mihon.

## Créditos e licença

- Baseado no [Mihon](https://github.com/mihonapp/mihon) (Apache 2.0).
- Pipeline de tradução: [manga-image-translator](https://github.com/zyddnys/manga-image-translator) (GPL-3.0), executado como serviço separado.
- Ícones: Material Symbols (Apache 2.0).

Distribuído sob a licença Apache 2.0, ver [LICENSE](LICENSE).
