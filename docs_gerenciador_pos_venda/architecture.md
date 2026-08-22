# Arquitetura Técnica — Gerenciador Pós-Venda (Faturamento EACE por INEP)
_Última atualização: 2026-08-22_

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
- **Auditoria** — login e execução de ações. **Gap:** hoje só cobre login;
  extensão para alteração de campo/status de INEP é decisão de
  implementação do Dev (estender existente ou log específico do módulo).
- **Usuários e Permissões** — dois perfis: Administrador (tudo) e Analista
  (tudo exceto excluir). CRUD de INEP/item, documentos e cadastro de
  usuário seguem essa regra.
- **Infra de e-mail** — reaproveita o padrão de polling IMAP já usado em
  `apps/integracoes/email` (sincronização de resposta), adaptado para a
  caixa dedicada do financeiro.
- **Frontend da tela "Endereços"** (`apps/leads/templates/leads/
  enderecos_lastmile.html` e partials) — exceção pontual à descontinuação
  de Leads, ver `ADR-001` (emenda 2026-08-22): reaproveita o template e as
  regras de frontend do grid (badge de status, filtros, cascata
  Setor→Responsável) para a `FEAT-007`. Trechos dependentes de
  Parceiro/cotação/Setor ainda precisam ser removidos ou adaptados pelo Dev
  na implementação.

### Novos nesta versão (v1)

- **Faturamento INEP** — INEP como cabeçalho, itens como registros filhos
  (`Descrição do Item`, `Qtde Produto`, `Valor Unit UR`), relação 1:N.
  Guarda também o "lado IXC" digitado manualmente na mesma granularidade.
  Só escopo **RI**.
- **Confronto** — compara item a item (quantidade e valor unitário, sem
  tolerância) o "lado EACE" (relatório, digitado à mão na v1) contra o
  "lado IXC"; e o KIT contra o relatório (erro formal) e contra o
  implantado em campo (alerta informal, não bloqueia). Lado EACE nunca é
  corrigido pelo pós-venda — só por um relatório atualizado da EACE.
- **Grid de INEPs** — linha por INEP (colunas: INEP, Nome da escola,
  Endereço, Status, Responsável) com drill-down para os itens; grid único
  de itens com filtro por status (não um grid separado por tipo de
  validação); exibe divergência com fundo vermelho.
- **Documentos** — armazena a Nota Fiscal (PDF) e o XML recebidos do
  financeiro por INEP; substitui uma NF anterior quando chega uma nova.
- **Fluxo de e-mail com o financeiro** — caixa própria do sistema
  `posvendas@megainfraestrutura.com.br` (envio e leitura, SMTP/IMAP);
  envio 1 e-mail por INEP (botão por linha do grid) com dados da escola e
  valores. Destinatários (Para): `hilber.lustosa@speedcsc.com.br`,
  `financeiro@speedcsc.com.br`. Cópia (Cc): `logistica-l@speedcsc.com.br`,
  `posvendas@megainfraestrutura.com.br`, `david.alves@speedcsc.com.br`.
  Leitura por polling IMAP (~5 min) identificando o INEP pela resposta ao
  e-mail enviado; e-mail fora do padrão gera alerta no log, não bloqueia.
- **Segunda validação** — confere se a NF recebida bate com o que foi
  solicitado ao financeiro antes de liberar o passo seguinte. Catálogo de
  status proposto em `requisitos.md` (ITEM 7, ainda `❓ aguardando
  validação do usuário`).
- **Ciclo de vida do INEP** — catálogo fechado de 8 status (ver RN-001 em
  `business_rules.md`): 7 na linha principal — Implantação EACE → Andamento
  → Envio de Email para faturamento → Aguardando financeiro → Aguardando
  Anexo portal EACE → Aguardando validação EACE → Faturamento Concluído —
  mais 1 desvio manual, "Correção MEGA", alcançável só a partir de
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

## Decisões Pendentes

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
