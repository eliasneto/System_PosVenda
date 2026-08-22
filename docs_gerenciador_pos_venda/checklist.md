# Checklist — Gerenciador Pós-Venda (v1 · Faturamento EACE por INEP)
_Última atualização: 2026-08-22_

> **Versão-alvo:** 1.0.0. **Nome exibido no menu do sistema:** "Gerenciador
> Pós Venda" (sem hífen) — ver `architecture.md`, "Identidade do Sistema e
> Versionamento".

> **Regra permanente:** toda alteração em `modelo-dados.md` ou em
> `requisitos.md` atualiza, no mesmo turno, os documentos derivados
> correspondentes — `modelo-dados-diagrama.html`/`.pdf` e
> `requisitos-validacao-cliente.html`/`.pdf`. Não é uma tarefa "quando
> solicitada" (ver `.claude/agents/orquestrador.md`, "Documentos derivados").

> Cobre somente a **v1** (processo **RI**, prazo **28/08/2026**). RE e os
> RPAs do Hub de Integrações ficam para as versões 2 (04/09/2026) e 3
> (10/09/2026) — ver `architecture.md` — e entram neste checklist quando
> essas versões forem planejadas. Toda feature aqui referencia `RF-XX`
> (`requisitos-validacao-cliente.html`), `RN-XXX` (`business_rules.md`) e o
> item correspondente em `requisitos.md`.

## Legenda de status
`⬜ Pendente` → `🔄 Em andamento` → `🔍 Aguardando QA` → `✅ Concluída`
(reprovação: `🔍 → 🔧 Correção pendente → 🔄`)

## Ordem sugerida (dependências)
FEAT-001 → (FEAT-002, FEAT-003) → FEAT-004 → FEAT-005 → FEAT-006 →
FEAT-007 → FEAT-008 → FEAT-009 → FEAT-010. FEAT-011 (auditoria) é
transversal e pode evoluir em paralelo a partir de FEAT-001.

---

### FEAT-001 — Base do projeto novo
**Descrição:** Repositório e banco próprios deste sistema, a partir da
cópia seletiva do código do `modulo-posVenda` (frontend, e-mail, permissão),
sem os módulos listados como lixo em `docs_gerenciador_pos_venda/lixo.md`.
**Tipo:** backend-only
**Status:** 🔍 Aguardando QA
**Prioridade:** Alta
**Critérios de aceite:**
- Projeto sobe localmente com frontend base, envio/leitura de e-mail e
  sistema de permissão reaproveitados.
- Módulos listados como "lixo confirmado" (`lixo.md`) não estão presentes.
- Banco próprio criado, com as tabelas de `modelo-dados.md` migradas.
- `docs/` do `modulo-posVenda` original permanece intacto — não é copiado
  nem alterado.
**Regras relacionadas:** —
**Dependências:** nenhuma.
**Tipo de validação:** QA (QA-001), critérios técnicos de setup.
**Entrega do Dev:**
- Repositório novo criado em `https://github.com/eliasneto/Sistema_posvenda`
  (privado), projeto Django com apps `core` (User + `perfil`, RN-004),
  `escolas` (Escola + campos novos, RN-007), `ri` (RI e itens/divergência/
  documento/e-mail) e `auditoria`, conforme `modelo-dados.md`.
