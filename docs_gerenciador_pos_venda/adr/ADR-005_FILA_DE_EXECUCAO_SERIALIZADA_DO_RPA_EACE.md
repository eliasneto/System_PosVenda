# ADR-005 - Fila de execução serializada do RPA EACE, com reprocessamento automático de erro não mapeado

## Status
Aprovado e implementado pelo Dev em 2026-09-03 (lógica de fila,
reprocessamento e tela — ver item 6).

**Emenda (2026-09-03):** DevOps entregou o serviço `rpa_eace_worker` no
`docker-compose.yml`/`docker-compose.hml.yml` — processo consumidor
rodando de verdade em produção, validado processando 1 item real da fila
contra o portal. Pendência de infraestrutura resolvida — ver
"Pendências".

## Contexto
A Fase 2 da `FEAT-033` (entregue em 2026-09-03) colocou ao vivo, na tela
de detalhe do RI, um botão "Disparar RPA" por log de Nota Fiscal — hoje a
execução é **síncrona**: a requisição HTTP só responde quando o núcleo do
RPA (`apps/integracoes/eace/rpa.py`, Playwright/Chromium) termina.

Com a tela funcionando, várias pessoas podem clicar em "Disparar RPA" ao
mesmo tempo, para RIs diferentes. Isso é um problema porque:

- cada execução abre um navegador Chromium próprio — pesado, e sem limite
  hoje, várias execuções simultâneas podem esgotar memória/CPU do
  container;
- todas as execuções usam o mesmo login no mesmo portal externo
  (`eace.org.br`) — dois fluxos navegando ao mesmo tempo na mesma sessão/
  conta arriscam se atrapalhar (um clica em algo que o outro esperava
  estável) e não há garantia de como o portal (SPA Bubble.io) se comporta
  com abas/sessões concorrentes da mesma conta.

O usuário pediu, no mesmo pedido, que uma falha passageira (rede,
timeout de UI, ambiente) ganhe 1 nova chance automática sem precisar de
clique manual — mas deixou explícito que isso vale só para esse tipo de
falha, nunca para um erro que já é uma questão de dado/regra de negócio
(ex.: valor divergente, OSP inexistente) — repetir a mesma tentativa ali
não muda nada sem uma correção manual.

## Decisão
1. **Fila única, serializada, para todo o sistema** — no máximo 1
   execução do núcleo do RPA roda por vez, não importa quantos RIs/
   usuários disparem ao mesmo tempo (`RN-058`).
2. **FIFO, com reprocessamento indo para o final** — um log que falha
   com erro não mapeado não fura a frente da fila; entra de novo no
   final, como se fosse um disparo novo.
3. **Reprocessamento automático só para erro NÃO mapeado** (falha
   técnica/de ambiente, sem relação com o dado da NF ou regra de
   negócio) — 1 única tentativa extra. Erro **mapeado** (regra de
   negócio, RN-056/RN-057) vira "Erro" definitivo já na 1ª tentativa,
   sem reprocessar sozinho.
4. **Processo consumidor único**, mesmo padrão já usado pelo
   `email_scheduler` (`docker-compose.yml`): um container próprio, em
   loop, chamando um `management command` a cada passada, que pega o
   próximo item da fila e processa. Decisão de infraestrutura (novo
   serviço no Compose, imagem com Playwright/Chromium/pdfplumber) cabe
   ao DevOps.
5. **"Disparar RPA"/"Tentar novamente" deixam de executar na hora** —
   passam a só enfileirar o log; quem executa de fato é o processo
   consumidor. A tela mostra um estado "Na fila" enquanto isso.
6. **Atualização da tela por polling HTMX** (decidido pelo Dev na
   implementação, 2026-09-03) — a seção de logs consulta
   `hx-get="every 5s"` enquanto existir algum log "Na fila", e para
   sozinha quando não há mais nenhum. Resolve a pendência de UI deixada
   em aberto (ver "Pendências"), como opção mais simples e reversível
   (CLAUDE.md §9) — sem introduzir WebSocket/SSE nem dependência nova.

## Consequências positivas
- Elimina o risco de múltiplas instâncias do Chromium/login simultâneas
  no mesmo portal externo.
- Falha passageira (rede, timeout) se resolve sozinha na maioria dos
  casos, sem exigir que alguém perceba o erro e clique de novo.
- Erro de regra de negócio nunca "mascara" com um reprocessamento inútil
  — o usuário vê o erro definitivo na hora e sabe que precisa agir
  (trocar arquivo, etc.), não esperar um retry que não vai adiantar.

## Consequências negativas / riscos
- **Deixa de ser síncrono** — quem clica em "Disparar RPA" não sabe mais
  na hora se deu certo; a Fase 2 (execução síncrona) previa resposta
  imediata. Mitigado pelo polling HTMX (item 6 da Decisão): a tela
  atualiza sozinha em até 5s depois do processo consumidor terminar.
- Introduz um novo processo/serviço em produção (mesma categoria de
  complexidade operacional do `email_scheduler`) — mais uma coisa para o
  DevOps monitorar/reiniciar se cair.
- Fila de 1 processo só é um gargalo deliberado: se muitas Notas Fiscais
  precisarem ser anexadas ao mesmo tempo (ex.: fim de mês), a fila
  cresce e demora — aceito conscientemente, já que o próprio portal
  externo é o recurso realmente limitante (não dá pra paralelizar contra
  ele com segurança, ver "Contexto").

## Alternativas consideradas
- **Sem fila, limitar por um lock simples (ex.: 1 lock global no banco)
  e rejeitar disparo se já tiver um rodando** — descartada: o usuário
  pediu explicitamente que o disparo entre na fila e espere a vez, não
  que seja rejeitado/precise ser clicado de novo manualmente.
- **Paralelizar com um número pequeno de execuções simultâneas (ex.: 2)**
  — não considerada a sério: o problema de concorrência é principalmente
  no portal externo (mesma conta/sessão), não só no servidor — mais de 1
  execução ao mesmo tempo mantém o risco descrito no Contexto.

## Pendências
- ~~Implementação da lógica de fila/reprocessamento~~ — feita em
  2026-09-03 pelo Dev: `LogRpaEace.tentativas`/`enfileirado_em`
  (migração `0029`), `MOTIVOS_REGRA_DE_NEGOCIO`
  (`apps/integracoes/eace/rpa.py`), consumidor
  `processar_proximo_da_fila_rpa_eace` (`apps/ri/services.py`,
  `select_for_update(skip_locked=True)`), comando de terminal
  `processar_fila_rpa_eace`; 15 testes novos, 484 no total, sem
  regressão.
- ~~Desenho de como a tela reflete o estado "Na fila"/conclusão sem
  reload manual~~ — feito em 2026-09-03: polling HTMX a cada 5s (item 6
  da Decisão), validado visualmente contra o HTML real.
- ~~Novo serviço no `docker-compose.yml` (processo consumidor) e imagem
  com as mesmas dependências já pendentes do `ADR-004`
  (Playwright/Chromium/pdfplumber)~~ — feito pelo DevOps em 2026-09-03:
  serviço `rpa_eace_worker`, mesmo padrão do `email_scheduler`; build e
  execução real validados, processando 1 item real da fila contra o
  portal em produção.
- Mesma pendência já registrada em `ADR-004`: falta 1 upload real (Fase
  1) para fechar a validação de ponta a ponta antes de tudo isso entrar
  em produção de verdade.
