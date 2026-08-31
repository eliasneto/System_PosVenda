# Arquitetura Técnica — Gerenciador Pós-Venda (Faturamento EACE por INEP)
_Última atualização: 2026-08-28_

> Esta pasta documenta um **sistema novo e separado** do `modulo-posVenda`
> (repositório e banco de dados próprios, ver `requisitos.md`, bloco 0 e
> ITEM 13). Nasce **copiando código** deste repositório como ponto de
> partida — frontend, e-mail e permissão são reaproveitados; o restante é
> excluído da cópia. Os dois sistemas **não se comunicam** em tempo de
> execução depois de prontos. A pasta `docs/` original deste repositório
> permanece intacta, só de consulta.
>
> Este documento registra o **desenho-alvo da v1** com base no
> `requisitos.md` (raiz do repositório). Onde `requisitos.md` ainda tem
> `❓ Pendente`, este documento marca o gap explicitamente — nada aqui foi
> inventado além do que já está `✅ Definido`/`✅ Resolvido`.

## Resumo da Decisão Arquitetural

Monólito modular único (mesmo estilo da ADR-005 do `modulo-posVenda`:
camadas Entrada / Serviços-Domínio / Integração), sem microserviços. Escopo
da v1 é **só RI (kits)** — RE fica de fora do frontend, só de dados/regras
de backend se o Dev decidir deixar preparado.

## Identidade do Sistema e Versionamento

- **Repositório:** `https://github.com/eliasneto/Sistema_posvenda`
  (privado) — repositório próprio, separado do `modulo-posVenda`
  (requisitos.md, bloco 0). Criado pelo usuário em 2026-08-21; base do
  projeto (FEAT-001) já enviada para a branch `main`.
- **Nome exibido no menu (string de UI):** "Gerenciador Pós Venda" (sem
  hífen). Os documentos deste projeto continuam com "Gerenciador
  Pós-Venda" (com hífen) no título, só para leitura da documentação.
- **Versionamento:** semântico (`MAJOR.MINOR.PATCH`). Primeira versão
  estável — **1.0.0** — corresponde ao escopo desta v1 (processo RI,
  `checklist.md`, prazo 28/08/2026).
- As versões seguintes já levantadas em `requisitos.md` ("versão 2" — RPAs,
  04/09/2026; "versão 3" — IXC/RE, 10/09/2026) ainda não têm número
  semântico definido; isso é decidido quando cada uma entrar em
  planejamento.
- **Relação com o `modulo-posVenda` (ver `adr/ADR-001`):** o destino final é
  um único sistema — este. O `modulo-posVenda` é fonte de reaproveitamento
  incremental enquanto este sistema não estiver completo; ao final, o que
  não tiver sido reaproveitado é eliminado. Não é um segundo sistema
  mantido em paralelo indefinidamente.

## Banco de Dados

**Decisão (2026-08-21):** **MySQL 8.0 em todos os ambientes** — local,
homologação e produção. Substitui a decisão anterior do FEAT-001 (SQLite
local, marcada como reversível) — o usuário optou por engine único desde o
desenvolvimento local, para não ter comportamento divergente entre
ambientes. `DB_ENGINE=mysql` passa a ser o padrão do `.env` local, não só
uma opção.

Produção segue fora do escopo atual do DevOps (`.claude/agents/devops.md`,
"ESCOPO — HOMOLOGAÇÃO APENAS") — esta decisão fixa o **engine**, não abre
o mandato de construir o deploy de produção em si; isso continua exigindo
pedido explícito do usuário quando chegar a hora.

**Exceção pontual (2026-08-28, `ADR-003`):** usuário confirmou que
`192.168.90.109` é o servidor de produção real e pediu explicitamente a
correção de uma falha nele (estático não servido). Abertura de escopo
restrita a essa correção, sem criar ambiente de produção formal — ver
`ADR-003` para as condições.

## Processo (visão de negócio)

Descrição em linguagem simples do percurso completo do processo, sem regras
técnicas nem nomes de módulo — a versão visual está no diagrama `03`; a
versão técnica, com regras de negócio e status de erro, está no diagrama `01`.

