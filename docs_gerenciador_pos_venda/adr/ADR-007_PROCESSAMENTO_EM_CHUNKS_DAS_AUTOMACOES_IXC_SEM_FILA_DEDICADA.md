# ADR-007 - Processamento em chunks das Automações IXC, sem fila dedicada

## Status
Aprovado e implementado pelo Dev em 2026-09-23.

## Contexto
`FEAT-053` (Automações IXC) precisa rodar uma automação linha a linha
contra a API do IXC (criação de Login/Endereço via `radusuarios`,
abertura de Atendimento via `su_ticket`), com barra de progresso real e
um botão Stop que interrompe o processamento — mesma necessidade que já
levou à fila serializada do RPA EACE (`ADR-005`). O projeto, porém, não
tem Celery nem qualquer worker assíncrono genérico; o único precedente
(`ADR-005`) resolve isso com um processo consumidor único, rodando num
container Docker dedicado (`rpa_eace_worker`), consumindo uma fila no
banco.

Diferente do RPA EACE (que abre um navegador Chromium pesado e depende
de uma sessão só no portal externo, exigindo serialização estrita),
cada linha das Automações IXC é só 1 chamada HTTP curta à API do IXC —
não existe o mesmo problema de concorrência que justificou a fila do
RPA EACE.

Perguntado diretamente ao usuário (CLAUDE.md §9 — decisão de
arquitetura) qual mecanismo usar, já que criar um novo serviço Docker é
decisão de infraestrutura (escopo do DevOps, não do Dev): o usuário
escolheu processar em chunks via requisições HTTP repetidas, sem
infraestrutura nova.

## Decisão
1. **Sem fila nem worker dedicado** — cada `ExecucaoAutomacaoIxc`
   guarda 1 `LinhaExecucaoIxc` por linha da planilha (`pendente`/
   `sucesso`/`erro`).
2. **Processamento em chunks, dentro da própria requisição HTTP** —
   `apps.ixc.services.processar_proximo_chunk` processa até 5 linhas
   `pendente` por chamada, chamando a API do IXC linha a linha.
3. **Encadeamento via HTMX** — a própria linha do grid carrega
   `hx-trigger="load"` enquanto `status == "processando"`; cada
   resposta troca a linha por uma nova cópia de si mesma, que dispara o
   próximo chunk sozinha, até não sobrar linha `pendente` (mesmo
   princípio do polling do RPA EACE, `ADR-005`, mas sem timer fixo —
   encadeado o mais rápido possível, chunk após chunk, em vez de
   esperar um intervalo fixo).
4. **Stop é cooperativo, não instantâneo** — marca
   `cancelar_solicitado=True`; o próximo chunk (não o atual, já em
   andamento) confere essa marcação antes de processar mais linhas e
   para ali, marcando a execução como `Cancelado`.

## Consequências positivas
- Nenhuma infraestrutura nova (sem serviço Docker adicional, sem
  Celery/Redis) — 100% dentro do escopo do Dev, entregue e testado na
  mesma sessão.
- Progresso real (não ilustrativo) e Stop funcional, com a mesma
  simplicidade de manutenção do resto do projeto.
- Reabrir a tela sozinho já resolve a maioria dos imprevistos — ver
  consequência negativa abaixo.

## Consequências negativas / riscos
- **Só avança enquanto existir alguém com a tela aberta** — o
  encadeamento (`hx-trigger=load`) depende de uma página carregada; se
  todo mundo fechar a aba no meio de uma execução `Processando`, ela
  fica parada até alguém abrir a tela de novo. Isso destrava sozinho,
  sem botão nem ação manual — o HTML sempre volta com `hx-trigger=load`
  enquanto o status for `Processando`, então só precisa de alguém
  olhar a tela outra vez.
- Sem paralelismo entre linhas da mesma execução — um lote grande
  demora proporcionalmente ao número de linhas × latência da API do
  IXC; aceito conscientemente, mesmo raciocínio da RN-058/`ADR-005` (o
  gargalo real é o sistema externo, não o servidor).

## Alternativas consideradas
- **Fila + worker em container dedicado, mesmo padrão do RPA EACE
  (`ADR-005`)** — mais robusto para lotes grandes e resiliente a
  ninguém com a tela aberta, mas exige um novo serviço de
  infraestrutura; descartada por ora porque o volume esperado das
  planilhas não justifica a complexidade operacional extra, e o
  usuário priorizou entregar sem depender do DevOps.
- **Processamento síncrono simples (tudo numa única requisição)** —
  mais simples ainda, mas sem barra de progresso real nem Stop de
  verdade (não dá para interromper no meio de uma requisição HTTP
  única); descartada porque o pedido do usuário incluía Start/Stop e
  progresso explicitamente.

## Pendências
- Sem teste real contra a API de produção do IXC (só com mocks nos
  testes automatizados) — falta 1 execução real controlada, com poucas
  linhas, antes do primeiro uso em produção de verdade (mesma pendência
  de "fechar a validação de ponta a ponta" já registrada em
  `ADR-004`/`ADR-005` para o RPA EACE).
- Se o volume real das planilhas crescer muito (lotes grandes,
  recorrentes), reconsiderar a alternativa de fila + worker acima —
  não é uma decisão fechada para sempre, só a mais simples para o
  volume conhecido hoje.
