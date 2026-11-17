# Fontes do letreiramento

Todas são SIL Open Font License 1.1 (licença ao lado, `OFL*.txt`), baixadas do repositório oficial do Google Fonts (`github.com/google/fonts`, pasta `ofl/`), menos a Permanent Marker, que é Apache 2.0 (pasta `apache/`, licença em `LICENSE-PermanentMarker.txt`). Todas têm os acentos do português (ã õ á é í ó ú â ê ô à ç, maiúsculas e minúsculas).

| Uso | Fonte | Arquivos | Licença |
|---|---|---|---|
| Fala (padrão) | Comic Neue | `ComicNeue-Bold.ttf`, `ComicNeue-Regular.ttf` | `OFL.txt` |
| Narração, pensamento, voz baixa | Comic Neue itálica | `ComicNeue-Italic.ttf`, `ComicNeue-BoldItalic.ttf` | `OFL.txt` |
| Grito, impacto, título de quadrinho; hoje: adesivo inclinado e título em curva | Bangers | `Bangers-Regular.ttf` | `OFL-Bangers.txt` |
| Grito condensado (coluna estreita, cartaz); hoje: palavras empilhadas sobre a arte e fala em negrito com halo | Anton | `Anton-Regular.ttf` | `OFL-Anton.txt` |
| Grito rabiscado à mão, letra embaixo de letra; hoje: grito empilhado que o detector achou por uma letra | Permanent Marker | `PermanentMarker-Regular.ttf` | `LICENSE-PermanentMarker.txt` (Apache 2.0) |
| Onomatopeia pesada, letreiro | Bowlby One SC, Titan One, Bungee | `BowlbyOneSC-Regular.ttf`, `TitanOne-Regular.ttf`, `Bungee-Regular.ttf` | `OFL-BowlbyOneSC.txt`, `OFL-TitanOne.txt`, `OFL-Bungee.txt` |
| Título arredondado, placa | Lilita One | `LilitaOne-Regular.ttf` | `OFL-LilitaOne.txt` |
| Terror, voz sinistra | Creepster | `Creepster-Regular.ttf` | `OFL-Creepster.txt` |
| Bilhete, nota escrita à mão, lousa | Patrick Hand, Kalam, Gochi Hand | `PatrickHand-Regular.ttf`, `Kalam-Regular.ttf`, `Kalam-Bold.ttf`, `GochiHand-Regular.ttf` | `OFL-PatrickHand.txt`, `OFL-Kalam.txt`, `OFL-GochiHand.txt` |
| Janela de sistema, rótulo estreito (manhwa) | Pathway Gothic One | `PathwayGothicOne-Regular.ttf` | `OFL-PathwayGothicOne.txt` |
| Narração formal, carta, livro | PT Serif | `PTSerif-Regular.ttf`, `PTSerif-Italic.ttf` | `OFL-PTSerif.txt` |

As fontes vão para a imagem do servidor pela pasta inteira (`COPY fonts /mangalate/fonts` no `Dockerfile.worker`).