- Reaproveitados do `modulo-posVenda`: User/UserManager, `has_group`, casca
  visual do `base.html`/`login.html` (adaptada à marca "Gerenciador Pós
  Venda"); nenhum módulo listado em `lixo.md` foi copiado.
- Banco local SQLite (`db.sqlite3`, decisão reversível — MySQL disponível
  via `DB_ENGINE=mysql` no `.env`); migrações aplicadas com sucesso.
- Fluxo de login testado de ponta a ponta (login → dashboard placeholder →
  logout) com usuário administrador de teste.
- `docs/` do `modulo-posVenda` original não foi tocado.
- **Pendência:** nenhuma.
**Pendência atual (resolvida em 2026-08-21):** a decisão de banco mudou
para MySQL obrigatório também em local (ver `architecture.md`, "Banco de
Dados") — `config/settings.py` (`DB_ENGINE` default) e `.env.example`
ajustados pelo Dev; usuário `admin`/`admin` recriado no MySQL local para
teste (banco trocado, dado antigo do SQLite não migra automaticamente).
**Resolvida em 2026-08-22 (Dev):** os 3 logos (howBE, speed, LK Tecnologia)
foram copiados de `static/img/` do `modulo-posVenda` para o
`static/img/` do `Sistema_posvenda` (`logo3.png` já com o fundo vermelho
corrigido) e o `login.html`/`base.html` de lá foram ajustados para exibi-
los. Validado com screenshot real da tela de login e do dashboard
autenticado — os 3 logos aparecem corretamente, sem ícone quebrado.
**Commitado e enviado ao GitHub** (`9cbdbba`, branch `main`) — não ficou
só no checkout local, para não repetir a perda do FEAT-012/FEAT-002.
**Reaberta em 2026-08-22:** usuário confirmou com print que o autofill
persistia mesmo com `autocomplete="off"` (Chrome/Edge ignoram esse valor
de propósito em formulário de login).
**Resolvida em 2026-08-22 (Dev, 2ª tentativa):** adicionados campos-isca
escondidos (`fake_username`/`fake_password`, fora da tela) antes dos
campos reais, para o navegador "gastar" o autofill de credencial salva
neles; campo Senha real passou a usar `autocomplete="new-password"`
(token que o Chrome respeita de fato). Validado com screenshot real
(Edge headless, desktop 1366px): campos abrem vazios, sem quebra de
layout; HTML servido conferido via `curl`. **Ressalva:** o ambiente de
teste (Edge headless) não tem a senha salva do usuário, então não
reproduz o autofill original — pedido ao usuário confirmar no navegador
real (com recarregamento forçado, Ctrl+F5) se o preenchimento
automático parou.

---

### FEAT-002 — Escolas: migração inicial e status de conexão
**Descrição:** Importar os dados de `Escola` (2.622 INEPs) para o banco
novo, com os campos adicionais (`lote`, `estado`, `municipio`) e o status
de conexão (RN-007).
**Tipo:** backend-only
**Status:** 🔍 Aguardando QA
**Prioridade:** Alta
**Critérios de aceite:**
- Todos os INEPs existentes no `modulo-posVenda` migrados antes do sistema
  entrar em uso; INEP tratado como texto de 8 dígitos.
- Cadastro de INEP fora da migração é rejeitado — sem cadastro manual de
  escola nesta versão.
- Campos `lote`, `estado`, `municipio` migrados/preenchidos.
- Escola nasce com `status_conexao = desconectado`; muda para
  `parcialmente_conectado` ou `conectado` conforme RN-007 ao preencher as
  datas de instalação (RE/RI).
**Regras relacionadas:** RN-007, RF-01.
**Dependências:** FEAT-001.
**Tipo de validação:** QA (QA-002).
**Fonte de dados de migração:** planilha `CONSOLIDADO EACE.xlsx` (raiz do
`modulo-posVenda`), aba `FATURAMENTO MATERIAIS` — 2.622 INEPs únicos, sem
duplicidade, campos completos (`LOTE`, `UF`, `MUNICIPIO`, `INEP`, `UNIDADE
ESCOLAR`, `ENDEREÇO`, `KIT WIFI ESTIMADO`, `VELOCIDADE`); conferida contra as
abas `FATURAMENTO BDO`/`FATURAMENTO MIP`, que trazem os mesmos 2.622 INEPs
sem divergência de valor. Nenhum INEP duplicado encontrado. Datas de
instalação RE/RI não vêm da planilha — RN-007 já define preenchimento manual
posterior via chamado IXC.
**Entrega do Dev:**
- Recriado o comando `importar_escolas_planilha` (lê `CONSOLIDADO EACE.xlsx`,
  aba `FATURAMENTO MATERIAIS`).
- Mapeia LOTE/UF/MUNICIPIO/INEP/UNIDADE ESCOLAR/ENDEREÇO/VELOCIDADE/KIT WIFI
  ESTIMADO para os campos de `Escola`.
- INEP tratado como texto de 8 dígitos; reimportação não duplica nem
  sobrescreve escola já existente (testado).
- Criados 10 testes automatizados cobrindo a importação e a RN-007; todos
  passando.
- Rodado contra o banco real: 0 criada(s), 2.622 já existente(s) — reproduz
  exatamente a migração já feita.
- **Pendência:** nenhuma.
**Resolvida em 2026-08-22 (Dev):** reaberta pelo DevOps porque o script e os
testes da migração original não existiam no repositório (só o dado no
banco). Comando e testes recriados a partir da mesma fonte
(`CONSOLIDADO EACE.xlsx`, aba `FATURAMENTO MATERIAIS`) e confirmados contra
o banco ao vivo: resultado idêntico ao já registrado (2.622 escolas, 0
divergência). `openpyxl` adicionado ao `requirements.txt`; a planilha de
origem foi incluída no `.gitignore` do `Sistema_posvenda` (dado de negócio,
não deve ser versionado).
**Reexecutada em 2026-08-22 (Dev, a pedido do usuário):** `importar_escolas_planilha`
rodado de novo contra o `CONSOLIDADO EACE.xlsx` que o usuário colocou na raiz
do repositório — banco já tinha as 2.622 escolas; resultado: `0 criada(s),
2622 já existente(s), 0 linha(s) inválida(s)`. Confirma que a planilha atual
não traz INEP novo nem diverge do que já está migrado.

---

### FEAT-003 — Usuários e permissões
**Descrição:** Cadastro de usuário com dois perfis fixos (Administrador e
Analista) e as regras de permissão da RN-004.
**Tipo:** fullstack
**Status:** ⬜ Pendente
**Prioridade:** Alta
**Critérios de aceite:**
- Administrador cria/edita/desativa usuário; Analista não acessa essa tela.
- Analista realiza CRUD de INEP/item e documentos, exceto exclusão.
- Tentativa de exclusão por Analista é bloqueada em qualquer tela onde
  exclusão exista.
**Regras relacionadas:** RN-004, RF-13.
**Dependências:** FEAT-001.
**Tipo de validação:** QA (QA-003) — inclui teste de permissão.
**Entrega do Dev:** nenhuma ainda.
**Pendência atual:** nenhuma.

---

### FEAT-004 — Cadastro manual de RI e itens (3 lados: Kit declarado, IXC, Relatório EACE)
**Descrição:** Formulários para digitar manualmente, por INEP, os itens dos
**3 lados** do RI (esclarecido em 2026-08-22 — antes documentado como só
2): **Kit declarado** (dado da EACE antes do projeto), **IXC** (chamado do
atendimento) e **Relatório EACE** (baixado depois da instalação) — mesma
granularidade nos três (item, quantidade, valor unitário).
**Tipo:** fullstack
**Status:** 🔍 Aguardando QA
**Prioridade:** Alta
**Critérios de aceite:**
- RI nasce vinculado a um INEP já existente, status inicial "Implantação
  EACE".
- Cada um dos 3 lados (Kit declarado, IXC, Relatório EACE) aceita
  múltiplos itens por INEP (1:N).
- Campo "Descrição do Item" é texto livre, sem validação de formato, nos
  3 lados.
- Kit declarado e Relatório EACE não são editáveis depois de criados,
  exceto por um novo lançamento (RN-002/RN-003) — só o lado IXC aceita
  editar/excluir item.
**Regras relacionadas:** RN-002, RN-003, RN-004, RF-02, RF-03.
**Dependências:** FEAT-002, FEAT-003 — **exceção autorizada explicitamente
pelo usuário em 2026-08-22** para iniciar fora de ordem (mesmo precedente da
FEAT-002/FEAT-007). FEAT-002 segue `🔍 Aguardando QA`; FEAT-003 (cadastro de
usuário) segue `⬜ Pendente` — a distinção Administrador/Analista da RN-004
já existe desde a FEAT-001 (`user.is_administrador`) e foi usada para a
regra de exclusão, mas não há tela de cadastro/gestão de usuário.
**Tipo de validação:** QA (QA-004).
**Entrega do Dev (2026-08-22):**
- Modelos (`Ri`, `RiItemEace`, `RiItemIxc`) já existiam desde a FEAT-001;
  criados `apps/ri/forms.py` e as views/rotas de cadastro (`ri_detail`,
  `ri_iniciar`, `ri_item_ixc_update`, `ri_item_ixc_delete`).
- Tela `ri/ri_detail.html` (acessível a partir do grid da FEAT-007): sem RI,
  oferece "Iniciar RI" (status inicial "Implantação EACE"); com RI, dois
  painéis — Lado EACE (só permite lançar item novo, sem editar/excluir,
  RN-003) e Lado IXC (lança, edita e exclui item).
- RN-004 aplicada: exclusão de item IXC só para Administrador (403 para
  Analista); criação/edição para os dois perfis.
- 11 testes automatizados (`apps/ri/tests.py`): login obrigatório, tela sem
  RI, criação do RI (status e não duplicação), múltiplos itens EACE,
  descrição livre com caracteres especiais, ausência de rota de
  edição/exclusão do lado EACE, lançar/editar/excluir item IXC, permissão
  de exclusão por perfil. Suíte completa do repositório (30 testes)
  passando.
- Corrigido durante a validação visual: campo de valor unitário do
  formulário de edição do IXC vinha com vírgula (formatação pt-br) dentro
  de um `<input type="number">`, que o navegador rejeita e mostra em
  branco — ajustado para usar ponto; teste de regressão adicionado.
- Validação visual em navegador (Playwright) contra o app real em Docker,
  autenticado, em 1366px e 390px: fluxo completo (iniciar RI, lançar item
  EACE, lançar/editar/excluir item IXC) sem quebra de layout e sem erro de
  console.
**Entrega do Dev (2026-08-22) — 3º lado (Relatório EACE):**
- Model novo `RiItemRelatorioEace` (mesma estrutura de `RiItemEace`/
  `RiItemIxc`); migration aplicada. Mantido o nome `RiItemEace` para o 1º
  lado (decisão técnica reversível, CLAUDE.md §9) — docstrings/`verbose_name`
  de todos os 3 models atualizados para deixar claro qual lado cada um é.
- `RiItemRelatorioEaceForm` (`apps/ri/forms.py`); `ri_detail_view` ganha o
  3º painel (só lançar, sem editar/excluir — mesma regra do 1º lado);
  `grid_inep_view` e o drill-down do grid (FEAT-007) atualizados para
  prefetch/mostrar os 3 lados lado a lado.
- 4 testes novos (lançar múltiplos itens, ausência de rota de edição/
  exclusão do 3º lado, drill-down mostra os 3); suíte completa do
  repositório (42 testes) passando.
- Validação visual em navegador (Playwright), 1366px e 390px: os 3
  painéis na tela de cadastro e os 3 cards no drill-down do grid, sem
  quebra de layout, sem erro de console.
**Pendência atual:** tela formal de cadastro/gestão de usuário (FEAT-003)
continua não implementada — pendência já registrada antes, sem relação
com o 3º lado. Confronto (FEAT-005) e sua exibição de divergências
(amarelo/vermelho) ainda não implementados — depende só desta feature,
que agora está completa.

---

### FEAT-005 — Confronto de divergências (2 confrontos: RN-002 e RN-003)
**Descrição:** Esclarecido em 2026-08-22 que são **dois confrontos**, não
um: (1) Kit declarado × IXC — informal, destaque amarelo, não bloqueia
(RN-002); (2) Relatório EACE × IXC — formal, sem tolerância, destaque
vermelho do lado do IXC, bloqueia (RN-003). Ambos item a item, mesma
mecânica (quantidade e valor unitário).
**Tipo:** fullstack
**Status:** ⬜ Pendente
**Prioridade:** Alta
**Critérios de aceite:**
- Confronto 1 (Kit declarado × IXC, RN-002): diferença de quantidade ou
  valor unitário em qualquer item = destaque amarelo no campo divergente;
  nunca bloqueia nenhuma transição.
- Confronto 2 (Relatório EACE × IXC, RN-003): diferença de quantidade ou
  valor unitário em qualquer item = divergência formal, destacada em
  vermelho do lado do item do IXC; bloqueia a transição do RI enquanto
  aberta (RN-001).
- Comparação estrita nos dois confrontos — acentuação, espaço e caixa
  contam como divergência.
- Campo "Descrição do Item" não entra no confronto de valor/quantidade em
  nenhum dos dois — só como referência de casamento entre os itens.
- INEP com divergência formal aberta (confronto 2) aparece destacado
  (fundo vermelho) no grid (FEAT-007).
**Regras relacionadas:** RN-002, RN-003, RF-04, RF-06.
**Dependências:** FEAT-004 (precisa do 3º lado, "Relatório EACE",
implementado — hoje `🔄 Em andamento`).
**Tipo de validação:** QA (QA-005).
**Entrega do Dev:** nenhuma ainda.
**Pendência atual:** catálogo fechado dos tipos de divergência formal
confirmado pelo cliente em 2026-08-21 (P-03, RN-003) — sem pendência nesse
ponto. Resta o critério de casamento entre itens dos lados, ainda não
confirmado; implementar as duas comparações de quantidade/valor com o
catálogo de `tipo` já fechado. Depende do 3º lado da FEAT-004 existir
antes de poder implementar o confronto 2.

---

### FEAT-006 — Ciclo de vida do RI (máquina de status)
**Descrição:** Os 8 status do RI (RN-001), incluindo o desvio manual
"Correção MEGA" e o bloqueio de transição enquanto houver divergência
aberta.
**Tipo:** fullstack
**Status:** 🔄 Em andamento
**Prioridade:** Alta
**Critérios de aceite:**
- RI só avança de "Andamento" para "Envio de Email para faturamento" sem
  divergência de quantidade/valor aberta (FEAT-005).
- Analista ou Administrador marcam "Correção MEGA" só a partir de
  "Andamento"; retorno só manual, só para "Andamento".
- Ao entrar em "Envio de Email para faturamento", campos do lado IXC com
  KIT divergente do declarado ficam destacados em amarelo (RN-002), sem
  bloquear a transição.
- Transições automáticas (envio de e-mail confirmado; resposta na caixa de
  entrada) mudam o status sem ação manual do usuário.
**Regras relacionadas:** RN-001, RN-002, RN-003, RF-14, RF-15.
**Dependências:** FEAT-004, FEAT-005 — **exceção autorizada explicitamente
pelo usuário em 2026-08-22** para iniciar a parte manual fora de ordem
(mesmo precedente da FEAT-002/004/007), mesmo com a FEAT-005 (confronto)
ainda `⬜ Pendente`.
**Tipo de validação:** QA (QA-006).
**Entrega do Dev (2026-08-22, parcial):**
- Campo de status do RI editável direto no drill-down do grid (FEAT-007),
  só com os status "trocados pelo usuário" (RN-001): Andamento, Envio de
  Email para faturamento, Aguardando validação EACE, Faturamento
  Concluído, Correção MEGA. Os automáticos (Aguardando financeiro,
  Aguardando Anexo portal EACE) e o inicial (Implantação EACE) não
  aparecem como opção.
- Regras aplicadas: "Correção MEGA" só a partir de "Andamento" e só volta
  para "Andamento"; "Andamento" → "Envio de Email para faturamento"
  bloqueado se houver divergência aberta que bloqueia (RN-003).
- 8 testes automatizados cobrindo login, transição permitida, bloqueio de
  status automático, as duas regras de "Correção MEGA" e o bloqueio/
  liberação por divergência. Suíte completa do repositório (40 testes)
  passando.
- Validação visual em navegador (Playwright), 1366px — sem erro de
  console.
**Pendência atual:** ainda faltam, para fechar a feature: destaque amarelo
de KIT divergente (RN-002) ao entrar em "Envio de Email para faturamento";
transições automáticas por e-mail (dependem da FEAT-008/009, envio e
leitura de e-mail com o financeiro, ainda não implementadas); e o
confronto automático de divergências em si (FEAT-005 continua `⬜
Pendente` — hoje as divergências só existem se forem criadas manualmente,
ex.: admin/testes).

---

### FEAT-007 — Grid de INEPs com drill-down
**Descrição:** Grid principal com 6 colunas — INEP, Nome da escola,
Endereço, Status de conexão, Status do RI, Responsável — com filtro e
detalhe dos itens por INEP. Status de conexão é atributo do próprio
INEP/Escola (RF-20); Status do RI e Responsável são atributos do RI
(RN-001/RF-05) — o INEP/Escola não tem campo próprio de status de
faturamento nem de responsável. As duas colunas de status ficam lado a
lado na linha, nenhuma "dentro" da outra.
**Tipo:** frontend-functional
**Status:** 🔍 Aguardando QA
**Prioridade:** Alta
**Critérios de aceite:**
- Uma linha do grid por INEP; botão de detalhe abre os itens (EACE e IXC)
  daquele INEP.
- Coluna e filtro "Status de conexão" (Escola, RF-20: desconectado/
  parcialmente conectado/conectado) visíveis direto na linha, sem precisar
  abrir o drill-down.
- Coluna e filtro "Status do RI" (RN-001) e coluna "Responsável" (do RI),
  também visíveis direto na linha (grid único de itens, não separado por
  tipo de validação).
- INEP com divergência aberta aparece com fundo vermelho (RN-003).
- Item de menu reorganizado em hierarquia: aba "Projeto" > "EACE" > grid
  (hoje item plano "Grid de INEPs" em `core/base.html`); ver
  `architecture.md`, "Estrutura de navegação (menu lateral)". Só
  navegação/UI — sem mudança de view, URL, template ou lógica do grid.
**Regras relacionadas:** RN-003, RF-05, RF-06.
**Dependências:** FEAT-004, FEAT-006 — **exceção autorizada explicitamente
pelo usuário em 2026-08-22** para iniciar fora de ordem (mesmo precedente
da FEAT-002), já que o modelo `Ri`/`RiItemEace`/`RiItemIxc`/`RiDivergencia`
já existia desde a FEAT-001. Consequência: hoje não há tela de cadastro
manual de RI (FEAT-004), então o grid real mostra "Sem RI" em todo INEP até
essa feature existir — comportamento esperado, não é bug.
**Tipo de validação:** QA (QA-007).
**Entrega do Dev (2026-08-22):**
- Grid real implementado — `apps/ri/views.py` (`grid_inep_view`),
  `apps/ri/urls.py`, `apps/ri/templates/ri/grid_inep.html` — e item de menu
  "Grid de INEPs" adicionado em `core/base.html`.
- Frontend trazido da tela "Endereços" do `modulo-posVenda` (referência
  registrada antes em `docs_gerenciador_pos_venda/frontend_reference/`):
  badge de status colorido, linha expansível de drill-down, fundo vermelho
  para divergência aberta, busca, filtro por status, paginação e estado
  vazio. Excluídos os trechos de Parceiro/cotação/Setor, como já decidido.
- Consulta com `prefetch_related` (Escola → RI mais recente → itens/
  divergências) para não gerar N+1.
- 8 testes automatizados (`apps/ri/tests.py`): login obrigatório, caminho
  principal com as 2.622 escolas reais, filtro por status, busca por INEP/
  nome/município/UF, estado vazio, divergência aberta soma no card e marca
  a linha, divergência resolvida não conta, drill-down mostra itens
  EACE/IXC. Suíte completa do repositório (18 testes) passando.
- Validação visual em navegador: executada contra o app real rodando em
  Docker (`docker compose`), autenticado, com os dados reais das 2.622
  escolas — capturada em 1366px e 390px; sidebar, cards e grid consistentes
  com o restante do sistema; sem quebra de layout.
**Pendência:** quando a FEAT-004 existir, o grid passa a mostrar RI de
verdade em vez de "Sem RI" — nenhuma mudança de código esperada, só dado.
**Pendência atual:** nenhuma — isto não iniciou a FEAT-007 (depende de
FEAT-004/FEAT-006, ainda `⬜ Pendente`); é só a referência de frontend.

**Entrega do Dev (2026-08-22) — revertidas as duas correções abaixo, RF-05
confirmado como fonte oficial:** localizado `requisitos-validacao-cliente.html`
(documento de requisitos validado com o cliente, referenciado em
`architecture.md`/`checklist.md` como "requisitos.md"). O RF-05 diz
literalmente: *"grid com uma linha por INEP ... (colunas: INEP, Nome da
escola, Endereço, **Status**, **Responsável**)"* — e a seção 5 do mesmo
documento ("Ciclo de Vida do RI — Status") deixa claro que esse "Status" é
o do RI (RN-001), não o de conexão. O status de conexão da Escola é um
requisito **separado** (RF-20). Ou seja, as duas correções registradas
logo abaixo (tirar Responsável do grid, trocar Status para conexão) foram
na direção contrária ao RF-05 oficial. Revertido:
- `grid_inep_view`/`grid_inep.html`: coluna e filtro "Status" voltam a ser
  o status do RI (`Ri.STATUS_CHOICES`); coluna "Responsável" volta à
  tabela principal — exatamente as 5 colunas do RF-05.
- Status de conexão da Escola (RF-20) passa a aparecer só no drill-down
  ("Status de conexão (RF-20): ...", visível para todo INEP, com ou sem
  RI), não mais como coluna/filtro do grid.
- Testes ajustados de volta ao comportamento do RF-05, mais 1 teste novo
  confirmando que o status de conexão aparece no drill-down; suíte
  completa do repositório (32 testes) passando.
- Validação visual em navegador (Playwright), 1366px e 390px — sem erro de
  console.
- **Pendência para o Orquestrador (nota, ainda em aberto):** confirmar
  se "requisitos.md" (citado em vários pontos deste projeto) já existiu e
  foi perdido — mesmo padrão do incidente já registrado na FEAT-002/
  FEAT-012 — ou se `requisitos-validacao-cliente.html` sempre foi a única
  fonte. Não achei o `.md` em nenhum dos dois repositórios (`Sistema_posvenda`
  e `sgpspeed_pos-venda`); enquanto isso, tratar o `.html` como fonte válida.

**Entrega do Dev (2026-08-22) — Responsável sai do grid, fica dentro do RI
(revertido no item acima):**
- Usuário apontou que "Responsável" é atributo do RI, não do INEP/Escola —
  não deveria ser coluna do grid principal (mesmo princípio já aplicado à
  correção do "Status" logo abaixo).
- `grid_inep.html`: coluna "Responsável" removida da tabela principal;
  passou para dentro do painel de drill-down (linha "Responsável pelo RI",
  visível só quando o INEP já tem RI) — e continua exibido na tela da
  FEAT-004 (`ri_detail`, card "Responsável").
- 1 teste novo confirmando a ausência da coluna no cabeçalho e a presença
  no drill-down; suíte completa do repositório (31 testes) passando.
- Validação visual em navegador (Playwright), 1366px e 390px — sem erro de
  console.
- **Pendência para o Orquestrador (resolvida em 2026-08-22):** "Descrição"
  ajustada para deixar explícito que Status/Responsável são atributos do
  RI, não do INEP/Escola.

**Entrega do Dev (2026-08-22) — correção da coluna/filtro "Status" (RN-007,
revertido no item acima):**
- Usuário apontou que a coluna "Status" do grid estava mostrando o status
  do RI (RN-001: Implantação EACE, Andamento, ...), quando deveria mostrar
  o status de conexão da Escola (RN-007: desconectado/parcialmente
  conectado/conectado). Confirmado diretamente com o usuário (as duas
  regras são catálogos distintos e a arquitetura não deixava explícito
  qual delas o grid deveria usar).
- `grid_inep_view` (`apps/ri/views.py`) e `grid_inep.html`: coluna e filtro
  "Status" agora usam `Escola.status_conexao`/`STATUS_CONEXAO_CHOICES`, não
  mais `Ri.status`. O status do RI continua visível na tela da FEAT-004
  (`ri_detail`, card "Status do RI") e no drill-down do grid.
- 2 testes ajustados para refletir a nova semântica (texto exibido e
  filtro); suíte completa do repositório (30 testes) passando.
- Validação visual em navegador (Playwright), 1366px e 390px, com rolagem
  horizontal conferida na tabela mobile — sem erro de console.
- **Pendência para o Orquestrador (resolvida em 2026-08-22, em sentido
  oposto ao sugerido):** o RF-05 confirma que "Status" do grid é o do RI,
  não o de conexão — ver entrega de reversão logo acima.

**Entrega do Dev (2026-08-22) — Status de conexão vira 6ª coluna do grid:**
- `grid_inep_view`/`grid_inep.html`: coluna e filtro "Conexão" (Escola,
  RF-20) voltam a aparecer direto na linha, ao lado de "Status do RI" e
  "Responsável" — dois filtros de status independentes agora (conexão e
  RI), cada um com seu próprio `<select>`.
- 3 testes ajustados/novos (as 6 colunas presentes, filtro de conexão
  isolado do filtro de RI); suíte completa do repositório (32 testes)
  passando.
- Validação visual em navegador (Playwright), 1366px e 390px — sem erro de
  console.
- **Bônus, a pedido do usuário:** dentro do drill-down, campo "Status do
  RI" ganhou fundo âmbar e botão preto/amarelo (cor de ação principal do
  projeto) para se destacar do resto do painel — só ajuste visual, sem
  lógica.

