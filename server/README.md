# Servidor de tradução do Mangalate

O app manda cada página para este servidor e recebe de volta a página limpa, reconstruída e traduzida. Ele usa o [manga-image-translator](https://github.com/zyddnys/manga-image-translator) com um portão de acesso por chave.

## Opção A · Google Colab (GPU grátis)

1. Abra o notebook: [Mangalate_Colab.ipynb](https://colab.research.google.com/github/delkrusty/Mangalate/blob/main/server/colab/Mangalate_Colab.ipynb).
2. **Ambiente de execução › Alterar tipo de ambiente › GPU T4**.
3. Na célula 1, preencha a chave do motor que vai usar (por exemplo `DEEPSEEK_API_KEY`). `MANGALATE_KEY` pode ficar vazia: uma senha é gerada.
4. Rode as células 2, 3 e 4. A célula 3 mostra:
   ```
   Endereço do servidor: https://xxxx.trycloudflare.com
   Chave de acesso     : ...
   ```
5. No app: **Configurações › Mangalate**, cole os dois e toque em **Testar conexão**.

O Colab gratuito desliga após algumas horas ou por inatividade, e o endereço muda a cada execução.

## Opção B · Docker no seu PC

Requer [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Windows/macOS) ou Docker Engine (Linux).

```bash
git clone https://github.com/delkrusty/Mangalate.git
cd Mangalate/server
cp .env.example .env      # no Windows: copy .env.example .env
# edite .env: defina MANGALATE_KEY e a chave do motor (ex.: DEEPSEEK_API_KEY)

docker compose --profile cpu up -d     # sem placa NVIDIA
# ou
docker compose --profile gpu up -d     # com placa NVIDIA
```

A primeira execução baixa a imagem e os modelos (vários GB). Depois, no app:

- **Endereço:** `http://IP-DO-PC:5003` (ex.: `http://192.168.0.15:5003`; veja o IP com `ipconfig` no Windows)
- **Chave:** o valor de `MANGALATE_KEY`

O celular precisa estar na mesma rede Wi-Fi. Para ler fora de casa, use um túnel como [Tailscale](https://tailscale.com/) ou Cloudflare Tunnel apontando para a porta 5003.

### Desempenho esperado

| Hardware | Perfil recomendado no app |
|---|---|
| Só CPU | Rápida |
| GPU NVIDIA com 6 GB+ (ou Colab T4) | Alta |
| GPU NVIDIA com 10 GB+ | Máxima |

## Escolhendo o motor

Defina no `.env` (ou na célula 1 do Colab) a chave do motor selecionado no app:

| Motor no app | Variável |
|---|---|
| DeepSeek | `DEEPSEEK_API_KEY` |
| Gemini | `GEMINI_API_KEY` |
| OpenAI | `OPENAI_API_KEY` |
| Groq | `GROQ_API_KEY` |
| Compatível OpenAI | `CUSTOM_OPENAI_API_BASE`, `CUSTOM_OPENAI_MODEL` |
| Offline (NLLB) | nenhuma |

## Como o app conversa com o servidor

`POST /translate/with-form/image` (multipart: `image` + `config` em JSON), com o cabeçalho `X-Mangalate-Key`. A resposta é a página em PNG. `POST /queue-size` é usado pelo botão **Testar conexão**.
