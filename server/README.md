# Servidor Mangalate

O servidor roda no seu PC com Docker. Ele lê o texto das páginas, apaga o original e escreve a tradução feita por uma IA escolhida por você. Só o texto das falas vai para a IA. O celular conversa apenas com o seu PC.

- **Qual IA usar e como pegar as chaves grátis:** [guia de IAs](BYOK.md).
- **O que o servidor garante e o que ainda precisa de revisão:** [QUALITY.md](QUALITY.md).

## Instalar (Windows)

1. Instale o [Docker Desktop](https://docs.docker.com/desktop/setup/install/windows-install/), o [Python](https://www.python.org/downloads/) e o [Git](https://git-scm.com/downloads). Abra o Docker Desktop e espere ele indicar que está rodando.
2. No PowerShell, um comando por vez:

```powershell
git clone https://github.com/delkrusty/Mangalate.git
cd Mangalate/server
py setup.py
```

Se `py` não funcionar, use `python`. O instalador pergunta, nesta ordem:

| Pergunta | O que responder |
|---|---|
| Hardware | `1` (CPU) se não souber; `2` se tiver placa NVIDIA |
| Celular na mesma rede Wi-Fi | `s` |
| Velocidade | Enter. O padrão é Rápido em CPU e Qualidade com placa NVIDIA |
| Qual IA | Groq e depois Gemini como reserva. Passo a passo no [guia de IAs](BYOK.md) |
| Iniciar agora | `s` |

No fim, o instalador mostra a **Chave Mangalate**, que vai no app. Ela fica salva em `server/secrets/mangalate_key.txt`.

3. Teste uma página antes de usar no celular:

```powershell
py -m pip install Pillow
py check.py --warmup
```

A primeira vez baixa os modelos e demora. Abra `server/review/teste-traduzido.png` e confira se o texto virou português: conectar não basta, o que importa é o resultado.

## Ligar o app

1. Rode `ipconfig` no PC e anote o IPv4 da rede Wi-Fi, por exemplo `192.168.0.15`.
2. No app: Mais › Tradução (Mangalate) › **Servidor**.
3. Endereço `http://192.168.0.15:5003` (troque pelo seu IP) e a Chave Mangalate.
4. Toque em **Testar conexão**.

`localhost` no celular é o próprio celular. Se o Windows perguntar sobre o firewall, permita só em redes privadas. Não abra a porta 5003 no roteador.

## Atualizar

```powershell
git pull
py rebuild.py
```

O `rebuild.py` reconstrói o servidor, mantém chaves, configuração e modelos e confere se a versão nova está rodando. Ele termina com "Servidor atualizado e rodando a versão nova.". Não use `docker compose up --build`: em versões recentes do Docker Desktop ele pode falhar ("failed to execute bake") e continuar rodando a versão antiga sem avisar.

Para trocar ou acrescentar uma IA, rode `py setup.py` de novo. Para parar o servidor: `docker compose --profile cpu stop` (ou `gpu`).

## Traduzir um capítulo inteiro no PC

Gera um CBZ traduzido e um pacote de revisão com os originais lado a lado. Coloque o capítulo na pasta `server` e rode:

```powershell
docker compose --profile cpu run --rm -v "${PWD}:/work" translator-cpu /mangalate/batch.py --input /work/capitulo.cbz --output /work/revisao --profile byok
```

Opções úteis:

| Opção | Para quê |
|---|---|
| `--pages 1-10` | Só algumas páginas, bom para testar |
| `--glossary /work/glossario.csv` | Nomes e termos fixos (colunas `source,target`) |
| `--speed fast` / `--speed quality` | Força uma velocidade |
| `--diagnostics` | Salva máscaras e regiões de cada página em `diagnostico/` |

Com placa NVIDIA, use `--profile gpu run ... translator-gpu` e acrescente `--gpu`. No Linux/macOS, troque `${PWD}` por `$PWD`.

Na saída, `capitulo-para-revisar.cbz` traz as páginas em ordem; quando uma página falha, fica o original, nunca uma página em branco. Em `revisao-completa.zip` estão os originais, os resultados e um `revisao.md` com o texto lido e o traduzido de cada página. Se três páginas seguidas falharem, o lote para de chamar a IA.

Para ler o CBZ no app, coloque-o na pasta de armazenamento do Mangalate, em `manga/Nome do mangá/`, e atualize a fonte Local.

## Outros sistemas e placas

- **Linux/macOS:** use os mesmos comandos, trocando `py` por `python3`. A aceleração por placa de vídeo é só NVIDIA; Mac usa CPU.
- **AMD:** no Windows, use CPU. No Linux com ROCm há um perfil experimental, ainda não testado em placa real: no `py setup.py`, escolha `3`. Rode `python hardware.py` para ver o que foi detectado.
- **Intel, DirectML e OpenVINO:** não implementados; use CPU.

## Servidor na internet (HTTPS)

Para uma VPS sua, com domínio apontando para ela: instale como acima (com `py rebuild.py`), acrescente `MANGALATE_DOMAIN=seu-dominio.exemplo` ao `.env` e rode

```bash
docker compose -f docker-compose.yml -f docker-compose.public.yml --profile gpu up -d
```

O Caddy cuida do HTTPS e a porta 5003 deixa de ficar exposta. No firewall, libere só as portas 80 e 443. No app, use `https://seu-dominio.exemplo` ([HTTPS automático do Caddy](https://caddyserver.com/docs/automatic-https)).

## Colab

O [notebook Colab](https://colab.research.google.com/github/delkrusty/Mangalate/blob/main/server/colab/Mangalate_Colab.ipynb) traduz um ZIP/CBZ sem instalar Docker e exporta o CBZ e o pacote de revisão. Ele não é um servidor para o app e não usa a Chave Mangalate. Se usar uma IA, coloque a chave num Secret chamado `MANGALATE_PROVIDER_KEY`, nunca numa célula. O notebook ainda está na versão 0.5.2 e será atualizado. As regras de uso são as do [Colab](https://research.google.com/colaboratory/intl/pt-BR/faq.html).

## Problemas

- **Docker não encontrado:** abra o Docker Desktop e confira `docker compose version`.
- **App diz chave inválida:** use a Chave Mangalate, não a chave da IA, sem espaços extras.
- **Atualizei e nada mudou:** rode `py rebuild.py` e confira a mensagem final.
- **Erro 502 no app:** veja `docker compose logs --tail=80`. Se for limite das IAs, espere ou acrescente outra IA.
- **Placa NVIDIA não reconhecida:** confira `nvidia-smi`, o driver e o [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html). Na dúvida, use CPU.

## Arquivos e licenças

```text
secrets/mangalate_key.txt   senha do app para este servidor
secrets/provider_key.txt    chaves das IAs (só neste PC)
.env                        hardware, velocidade e endereços; sem chaves
```

O motor é o [manga-image-translator](https://github.com/zyddnys/manga-image-translator) (GPL-3.0), numa versão fixa. Ele roda num serviço interno, e só o gateway com a Chave Mangalate fica acessível pela rede. `engine_compat.py`, `quality.py`, `providers.py` e `seams.py` trazem as correções do Mangalate; `engine_compat.py` é GPL-3.0 ([LICENSE.engine](LICENSE.engine)). Os modelos têm licenças próprias. Use apenas capítulos que você tem direito de usar.

O Docker Desktop pode exigir licença paga em alguns usos empresariais ([termos](https://docs.docker.com/subscription/desktop-license/)).
