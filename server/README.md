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
| Hardware | `1` (CPU) se não souber, ou com placa AMD RX 6000 ou mais antiga, ou Intel; `2` se tiver placa NVIDIA. Radeon RX 7000 ou mais nova: veja [AMD no Windows](#amd-no-windows-radeon-rx-7000-ou-mais-nova-experimental) |
| Celular na mesma rede Wi-Fi | `s` |
| Velocidade | Enter. O padrão é Rápido em CPU e Qualidade com placa NVIDIA |
| Qual IA | Groq e depois Gemini como reserva. Com o Ollama instalado, ele pode entrar como 3ª opção. Passo a passo no [guia de IAs](BYOK.md) |
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
| `--glossary /work/glossario.csv` | Nomes e termos fixos (colunas `source,target`, e `gender` opcional com `m` ou `f` para o gênero do personagem); vencem os termos aprendidos |
| `--work "Nome da obra"` | Obra para a memória (padrão: nome do arquivo). Use o mesmo nome em todos os capítulos |
| `--no-memory` | Traduz sem a memória da obra (sem glossário aprendido e sem páginas anteriores) |
| `--speed fast` / `--speed quality` | Força uma velocidade |
| `--diagnostics` | Salva máscaras e regiões de cada página em `diagnostico/` |
| `--art-text traduzir` | Experimental: traduz também a fala escrita sobre o desenho; o fundo sob as letras é refeito pelo modelo e pode sair borrado (padrão: `preservar`, que deixa no original) |
| `--box-layout` | Encaixa o texto na caixa do original, como na 0.5.3 (para comparar) |

Com placa NVIDIA, use `--profile gpu run ... translator-gpu` e acrescente `--gpu`. No Linux/macOS, troque `${PWD}` por `$PWD`.

**Memória da obra.** A cada página, o servidor guarda os nomes e termos que a IA usou e as falas da página. Nas próximas páginas e capítulos da mesma obra, a IA recebe esses termos e as falas das duas páginas anteriores, então um nome sai sempre igual e o gênero de cada personagem, quando a página mostra, fica guardado. A memória é a mesma para o app e para este comando, e fica no volume `memoria` do Docker (não some com o `py rebuild.py`). O lote também grava `glossario.csv` com tudo o que a obra já tem: corrija o que quiser e passe de volta com `--glossary`.

Na saída, `capitulo-para-revisar.cbz` traz as páginas em ordem; quando uma página falha, fica o original, nunca uma página em branco. Em `revisao-completa.zip` estão os originais, os resultados e um `revisao.md` com o texto lido e o traduzido de cada página. Se três páginas seguidas falharem, o lote para de chamar a IA.

Para ler o CBZ no app, coloque-o na pasta de armazenamento do Mangalate, em `manga/Nome do mangá/`, e atualize a fonte Local.

## Outros sistemas e placas

- **Linux/macOS:** use os mesmos comandos, trocando `py` por `python3`. A aceleração por placa de vídeo é só NVIDIA; Mac usa CPU.
- **AMD:** Radeon RX 7000 ou mais nova acelera no Windows pelo WSL2 (veja abaixo). Placas mais antigas (RX 6000 para trás) usam CPU no motor, mas o Ollama, se você usar, roda nelas (veja o [guia de IAs](BYOK.md#ollama-experimental)). No Linux com ROCm, no `python3 setup.py` escolha `3`. As duas opções AMD são experimentais, ainda não testadas em placa real. Rode `python hardware.py` para ver o que foi detectado.
- **Intel, DirectML e OpenVINO:** não implementados; use CPU.

### AMD no Windows (Radeon RX 7000 ou mais nova, experimental)

O servidor roda no Ubuntu do WSL2, e a placa chega até ele pelo ROCm da AMD. Funciona com Radeon RX 7000 e RX 9000 (e Ryzen AI recentes); RX 6000 e mais antigas não são suportadas pela AMD. A placa deixa a página umas 4 a 5 vezes mais rápida que o processador (estimativa, ainda sem medição em placa real).

1. Atualize o driver AMD Adrenalin para a versão 26.2.2 ou mais nova.
2. No PowerShell: `wsl --install -d Ubuntu-24.04` e reinicie o PC. Abra o "Ubuntu 24.04" no menu Iniciar.
3. No Ubuntu, instale o ROCm 7.2 para WSL com a librocdxg, seguindo o [guia da AMD para Radeon no WSL](https://rocm.docs.amd.com/projects/radeon-ryzen/en/latest/docs/install/installrad/wsl/howto_wsl.html). No fim deve existir o arquivo `/opt/rocm/lib/librocdxg.so`.
4. Instale o Docker dentro do Ubuntu: `curl -fsSL https://get.docker.com | sudo sh` e depois `sudo usermod -aG docker $USER` (feche e abra o Ubuntu). Use este Docker, não o Docker Desktop.
5. Ainda no Ubuntu: `git clone https://github.com/delkrusty/Mangalate.git`, `cd Mangalate/server` e `python3 setup.py`. Em Hardware, escolha `4`.

Ao iniciar, o servidor escreve no log `Placa de vídeo em uso: ...` (veja com `docker compose --profile amd-wsl logs translator-amd-wsl`). Se aparecer `usando o processador`, o ROCm não chegou ao container: confira o passo 3. O celular conecta no IP do Windows, porta 5003, como no modo normal; na primeira vez o Windows pode pedir para liberar o acesso do WSL na rede.

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
