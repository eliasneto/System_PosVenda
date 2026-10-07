# ADR-008 - Fila única do RPA EACE para RI, MIP (LOTE) e Validação MIP (NF)

## Status
`Aprovado` (decisões do usuário em 2026-09-28 e 2026-09-29). Emenda a
`ADR-005` (fila serializada do RPA EACE) — ponteiro registrado nela.

## Contexto
O portal EACE passou a ter 3 tipos de execução automática, todos com o
mesmo login de fornecedor:

1. **RI** — anexo de PDF+XML por INEP (FEAT-033, `LogRpaEace`, `ADR-005`).
2. **MIP (LOTE)** — anexo só do PDF da NF do município (FEAT-056, RN-108).
3. **Validação MIP (NF)** — leitura, só leitura, dos status dos cards do
   pedido do MIP (FEAT-055, RN-109).

Antes desta decisão, só o RI tinha fila (`processar_fila_rpa_eace`,
container `rpa_eace_worker`). A Validação nasceu (2026-09-28) com a ideia
de um container próprio (`mip_worker`), que nunca chegou ao servidor — a
primeira execução real pedida pelo botão ficou parada "Na fila".

Conferido no código em 2026-09-29: `LogRpaEace.ri` é obrigatório e a
lógica do RI (resolver OSP, avançar status do RI, `rpa_eace_concluida`)
assume que todo log tem um RI.

## Decisão
- **Uma fila e um worker só** (`processar_fila_rpa_eace` /
  `rpa_eace_worker`) para os 3 tipos — no máximo 1 execução do portal por
  vez em todo o sistema.
- **Log próprio por tipo**: `LogRpaEace` (RI, sem mudança),
  `LogRpaEaceMip` (MIP, ligado ao LOTE) e `ValidacaoNfMip` (Validação).
- **Ordem em cada passada:** o envio mais antigo entre RI e MIP
  (`enfileirado_em`); só com os 2 vazios, a próxima Validação MIP (NF).
  Envio de NF tem prioridade sobre leitura de status.
- **Reprocessamento do MIP** segue a RN-058, com a lista própria de
  motivos de regra de negócio (`MOTIVOS_REGRA_DE_NEGOCIO_MIP`); "envio não
  confirmado" nunca reprocessa sozinho.
- A execução automática da Validação (08h–19h) roda neste mesmo worker,
  desligada por padrão (`VALIDACAO_NF_MIP_AGENDADA`).
- "Projeto > Fila" mostra RI e MIP, marcados por tipo.

## Consequências positivas
- Nunca há 2 logins simultâneos no portal com a mesma conta.
- Nenhum container novo nem mudança no docker-compose.
- O modelo e as regras do RI não mudaram.

## Consequências negativas / riscos
- Uma Validação longa (1–2 min) atrasa um envio de NF que chegar logo
  depois; o inverso também (Validação espera os envios).
- A posição "Na fila" mostrada no card do RI conta só os itens do RI.
- 3 modelos de log parecidos (campos de fila repetidos).

## Alternativas consideradas
- **Mesmo log do RI (`LogRpaEace`) com campo Tipo e LOTE** — recusada pelo
  usuário: exigiria tornar o RI opcional no log e mexer no modelo, nas
  regras e nas telas do RI, que assumem sempre um RI.
- **Container próprio `mip_worker` para a Validação** — escolhida em
  2026-09-28 e substituída em 2026-09-29: dependia de mudança de DevOps
  que não aconteceu, e podia logar no portal ao mesmo tempo que o worker
  do RI/MIP.
- **Executar na hora (síncrono) pelo botão** — recusada em 2026-09-28: a
  tela ficaria esperando 1–2 min e podia estourar o tempo do navegador.

## Pendências
- Deploy da passagem da Validação para o `rpa_eace_worker` (código pronto
  em 2026-09-29, ainda não publicado).
- Usuário vai definir a partir de quando ligar a execução automática.
