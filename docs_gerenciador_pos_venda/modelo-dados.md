# Modelagem de Banco de Dados — Gerenciador Pós-Venda
_Última atualização: 2026-08-26_

> Escopo: banco de dados próprio deste sistema (separado do `modulo-posVenda`
> original, ver `architecture.md`). Cobre o processo **RI** da v1
> (`requisitos.md`, `business_rules.md` RN-001/RN-002). O processo **RE**
> fica fora desta modelagem — entra quando a v3 for planejada.
>
> Convenções: tabelas no singular, `snake_case`; toda tabela tem `id`
> (chave primária) e, quando aplicável, `criado_em`/`atualizado_em`; chave
> estrangeira nomeada `<tabela>_id`. Tipos em sintaxe MySQL (banco do
> `modulo-posVenda` original, reaproveitado como ponto de partida).
>
> Pontos ainda **pendentes de confirmação do cliente** (ver seção final)
> foram assumidos aqui como proposta técnica, não como definição fechada.

## Diagrama de relacionamento (resumo)

| De | Para | Tipo |
|---|---|---|
| `escola` | `ri` | 1 escola → N RI |
| `usuario` | `ri` | 1 usuário → N RI (responsável) |
| `ri` | `ri_item_eace` | 1 RI → N itens (1º lado — Kit declarado, EACE antes do projeto) |
| `ri` | `ri_item_ixc` | 1 RI → N itens (2º lado — IXC) |
| `ri` | `ri_item_relatorio_eace` | 1 RI → N itens (3º lado — Relatório EACE, novo, pós-instalação) |
| `ri` | `ri_divergencia` | 1 RI → N divergências |
| `ri` | `documento` | 1 RI → N documentos (NF/XML) |
| `ri` | `email_financeiro_log` | 1 RI → N e-mails (enviados/recebidos) |
| `ri` | `ri_historico` | 1 RI → N registros de histórico (mensagem, anexo, e-mail, log automático) |
| `usuario` | `auditoria` | 1 usuário → N registros de auditoria |
| `escola` | `kit_padrao` | cruzamento por valor (`escola.kit_inicial` = `kit_padrao.descricao` **e** `escola.lote` = `kit_padrao.lote`) — não é FK, ver RN-010 |

## Tabelas

### `escola`
Reaproveitada do `modulo-posVenda` (model `Escola`). Migração inicial dos
2.622 registros é obrigatória antes da v1 entrar em uso (já confirmado).

| Campo | Tipo | Nulo | Descrição |
|---|---|---|---|
| `id` | `BIGINT` | não | Chave primária |
| `inep` | `VARCHAR(8)` | não | Único. Texto, não numérico — preserva zero à esquerda |
| `nome` | `VARCHAR(255)` | não | Nome da escola (coluna do grid, ITEM 5) |
| `endereco` | `VARCHAR(255)` | sim | Coluna do grid (ITEM 5) |
| `lote` | `INT` | sim | Lote de escolas informado pela EACE (requisitos.md, ITEM 11) |
| `estado` | `CHAR(2)` | sim | UF (requisitos.md, ITEM 11) |
| `municipio` | `VARCHAR(150)` | sim | Município (requisitos.md, ITEM 11) |
| `kit_inicial` | `VARCHAR(100)` | sim | KIT declarado pela EACE (reaproveitado, RN-057 original) |
| `velocidade_dl_minima` | `VARCHAR(50)` | sim | Reaproveitado (RN-057 original) |
| `status_conexao` | `ENUM('desconectado','parcialmente_conectado','conectado')` | não | Default `desconectado`. Ver RN-007 |
| `data_instalacao_re` | `DATE` | sim | Preenchimento manual (vem do chamado); RE fora do frontend da v1 (só guarda o dado) |
| `data_instalacao_ri` | `DATE` | sim | Preenchimento manual (vem do chamado) |
| `criado_em` / `atualizado_em` | `DATETIME` | não | — |

