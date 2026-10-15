# Ajuda do Mangalate

A ajuda completa também está no app, em **Mais › Ajuda do Mangalate**, com busca e funcionando offline.

## Usar

- **Traduzir:** abra um capítulo, toque no centro da página e depois em **文A**. Escolha os idiomas e toque em Traduzir.
- **Ver o original:** toque em 文A de novo.
- **Ajustes:** Mais › Tradução (Mangalate).
- **Modo No celular:** na primeira vez, toque em Preparar idiomas com internet. Depois funciona offline.
- **Modo Servidor:** precisa do servidor rodando no seu PC. Veja o [manual do servidor](server/README.md).

## Conectar o app ao servidor

1. No PC, rode `py setup.py` dentro da pasta `server`. Ele mostra a **Chave Mangalate** e o endereço.
2. No app: Mais › Tradução (Mangalate) › **Servidor**.
3. Endereço: `http://IP-DO-PC:5003`. Para ver o IP, rode `ipconfig` no Windows e procure o IPv4, por exemplo `192.168.0.15`.
4. Chave Mangalate: o conteúdo de `server/secrets/mangalate_key.txt`.
5. Toque em **Testar conexão**.

São duas chaves diferentes. A **Chave Mangalate** é a senha entre o celular e o seu PC e vai no app. A **chave da IA** (Groq, Gemini…) fica só no PC e nunca vai no celular.

## Ler offline

Ligue **Traduzir capítulos ao baixar** antes de baixar e espere a tradução terminar. Para ver as páginas traduzidas, a tradução precisa estar ligada no leitor. Se você mudar o idioma, o modo ou o servidor, os capítulos precisam ser traduzidos de novo.

## Problemas comuns

- **Chave inválida (HTTP 401):** cole o conteúdo inteiro de `mangalate_key.txt`, sem espaços. Não use a chave da IA.
- **Servidor iniciando (HTTP 503):** espere. Na primeira página o servidor ainda pode estar baixando modelos. No PC, veja `docker compose logs --tail=80`.
- **Servidor ocupado (HTTP 429):** espere a página atual terminar.
- **Erro do servidor (HTTP 502):** se a mensagem disser que o limite grátis de todas as IAs acabou, espere ou acrescente outra IA rodando `py setup.py`. Nos outros casos, veja os logs no PC.
- **Celular não conecta:** use o IP do PC, não `localhost`. Os dois precisam estar no mesmo Wi-Fi. Permita o Docker no firewall só em redes privadas.
- **Sobrou texto em inglês:** pode ser texto sobre o desenho, que o servidor deixa no original de propósito. Se for dentro de um balão, mande um print do original e do resultado.
- **Texto pequeno:** falas longas em balões pequenos precisam de letra menor. Deixe o ajuste de fonte em zero e use zoom.
- **Página não aparece traduzida offline:** confira se a tradução terminou e se você está com os mesmos ajustes usados ao baixar.

## Atualizar

- **App:** baixe a versão nova em [Releases](https://github.com/delkrusty/Mangalate/releases/latest) e instale por cima, sem desinstalar.
- **Servidor:** na pasta `server`, rode `git pull` e depois `py rebuild.py`.

## Relatar um problema

Abra uma [issue](https://github.com/delkrusty/Mangalate/issues) e informe a versão, o modo, os idiomas e os passos para reproduzir. Prints do original e do resultado ajudam muito. **Nunca** mande chaves (Mangalate ou de IA) em prints, logs ou mensagens.