**Entrega do Dev (2026-08-22) — reorganização do menu (frontend-layout):**
- Menu lateral reorganizado em `core/base.html`: item plano "Grid de INEPs"
  virou grupo recolhível "Projeto" (padrão trazido do `modulo-posVenda`,
  mesma função `toggleSubmenu`) com o subitem "EACE", que leva ao mesmo
  grid da FEAT-007. Nenhuma view, URL, template ou lógica do grid mudou.
- Suíte `apps/ri`/`apps/core` (8 testes) executada dentro do container
  Docker: passou sem alteração de resultado.
- Validação visual em navegador (Playwright) contra o app real em Docker,
  autenticado: grupo "Projeto" fechado e aberto, navegação até o grid via
  "EACE", em 1366px e 390px — sem quebra de layout, sem erro de console.
- Só alteração visual/navegação, sem lógica nova — segue direto para
  validação visual do usuário, sem novo ciclo de QA (CLAUDE.md §3).
**Status desta reorganização:** 👤 Aguardando validação visual do usuário.
A FEAT-007 em si (grid funcional) continua `🔍 Aguardando QA`, sem mudança.

**Pendência (2026-08-22, ligada à reabertura da FEAT-004 — resolvida):** o
drill-down do grid ganhou o 3º card ("Relatório EACE"), junto com "Kit
declarado" e "IXC" — ver entrega do Dev na FEAT-004.

