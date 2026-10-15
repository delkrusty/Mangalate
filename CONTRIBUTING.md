# Contribuir com o Mangalate

Problemas e sugestões: abra uma [issue](https://github.com/delkrusty/Mangalate/issues/new/choose). Pull requests são bem-vindos.

## Onde fica cada coisa

- **App Android:** é o [Mihon](https://github.com/mihonapp/mihon), com a tradução em `app/src/main/java/app/mangalate/`. Precisa de JDK 21 e Android SDK; para compilar: `./gradlew :app:assembleRelease -Pdist=local`.
- **Servidor:** `server/` (Python e Docker). Testes: `python -m unittest discover server/tests`. Leia o [QUALITY.md](server/QUALITY.md) antes de mexer na tradução ou na limpeza.

## Regras

- Mudanças de tradução ou limpeza precisam de páginas de teste com prints de antes/depois. Use só páginas próprias, autorizadas ou sintéticas, e não as coloque no repositório.
- Nada de chaves, tokens ou URLs privadas em código, testes, commits ou prints.
- Problemas do leitor que também acontecem no Mihon devem ser relatados [no Mihon](https://github.com/mihonapp/mihon).
- O Mangalate não fornece fontes de conteúdo nem extensões.
