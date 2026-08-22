# Regras de Negócio — Gerenciador Pós-Venda (Faturamento EACE por INEP)
_Última atualização: 2026-08-20_

## Ciclo de Vida do RI

### RN-001 — Ciclo de vida (status) do RI
**Descrição:** Todo RI nasce com o status "Implantação EACE" e percorre uma
sequência de 8 status até "Faturamento Concluído" — 7 na linha principal e 1
desvio de correção ("Correção MEGA") — com transições manuais (feitas pelo
usuário) e automáticas (disparadas pelo sistema).

**Contexto:** Levantado a partir do fluxo operacional real do pós-venda, para
dar visibilidade de em que ponto do faturamento cada INEP está.

**Critérios:**
| # | Status | Quem troca | Gatilho |
|---|---|---|---|
| 1 | Implantação EACE | — | status inicial de todo RI |
| 2 | Andamento | Usuário | chamado do IXC chega; usuário digita no sistema os dados do chamado (lado IXC) |
| 3 | Envio de Email para faturamento | Usuário | usuário confirma que todos os dados do chamado estão no sistema |
| 4 | Aguardando financeiro | Sistema | e-mail ao financeiro é efetivamente enviado |
| 5 | Aguardando Anexo portal EACE | Sistema | resposta do financeiro (NF + XML) entra na caixa de entrada |
| 6 | Aguardando validação EACE | Usuário | usuário concluiu o anexo do PDF/XML no portal da EACE |
| 7 | Faturamento Concluído | Usuário | cliente EACE validou a instalação |
| 8 | Correção MEGA | Usuário (Analista ou Administrador) | usuário identifica, durante o status "Andamento", divergência de quantidade/valor (RN-003/RF-04) entre o lado IXC e o relatório da EACE, e marca que os dados voltaram para a MEGA corrigir |

Ao entrar no status 3 ("Envio de Email para faturamento"):
- o sistema destaca em amarelo os campos digitados do chamado IXC que
  divergem do KIT declarado (ver RN-002);
- libera um botão que abre um formulário para o usuário digitar os dados a
  enviar ao financeiro; ao salvar, habilita o botão "Enviar e-mail";
- ao clicar em enviar, abre a tela de e-mail com um PDF (gerado com os
  dados) já anexado e os mesmos dados no corpo do e-mail.

**Status 8 — Correção MEGA (atualização 2026-08-21):** desvio manual, não
sequencial, ligado só ao status 2 ("Andamento"):
- **Entrada (2→8):** só a partir de "Andamento", só manual, só quando há
  divergência de quantidade/valor (RN-003/RF-04) aberta entre o lado IXC e o
  relatório EACE — o usuário marca o RI como "Correção MEGA" para deixar
  visível no grid que os dados do lado IXC voltaram para a MEGA corrigir.
- **Permissão:** Analista e Administrador — mesma regra do CRUD comum de
  INEP (ITEM 13 de `requisitos.md`); marcar "Correção MEGA" não é exclusão.
- **Retorno (8→2):** também manual — depois de corrigir os dados do lado
  IXC, o usuário troca o status de volta para "Andamento" por conta própria;
  não há gatilho automático de saída. Ao voltar para "Andamento", o
  confronto RN-003/RF-04 é refeito do zero, como uma primeira tentativa.
- Não existe transição direta de "Correção MEGA" para nenhum outro status
  além de "Andamento" (2).

**Exceções:** A transição do status 2 para o status 3 é bloqueada enquanto
houver divergência de quantidade/valor entre o lado IXC e o relatório da
EACE (RN-003 / RF-04) em aberto — "Correção MEGA" (8) é a forma visível de
sinalizar esse bloqueio, não uma forma de contorná-lo: enquanto o RI estiver
em "Correção MEGA" ou de volta em "Andamento" com a divergência ainda aberta,
a transição para o status 3 continua bloqueada. A divergência de KIT
(amarelo, RN-002) é só alerta e não bloqueia nenhuma transição.

**Impacto técnico:** campo de status do RI com os 8 valores fixos acima (7 da
sequência principal + "Correção MEGA"); guarda (guard) impedindo a transição
2→3 com divergência de quantidade/valor aberta; transições manuais 2→8 e 8→2
sem gatilho automático em nenhum dos dois sentidos; duas transições
automáticas disparadas por evento de sistema (envio de e-mail confirmado;
leitura de resposta na caixa de entrada do financeiro).