---

### FEAT-008 — Envio de e-mail para o financeiro
**Descrição:** Formulário de dados a enviar, botão de e-mail com PDF
gerado anexado, e transição automática de status ao confirmar envio.
**Tipo:** fullstack
**Status:** ⬜ Pendente
**Prioridade:** Alta
**Critérios de aceite:**
- Formulário só disponível no status "Envio de Email para faturamento"; ao
  salvar, habilita o botão "Enviar e-mail".
- E-mail sai da caixa própria do sistema (`posvendas@megainfraestrutura.com.br`)
  com destinatários fixos — Para: `hilber.lustosa@speedcsc.com.br`,
  `financeiro@speedcsc.com.br`; Cc: `logistica-l@speedcsc.com.br`,
  `posvendas@megainfraestrutura.com.br`, `david.alves@speedcsc.com.br`.
- PDF anexado é gerado com os dados do formulário; os mesmos dados aparecem
  no corpo do e-mail.
- Um e-mail por INEP, um botão de envio por linha — nunca em lote.
- Ao confirmar o envio, o status do RI muda automaticamente para
  "Aguardando financeiro".
**Regras relacionadas:** RN-001, RF-16, RF-17, RF-18.
**Dependências:** FEAT-006, FEAT-007.
**Tipo de validação:** QA (QA-008).
**Entrega do Dev:** nenhuma ainda.
**Pendência atual:** nenhuma.

