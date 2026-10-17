# Mangalate

Leitor de mangá para Android baseado no Mihon que traduz as páginas e escreve a tradução dentro dos balões. O dono do projeto é o Lucas; fale com ele em português do Brasil. Código, identificadores e comentários seguem o estilo do arquivo (em geral, inglês); CHANGELOG, README, ajuda e mensagens de commit são em português.

## Arquitetura

**App Android** (Kotlin, fork do Mihon). O código do Mangalate fica em `app/src/main/java/app/mangalate/`; o resto do repositório é Mihon e deve mudar o mínimo possível, para facilitar atualizações.
- `local/`: modo No celular, offline. OCR e tradução do ML Kit (`OnDeviceOcr`, `OnDeviceTranslate`), balões (`BubbleSegmenter`, `BubbleGeometry`), quebra de texto e hifenização em português (`BubbleTextWrapper`, `PortugueseHyphenator`, dicionário em `app/src/main/assets/lettering/`) e desenho da página (`PageRenderer`).
- `translate/`: cliente do servidor, pré-tradução, tradução ao baixar e ajustes.
- `ui/`: telas de ajuda, configuração rápida e estado no leitor.
- Testes: `app/src/test/java/app/mangalate/local/`.

**Servidor** (`server/`, Python e Docker), que roda no PC do Lucas:
- `gateway.py` recebe o app na porta 5003 e confere a Chave Mangalate; `worker.py` e `core.py` rodam o motor.
- O motor é o manga-image-translator (GPL-3.0), numa versão fixa, rodando como serviço separado. As correções do Mangalate entram por fora:
  - `engine_compat.py` (GPL-3.0): ganchos no motor, como detecção, reparo de linhas, releitura do OCR, junção de blocos e chamada do letreiramento.
  - `quality.py`: separa balão de arte pelo fundo, corrige letras trocadas pelo OCR (lista de palavras em `words/`), descarta duplicatas, separa colunas e confere negação e gênero.
  - `lettering.py`: encaixa o texto no formato do balão, com a fonte em `fonts/`.
  - `providers.py`: IAs BYOK com rodízio e pausas por limite.
  - `memory.py`: glossário e contexto por obra.
  - `seams.py`: balões cortados entre fatias de webtoon.
  - `speed.py`: limpeza antecipada e preenchimento liso.
- `colab/batch.py` vira `/mangalate/batch.py` na imagem e traduz um capítulo inteiro, com relatório de revisão.
- `profiles/` guarda as configurações do motor e as instruções da IA (`scan-prompt.yaml`).
- Testes: `server/tests/` (unittest, sem Docker). `byok_live.py` e `byok_runtime.py` não são testes de unidade.
- O pipeline passo a passo está em `server/QUALITY.md`; instalação e lote, em `server/README.md`; IAs, em `server/BYOK.md`.

## Prioridades de qualidade

Em conflito, a de cima vence. Uma mudança só está pronta quando melhora as páginas que a motivaram sem piorar as outras. Compilar, passar nos testes ou receber HTTP 200 não basta.

1. **Preservar a arte.** Nada é apagado fora dos balões. Texto sobre o desenho fica no original e a página é marcada para revisão. Uma página que falha sai como o original, nunca em branco.
2. **Limpar o balão direito.** Todo o texto original sai e o contorno fica intacto.
3. **Não perder fala.** Nenhuma fala fica faltando, duplicada, trocada de lugar ou em inglês dentro de um balão.
4. **Português natural.** O sentido certo (negação e gênero incluídos), com nomes e termos iguais em toda a obra e o tom do personagem em pt-BR, não uma tradução literal.
5. **Bom letreiramento.** O texto fica dentro do balão, legível, sem palavra cortada, no formato do balão e com tamanho próximo ao original.
6. **Robustez e velocidade.** Vêm por último, sem sacrificar os itens acima.

## Comandos

Testes do servidor, rápidos e sem Docker (os mesmos do CI):
```bash
pip install -r server/requirements-gateway.txt numpy opencv-python-headless   # uma vez
python -m unittest discover -s server/tests -v
python -m unittest discover -s server/tests -p test_quality.py   # um arquivo
```