**Features relacionadas:** FEAT-006.

**Status:** Ativa

### RN-002 — Alerta de divergência de KIT (não bloqueia)
**Descrição:** Ao entrar no status "Envio de Email para faturamento", o
sistema destaca em amarelo os campos do KIT digitados a partir do chamado do
IXC que divergem do KIT declarado pela EACE.

**Contexto:** Mesma regra já levantada em `requisitos.md` (ITEM 12): o KIT
declarado antes da instalação pode diferir do que foi realmente implantado
em campo — isso é só um alerta de atenção, não um erro formal.

**Critérios:** Comparação é KIT declarado (EACE) × KIT informado no chamado
IXC (implantado). Resultado divergente = destaque visual amarelo.

**Exceções:** Não bloqueia nenhuma transição de status nem o avanço do
processo — é apenas indicador visual.

**Impacto técnico:** a definir pelo Dev (decisão técnica reversível e de
baixo risco).

**Features relacionadas:** FEAT-005.

**Status:** Ativa

## Confronto de Divergências

### RN-003 — Confronto de divergências (EACE × IXC)
**Descrição:** O sistema compara, item a item, os dados digitados para o
"lado EACE" (relatório) contra os dados digitados para o "lado IXC"
(atendimento), usando quantidade e valor unitário, sem tolerância. O KIT
também entra nesse confronto formal contra o relatório da EACE — diferente
do alerta informal de KIT declarado × implantado (RN-002).

**Contexto:** `requisitos.md`, ITEM 4 e "PROCESSO do Projeto" (correções 1
e 2, 2026-08-20).

**Critérios:** comparação estrita — acentuação, espaço e maiúscula/minúscula
contam como divergência; o campo "Descrição do Item" não entra no confronto
de quantidade/valor, é usado só como referência de casamento entre os dois
lados; o lado EACE nunca é editado pelo pós-venda — uma correção só pode
vir de um relatório novo/atualizado da própria EACE.

**Exceções:** o catálogo fechado dos tipos de divergência formal (`valor`,
`quantidade`, `kit_relatorio`, `nf_financeiro`) foi **confirmado pelo
cliente em 2026-08-21 (P-03)** — ver `requisitos.md`, "PROCESSO do
Projeto"; pode ser ajustado ao longo do projeto se necessário, mas vale
para a v1 a partir de agora. **Pendência restante:** o critério exato de
casamento entre os itens dos dois lados (hoje proposto como texto igual da
descrição) ainda não foi confirmado pelo usuário, que optou por seguir sem
essa definição por agora.

**Impacto técnico:** tabela `ri_divergencia` (`modelo-dados.md`); bloqueia a
transição de status 2→3 do RN-001 enquanto houver divergência de
quantidade/valor aberta.

**Features relacionadas:** FEAT-004, FEAT-005, FEAT-006.

**Status:** Ativa (pendência restante só no critério de casamento entre
itens)

## Permissões

### RN-004 — Permissões por perfil de usuário
**Descrição:** Dois perfis fixos — Administrador (acesso total) e Analista
(tudo, exceto excluir). Aplica-se ao CRUD de INEP/item, aos documentos
anexados (NF/XML) e ao cadastro de usuário.

**Contexto:** `requisitos.md`, ITEM 13.

**Critérios:** exclusão de INEP/item e de usuário — só Administrador;
criação, edição e leitura de INEP/item, documentos e marcações manuais
(inclusive "Correção MEGA", RN-001) — Administrador e Analista; cadastro de
usuário (criar/editar/desativar) — só Administrador.

**Exceções:** nenhuma além das listadas — não há terceiro perfil nem
permissão granular por módulo nesta versão.

**Impacto técnico:** campo `usuario.perfil` (`administrador`/`analista`,
`modelo-dados.md`); checagem de permissão nas ações de exclusão e no
cadastro de usuário.

**Features relacionadas:** FEAT-003, FEAT-004, FEAT-006, FEAT-010.

**Status:** Ativa

## Segunda Validação Financeira

### RN-005 — Segunda validação da Nota Fiscal recebida
**Descrição:** Antes de liberar a marcação de anexo no portal EACE, o
sistema confere se a Nota Fiscal e o XML recebidos do financeiro
correspondem ao que foi solicitado no e-mail enviado para aquele INEP.

**Contexto:** `requisitos.md`, ITEM 7 e "PROCESSO do Projeto".

