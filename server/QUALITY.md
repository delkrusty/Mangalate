# Mangalate: protocolo para buscar acabamento de scan

Este é um protocolo de aceitação e evolução, não um certificado de qualidade já atingido. GPU mais forte e API paga não tornam automaticamente o resultado impecável; cada etapa e um conjunto real de páginas precisam ser avaliados.

## Produto e responsabilidades

- **Básico:** tradução no celular ou servidor pessoal com modelos locais. Sem cobrança Mangalate. Respeitar a licença não comercial e as limitações do NLLB ([model card](https://huggingface.co/facebook/nllb-200-distilled-600M)).
- **BYOK avançado:** servidor e API do próprio usuário, custos diretos aos fornecedores, sem comissão Mangalate. Não é uma assinatura gerenciada ou infraestrutura fornecida por nós.
- **Edição final:** só após revisão visual e linguística. O pacote automático é uma versão para revisar; não deve ser anunciado como scan humano final.

## O que está implementado

- **Detecção/OCR:** perfil Básico default + 48px; BYOK CTD + 48px. Texto sobre arte filtrado por heurística, desligado por padrão. Não há garantia de identificar toda onomatopeia ou legenda.
- **Tradução:** NLLB local ou Chat Completions compatível. Lote BYOK injeta contexto das duas páginas anteriores e glossário opcional; leitura ao vivo usa contexto da página.
- **Limpeza:** LaMa MPE ou LaMa Large, sem colorização/super-resolução. A imagem deve manter dimensões. Alteração global excessiva bloqueia o resultado; isso não substitui uma máscara supervisionada por balão.
- **Composição:** fonte e direção horizontais para PT-BR, sem hifenização inglesa no servidor, margens/encaixe do renderer upstream. No celular permanece o renderer/hifenizador aprovados da 0.5.0.
- **Revisão:** originais, resultados, inventário de texto, CBZ ordenado e relatório Markdown/JSON. Falhas preservam originais. Depois de três falhas seguidas, o lote evita continuar chamando a API.
- **Segurança/custo:** servidor fechado por chave própria, API paga só no worker, execução serial, corpo e imagens limitados. Limites financeiros reais devem ser configurados pelo usuário no provedor.

## Conjunto de testes antes de recomendar um perfil como scan

Monte pelo menos 20 páginas próprias/autorizadas, sem escolhê-las só por serem fáceis. Inclua japonês vertical, inglês, letras pequenas, balões escuros/coloridos, textura, diálogo sem balão, texto perto de rostos, quadros múltiplos, nomes recorrentes, capítulo longo e onomatopeias grandes. Inclua os bugs já observados: máscara enorme, metade da tela apagada, arte embranquecida, texto sobre desenho e palavras cortadas.

Compare original e resultado lado a lado. Para cada página, registre:

| Critério | Alvo de aceitação, não medição já realizada |
|---|---|
| Enquadramento | Mesmas dimensões e nenhum recorte/estiramento |
| Arte | Zero dano visível fora das regiões autorizadas |
| Balões | Contorno preservado, limpeza uniforme, sem invasão do painel |
| Texto | Sem omissões, duplicatas, fala trocada ou invenção |
| Português | Sentido, registro, pontuação e voz dos personagens naturais |
| Glossário | Nomes e termos aprovados consistentes em todo capítulo |
| Composição | Nada fora do balão; tamanho legível, sem cortes indevidos |
| Ordem | Painéis e falas na ordem correta |
| Efeitos | Onomatopeias preservadas quando a opção não está habilitada |
| Revisão | Todas as páginas sinalizadas realmente conferidas |

Se um modelo ganha em fluência mas perde nomes/falas, ele não é “melhor” para esse perfil. Compare com o mesmo capítulo e mesma máscara, registrando latência, custos no painel do provedor e taxa de retrabalho. Não estimar qualidade pelo preço da GPU.

## Próximas etapas de engenharia

O nível scan consistente ainda exige segmentação supervisionada dos balões, máscaras e overlays auditáveis por região, editor para correção de OCR/tradução, estilos por personagem, memória de capítulo mais ampla e tipografia em português calibrada com casos reais. DirectML/OpenVINO exigem exportação e validação dos modelos por etapa; ROCm é experimental neste pacote e precisa de hardware real.

Colab é um caminho interativo de lote, não uma promessa de servidor gratuito estável. Respeite as políticas e limites do runtime ([FAQ Colab](https://research.google.com/colaboratory/intl/pt-BR/faq.html)).
