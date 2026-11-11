# ADR-009 - Robôs do RPA EACE em paralelo, cadastrados no admin

## Status
`Aprovado` (decisão do usuário em 2026-11-10). Emenda a `ADR-005` e a
`ADR-008` no ponto "no máximo 1 execução do portal por vez" e a RN-058 no
mesmo ponto - o restante delas (FIFO, reprocessamento, fila única RI + MIP
+ Validação) continua valendo.

## Contexto
Com 1 execução por vez, a fila do RPA EACE (RI e MIP) fica lenta quando
muitos envios chegam juntos. O usuário pediu que vários robôs rodem ao
mesmo tempo, consumindo a mesma fila na ordem de chegada (o 1º e o 2º
itens rodam juntos), cada um com o próprio login no portal (para poder
criar N usuários, se o portal permitir), num navegador próprio, sem um
atrapalhar o outro, e com 1 robô por INEP.

## Decisão
- **Cadastro no admin** - "Robôs do RPA EACE" (`apps.core.models.
  RoboRpaEace`): nome, usuário, senha e ativo. Cada robô ativo = 1
  processo. Sem nenhum ativo, roda 1 robô com o login do `.env`
  (comportamento anterior, deploy sem cadastro não muda nada).
- **Supervisor** - o container `rpa_eace_worker` roda
  `supervisionar_robos_rpa_eace`, que mantém 1 processo
  `processar_fila_rpa_eace --robo <id>` por robô ativo, em loop (1 passada
  por processo: cada execução abre e fecha o próprio Chromium; o login do
  robô vale só dentro do processo dele).
- **Reserva sob trava** - o próximo item é escolhido e marcado
  "Processando" dentro de uma transação que trava a linha única
  `TravaFilaRpaEace` (`apps.ri.fila_rpa_eace.reservar_proximo_envio`);
  a execução roda fora da trava, em paralelo.
- **1 robô por INEP** - item cujo INEP (RI) ou INEPs/LOTE (MIP) já está
  "Processando" em outro robô é pulado; o robô pega o próximo livre.
- **Recuperação por robô** - o log grava o robô (`robo`); cada robô só
  recupera o próprio envio preso em "Processando", e o supervisor recupera
  os de robôs sem processo rodando (inclusive tudo, ao iniciar).
- **Teto de robôs** - `RPA_EACE_MAX_ROBOS` (padrão 3, servidor com 12 GB
  desde 2026-11-11): só os N primeiros robôs ativos (ordem de cadastro)
  rodam ao mesmo tempo; cada um chega a ~2,5 GB de RAM no pico.
- Leitura EACE do BDO e Validação MIP (NF) seguem como antes (só quando
  não há envio livre), com reserva condicional para 2 robôs não pegarem
  a mesma.

## Consequências positivas
- Vazão proporcional ao número de robôs ativos, ajustável no admin sem
  deploy (robô novo começa em ~1 s; desativado termina o item atual e para).
- Nenhuma dependência nova (sem Celery/Redis).

## Consequências negativas / riscos
- **Portal EACE com sessões simultâneas** - não se sabe se o portal
  aceita 2 logins ao mesmo tempo da mesma conta; por isso cada robô tem o
  próprio usuário. Usuário confirmou (2026-11-11) que o portal aceita o
  mesmo login em várias sessões ao mesmo tempo - os robôs podem usar a
  mesma conta.
- Cada robô ativo é um Chromium a mais aberto ao mesmo tempo
  (memória/CPU do servidor).
- A senha do robô fica no banco (não sai na tela do admin, que só aceita
  troca).
- Robô que já trabalhou não pode ser excluído (só desativado) - o log
  aponta para ele.
- A posição "Na fila" mostrada na tela continua contando 1 por vez.

## Alternativas consideradas
- **1 container por robô no docker-compose** - recusada: mudar o número
  de robôs exigiria deploy; o pedido foi configurar no admin.
- **1 robô fixo para RI e outro para MIP** - recusada pelo usuário: os
  robôs devem seguir a fila, sem separar por tipo.
