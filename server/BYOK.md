# Básico ou BYOK: qual usar e como configurar

Rascunho para revisão (14/10/2026). Os limites gratuitos mudam com frequência; confira sempre a página do provedor antes de usar.

## A diferença em uma frase

- **Básico:** o seu computador faz tudo — lê o texto, apaga, traduz e escreve. Não precisa de conta em lugar nenhum. A tradução é feita pelo NLLB, que é rápido mas literal e puxa para o português de Portugal ("estás a falar", "preciso de ti").
- **BYOK** ("traga sua própria chave"): o seu computador continua lendo, apagando e escrevendo. **Só a tradução** é feita por uma IA de texto na internet, usando uma chave que é sua. O resultado fica muito mais natural em português brasileiro, respeita nomes próprios e o jeito de cada personagem.

O aplicativo no celular é o mesmo nos dois casos. Ele sempre fala com o seu servidor Mangalate, usando a **Chave Mangalate**. A chave da IA fica só no servidor e nunca vai para o celular.

## O que é enviado no BYOK

Somente o **texto** das falas de cada página, em inglês, junto com as instruções de tradução. As imagens das páginas não saem do seu computador. Cada página é um pedido à IA, então um capítulo de 117 páginas usa cerca de 117 pedidos.

## Onde conseguir uma chave grátis

| Provedor | Grátis? | Quanto dá | Atenção |
|---|---|---|---|
| **Google Gemini (AI Studio)** | Sim, nos modelos Flash e Flash-Lite | Limite diário por modelo; veja a sua cota no AI Studio | No plano gratuito, o Google pode usar o conteúdo enviado para melhorar os produtos dele |
| **Groq** | Sim, plano Free | Exemplo publicado: 1.000 pedidos por dia por modelo, 30 por minuto | Os limites exatos da sua conta ficam em Settings › Limits |
| **OpenRouter** (modelos com `:free` no nome) | Sim, sem cartão | **50 pedidos por dia** — não chega a um capítulo inteiro. Sobe para 1.000 por dia depois de uma compra única de US$ 10 em créditos | 20 pedidos por minuto; limite por conta, não por chave |

Indicação para começar: **Gemini Flash-Lite** ou **Groq**. Se o limite do dia acabar no meio de um capítulo, as páginas restantes ficam no original e podem ser traduzidas no dia seguinte.

### Gemini (Google AI Studio)

1. Entre em [aistudio.google.com](https://aistudio.google.com) com sua conta Google e clique em **Get API key** › **Create API key**.
2. No instalador, use:
   - Endpoint: `https://generativelanguage.googleapis.com/v1beta/openai/`
   - Modelo: `gemini-flash-lite-latest`
   - Chave: a que você acabou de criar.

### Groq

1. Crie a conta em [console.groq.com](https://console.groq.com) e vá em **API Keys** › **Create API Key**.
2. No instalador, use:
   - Endpoint: `https://api.groq.com/openai/v1`
   - Modelo: um dos listados em **Models** no console (por exemplo `openai/gpt-oss-120b`).
   - Chave: a que você criou.

### OpenRouter

1. Crie a conta em [openrouter.ai](https://openrouter.ai) e gere uma chave em **Keys**.
2. No instalador, use:
   - Endpoint: `https://openrouter.ai/api/v1`
   - Modelo: um modelo terminado em `:free`, copiado da lista de modelos do site.

## Como ligar o BYOK no servidor

Dentro da pasta `server`:

```powershell
py setup.py
```

1. **Perfil:** digite `2` (BYOK).
2. **Hardware e rede:** responda igual ao Básico.
3. **Endpoint, modelo e chave:** cole os valores do provedor escolhido (tabela acima). A chave fica oculta enquanto você digita e é guardada em `server/secrets/provider_key.txt`.
4. Inicie e teste uma página antes de abrir um capítulo:

```powershell
docker compose --profile cpu up --build -d
python check.py --warmup
```

No celular nada muda: o endereço e a **Chave Mangalate** continuam os mesmos.

Para voltar ao Básico, rode `py setup.py` de novo e escolha `1`.

## Grátis e sem internet: IA no próprio computador (em preparação)

O [Ollama](https://ollama.com) roda modelos de IA no seu PC, sem conta e sem limite diário, e fala o mesmo "idioma" dos provedores acima. **Ainda não funciona pelo instalador**, porque ele só aceita endereços HTTPS e o Docker precisa enxergar o Ollama. Essa opção está prevista para a próxima versão. Ela exige um computador mais forte: em CPU, cada página pode levar dezenas de segundos.

## Problemas comuns

- **"Limite atingido" ou páginas que voltam em inglês no meio do capítulo:** a cota grátis do dia acabou. Espere o próximo dia ou troque de provedor.
- **Chave recusada:** confira se colou a chave da IA no instalador e a **Chave Mangalate** no celular — são coisas diferentes.
- **Modelo não encontrado:** o nome precisa ser exatamente o que o provedor mostra, incluindo prefixos como `openai/` ou o sufixo `:free`.