Tudo começa quando os dados da implantação — feita pela MEGA através de um
parceiro — chegam ao sistema pelo atendimento registrado no IXC. O pós-venda
confere esses dados contra o relatório baixado no portal da EACE. Se houver
divergência, o atendimento volta para ser corrigido no IXC e o confronto se
repete. Se não houver divergência, o pós-venda pega os dados, monta uma
planilha e envia por e-mail ao financeiro.

O financeiro responde o e-mail com a Nota Fiscal (PDF) e o XML. O pós-venda
confere se os dados da Nota Fiscal estão corretos, valida as informações no
portal da EACE e anexa o PDF e o XML lá. A partir daí, o processo espera a
validação do cliente EACE, que responde por e-mail — quando isso acontece, o
INEP é considerado concluído (Faturado).

## Módulos e Responsabilidades

### Reaproveitados como código (adaptados ao banco novo)

- **Escolas** — model `Escola` (INEP, `kit_inicial`, `velocidade_dl_minima`,
  mais `lote`/`estado`/`municipio`/`status_conexao`/`data_instalacao_re`/
  `data_instalacao_ri`, ver RN-007). Sem cadastro novo de escola: os INEPs
  precisam existir desde o início. Migração/importação inicial das 2.622
  escolas para o banco novo é **obrigatória** antes da v1 entrar em uso
  (requisitos.md, bloco 0).
- **Auditoria** — login, transição de status do RI, alteração de campo/
  item (responsável, Lado IXC, Lado Relatório EACE), envio/recebimento de
  e-mail com o financeiro e erro não tratado da aplicação (FEAT-011,
  2026-08-31 — estendeu o `apps/auditoria` já existente, sem log
  específico separado). Sem tela própria nesta versão; consulta só por
  acesso direto ao banco.
- **Usuários e Permissões** — dois perfis: Administrador (tudo) e Analista
  (tudo exceto excluir). CRUD de INEP/item, documentos e cadastro de
  usuário seguem essa regra. **Exceção (RN-043, 2026-08-28):** login via
  Active Directory cria automaticamente o usuário local, com perfil
  Analista, no primeiro acesso — único caso em que a criação de usuário não
  passa pelo Administrador.
- **Infra de e-mail** — reaproveita o padrão de polling via **Microsoft
  Graph** já usado em `apps/integracoes/email` (sincronização de resposta;
  corrigido em 2026-08-25 — não é IMAP, a Microsoft aposentou Basic Auth
  IMAP nessa caixa e o `modulo-posVenda` já migrou para Graph, com um app
  do Azure AD próprio dele, real e habilitado —
  `GRAPH_EMAIL_REPLIES_ENABLED=true` no `.env` de lá), adaptado para a
  caixa dedicada do financeiro com um app do Azure AD **exclusivo deste
  sistema** (RN-009, ainda não provisionado, ver `FEAT-009`), e o código de
  rastreio de `apps/core/email_tracking.py` (RN-009), que identifica o
  INEP pelo assunto do e-mail.
- **Frontend da tela "Endereços"** (`apps/leads/templates/leads/
  enderecos_lastmile.html` e partials) — exceção pontual à descontinuação
  de Leads, ver `ADR-001` (emenda 2026-08-22): reaproveita o template e as
  regras de frontend do grid (badge de status, filtros, cascata
  Setor→Responsável) para a `FEAT-007`. Trechos dependentes de
  Parceiro/cotação/Setor ainda precisam ser removidos ou adaptados pelo Dev
  na implementação.
- **Autenticação e sincronização via Active Directory** (`ADR-002`,
  RN-043/RN-044, `FEAT-027`) — login passa a validar credenciais contra o
  AD (`django_auth_ldap.backend.LDAPBackend`, com `ModelBackend` como
  fallback), reaproveitando a mesma conta de serviço de bind e as mesmas
  variáveis `AD_*`/`USE_AD_AUTH` já configuradas no `.env` do
  `modulo-posVenda` — decisão explícita do usuário, diferente do app do
  Graph do financeiro (RN-009), que é exclusivo deste sistema. Depois de
  qualquer login, `apps/integracoes/ad/ad_sync.py` sincroniza e-mail/nome
  do usuário a partir do AD, sem bloquear o login se o LDAP estiver
  indisponível. Resolve a pendência aberta em `lixo.md` (item 7).

