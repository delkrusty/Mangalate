# Mangalate: servidor + IA sem complicação

No celular, o aplicativo oferece **No celular** ou **Servidor**. O servidor roda no seu computador: lê o texto, apaga o original e escreve a tradução; só o texto das falas vai para a IA que você escolher. Não é uma assinatura vendida pelo Mangalate. A chave Mangalate e a chave da IA são coisas diferentes.

## Qual caminho escolher

- **No celular:** prepare os idiomas uma vez no aplicativo; depois traduza offline. A limpeza local continua baseada na 0.5.0.
- **Docker + IA:** seu PC executa leitura do texto, limpeza e diagramação; a tradução vem da IA escolhida no menu do instalador — Groq e Gemini com cota grátis e alternância automática, OpenRouter, ou Ollama rodando no próprio PC sem internet. Mangalate não recebe pagamento nem comissão. A chave da IA fica no seu servidor. Veja o [guia de IAs](BYOK.md).
- O antigo perfil **Básico** (NLLB) saiu do instalador na 0.5.3. Instalações feitas antes continuam funcionando até você rodar `setup.py` de novo.
- **Colab:** envie um capítulo, acompanhe a tradução no notebook e baixe o resultado para ler offline. Não é oferecido como servidor permanente para o celular. As restrições e a disponibilidade de recursos são do Google ([regras oficiais](https://research.google.com/colaboratory/intl/pt-BR/faq.html)).

## Docker: primeiro uso no Windows

### Instale os programas

Instale [Docker Desktop](https://docs.docker.com/desktop/setup/install/windows-install/), [Python](https://www.python.org/downloads/) e [Git](https://git-scm.com/downloads). Abra o Docker Desktop e espere ele indicar que está rodando. Docker Desktop pode exigir licença paga em determinados usos empresariais; confira os termos, sem presumir que é gratuito para toda empresa ([termos do Docker Desktop](https://docs.docker.com/subscription/desktop-license/)).

Abra o PowerShell. Cole um comando por vez:

```powershell
git clone https://github.com/delkrusty/Mangalate.git
cd Mangalate/server
py setup.py
```

Se `py` não funcionar, tente `python setup.py`. O assistente pergunta:

1. **Qual IA vai traduzir:** escolha Groq (1) e depois Gemini (2) como reserva; as chaves são grátis. Passo a passo no [guia de IAs](BYOK.md).
2. **Hardware:** escolha CPU se não souber. NVIDIA-CUDA exige driver compatível e Container Toolkit ([instalação NVIDIA](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)). AMD-ROCm é experimental e exige Linux compatível; não é um perfil para Windows.
3. **Celular na mesma rede Wi-Fi:** escolha S para leitura ao vivo na rede local. Não exponha a porta 5003 no roteador.
4. **Iniciar agora:** escolha S. Ele verifica Docker Compose e executa a instalação.

Se preferir iniciar depois, ou para **atualizar depois de um `git pull`**:

```powershell
py rebuild.py
```

Ele constrói as imagens com `docker build`, reinicia o servidor mantendo chaves, configuração e modelos, e confere se a versão nova está rodando. Evite `docker compose up --build`: nas versões recentes do Docker Desktop ele pode falhar com "failed to execute bake" e continuar rodando a versão antiga sem avisar.

Use **somente um** perfil de hardware por vez. Não ative CPU, NVIDIA e AMD juntos.

### AMD, Radeon e Intel não ficam excluídas

O caminho CPU está disponível independentemente do fabricante. Rode `python hardware.py` para ver os candidatos e o estado real de cada backend. Não confunda detecção de placa com compatibilidade dos modelos.

No Linux com ROCm e uma Radeon/Instinct suportada, há um perfil **experimental**:

```bash
docker compose --profile amd-rocm up --build -d
```

Ele expõe `/dev/kfd` e `/dev/dri` somente ao worker, mantém as rodas AMD de PyTorch e deixa a tradução offline na CPU para não exigir CUDA no CTranslate2. A imagem base corresponde a uma tag publicada pela AMD; isso não valida automaticamente nosso pipeline inteiro ([PyTorch Radeon/ROCm](https://rocm.docs.amd.com/projects/radeon-ryzen/en/latest/docs/install/installrad/native_linux/install-pytorch.html)). Confirme a matriz de hardware/SO e as permissões dos dispositivos; este pacote não foi validado numa GPU AMD ([Docker com ROCm](https://rocm.docs.amd.com/projects/install-on-linux/en/latest/how-to/docker.html)).

No Windows com AMD/Intel, use CPU neste pacote. **DirectML e OpenVINO estão previstos na camada de hardware, não implementados nem anunciados como aceleração funcional.** O motor atual usa etapas PyTorch; adicionar um provider ONNX sem exportar/testar os modelos não resolve isso. Uma falha de aceleração pode ser resolvida parando o perfil experimental e iniciando CPU; não há fallback automático de contêiner já validado.

### Onde está a chave Mangalate

O assistente gera e mostra o caminho completo. Por padrão:

```text
Mangalate/server/secrets/mangalate_key.txt
```

No PowerShell, dentro da pasta `server`:

```powershell
Get-Content .\secrets\mangalate_key.txt
```

Copie o conteúdo do arquivo, não esse caminho. Essa é uma senha privada; não envie prints dela. Para usar outro local, altere `MANGALATE_KEY_FILE` em `.env` para o caminho do arquivo no computador. O Docker o monta em `/run/secrets/mangalate_key`; isso **não** significa que você deva criar uma pasta `/run` no Windows.

### Atualizar o servidor

Quando sair uma versão nova, dentro da pasta `server`:

```powershell
git pull
py rebuild.py
```

O `rebuild.py` constrói as imagens sem depender do "bake" do Docker Compose (que falha em algumas instalações do Docker Desktop), reinicia o servidor e confere se ele está rodando os arquivos desta pasta. Chaves, configuração e modelos baixados são mantidos. O hardware (CPU ou NVIDIA) vem da configuração feita no `py setup.py`.

### Teste de verdade antes de usar no celular

Ainda dentro da pasta `server`:

```powershell
py -m pip install Pillow
py check.py --warmup
```

Esse comando traduz uma página sintética, preparando os modelos. A primeira execução pode baixar arquivos grandes e demorar. **Abra `server/review/teste-traduzido.png` e confira se Hello world! virou português.** Uma conexão funcionando ou HTTP 200 não prova a qualidade da tradução. No BYOK, o comando pede confirmação porque o teste pode consumir saldo.

Se `DejaVuSans.ttf` não existir no Windows, o diagnóstico usa Arial do sistema. Não feche o terminal enquanto prepara os modelos.

### Ligue o aplicativo

Execute `ipconfig` no PC e procure o endereço IPv4 da placa conectada ao seu Wi-Fi, por exemplo `192.168.0.15`. No aplicativo:

1. Mais → Tradução (Mangalate) → **Servidor**.
2. Endereço: `http://192.168.0.15:5003`, trocando pelo IPv4 real do seu PC.
3. Chave Mangalate: conteúdo de `mangalate_key.txt`.
4. Toque em **Testar conexão**.
5. Abra um capítulo e toque em 文A.

`localhost` no celular é o próprio celular, não o computador. Se o Windows perguntar sobre firewall, permita somente redes privadas confiáveis. Não desligue o firewall inteiro.

## Linux ou macOS

Instale Docker Engine + plugin Compose no Linux ou Docker Desktop no macOS, além de Python e Git. Use os mesmos comandos, substituindo `py` por `python3` e `Get-Content` por `cat`. O perfil GPU deste pacote é NVIDIA; não prometa aceleração CUDA em Mac Apple Silicon. O pacote CPU também depende da disponibilidade das rodas de todas as bibliotecas para sua arquitetura.

## BYOK: servidor mais forte, sua chave, seus gastos

Rode `setup.py` e escolha 2. Informe endpoint HTTPS, nome exato do modelo e sua chave oculta. O cliente upstream exige compatibilidade com **Chat Completions**, `max_tokens`, `temperature` e `top_p`; uma API somente Responses ou um modelo que rejeite esses campos não é automaticamente compatível ([cliente upstream fixado](https://raw.githubusercontent.com/zyddnys/manga-image-translator/d6de6ab62a7be6afc0d07a3184149cdefbcd32f2/manga_translator/translators/custom_openai.py)).

Os caminhos padrão são:

```text
server/secrets/mangalate_key.txt   senha do app para seu servidor
server/secrets/provider_key.txt    chave da API, somente no servidor
server/.env                       perfil, endpoint, modelo e caminhos; sem chave API
```

Configure limite de gastos e alertas na conta do provedor. Validações e novas tentativas podem consumir mais API. GPU maior melhora capacidade, não garante uma tradução melhor: a qualidade também depende do OCR, modelo, contexto, glossário e revisão.

Se trocar a chave da API, recrie ou reinicie os containers para o worker carregá-la. O assistente faz isso quando você escolhe iniciar; alterar o arquivo sozinho não troca a chave já carregada em um processo rodando.

### Servidor público com HTTPS

Contrate a máquina e configure NVIDIA/Docker por conta própria. Não há provisionamento, revenda ou afiliado Mangalate. Configure um domínio DNS para o IP da máquina e acrescente `MANGALATE_DOMAIN=seu-dominio.example` ao `.env`.

```bash
docker compose -f docker-compose.yml -f docker-compose.public.yml --profile gpu up --build -d
```

Na VPS, libere no firewall somente HTTPS/HTTP para o Caddy e o acesso administrativo restrito que você utiliza. As portas dos motores não são publicadas. A porta 5003 deixa de ser publicada na configuração pública. No app, use `https://seu-dominio.example` e a chave Mangalate. HTTPS automático requer DNS correto e portas acessíveis ([documentação do Caddy](https://caddyserver.com/docs/automatic-https)).

## Preparar um capítulo com mais consistência e revisão

O processamento em lote BYOK é o caminho recomendado para buscar acabamento de scan. Ele usa dados das duas páginas anteriores e um glossário opcional como contexto, além de traduzir sequencialmente. A leitura ao vivo usa contexto da página, **não garante contexto de capítulo**.

No Linux/servidor, coloque `capitulo.cbz` e um glossário opcional `glossario.csv` em uma pasta `trabalho`:

```csv
source,target
Karai,Karai
Student Council,Conselho Estudantil
```

Execute da pasta `server`:

```bash
docker compose --profile gpu run --rm -v "$PWD/trabalho:/work" translator-gpu /mangalate/batch.py --input /work/capitulo.cbz --output /work/revisao --profile byok --gpu --glossary /work/glossario.csv
```

No PowerShell, substitua o argumento de volume por `"${PWD}/trabalho:/work"`. Sem glossário, remova os dois últimos argumentos. Sem placa NVIDIA, use o serviço `translator-cpu`, perfil Compose `cpu` e remova `--gpu`.

A saída contém:

- **capitulo-para-revisar.cbz:** páginas em ordem para leitura. Páginas bloqueadas mantêm o original, não uma página branca.
- **revisao-completa.zip:** originais, resultados, `revisao.md` legível e `review.json` com texto reconhecido/traduzido e estado de cada página. Após três falhas consecutivas, o lote para de chamar o motor e preserva as páginas restantes, evitando repetir gastos/falhas.

Revise sentido, nomes, ordem dos painéis, encaixe, contornos e arte antes de chamar de edição final. Os limites automáticos detectam mudança de tamanho e edição global excessiva, **não garantem detecção de toda invasão de arte ou palavra cortada**. O filtro de texto fora de balões é heurístico; pode deixar onomatopeias passar ou ignorar legendas. Por padrão não há super-resolução nem colorização, para evitar alterar o enquadramento/traço. Palavras ficam inteiras no servidor, evitando hifenização inglesa inadequada.

Se trocar o perfil/modelo do servidor mantendo o mesmo endereço, limpe o cache de tradução do aplicativo e prepare novamente os capítulos necessários. Páginas já baixadas não mudam de qualidade automaticamente.

## Colab revisado

Abra [Mangalate_Colab.ipynb](https://colab.research.google.com/github/delkrusty/Mangalate/blob/main/server/colab/Mangalate_Colab.ipynb). Selecione GPU se disponível e rode as células em ordem. Elas instalam o código de uma revisão fixa, param em erros, recebem um capítulo e exportam CBZ + revisão. No BYOK, use um Secret chamado `MANGALATE_PROVIDER_KEY`, ou o campo oculto solicitado; nunca escreva chave em uma célula pública.

A célula de preparação instala Python 3.13.12 em um ambiente separado usando uv. Não precisa trocar manualmente o Python do runtime Google ou instalar pacotes dentro do ambiente que mantém a interface do Colab; os comandos de tradução rodam no ambiente isolado.

Neste caminho você **não precisa da chave Mangalate**, porque o notebook não conecta o celular a um servidor. No Básico, não precisa de chave de IA; no BYOK, somente sua própria chave de API. A chave Mangalate é gerada pelo instalador Docker para a conexão do aplicativo.

Não há Cloudflare Tunnel, servidor público nem laço para manter sessão ativa. Os limites e restrições são do Google; o funcionamento real depende de GPU, runtime, dependências e downloads disponíveis, e uma revisão sintática não equivale a uma execução GPU no Colab ([FAQ](https://research.google.com/colaboratory/intl/pt-BR/faq.html)).

Para ler o CBZ, escolha a pasta de armazenamento do aplicativo e crie dentro dela:

```text
manga/
  Nome do mangá/
    Capitulo 01.cbz
```

Atualize a fonte Local no aplicativo. O CBZ já contém as páginas processadas; não precisa ligar 文A de novo. Confira os resultados antes de apagar os originais.

## Resolver problemas

- **Docker não encontrado:** abra Docker Desktop; confira `docker compose version`.
- **Chave recusada:** confira se colou a chave Mangalate, não a chave da IA; não copie espaços/linhas extras.
- **Conecta mas demora:** prepare os modelos com `check.py --warmup` e verifique RAM, disco e logs.
- **GPU não reconhecida:** veja `nvidia-smi`, driver e NVIDIA Container Toolkit. Comece em CPU se não souber.
- **BYOK HTTP 502:** confira endpoint, compatibilidade, modelo, chave, saldo e limites nos logs do seu servidor. Mensagens upstream não são devolvidas ao telefone porque podem conter dados privados.
- **Resultado bloqueado:** não relaxe as proteções globalmente só para aprovar uma página. Revise os originais e ajuste uma cópia do perfil com amostras reais.
- **Ler offline:** prepare os capítulos antes e espere a tradução finalizar; ou importe o CBZ revisado.
- **Parar:** `docker compose --profile cpu stop` ou `gpu stop`.
- **Atualizar:** faça backup das chaves e revise mudanças antes de `git pull`; modelos usam volumes persistentes.

## Estado de validação e licenças

As versões do upstream e do pydensecrf estão fixadas no Docker/Colab para evitar alterações silenciosas. Testes de gateway usam backend simulado e verificam autenticação, multipart, perfis, limites, erros, segurança de ZIP e sintaxe do notebook; CI também tenta construir e exercitar o motor CPU real. Não confunda isso com validação de GPU, de conta BYOK paga ou de todo capítulo real.

O motor Docker chama `MangaTranslator` diretamente em um serviço privado. Não usa o despachante HTTP/pickle experimental do upstream, nem exige que você descubra uma terceira chave interna. Somente o gateway autenticado pode ser publicado na rede; mantenha os serviços do motor sem portas públicas.

O adaptador `engine_compat.py` corrige a chamada do token de idioma NLLB, o código de coreano e o uso do cache; ele não ignora traduções vazias como se fossem sucesso. Essa adaptação do motor tem identificação GPL-3.0, preservando a [licença do upstream](https://raw.githubusercontent.com/zyddnys/manga-image-translator/d6de6ab62a7be6afc0d07a3184149cdefbcd32f2/LICENSE); não altera a licença do aplicativo Android.

Na detecção automática, o classificador NLLB considera os idiomas suportados pelo adaptador, evitando que diálogos curtos sejam classificados em um idioma sem mapeamento e pulados silenciosamente. O adaptador também normaliza geometrias OpenCV 4/5 na identificação de painéis e remove seus arquivos temporários, inclusive em falhas.

No BYOK, o adaptador aceita respostas sem estatística de tokens e rejeita conteúdo truncado ou traduções faltantes. Uma rejeição preserva a imagem original no lote e não substitui os balões por respostas vazias no app. Isso é uma proteção de integridade, não uma garantia de qualidade linguística.

As respostas BYOK têm teto de 4096 tokens por pedido e espera de até 180 segundos por trecho. O adaptador não reinicia automaticamente um pedido pago apenas porque demorou; a revisão linguística configurada no perfil ainda pode gerar novas chamadas. Consumo, preço e disponibilidade dependem do seu provedor.

O backend upstream é GPL-3.0 ([licença](https://raw.githubusercontent.com/zyddnys/manga-image-translator/d6de6ab62a7be6afc0d07a3184149cdefbcd32f2/LICENSE)); modelos e fontes têm licenças próprias. Preserve os avisos e revise permissões antes de distribuir um produto comercial. Use somente capítulos próprios/autorizados. “Premium/BYOK” significa infraestrutura/modelo do próprio usuário, não direito de uso irrestrito de qualquer modelo.