---

### FEAT-009 — Leitura da resposta do financeiro e segunda validação
**Descrição:** Polling (~5 min) na caixa de entrada, identificação do INEP
pela resposta, anexo de NF+XML e validação contra o que foi solicitado
antes de liberar o próximo passo (RN-005).
**Tipo:** backend-only
**Status:** ⬜ Pendente
**Prioridade:** Alta
**Critérios de aceite:**
- Resposta identificada corretamente ao INEP pelo rastreio do e-mail
  enviado (FEAT-008).
- NF (PDF) e XML ficam disponíveis no INEP; nova resposta substitui a
  versão anterior.
- E-mail fora do padrão (sem 1 PDF + 1 XML, ou sem INEP identificável) não
  bloqueia o fluxo, só gera alerta no log.
- Ao identificar a resposta, o status do RI muda automaticamente para
  "Aguardando Anexo portal EACE".
**Regras relacionadas:** RN-001, RN-005, RF-08, RF-09, RF-19.
**Dependências:** FEAT-008.
**Tipo de validação:** QA (QA-009).
**Entrega do Dev:** nenhuma ainda.
**Pendência atual:** nenhuma — o tipo "NF × financeiro" do catálogo de
divergência (RN-003) foi confirmado pelo cliente em 2026-08-21 (P-03).

---

### FEAT-010 — Anexo manual no portal EACE e conclusão Faturado
**Descrição:** Marcação manual de anexo feito no portal EACE e conclusão
manual como "Faturamento Concluído".
**Tipo:** fullstack
**Status:** ⬜ Pendente
**Prioridade:** Alta
**Critérios de aceite:**
- Botão de marcação "anexo feito no EACE" disponível para Analista e
  Administrador, só no status "Aguardando Anexo portal EACE"; ao marcar,
  status muda para "Aguardando validação EACE".
- Botão de conclusão "Faturamento Concluído" só habilitado depois da
  marcação de anexo.
- Conclusão não dispara notificação, relatório nem fechamento automático
  adicional.
**Regras relacionadas:** RN-001, RN-004, RF-10, RF-11.
**Dependências:** FEAT-009.
**Tipo de validação:** QA (QA-010).
**Entrega do Dev:** nenhuma ainda.
**Pendência atual:** nenhuma.

---

### FEAT-011 — Auditoria estendida
**Descrição:** Estender `apps/auditoria` (reaproveitado) para cobrir
alteração de campo, transição de status, ação manual, envio/recebimento de
e-mail e erros, além do login já existente.
**Tipo:** backend-only
**Status:** ⬜ Pendente
**Prioridade:** Média
**Critérios de aceite:**
- Toda transição de status do RI (FEAT-006) gera registro de auditoria.
- Toda alteração de campo relevante do RI/itens gera registro de
  auditoria.
- Envio e recebimento de e-mail (FEAT-008/FEAT-009) geram registro de
  auditoria.
- Erros do sistema geram registro de auditoria.
- Registros sem prazo de expiração.
**Regras relacionadas:** RN-006, RF-12.
**Dependências:** FEAT-001 (evolui em paralelo às demais a partir daqui).
**Tipo de validação:** QA (QA-011).
**Entrega do Dev:** nenhuma ainda.
**Pendência atual:** nenhuma.

---

### FEAT-012 — Infraestrutura do repositório novo (Docker, CI/CD, deploy)
**Descrição:** Preparar Docker/Compose, pipeline de CI/CD e estratégia de
deploy do repositório novo do Gerenciador Pós-Venda; identificar o que de
`docs/devops/` e da esteira de CI do `modulo-posVenda` não se aplica ao
sistema novo.
**Tipo:** devops
**Status:** 🔄 Em andamento
**Prioridade:** Alta
**Critérios de aceite:**
- Dockerfile/Compose do repositório novo builda e sobe localmente.
- Pipeline de CI configurado para o repositório novo (build + testes).
- Variáveis de ambiente do sistema novo documentadas (sem valores reais).
- Estratégia de deploy definida (mesmo que só para ambiente de homologação
  nesta v1).
- Itens de `docs/devops/` e da esteira de CI do `modulo-posVenda` que não se
  aplicam ao sistema novo identificados e descartados (não copiados).
**Regras relacionadas:** RNF-05.
**Dependências:** FEAT-001 (precisa da estrutura de código do projeto novo).
**Tipo de validação:** critérios técnicos — validação do próprio DevOps, sem
QA-XXX (feature tipo `devops`).
**Entrega do DevOps (registrada em 2026-08-21 — não confirmada no
repositório, ver correção abaixo):** Dockerfile, `docker-compose.yml`/
`.hml.yml`, pipeline `.github/workflows/homolog.yml`,
`scripts/deploy_homolog.sh` e `docs/devops/` foram descritos como criados e
validados (`docker compose up -d --build` funcionando, serviço `db` MySQL
8.0 na porta `3315`, `migrate` limpo, título "Gerenciador Pós Venda"
confirmado).