### Novos nesta versão (v1)

- **Faturamento INEP (3 lados do RI, esclarecido em 2026-08-22)** — INEP
  como cabeçalho, itens como registros filhos (`Descrição do Item`, `Qtde
  Produto`, `Valor Unit UR`), relação 1:N, em **3 lados** independentes:
  1. **Kit declarado** — dados informados pela EACE **antes do início do
     projeto** (model já implementado na FEAT-004, hoje chamado
     `RiItemEace` — nome pode ser ajustado pelo Dev para não confundir com
     o lado 3).
  2. **IXC** — dados informados manualmente pelo usuário a partir do
     chamado (já implementado, `RiItemIxc`).
  3. **Relatório EACE** (novo, ainda não implementado) — dados do relatório
     baixado no portal da EACE **depois da instalação**; mesma
     granularidade dos outros dois lados; nunca editado pelo pós-venda,
     só por um relatório novo/atualizado da própria EACE.

  Só escopo **RI**.
- **Catálogo de preços fixos EACE (LPU, RN-010)** — valores fixos por
  produto/kit e por Lote (Equipamento + Serviço), vindos da aba `LPU` de
  `CONSOLIDADO EACE.xlsx`; cruzado com `Escola.kit_inicial` **e**
  `Escola.lote` (não só a descrição) para resolver Quantidade/Valor do
  Kit declarado (1º lado) sem digitação manual. Model `KitPadrao` já
  existe (FEAT-004), ainda vazio; evolução do formato (lote, unidade,
  valor de equipamento/serviço) e importação em lote ficam para a
  FEAT-015.
- **Confronto (2 confrontos, RN-002/RN-003)** — compara item a item
  (Descrição/Quantidade/Valor Unitário):
  - **1º × 2º lado** (Kit declarado × IXC) — informal, destaque **amarelo**,
    não bloqueia (RN-002).
  - **3º × 2º lado** (Relatório EACE × IXC) — formal, sem tolerância,
    destaque **vermelho do lado do IXC** (2º lado); KIT também entra aqui
    contra o relatório (erro formal); **bloqueia** a transição do RI
    enquanto aberto (RN-003/RN-001).
- **Grid de INEPs** — linha por INEP, **5 colunas**: INEP, Nome da escola,
  Endereço, **Status de conexão** (atributo da própria Escola/INEP, RF-20:
  desconectado/parcialmente conectado/conectado) e **Status do RI** (RN-001/
  seção 5 dos requisitos: Implantação EACE, Andamento, ... Faturamento
  Concluído). Com drill-down para os itens; grid único de itens com filtro
  por status do RI (não um grid separado por tipo de validação); exibe
  divergência com fundo vermelho. Status do RI é atributo do RI, não do
  INEP/Escola; Status de conexão é o único status que pertence à própria
  Escola/INEP — as duas colunas ficam lado a lado no grid, sem uma estar
  "dentro" da outra. O mesmo vale, futuramente, para o RE.
  **Responsável** (também atributo do RI, RN-012) **não é coluna da tabela
  principal** — decisão revista em 2026-08-25: fica só dentro do drill-down
  do grid e da tela de detalhe do RI (FEAT-004), como campo editável
  (`<select>` com os usuários do sistema), não mais como texto fixo.
- **Documentos** — armazena a Nota Fiscal (PDF) e o XML recebidos do
  financeiro por INEP; substitui uma NF anterior quando chega uma nova.
