# Guia de IAs do servidor

O servidor lê a página, apaga o texto original e escreve a tradução. Só a **tradução** é feita por uma IA, com uma chave que é sua, ou pelo Ollama, no próprio PC. Só o **texto** das falas, em inglês, é enviado; as imagens não saem do seu computador. Cada página é um pedido à IA: um capítulo de 100 páginas usa cerca de 100 pedidos.

Os limites grátis mudam com frequência; confira na página de cada provedor.

## Qual escolher

Testado em 14/10/2026 com as mesmas falas:

| | Tempo | Estilo | Limite grátis |
|---|---|---|---|
| **Groq** (`openai/gpt-oss-120b`) | ~1 s | Natural, um pouco mais neutro | Exemplo publicado: 1.000 pedidos por dia, 30 por minuto |
| **Gemini** (`gemini-flash-lite-latest`) | ~4 s | Mais coloquial ("tá", "a gente") | Cota diária vista no AI Studio. No plano grátis, o Google pode usar o conteúdo para melhorar os produtos dele |
| **OpenRouter** (modelos `:free`) | varia | varia | 50 pedidos por dia, o que não chega a um capítulo |
| **Ollama** (no seu PC) | depende do PC | depende do modelo | Sem limite e sem internet; exige PC forte |

**Recomendado: Groq e Gemini juntos.** Quando um chega ao limite grátis, o servidor passa sozinho para o outro e volta ao primeiro quando ele liberar.

## 1. Criar as chaves

- **Groq:** [console.groq.com/keys](https://console.groq.com/keys) › **Create API Key**.
- **Gemini:** [aistudio.google.com/apikey](https://aistudio.google.com/apikey), com sua conta Google › **Create API key**.
- **OpenRouter:** [openrouter.ai/keys](https://openrouter.ai/keys). Anote também o nome de um modelo terminado em `:free`.

**Não mande as chaves em conversas, prints ou mensagens.** Se uma vazar, apague-a no site e crie outra.

## 2. Rodar o instalador

Na pasta `server`, rode `py setup.py`:

1. **Hardware:** `1` (CPU) se não souber.
2. **Celular na mesma rede Wi-Fi:** `s`.
3. **Substituir a configuração** (se já existir): `s`.
4. **Velocidade:** Enter. O padrão é Rápido em CPU, cerca de 3 vezes mais rápido e com limpeza praticamente igual nos testes, e Qualidade com placa NVIDIA.
5. **Qual IA:** `1` para Groq.
6. **Modelo:** Enter para usar o recomendado.
7. **Chave:** copie a chave no site (botão Copiar ou Ctrl+C), volte ao PowerShell e **só aperte Enter**: no Windows o instalador lê a chave copiada. Deve aparecer "Chave recebida: … caracteres".
8. **Tem chave de outra IA para usar como reserva?** `s`, escolha `2` (Gemini) e repita os passos 6 e 7. Quando acabar, responda `n`.
9. **Iniciar agora:** `s`. Depois teste uma página com `py check.py --warmup`.

No celular nada muda: o endereço e a Chave Mangalate continuam os mesmos. Para trocar ou acrescentar uma IA, rode `py setup.py` de novo.

## O que acontece no limite

- Uma IA que responde "limite atingido" descansa pelo tempo que pedir (normalmente 1 minuto), e a página vai para a próxima.
- Depois de três limites seguidos, ela descansa 1 hora: é o caso da cota do dia.
- Chave errada, sem saldo ou modelo inexistente: descansa 1 hora e a próxima assume. O aviso aparece em `docker compose logs`.
- Se todas estiverem no limite, o app mostra "Limite gratuito de todos os provedores atingido" naquela página.
- Páginas traduzidas por IAs diferentes podem variar um pouco no estilo.

## Ollama (experimental)

1. Instale o [Ollama](https://ollama.com) e baixe um modelo, por exemplo `ollama pull gpt-oss:20b`.
2. Com o Ollama aberto, rode `py setup.py`, escolha **Ollama** e digite só o nome do modelo (por exemplo `gpt-oss:20b`), sem `ollama pull`.

O Ollama usa a placa de vídeo sozinho, inclusive AMD. Testado em 25/10/2026 num PC com 16 GB de RAM e Radeon RX 6600 (8 GB), em 6 páginas:

| Modelo | Tradução por página | Qualidade |
|---|---|---|
| `gpt-oss:20b` (13 GB) | 6 a 28 s; a primeira, 43 s (carrega o modelo) | Erra mais que o Groq: em 35 falas, 2 com o sentido invertido, 3 com gênero errado e 3 literais demais. Revise antes de publicar |
| `gemma3:4b` (3,4 GB) | 2 a 6 s | Erra o sentido com frequência: gênero trocado, "calcinha" virou "calça", uma crítica virou elogio |

Prefira o `gpt-oss:20b`. O servidor espera até 2 minutos por uma IA no próprio PC (45 s para as da internet) e pede ao `gpt-oss` um raciocínio curto, que deixa a página umas duas vezes mais rápida. Ainda não foi validado com um capítulo inteiro.

## Problemas comuns

- **Páginas com erro no meio do capítulo:** todas as IAs escolhidas estão no limite. Espere ou acrescente outra.
- **Chave recusada:** a chave da IA vai no instalador e a Chave Mangalate vai no celular. São coisas diferentes.
- **Modelo não encontrado:** o nome precisa ser exatamente o do provedor, incluindo prefixos como `openai/` ou o sufixo `:free`.