**Exemplo:**
| id | inep | nome | endereco | lote | estado | municipio | status_conexao |
|---|---|---|---|---|---|---|---|
| 1 | `53008430` | EM José da Silva | Rua das Flores, 123 — Centro | 9 | SP | Nova Aliança | parcialmente_conectado |

### `usuario`
Reaproveitado (permissão). Dois perfis fixos (ITEM 13).

| Campo | Tipo | Nulo | Descrição |
|---|---|---|---|
| `id` | `BIGINT` | não | Chave primária |
| `nome` | `VARCHAR(150)` | não | — |
| `email` | `VARCHAR(255)` | não | Único |
| `perfil` | `ENUM('administrador','analista')` | não | Administrador: tudo. Analista: tudo exceto excluir |
| `ativo` | `BOOLEAN` | não | Default `true` |
| `criado_em` / `atualizado_em` | `DATETIME` | não | — |

**Exemplo:**
| id | nome | email | perfil | ativo |
|---|---|---|---|---|
| 2 | Maria Souza | maria.souza@megainfraestrutura.com.br | analista | true |

### `ri`
Tabela central do processo — cabeçalho do INEP ("Faturamento INEP", ITEM 2).
Um RI nasce com status `implantacao_eace` e percorre os 8 status do RN-001
(7 na linha principal + o desvio manual `correcao_mega`).

| Campo | Tipo | Nulo | Descrição |
|---|---|---|---|
| `id` | `BIGINT` | não | Chave primária |
| `escola_id` | `BIGINT` (FK `escola.id`) | não | — |
| `responsavel_id` | `BIGINT` (FK `usuario.id`) | sim | Coluna "Responsável" do grid (ITEM 5) |
| `status` | `ENUM(...)` | não | Os 8 valores do RN-001 (ver abaixo). Default `implantacao_eace` |
| `kit_informado_ixc` | `VARCHAR(100)` | sim | KIT do chamado IXC, para o alerta do RN-002 |
| `divergencia_kit` | `BOOLEAN` | não | Alerta amarelo (RN-002) — `kit_informado_ixc` ≠ `escola.kit_inicial`. Não bloqueia |
| `data_ativacao` | `DATE` | sim | Data de Ativação do Lado IXC (RN-011); valor único por RI, não por item |
| `municipio_ixc` | `VARCHAR(150)` | sim | Município do Lado IXC (RN-014), preenchimento manual; usado na planilha de faturamento (RN-013). Comparado a `escola.municipio` — divergência é só alerta visual |
| `estado_ixc` | `CHAR(2)` | sim | UF do Lado IXC (RN-014), preenchimento manual, sempre maiúsculo. Comparado a `escola.estado` — divergência é só alerta visual |
| `observacoes_envio_financeiro` | `TEXT` | sim | Texto livre do campo "Mensagem" da tela de composição de e-mail (FEAT-008) |
| `dados_financeiro_confirmados_em` | `DATETIME` | sim | Preenchido ao confirmar o envio na tela de composição (FEAT-008) |
| `concluido_em` | `DATETIME` | sim | Preenchido ao chegar em `faturamento_concluido` |
| `criado_em` / `atualizado_em` | `DATETIME` | não | — |

Valores de `status`: `implantacao_eace`, `andamento`, `envio_email_faturamento`,
`aguardando_financeiro`, `aguardando_anexo_portal_eace`,
`aguardando_validacao_eace`, `faturamento_concluido`, `correcao_mega`.

`correcao_mega` (RN-001, 2026-08-21) só é alcançado a partir de `andamento`,
manualmente, quando há divergência de quantidade/valor (RF-04) aberta contra
o relatório EACE; retorna também manualmente para `andamento` — sem gatilho
automático em nenhum dos dois sentidos, e sem transição direta para nenhum
outro valor.

**Exemplo:**
| id | escola_id (inep) | status | responsavel_id | kit_informado_ixc | divergencia_kit |
|---|---|---|---|---|---|
| 1 | 1 (`53008430`) | `andamento` | 2 | Kit Padrão 10Mb | false |
| 2 | 3 (`53012345`) | `correcao_mega` | 2 | Kit Padrão 20Mb | false |