- **Fluxo de e-mail com o financeiro** — caixa própria do sistema
  `posvendas@megainfraestrutura.com.br` (envio via SMTP; leitura via
  Microsoft Graph, não IMAP — ver "Infra de e-mail" acima); o
  grid mostra só um botão por linha do INEP (habilitado conforme o status
  do RI), que abre uma tela/modal de composição com os campos De
  (automático, remetente do sistema, não editável), Para, Cc, Assunto,
  Anexo e Mensagem — não mais um formulário direto na tela do grid.
  Para/Cc/Assunto vêm pré-preenchidos — Para: `hilber.lustosa@speedcsc.com.br`,
  `financeiro@speedcsc.com.br`; Cc: `logistica-l@speedcsc.com.br`,
  `posvendas@megainfraestrutura.com.br`, `david.alves@speedcsc.com.br`;
  Assunto com o código de rastreio (RN-009) — mas editáveis pelo usuário
  antes de enviar. Anexo: uma cópia preenchida da planilha-modelo
  `doc/FATURAMENTO MATERIAS EACE.xlsx` (uma aba por produto/KIT lançado
  no Lado IXC, criada automaticamente quando não há aba correspondente)
  continua anexada por padrão, no lugar do PDF gerado antes (FEAT-017);
  o campo permite acrescentar mais um arquivo, opcional; botão "Baixar
  planilha" gera a mesma cópia antes de enviar, para conferência — ver
  `business_rules.md`, RN-013/RN-014/RN-015. Leitura por polling via Microsoft Graph (~5 min,
  serviço `email_scheduler`) identificando o INEP pelo código de rastreio
  embutido no assunto do e-mail enviado (RN-009); e-mail fora do padrão
  gera alerta no log, não bloqueia.
- **Segunda validação** — confere se a NF recebida bate com o que foi
  solicitado ao financeiro antes de liberar o passo seguinte. Catálogo de
  status proposto em `requisitos.md` (ITEM 7, ainda `❓ aguardando
  validação do usuário`).
- **Ciclo de vida do INEP** — catálogo fechado de 8 status (ver RN-001 em
  `business_rules.md`): 7 na linha principal — Implantação EACE → Andamento
  → Envio de Email para faturamento → Aguardando financeiro → Resposta
  Financeiro → Aguardando validação EACE → Faturamento Concluído — mais 1
  desvio manual, "Correção MEGA", alcançável só a partir de
  "Andamento" quando há divergência de quantidade/valor (RF-04) aberta, e
  que só retorna manualmente para "Andamento" (sem gatilho automático em
  nenhum sentido). A transição Andamento → Envio de Email para faturamento
  é bloqueada enquanto essa divergência estiver aberta — "Correção MEGA" é a
  forma visível desse bloqueio, não um jeito de contorná-lo; a divergência
  de KIT (RN-002) é só alerta visual (amarelo), não bloqueia.

### Estrutura de navegação (menu lateral)

- Menu lateral organizado em nível hierárquico: aba **"Projeto"** agrupando,
  por enquanto, só o subitem **"EACE"**; dentro de "EACE" fica o grid
  existente da FEAT-007 (hoje item de menu plano "Grid de INEPs" em
  `core/base.html`).
- Reorganização só de navegação/UI — não altera view, URL, template ou
  lógica do grid da FEAT-007 (`apps/ri/views.py`, `grid_inep.html`), que
  segue `🔍 Aguardando QA`.
- Outros itens dentro de "Projeto" ficam em aberto para quando existirem
  (usuário confirmou que, por ora, é só o agrupamento para EACE).

### Fora do escopo da v1 (gap — Hub de Integrações, dividido em v2 e v3)