**Corrigido em 2026-08-22 (DevOps re-clonou o repositório do GitHub):**
nada disso está no `Sistema_posvenda` de verdade — o clone fresco de
`https://github.com/eliasneto/Sistema_posvenda` só tem 2 commits, ambos
`[FEAT-001]`, sem nenhum arquivo de Docker/CI. Esse trabalho nunca foi
commitado e se perdeu quando o checkout local antigo desapareceu do disco.
Precisa ser **recriado do zero e commitado** — não é só reaplicar o que já
existia.

**Nota separada, sobre o `modulo-posVenda` (não é este repositório):** ele
tem, sem commit, alterações em `Dockerfile`/`docker-compose.yml`/
`.gitignore` que o renomeiam para `parceiro_*` — essa é a correção já
documentada em `.claude/agents/devops.md` para a confusão de nomes com
"posvenda" (feita em 2026-08-21) e não deve ser revertida; o usuário
cancelou um pedido de reversão nisso em 2026-08-22. Sem decisão tomada
sobre deixar a porta `8095` indisponível.

**Resolvida em 2026-08-22 (DevOps):** repositório `Sistema_posvenda`
re-clonado em `C:\Projetos\Sistema_posvenda`. `Dockerfile` e
`docker-compose.yml` recriados do zero (não copiados do `modulo-posVenda`
como estavam — adaptados: sem as libs de AD auth, sem o script
`ops/setup_speed.py` que não existe aqui); `requirements.txt` ganhou
`gunicorn` e `mysqlclient`; `.env` reescrito só com as variáveis que o
`settings.py` deste repositório usa (o anterior tinha sido copiado do
`modulo-posVenda` e trazia credencial de AD/IXC/Graph que não pertence
aqui — removida; `SECRET_KEY` gerada nova, `DB_PASSWORD` é a senha real já
em uso pelo MySQL deste projeto, não a de outro sistema).

**Validado de ponta a ponta:** `docker compose up -d --build` builda e
sobe os dois serviços (`db` MySQL 8.0 porta `3315`, `web` porta `8000`),
reaproveitando o volume que já tinha as 2.622 escolas (confirmado: dado
intacto depois do rebuild). Ajuste feito na validação: o comando do
serviço `web` usa `runserver` em vez de `gunicorn` no ambiente local,
porque Gunicorn sozinho não serve arquivo estático (exigiria WhiteNoise no
`settings.py`, fora do escopo do DevOps) — `runserver` já serve, é o mesmo
comportamento que já estava rodando antes. Login testado com screenshot
real, logos aparecendo corretamente. Commitado e enviado ao GitHub
(`9b0046e`, `53ca9f0`).

Também copiada a pasta `docs_gerenciador_pos_venda/` (brief, arquitetura,
regras, checklist, `ADR-001`) para dentro do `Sistema_posvenda` — a
documentação de planejamento passa a viver junto do repositório que ela
descreve.

**Pendência atual:** ainda falta o pipeline `.github/workflows/homolog.yml`
e `scripts/deploy_homolog.sh` (escopo de homologação, não pedido nesta
rodada) e o `docker-compose.hml.yml` correspondente.

---

### FEAT-013 — Alternância de modo escuro (dark mode)
**Descrição:** Botão liga/desliga, disponível em todo o sistema, para
ativar ou desativar o modo escuro.
**Tipo:** frontend-functional (envolve JavaScript e memória de preferência
do usuário entre sessões — não é só cor/espaçamento).
**Status:** 🔍 Aguardando QA
**Prioridade:** Baixa — melhoria de interface, não faz parte do caminho
crítico do processo RI (prazo 28/08/2026).
**Critérios de aceite:**
- Botão liga/desliga visível e acessível a partir de qualquer tela
  autenticada (ex.: sidebar ou cabeçalho).
- Preferência do usuário é lembrada entre sessões (não volta ao modo claro
  ao recarregar a página ou logar de novo).
- Modo escuro se aplica a todas as telas do sistema (login incluído),
  mantendo contraste e legibilidade — sem quebra visual em nenhuma delas.
- Não altera nenhuma regra de negócio, dado ou comportamento funcional
  além da aparência.
**Regras relacionadas:** nenhuma — feature de interface, sem regra de
negócio associada.
**Dependências:** nenhuma — isolada, pode ser feita a qualquer momento sem
afetar o processo RI.
**Tipo de validação:** QA (QA-013) — cobre navegação por todas as telas
com o modo escuro ativo e a persistência da preferência.
**Entrega do Dev:**
- Botão de modo escuro no cabeçalho (visível em toda tela autenticada).
- Preferência salva no navegador (localStorage); volta escura ao
  recarregar ou logar de novo, sem alterar dado de usuário no banco.
- Aplicado em login, dashboard, grid de INEPs (com filtros) e tela de RI.
- Validado no navegador real (desktop e celular 390px), sem quebra visual.
- Suíte completa (42 testes) passando.
- **Pendência:** nenhuma na feature; ver nota abaixo sobre o ambiente local.

---

### FEAT-014 — Histórico de comunicação por RI (mensagem, anexo, e-mail)
**Descrição:** Linha do tempo dentro da tela do RI (FEAT-004) onde o
usuário escreve mensagem (comentário livre, com anexo opcional), anexa
arquivo isolado e envia e-mail — reaproveitando o padrão de
`RegistroHistorico` do `modulo-posVenda`. Mudança de status (FEAT-006) e de
campo relevante do RI gera entrada automática (rótulo + valor anterior/
novo) na mesma linha do tempo.
**Tipo:** fullstack
**Status:** ⬜ Pendente
**Prioridade:** Média — não bloqueia o caminho crítico do faturamento
(FEAT-004 a FEAT-010), é um registro de acompanhamento complementar.
**Critérios de aceite:**
- Dentro da tela do RI, usuário escreve uma mensagem e ela aparece na
  linha do tempo, mais recente primeiro.
- Usuário consegue anexar um arquivo (à mensagem ou como entrada própria).
- Envio de e-mail a partir dessa tela (reaproveitando a infra já prevista
  na FEAT-008) gera entrada na linha do tempo; e-mail recebido em resposta
  (mesmo polling da FEAT-009) também aparece.
- Mudança de status do RI e de campo relevante geram entrada automática
  estruturada (rótulo + valor anterior/novo), não só uma frase livre.
**Regras relacionadas:** RN-008. Sem RF associado em
`requisitos-validacao-cliente.html` — pedido tratado como reaproveitamento
técnico do `modulo-posVenda`, não como novo requisito formal (usuário
pediu para não alterar os requisitos).
**Dependências:** FEAT-004 (tela do RI já existe), FEAT-006 (transições de
status a registrar).
**Tipo de validação:** QA (QA-014).
**Entrega do Dev:** nenhuma ainda.
**Pendência atual:** nenhuma.

---