**Critérios:** validação ocorre durante o status "Aguardando Anexo portal
EACE" (RN-001); encontrar divergência classifica como o tipo
"NF × financeiro" no catálogo de divergências (RN-003).

**Exceções:** e-mail de resposta fora do padrão (sem 1 PDF + 1 XML, ou sem
INEP identificável) não bloqueia o fluxo, só gera alerta no log de e-mail.

**Impacto técnico:** tabelas `email_financeiro_log` e `documento`
(`modelo-dados.md`).

**Features relacionadas:** FEAT-009.

**Status:** Ativa

## Auditoria

### RN-006 — Escopo da auditoria
**Descrição:** O sistema audita alteração de campo, transição de status,
execução de ação manual que hoje substitui um RPA futuro, envio/recebimento
de e-mail, login no sistema e erros.

**Contexto:** `requisitos.md`, ITEM 10.

**Critérios:** reaproveita `apps/auditoria` do `modulo-posVenda` como
código-base; retenção indefinida (sem expiração); consulta aos registros só
por acesso direto ao banco nesta versão, sem tela própria.

**Exceções:** hoje `apps/auditoria` original só cobre login — estender para
alteração de campo/transição de status é decisão de implementação do Dev
(estender o existente ou criar log específico do módulo).

**Impacto técnico:** tabela `auditoria` (`modelo-dados.md`).

**Features relacionadas:** FEAT-011.

**Status:** Ativa

## Cadastro de Escola

### RN-007 — Status de conexão da Escola
**Descrição:** Toda escola tem um status de conexão com três valores fixos
— desconectado, parcialmente conectado, conectado — derivado do
preenchimento das datas de instalação dos processos RE e RI.

**Contexto:** `requisitos.md`, ITEM 11 (resposta de 2026-08-21).

**Critérios:** nasce **desconectado**; passa a **parcialmente conectado**
quando exatamente um dos dois processos (RE ou RI) tem data de instalação
preenchida; passa a **conectado** somente quando os dois processos têm data
de instalação preenchida. As datas são preenchidas manualmente pelo usuário,
a partir da informação que chega pelo chamado (IXC) — não há cálculo
automático nem RPA.

**Exceções:** esta versão (v1) só opera o processo RI em tela — o campo de
data de instalação do RE existe no modelo de dados, mas seu preenchimento
não tem fluxo próprio nesta versão (RE entra com tela própria na v3,
`architecture.md`). Uma escola cujo RI seja concluído nesta versão fica,
portanto, no máximo em "parcialmente conectado" até o RE ser tratado.

**Impacto técnico:** campos `escola.status_conexao`,
`escola.data_instalacao_re` e `escola.data_instalacao_ri`
(`modelo-dados.md`); recálculo do `status_conexao` a cada alteração de uma
das duas datas.

**Features relacionadas:** FEAT-002.

**Status:** Ativa

## Histórico de Alterações
| Data | Regra | Alteração |
|---|---|---|
| 2026-08-20 | RN-001, RN-002 criadas | Usuário detalhou o ciclo de vida completo de status do RI; confirmado que o confronto de quantidade/valor (RF-04) acontece durante "Andamento" e bloqueia a transição para "Envio de Email para faturamento" |
| 2026-08-21 | RN-001 ampliada (8º status "Correção MEGA") | Usuário pediu um status para sinalizar RI com divergência EACE×IXC devolvido à MEGA para correção; confirmado como status oficial (não flag), retorno manual para "Andamento", permissão de Analista e Administrador |
| 2026-08-21 | RN-003, RN-004, RN-005, RN-006 criadas | Orquestrador formalizou como regra de negócio decisões já registradas em `requisitos.md` (confronto RF-04, permissões RF-13, segunda validação RF-09, auditoria RF-12), para vincular ao `checklist.md` recém-criado |
| 2026-08-21 | RN-007 criada | Usuário respondeu a pendência de campos adicionais de `Escola` (requisitos.md, ITEM 11) com a regra de status de conexão (desconectado/parcialmente conectado/conectado) |
| 2026-08-21 | RN-003 e RN-005 perdem a pendência do catálogo de divergência; RN-003 mantém só a pendência do critério de casamento entre itens | Cliente confirmou o catálogo (P-03: `valor`, `quantidade`, `kit_relatorio`, `nf_financeiro`), podendo ajustar ao longo do projeto se necessário |