### `kit_padrao` (catálogo de preços fixos EACE — LPU, RN-010)
Catálogo de valores fixos por produto/kit, informado pela EACE na aba
`LPU` de `CONSOLIDADO EACE.xlsx` ("TABELA 1 - LISTA DE PREÇOS UNITÁRIOS").
Sem FK para `escola` — o cruzamento com `escola.kit_inicial`/`escola.lote`
é por valor (mesmo texto + mesmo lote), usado para resolver Quantidade e
Valor Unitário de `ri_item_eace` (RN-010). Tabela existe desde 2026-08-24
(model `KitPadrao`, migration 0005), hoje só com `descricao`/
`quantidade_padrao`/`valor_unitario_padrao` e vazia (nenhum valor
inventado). Os campos abaixo já refletem a evolução prevista para
incorporar os valores reais da planilha (lote, unidade, valor de
equipamento e de serviço separados) — ver FEAT-015, ainda não migrada.

| Campo | Tipo | Nulo | Descrição |
|---|---|---|---|
| `id` | `BIGINT` | não | Chave primária |
| `descricao` | `VARCHAR(255)` | não | Mesmo texto de `escola.kit_inicial` |
| `lote` | `INT` | sim | Mesmo valor de `escola.lote`; o preço varia por lote (ex.: `9`, `11`, hoje os únicos mapeados na planilha) |
| `unidade` | `VARCHAR(50)` | sim | Texto da coluna "Unidade" da planilha (`Escola`, `Escola/Mês`, `Unidade`, `km`, `enlace`, `metro`, `par`) — define se o valor é o KIT fechado da escola (`Escola`/`Escola/Mês`) ou preço unitário de item avulso |
| `quantidade_padrao` | `INT` | não | `1` para linhas tipo `Escola`/`Escola/Mês` (o kit fechado); sem uso automático nas demais linhas |
| `valor_equipamento` | `DECIMAL(10,2)` | sim | Coluna "Equipamentos (R$)" da planilha; nulo quando a planilha não traz valor de equipamento para o item |
| `valor_servico` | `DECIMAL(10,2)` | sim | Coluna "Serviços (R$)" da planilha |
| `descricao_curta` | `VARCHAR(255)` | sim | Nome mostrado nas listas do Lado IXC (RN-011) — `descricao` sem o qualificador entre parênteses do final; preenchida automaticamente ao salvar quando vazia |
| `numero_access_points` | `INT` | sim | Extraído automaticamente da `descricao` (padrão "... N Access Points"); usado para cruzar com `escola.kit_inicial` quando ela traz só o número (RN-010 ampliada) |
| `aba_planilha_financeiro` | `VARCHAR(50)` | sim | Atalho opcional: nome da aba na planilha de faturamento (RN-013) — permite juntar produtos parecidos numa aba compartilhada (ex.: "Rack 3U"/"Rack 5U" → "RACK"). Sem preencher, o produto ganha aba própria automática. Não se aplica a KIT |
| `criado_em` / `atualizado_em` | `DATETIME` | não | — |

Chave única de negócio: (`descricao`, `lote`) — a mesma descrição pode se
repetir com valor diferente em outro lote.

**Exemplo:**
| id | descricao | lote | unidade | valor_equipamento | valor_servico |
|---|---|---|---|---|---|
| 1 | Kit Cobertura Wi-Fi - 6 Access Points | 9 | Escola | 14457.89 | 20673.51 |
| 2 | Kit Cobertura Wi-Fi - 6 Access Points | 11 | Escola | 13896.92 | 19871.38 |
| 3 | Access Point adicional Indoor | 9 | Unidade | 727.31 | 1711.70 |