## Histórico de Alterações
| Data | Alteração |
|---|---|
| 2026-08-22 | Criada FEAT-014 (histórico de comunicação por RI) e RN-008 em `business_rules.md`; `ri_historico` adicionada a `modelo-dados.md` | Usuário pediu para trazer do `modulo-posVenda` o "módulo de logs" (mensagem, anexo, e-mail) e as alterações de status/campo; distinto do Auditoria/RN-006, que continua sem tela própria; requisitos não foram alterados a pedido do usuário |
| 2026-08-22 | FEAT-013 entregue pelo Dev, `🔍 Aguardando QA` — modo escuro implementado (Tailwind `dark:`, preferência em localStorage) em login, dashboard, grid de INEPs e tela de RI; suíte completa (42 testes) passando | Validação visual feita no app real (Docker), desktop e celular; para isso a senha do usuário local `admin` foi redefinida temporariamente (o Dev não tinha a senha original e não pôde restaurá-la) — usuário deve trocá-la se for usar esse login |
| 2026-08-22 | FEAT-007 entregue pelo Dev, `🔍 Aguardando QA` — grid real de INEPs (view/URL/template/menu), 8 testes automatizados, 18 testes da suíte passando | Usuário autorizou explicitamente iniciar fora de ordem (FEAT-004/006 ainda pendentes), mesmo precedente da FEAT-002; validado contra o app real (Docker) com as 2.622 escolas |
| 2026-08-22 | Dev entrega referência de frontend da FEAT-007 (`docs_gerenciador_pos_venda/frontend_reference/`) | HTML estático adaptado da tela "Endereços" do `modulo-posVenda`, verificado em 1366px/390px; não inicia a FEAT-007 (dependências FEAT-004/006 continuam pendentes) — é só material de apoio para quando ela for implementada |
| 2026-08-22 | FEAT-007: nota atualizada de "referência visual" para reaproveitamento de código de fato (tela "Endereços" do `modulo-posVenda`) | Usuário confirmou, no mesmo dia, que quer copiar/adaptar o template e as regras de frontend dessa tela — não só usá-la como inspiração; `ADR-001` recebeu emenda registrando a exceção (escopo limitado a essa tela, Provedores/Parceiro continuam descontinuados) |
| 2026-08-22 | FEAT-007 recebe nota de referência visual (tela "Endereços" do `modulo-posVenda`) | Usuário confirmou: é só inspiração de UX (badge de status, filtro, drill-down em modal), sem reaproveitar código — `ADR-001` continua descontinuando Leads/cadastro de Parceiro |
| 2026-08-22 | FEAT-001 (logos) e FEAT-012 (Docker/CI) refeitos de verdade e commitados no `Sistema_posvenda` (`9cbdbba`, `9b0046e`, `53ca9f0`) — `docker compose up -d --build` validado com screenshot real, dado das 2.622 escolas preservado. `.env` daquele repositório também foi limpo (tinha credencial de AD/IXC/Graph copiada do `modulo-posVenda` por engano) |
| 2026-08-22 | FEAT-002 reaberta (`🔍 → 🔄`) e FEAT-012 corrigida: o checkout local do `Sistema_posvenda` desapareceu do disco sem nunca ter sido commitado além de FEAT-001; ao re-clonar do GitHub, confirmou-se que a migração de dados (2.622 escolas) sobrevive no banco, mas os scripts/testes do FEAT-002 e toda a infraestrutura Docker/CI do FEAT-012 não existem no repositório — precisam ser refeitos e commitados. Ver também `ADR-001` |
| 2026-08-21 | Criação do checklist (FEAT-001 a FEAT-011, v1/RI), a partir de `requisitos.md`, `architecture.md`, `business_rules.md` e `modelo-dados.md` |
| 2026-08-21 | Criação de FEAT-012 (infraestrutura do repositório novo, tipo devops) — usuário pediu que o DevOps veja, em paralelo ao Dev, o que muda do lado dele e o que é descartado |
| 2026-08-21 | FEAT-001 concluída pelo Dev, `🔍 Aguardando QA` — repositório `Sistema_posvenda` criado e enviado ao GitHub, projeto Django sobe localmente com banco (SQLite) migrado e login testado ponta a ponta |
| 2026-08-21 | Cabeçalho ganha versão-alvo (1.0.0) e nome de exibição ("Gerenciador Pós Venda") | Usuário definiu antes do início do desenvolvimento |
| 2026-08-21 | `requisitos-validacao-cliente.html`/`.pdf` (RF-01, RF-20 nova, seção 9) e `modelo-dados-diagrama.html`/`.pdf` (campos novos de `escola`) atualizados e regerados; regra permanente de sincronização registrada | Usuário identificou que os documentos derivados tinham ficado desatualizados; PDFs regerados via Edge headless e confirmados visualmente (nenhuma entidade/campo cortado) |
| 2026-08-21 | FEAT-002 recebe nota de fonte de dados de migração | Usuário indicou `CONSOLIDADO EACE.xlsx`; verificação confirmou 2.622 INEPs únicos, sem duplicidade, campos completos — nenhuma pendência de dado faltante encontrada |
| 2026-08-21 | FEAT-012 avança para `🔄 Em andamento` com entrega do DevOps (Dockerfile, docker-compose local/homologação, pipeline `.github/workflows/homolog.yml`, `docs/devops/`) no repositório `Sistema_posvenda` | Usuário pediu para o DevOps assumir a FEAT-012; build Docker não pôde ser validado neste ambiente (Docker Desktop indisponível) — pendência registrada na própria feature |
| 2026-08-21 | FEAT-005 e FEAT-009 perdem a pendência do catálogo de tipos de divergência | Cliente confirmou o P-03 (RN-003); FEAT-005 mantém só a pendência do critério de casamento entre itens |
| 2026-08-21 | Correção de escopo: DevOps havia subido/validado o repositório errado (`modulo-posVenda`, "sistema de Parceiro") pensando ser o Gerenciador Pós-Venda | Usuário identificou o engano; repositório correto é `C:\Projetos\Sistema_posvenda` (separado, remoto `eliasneto/Sistema_posvenda`) — guardrail registrado em `.claude/agents/devops.md`. Verificado neste momento: FEAT-002 (migração das escolas) ainda não foi executada — `escolas_escola` com 0 linhas e só a migration `0001_initial` no repositório novo; segue `⬜ Pendente` até confirmação/execução real |
| 2026-08-21 | `docker compose up -d --build` validado no repositório correto (`Sistema_posvenda`); usuário criado/senha redefinida para teste local (`admin`/`admin`) | Build e boot sem erro; título "Gerenciador Pós Venda" confirmado na tela de login, migrations todas aplicadas |
| 2026-08-21 | Decisão de banco revista: MySQL 8.0 obrigatório em local, homologação e produção (substitui o SQLite local do FEAT-001, que era reversível) | Usuário decidiu manter engine único entre ambientes; registrado em `architecture.md`, "Banco de Dados" |
| 2026-08-21 | Dev ajustou `config/settings.py`/`.env.example` (MySQL como padrão local) e DevOps adicionou serviço `db` (MySQL 8.0) ao `docker-compose.yml` local, validado com `migrate` e boot limpo | Executado a pedido do usuário ("pode chamar"), na sequência da decisão de banco acima |
| 2026-08-21 | Conferência da fonte de migração (`CONSOLIDADO EACE.xlsx`) repetida a pedido do usuário; confirma o já registrado (2.622 INEPs únicos entre `FATURAMENTO MATERIAIS`/`BDO`/`MIP`, sem dado faltante). `FEAT-002` recebe pendência formal: dependência `FEAT-001` segue `🔍 Aguardando QA`, não `✅ Concluída` | Usuário pediu para chamar o Dev; Orquestrador não inicia outro agente automaticamente nem decide sozinho ignorar dependência obrigatória (CLAUDE.md §3) |
| 2026-08-21 | Usuário autorizou explicitamente iniciar `FEAT-002` mesmo com `FEAT-001` ainda em `🔍 Aguardando QA` — exceção pontual só para esta feature | Perguntado diretamente ao usuário por ser decisão de escopo/dependência (CLAUDE.md §9); `FEAT-001` continua precisando de aprovação do QA de forma independente |
| 2026-08-21 | FEAT-002 entregue pelo Dev, `🔍 Aguardando QA` — 2.622 escolas migradas para o banco do `Sistema_posvenda` (INEP, lote, UF, município, nome, endereço, velocidade, kit estimado), status inicial "desconectado" (RN-007) | Usuário autorizou chamar o Dev; entrega relatada pelo próprio Dev (idempotência e testes automatizados citados) — ainda sem verificação independente do QA |
| 2026-08-22 | FEAT-001 recebe pendência: campos Usuário/Senha do `login.html` aparecem preenchidos ao carregar, por autofill do navegador (não há `value` fixo no template) | Usuário reportou; ajuste (`autocomplete="off"`) fica dentro da própria FEAT-001, sem gerar nova feature; implementação é do Dev, fora do escopo do Orquestrador |
| 2026-08-22 | FEAT-007 recebe critério de aceite adicional: menu lateral reorganizado em aba "Projeto" > "EACE" > grid (hoje item plano "Grid de INEPs") | Usuário pediu a reorganização; confirmado que é o mesmo grid da FEAT-007 (sem lógica nova) e que "Projeto" por ora só agrupa "EACE"; ver `architecture.md`, "Estrutura de navegação (menu lateral)"; implementação é do Dev, fora do escopo do Orquestrador |
| 2026-08-22 | FEAT-004 entregue pelo Dev, `🔍 Aguardando QA` — cadastro manual de RI e itens EACE/IXC, 11 testes automatizados, 30 testes da suíte passando | Usuário autorizou explicitamente iniciar fora de ordem (FEAT-002 ainda Aguardando QA, FEAT-003 ainda Pendente), mesmo precedente da FEAT-002/FEAT-007; validado contra o app real (Docker); corrigido bug de formatação decimal (vírgula) no formulário de edição do item IXC, achado durante a validação visual |
| 2026-08-22 | FEAT-007: coluna e filtro "Status" do grid corrigidos pelo Dev — agora usam o status de conexão da Escola (RN-007), não mais o status do RI (RN-001) | Usuário identificou a inconsistência; confirmado que os dois catálogos existem na documentação e que o grid deveria usar o de conexão; status do RI segue visível na tela da FEAT-004 e no drill-down; pendência registrada para o Orquestrador deixar isso explícito em `architecture.md`/critérios de aceite |
| 2026-08-22 | FEAT-007: coluna "Responsável" removida do grid principal pelo Dev — passa a aparecer só dentro do RI (drill-down do grid e tela da FEAT-004) | Usuário identificou que Responsável é atributo do RI, não do INEP/Escola, mesmo princípio da correção de Status; suíte completa (31 testes) passando |
| 2026-08-22 | FEAT-007: as duas correções acima (Status→conexão, Responsável fora do grid) revertidas pelo Dev — localizado `requisitos-validacao-cliente.html` (o "requisitos" citado na documentação); RF-05 confirma que Status=status do RI e Responsável são as colunas oficiais do grid; status de conexão (RF-20) passa a aparecer só no drill-down | Usuário apontou que faltava o campo de status e que essa regra existe nos requisitos; suíte completa (32 testes) passando; pendência registrada para o Orquestrador sobre onde vive de fato o documento de requisitos |
| 2026-08-22 | `architecture.md`/`checklist.md`: explicitado que Status e Responsável são atributos do RI (RN-001/RF-05), não do INEP/Escola — a Escola não tem campo próprio de status de faturamento nem de responsável (só o de conexão, RF-20) | Usuário confirmou a regra ("só RI e RE têm responsável; o INEP, atividade pai, não tem"); implementação do Dev já refletia isso corretamente (`Ri.status`/`Ri.responsavel`) — sem mudança de código, só clareza documental |
| 2026-08-22 | FEAT-007 passa a exigir 6 colunas no grid: Status de conexão (Escola, RF-20) vira coluna e filtro próprios, ao lado de Status do RI e Responsável (RF-05) — sai do drill-down | Usuário apontou que status de conexão é atributo do próprio INEP/Escola e merece a mesma visibilidade das colunas do RI; implementação (adicionar a coluna/filtro de volta ao grid) é do Dev |
| 2026-08-22 | FEAT-007: 6ª coluna (Status de conexão) implementada pelo Dev, com filtro próprio separado do filtro de Status do RI; suíte completa (32 testes) passando | Usuário confirmou o desenho de 6 colunas proposto pelo Orquestrador |
| 2026-08-22 | FEAT-006 iniciada fora de ordem pelo Dev (parcial, `🔄 Em andamento`): campo de status do RI editável no drill-down do grid, com as regras de RN-001 (Correção MEGA) e RN-003 (bloqueio por divergência) já aplicadas; 8 testes novos, suíte completa (40 testes) passando | Usuário pediu o campo porque "pode alterar manualmente alguns status"; autorizada exceção de dependência (FEAT-005 ainda `⬜ Pendente`), mesmo precedente já usado antes |
| 2026-08-22 | Campo "Status do RI" no drill-down ganha destaque visual (fundo âmbar, botão preto/amarelo) | Usuário pediu uma cor diferente para essa área; ajuste puramente visual, sem lógica |
| 2026-08-22 | Botão "Ver / lançar itens" removido do drill-down do grid — os próprios cards "Lado EACE"/"Lado IXC" viraram links clicáveis (mesma cor âmbar do bloco de status) | Usuário pediu para os cards serem clicáveis em vez de precisar do botão separado, na mesma cor do status; ajuste puramente visual, sem lógica |
| 2026-08-22 | Criada FEAT-013 — Alternância de modo escuro (dark mode), `⬜ Pendente`, prioridade baixa, sem dependências | Usuário pediu um botão liga/desliga de modo escuro para o sistema; classificada frontend-functional (envolve JS e memória de preferência) — exige QA |
| 2026-08-22 | RI esclarecido como tendo 3 lados, não 2: "Kit declarado" (1º, hoje `RiItemEace`), "IXC" (2º, `RiItemIxc`) e "Relatório EACE" (3º, novo, ainda não implementado). RN-002/RN-003 (`business_rules.md`) e `modelo-dados.md` reescritos; FEAT-004 reaberta (`🔍 → 🔄`, falta o 3º lado); FEAT-005 critérios reescritos (2 confrontos: 1º×2º amarelo/informal, 3º×2º vermelho/bloqueia) | Usuário esclareceu, depois que o Dev entregou a FEAT-004 só com 2 lados, que o model já implementado representa o "Kit declarado" (dado da EACE antes do projeto), não "o relatório" — confirmado que os dois confrontos usam a mesma mecânica item a item |
| 2026-08-22 | FEAT-004 completa: 3º lado ("Relatório EACE") implementado pelo Dev — model `RiItemRelatorioEace`, painel na tela de cadastro e 3º card no drill-down do grid (FEAT-007). `🔄 → 🔍 Aguardando QA`. Suíte completa (42 testes) passando | FEAT-005 (confronto) e sua exibição de divergências continuam pendentes, mas já podem começar — a base de dados dos 3 lados está pronta |