**Versão 2 — entrega 04/09/2026:**
- RPA de download do relatório EACE (substitui a digitação manual do "lado
  EACE").
- RPA de anexo dos arquivos no portal EACE (substitui a marcação manual).

**Versão 3 — entrega 10/09/2026:**
- Integração automática com o IXC via API/parsing de atendimento
  (substitui a digitação manual do "lado IXC"); client já existe em
  `apps/integracoes/ixc` no `modulo-posVenda` original, reaproveitável
  quando isso for retomado.
- Processo RE (instalação de link) com tela própria. **Nota de
  prontidão (2026-08-22):** o usuário confirmou que a v1 continua só RI —
  RE não entra agora, nem como requisito, nem como tela. O pedido é só
  arquitetural: quando a v3 for planejada, RE deve seguir o mesmo padrão
  já usado pela RI — uma subatividade própria por Escola (hoje o model
  `Ri`), não misturada dentro dela. Isso não antecipa modelo de dados,
  status ou regra de RE — nada disso está decidido; é só a orientação de
  que RE ganha seu próprio model/tela quando chegar a hora, no mesmo
  formato da RI, em vez de ser encaixada dentro do que já existe.

## Padrão de Interação Frontend — Atualizações Sem Reload Completo

Ações pontuais de atualização (troca de status do RI, troca de responsável,
registro de histórico/log) usam **HTMX** para atualizar só o trecho da tela
afetado, sem recarregar a página inteira nem perder posição de rolagem ou
filtros aplicados. HTMX já era a ferramenta padrão do Dev para esse tipo de
interação (`.claude/agents/dev.md`, seção 11); esta seção registra a decisão
no nível do projeto — até 2026-08-26 ela só existia na instrução do agente,
não na arquitetura documentada.

Aplicação inicial (escopo da `FEAT-019`): `ri_status_update_view`,
`ri_responsavel_update_view` e o registro de histórico/log da `FEAT-014`,
hoje implementados como POST tradicional com `redirect()` de página
completa (`apps/ri/views.py`).

Regras do padrão, quando usado:

- a view responde com o partial atualizado (fragmento HTML) quando a
  requisição chega via HTMX (header `HX-Request`), e mantém o
  comportamento de POST + redirect tradicional como fallback quando não
  chega — navegação sem JavaScript continua funcionando;
- mensagens de sucesso/erro (`django.contrib.messages`) continuam sendo
  exibidas no fluxo HTMX;
- CSRF continua obrigatório;
- ações destrutivas continuam exigindo confirmação.

## Decisões Pendentes

- Ambiente de produção formal (compose próprio, branch própria, pipeline de
  CI/CD, secrets segregados de homologação) — `192.168.90.109` roda hoje sem
  isso; abertura de escopo atual é pontual (`ADR-003`), não define o
  ambiente definitivo.
- Critério exato de casamento entre os itens dos dois lados (EACE × IXC),
  hoje proposto como texto igual da descrição (`business_rules.md` RN-003;
  `modelo-dados.md`, "Pendências desta modelagem") — ainda não confirmado
  pelo cliente; distinto do catálogo de tipos de divergência (já
  confirmado, ver abaixo).
- Diagramas `01` (processo técnico) e `03` (jornada de negócio) ainda
  mostram a sequência de 7 status — desatualizados após o 8º status
  "Correção MEGA" (RN-001, 2026-08-21). Regenerar quando solicitado
  (MODO 5 — não é automático).

Resolvidas nesta rodada (2026-08-20): migração inicial de dados de Escola
(obrigatória, ver ITEM 11/bloco 0); estrutura do grid de detalhe (grid único
com filtro por status, ver ITEM 5); endereços completos do e-mail ao
financeiro — Para e Cc (ver ITEM 6 e módulo "Fluxo de e-mail com o
financeiro" acima).

Resolvida em 2026-08-21: catálogo de tipos de divergência (P-03) —
confirmado pelo cliente como `valor`, `quantidade`, `kit_relatorio`,
`nf_financeiro` (bloqueiam) e o alerta `kit_declarado_diferente_implantado`
(não bloqueia); ver `requisitos.md` ("PROCESSO do Projeto") e
`business_rules.md` RN-003/RN-005.

## Conjunto de diagramas e ordem de leitura

| # | Diagrama | Pergunta que responde | Público |
|---|---|---|---|
| `01` | Processo de faturamento RI | Como o processo flui do kit instalado até o INEP Faturado, e o que é manual na v1 x automático na v2? (versão técnica, com regras e status de erro) | quem vai desenvolver ou revisar |
| `02` | Arquitetura dos módulos | Como o sistema se organiza por dentro: módulos reaproveitados, módulos novos e onde entra o Hub de Integrações da v2? | quem vai desenvolver ou revisar |
| `03` | Jornada do processo (visão de negócio) | Qual o percurso do processo, em linguagem simples e sem regras técnicas, do atendimento da implantação até a validação do cliente EACE? | qualquer pessoa, inclusive fora da equipe |

## Histórico de Alterações
| Data | Alteração | Motivo |
|---|---|---|
| 2026-08-31 | "Ciclo de vida do INEP" corrigido — nome do status 5 atualizado para "Resposta Financeiro" (estava com o nome antigo, "Aguardando Anexo portal EACE") | FEAT-020 já tinha renomeado o status em `business_rules.md` (RN-001); esta seção não tinha sido atualizada junto |
| 2026-08-31 | "Auditoria" em "Módulos e Responsabilidades" deixa de descrever gap ("hoje só cobre login") e passa a listar o escopo entregue | FEAT-011 entregue pelo Dev — login, transição de status, alteração de campo/item, envio/recebimento de e-mail e erro não tratado passam a gerar registro de auditoria; aguardando QA |
| 2026-08-28 | Abertura pontual de escopo de produção para o DevOps corrigir estático não servido em `192.168.90.109` (`ADR-003`) | Usuário confirmou que esse servidor é produção (não homologação) e pediu explicitamente a correção da logo quebrada; FEAT-012 |
| 2026-08-28 | Novo módulo "Autenticação e sincronização via Active Directory" em "Módulos e Responsabilidades"; "Usuários e Permissões" recebe exceção (RN-043) | Usuário pediu a integração com AD, resolvendo a pendência aberta em `lixo.md` (item 7); RN-043/RN-044 criadas em `business_rules.md`; decisão de reaproveitar a mesma conta de serviço/config do `modulo-posVenda` registrada em `ADR-002`; gera `FEAT-027` |
| 2026-08-26 | Nova seção "Padrão de Interação Frontend — Atualizações Sem Reload Completo" (HTMX); `FEAT-019` criada | Usuário pediu para trocar de status/responsável e registrar histórico sem recarregar a página inteira; HTMX já era padrão do Dev (`dev.md`) mas não estava registrado na arquitetura do projeto |
| 2026-08-26 | "Fluxo de e-mail com o financeiro" atualizado: nota de alvo (PDF → planilha) vira descrição do estado atual, já entregue e validado no navegador real | FEAT-017/FEAT-018 entregues pelo Dev no mesmo dia; RN-013 revisada 2× até o desenho final (aba automática, exigência só no envio/download) e RN-015 criada (1 KIT por INEP) |
| 2026-08-26 | "Fluxo de e-mail com o financeiro" recebe nota de alvo: anexo automático passa de PDF para cópia preenchida de `doc/FATURAMENTO MATERIAS EACE.xlsx` | RN-013/RN-014 criadas e FEAT-017/FEAT-018 abertas — alvo ainda não implementado, estado atual (PDF) mantido na descrição até a entrega |
| 2026-08-24 | Módulo "Catálogo de preços fixos EACE (LPU)" registrado em "Módulos e Responsabilidades" | Usuário indicou a aba `LPU` de `CONSOLIDADO EACE.xlsx` (produto/lote/valor de equipamento/valor de serviço) como origem dos valores fixos do Kit; RN-010 ampliada e FEAT-015 criada |
| 2026-08-22 | Nota de prontidão para RE na seção "Fora do escopo da v1" (Versão 3) | Usuário pediu para deixar a arquitetura pronta para RE, mas confirmou que a v1 continua só RI e que os requisitos não devem ser alterados agora — registrado só como orientação de padrão (RE ganha model/tela próprios, não entra dentro da RI), sem antecipar modelo, status ou regra de RE |
| 2026-08-22 | Módulo "Frontend da tela Endereços" adicionado aos reaproveitados; ADR-001 recebe emenda | Usuário confirmou reaproveitamento de código (não só referência visual) do frontend da tela Endereços do `modulo-posVenda` para a FEAT-007, mantendo descontinuados Provedores/Parceiro e o restante de Leads |
| 2026-08-22 | ADR-001 e seção "Relação com o `modulo-posVenda`" | Usuário definiu o destino final: um único sistema (este); `modulo-posVenda` é fonte de reaproveitamento até ser eliminado |
| 2026-08-20 | Criação do documento e do conjunto de diagramas 01/02 | Primeiro registro de arquitetura do Gerenciador Pós-Venda, a partir de `requisitos.md` |
| 2026-08-20 | Diagrama 03 (jornada de negócio) e seção "Processo (visão de negócio)" | Usuário pediu uma versão do percurso do processo sem regras técnicas, para leitura por qualquer pessoa |
| 2026-08-20 | Criação de `business_rules.md` (RN-001, RN-002); ciclo de vida do INEP detalhado | Usuário detalhou o catálogo completo de status do RI |
| 2026-08-20 | Diagramas 01/02/03 atualizados (terminologia "Faturamento Concluído", sublabel do módulo Ciclo de Vida, card de status oficiais) | Alinhar os diagramas ao RN-001/RN-002 recém-criados |
| 2026-08-20 | Respostas a P-01/P-02/P-05: migração de Escola obrigatória, grid único com filtro por status, caixa própria `posvendas@megainfraestrutura.com.br` | Usuário respondeu pendências do documento de validação |
| 2026-08-20 | P-01 fechado: endereços Para/Cc do e-mail ao financeiro | Usuário informou os destinatários completos |
| 2026-08-20 | Escopo pós-v1 dividido em v2 (04/09/2026, os 2 RPA) e v3 (10/09/2026, API IXC + RE) | Usuário definiu prazos e recorte das próximas versões |
| 2026-08-20 | Diagramas 01/02 atualizados para o recorte v2/v3; corrigido tag de migração de Escola (era "gap", agora "obrigatória") | Alinhar diagramas ao novo recorte e à resposta já dada ao P-05 |
| 2026-08-20 | Criação de `modelo-dados.md` (tabelas, campos, relacionamentos, exemplos) | Usuário pediu a modelagem de banco de dados do sistema |
| 2026-08-20 | Criação de `modelo-dados-diagrama.pdf` (diagrama ER visual) | Usuário pediu o mesmo conteúdo no formato de diagrama entidade-relacionamento |
| 2026-08-20 | `modelo-dados-diagrama.pdf` reconstruído com Mermaid (`erDiagram`) em vez de SVG manual | Usuário pediu uma biblioteca específica para o diagrama, após o desenho manual ter saído com defeitos |
| 2026-08-20 | Criação de `lixo.md` (mapa do que não faz parte da cópia: apps inteiros, trechos de model/template dentro de apps reaproveitados, scripts e artefatos de operação) | Usuário pediu um levantamento organizado do que hoje não será usado no sistema novo, para exclusão segura depois que a v1/v2/v3 estiver pronta |
| 2026-08-21 | Ciclo de vida do INEP passa de 7 para 8 status (novo status "Correção MEGA") | Usuário pediu um status para RI com divergência EACE×IXC devolvido à MEGA para correção; ver RN-001 em `business_rules.md` |
| 2026-08-21 | Campos adicionais de `Escola` definidos (`lote`, `estado`, `municipio`, `status_conexao`, datas de instalação RE/RI); RN-007 criada | Usuário respondeu a pendência de campos de Escola (requisitos.md, ITEM 11) |
| 2026-08-21 | Criação de `checklist.md` (FEAT-001 a FEAT-011, v1/RI); RN-003 a RN-006 criadas em `business_rules.md` | Usuário pediu início do desenvolvimento; regras já decididas em `requisitos.md` (confronto, permissões, segunda validação, auditoria) formalizadas para vincular ao checklist |
| 2026-08-21 | Nome de exibição ("Gerenciador Pós Venda", sem hífen) e versionamento (1.0.0 para a v1) definidos | Usuário definiu o nome exibido no menu e a primeira versão do sistema antes do início do desenvolvimento |
| 2026-08-21 | Repositório do sistema novo registrado (`Sistema_posvenda`, privado); FEAT-001 entregue pelo Dev | Usuário criou o repositório no GitHub; Dev montou a base do projeto (config, apps core/escolas/ri/auditoria) sobre ele |
| 2026-08-21 | Catálogo de tipos de divergência (P-03) sai de "Decisões Pendentes" — confirmado pelo cliente | Pendência restante do confronto EACE×IXC passa a ser só o critério de casamento entre itens (ainda em aberto) |
| 2026-08-22 | Estrutura de navegação do menu lateral definida: aba "Projeto" > "EACE" > grid da FEAT-007 | Usuário pediu reorganização do menu (hoje item plano "Grid de INEPs"); confirmado que é o mesmo grid da FEAT-007, sem lógica nova, e que "Projeto" por ora só agrupa "EACE" |
| 2026-08-22 | Esclarecido: Status e Responsável são atributos do RI (e, futuramente, do RE) — o INEP/Escola (atividade pai) não tem esses campos próprios; a coluna do grid mostra o dado do RI mais recente daquele INEP | Usuário confirmou a regra depois de eu apontar que o RF-05 (`requisitos-validacao-cliente.html`) já lista as duas colunas; a implementação entregue pelo Dev já refletia essa regra (`Ri.status`/`Ri.responsavel`, nunca campo da `Escola`) — sem mudança de código, só de clareza na documentação |
| 2026-08-22 | Grid de INEPs passa a ter 6 colunas: Status de conexão (Escola, RF-20) entra como coluna própria, ao lado de Status do RI e Responsável (RF-05) — não fica mais só dentro do drill-down | Usuário apontou que status de conexão é atributo do próprio INEP/Escola e merece a mesma visibilidade de linha que as colunas do RI, não deveria ficar escondido dentro do drill-down |
| 2026-08-22 | RI passa de 2 para 3 "lados": Kit declarado (1º, antes do projeto), IXC (2º) e Relatório EACE (3º, novo); dois confrontos — RN-002 (1º×2º, amarelo, informal) e RN-003 (3º×2º, vermelho do lado do IXC, bloqueia) | Usuário esclareceu que o model já implementado (`RiItemEace`, FEAT-004) representa o 1º lado, não "o relatório"; ver `business_rules.md` (RN-002/RN-003 reescritas) e `checklist.md` (FEAT-004/FEAT-005 atualizadas) |
| 2026-08-23 | "Infra de e-mail" e "Fluxo de e-mail com o financeiro" passam a citar explicitamente o mecanismo de código de rastreio (RN-009), reaproveitado de `apps/core/email_tracking.py` do `modulo-posVenda` | Usuário pediu para trazer ao `Sistema_posvenda` a funcionalidade de e-mail (enviar, receber, rastreio e histórico) já existente no `modulo-posVenda`; identificação do INEP na resposta (FEAT-009) deixa de ser genérica e passa a referenciar o mecanismo concreto |
| 2026-08-24 | "Fluxo de e-mail com o financeiro" passa a descrever uma tela/modal de composição (De/Para/Cc/Assunto/Anexo/Mensagem) aberta por um único botão do grid, em vez do formulário com só "Observação" direto na tela; Para/Cc/Assunto viram pré-preenchidos e editáveis (antes estritamente fixos); Anexo passa a ser adicional ao PDF automático (RN-008), não substituto | Usuário reprovou a entrega da FEAT-008 (só um campo de observação) antes mesmo do QA revisar; pediu tela dedicada de envio de e-mail; FEAT-008 volta para `🔄 Em andamento` em `checklist.md` |
| 2026-08-25 | Grid de INEPs volta a ter 5 colunas: "Responsável" deixa de ser coluna da tabela principal e passa a viver só dentro do RI (drill-down do grid e tela da FEAT-004), agora como campo editável (`<select>` com os usuários do sistema) — RN-012 criada em `business_rules.md`; FEAT-007 volta a `🔄 Em andamento` | Usuário viu, na tela real, a coluna "Responsável" ainda na tabela principal e pediu a mudança; reabre, com decisão explícita do usuário, a discussão já registrada em 2026-08-22 sobre onde essa coluna deveria viver (RF-05 continua valendo para Status; Responsável passa a ter tratamento próprio) |
| 2026-08-25 | Corrigido: "Infra de e-mail" e "Fluxo de e-mail com o financeiro" descreviam a leitura como polling IMAP — não é IMAP, é Microsoft Graph (a Microsoft aposentou Basic Auth IMAP nessa caixa); passam a citar o serviço `email_scheduler` (FEAT-012) e o app do Azure AD exclusivo deste sistema (RN-009, ainda não provisionado) | Usuário perguntou se o `modulo-posVenda` também precisou dessa mudança; verificação no código confirmou que sim — `apps/integracoes/email` de lá já usa Microsoft Graph (`GRAPH_EMAIL_REPLIES_ENABLED=true`, credenciais reais no `.env` de lá), não IMAP; a descrição desta arquitetura estava desatualizada nesse ponto |