### `ri_item_eace` (1º lado — Kit declarado)
**Esclarecido em 2026-08-22:** apesar do nome (mantido por ora — ajuste de
nome é decisão técnica do Dev), esta tabela guarda os itens do **1º lado**
do RI: os dados informados pela EACE **antes do início do projeto** ("Kit
declarado"). Não é "o relatório" — esse é o 3º lado, `ri_item_relatorio_eace`
(novo, ver abaixo). Confrontado contra `ri_item_ixc` na RN-002 (informal,
amarelo, não bloqueia).

| Campo | Tipo | Nulo | Descrição |
|---|---|---|---|
| `id` | `BIGINT` | não | Chave primária |
| `ri_id` | `BIGINT` (FK `ri.id`) | não | — |
| `descricao_item` | `VARCHAR(255)` | não | Não entra no confronto; usada aqui como chave de casamento com `ri_item_ixc` — **ver pendência ao final** |
| `quantidade` | `INT` | não | Entra no confronto RN-002 |
| `valor_unitario` | `DECIMAL(10,2)` | não | Entra no confronto RN-002 |
| `criado_em` | `DATETIME` | não | — |

**Exemplo:**
| id | ri_id | descricao_item | quantidade | valor_unitario |
|---|---|---|---|---|
| 1 | 1 | Roteador Wi-Fi 6 | 2 | 350.00 |

### `ri_item_ixc` (2º lado — IXC)
Mesma estrutura de `ri_item_eace`, para o lado IXC (RF-03), mais 1 campo
próprio. Entra nos dois confrontos: contra o 1º lado (RN-002, informal) e
contra o 3º lado (RN-003, formal — divergência aparece destacada do lado
deste, o IXC). Único dos 3 lados editável/excluível pelo pós-venda
(RN-004).

| Campo | Tipo | Nulo | Descrição |
|---|---|---|---|
| `eh_kit` | `BOOLEAN` | não | Default `false`. Marca o item como o "KIT Instalado" (RN-011), não produto avulso — usado na planilha de faturamento (RN-013, aba fixa "NF KIT") e no limite de 1 KIT por RI (RN-015) |

**Exemplo (com divergência de quantidade em relação ao item acima):**
| id | ri_id | descricao_item | quantidade | valor_unitario | eh_kit |
|---|---|---|---|---|---|
| 1 | 1 | Roteador Wi-Fi 6 | 1 | 350.00 | false |

### `ri_item_relatorio_eace` (3º lado — Relatório EACE, novo, 2026-08-22)
Itens do relatório baixado no portal da EACE **depois da instalação**.
Mesma estrutura de `ri_item_eace`/`ri_item_ixc`. Nunca editado pelo
pós-venda — correção só via um relatório novo/atualizado da própria EACE
(RN-003). Confrontado contra `ri_item_ixc` na RN-003 (formal, sem
tolerância, bloqueia a transição do RI enquanto aberto). Ainda não
implementado — ver `checklist.md`, FEAT-004/FEAT-005.

| Campo | Tipo | Nulo | Descrição |
|---|---|---|---|
| `id` | `BIGINT` | não | Chave primária |
| `ri_id` | `BIGINT` (FK `ri.id`) | não | — |
| `descricao_item` | `VARCHAR(255)` | não | Não entra no confronto; usada como chave de casamento com `ri_item_ixc` — mesma pendência do 1º lado |
| `quantidade` | `INT` | não | Entra no confronto RN-003 |
| `valor_unitario` | `DECIMAL(10,2)` | não | Entra no confronto RN-003 |
| `criado_em` | `DATETIME` | não | — |

**Exemplo (com divergência formal em relação ao item do IXC acima):**
| id | ri_id | descricao_item | quantidade | valor_unitario |
|---|---|---|---|---|
| 1 | 1 | Roteador Wi-Fi 6 | 2 | 350.00 |

### `ri_divergencia`
Catálogo de divergências formais (bloqueiam) e alertas informais. **O `tipo`
abaixo foi confirmado pelo cliente em 2026-08-21 (P-03,
`requisitos.md`/"PROCESSO do Projeto") — pode ser ajustado ao longo do
projeto se necessário, mas vale para a v1 a partir de agora.**

| Campo | Tipo | Nulo | Descrição |
|---|---|---|---|
| `id` | `BIGINT` | não | Chave primária |
| `ri_id` | `BIGINT` (FK `ri.id`) | não | — |
| `tipo` | `ENUM('valor','quantidade','kit_relatorio','nf_financeiro')` | não | Confirmado (P-03, 2026-08-21) |
| `bloqueia` | `BOOLEAN` | não | `true` para os 4 tipos acima (RF-04/RF-09) |
| `descricao` | `TEXT` | sim | Detalhe legível da divergência |
| `resolvida_em` | `DATETIME` | sim | — |
| `criado_em` | `DATETIME` | não | — |

**Exemplo (confronto RN-003, 3º lado × 2º lado):**
| id | ri_id | tipo | bloqueia | descricao |
|---|---|---|---|---|
| 1 | 5 | quantidade | true | Item "Roteador Wi-Fi 6": Relatório EACE = 2, IXC = 1 |

### `documento`
Nota Fiscal (PDF) e XML recebidos do financeiro (RF-08, ITEM 5/7).

| Campo | Tipo | Nulo | Descrição |
|---|---|---|---|
| `id` | `BIGINT` | não | Chave primária |
| `ri_id` | `BIGINT` (FK `ri.id`) | não | — |
| `tipo` | `ENUM('nota_fiscal_pdf','xml')` | não | — |
| `caminho_arquivo` | `VARCHAR(500)` | não | Armazenamento interno (decisão do Dev) |
| `versao` | `INT` | não | Default `1`; incrementa se a NF for substituída (ITEM 5) |
| `ativo` | `BOOLEAN` | não | `true` só na versão vigente |
| `recebido_em` | `DATETIME` | não | — |
| `criado_em` | `DATETIME` | não | — |

**Exemplo:**
| id | ri_id | tipo | caminho_arquivo | versao | ativo |
|---|---|---|---|---|---|
| 1 | 1 | nota_fiscal_pdf | /documentos/ri_1/nf_v1.pdf | 1 | true |

### `email_financeiro_log`
Histórico de envio/recebimento com o financeiro (RF-07/RF-08).

| Campo | Tipo | Nulo | Descrição |
|---|---|---|---|
| `id` | `BIGINT` | não | Chave primária |
| `ri_id` | `BIGINT` (FK `ri.id`) | não | — |
| `direcao` | `ENUM('enviado','recebido')` | não | — |
| `remetente` | `VARCHAR(255)` | não | `posvendas@megainfraestrutura.com.br` no envio |
| `destinatarios` | `TEXT` | sim | Para/Cc (RF-07); nulo quando `direcao='recebido'` |
| `assunto` | `VARCHAR(255)` | sim | — |
| `anexo_pdf` | `VARCHAR(500)` | sim | Caminho do PDF gerado (RF-17) |
| `status_leitura` | `ENUM('ok','fora_do_padrao')` | sim | Só para `direcao='recebido'` (RF-08) |
| `data_hora` | `DATETIME` | não | — |

**Exemplo:**
| id | ri_id | direcao | remetente | destinatarios | data_hora |
|---|---|---|---|---|---|
| 1 | 1 | enviado | posvendas@megainfraestrutura.com.br | Para: hilber.lustosa@speedcsc.com.br, financeiro@speedcsc.com.br; Cc: logistica-l@speedcsc.com.br, posvendas@megainfraestrutura.com.br, david.alves@speedcsc.com.br | 2026-08-29 14:05:00 |

### `ri_historico`
Linha do tempo de comunicação por RI (RN-008) — mensagem, anexo, e-mail e
log automático de mudança de status/campo. Reaproveita o modelo de
`RegistroHistorico` do `modulo-posVenda` (lá RN-029/041), adaptado para FK
direta a `ri` em vez de `GenericForeignKey` — só RI existe hoje; RE ganha
tabela própria quando a v3 for planejada.

| Campo | Tipo | Nulo | Descrição |
|---|---|---|---|
| `id` | `BIGINT` | não | Chave primária |
| `ri_id` | `BIGINT` (FK `ri.id`) | não | — |
| `usuario_id` | `BIGINT` (FK `usuario.id`) | sim | Nulo em log automático do sistema |
| `tipo` | `ENUM('comentario','anexo','sistema')` | não | Mensagem escrita, anexo isolado ou log automático (status/campo, e-mail enviado/recebido) |
| `acao` | `TEXT` | sim | Mensagem livre (comentário) ou descrição do log automático |
| `rotulo` | `VARCHAR(100)` | sim | Nome do campo/status alterado, só em `tipo='sistema'` |
| `valor_anterior` / `valor_novo` | `TEXT` | sim | Só em `tipo='sistema'` |
| `arquivo` | `VARCHAR(500)` | sim | Caminho do anexo, quando houver |
| `criado_em` | `DATETIME` | não | — |

**Exemplo:**
| id | ri_id | usuario_id | tipo | acao | rotulo | valor_anterior | valor_novo |
|---|---|---|---|---|---|---|---|
| 1 | 1 | 2 | sistema | — | status | andamento | envio_email_faturamento |
| 2 | 1 | 2 | comentario | Aguardando confirmação do parceiro no local. | — | — | — |

### `auditoria`
Reaproveitada do `modulo-posVenda`; hoje só cobre login. A estrutura abaixo
já assume a extensão para alteração de campo/status (gap — decisão do Dev,
ver `architecture.md`).

| Campo | Tipo | Nulo | Descrição |
|---|---|---|---|
| `id` | `BIGINT` | não | Chave primária |
| `usuario_id` | `BIGINT` (FK `usuario.id`) | sim | Nulo em ações automáticas do sistema |
| `acao` | `VARCHAR(50)` | não | `login`, `alteracao_campo`, `transicao_status`, `envio_email`, `recebimento_email`, `erro` |
| `entidade` | `VARCHAR(50)` | sim | Ex.: `ri` |
| `entidade_id` | `BIGINT` | sim | — |
| `campo` | `VARCHAR(100)` | sim | Nome do campo alterado |
| `valor_anterior` / `valor_novo` | `TEXT` | sim | — |
| `ip_origem` | `VARCHAR(45)` | sim | — |
| `criado_em` | `DATETIME` | não | — |

**Exemplo:**
| id | usuario_id | acao | entidade | entidade_id | campo | valor_anterior | valor_novo |
|---|---|---|---|---|---|---|---|
| 1 | 2 | transicao_status | ri | 1 | status | andamento | envio_email_faturamento |

## Pendências desta modelagem

- **Critério de casamento entre os itens dos lados** (`ri_item_eace` ×
  `ri_item_ixc`, RN-002; `ri_item_relatorio_eace` × `ri_item_ixc`, RN-003):
  assumido aqui como `descricao_item` igual. O próprio `requisitos.md`
  (ITEM 4) registra isso como não confirmado — a descrição pode variar de
  texto sem ser tratado como erro, então o casamento por texto exato pode
  não ser ideal. Decisão técnica a confirmar antes de implementar os
  confrontos.
- **Nome de `ri_item_eace`:** esclarecido em 2026-08-22 que essa tabela é
  o 1º lado ("Kit declarado"), não "o relatório" (esse é o novo
  `ri_item_relatorio_eace`, 3º lado). O nome atual ficou desalinhado do
  significado; renomear ou não é decisão técnica reversível do Dev.
- **`ri_item_relatorio_eace` (3º lado):** verificado em 2026-08-22 — model,
  migration e formulário de lançamento já existem no código (`apps/ri`);
  pendência anterior removida. Fora do escopo desta verificação: se
  `checklist.md` (FEAT-004/FEAT-006) já foi atualizado com essa entrega é
  responsabilidade de quem a fez, não deste registro.
- **Diagrama derivado:** regenerado em 2026-08-22 junto com a criação de
  `ri_historico` (ver Histórico de Alterações) — inclui agora os 3 lados
  do RI e a nova tabela.
- **Extensão da auditoria** para `alteracao_campo`/`transicao_status`: gap
  já registrado em `architecture.md`, decisão de implementação do Dev.
- **`ri_historico`:** nome de campo/tabela é decisão técnica reversível do
  Dev na implementação (mesmo critério já usado para `auditoria`) — a
  estrutura acima é o ponto de partida, não uma definição fechada.
- **`kit_padrao` (catálogo LPU):** evoluído e entregue pelo Dev na
  FEAT-015 (2026-08-24) — `lote`, `unidade`, `valor_equipamento` e
  `valor_servico` já implementados, com comando de importação a partir
  da aba `LPU` de `CONSOLIDADO EACE.xlsx`. **Decidido:**
  `ri_item_eace.valor_unitario` continua único, não discrimina
  Equipamento/Serviço como o catálogo (RN-010). Pendência residual: não
  existe ainda código que crie `ri_item_eace` automaticamente a partir
  do catálogo — fica para uma feature futura.
- **RE (instalação de link):** fora desta modelagem. Quando a v3 entrar em
  planejamento, provavelmente espelha `ri`/`ri_item_*`/`ri_historico` em
  tabelas próprias (`re`, `re_item_*`, `re_historico`), reaproveitando a
  mesma separação que já existe hoje no `modulo-posVenda` original entre
  subatividades RE/RI.

## Histórico de Alterações
| Data | Alteração | Motivo |
|---|---|---|
| 2026-08-26 | Documentados campos que faltavam: `ri.data_ativacao`/`municipio_ixc`/`estado_ixc`/`observacoes_envio_financeiro`/`dados_financeiro_confirmados_em`; `kit_padrao.descricao_curta`/`numero_access_points`/`aba_planilha_financeiro`; `ri_item_ixc.eh_kit` | Orquestrador identificou, ao consolidar a documentação de FEAT-017/FEAT-018 (RN-013/RN-014/RN-015), que vários campos já existentes no código desde FEAT-004/FEAT-011/FEAT-015/FEAT-016/FEAT-017/FEAT-018 nunca tinham sido sincronizados aqui; `modelo-dados-diagrama.html`/`.pdf` ainda não regenerados — pendência separada |
| 2026-08-24 | Pendência sobre `ri_item_eace.valor_unitario` removida | Usuário decidiu manter valor único, sem discriminar Equipamento/Serviço (RN-010) |
| 2026-08-24 | Tabela `kit_padrao` detalhada (lote, unidade, valor de equipamento e de serviço separados), com chave de negócio (`descricao`, `lote`); relação com `escola` registrada no diagrama de resumo | Usuário indicou a aba `LPU` de `CONSOLIDADO EACE.xlsx` como origem dos valores fixos do Kit por produto/lote e pediu integração com o kit já guardado por escola; gera FEAT-015 |
| 2026-08-22 | Nova tabela `ri_historico`; diagrama regenerado (agora com os 3 lados do RI e `ri_historico`); pendência de `ri_item_relatorio_eace` removida (já implementado no código) | Usuário pediu para trazer do `modulo-posVenda` o histórico de mensagem/anexo/e-mail e log de status/campo (RN-008, `business_rules.md`) |
| 2026-08-20 | Criação do documento | Usuário pediu a modelagem de banco de dados do sistema |
| 2026-08-21 | `ri.status` ganha o 8º valor `correcao_mega` | Acompanha a ampliação do RN-001 em `business_rules.md` (novo status "Correção MEGA") |
| 2026-08-21 | `escola` ganha `lote`, `estado`, `municipio`, `status_conexao`, `data_instalacao_re`, `data_instalacao_ri` | Usuário respondeu a pendência de campos adicionais de Escola (requisitos.md, ITEM 11); nova regra RN-007 em `business_rules.md` |
| 2026-08-21 | `ri_divergencia.tipo` confirmado (deixa de ser proposta) | Cliente validou o catálogo P-03 (`valor`, `quantidade`, `kit_relatorio`, `nf_financeiro`); pendência removida desta modelagem |
| 2026-08-22 | RI passa de 2 para 3 lados: `ri_item_eace` reclassificada como 1º lado ("Kit declarado"); nova tabela `ri_item_relatorio_eace` (3º lado, "Relatório EACE", ainda não implementada) | Usuário esclareceu que o model já implementado não era "o relatório" — RN-002/RN-003 reescritas em `business_rules.md`; diagrama derivado (`.html`/`.pdf`) fica pendente de regeneração |