App Android (JDK 21 e Android SDK):
```bash
./gradlew :app:assembleRelease -Pdist=local
./gradlew :app:testDebugUnitTest --tests 'app.mangalate.local.*'
./gradlew spotlessCheck
```

Servidor real no PC do Lucas (Windows, PowerShell, dentro de `server/`):
```powershell
py rebuild.py        # depois de trocar de commit; tem que terminar com "Servidor atualizado e rodando a versão nova."
py check.py --warmup # uma página de teste em review/teste-traduzido.png
docker compose logs --tail=80
```
Não use `docker compose up --build`, que pode falhar em silêncio e manter a versão antiga.

Rodada de teste com páginas reais (no PC, em `server/`):
```powershell
docker compose --profile cpu run --rm -v "${PWD}:/work" translator-cpu /mangalate/batch.py `
  --input "/work/<capitulo>.cbz" --pages 5-10 --work "<obra>" `
  --output "/work/teste-curto/<rodada>/<trecho>" --profile byok --speed fast --diagnostics `
  *> "teste-curto\<rodada>\<trecho>.log"
```
Com placa NVIDIA, use `--profile gpu run ... translator-gpu` e acrescente `--gpu`. Cada trecho gera `review.json`, `revisao.md`, `originals/`, `translated/` e, com `--diagnostics`, `diagnostico/NNNN/` (`1-original`, `2-mascara-detector`, `3-regioes`, `4-mascara-final`, `5-limpa`, `regioes.json`). Os capítulos de teste ficam em `server/teste/` e as saídas em `server/teste-curto/`, só no PC.

CI: `.github/workflows/server.yml` roda em push para `melhoria/**`, `candidate/**` e `teste/**` (testes de unidade, build da imagem de CPU e um lote real com página sintética). `build.yml` compila o APK e publica a release na `main`.

## Regras permanentes

- **Nada específico de uma obra.** O motor tem que servir para qualquer mangá, manhwa ou webtoon. Não crie regra, constante, exceção ou exemplo de instrução da IA que dependa de nome de obra, personagem, capítulo, página ou de uma fala conhecida. Os exemplos da IA usam nomes neutros. Um teste pode citar de onde veio o caso num comentário, mas reproduz o mecanismo com imagem sintética e geometria genérica.
- **Segredos.** Nunca leia, imprima, copie nem faça commit de `server/secrets/` (Chave Mangalate e chaves das IAs), keystore ou `local.properties`. Logs e diagnósticos mostram no máximo o nome do provedor e o tipo do erro, nunca a chave nem o corpo da resposta.
- **Páginas protegidas.** Capítulos e páginas de teste não entram no repositório, nem em testes, commits ou prints públicos. `server/teste/` e `server/teste-curto/` estão no `server/.gitignore`, mas mesmo assim adicione arquivos ao git pelo nome, nunca com `git add -A` ou `git add .`.
- **Git.** Trabalhe numa branch `melhoria/<assunto>` criada a partir da `main` ou na branch indicada pelo Lucas, nunca direto na `main`. Commit, push, PR e merge só quando ele pedir. Nunca use force push nem reescreva histórico publicado. Um assunto por commit, com a entrada correspondente no CHANGELOG em "Em teste".
- **Mudanças pequenas e reversíveis.** Um problema por vez, medido antes e depois. Para mexer no motor (detecção, OCR, balão ou arte, limpeza, tradução, letreiramento), siga a skill `evoluir-motor`. Antes de propor o commit, peça a revisão do subagente `revisor-motor`.
- **Licenças.** `engine_compat.py` é GPL-3.0, como o motor. O app é Apache 2.0: não copie código do motor para o app.
- **Cota das IAs.** As rodadas gastam a cota grátis diária (Groq, Gemini e outras). Prefira trechos curtos com `--pages`. Rodar um capítulo inteiro só com motivo, e nunca para "ver se passa".
- **Onde roda o quê.** Os testes de unidade rodam em qualquer lugar. O Docker com páginas reais roda no PC do Lucas. Uma sessão na nuvem pede a rodada no PC e lê os resultados de lá, sem inventar números.
