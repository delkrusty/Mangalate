# Servidor + IA: qual IA usar e como configurar

Os limites gratuitos mudam com frequência; confira a página do provedor antes de usar.

## Como funciona

O servidor Mangalate roda no seu computador: lê o texto da página, apaga o original e escreve a tradução. **Só a tradução** é feita por uma IA, usando uma chave que é sua — ou pelo Ollama, no próprio computador. O resultado sai em português brasileiro natural, respeitando nomes e o jeito de cada personagem.

O aplicativo no celular fala só com o seu servidor, usando a **Chave Mangalate**. A chave da IA fica só no servidor e nunca vai para o celular.

O antigo perfil Básico (tradução NLLB, sem IA) saiu na 0.5.3: nos testes ele usava português de Portugal ("estás a falar", "preciso de ti") e perdia falas.

## O que é enviado no BYOK

Somente o **texto** das falas de cada página, em inglês, junto com as instruções de tradução. As imagens das páginas não saem do seu computador. Cada página é um pedido à IA, então um capítulo de 117 páginas usa cerca de 117 pedidos.

## Qual escolher

Testado em 14/10/2026 com as mesmas falas (frases de teste, um pedido por provedor):

| | Tempo | Estilo | Limite grátis |
|---|---|---|---|
| **Groq** (`openai/gpt-oss-120b`) | ~1 s | Natural, um pouco mais neutro | Exemplo publicado: 1.000 pedidos/dia por modelo, 30 por minuto |
| **Gemini** (`gemini-flash-lite-latest`) | ~4 s | Mais coloquial ("tá", "a gente", "né") | Cota diária por modelo, vista no AI Studio. No plano grátis o Google pode usar o conteúdo para melhorar os produtos dele |
| **OpenRouter** (modelos `:free`) | varia | varia | **50 pedidos/dia** — não chega a um capítulo. 1.000/dia após comprar US$ 10 em créditos uma vez |
| **Ollama** (no seu PC) | depende do PC | depende do modelo | Sem limite e sem internet; exige computador forte |

**Recomendado: Groq e Gemini juntos.** Cada página é um pedido; quando o primeiro atinge o limite grátis, o servidor passa sozinho para o segundo e volta ao primeiro quando ele liberar. A leitura não para.

## Passo 1 — criar as chaves

- **Groq:** entre em [console.groq.com/keys](https://console.groq.com/keys) e clique em **Create API Key**.
- **Gemini:** entre em [aistudio.google.com/apikey](https://aistudio.google.com/apikey) com sua conta Google e clique em **Create API key**.
- **OpenRouter:** [openrouter.ai/keys](https://openrouter.ai/keys). Copie também o nome de um modelo terminado em `:free`.

Guarde as chaves só para colar no instalador. **Não mande as chaves em conversas, prints ou mensagens.** Se uma vazar, apague-a no site e crie outra.

## Passo 2 — rodar o instalador

Dentro da pasta `server`:

```powershell
py setup.py
```

1. **Hardware:** `1` (CPU) se não souber.
2. **Celular na mesma rede Wi-Fi:** `s`.
3. **Substituir a configuração:** `s`.
4. **Número da IA:** `1` para Groq (ou só Enter).
5. **Modelo:** aperte **Enter** para usar o recomendado.
6. **Chave:** no site, copie a chave (botão **Copiar** ou Ctrl+C), volte ao PowerShell e **só aperte Enter** — no Windows o instalador lê a chave copiada, sem precisar colar. Deve aparecer "Chave recebida: … caracteres". Ela fica só em `server/secrets/provider_key.txt`.
7. **Tem chave de outra IA para usar como reserva?** `s`, escolha `2` (Gemini) e repita os passos 5 e 6. Quando não tiver mais, responda `n`.
8. Inicie e teste uma página antes de abrir um capítulo:

```powershell
py rebuild.py
python check.py --warmup
```

No celular nada muda: o endereço e a **Chave Mangalate** continuam os mesmos. Para trocar de IA ou acrescentar outra, rode `py setup.py` de novo.

## O que acontece no limite

- Um provedor que responde "limite atingido" descansa pelo tempo que ele pedir (normalmente 1 minuto) e a página vai para o próximo.
- Depois de três limites seguidos, ele descansa 1 hora — é o caso da cota do dia.
- Chave errada, sem saldo ou modelo inexistente: descansa 1 hora e o próximo assume. O aviso aparece em `docker compose logs`.
- Se todos estiverem no limite, o celular mostra erro naquela página e ela pode ser traduzida depois.
- Páginas traduzidas por provedores diferentes podem variar um pouco o estilo.

## Ollama: grátis e sem internet (experimental)

1. Instale o [Ollama](https://ollama.com) e baixe um modelo, por exemplo `ollama pull qwen3:8b`.
2. Deixe o Ollama aberto, rode `py setup.py`, escolha BYOK e a opção **Ollama** e digite o nome do modelo.

Ainda não foi testado com um modelo real no Mangalate. Em CPU, cada página pode levar dezenas de segundos.

## Problemas comuns

- **Páginas voltam com erro no meio do capítulo:** todos os provedores escolhidos estão no limite. Espere ou acrescente outro provedor no instalador.
- **Chave recusada:** confira se colou a chave da IA no instalador e a **Chave Mangalate** no celular — são coisas diferentes.
- **Modelo não encontrado:** o nome precisa ser exatamente o do provedor, incluindo prefixos como `openai/` ou o sufixo `:free`.
