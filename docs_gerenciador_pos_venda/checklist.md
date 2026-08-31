# Checklist — Gerenciador Pós-Venda (v1 · Faturamento EACE por INEP)
_Última atualização: 2026-08-31_

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
transversal e pode evoluir em paralelo a partir de FEAT-001. FEAT-015
(catálogo LPU) depende de FEAT-002/FEAT-004 e pode evoluir em paralelo às
demais. FEAT-016 (cruzamento por número de Access Points) depende de
FEAT-015 e também pode evoluir em paralelo. FEAT-023 (upload da Planilha
EACE) depende só de FEAT-003 e pode evoluir em paralelo; FEAT-024
(Sincronizador do Lado Relatório EACE) depende de FEAT-023, FEAT-022 e
FEAT-016. FEAT-026 (dashboard financeiro) depende de FEAT-002/FEAT-006/
FEAT-015/FEAT-022 e pode evoluir em paralelo às demais. FEAT-027
(integração com Active Directory) depende só de FEAT-001 e pode evoluir em
paralelo às demais.

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
Analista) e as regras de permissão da RN-004. **Fechada em 2026-08-31,
sem tela própria de cadastro:** a RN-004 foi ampliada junto com a FEAT-028
(28/08) para manter criar/editar/desativar usuário só pelo `/admin/` do
Django — a tela interna "Administrador > Usuários" cobre só troca de
perfil (FEAT-028) e liga/desliga de acesso (FEAT-029). O critério original
desta feature (tela completa de cadastro) foi substituído por essa
decisão.
**Tipo:** fullstack
**Status:** 🔍 Aguardando QA (via QA-028/QA-029 — sem código próprio)
**Prioridade:** Alta
**Critérios de aceite:**
- Criar, editar e desativar usuário continuam exclusivos do `/admin/` do
  Django (RN-004, ampliada) — não há tela própria no sistema para isso.
- Troca de perfil (Administrador ↔ Analista) e liga/desliga de acesso são
  feitos pela tela "Administrador > Usuários" (FEAT-028/FEAT-029), não por
  esta feature.
- Analista realiza CRUD de INEP/item e documentos, exceto exclusão — já
  aplicado desde a FEAT-001 (`user.is_administrador`).
- Tentativa de exclusão por Analista é bloqueada em qualquer tela onde
  exclusão exista — já aplicado (FEAT-004/FEAT-006).
**Regras relacionadas:** RN-004, RF-13.
**Dependências:** FEAT-001.
**Tipo de validação:** QA — via QA-028/QA-029; sem QA-003 separada (não há
código próprio desta feature).
**Entrega do Dev (2026-08-31):**
- Investigado o que faltava — confirmado que não há mais nada a
  implementar. RN-004 já foi ampliada (junto com a FEAT-028, 28/08) para
  manter criação/edição/desativação de usuário só no `/admin/`.
- Troca de perfil e liga/desliga de acesso, que cobrem o que a tela
  interna realmente oferece, já foram entregues nas FEAT-028 e FEAT-029.
- A regra de permissão (exclusão só para Administrador) já está ativa
  desde a FEAT-001.
- **Pendência:** nenhuma — nada a implementar nesta feature.
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
  lados IXC e Relatório EACE.
- Kit declarado (1º lado) não é texto livre nem digitação manual de
  Quantidade/Valor Unitário (**RN-010, 2026-08-24 — ainda não
  implementado**): descrição vem de `Escola.kit_inicial` (coluna H do
  `CONSOLIDADO EACE.xlsx`, FEAT-002); Quantidade e Valor Unitário vêm de
  um catálogo de valores padrão por kit, cruzado pela descrição — vale
  para o lançamento inicial e para qualquer correção.
- Kit declarado e Relatório EACE não são editáveis depois de criados,
  exceto por um novo lançamento (RN-002/RN-003) — só o lado IXC aceita
  editar/excluir item.
- Lado IXC (**RN-011, 2026-08-24 — ainda não implementado**): lançamento
  deixa de ter Descrição livre. Passa a ter "KIT Instalado" (obrigatório,
  descrição escolhida no catálogo `KitPadrao`, Valor Unitário digitado
  manualmente) + itens individuais adicionais via botão "+" (Serviço
  escolhido no catálogo `KitPadrao`, Quantidade e Valor Unitário digitados
  manualmente).
**Regras relacionadas:** RN-002, RN-003, RN-004, RN-010, RN-011, RF-02, RF-03.
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
**Entrega do Dev (2026-08-24) — RN-010 (Kit declarado sem digitação):**
- Model novo `KitPadrao` (catálogo de valores padrão por kit), migration
  aplicada e registrado no admin para cadastro manual.
- Painel "Kit declarado" e a ação "Lançar item do Kit declarado" não têm
  mais campos de Descrição/Quantidade/Valor Unitário: a descrição vem de
  `Escola.kit_inicial` e Quantidade/Valor Unitário vêm do `KitPadrao`
  cruzado por ela — vale para o lançamento inicial e para qualquer
  correção.
- Sem `kit_inicial` na Escola, ou sem kit correspondente no catálogo: o
  lançamento é bloqueado com mensagem de erro, nenhum item é criado.
- 4 testes ajustados/novos (lançamento usa o catálogo, múltiplos
  lançamentos, bloqueio sem `kit_inicial`, bloqueio sem kit no catálogo);
  suíte completa do repositório (63 testes) passando.
- Validação visual em navegador: não executada (sem Playwright/browser
  disponível neste ambiente) — checagem feita via cliente de teste Django
  (`assertContains`), que renderiza o template real e confirma ausência de
  erro de template/servidor.
- **Ajuste visual (2026-08-24, sem mudança de lógica):** usuário pediu que
  a descrição apareça dentro de um campo (como antes), não como texto
  corrido — e que a frase explicando a origem de Quantidade/Valor
  Unitário fosse removida. Campo agora é um input somente leitura com o
  valor de `Escola.kit_inicial`; frase removida. Suíte completa (63
  testes) continua passando.
- **Ajuste visual (2026-08-24, sem mudança de lógica):** removida do
  painel "Kit declarado" a lista de itens já lançados (a caixa com
  descrição + "N un. — R$ valor"), considerada irrelevante pelo usuário —
  o card mostra só o campo com a descrição e o botão de lançar. Os itens
  continuam salvos no banco e visíveis no drill-down do grid (FEAT-007),
  só não aparecem mais dentro desta tela. Suíte completa (63 testes)
  continua passando.
- **Remoção do lançamento manual (2026-08-24):** usuário esclareceu que o
  Kit declarado não nasce mais de um clique nesta tela — botão "Lançar
  item do Kit declarado" e a ação `adicionar_eace` (view) removidos; o
  painel passa a só exibir `Escola.kit_inicial` em modo leitura. Escolas
  do Lote 1 terão o item gravado direto no banco (fora desta tela, ainda
  bloqueado — falta a planilha com Quantidade/Valor por kit, que o
  usuário confirmou não existir ainda); Lote 2/3 continuam cadastráveis
  pelo administrador via Django admin (`RiItemEace` já registrado),
  válido só nesta primeira versão do sistema. 1 teste novo confirma a
  exibição sem o botão; suíte completa (60 testes) passando.
  **Fora do escopo do Dev:** `business_rules.md` (RN-010) e os critérios
  de aceite da FEAT-004 ainda descrevem o lançamento manual — atualização
  formal desses dois documentos é do Orquestrador.
**Entrega do Dev (2026-08-24) — RN-011 (Lado IXC: KIT Instalado + Produtos):**
- Lançamento do Lado IXC deixou de ter Descrição livre. Painel "IXC (2º
  lado)" ganhou dois formulários: "KIT Instalado" (obrigatório, select com
  o catálogo `KitPadrao` — aba LPU do `CONSOLIDADO EACE.xlsx`, RN-010/
  FEAT-015 — filtrado à Unidade "Escola" e por `Escola.lote`, quantidade
  fixa em 1, valor unitário digitado) e "Produtos" (botão "+" lança 0+
  linhas numa única submissão — Produto do mesmo catálogo, excluída a
  Unidade "Escola", Quantidade e Valor unitário digitados).
- **Três idas e voltas até fechar a origem/filtro da lista (mesmo dia):**
  1ª versão usou `KitPadrao` já separado por Unidade (Escola x avulso);
  usuário mandou print do modelo de dados sugerindo o Kit Declarado
  (`RiItemEace`) desta escola — implementado e testado; usuário então
  esclareceu que a fonte é mesmo `KitPadrao` (aba LPU, "todos os kits e
  produtos, valor de serviço e Lote") — revertido, sem separar por
  Unidade; por fim, com a tela real na mão (print do painel IXC vazio),
  usuário pediu de volta o filtro por Unidade "Escola" no KIT — versão
  final volta a separar (mesmo critério de
  `KitPadrao.kit_fechado_por_escola`, já usado na RN-010). Rótulo
  "Serviço" virou "Produtos" e a lista de Produtos nasce sem nenhuma
  linha aberta (só aparece ao clicar no "+") — isso não mudou entre as
  versões.
- Sem nenhuma entrada de KIT (Unidade "Escola") no catálogo para o Lote
  desta escola, o painel avisa em vez de oferecer um select vazio.
  Edição/exclusão de item do IXC já lançado (RN-004) não mudou — continua
  com Descrição livre, fora do pedido do usuário.
- **Causa do painel vazio na tela real, achada durante a validação:** o
  catálogo `KitPadrao` estava com 0 registros no banco usado pelo
  `docker compose` — o comando `importar_catalogo_lpu` (FEAT-015) nunca
  tinha sido rodado contra esse banco, só testado. Rodado agora
  (`python manage.py importar_catalogo_lpu`) contra o
  `CONSOLIDADO EACE.xlsx` da raiz do projeto: 80 registros criados (Lotes
  9 e 11; Unidades Escola, Escola/Mês, Unidade, km, enlace, metro, par).
  Operação segura e idempotente, sem mudança de código.
- 8 testes (lançar KIT Instalado, KIT só lista Unidade Escola, Produto
  exclui Unidade Escola, catálogo filtra por Lote, lançar múltiplos
  Produtos numa submissão, lista de Produtos nasce vazia, submissão vazia
  do "+" não cria item, aviso com catálogo vazio); suíte completa do
  repositório (81 testes) passando.
- Validação visual em navegador: não executada (sem Playwright/browser
  disponível neste ambiente) — checagem feita via cliente de teste Django
  contra o banco real, com o catálogo já importado (render real do
  template, status 200, KIT do INEP 52101894 aparecendo, aviso de
  catálogo vazio some) e suíte completa passando.
**Entrega do Dev (2026-08-24) — RN-011 (Descrição curta no catálogo):**
- Nome do kit/produto na Descrição completa da LPU vem com um
  qualificador entre parênteses no final (ex.: "(serviços, materiais e
  equipamentos)"), grande demais para um select. Novo campo `KitPadrao.
  descricao_curta` (migration `0007`), preenchido automaticamente ao
  salvar quando fica em branco — tira esse sufixo (ex.: "Kit Cobertura
  Wi-Fi - 8 Access Points"); pode ser digitado à mão no Django admin para
  um caso que a regra automática não resolva bem, e não é sobrescrito
  numa reimportação (`importar_catalogo_lpu`) seguinte. Selects de "KIT
  Instalado" e "Produto" (RN-011) passam a mostrar essa Descrição curta,
  não a completa. Descrição do item lançado no IXC continua sendo a
  completa (RN-002/RN-003 e o PDF do financeiro, RN-008, não mudam).
- Backfill rodado nos 80 registros já importados no banco real; conferido
  o exemplo "Kit Cobertura Wi-Fi - 8 Access Points" citado pelo usuário.
- 3 testes de model (tira qualificador entre parênteses, sem parênteses
  usa a descrição inteira, valor digitado à mão não é sobrescrito) + 1
  teste de tela (select mostra a curta, não a completa); suíte completa
  do repositório (85 testes) passando.
- Validação visual em navegador: não executada (mesmo motivo acima) —
  conferido contra o banco real (INEP 52101894): a versão curta aparece
  no select, a completa não aparece mais.
**Entrega do Dev (2026-08-24) — RN-011 (opção "Outro" no KIT Instalado):**
- Select "KIT Instalado" ganhou a opção "Outro — kit não cadastrado", para
  quando o kit instalado é diferente de tudo que está no catálogo. Ao
  escolher "Outro", abre o campo "Número de Access Points"; a descrição
  gravada segue o mesmo padrão de nome do catálogo — ex.: digitou "20" →
  grava "Kit Cobertura Wi-Fi - 20 Access Points" (decisão do usuário,
  confirmada antes de implementar). Sem o número preenchido, "Outro" dá
  erro e não lança nada.
- "Outro" aparece sempre, mesmo com o catálogo cheio — não é só para
  quando falta cadastro no Lote.
- 3 testes novos (lançar "Outro" gera a descrição no padrão do catálogo,
  "Outro" sem número não lança nada, "Outro" está sempre na lista); suíte
  completa do repositório (88 testes) passando.
- Validação visual em navegador: não executada (mesmo motivo acima) —
  conferido contra o banco real: opção "Outro", campo "Número de Access
  Points" e o JS que mostra/esconde esse campo estão presentes na tela.
**Entrega do Dev (2026-08-24) — RN-011 (campo Valor unitário removido do
lançamento):**
- Usuário pediu para tirar o campo Valor unitário do lançamento do Lado
  IXC — "não é informação necessária agora". Removido de "KIT Instalado"
  e de cada linha de "Produtos"; item lançado nasce com valor 0,00
  (`RiItemIxc.valor_unitario` é obrigatório no banco, não aceita vazio).
  Edição de item já lançado (RN-004) não mudou — continua com o campo de
  valor, para corrigir depois se precisar.
- 3 testes ajustados para o novo valor 0 (lançar KIT Instalado, lançar
  "Outro", lançar múltiplos Produtos); suíte completa do repositório (88
  testes) passando.
- Validação visual em navegador: não executada (mesmo motivo acima) —
  conferido contra o banco real: campo Valor unitário some do bloco do
  KIT Instalado, só resta o do painel Relatório EACE (não tocado).
**Entrega do Dev (2026-08-24) — RN-011 (campo Data Ativação no bloco
Produtos):**
- Novo campo `Ri.data_ativacao` (migration `0008`) — um valor só por RI,
  não por item (confirmado com o usuário antes de implementar). Aparece
  no bloco "Produtos" do Lado IXC, salvo junto com o lançamento de
  produtos (mesma submissão), mesmo quando nenhum produto é lançado
  junto. Submissão sem nenhum produto e sem mudar a data mostra erro, em
  vez de salvar vazio.
- 3 testes novos (Data Ativação salva sozinha, salva junto com um
  produto na mesma submissão, submissão totalmente vazia mostra erro);
  suíte completa do repositório (90 testes) passando.
- Validação visual em navegador: não executada (mesmo motivo acima) —
  conferido contra o banco real: campo "Data Ativação" (input de data)
  presente no bloco Produtos.
**Entrega do Dev (2026-08-24) — RN-011 (um só botão de salvar no Lado
IXC):**
- Usuário apontou dois botões de salvar no mesmo bloco (print da tela) —
  "Lançar KIT Instalado" e "Lançar produtos" viraram um único formulário
  e um único botão "Salvar" (ação `salvar_ixc`, substitui
  `adicionar_ixc_kit`/`adicionar_ixc_produtos`). KIT, Produtos e Data
  Ativação agora são opcionais nessa submissão — o KIT deixou de ser
  obrigatório a cada clique, já que uma submissão pode ser só para
  atualizar a Data Ativação ou só lançar um produto novo. Submissão sem
  nada preenchido mostra erro, em vez de salvar vazio.
- Edição/exclusão de item já lançado (RN-004) não mudou.
- 7 testes ajustados para a ação e o formulário únicos; suíte completa
  do repositório (90 testes) passando.
- Validação visual em navegador: não executada (mesmo motivo acima) —
  conferido contra o banco real: só um botão "Salvar" no bloco do Lado
  IXC, os dois antigos não existem mais.
**Entrega do Dev (2026-08-24) — RN-011 (remover linha de Produto + altura
travada da lista):**
- Botão "x" em cada linha de Produto (servidor ou clonada pelo "+") para
  remover antes de enviar — usuário apontou que não tinha como excluir
  uma linha aberta por engano. Remove só a `div` no navegador, sem
  reindexar as demais; um índice de formset ausente na submissão é
  tratado pelo Django como linha extra vazia, não erro (testado).
- Lista de Produtos ganhou altura travada com rolagem própria
  (`max-h-72 overflow-y-auto`) — painel do IXC não cresce mais sem limite
  conforme produtos são adicionados. **Resposta à pergunta do usuário:**
  não precisa de model separado — era só CSS/layout, sem relação com
  dado ou estrutura de tabela.
- 1 teste novo (índice do meio ausente na submissão não quebra o
  lançamento dos outros dois); suíte completa do repositório (91 testes)
  passando.
- Validação visual em navegador: não executada (mesmo motivo acima) —
  conferido contra o banco real: botão de remover e o container com
  altura travada/rolagem presentes na tela.
**Entrega do Dev (2026-08-24) — RN-011 (espaçamento entre Produto e
Quantidade):**
- Usuário apontou (print) que os campos "Produto" e "Quantidade" de cada
  linha estavam colados, atrapalhando a leitura. Espaçamento entre os
  dois aumentado e o rótulo de cada campo ganhou espaçamento próprio e
  explícito em relação ao input, em vez de depender só da quebra de
  linha natural do campo `w-full`.
- Ajuste puramente visual (frontend-layout), sem mudança de lógica —
  suíte do app `ri` (76 testes) confirmada passando.
- Validação visual em navegador: não executada (sem Playwright/browser
  disponível neste ambiente) — conferido o HTML gerado (mesmo trecho
  clonado pelo "+") contra o banco real.
**Entrega do Dev (2026-08-24) — RN-011 (correção da causa real: contraste
dos campos de Produto/Quantidade):**
- O ajuste anterior (gap) não resolveu — usuário mandou novo print
  mostrando que o campo "Quantidade" (e o próprio select "Produto")
  ficavam praticamente invisíveis. Causa raiz: o campo usava o mesmo
  fundo cinza (`bg-gray-50`/`dark:bg-gray-800`) do card que o envolve,
  sem contraste nenhum — não era falta de espaçamento. Corrigido
  invertendo a cor do campo (fundo branco/escuro + borda), mesmo padrão
  já usado no formulário de edição do item IXC.
- Ajuste puramente visual (frontend-layout), sem mudança de lógica —
  suíte do app `ri` (76 testes) confirmada passando.
- Validação visual em navegador: não executada (mesmo motivo acima) —
  conferido contra o banco real que o campo agora renderiza com
  fundo/borda diferentes do card que o envolve.
**Pendência atual:** tela formal de cadastro/gestão de usuário (FEAT-003)
continua não implementada — pendência já registrada antes, sem relação
com o 3º lado. Confronto (FEAT-005) e sua exibição de divergências
(amarelo/vermelho) ainda não implementados — depende só desta feature,
que agora está completa. Catálogo `KitPadrao` nasce vazio (nenhum valor
inventado, CLAUDE.md §9) — fonte da carga real definida em 2026-08-24
(aba `LPU` de `CONSOLIDADO EACE.xlsx`); carga e a correção do cruzamento
(passa a considerar `Escola.lote`, não só a descrição) ficam para a
FEAT-015. **"Lote 1"/"Lote 2/3" citadas acima — verificado pelo
Orquestrador (2026-08-24):** não é o mesmo campo `Escola.lote` da LPU.
Os dados reais da planilha só têm `Escola.lote` `9` e `11` (verificado
na aba `FATURAMENTO MATERIAIS`); "Lote 1/2/3" não aparece em nenhum
outro documento do projeto (`requisitos-validacao-cliente.html`,
`business_rules.md`, `architecture.md`) — é linguagem informal do Dev
para uma leva de implantação, não um campo com valor definido hoje.
Pendência residual: **o que hoje distingue "Lote 1" de "Lote 2/3"**
(critério real de quais escolas entram automaticamente vs. cadastro
manual) continua sem definição — só interessa quando existir a feature
de geração automática de `RiItemEace` (ver FEAT-015). **Sem relação com
a pendência acima:** no mesmo dia, o usuário usou "lote 1"/"lote 2"
informalmente para o 1º e 2º lado (RN-002) — não `Escola.lote` — ao
relatar que `Escola.kit_inicial` às vezes traz só o número do KIT (ex.:
`4`) em vez do texto completo do catálogo `KitPadrao`; cruzamento
proposto (`KitPadrao.numero_access_points`) registrado em RN-010
ampliada e agora rastreado na FEAT-016. Validação visual
da mudança no painel do Kit declarado ainda depende de inspeção manual/
Playwright. **Nova pendência (2026-08-24, RN-011):** Lado IXC precisa do
bloco "KIT Instalado" + itens individuais via "+", descrito no critério
de aceite acima — ainda não implementado pelo Dev.

**Entrega do Dev (2026-08-27) — ordenação das listas KIT Instalado/Produtos:**
- Usuário reportou que a lista "KIT Instalado" (e "Produtos") do Lado IXC
  não aparecia em ordem — texto alfabético colocava "16 Access Points"
  antes de "2 Access Points". Corrigido: as duas listas (e as
  equivalentes do Relatório EACE, RN-018, mesma função compartilhada)
  passam a ordenar por `KitPadrao.numero_access_points` crescente (KIT 1,
  2, 4, 8...); itens sem número extraído (avulsos) vão para o final, por
  Descrição entre si.
- Ajuste pontual de lógica (ordenação de consulta), sem mudança de regra
  de negócio nem de dado gravado — suíte completa do app `ri` (172
  testes) confirmada passando.
- **Fora do escopo do Dev:** registrar o ajuste em `business_rules.md`
  (RN-011/RN-018) é do Orquestrador.

---

### FEAT-005 — Confronto de divergências (2 confrontos: RN-002 e RN-003)
**Descrição:** Esclarecido em 2026-08-22 que são **dois confrontos**, não
um: (1) Kit declarado × IXC — campo único (descrição do KIT), destaque
amarelo, não bloqueia (RN-002); (2) Relatório EACE × IXC — formal, sem
tolerância, destaque vermelho do lado do IXC, bloqueia (RN-003). Critérios
do confronto 2 fechados em 2026-08-26: compara Descrição (qual KIT/Produto
do catálogo) e Quantidade — sem Valor Unitário. Confronto 1 confirmado
completo em 2026-08-31 — nunca foi item a item (RN-002 consolidada).
**Tipo:** fullstack
**Status:** 🔍 Aguardando QA (os dois confrontos)
**Prioridade:** Alta — confronto 2 era o próximo a implementar (usuário
pediu o bloqueio do envio ao financeiro); ambos concluídos.
**Critérios de aceite:**
- Confronto 2 (Relatório EACE × IXC, RN-003 — pronto para implementar):
  compara "KIT Instalado" isoladamente (no máximo 1 de cada lado) e
  "Produtos" como conjunto (mesma Descrição + mesma Quantidade total nos
  dois lados). Falta, sobra ou quantidade diferente de qualquer KIT/
  Produto = divergência formal, destacada em vermelho nos itens do Lado
  IXC; bloqueia a transição "Andamento" → "Envio de Email para
  faturamento" (RN-001) enquanto aberta. Valor Unitário não entra nesse
  confronto (RN-003).
- Divergência do confronto 2 é recalculada automaticamente a cada
  lançamento, edição ou exclusão de item no Lado IXC ou no Lado Relatório
  EACE — 1 registro de `RiDivergencia` por RI para esse tipo
  (`kit_relatorio`), atualizado (não acumulado por item).
- Bloqueio da transição já existe no código
  (`_validar_transicao_status_ri`) — falta só o gerador da divergência
  acima alimentar `ri.divergencias`.
- INEP com divergência formal aberta (confronto 2) aparece destacado
  (fundo vermelho) no grid (FEAT-007) — exibição já existe, também só
  falta o gerador alimentar.
- Confronto 1 (Kit declarado × IXC, RN-002 — consolidada em 2026-08-31):
  campo único — descrição do "Kit declarado" × descrição do "KIT
  Instalado" do Lado IXC; destaque amarelo, nunca bloqueia. Já
  implementado (`divergencia_kit`, `ri_detail_view`) e confirmado em
  2026-08-27 (FEAT-006). Não existe "Produtos avulsos" do lado Kit
  declarado para comparar — `RiItemEace` nunca guardou uma lista de
  itens, só a descrição do KIT (o lançamento manual foi removido pela
  RN-010 em 2026-08-24).
- Comparação estrita nos dois confrontos — acentuação, espaço e caixa
  contam como divergência.
**Regras relacionadas:** RN-002, RN-003, RN-011, RN-018, RF-04, RF-06.
**Dependências:** FEAT-004 (3º lado "Relatório EACE", `🔍 Aguardando QA`),
FEAT-022 (KIT/Produtos do Lado Relatório EACE vêm do catálogo, `🔍
Aguardando QA` — condição para o casamento por Descrição ser confiável).
**Tipo de validação:** QA (QA-005).
**Entrega do Dev:**
- Confronto 2 (RN-003) implementado: compara KIT isolado + Produtos como
  conjunto entre Lado IXC e Lado Relatório EACE, sem Valor Unitário.
- Divergência (`RiDivergencia`, tipo `kit_relatorio`) é criada, atualizada
  ou resolvida automaticamente a cada lançamento/edição/exclusão de item
  nos dois lados — 1 registro por RI, não acumulado por item.
- Itens divergentes do Lado IXC ficam com destaque vermelho (borda +
  texto) na tela do RI; bloqueio do envio ao financeiro e destaque no
  grid (FEAT-007) já existiam e passaram a funcionar de ponta a ponta.
- Suíte completa do app `ri` (164 testes) passando.
- Validado no navegador real (Playwright, servidor local): KIT/Produto
  divergentes destacados em vermelho na tela do RI, tentativa de mudar
  status para "Envio de Email para faturamento" bloqueada com a mensagem
  da RN-003, e linha do INEP destacada no grid.
- **Pendência:** nenhuma.

**Entrega do Dev (2026-08-31):**
- Investigado o que faltava do confronto 1 (RN-002) — confirmado que já
  estava completo, sem precisar de código novo.
- `RiItemEace` (Kit declarado) nunca guardou uma lista de produtos: desde
  a RN-010 (24/08), o lançamento manual foi removido e o painel mostra só
  uma descrição de KIT — não existe "Produtos avulsos" desse lado para
  comparar.
- O alerta de KIT (`divergencia_kit`) já estava implementado e confirmado
  em 2026-08-27, junto com a entrega da FEAT-006.
- **Pendência:** nenhuma — FEAT-005 completa (os dois confrontos).

---

### FEAT-006 — Ciclo de vida do RI (máquina de status)
**Descrição:** Os 8 status do RI (RN-001), incluindo o desvio manual
"Correção MEGA" e o bloqueio de transição enquanto houver divergência
aberta.
**Tipo:** fullstack
**Status:** 🔍 Aguardando QA
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
- Usuário Administrador tem opção manual de tirar o RI de "Aguardando
  financeiro" direto para "Resposta Financeiro", sem esperar o gatilho
  automático; Analista não vê essa opção (RN-019).
- Com o RI em "Faturamento Concluído", campos do Lado IXC e do Lado
  Relatório EACE ficam somente leitura para os dois perfis; só
  Administrador troca o status a partir desse status; ao trocar, os campos
  voltam a ficar editáveis (RN-020).
**Regras relacionadas:** RN-001, RN-002, RN-003, RN-019, RN-020, RF-14, RF-15.
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

**Entrega do Dev (2026-08-26, RN-019):**
- Administrador ganha um botão "Forçar Resposta Financeiro" no drill-down
  do grid, só quando o RI está em "Aguardando financeiro" — leva direto
  para "Resposta Financeiro" (mesmo destino do gatilho automático).
- Analista não vê o botão; tentativa por outro perfil, outro destino ou
  outra origem continua bloqueada com a mesma mensagem de sempre.
- Ação registra log na linha do tempo com o Administrador como autor
  (RN-008).
- 8 testes automatizados novos (permissão, destino/origem inválidos, log,
  visibilidade do botão). Suíte completa do repositório (189 testes)
  passando.
- Validação: smoke test no app real (Docker, via curl) confirmando o fluxo
  ponta a ponta. Navegador não aberto — `chromium-cli` indisponível no
  ambiente; sem inspeção visual.

**Entrega do Dev (2026-08-27, RN-020):**
- Com o RI em "Faturamento Concluído", os campos do Lado IXC e do Lado
  Relatório EACE ficam bloqueados (leitura) para Administrador e Analista,
  no lançamento, na edição e na exclusão.
- Só Administrador troca o status a partir de "Faturamento Concluído";
  Analista não vê a opção no drill-down (select trava no valor atual).
- Ao Administrador trocar o status, os dois lados voltam a ficar editáveis
  normalmente, sem diferença de um RI que nunca passou por esse status.
- 11 testes automatizados novos (bloqueio dos dois lados nas 6 rotas
  afetadas, guarda de status para os dois perfis, UI travada no drill-down).
  Suíte completa do repositório (200 testes) passando.
- Validação: smoke test no app real (Docker, via `Client` autenticado)
  confirmando os dois perfis na tela de detalhe e no drill-down do grid.
  Navegador não aberto — `chromium-cli` indisponível no ambiente; sem
  inspeção visual.

**Entrega do Dev (2026-08-27, fechamento):**
- Confirmado que os 3 itens da pendência anterior já estavam resolvidos
  por entregas de outras features, sem precisar de código novo: destaque
  amarelo de KIT divergente (`divergencia_kit`, RN-002); transições
  automáticas por e-mail (envio confirmado → "Aguardando financeiro",
  resposta recebida → "Resposta Financeiro", FEAT-008/009); e o confronto
  automático de divergências (`sincronizar_divergencia_kit_relatorio`,
  RN-003/FEAT-005) alimentando o bloqueio de transição.
- 2 testes novos de integração confirmando que uma divergência **gerada
  automaticamente** (não criada manualmente em teste) bloqueia e depois
  libera a transição "Andamento" → "Envio de Email para faturamento".
- Suíte completa do app `ri` (204 testes) e do repositório (221 testes)
  sem regressão.
- Validação visual em navegador: não aplicável — nenhuma tela nova ou
  alterada, só testes de integração backend.
- **Pendência:** nenhuma.

---

### FEAT-007 — Grid de INEPs com drill-down
**Descrição:** Grid principal com 5 colunas — INEP, Nome da escola,
Endereço, Status de conexão, Status do RI — com filtro e detalhe dos itens
por INEP. Status de conexão é atributo do próprio INEP/Escola (RF-20);
Status do RI é atributo do RI (RN-001/RF-05) — o INEP/Escola não tem campo
próprio de status de faturamento. "Responsável" **não é coluna da tabela
principal**: é atributo do RI (RN-012) exibido e editável dentro do
drill-down do grid (e da tela de detalhe da FEAT-004), como campo `<select>`
com os usuários do sistema.
**Tipo:** frontend-functional
**Status:** 🔍 Aguardando QA
**Prioridade:** Alta
**Critérios de aceite:**
- Uma linha do grid por INEP; botão de detalhe abre os itens (EACE e IXC)
  daquele INEP.
- Coluna e filtro "Status de conexão" (Escola, RF-20: desconectado/
  parcialmente conectado/conectado) visíveis direto na linha, sem precisar
  abrir o drill-down.
- Coluna e filtro "Status do RI" (RN-001), também visíveis direto na linha
  (grid único de itens, não separado por tipo de validação).
- Tabela principal do grid **sem** coluna "Responsável".
- Dentro do drill-down do INEP: campo "Responsável" (RN-012), com o nome do
  usuário atual e um `<select>` com todos os usuários do sistema para
  reatribuir o RI; salvar aplica na hora (mesmo padrão do campo "Status do
  RI" já editável, FEAT-006).
- Tela de detalhe do RI (`ri_detail`, FEAT-004) também passa a exibir
  "Responsável" como o mesmo campo editável, não só texto.
- INEP com divergência aberta aparece com fundo vermelho (RN-003).
- Item de menu reorganizado em hierarquia: aba "Projeto" > "EACE" > grid
  (hoje item plano "Grid de INEPs" em `core/base.html`); ver
  `architecture.md`, "Estrutura de navegação (menu lateral)". Só
  navegação/UI — sem mudança de view, URL, template ou lógica do grid.
**Regras relacionadas:** RN-003, RN-012, RF-05, RF-06.
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

**Entrega do Dev (2026-08-25) — Responsável sai do grid, fica editável
dentro do RI (RN-012):**
- `grid_inep.html`: coluna "Responsável" removida da tabela principal (5
  colunas); dentro do drill-down, "Status do RI" e "Responsável" ficam
  lado a lado (empilham no celular), cada um com um `<select>` que salva
  direto ao trocar a opção — sem botão de salvar (ajuste pedido pelo
  usuário).
- `ri_detail.html` (FEAT-004): card "Responsável" também passa a ser esse
  mesmo `<select>` com salvamento automático.
- Nova rota `ri_responsavel_update`, mesma permissão do campo "Status do
  RI" (login obrigatório, RN-004); reatribuição grava log na linha do
  tempo do RI (RN-008).
- 7 testes novos/ajustados; suíte completa do repositório (108 testes)
  passando.
- Validação visual em navegador (Playwright), 1366px e 390px — sem erro de
  console; corrigido durante a validação um empilhamento indevido dos dois
  campos no celular (rolagem horizontal para alcançar "Responsável").
**Pendência:** nenhuma.
**Correção (2026-08-27):** card "Com divergência" vira filtro, igual ao
card "Resposta Financeiro" (RN-016) — clicar filtra o grid pelos INEPs com
divergência aberta; combina com os demais filtros (busca, status de
conexão, Status do RI). 2 testes novos; suíte completa (236 testes) sem
regressão.

---

### FEAT-008 — Envio de e-mail para o financeiro
**Descrição:** Tela dedicada de composição de e-mail (De/Para/Cc/Assunto/
Anexo/Mensagem), aberta a partir de um único botão por linha do grid, com
PDF gerado anexado e transição automática de status ao confirmar envio.
**Tipo:** fullstack
**Status:** 🔍 Aguardando QA
**Prioridade:** Alta
**Critérios de aceite:**
- Grid mostra só um input/botão por linha do INEP, habilitado somente no
  status "Envio de Email para faturamento"; ao clicar, abre uma tela/modal
  de composição de e-mail — não mais um formulário direto na tela do grid.
- Tela de composição tem os campos De (automático, remetente do sistema,
  não editável), Para, Cc, Assunto, Anexo e Mensagem.
- Para, Cc e Assunto vêm pré-preenchidos — Para: `hilber.lustosa@speedcsc.com.br`,
  `financeiro@speedcsc.com.br`; Cc: `logistica-l@speedcsc.com.br`,
  `posvendas@megainfraestrutura.com.br`, `david.alves@speedcsc.com.br`;
  Assunto com o código de rastreio (RN-009) — mas o usuário pode editá-los
  antes de enviar (deixa de ser estritamente fixo).
- Anexo: o PDF gerado automaticamente (RN-008, itens do lado IXC) continua
  anexado por padrão; o campo permite acrescentar mais um arquivo, opcional
  — não o substitui.
- PDF anexado é gerado com os itens do lado IXC e o texto da Mensagem; o
  mesmo texto aparece no corpo do e-mail enviado.
- Um e-mail por INEP, um botão de envio por linha — nunca em lote.
- Ao confirmar o envio na tela de composição, o status do RI muda
  automaticamente para "Aguardando financeiro".
**Regras relacionadas:** RN-001, RN-009, RF-16, RF-17, RF-18.
**Dependências:** FEAT-006, FEAT-007 — **exceção autorizada explicitamente
pelo usuário em 2026-08-23** para iniciar mesmo com a FEAT-006 ainda
`🔄 Em andamento` (parcial, mas já cobre a troca de status usada aqui) e a
FEAT-007 ainda `🔍 Aguardando QA`, mesmo precedente já usado antes.
**Tipo de validação:** QA (QA-008).
**Entrega do Dev:**
- Campos do formulário definidos com o usuário: reaproveita os itens já
  lançados do lado IXC (sem redigitar) + observação livre opcional — não
  havia lista de campos fechada em nenhum documento antes disso.
- No drill-down do grid (mesmo lugar da troca de status), com o RI em
  "Envio de Email para faturamento": formulário de observação (salvar
  libera "Enviar e-mail") e botão de envio, um por linha.
- E-mail enviado com PDF anexado (itens do IXC + observação), mesmos dados
  no corpo; assunto com código de rastreio RN-009 (`#RI-AAAAMMDD-INEP -
  ...`), em `apps/core/email_tracking.py`, reaproveitável pela FEAT-009.
- Registra o envio em `EmailFinanceiroLog` e na linha do tempo do RI
  (FEAT-014, com o PDF também anexado ali) e muda o status automaticamente
  para "Aguardando financeiro", com log automático (RN-008).
- Validado no navegador real (Docker): confirmar dados, enviar e-mail,
  verificado no log do backend de e-mail (console, ambiente local) o
  assunto com código de rastreio e os destinatários fixos; modo claro e
  escuro.
- Suíte completa (60 testes) passando.
**Reaberta em 2026-08-24 (Orquestrador, a pedido do usuário):** a entrega
acima mostra só o campo "Observações para o financeiro" direto no
drill-down do grid, com botão "Enviar e-mail" que dispara o envio via
`confirm()` do navegador — sem tela de composição. Usuário pediu uma tela
dedicada, substituindo esse formulário. Critérios de aceite acima já
atualizados; decisões tomadas com o usuário: (1) Para/Cc/Assunto vêm
pré-preenchidos com os valores hoje fixos, mas passam a ser editáveis pelo
usuário antes de enviar; (2) o campo Anexo é adicional ao PDF gerado
automaticamente (RN-008), que continua sendo anexado por padrão — não o
substitui. O campo "Mensagem" da nova tela assume o papel do atual
"Observação" (mesmo dado, mesmo uso no corpo do e-mail/PDF). Status volta
para 🔄 Em andamento — a entrega anterior não chegou a passar por QA.
**Entrega do Dev (2026-08-24):**
- Grid agora mostra só o botão "Compor e-mail" (habilitado só em "Envio de
  Email para faturamento"), que abre uma tela/modal com os campos De
  (automático), Para, Cc, Assunto, Anexo e Mensagem.
- Para/Cc/Assunto vêm pré-preenchidos com os valores de antes, mas o
  usuário pode editá-los antes de enviar; o código de rastreio (RN-009) é
  preservado no Assunto mesmo se o texto for alterado.
- Anexo é adicional ao PDF gerado automaticamente (RN-008) — o PDF
  continua sempre anexado; o campo só soma mais um arquivo, se o usuário
  quiser.
- O antigo fluxo em duas etapas (confirmar dados → enviar e-mail) virou um
  só passo, direto na tela de composição; o campo "Mensagem" substitui o
  antigo "Observação" (mesmo dado internamente).
- Testes ajustados/novos cobrindo o novo fluxo (bloqueio fora do status,
  destinatário inválido/ausente, edição de Para/Cc/Assunto, anexo extra
  somado ao PDF); suíte completa (61 testes) passando.
- Validado no navegador real (Docker): tela abre com os dados corretos,
  campos editáveis, fecha pelo X/Cancelar/clique fora, em desktop (1366px)
  e celular (390px), modo claro e escuro — sem erro de console.
**Pendência:** nenhuma na feature. FEAT-009 (leitura da resposta) já pode
reaproveitar `extrair_codigos_rastreio` de `apps/core/email_tracking.py`
quando for implementada.

---

### FEAT-009 — Leitura da resposta do financeiro e segunda validação
**Descrição:** Polling (~5 min) na caixa de entrada, identificação do INEP
pela resposta, anexo de NF+XML e validação contra o que foi solicitado
antes de liberar o próximo passo (RN-005).
**Tipo:** backend-only
**Status:** 🔍 Aguardando QA
**Prioridade:** Alta
**Critérios de aceite:**
- Resposta identificada corretamente ao INEP pelo código de rastreio do
  e-mail enviado (RN-009), extraído do assunto — não por remetente nem
  corpo do texto.
- NF (PDF) e XML ficam disponíveis no INEP; nova resposta substitui a
  versão anterior.
- E-mail fora do padrão (sem 1 PDF + 1 XML, ou sem código de rastreio
  identificável) não bloqueia o fluxo, só gera alerta no log.
- Ao identificar a resposta, o status do RI muda automaticamente para
  "Aguardando Anexo portal EACE".
  **Divergência (2026-08-26):** RN-016 renomeia esse status para "Resposta
  Financeiro" e estende o gatilho para cobrir também resposta fora do
  padrão — critério acima passa a valer no formato novo; implementação é
  da FEAT-020, não reabre esta feature.
**Regras relacionadas:** RN-001, RN-005, RN-009, RF-08, RF-09, RF-19.
**Dependências:** FEAT-008 (ainda `🔍 Aguardando QA` — iniciada fora de
ordem, autorizada explicitamente pelo usuário em 2026-08-25).
**Tipo de validação:** QA (QA-009).
**Entrega do Dev:**
- Criado o comando `sincronizar_email_financeiro` — identifica o RI pelo
  código de rastreio do assunto (RN-009) a cada passada.
- NF (PDF) e XML ficam anexados ao INEP; nova resposta substitui a
  versão anterior.
- Status muda automaticamente para "Aguardando Anexo portal EACE" ao
  identificar a resposta (RF-19).
- E-mail fora do padrão ou sem código de rastreio não bloqueia o fluxo,
  só gera alerta no log (RN-005/RN-009).
- Suíte completa (118 testes) passando.
- **Pendência:** ver abaixo — leitura real ainda não validada ponta a
  ponta (falta credencial do Microsoft Graph).
**Pendência atual:**
- IMAP com usuário/senha foi testado contra a caixa real e falhou (a
  Microsoft aposentou essa autenticação); a leitura passou a usar
  Microsoft Graph, mas com um app do Azure AD **exclusivo deste sistema**
  — usuário confirmou que o Sistema_posvenda não pode depender do app do
  `modulo-posVenda`. Esse app ainda não existe; até lá a sincronização
  fica desligada (`GRAPH_FINANCEIRO_ENABLED=False`), então a leitura real
  não foi validada ponta a ponta, só com a chamada ao Graph simulada nos
  testes. **Corrigido em 2026-08-25 (Orquestrador):** o DevOps havia
  reportado um roteiro pronto em `docs/devops/AZURE_AD_GRAPH_FINANCEIRO.md`
  — verificado agora e **esse arquivo não existe no repositório** (não há
  nem pasta `docs/` no `Sistema_posvenda`; `git status` não mostra o
  arquivo nem staged nem untracked). O serviço `email_scheduler` em
  `docker-compose.yml` e a variável `GRAPH_FINANCEIRO_POLL_INTERVAL_SECONDS`
  em `.env.example` são reais (confirmados no working tree, ainda não
  commitados), só o documento do roteiro não foi de fato criado. Falta
  pedir ao DevOps para escrever e commitar o roteiro de verdade antes de
  repassar ao time de infra; provisionar o app em si continua exigindo
  alguém com papel de admin do tenant (Application Administrator +
  Application Administrator do Exchange) — não é algo que Dev, DevOps ou
  Orquestrador possam fazer sem essas credenciais reais (CLAUDE.md §6/§9).
- Comparar o conteúdo da NF/XML contra os itens do lado IXC para detectar
  divergência "NF × financeiro" (RN-003) não foi implementado — a RN-003
  ainda não define o critério de casamento entre os itens; esta versão só
  confere a estrutura da resposta (1 PDF + 1 XML), que é o critério já
  fechado na RN-005.
- **Resolvido em 2026-08-25 (DevOps):** agendamento do polling — serviço
  `email_scheduler` no `docker-compose.yml` (mesma imagem do `web`), roda
  `sincronizar_email_financeiro` a cada
  `GRAPH_FINANCEIRO_POLL_INTERVAL_SECONDS` (padrão 300s/~5min, em
  `.env.example`), sem dependência nova (Celery/Redis/cron do SO).
  Enquanto o app do Azure AD acima não existir, o comando falha rápido e o
  loop tenta de novo no ciclo seguinte, sem derrubar o container —
  validado com `docker compose config`.
- **(2026-08-26)** Usuário reportou, testando a tela do RI, que a resposta
  do financeiro (PDF + XML) não tem onde ser baixada — nem na linha do
  tempo (FEAT-014/RN-008: a entrada tipo "e-mail" criada em
  `_processar_mensagem` grava só um resumo em texto, sem anexo vinculado),
  nem em nenhuma outra tela do RI. Os arquivos são gravados normalmente
  (`Documento`, RF-08, com versionamento), só falta a exposição para
  download; critério desta feature "NF (PDF) e XML ficam disponíveis no
  INEP" não está cumprido. Correção é do Dev antes de seguir ao QA-009.
- **Corrigido (2026-08-27, Dev):** primeira versão criava 2 entradas de
  anexo separadas (`RiHistorico` tipo `anexo`, uma por arquivo) — usuário
  testou e pediu para não separar do card do e-mail. Redesenhado: novo
  campo `RiHistorico.documentos` (M2M para `Documento`, migração `0018`)
  — a própria entrada `email` referencia os `Documento` já salvos (sem
  duplicar upload), com "Baixar Nota Fiscal (PDF)"/"Baixar XML" dentro do
  mesmo card; nada muda quando a resposta é fora do padrão. `ri_detail`
  passa a usar `prefetch_related("documentos")` (evita N+1 na linha do
  tempo, CLAUDE.md §7). RI 12 (INEP 35244752, já tinha resposta recebida
  antes da correção) recebeu backfill pontual para o novo formato, com
  validação no navegador real (Docker) confirmando um único card, sem
  duplicar arquivo, com autor "Sistema" (antes aparecia "Usuário
  removido"). Suíte completa do app `ri` (172 testes) passando.

---

### FEAT-010 — Anexo manual no portal EACE e conclusão Faturado
**Descrição:** Marcação manual de anexo feito no portal EACE e conclusão
manual como "Faturamento Concluído".
**Tipo:** fullstack
**Status:** 🔍 Aguardando QA
**Prioridade:** Alta
**Critérios de aceite:**
- Botão de marcação "anexo feito no EACE" disponível para Analista e
  Administrador, só no status "Resposta Financeiro" (nome atual do status
  5, RN-001/FEAT-020 — antes "Aguardando Anexo portal EACE"); ao marcar,
  status muda para "Aguardando validação EACE".
- Botão de conclusão "Faturamento Concluído" só habilitado depois da
  marcação de anexo (ou seja, só a partir de "Aguardando validação EACE").
- Conclusão não dispara notificação, relatório nem fechamento automático
  adicional.
**Regras relacionadas:** RN-001, RN-004, RF-10, RF-11.
**Dependências:** FEAT-009.
**Tipo de validação:** QA (QA-010).
**Entrega do Dev (2026-08-31):**
- As duas transições reaproveitam o mesmo formulário de status já usado
  pelas demais (FEAT-006, drill-down do grid) — sem tela nova. Adicionadas
  as duas regras que faltavam: marcar o anexo só é aceito a partir de
  "Resposta Financeiro"; concluir só é aceito a partir de "Aguardando
  validação EACE". Analista e Administrador têm as duas opções nos status
  certos, igual às demais trocas manuais.
- Administrador continua podendo voltar um RI já concluído para
  "Aguardando validação EACE" para corrigir algo (RN-020) — a regra nova
  não bloqueia essa exceção já existente.
- Conclusão manual passa a gravar `concluido_em`, mesmo campo que a
  conclusão automática (RN-024) já gravava — antes ficava vazio quando a
  conclusão era manual.
- Nenhuma notificação, relatório ou fechamento automático adicional é
  disparado pela conclusão (critério de aceite já era satisfeito pela
  troca de status simples).
- 6 testes novos (marcar anexo permitido/bloqueado, correção do
  Administrador, concluir permitido/bloqueado, log da conclusão); suíte
  completa do repositório (385 testes) passando.
- Validação visual em navegador: não executada (sem Playwright/browser
  disponível neste ambiente) — sem tela nova nem alteração de HTML, só as
  duas regras novas no mesmo formulário já validado visualmente na
  FEAT-006; conferido via testes automatizados que exercitam a view e o
  template reais.
- **Pendência:** nenhuma.
**Pendência atual:** nenhuma.

---

### FEAT-011 — Auditoria estendida
**Descrição:** Estender `apps/auditoria` (reaproveitado) para cobrir
alteração de campo, transição de status, ação manual, envio/recebimento de
e-mail e erros, além do login já existente.
**Tipo:** backend-only
**Status:** 🔍 Aguardando QA
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
**Entrega do Dev:**
- Login, troca de status do RI, alteração de responsável/itens (Lado IXC
  e Lado Relatório EACE) e envio/recebimento de e-mail com o financeiro
  passam a gerar registro de auditoria.
- Qualquer erro não tratado durante o uso do sistema também é registrado
  automaticamente, sem depender de cada tela avisar.
- Sem tela própria nesta versão, como já previsto (RN-006) — consulta só
  por acesso direto ao banco.
- Registros não têm expiração.
- 12 testes automatizados novos cobrindo os pontos acima; suíte completa
  do repositório (379 testes) passando.
- **Pendência:** nenhuma.
**Pendência atual:** nenhuma. **Fora do escopo do Dev:** `architecture.md`
ainda descreve a Auditoria como "hoje só cobre login" (seção "Módulos e
Responsabilidades") — atualização desse trecho é do Orquestrador.

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

**Adicionado em 2026-08-25 (DevOps, a pedido do FEAT-009):** serviço
`email_scheduler` no `docker-compose.yml` (mesma imagem do `web`), roda o
comando `sincronizar_email_financeiro` a cada
`GRAPH_FINANCEIRO_POLL_INTERVAL_SECONDS` (padrão 300s, `.env.example`);
`docker compose config` validado. Falta replicar esse serviço quando o
`docker-compose.hml.yml` (pendência acima) for criado.

**Entrega do DevOps (2026-08-28):** usuário reportou logo quebrada num
deploy de homologação/produção separado deste ambiente local — causa:
`Dockerfile` sobe com `gunicorn` puro, que não serve arquivo estático
sozinho (o ambiente local só funciona porque roda `runserver` com
`DEBUG=True`, decisão já registrada acima). Fechando a pendência que
faltava:
- `docker-compose.hml.yml` — `db` (sem porta publicada, com healthcheck),
  `web` (`gunicorn` padrão do `Dockerfile`, sem bind mount), `nginx`
  (serve `/static`/`/media` dos volumes nomeados `staticfiles_hml`/
  `media_hml`, repassa o resto para o `web`) e `email_scheduler`. WhiteNoise
  descartado como alternativa — exigiria alterar `settings.py`, fora do
  escopo do DevOps (`.claude/agents/devops.md`).
- `docker/nginx/homolog.conf`, `.env.hml.example`,
  `scripts/deploy_homolog.sh` (atualiza código → sobe containers →
  migrations → collectstatic) e `.github/workflows/homolog.yml`
  (`manage.py check`/`test` + build Docker; deploy via SSH só em push
  direto na branch `homolog`, depois do CI passar).
- `docs_gerenciador_pos_venda/devops/` — `CONTAINERS.md`, `CI_CD.md`,
  `DEPLOYMENT.md`, `TROUBLESHOOTING.md` (inclui o próprio caso relatado,
  "logo quebrada", como primeiro item).
- `.gitignore` ganhou `.env.hml`/`*.hml.env`.
- **Validado neste ambiente** (build + subida completa do
  `docker-compose.hml.yml`, `migrate` + `collectstatic` reais,
  `docker compose down -v` ao final): as 3 logos e a tela de login
  carregam via Nginx na porta `8010` (HTTP 200, `Content-Type: image/png`
  correto) exatamente como seriam servidas em homologação.
**Pendência atual:** servidor de homologação real ainda não provisionado;
secrets do GitHub (`HML_HOST`, `HML_USER`, `HML_PORT`, `HML_SSH_KEY`,
`CI_CD.md`) ainda não cadastrados; domínio/HTTPS do Nginx ainda TODO. Sem
esses três itens, o pipeline builda e testa, mas o job de deploy não roda
de verdade ainda — mantendo `🔄 Em andamento` (não é `✅ Concluída` nem
`🔍 Aguardando QA`; esta feature `devops` usa validação técnica própria,
sem `QA-XXX`, conforme já registrado acima).

**Correção (2026-08-28):** usuário confirmou que a logo quebrada era num
servidor real já existente (`192.168.90.109:8000`, credencial em arquivo
local `ServidorEACE`, já sinalizado como risco de segurança — não
versionado, ver `.gitignore`). Diagnóstico confirmado por `curl` direto
nele: `runserver` (não Gunicorn) com `DEBUG=False` — mesmo problema já
descrito acima, servidor ainda não migrado para o `docker-compose.hml.yml`.
Tentativa de acessar via SSH para aplicar a migração foi bloqueada pelo
classificador de permissões do ambiente (duas vezes — direto e ao tentar
liberar a permissão); script temporário com a senha foi apagado sem deixar
nada exposto. Migração para lá **não foi aplicada** — passos manuais
documentados em `DEPLOYMENT.md` ("Migrando esse servidor para o
docker-compose.hml.yml"), incluindo o known IP/pasta desse servidor.

**Pendência (2026-08-28):** usuário confirmou que `192.168.90.109` é
servidor de **produção**, não homologação. Usuário deu autorização direta
ao DevOps para aplicar a correção, mas a regra de produção do próprio
agente (`.claude/agents/devops.md`, "Alterações em produção exigem
confirmação explícita do Orquestrador") não foi satisfeita — autorização
do usuário ao DevOps não substitui essa confirmação. DevOps não aplicou a
migração. Falta: (1) Orquestrador confirmar a mudança em produção; (2)
decidir se o `docker-compose.hml.yml` sobe reaproveitando o volume de
banco atual do servidor ou um volume novo vazio; (3) confirmar se
`/home/Sistem_PosVenda` é um checkout git com `origin` válido antes de
rodar `scripts/deploy_homolog.sh` lá.

**Confirmação do Orquestrador (2026-08-28):** autorização de produção
concedida, escopo restrito à correção do estático — ver `ADR-003`. DevOps
pode aplicar o stopgap `docker-compose.hml.yml` nesse servidor, desde que:
backup do MySQL antes de qualquer `up`/`migrate`; reaproveitar o volume de
dado existente (nunca subir volume novo vazio); confirmar que
`/home/Sistem_PosVenda` é checkout git com `origin` correto antes do `git
reset --hard` do script (senão, rodar os comandos manualmente); nenhum
comando destrutivo. Não autoriza criar ambiente de produção formal
(compose/branch/pipeline própria) — isso segue como pendência separada
(`architecture.md`, "Decisões Pendentes").

**Tentativa do DevOps (2026-08-28):** com a autorização acima, testei se
havia caminho automatizado — sem chave SSH cadastrada para este agente e
sem ferramenta de senha não-interativa disponível neste ambiente
(`sshpass`/`plink`); `ssh -o BatchMode=yes` ao servidor recusou com
`Permission denied (publickey,password)`, confirmando que só resta acesso
interativo com a senha real. Não tentei contornar isso instalando
ferramenta nova para automatizar senha de produção — é exatamente o tipo
de atalho já bloqueado antes (ver tentativa anterior acima). **Não
apliquei nenhuma mudança no servidor.** Passo a passo final, já com backup
e restauração do dado (preservação garantida via `mysqldump`/restore em
vez de reaproveitar o volume Docker diretamente), documentado em
`DEPLOYMENT.md` ("Migrando esse servidor...") para execução manual por
quem tiver a senha real.
**Pendência atual:** execução manual dos passos 1–8 de `DEPLOYMENT.md` por
alguém com acesso interativo ao servidor. Mantém `🔄 Em andamento`.

**Recusa registrada (2026-08-28):** usuário reenviou a senha do servidor e
ordenou pular o backup ("não precisa fazer backup, só rodar"). DevOps não
executou — backup é condição não negociável da `ADR-003`, e essa condição
é do Orquestrador, não algo que uma ordem ao DevOps possa remover
sozinha. Nenhum comando rodado no servidor.

**Execução concluída (2026-08-28), seguindo as 5 condições da `ADR-003`:**
1. Backup completo do MySQL (`mysqldump --all-databases`) feito e
   validado (`gzip -t`) no próprio servidor antes de qualquer comando,
   em `backups/backup_pre_nginx_hml_20260828.sql.gz`.
2. `docker-compose.hml.yml`, `docker/nginx/homolog.conf` e
   `scripts/deploy_homolog.sh` (ainda não commitados) enviados via
   `git commit`/`push` (`3125766`) e trazidos ao servidor com
   `git fetch`/`reset --hard` manual — o checkout real está na branch
   `feat-002-importar-escolas-planilha`, não `homolog`, então
   `deploy_homolog.sh` não pôde ser usado como está (mesma exceção
   prevista na condição 3 da ADR).
3. Volume de banco existente (`sistema_posvenda_posvenda_db_data`)
   reaproveitado via `docker-compose.hml.override.yml` (`external:
   true`) — nenhum volume novo de banco foi criado; `migrate` confirmou
   "No migrations to apply", provando que era o dado real.
4. Stack antigo derrubado sem `-v` (`docker compose -f
   docker-compose.yml down`, volume preservado) e stack novo (Nginx +
   web + db + email_scheduler) subido reaproveitando esse volume.
5. Nenhum comando destrutivo rodado.
**Validado:** `curl` confirma HTTP 200 nas 3 logos
(`/static/img/logo{1,2,3}.png`) e em `/login/`; contagem de escolas no
banco real confirmada em `2622` (nenhum dado perdido). Servidor
`192.168.90.109:8000` operando a partir do stack `docker-compose.hml.yml`
a partir de agora. Feature mantém `🔄 Em andamento` — pendências da
ADR-003 (ambiente de produção formal) continuam em aberto.

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
**Status:** 🔍 Aguardando QA
**Prioridade:** Média — não bloqueia o caminho crítico do faturamento
(FEAT-004 a FEAT-010), é um registro de acompanhamento complementar.
**Critérios de aceite:**
- Dentro da tela do RI, usuário escreve uma mensagem e ela aparece na
  linha do tempo, mais recente primeiro.
- Usuário consegue anexar um arquivo (à mensagem ou como entrada própria).
- Envio de e-mail a partir dessa tela (reaproveitando a infra já prevista
  na FEAT-008) gera entrada na linha do tempo; e-mail recebido em resposta
  (mesmo polling da FEAT-009) também aparece. **Adiado** — ver pendência.
- Mudança de status do RI e de campo relevante geram entrada automática
  estruturada (rótulo + valor anterior/novo), não só uma frase livre.
- **(2026-08-26)** Cadastro, edição e exclusão de item do Lado IXC (KIT
  Instalado, Produto, Data de Ativação, Município/Estado) e cadastro de
  item do Relatório EACE geram entrada própria na linha do tempo (RN-008
  esclarecida) — hoje só a troca de status e a troca de responsável
  (RN-012) geram log.
**Regras relacionadas:** RN-008. Sem RF associado em
`requisitos-validacao-cliente.html` — pedido tratado como reaproveitamento
técnico do `modulo-posVenda`, não como novo requisito formal (usuário
pediu para não alterar os requisitos).
**Dependências:** FEAT-004 (tela do RI já existe), FEAT-006 (transições de
status a registrar).
**Tipo de validação:** QA (QA-014) — ver pendência sobre o critério de
e-mail, adiado com autorização do usuário.
**Entrega do Dev:**
- Log automático (rótulo + valor anterior/novo) cobre: troca de status,
  troca de responsável, e cadastro/edição/exclusão de KIT/Produto/Data de
  Ativação/Município/Estado do Lado IXC e cadastro do Relatório EACE.
  Cadastro novo (sem valor anterior) aparece como "Cadastrou", não
  "Alterou".
- **(2026-08-26)** Linha do tempo passa a paginar de 10 em 10 — página
  seguinte só é consultada quando o usuário clica na paginação (pedido do
  usuário para não trazer o histórico inteiro de uma vez).
- Tipo "e-mail" já existe no modelo, pronto para quando a FEAT-008/009
  passarem a gravar ali — sem produtor ainda (ver pendência).
- 9 testes novos (logs de cadastro/edição/exclusão e paginação); suíte
  completa do app (140 testes) passando.
- Validação visual em navegador: não executada nesta correção —
  comportamento conferido via teste automatizado do HTML renderizado, não
  em navegador real.
**Pendência atual:** o critério de e-mail (envio/recebimento) depende da
FEAT-008/FEAT-009, ainda `⬜ Pendente` — usuário autorizou explicitamente
adiar essa parte e implementar o resto agora; QA-014 deve cobrir os 3
critérios restantes, não o de e-mail. **Correção pendente (2026-08-26):**
usuário reportou, antes da validação do QA, que a linha do tempo só grava
a troca de status — não grava o cadastro/edição/exclusão dos itens do
Lado IXC nem o cadastro do Relatório EACE (RN-008 esclarecida); Dev
corrige antes de seguir para o QA.

---

### FEAT-015 — Catálogo de preços fixos EACE (LPU) e integração ao Kit Declarado por Lote
**Descrição:** Evoluir o catálogo `KitPadrao` (RN-010) para guardar os
valores reais de Equipamento e Serviço por Lote e criar o comando de
importação em lote a partir da aba `LPU` de `CONSOLIDADO EACE.xlsx`,
corrigindo o cruzamento com o Kit Declarado para considerar também o Lote
da escola, não só a descrição do kit.
**Tipo:** backend-only
**Status:** 🔍 Aguardando QA
**Prioridade:** Alta — desbloqueia a carga real do Kit Declarado (1º
lado), hoje travada por falta de valores no catálogo (nota da FEAT-004).
**Critérios de aceite:**
- Model `KitPadrao` evoluído com `lote`, `unidade`, `valor_equipamento` e
  `valor_servico` (formato de campo final é decisão do Dev); chave única
  de negócio (`descricao`, `lote`).
- Comando de importação (mesmo padrão de `importar_escolas_planilha`,
  FEAT-002) lê a aba `LPU` de `CONSOLIDADO EACE.xlsx` e popula o catálogo
  para os Lotes hoje mapeados (`9` e `11`), sem duplicar em reexecução.
- Cruzamento usado pela RN-010 para resolver Quantidade/Valor do Kit
  Declarado passa a considerar `Escola.kit_inicial` **e** `Escola.lote`
  (não só a descrição). **Atendido no nível do catálogo** (chave
  `descricao`+`lote` implementada); não existe hoje código que crie
  `RiItemEace` automaticamente — geração automática é uma feature futura,
  fora do escopo desta.
- Django admin do catálogo atualizado com os novos campos e filtro por
  lote.
- Escola sem `lote` ou sem correspondência exata (descrição + lote) no
  catálogo mantém o bloqueio já existente (RN-010) — nenhum item gravado
  com valor inventado.
- ~~Antes de fechar a feature, Dev confirma e registra se as "Lote
  1"/"Lote 2/3" citadas na FEAT-004 correspondem ao mesmo `Escola.lote`
  usado pela LPU~~ — **verificado pelo Orquestrador (2026-08-24): não
  são o mesmo campo** (ver nota na FEAT-004); critério removido, não
  bloqueia mais o fechamento desta feature.
**Regras relacionadas:** RN-010.
**Dependências:** FEAT-002 (`Escola.lote`/`kit_inicial`), FEAT-004
(`RiItemEace` e o catálogo `KitPadrao` já existem).
**Tipo de validação:** QA (QA-015).
**Entrega do Dev (2026-08-24):**
- Model `KitPadrao` evoluído: campos `lote`, `unidade`,
  `valor_equipamento` e `valor_servico` (substituem o valor único
  anterior); chave única por descrição + lote; migration aplicada.
- Comando `importar_catalogo_lpu` (mesmo padrão do comando de Escola):
  lê a aba `LPU` do `CONSOLIDADO EACE.xlsx`, ignora linha de seção e o
  rodapé de notas, seguro para reexecutar (atualiza em vez de duplicar).
- Rodado contra a planilha real: 80 registros criados (40 itens × 2
  Lotes, 9 e 11) — confere com a Tabela 1 da aba LPU, nenhuma linha
  ignorada.
- Django admin do catálogo atualizado com os novos campos e filtro por
  Lote/Unidade.
- 14 testes novos (valores por lote, item sem valor de equipamento,
  seção ignorada, rodapé de notas ignorado, reimportação idempotente,
  chave única); suíte completa do app (59 testes) passando.
- **Fora do meu escopo, sinalizando para o Orquestrador:** não existe
  hoje nenhuma tela/comando que crie `RiItemEace` automaticamente a
  partir do catálogo — o lançamento manual foi removido antes desta
  feature (nota da FEAT-004), então o critério "corrigir o cruzamento"
  não tem código vivo para corrigir. A chave (descrição + lote) já está
  pronta para quando essa geração automática existir.
**Pendência atual:** "Lote 1"/"Lote 2/3" da FEAT-004 verificado pelo
Orquestrador — não é `Escola.lote` (ver nota na FEAT-004); não bloqueia
mais esta feature. Usuário decidiu (2026-08-24) manter `RiItemEace` com
Valor Unitário único, sem discriminar Equipamento/Serviço (RN-010) —
pendência encerrada. Continua em aberto, sem bloquear esta feature, a
geração automática de `RiItemEace` a partir do catálogo (sem tela/
comando ainda), fica para uma feature futura. Validação visual: não se
aplica (feature backend-only, sem tela).

---

### FEAT-016 — Cruzamento por número de Access Points (Kit Declarado × catálogo)
**Descrição:** Em parte das escolas, `Escola.kit_inicial` (1º lado, Kit
Declarado) não traz o texto completo do kit, só o número informado pela
EACE (ex.: `4`), enquanto o catálogo `KitPadrao` (usado no 2º lado, IXC)
guarda o nome completo (ex.: "Kit Cobertura Wi-Fi - 4 Access Points").
Como esse número sempre corresponde à quantidade de Access Points do kit,
a feature cria uma coluna própria no catálogo para o cruzamento, em vez de
comparar o texto inteiro.
**Tipo:** backend-only
**Status:** 🔍 Aguardando QA
**Prioridade:** Média — não bloqueia nenhuma feature em aberto, mas evita
divergência falsa na comparação estrita da RN-002 para escolas nesse
formato.
**Critérios de aceite:**
- Novo campo `KitPadrao.numero_access_points` (inteiro, opcional),
  derivado automaticamente da Descrição ao salvar — mesmo padrão de
  `descricao_curta` (RN-011): extrai o número que precede "Access
  Points"; fica vazio para itens que não seguem esse padrão (avulsos:
  km, enlace, metro, par).
- Quando `Escola.kit_inicial` for só um número, o cruzamento com o
  catálogo usa `numero_access_points` (e `Escola.lote`, quando houver)
  em vez do texto completo da Descrição.
- Django admin do catálogo exibe o novo campo.
- Comportamento já existente para `Escola.kit_inicial` com texto completo
  (RN-010 original) não muda.
- Testes: derivação automática a partir da Descrição; ausência de
  derivação quando a Descrição não segue o padrão; cruzamento correto
  para `Escola.kit_inicial` numérico.
**Regras relacionadas:** RN-010 (ampliada, 2026-08-24), RN-002.
**Dependências:** FEAT-015 (`KitPadrao` já com `lote`/`unidade`/valores).
**Tipo de validação:** QA (QA-016).
**Entrega do Dev (2026-08-25):**
- Campo `KitPadrao.numero_access_points` (inteiro, opcional), derivado
  automaticamente da Descrição ao salvar (mesmo padrão de
  `descricao_curta`, RN-011); migration `0009` aplicada.
- Método `KitPadrao.resolver_kit_declarado(kit_inicial, lote=None)`: cruza
  por `numero_access_points` quando `kit_inicial` é só um número, ou pela
  Descrição completa quando não é (comportamento original preservado);
  sempre restringe por Lote quando informado.
- Django admin do catálogo exibe o novo campo.
- 7 testes novos (derivação automática, ausência de derivação, valor
  digitado à mão preservado, cruzamento por número, por texto completo,
  sem correspondência, respeito ao Lote); suíte completa do app `ri` (83
  testes) passando.
**Correção (2026-08-25):** migration `0009` só tinha sido aplicada no
banco de teste — o container real (`sistema_posvenda-web-1`/`-db-1`)
ficou sem a coluna e quebrou `/inep/<inep>/` (`OperationalError: Unknown
column 'ri_kitpadrao.numero_access_points'`) até o `migrate` ser
executado nele. Confirmado corrigido (`showmigrations` com as 9
migrations de `ri` aplicadas no container).
**Entrega complementar (2026-08-25) — usuário testou e não viu diferença:**
usuário esperava ver a descrição completa no lugar do número bruto no
card "Kit Declarado (1º lado)". Duas causas encontradas e corrigidas: (1)
`ri_detail_view`/`ri_detail.html` mostravam `Escola.kit_inicial` direto,
sem chamar `resolver_kit_declarado` — corrigido, agora resolve e cai para
o valor bruto só quando não há correspondência (nenhum valor inventado,
CLAUDE.md §9); (2) os 80 registros do catálogo (FEAT-015) já existiam
antes do campo `numero_access_points` e nunca foram salvos de novo, então
ficaram todos com o campo vazio — migration de dados `0010` (RunPython)
preencheu os já cadastrados. Confirmado no INEP real relatado pelo
usuário (35275505, kit "4" → resolve para "Kit Cobertura Wi-Fi - 4 Access
Points..."). 2 testes novos; suíte completa do app `ri` (85 testes)
passando.
**Ajuste visual (2026-08-25, sem relação com RN-010):** usuário pediu para
tirar o valor (R$) do resumo de cada item da lista do Lado IXC — sempre,
mesmo quando o item já tem valor real editado (RN-004). A lista passa a
mostrar só a quantidade ("2 un."); o valor continua editável no formulário
de edição do item, sem mudança ali. Ajuste puramente visual
(frontend-layout), sem lógica — suíte completa do app `ri` (85 testes)
confirmada passando.
**Ajuste (2026-08-25):** usuário pediu a mesma nomenclatura do Lado IXC —
o painel mostrava a Descrição completa (com o qualificador entre
parênteses), grande demais para o campo e cortada visualmente. Passa a
usar a Descrição curta (RN-011, mesmo campo já usado nas listas do Lado
IXC): "Kit Cobertura Wi-Fi - 4 Access Points", sem o texto entre
parênteses. Suíte completa do app `ri` (85 testes) passando.
**Correção (2026-08-25, sem relação com RN-010):** usuário pediu para
excluir do banco o texto entre parênteses (ex.: "(serviços, materiais e
equipamentos)"). Verificado antes de agir: `KitPadrao.descricao` (80
registros, todos com parênteses) é o texto original da planilha LPU,
usado pelo comando `importar_catalogo_lpu` para não duplicar em
reimportação — **não alterado**, risco de duplicar o catálogo. A causa
real era outra: `RiItemIxc.descricao_item` gravava a Descrição completa
do catálogo em vez da curta (RN-011) ao lançar KIT/Produto — bug em
`forms.py`/`views.py`, corrigido; migration de dados `0011` limpou os 2
itens já salvos com parênteses (RI #3). `RiItemEace`/`RiItemRelatorioEace`
não tinham nenhum registro afetado. Usuário confirmou o plano antes da
execução. 2 testes novos; suíte completa do app `ri` (87 testes)
passando.
**Pendência atual:** cruzamento ainda sem tela/comando que o chame —
segue o mesmo caso já registrado na FEAT-015 (não existe hoje geração
automática de `RiItemEace`); `resolver_kit_declarado` fica pronto para
quando essa geração existir. Validação visual: não se aplica
(feature backend-only, sem tela).

---

### FEAT-017 — Anexo do financeiro em planilha (substitui PDF), com aba por produto
**Descrição:** E-mail ao financeiro (FEAT-008) passa a anexar a planilha
de faturamento preenchida (modelo `doc/FATURAMENTO MATERIAS EACE.xlsx`),
com uma aba por produto distinto lançado no Lado IXC, no lugar do PDF
gerado hoje; tela de composição ganha um botão para baixar essa planilha
antes de enviar.
**Tipo:** fullstack
**Status:** 🔍 Aguardando QA
**Prioridade:** Alta — muda o anexo padrão do fluxo de faturamento já em
produção (FEAT-008).
**Critérios de aceite:**
- Anexo automático do e-mail (FEAT-008) passa a ser a planilha preenchida
  (RN-013), no lugar do PDF de `gerar_pdf_dados_financeiro` (removida);
  campo Anexo manual da tela de composição continua existindo, sem
  mudança.
- Uma aba por produto distinto lançado no Lado IXC do RI (KIT incluso).
  Produto sem aba já cadastrada **não bloqueia** — ganha uma aba nova,
  criada na hora, clonando layout e logo de uma aba já existente
  (RN-013). `KitPadrao.aba_planilha_financeiro` é atalho opcional para
  juntar produtos parecidos numa aba compartilhada.
- Preenchimento de cada aba segue RN-013 (linha 10: `E`/`F`/`H`; linha 12:
  fórmula do modelo preservada; linha 16: `C`/`F`/`G`/`H`/`I`); demais
  células iguais ao modelo, sem alterar estrutura, texto ou espaçamento.
- Envio de e-mail e "Baixar planilha" bloqueiam, com 1 mensagem só
  listando o que falta, quando o RI não tem KIT lançado (RN-015), Data de
  Ativação, Município ou Estado do Lado IXC (RN-014) — checado só nesse
  momento, não a cada "Salvar" do Lado IXC.
- Botão "Baixar planilha" na tela de composição de e-mail (FEAT-008) gera
  e baixa a mesma cópia que seria anexada, sem enviar o e-mail.
**Regras relacionadas:** RN-008, RN-013, RN-014, RN-015.
**Dependências:** FEAT-008 (🔍 Aguardando QA), FEAT-018 (Município/Estado
do Lado IXC).
**Tipo de validação:** QA (QA-017).
**Entrega do Dev (consolidada — passou por 3 ajustes no mesmo dia, ver
histórico):**
- Anexo automático do e-mail (e "Baixar planilha") gera a planilha a
  partir do modelo `doc/FATURAMENTO MATERIAS EACE.xlsx`, no lugar do PDF;
  uma aba por produto distinto lançado no Lado IXC (KIT incluso), demais
  abas do modelo fora da cópia final.
- Produto sem aba já cadastrada ganha aba nova, criada na hora (clona
  layout e logo de uma aba existente, nome truncado a 31 caracteres —
  limite do Excel); `KitPadrao.aba_planilha_financeiro` é atalho opcional
  para juntar produtos numa aba compartilhada (ex.: Rack 3U/5U/7U →
  "RACK").
- Envio/download bloqueiam, com 1 mensagem só, quando falta KIT lançado
  (RN-015), Data de Ativação, Município ou Estado do Lado IXC (RN-014) —
  verificado só nesse momento, não a cada "Salvar".
- Botão "Baixar planilha" na tela de composição gera e baixa a mesma
  cópia que seria anexada, sem enviar e-mail.
- Suíte completa dos apps `ri`+`core`: 132 testes passando.
- Validado no navegador real (Docker): fluxo completo (lançar KIT/produto
  → compor e-mail → baixar planilha) conferido célula a célula, com e sem
  aba cadastrada, logo presente em toda aba, bloqueio quando falta dado
  obrigatório. Envio real de e-mail (SMTP) não foi disparado — coberto só
  pelos testes automatizados, para não mandar e-mail de verdade.
- **Pendência:** nenhuma.
**Histórico:** bloqueio por produto sem aba virou criação automática,
depois de erro relatado em produção ("Nobreak" sem cadastro); logo sumia
nas abas criadas na hora (limitação do `openpyxl.copy_worksheet`,
corrigida); exigência de KIT/Data de Ativação/Município/Estado tentou
travar o "Salvar" antes de o usuário esclarecer que trava só o
envio/download (RN-013 detalha o desenho final). Correção 2026-08-26
(pós-entrega, reportada pelo usuário via e-mail real enviado): o corpo do
e-mail (texto) mostrava todo item e o total zerados — usava
`RiItemIxc.valor_unitario` (nasce 0,00) em vez do valor do catálogo
`KitPadrao`, mesma origem já usada na planilha anexa; corrigido para
buscar o valor do catálogo também no texto; suíte `ri`+`core`: 156 testes
passando.

---

### FEAT-018 — Município e Estado manuais no Lado IXC
**Descrição:** Painel "Lado IXC" (RN-011) ganha campos Município e Estado
(UF, 2 letras), preenchidos manualmente e usados na planilha de
faturamento (FEAT-017); divergência contra o cadastro da Escola gera só
alerta visual (RN-014).
**Tipo:** fullstack
**Status:** 🔍 Aguardando QA
**Prioridade:** Alta — dependência de FEAT-017.
**Critérios de aceite:**
- Campos Município (texto livre) e Estado (2 letras) na mesma submissão
  do formulário único do Lado IXC (`salvar_ixc`, RN-011) — opcionais, não
  travam o "Salvar"; exigidos, junto com KIT (RN-015) e Data de Ativação,
  só na hora de enviar o e-mail ou baixar a planilha (RN-013).
- Estado aceita só 2 letras (UF), sempre gravado em maiúsculas.
- Quando os dois lados (Lado IXC × `Escola.municipio`/`Escola.estado`)
  têm valor e divergem, o campo correspondente fica com alerta visual
  (borda + texto); não bloqueia o avanço de status do RI.
- Campo vazio de qualquer um dos lados não gera alerta.
- RI só pode ter 1 KIT lançado (RN-015) — seletor "KIT Instalado" some da
  tela quando já existe um; trocar é por editar/excluir o item já
  lançado (RN-004).
- Valores ficam disponíveis para a geração da planilha de faturamento
  (FEAT-017/RN-013).
**Regras relacionadas:** RN-011, RN-013, RN-014, RN-015.
**Dependências:** nenhuma nova (mesma tela/formulário da FEAT-004).
**Tipo de validação:** QA (QA-018).
**Entrega do Dev (consolidada — passou por 4 ajustes no mesmo dia, ver
histórico):**
- Campos Município (Lado IXC) e Estado (UF) no formulário único do Lado
  IXC, salvos junto com a Data Ativação (`Ri.municipio_ixc`/`Ri.
  estado_ixc`); Estado sempre gravado em maiúsculas, validado com 2
  letras.
- Município/Estado opcionais a cada "Salvar" — exigidos, junto com KIT e
  Data de Ativação, só na hora de enviar e-mail/baixar planilha
  (RN-013), com 1 mensagem só listando o que falta.
- Divergência contra `Escola.municipio`/`Escola.estado` mostra alerta
  visual (borda + texto), sem bloquear.
- RI só pode ter 1 KIT lançado (RN-015): seletor some da tela quando já
  existe um, bloqueado também no servidor contra POST direto.
- Suíte completa dos apps `ri`+`core`: 132 testes passando.
- Validado no navegador real (Docker): campos, alerta, obrigatoriedade
  no envio/download com mensagem em português, limite de 1 KIT — desktop,
  celular, modo escuro.
- **Pendência:** nenhuma; senha do usuário local `admin` foi redefinida
  temporariamente durante uma das validações (mesmo precedente da
  FEAT-013) — trocar se for usar esse login.
**Histórico:** obrigatoriedade de Município/Estado tentou travar o
"Salvar" (com 2 correções no meio — idioma da mensagem nativa do
navegador, depois mensagem duplicada) antes de o usuário esclarecer que
deve travar só o envio/download, junto com KIT e Data de Ativação
(RN-013); limite de 1 KIT por INEP (RN-015) pedido em seguida, no mesmo
dia.

---

### FEAT-019 — Atualizações sem reload completo da página (HTMX)

**Descrição:** Troca de status do RI, troca de responsável e registro de
histórico/log passam a atualizar só o trecho da tela afetado (via HTMX,
ver `architecture.md`, "Padrão de Interação Frontend"), em vez de
recarregar a página inteira — hoje o usuário perde a posição de rolagem e
o filtro aplicado no grid a cada ação.
**Tipo:** fullstack
**Status:** 🔍 Aguardando QA
**Prioridade:** Média — melhoria de uso sobre telas já entregues, sem
bloquear nenhuma feature nova.
**Critérios de aceite:**
- Troca de status do RI (`ri_status_update_view`, drill-down do grid da
  FEAT-007 e tela da FEAT-004) não recarrega a página; posição de
  rolagem e filtros do grid continuam como estavam.
- Troca de responsável (`ri_responsavel_update_view`) tem o mesmo
  comportamento, nos mesmos dois pontos de tela.
- Registro de histórico/log (FEAT-014) reflete a ação (nova entrada na
  linha do tempo) sem reload completo.
- Mensagem de sucesso/erro (`django.contrib.messages`) continua visível
  em todos os três casos.
- Sem JavaScript no navegador, as três ações continuam funcionando pelo
  fluxo tradicional (POST + redirect) — HTMX é aprimoramento, não
  requisito para o fluxo funcionar.
- Nenhuma regra de permissão (RN-004/RN-012) muda.
**Regras relacionadas:** RN-012 (troca de responsável); nenhuma regra nova.
**Dependências:** FEAT-004, FEAT-007, FEAT-014 (telas e views já
implementadas que serão adaptadas).
**Tipo de validação:** QA (QA-019).
**Entrega do Dev:**
- HTMX carregado via CDN (mesmo padrão do Tailwind/Lucide) só nas 3 ações
  previstas — status do RI, responsável e histórico; as demais ações da
  tela do RI (Lado IXC, Relatório EACE) não foram tocadas.
- As views respondem com um fragmento (badge, formulário, linha do tempo
  e toast, por troca out-of-band) quando a requisição vem do HTMX; sem
  esse header, continuam com o POST + redirect de sempre, inalterado.
- Suíte completa (150 testes, 5 novos cobrindo os fluxos HTMX) passando.
- Validado no navegador real (Docker, claro e escuro): troca de
  status/responsável no drill-down do grid e no cabeçalho do RI, e envio
  de mensagem no histórico — nenhuma ação recarrega a página, a linha do
  drill-down continua expandida, mensagem aparece em toast.
- **Nota:** "Status do RI" só existe no drill-down do grid (FEAT-007) — a
  tela de detalhe (FEAT-004) sempre mostrou o status como texto fixo, sem
  formulário; o critério de aceite cita "tela da FEAT-004" para o status,
  mas não existe esse formulário lá para adaptar.
- **Pendência:** senha do usuário local `admin` foi redefinida durante a
  validação (mesmo precedente da FEAT-013) — a pedido do usuário, ficou
  como `admin`; o RI de teste (INEP 35244752) ficou com status
  "Aguardando validação EACE" e responsável "admin" como resíduo da
  validação.

---

### FEAT-020 — Status "Resposta Financeiro" e card de contagem no grid

**Descrição:** Renomeia o status 5 do ciclo de vida do RI (RN-001) de
"Aguardando Anexo portal EACE" para "Resposta Financeiro" e estende o
gatilho automático que leva o RI até ele: qualquer resposta do financeiro
identificada pelo código de rastreio (RN-009) agora muda o status — antes
só a resposta no padrão (1 PDF + 1 XML) mudava, a fora do padrão ficava
parada em "Aguardando financeiro". O grid de INEPs (FEAT-007) ganha um 3º
card de contagem, no mesmo padrão dos 2 já existentes.
**Tipo:** fullstack
**Status:** 🔍 Aguardando QA
**Prioridade:** Média
**Critérios de aceite:**
- Rótulo "Aguardando Anexo portal EACE" passa a "Resposta Financeiro" em
  todo lugar que exibe o status (filtro do grid, badge, drill-down,
  `ri_detail`, histórico) — mesmo valor interno no banco, sem migração de
  dado nem novo status na sequência da RN-001.
- Resposta do financeiro fora do padrão (sem 1 PDF + 1 XML reconhecíveis)
  passa a mudar o status para "Resposta Financeiro", igual à resposta
  válida — deixa de ficar parada em "Aguardando financeiro"; RN-005
  continua sem bloquear em nenhum dos dois casos.
- Grid de INEPs (`grid_inep.html`) ganha um 3º card ao lado de "Total de
  INEPs" e "Com divergência", mesmo estilo visual, com a contagem de INEPs
  cujo RI atual está em "Resposta Financeiro".
- Clique no novo card filtra o grid pelo status "Resposta Financeiro"
  (mesmo efeito de escolher esse valor no filtro "Status do RI" já
  existente).
**Regras relacionadas:** RN-001, RN-005, RN-009, RN-016.
**Dependências:** FEAT-007 (grid, `🔍 Aguardando QA`), FEAT-009 (leitura da
resposta do financeiro, `🔍 Aguardando QA`) — mesmo precedente já usado
antes de depender de feature ainda não aprovada pelo QA.
**Tipo de validação:** QA (QA-020).
**Entrega do Dev:**
- Rótulo do status renomeado (`Ri.STATUS_CHOICES`), com migração `0016`
  só de metadado (sem alterar dado gravado — RI já nesse status continuam
  íntegros).
- `_processar_mensagem` (sincronização do e-mail) passa a avançar o status
  também na resposta fora do padrão, não só na válida.
- 3º card criado no grid, com a contagem e o link de filtro por "Resposta
  Financeiro"; mesmo estilo visual dos 2 cards existentes.
- Resumo do comando `sincronizar_email_financeiro` corrigido para não
  subestimar quantos RI mudaram de status (antes só contava a resposta no
  padrão).
- Suíte completa (164 testes, 2 novos + 2 ajustados) passando.
- Validado no app real (Docker) com um e-mail de resposta de teste enviado
  pelo próprio usuário à caixa do financeiro: rodada manual do comando
  identificou a resposta (fora do padrão, sem NF/XML anexados) e moveu o
  RI correspondente (INEP 35079844) de "Aguardando financeiro" para
  "Resposta Financeiro" — confirmado no histórico do RI.
- **Pendência:** nenhuma.

---

### FEAT-021 — Nobreak declarado (1º lado): item padrão para toda escola
**Descrição:** Toda Escola passa a ter também um Nobreak declarado, além
do Kit (RN-002/RN-010) — um item padrão único, igual para as 2.622
escolas, sem valor financeiro, exibido junto ao Kit no card "Kit
declarado (1º lado)".
**Tipo:** fullstack
**Status:** 🔍 Aguardando QA
**Prioridade:** Média
**Critérios de aceite:**
- Novo campo em `Escola` (análogo a `kit_inicial`) guarda o Nobreak
  declarado; migration de dados preenche o mesmo valor padrão nas 2.622
  escolas já migradas (FEAT-002).
- Escola nova (importação futura ou cadastro) já nasce com o valor
  padrão, sem passo manual.
- Nobreak aparece junto ao Kit no card "Kit declarado (1º lado)": tela do
  RI (`ri_detail.html`) e drill-down do grid (`grid_inep.html`,
  FEAT-007), sempre com quantidade 1 (fixa).
- Nobreak não tem valor unitário, não entra no catálogo `KitPadrao` nem
  no cálculo financeiro do RI (RN-017).
- IXC (2º lado) e Relatório EACE (3º lado) continuam sem alteração.
**Regras relacionadas:** RN-002, RN-010, RN-017.
**Dependências:** FEAT-002 (Escola, `🔍 Aguardando QA`), FEAT-004 e
FEAT-007 (telas onde o 1º lado aparece, ambas `🔍 Aguardando QA`) — mesmo
precedente já usado antes de depender de feature ainda não aprovada pelo
QA.
**Tipo de validação:** QA (QA-021).
**Entrega do Dev:**
- Campo `Escola.nobreak_inicial` criado (migration `0002`, com valor
  padrão `"Nobreak"` já aplicado às 2.622 escolas existentes e a toda
  escola nova, sem passo manual).
- Nobreak exibido junto ao Kit no card "Kit declarado (1º lado)", com
  quantidade fixa "1 un.": tela do RI e drill-down do grid.
- 4 testes novos, suíte completa (170 testes) passando.
- Validado no app real (Docker), desktop (1366px) e celular (390px): os
  dois pontos renderizam sem quebra, com usuário e RI já existentes no
  banco de dev.
- **Pendência:** durante a implementação, usuário pediu que a quantidade
  do Nobreak seja sempre 1 — já implementado na exibição; falta o
  Orquestrador formalizar esse critério em `business_rules.md`
  (RN-017, hoje só menciona "sem quantidade") e no checklist, pois é
  regra de negócio/critério de aceite, fora do escopo do Dev.

---

### FEAT-022 — Lado Relatório EACE ganha o formulário do Lado IXC (KIT Instalado + Produtos)
**Descrição:** O painel "Relatório EACE" (3º lado, `ri_detail.html`) passa
a usar o mesmo formulário já implementado no Lado IXC (RN-011): "KIT
Instalado" (catálogo `KitPadrao`) + "Produtos" via botão "+", sem Data
Ativação, Município ou Estado — campos exclusivos do Lado IXC. Valor
Unitário passa a ser preenchido automaticamente pelo catálogo (RN-018), em
vez de digitado manualmente.
**Tipo:** fullstack
**Status:** 🔍 Aguardando QA
**Prioridade:** Alta — usuário pediu paridade de campos com o Lado IXC.
**Critérios de aceite:**
- Campo "Descrição do item" livre some do lançamento novo do Lado
  Relatório EACE; a descrição do KIT/Produto vem do catálogo `KitPadrao`
  (Descrição curta, RN-011), com opção "Outro" para o KIT.
- Valor Unitário do item lançado vem do `KitPadrao` (preço por Lote), sem
  digitação manual (RN-018) — diferente do Lado IXC, que nasce em R$ 0,00.
  Quantidade do KIT é sempre 1; Quantidade de cada Produto é digitada
  manualmente.
- Painel não exibe nem lança Data Ativação, Município ou Estado.
- RI só pode ter 1 item marcado como KIT no Lado Relatório EACE (RN-015
  estendida pela RN-018) — campo "KIT" some da tela quando já existe um.
- Diferente dos itens "Produtos" desse lado (continuam sem editar/
  excluir), o item marcado como KIT pode ser editado/excluído — exclusão
  restrita a Administrador (RN-004), mesma regra já aplicada no Lado IXC.
- Card "Relatório EACE (3º)" do drill-down do grid (FEAT-007) continua
  mostrando descrição, quantidade e valor — agora resolvido pelo catálogo.
**Regras relacionadas:** RN-003, RN-004, RN-010, RN-011, RN-015, RN-018.
**Dependências:** FEAT-004 (mesma tela/formulário), FEAT-015 (catálogo
`KitPadrao` já com preços por Lote).
**Tipo de validação:** QA (QA-022).
**Entrega do Dev:**
- Painel "Relatório EACE (3º lado)" ganhou "KIT Instalado" (catálogo,
  + "Outro") e "Produtos" via "+", mesmo mecanismo do Lado IXC.
- Valor Unitário do item lançado vem do catálogo `KitPadrao`, sem
  digitação; Data Ativação/Município/Estado não aparecem nesse painel.
- Limite de 1 KIT por INEP aplicado também aqui; o item KIT (só ele)
  pode ser editado/excluído — exclusão restrita a Administrador.
- Suíte completa do app `ri` (159 testes) passando.
- Validado no navegador real (Playwright, servidor local): desktop
  (1366px) e celular (390px), opção "Outro" e "+" de Produtos
  funcionando, sem erro de console.
- **Pendência:** nenhuma.
**Correção (2026-08-27):** editar/excluir, antes só do item KIT, passa a
valer também para os itens "Produtos" desse lado (exclusão continua só
Administrador) — usuário testou o Sincronizador (FEAT-024) e não
conseguiu excluir um Produto casado errado; `business_rules.md` (RN-003/
RN-018) atualizado com a ampliação.

---

### FEAT-023 — Administrador > Planilha EACE (upload)
**Descrição:** Novo grupo de menu "Administrador" (visível só a quem tem
`user.is_administrador`, RN-004) com a opção "Planilha EACE": tela de
upload do arquivo `.csv` de faturamento por INEP (mesmo layout de
`doc/EACE.csv`), que substitui o arquivo ativo anterior. Não copia linhas
para tabela própria — o arquivo em si é a fonte usada pelo Sincronizador
(FEAT-024).
**Tipo:** fullstack
**Status:** 🔍 Aguardando QA
**Prioridade:** Alta — pré-requisito da FEAT-024 (Sincronizador).
**Critérios de aceite:**
- Menu lateral ganha grupo "Administrador" (só visível a
  `user.is_administrador`) com item "Planilha EACE".
- Tela de upload aceita `.csv`; valida colunas mínimas (Projeto, Descrição
  do Item, Qtde Produto, Valor Unit UR) antes de aceitar; rejeita com
  mensagem objetiva se faltar alguma.
- Upload bem-sucedido substitui o arquivo ativo anterior (no máximo 1
  ativo por vez).
- Tela mostra nome do arquivo ativo, quem enviou e quando.
- Ação bloqueada para usuário sem perfil Administrador.
- Testes: upload válido, upload com coluna faltando, substituição do
  arquivo anterior, bloqueio para Analista.
**Regras relacionadas:** RN-021, RN-004 (ampliada).
**Dependências:** FEAT-003 (perfis de usuário).
**Tipo de validação:** QA (QA-023).
**Entrega do Dev (2026-08-27):**
- Menu "Administrador > Planilha EACE" (só para `is_administrador`) e tela
  de upload do `.csv`, com validação das 4 colunas mínimas.
- Novo model `PlanilhaEace` (singleton — upload novo remove o arquivo
  anterior do disco e do banco); sem tabela de linhas.
- Ação bloqueada (403) para Analista, na tela e na rota direta.
- 5 testes novos (upload válido, coluna faltando, substituição, bloqueio
  Analista, exibição do arquivo ativo); suíte completa dos apps `ri`,
  `core` e `escolas` (205 testes) sem regressão nova — os 6 erros
  restantes são pré-existentes em `apps.escolas` (trava de arquivo do
  Windows ao limpar `.xlsx` temporário de teste), fora do escopo desta
  feature.
- Validado no navegador real (Playwright, servidor local): desktop
  (1366px) e celular (390px), upload real do `doc/EACE.csv` confirmado
  na tela, sem erro de console.
- **Pendência:** nenhuma.
**Correção (2026-08-27):** migration `0020_planilhaeace` só tinha sido
aplicada no banco de teste (sqlite local) — o container real
(`sistema_posvenda-web-1`/`-db-1`, MySQL) ficou sem a tabela e quebrou
`/administrador/planilha-eace/` (`ProgrammingError: Table
'ri_planilhaeace' doesn't exist`) até o `migrate` ser executado nele.
Mesmo padrão já registrado na FEAT-016. Confirmado corrigido
(`showmigrations` com as 20 migrations de `ri` aplicadas no container).
**Correção (2026-08-27):** input do arquivo mostrava o texto nativo do
navegador em inglês ("Choose File"/"No file chosen") — trocado por botão
"Escolher arquivo" + texto "Nenhum arquivo selecionado"/nome do arquivo
escolhido, em português (input original só visualmente escondido,
continua acessível). 1 teste novo; suíte completa (234 testes) sem
regressão.
**Pendência (2026-08-27, achado pelo Dev durante a implementação da
RN-024):** o arquivo local `doc/EACE.csv` (não versionado no Git) hoje
traz o cabeçalho da coluna sem acento — `Descricao do Item` — enquanto
`PlanilhaEace.COLUNAS_OBRIGATORIAS` e o Sincronizador (RN-022) exigem
`Descrição do Item`, com acento. Um upload desse arquivo, como está agora,
seria rejeitado pela validação de colunas obrigatórias da FEAT-023 (e, se
a validação um dia aceitar sem acento, o Sincronizador não casaria nenhum
item, porque procura a chave acentuada). Não corrigido nesta tarefa —
decisão de como tratar (aceitar as duas grafias, normalizar acentos, ou
manter só a versão acentuada) depende do usuário, por afetar a integração
com o arquivo real da EACE (CLAUDE.md §9).

---

### FEAT-024 — Sincronizador do Lado Relatório EACE (Planilha EACE × INEP)
**Descrição:** Botão "Sincronizador" no painel "Relatório EACE (3º lado)"
da tela do RI. Reprocessa o arquivo ativo da Planilha EACE (FEAT-023),
filtra pelo INEP do RI atual e casa a Descrição do Item com o catálogo
`KitPadrao` (KIT por número de Access Points, produto avulso por
palavra-chave), lançando os itens encontrados como `RiItemRelatorioEace`,
igual a um lançamento manual (RN-018). Preenchimento manual continua
disponível.
**Tipo:** fullstack
**Status:** 🔍 Aguardando QA
**Prioridade:** Alta — é o pedido central do usuário (2026-08-27).
**Critérios de aceite:**
- Botão "Sincronizador" visível no painel do Lado 3, ao lado do
  lançamento manual já existente (FEAT-022).
- Sem Planilha EACE ativa ou sem linha para o INEP: aviso objetivo, sem
  erro/travamento.
- Item da planilha casado com o catálogo é gravado como
  `RiItemRelatorioEace` com a Descrição curta do catálogo (RN-011),
  Quantidade da planilha e Valor Unitário do catálogo (RN-018) — nunca o
  valor bruto da planilha.
- Item sem correspondência no catálogo não é lançado automaticamente;
  fica listado para o usuário decidir.
- Respeita RN-015 (1 KIT por INEP) e RN-004 (exclusão só Administrador).
- Sincronizar de novo não duplica item já lançado idêntico.
- Testes: sincronização com correspondência exata, com sufixo extra (ex.
  "- Equip - MEGA - CO"), sem correspondência, sem planilha ativa, sem
  linha para o INEP, KIT já lançado (bloqueio RN-015), duplicidade ao
  sincronizar 2x.
- **Critério adicional (2026-08-27):** cada item sincronizado (KIT ou
  Produto) guarda também Num OSP, Validação OSP e Nota Fiscal (colunas
  N/O/Q da planilha, RN-022 ampliada), por item — não 1 valor só por RI,
  já que a Nota Fiscal pode variar entre o KIT e cada Produto da mesma
  planilha. Campos fechados (nunca digitados/editados manualmente, mesmo
  com a edição do item liberada, RN-003/RN-018 ampliada); exibidos como
  rótulo com o valor em verde na lista do Lado 3; item sem esses dados
  (lançado manualmente) não exibe o rótulo.
- **Critério adicional (2026-08-27):** quando a coluna "Status escola" da
  Planilha EACE trouxer "Conectada" para o INEP do RI, o Sincronizador
  também muda o status do RI para "Faturamento Concluído" (RN-024) e grava
  `concluido_em` com a data/hora — vale a partir de qualquer status atual,
  inclusive encerrando uma "Correção MEGA" em aberto; independe do
  resultado do lançamento de itens da mesma sincronização.
**Regras relacionadas:** RN-024, RN-022 (ampliada), RN-018, RN-015, RN-011,
RN-010 (ampliada/FEAT-016).
**Dependências:** FEAT-023 (Planilha EACE ativa), FEAT-022 (Lado
Relatório EACE com formulário do catálogo), FEAT-016 (`numero_access_
points`/`resolver_kit_declarado`).
**Tipo de validação:** QA (QA-024).
**Entrega do Dev (2026-08-27):**
- Botão "Sincronizador" no painel "Relatório EACE (3º lado)", ao lado do
  lançamento manual já existente.
- Casamento planilha × catálogo: KIT pelo número de Access Points
  (reaproveita a FEAT-016); produto avulso pela Descrição curta do
  catálogo como prefixo da Descrição da planilha — cobre o sufixo real
  de fornecedor/UF (ex.: "... Access Points - Equip - MEGA - CO").
- Item lançado com Descrição/Valor do catálogo (nunca o valor bruto da
  planilha); sem correspondência, sem Planilha EACE ativa, sem linha
  para o INEP, KIT já lançado ou quantidade inválida — nada é lançado
  sozinho, mensagem objetiva explica o que faltou.
- Sincronizar de novo não duplica item já lançado; respeita RN-015 (1
  KIT por INEP) e recalcula o confronto RN-003 quando lança algo novo.
- 9 testes novos (casamento com sufixo extra, produto por prefixo, sem
  correspondência, sem planilha ativa, sem linha para o INEP, KIT já
  lançado, duplicidade, fluxo pela tela, mensagem de erro); suíte
  completa do app `ri` (197 testes) sem regressão.
- Validado no navegador real (Playwright, servidor local): KIT e produto
  lançados a partir de uma Planilha EACE com sufixo de fornecedor/UF
  real, valores batendo com o catálogo, sem erro de console.
- **Pendência:** nenhuma.
**Correção (2026-08-27):** critério adicional entregue — `RiItemRelatorioEace`
ganhou os 3 campos (`num_osp`, `validacao_osp`, `nota_fiscal`, migration
`0021`), preenchidos só pelo Sincronizador (nunca aparecem no formulário
de edição) e exibidos por item na lista do Lado 3 como rótulo com o valor
em verde, só quando presentes. 4 testes novos (valores gravados por item,
Nota Fiscal diferente entre KIT e Produto do mesmo INEP, item manual
nasce sem os 3 campos, rótulo verde renderizado); suíte completa do app
`ri` (202 testes) sem regressão. Migration aplicada no container real.
**Correção (2026-08-27):** usuário testou no app real (INEP 53004230) e,
depois de sincronizar, clicou no "Salvar" do formulário manual (ação
separada) sem preencher nada — mensagem "Selecione um KIT ou um produto
para lançar" soava como erro, mas os itens já estavam salvos (confirmado
direto no banco do container real). Ajustado: esse envio vazio, quando já
existe item lançado no Relatório EACE, mostra "Os itens do Relatório EACE
já estão salvos — nada novo para lançar" (sucesso, não erro). 1 teste
novo; suíte completa do app `ri` (198 testes) sem regressão.
**Correção (2026-08-27):** RN-024 implementada — quando a coluna "Status
escola" (coluna T) da Planilha EACE trouxer "Conectada" para o INEP do
RI, o Sincronizador também muda o status para "Faturamento Concluído" e
grava `concluido_em`, a partir de qualquer status atual (inclusive
encerrando uma "Correção MEGA" em aberto, sem exigir o retorno manual
para "Andamento"), independente do resultado do lançamento de itens da
mesma sincronização; a troca gera entrada na linha do tempo do RI
(RN-008), mesmo padrão da troca manual de status. 7 testes novos; suíte
completa do app `ri` (228 testes) sem regressão.
- **Critério adicional (2026-08-28, RN-046):** cada item sincronizado
  passa a guardar também o valor da coluna "Status escola" (coluna T) da
  própria linha da planilha, exibido por item no Lado 3 (mesmo padrão do
  rótulo verde de Num OSP/Validação OSP/Nota Fiscal). Quando os itens de
  um mesmo RI têm "Status escola" diferente entre si, o painel mostra o
  alerta "Divergência Status EACE" e **todos** os itens do Lado 3 desse RI
  ficam com o status em vermelho (não só os que divergem da maioria —
  decisão do usuário, sem lado de referência nessa comparação). Não altera
  a RN-024 (conclusão automática por "Conectada" continua incondicional).
**Entrega do Dev (2026-08-28, RN-046):**
- `RiItemRelatorioEace` ganhou o campo `status_escola` (migration `0022`),
  preenchido só pelo Sincronizador com a coluna "Status escola" da mesma
  linha da planilha; exibido por item no Lado 3 em verde (igual a Num
  OSP/Validação OSP/Nota Fiscal), sem valor quando lançado manualmente.
- Divergência entre itens do mesmo RI dispara o alerta "Divergência Status
  EACE" no topo do painel e deixa todos os itens do Lado 3 com anel
  vermelho — item sem valor (manual) não entra na comparação.
- Vale também no Sincronizador em lote (FEAT-025) — mesma função
  reaproveitada, sem lógica separada.
- 9 testes novos (gravação por item, item manual sem valor, divergência
  entre 2 produtos, sem divergência com valores iguais, item sem valor
  ignorado na comparação, alerta e anel vermelho na tela, ausência do
  alerta sem divergência, mesma gravação no lote); suíte completa do app
  `ri` (262 testes) sem regressão. Migration aplicada no container real.
- Validação visual em navegador: não executada — sem Playwright/
  chromium-cli disponível no ambiente; confirmado via `Client` Django
  autenticado (teste renderiza a página real e verifica o texto do alerta
  e a classe `ring-red-400` no HTML).
- **Pendência:** nenhuma.
**Correção (2026-08-28):** usuário reportou item já sincronizado (INEP
35206097) sem "Status escola" na tela, mesmo com a coluna preenchida na
planilha ("Em planejamento") — item lançado antes deste campo existir só
entrava em "duplicados"/"kit_ignorado" ao sincronizar de novo, sem nunca
atualizar nada. Sincronizar de novo agora atualiza o campo em item já
lançado (KIT ou Produto), sem duplicar e sem tocar em Num OSP/Validação
OSP/Nota Fiscal. Confirmado no INEP real depois da correção. 2 testes
novos (Produto e KIT já lançados); suíte completa do app `ri` (264 testes)
sem regressão.
**Correção (2026-08-28):** usuário pediu para estender a mesma atualização
a Num OSP, Validação OSP e Nota Fiscal (não só "Status Equip") — cobre o
caso real de a EACE emitir a Nota Fiscal só depois de o item já ter sido
sincronizado sem ela. Sincronizar de novo passa a atualizar os 4 campos
fechados de item já lançado sempre que a planilha ativa trouxer um valor
novo e diferente; coluna vazia na planilha nunca apaga um valor já
gravado. 2 testes novos (Nota Fiscal atualizada, coluna vazia não apaga);
suíte completa do app `ri` (266 testes) sem regressão.
**Nota para o Orquestrador:** este ajuste muda um critério implícito da
RN-022 ampliada (Num OSP/Validação OSP/Nota Fiscal eram descritos como
gravados só na criação) — os 4 campos fechados agora são atualizados a
cada sincronização, não só na primeira; falta refletir isso no texto da
RN-022 ampliada/RN-046 em `business_rules.md`.

---

### FEAT-025 — Sincronizador em lote da Planilha EACE (todas as RI de uma vez)
**Descrição:** Botão "Sincronizar todas as RI" no card "Arquivo ativo" da
tela "Administrador > Planilha EACE" (FEAT-023). Aplica a mesma lógica do
Sincronizador individual (RN-022/FEAT-024) a cada RI existente no sistema,
sem precisar abrir RI por RI, e devolve um resumo agregado ao final.
**Tipo:** fullstack
**Status:** 🔍 Aguardando QA
**Prioridade:** Alta — pedido direto do usuário (2026-08-27), continuação
do Sincronizador (FEAT-024).
**Critérios de aceite:**
- Botão "Sincronizar todas as RI" no card "Arquivo ativo", visível só
  para Administrador e só quando há Planilha EACE ativa.
- Reaproveita a função de sincronização já usada pelo Lado Relatório EACE
  (`sincronizar_relatorio_eace_da_planilha`, FEAT-024), sem duplicar a
  lógica de casamento planilha × catálogo.
- RI sem linha na planilha para o INEP, ou bloqueado pelo status
  "Faturamento Concluído" (RN-020), não interrompe o processamento dos
  demais — entra no resumo como pendência.
- Sincronizar de novo não duplica item já lançado (mesma regra da
  RN-022).
- Resumo final mostra contagens agregadas (RIs com item novo, já
  sincronizados sem novidade, sem correspondência, sem linha na
  planilha, bloqueados) e a lista dos INEPs que precisam de atenção
  manual.
- Cada item lançado é registrado no histórico do RI correspondente
  (RN-008).
- Testes: lote com RIs em cada situação (item novo, já sincronizado,
  sem correspondência, sem linha na planilha, bloqueado por status),
  sem N+1 nas consultas, permissão restrita a Administrador.
- **Critério adicional (2026-08-27):** mesma conclusão automática por
  "Status escola" da FEAT-024 (RN-024) — RI com INEP "Conectada" na
  Planilha EACE muda para "Faturamento Concluído" também no lote, com
  `concluido_em` gravado; entra na contagem do resumo final.
**Regras relacionadas:** RN-024, RN-023, RN-022, RN-021, RN-020, RN-008.
**Dependências:** FEAT-024 (Sincronizador individual — precisa estar
`✅ Concluída`; hoje `🔍 Aguardando QA`), FEAT-023 (Planilha EACE ativa).
**Tipo de validação:** QA (QA-025).
**Entrega do Dev (2026-08-27):**
- Botão "Sincronizar todas as RI" no card "Arquivo ativo", visível só
  para Administrador, ao lado da informação do arquivo enviado.
- Reaproveita a mesma função de sincronização do Lado Relatório EACE
  (FEAT-024) para o RI atual de cada Escola; arquivo da planilha lido e
  agrupado por INEP 1 única vez para o lote inteiro (não a cada RI).
- RI sem linha na planilha, ou bloqueado pelo status "Faturamento
  Concluído" (RN-020), não trava os demais — entra no resumo final.
- Cada item lançado é registrado na linha do tempo do RI (RN-008), igual
  ao Sincronizador individual.
- 10 testes novos (RI atual por Escola, Escola com mais de 1 RI, bloqueio
  por status, RI sem linha na planilha, sem Planilha ativa, ausência de
  N+1, permissão, log gerado). Suíte completa do app `ri` (231 testes) e
  do repositório sem regressão.
- Validação visual em navegador: não executada — `chromium-cli`
  indisponível no ambiente; confirmado via `Client` Django autenticado
  (a mesma suíte de testes renderiza a página e processa o POST real).
- **Pendência:** entrega começou antes de FEAT-024 estar `✅ Concluída`
  (hoje `🔍 Aguardando QA`) — mesmo padrão de exceção já usado na
  FEAT-006; falta o Orquestrador formalizar/confirmar a exceção.
**Correção (2026-08-27):** usuário testou no app real e reportou que o
resumo aparecia em vermelho (estilo de erro) mesmo com a sincronização
tendo rodado certinho — "0 item novo" é resultado normal do lote (RI sem
linha na planilha, ou já sincronizado antes), não uma falha; confirmado
que 13 dos 15 RIs do teste eram de Escolas fora da planilha ativa (dado
real, não bug de casamento por INEP). Mensagem passa a usar sempre o
estilo de sucesso quando o lote roda até o fim — só "sem Planilha EACE
ativa" continua como erro de verdade. 1 teste novo; suíte completa do
app `ri` sem regressão.
**Correção (2026-08-27):** usuário pediu para tirar o detalhamento da
mensagem (já sincronizado, bloqueado, sem linha na planilha, sem
correspondência) — só precisa da contagem de INEPs atualizados. Mensagem
passa a ser só "Sincronização em lote: N INEP(s) atualizado(s)."; quem
quiser investigar um INEP sem novidade abre o RI dele. 2 testes
ajustados/novos; suíte completa (233 testes) sem regressão.
**Nota para o Orquestrador:** este ajuste muda o critério de aceite da
RN-023 ("resumo agregado com as contagens... e a lista dos INEPs que
precisam de atenção manual") — `business_rules.md` ainda descreve a
versão detalhada; falta atualizar o texto da regra para refletir a
mensagem só com a contagem.
**Correção (2026-08-27):** RN-024 também aplicada ao lote — RI com INEP
"Conectada" na Planilha EACE conclui o RI dentro da mesma
`sincronizar_relatorio_eace_da_planilha` reaproveitada pelo lote (sem
duplicar lógica) e entra na contagem "N INEP(s) atualizado(s)" mesmo sem
item novo lançado, já que a troca de status independe do lançamento de
itens. 2 testes novos; suíte completa do app `ri` (228 testes) sem
regressão.
- **Critério adicional (2026-08-28, RN-046):** o "Status escola" por item
  e o alerta "Divergência Status EACE" (ver FEAT-024) valem também para
  itens lançados pelo lote, sem lógica separada — mesma
  `sincronizar_relatorio_eace_da_planilha` reaproveitada.
**Entrega do Dev (2026-08-28, RN-046):** confirmado que o campo
`status_escola` é gravado igual no lote (1 teste novo); suíte completa do
app `ri` (262 testes) sem regressão.

---

### FEAT-026 — Dashboard financeiro: Valor Total do Projeto e Valor já faturado
**Descrição:** Tela inicial (`core/home.html`, hoje placeholder) ganha os
2 primeiros cards do dashboard financeiro do projeto: (1) "Valor Total do
Projeto", somando Kit + Nobreak inicial de todas as escolas; (2) "Valor já
faturado", somando os itens do Lado 3 (Relatório EACE) de RIs em
"Faturamento Concluído", com a diferença para a meta do card 1 (vermelho
se falta, verde se atingiu/ultrapassou), numa divisão visual verde
(acima)/vermelho (abaixo) proporcional. Usuário sinalizou que pode trazer
mais cards para este mesmo dashboard depois.
**Tipo:** fullstack
**Status:** 🔍 Aguardando QA
**Prioridade:** Média — pedido direto do usuário (2026-08-27); sem
dependência de outra feature em aberto, mas o prazo da v1 é 28/08/2026 —
avaliar com o usuário se entra antes do prazo ou depois.
**Critérios de aceite:**
- Card "Valor Total do Projeto": soma global (todas as escolas) do Kit
  Declarado (RN-010) + Nobreak inicial (RN-017 corrigida) por escola,
  resolvidos via `KitPadrao` (descrição + lote); escola sem
  correspondência no catálogo entra como R$ 0,00 (RN-025).
- Card "Valor já faturado": soma global de `RiItemRelatorioEace`
  (quantidade × valor unitário) só dos RIs com status "Faturamento
  Concluído"; RI com item no Lado 3 mas noutro status não conta (RN-026).
- Diferença entre os 2 cards exibida no card 2: vermelho quando falta
  faturar, verde quando bate ou ultrapassa a meta; divisão proporcional
  verde (acima) / vermelho (abaixo) dentro do card (RN-026).
- Consultas agregadas sem N+1 (soma no banco, não em loop Python).
- Testes: cálculo com escolas/RIs em cada situação (com/sem correspondência
  no catálogo, RI em Faturamento Concluído e noutros status), permissão de
  acesso ao dashboard igual à já existente na home.
**Regras relacionadas:** RN-025, RN-026, RN-017, RN-010, RN-001, RN-020.
**Dependências:** nenhuma bloqueante — depende de o catálogo `KitPadrao`
ter a entrada do Nobreak por Lote (reimportar `importar_catalogo_lpu`,
FEAT-015, se faltar).
**Tipo de validação:** QA (QA-026).
**Entrega do Dev (2026-08-27):**
- Cards "Valor Total do Projeto" e "Valor já Faturado" implementados em
  `core/home.html`, com a soma calculada em `apps/ri/services.py`
  (`montar_dashboard_financeiro`), sem N+1 (catálogo carregado 1 vez;
  soma do Lado 3 agregada no banco).
- Novo `KitPadrao.resolver_nobreak_declarado` (RN-017 corrigida) resolve o
  valor do Nobreak inicial pelo mesmo catálogo do Kit.
- Valores em R$ com separador de milhar e vírgula decimal (pt-BR, filtro
  `intcomma`), a pedido do usuário.
- Divisão proporcional verde/vermelho do card 2 implementada.
- 19 testes novos (resolução do Nobreak, cálculo dos 2 cards em cada
  cenário, formatação em R$); suíte completa do projeto (260 testes)
  sem regressão.
- Validação visual em navegador: não executada nesta entrega (usuário já
  validou no app real via captura de tela, apontando o ajuste de
  formatação numérica acima).
**Correção (2026-08-27):** usuário pediu, direto ao Dev, para o Dashboard
ganhar 3 submenus — Faturamento, Equipamentos e Relatórios — com os 2
cards acima dentro de "Faturamento". Implementado: menu "Dashboard" no
`base.html` virou um submenu (mesmo padrão de "Projeto"/"Administrador"),
com as 3 rotas (`/`, `/equipamentos/`, `/relatorios/`); Equipamentos e
Relatórios nascem como placeholder (sem cards definidos ainda). 4 testes
novos (login exigido e renderização das 2 páginas novas).
**Ampliação (2026-08-27):** usuário pediu, dentro de "Faturamento", um
gráfico de "quanto já faturei por estado" — 1 barra por UF (`Escola.estado`),
clicável: ao clicar, os 2 cards acima passam a somar só aquele estado
(`?estado=UF`, RN-027, nova). Cada linha do gráfico mostra o valor já
faturado e, no final da linha, a meta (Kit + Nobreak) daquele estado; a
barra é proporcional a quanto da própria meta do estado já foi faturado.
"Ver todos os estados" limpa o filtro. 15 testes novos (filtro por
estado nos 2 cards, cálculo/ordenação do gráfico, UF sem faturamento
ainda, escola sem Estado cadastrado não entra); suíte completa do
projeto (258 testes) sem regressão. **Ajuste (2026-08-27):** a pedido do
usuário, o card "Valor já Faturado" e o gráfico ganharam um badge no
canto com a % já faturada sobre a meta (mesmo `percentual_faturado_pct`
da RN-026); espaçamento ajustado depois para o badge não encostar na
barra proporcional do card.
**Ampliação (2026-08-27):** usuário pediu que, ao clicar num estado, o
mesmo gráfico expanda (dentro do mesmo card) mostrando os Municípios
daquele estado, com a mesma informação (valor faturado + meta + barra
proporcional); clicar num município filtra os 2 cards mais 1 nível
(`?estado=UF&municipio=Nome`). Município só é aplicado junto com estado
(nome de cidade se repete entre UFs diferentes). Extraído o partial
`core/_linha_faturamento.html`, reaproveitado pelas 2 listas (estado e
município). 8 testes novos; suíte completa (265 testes) sem regressão.
**Correção (2026-08-27):** usuário reportou, com captura de tela do app
real, o texto de um comentário aparecendo literalmente na tela (dentro de
cada linha do gráfico). Causa: comentário Django `{# ... #}` de múltiplas
linhas — limitação documentada do próprio Django (só `{% comment %}
...{% endcomment %}` aceita múltiplas linhas; `{# #}` que ultrapassa 1
linha "vaza" como texto). Corrigido no partial `_linha_faturamento.html`;
2 testes ajustados (checavam o texto de um jeito frágil o bastante para
não detectar esse vazamento). Suíte completa sem regressão.
**Ajuste (2026-08-27):** a pedido do usuário, os gráficos "Faturado por
Estado" e "Faturado por Município" passam a ordenar pela % da própria
meta já faturada (do mais perto de 100% para o mais perto de 0%), não
mais pelo valor bruto em R$ — um estado/município com valor alto mas %
baixa aparece por último. 3 testes novos (cenário onde os 2 critérios
dão ordens diferentes).
**Correção (2026-08-27):** usuário reportou que o badge de % (card
"Valor já Faturado" e gráfico) travava em "100%" mesmo quando o valor
faturado ultrapassava a meta — deveria mostrar mais de 100% (ex.: 200%).
Corrigido: o texto/badge (`percentual_faturado_pct`) não tem mais teto;
só a barra de 2 segmentos do card (CSS, `percentual_faturado_css`)
continua capada em 100% — geometricamente não cabe mais que isso num
contêiner de altura fixa. 2 testes novos.
**Ampliação (2026-08-28):** usuário pediu, direto ao Dev, os 2 primeiros
cards do submenu "Equipamentos" (até então placeholder sem cards
definidos): "Kits Programados" e "Nobreaks Programados", em cards
separados (pedido do usuário — unidades de natureza diferente, Kit de
rede Wi-Fi × equipamento de energia, não fazem sentido somadas num total
só). 1ª versão somava a Quantidade cadastrada em `RiItemEace` (1º lado do
RI) — revista no mesmo dia ao tentar validar visualmente: essa tabela tem
só 9 registros lançados pras 2.622 escolas do projeto real (RN-010: Lote
1 bloqueado sem planilha, Lote 2/3 dependem de lançamento manual no
admin), sem uso prático ainda. Trocado para a mesma origem já usada no
card "Valor Total do Projeto" (RN-025): `Escola.kit_inicial` +
`Escola.nobreak_inicial` (RN-017) resolvidos pelo catálogo `KitPadrao`,
dado que já existe pras 2.622 escolas.
**Correção (2026-08-28):** usuário reportou, com captura de tela do app
real, que "Kits Programados" passava de 20 mil — a 2ª versão somava os
Access Points de cada Kit (ex.: Kit de 4 Access Points contava 4), quando
deveria ser 1 Kit por escola (no máximo 2.622, 1 Kit declarado por
escola). Corrigido: "Kits Programados" conta 1 por escola com Kit
reconhecido no catálogo `KitPadrao` (escola sem correspondência não soma,
mesma regra conservadora da RN-025); "Nobreaks Programados" já contava 1
por escola, sem alteração. O detalhamento "Kits por Produto" inicialmente
manteve, por tipo de Kit, a quantidade de escolas + o total de Access
Points daquele tipo (escolas × tamanho do Kit) — usuário apontou, ainda
na mesma validação, que esse total (ex.: 267 escolas × 15 Access Points =
4.005) não representa nada real no inventário dele: "Access Points" é só
o tamanho/nome do tipo de Kit, não uma contagem de equipamento físico que
se multiplica pela quantidade de escolas. Removido: o detalhamento passa
a mostrar só a quantidade de escolas por tipo de Kit, sem nenhum número
derivado de escola × tamanho — confirmado contra o banco real que a soma
das linhas bate exatamente com o total do card (2.622). 4 testes novos
(cards vazios, 1 Kit por escola, escola sem correspondência no catálogo,
detalhamento por produto só com contagem de escolas); suíte completa do
projeto (285 testes) sem regressão — rodada no container Docker real
(`sistema_posvenda-web-1`), ambiente oficial do projeto, com os 2.622
registros reais de Escola. Validação visual em navegador: não executada
por mim — o usuário validou direto no app real (Docker) e reportou os 2
problemas acima por captura de tela.
**Ampliação (2026-08-28):** usuário pediu um 3º card, "Kits Instalados"
(quantos Kits já têm a escola conectada), mais um gráfico "Kits
Instalados por Estado" igual ao "Faturado por Estado" já usado na aba
Faturamento (RN-027) — 1 barra por UF, clicável, filtrando os 3 cards.
1ª versão de "Kits Instalados" usou `Escola.status_conexao` (RN-007): conta
1 por escola com Kit reconhecido no catálogo E status "conectado" — mas
conferido contra o banco real, nenhuma das 2.622 escolas tinha as 2 datas
de instalação preenchidas ainda, então o card ficava zerado no projeto
inteiro.
**Correção (2026-08-28):** usuário apontou que a fonte certa de "Kits
Instalados" é outra: RIs com status "Faturamento Concluído" cujo Kit foi
lançado no Lado Relatório EACE (3º lado, `RiItemRelatorioEace.eh_kit`) —
mesma fonte já usada no card "Valor já Faturado" (RN-026), que é
literalmente baixada da EACE depois da instalação. Conferido antes de
trocar: só 2 dos 368 RIs em Faturamento Concluído tinham Kit no Lado IXC
(2º lado, digitado manualmente pelo técnico) contra 366 no Lado Relatório
EACE — confirma a fonte certa. Corrigido: "Kits Instalados" conta escolas
distintas com Kit lançado no Lado Relatório EACE de RI em Faturamento
Concluído (366 no projeto real, bem distribuído entre estados). O gráfico
"Kits Instalados por Estado" usa a mesma fonte corrigida.
Novo partial `core/_linha_kits_instalados.html` (mesmo padrão visual de
`_linha_faturamento.html`, mas para contagem de Kits em vez de R$ —
separado para não arriscar o partial já aprovado do Faturamento). 8
testes novos (card "Kits Instalados" vazio/com dado, só Kit no Lado
Relatório EACE de RI concluído conta — não o Lado IXC nem RI não
concluído —, gráfico sem filtro, clique filtra os 3 cards, UF sem
instalação ainda entra com 0, estado inválido não quebra); suíte completa
do projeto (290 testes) sem regressão — rodada no container Docker real.
**Ampliação (2026-08-28):** usuário reportou que, ao filtrar por estado
(ex.: SP), o card "Kits Instalados" mudava o total mas o detalhamento
"Kits por Produto" não dizia quais tipos de Kit formavam aquele número.
Corrigido: cada linha de "Kits por Produto" passa a trazer as 2 contagens
lado a lado — Programados e Instalados — já dentro do recorte de estado
selecionado (Descrição que só existe do lado Instalados, sem
correspondência nos Programados do recorte atual, ainda aparece, não é
descartada — CLAUDE.md §9). Conferido contra o banco real: a soma dos
Instalados de todas as linhas bate exatamente com o total do card "Kits
Instalados" (SP: 230 = 230). 2 testes novos; suíte completa do projeto
(291 testes) sem regressão — rodada no container Docker real.
**Ampliação (2026-08-28):** usuário pediu o mesmo badge de % já usado no
card "Valor já Faturado" (RN-026) — % de Kits Instalados sobre Kits
Programados, no canto do card "Kits Instalados" e repetido no cabeçalho
do gráfico "Kits Instalados por Estado" (mesmo padrão visual dos 2 badges
espelhados do Faturamento). Sem teto (pode passar de 100% se as 2 fontes
divergirem — mesma correção de 2026-08-27 aplicada à RN-026), verde só
com meta real atingida/ultrapassada. 3 testes novos (badge com %
calculada, sem teto acima de 100%); suíte completa do projeto (292
testes) sem regressão — rodada no container Docker real. Conferido
contra o banco real: projeto geral 14% (366/2622), SP 15,6% (230/1479).
**Ampliação (2026-08-28):** usuário pediu que "Kits por Produto" também
mostre a quantidade de Nobreak (ex.: "+2"), com legenda explicando o
valor. Adicionada 1 linha à parte, abaixo da lista de Kits, com "+" na
frente do número (mesmo total já usado no card "Nobreaks Programados",
já dentro do recorte de estado quando filtrado) e uma legenda deixando
claro que não é um tipo de Kit — é o item fixo do 1º lado (RN-017). Sem
mudança no service (`montar_dashboard_equipamentos`): reaproveita
`total_nobreaks_programados`, que já existia no contexto. 1 teste novo
(linha e legenda aparecem, valor respeita o filtro de estado); suíte
completa do projeto (293 testes) sem regressão — rodada no container
Docker real.
**Ampliação (2026-08-28):** usuário pediu uma interação entre os
dashboards Faturamento e Equipamentos — filtrar por estado numa tela e
poder ir para a outra já com o mesmo filtro aplicado, "o que ficar mais
profissional e acessível". Decisão do Dev (CLAUDE.md §9, técnica
reversível/baixo risco): link cruzado por `?estado=UF` em vez de modal —
os 2 dashboards já usam o mesmo parâmetro, então é só um link comum
(`<a href>`), sem HTMX/JS novo, acessível por teclado/leitor de tela e
com URL própria pra compartilhar (modal exigiria endpoint novo, mais
complexidade, sem ganho real aqui). Aparece só quando um estado está
filtrado, ao lado de "Ver todos os estados": "Ver Equipamentos de UF" no
Faturamento, "Ver Faturamento de UF" em Equipamentos. 4 testes novos
(link aparece com o href certo quando filtrado, não aparece sem filtro,
nos 2 dashboards); suíte completa do projeto (297 testes) sem regressão —
rodada no container Docker real.
**Ampliação (2026-08-28):** usuário reportou que existem outros
equipamentos além de Kit e Nobreak, "complemento" — não programados
antes do projeto — e pediu visibilidade deles. Conferido contra o banco
real antes de implementar (usuário confirmou: "esses valores também vêm
do lado 3"): 7 tipos de produto avulso lançados no Lado Relatório EACE
(3º lado, `eh_kit=False`) de RIs em Faturamento Concluído, incluindo 1
"Nobreak" avulso (367 escolas) diferente do Nobreak Programado
(`Escola.nobreak_inicial`) — excluído da lista nova por já ter card/linha
próprios; fica registrado como possível "Nobreaks Instalados" futuro, não
implementado agora (sem pedido explícito). Novo bloco "Produtos
Complementares": Descrição + Quantidade somada (soma legítima aqui — ao
contrário do Kit, a Quantidade não vem embutida na Descrição, é um dado
lançado à parte, RN-018) + escolas onde aparece; sem "Programado" (não
existe meta pra esses itens). Respeita o filtro de estado. 3 testes
novos (agrupamento com soma correta, exclusão de Kit/Nobreak/RI não
concluído, filtro por estado); suíte completa do projeto (300 testes) sem
regressão — rodada no container Docker real. Conferido
contra o banco real: Access Point adicional Indoor (129 un./42 escolas),
Rack 7U (6/5), Switch 8 portas (4/4), Switch 16 portas (2/2), Rack 5U
(1/1), Rack 9U (1/1).
**Ampliação (2026-08-28):** usuário pediu para filtrar por "Kits por
Produto" e "Produtos Complementares" — clicar numa linha filtra a página,
mesmo padrão já usado no gráfico por estado (decisão confirmada com o
usuário entre esse formato e um campo de busca por texto). Também pediu
para trocar a palavra "Produto" por "Equipamento" nos rótulos — renomeado
"Kits por Produto" → "Kits por Equipamento" e "Produtos Complementares" →
"Equipamentos Complementares" (nomes internos de variável/service mantidos
em português já usado no projeto, sem risco de regressão). Implementado:
3 filtros independentes e combináveis via `?estado=UF&kit=Descrição&
produto=Descrição` — `kit` restringe os 3 cards, o próprio detalhamento e
o gráfico "Kits Instalados por Estado" a só aquele tipo de Kit; `produto`
restringe só "Equipamentos Complementares" (Kit/Nobreak são eixos
independentes, não afetados). Clicar numa linha já selecionada limpa o
filtro (toggle); cada "Ver todos os X" preserva os outros 2 filtros. 6
testes novos (clique filtra cards + gráfico, combinação kit+estado, toggle
ao clicar de novo, clique em Equipamento Complementar não afeta Kit,
"Ver todos os X" preserva os outros filtros); suíte completa sem
regressão. Conferido contra o banco real: filtrar pelo Kit de 15 Access
Points dá 267 programados/65 instalados, distribuídos corretamente por
estado (ex.: SP 32/177).
**Ampliação (2026-08-28):** usuário pediu, ao clicar num Equipamento
Complementar, "filtrar a página toda" e "saber o estado que está aquele
equipamento" + "o valor no filtro de faturamento" — 1ª versão criou uma
lista "por Estado" nova, duplicada, dentro do próprio bloco "Equipamentos
Complementares"; usuário reportou que já existia um gráfico por estado lá
em cima (o de Kits) e pediu pra reaproveitar aquele espaço em vez de
duplicar embaixo. Corrigido: 1 único gráfico por estado no topo, que
mostra "Kits Instalados por Estado" por padrão ou "{Equipamento} por
Estado" quando um Equipamento Complementar está selecionado — clicar numa
linha define o estado, que já revela o link cruzado "Ver Faturamento de
UF" existente (é ali que o usuário vê o valor faturado, sem duplicar
cálculo novo). Nova função de service `montar_produtos_complementares_por_estado`
(vazia sem `produto` selecionado — misturar tipos diferentes num só total
não conta história, mesmo racional já usado pro Kit) e partial
`_linha_produto_estado.html`. 3 testes novos (gráfico vazio sem produto,
dados corretos por estado com produto, clique define estado + revela link
de Faturamento); suíte completa do projeto (307 testes) sem regressão —
rodada no container Docker real.
**Correção (2026-08-28):** usuário reportou 2 problemas depois de validar
o item acima: (1) trocar de Equipamento Complementar carregava o estado
que estava selecionado — ele valia só pra distribuição do equipamento
anterior (ex.: "Rack 7U" em RJ), e o equipamento novo podia nem existir
lá; corrigido, escolher outro equipamento sempre começa do zero (sem
estado). (2) "o financeiro tem que trazer os valores referente aquele
filtro" — clicar "Ver Faturamento de UF" levava pro Faturamento com o
valor GERAL do estado, não o valor do Kit/Equipamento que estava
filtrado. Decisão de escopo confirmada com o usuário: Faturamento ganha
os mesmos filtros `?kit=`/`?produto=` (mutuamente exclusivos, vindos de
Equipamentos), recalculando os 2 cards (RN-025/RN-026) só daquele
item — pra Kit, meta (só o Kit, sem Nobreak) x faturado daquele tipo; pra
Equipamento Complementar, sem meta (nunca programado antes do projeto,
já confirmado antes), só o valor faturado, sem comparação. Os gráficos
"Faturado por Estado"/"por Município" somem nesse recorte (comparar
vários estados não faz sentido já filtrado por 1 item; o Card 2 sozinho
já mostra o valor). "Ver Faturamento de UF" agora carrega o Kit/
Equipamento junto. 6 testes novos (kit restringe os 2 cards, produto sem
meta, gráfico por estado some, link cruzado carrega o kit, reset ao
trocar de equipamento, "Ver Faturamento geral" preserva estado); suíte
completa do projeto (313 testes) sem regressão — rodada no container
Docker real. Conferido contra o banco real: geral R$
106.636.085,84/R$ 15.267.489,61; Kit 15 Access Points R$
13.459.377,66/R$ 3.254.649,47; Rack 7U (sem meta) R$ 14.779,84 faturado.
**Nota para o Orquestrador:** os ajustes acima (submenus do dashboard,
formatação R$ pt-BR, o gráfico/filtro por estado incluindo o drill-down
por Município — RN-027 —, os cards "Kits Programados"/"Kits Instalados"/
"Nobreaks Programados" do submenu Equipamentos com o gráfico "Kits
Instalados por Estado", e agora o filtro por Kit/Equipamento também no
Faturamento) vieram direto do usuário ao Dev durante a implementação e
ampliam o critério de aceite original desta FEAT — falta formalizar em
`business_rules.md`/`checklist.md` (critérios de aceite, a RN-027 já
cobrindo estado e município, e uma nova RN para os 3 cards de
Equipamentos — 1 Kit/Nobreak por escola para os "Programados", "Kits
Instalados" via Lado Relatório EACE + Faturamento Concluído, mesma fonte
da RN-026, sem nenhuma conta derivada de Access Points — mais o filtro
por Kit/Equipamento espelhado no Faturamento).
**Pendência:** usuário sinalizou que pode trazer mais cards para este
dashboard (dentro de Faturamento ou Equipamentos, ou no submenu ainda
vazio Relatórios) — critérios de aceite podem crescer antes do QA.

---

### FEAT-027 — Integração com Active Directory (Autenticação + Sincronização)
**Descrição:** Login do sistema passa a validar usuário e senha contra o
Active Directory (LDAP), reaproveitando o padrão do `modulo-posVenda`
(`django_auth_ldap`, `ModelBackend` como fallback); depois de qualquer
login, e-mail e nome do usuário são sincronizados a partir do AD
(`apps/integracoes/ad/ad_sync.py`). Resolve a pendência registrada em
`lixo.md` (item 7) desde 2026-08-20.
**Tipo:** backend-only
**Status:** 🔍 Aguardando QA
**Prioridade:** Média — sem prazo da v1 vinculado; pedido direto do usuário
em 2026-08-28.
**Critérios de aceite:**
- Usuário válido no AD faz login com a senha do domínio; senha errada é
  recusada.
- Primeiro login de um usuário do AD sem cadastro local cria o usuário
  automaticamente, com perfil Analista (RN-004/RN-043) — nunca
  Administrador.
- Usuário local desativado (`is_active=False`) não consegue logar, mesmo
  com senha correta no AD.
- Após login (AD ou local), e-mail e nome são atualizados a partir do AD
  quando diferentes; e-mail já em uso por outro usuário não é sobrescrito
  (RN-044).
- LDAP indisponível não impede login local nem derruba a aplicação —
  degrada para `ModelBackend` sem erro visível ao usuário.
- `USE_AD_AUTH=false` mantém o comportamento atual (100% login local), sem
  nenhuma chamada ao AD.
**Regras relacionadas:** RN-043, RN-044, RN-004.
**Dependências:** FEAT-001 (User/perfil/permissão já reaproveitados); sem
dependência bloqueante de FEAT-003 (telas de CRUD manual de usuário).
**Tipo de validação:** QA (QA-027) — inclui teste de permissão e de
indisponibilidade do LDAP.
**Entrega do Dev:** `AUTHENTICATION_BACKENDS` condicional a `USE_AD_AUTH`
(`config/settings.py`, fallback automático para `ModelBackend` se a
biblioteca não estiver instalada, sem erro visível); módulo
`apps/integracoes/ad/ad_sync.py` (RN-044, reaproveitado do
`modulo-posVenda`) sincroniza e-mail e nome a cada login (AD ou local),
conectado via `apps/core/apps.py` (`ready()`); criação automática de
usuário via AD fica Analista "de graça" (`perfil` já é `default` no
model, RN-004/RN-043 — nenhum código novo decide isso). Verificação de
certificado TLS desativada na conexão LDAPS (mesma solução do
`modulo-posVenda`, decisão confirmada pelo usuário em 2026-08-28 — ver
`ADR-002`, CA interna do AD não está na cadeia de confiança do
container). 20 testes automatizados (`apps/integracoes/ad/tests.py`, com
cliente LDAP mockado); suíte completa (68 testes) roda sem erro tanto no
host (sem `python-ldap`) quanto dentro do container com `USE_AD_AUTH=true`
e a lib instalada.
**Validação end-to-end (2026-08-28), com DevOps já tendo reintroduzido
`python-ldap`/`django-auth-ldap`/libs de sistema e o `.env` real
preenchido:** login de verdade contra o AD, com a conta real do usuário
(senha nunca gravada em arquivo/commit) — usuário criado automaticamente
com perfil Analista, `is_staff`/`is_superuser` falsos; e-mail e nome
sincronizados do AD (RN-044); senha errada recusada; usuário desativado
(`is_active=False`) barrado mesmo com senha certa do AD. Todos os
critérios de aceite abaixo confirmados na prática, exceto "LDAP
indisponível degrada sem erro" e "e-mail já em uso não é sobrescrito", que
ficam cobertos pelos testes automatizados (mock), não por um cenário real
de indisponibilidade.
**Pendência atual:** nenhuma bloqueante. Fica à parte, não bloqueante:
consolidar em `business_rules.md`/RN-043 a nota sobre a verificação de
TLS desativada (hoje só na `ADR-002` e neste checklist).

---

### FEAT-028 — Administrador > Usuários (trocar perfil)
**Descrição:** Novo item no menu "Administrador" (ao lado de "Planilha
EACE"), visível só a `user.is_administrador` (RN-004): tela lista os
usuários (usuário, e-mail, perfil atual) e permite trocar o perfil entre
Administrador e Analista. Não cria usuário, não edita outros campos e não
ativa/desativa — isso continua só pelo `/admin/` do Django.
**Tipo:** fullstack
**Status:** 🔍 Aguardando QA
**Prioridade:** Média — sem prazo da v1 vinculado; pedido direto do usuário
em 2026-08-28.
**Critérios de aceite:**
- Menu lateral "Administrador" ganha item "Usuários", visível só a
  `user.is_administrador`.
- Tela lista todos os usuários com usuário, e-mail e perfil atual.
- Cada linha permite trocar o perfil (Administrador ↔ Analista) com
  confirmação antes de aplicar.
- Ação bloqueada (403) para usuário sem perfil Administrador, tanto na
  tela quanto na rota direta.
- Administrador não consegue trocar o próprio perfil por essa tela (nem na
  tela, nem na rota direta).
- Testes: troca bem-sucedida nos 2 sentidos, bloqueio para Analista (tela e
  rota direta), bloqueio de autotroca.
**Regras relacionadas:** RN-004 (ampliada).
**Dependências:** nenhuma — `User.perfil`/`is_administrador` já existem
desde FEAT-001.
**Tipo de validação:** QA (QA-028).
**Entrega do Dev (2026-08-28):**
- Criado o item "Usuários" no menu "Administrador", ao lado de "Planilha
  EACE".
- Tela lista usuário, e-mail e perfil, com botão para trocar o perfil.
- Ação bloqueada para quem não é Administrador e para trocar o próprio
  perfil, com confirmação antes de aplicar.
- 8 testes novos; suíte completa (340 testes) sem regressão.
- Validado ponta a ponta contra o servidor real (login, listagem, troca de
  perfil persistida no banco); usuários de teste removidos depois.
- **Pendência:** validação visual em navegador (Playwright/preview) não
  executada — sem essa ferramenta disponível nesta sessão; layout reaproveita
  os mesmos componentes (tabela, badges, botões) já aprovados em outras
  telas do "Administrador".
**Pendência atual:** aguardando revisão do QA.

---

### FEAT-029 — Liberação de acesso aos dados (liga/desliga por usuário)
**Descrição:** Segundo controle por conta de usuário, independente do
perfil (RN-004): acesso aos dados Ligado/Desligado (RN-045). Conta
Desligada faz login normalmente e vê o menu, mas nenhuma tela com
informação do projeto mostra dado — aparece um aviso de "aguardando
liberação do Administrador". Vale para Analista e também para
Administrador. Administrador liga/desliga qualquer outra conta pela tela
"Administrador > Usuários" (FEAT-028), sem poder ligar/desligar a própria
conta por lá. Usuário já existente antes desta feature não é afetado —
continua com acesso; só conta criada a partir de agora (pelo `/admin/` ou
pelo login automático via AD, RN-043) nasce Desligada.
**Tipo:** fullstack
**Status:** 🔍 Aguardando QA
**Prioridade:** Média — sem prazo da v1 vinculado; pedido direto do usuário
em 2026-08-28.
**Critérios de aceite:**
- Novo controle Ligado/Desligado por usuário, separado do perfil
  (Administrador ↔ Analista continuam podendo estar Desligados os dois).
- Migração marca todo usuário já existente como Ligado; só conta criada
  depois desta feature nasce Desligada (inclusive via login AD, RN-043).
- Usuário Desligado loga normalmente e vê o menu lateral, mas toda tela com
  dado do projeto mostra um aviso de "aguardando liberação do
  Administrador" em vez do conteúdo — inclui os 3 submenus do Dashboard, o
  Grid de INEPs, o detalhe do RI (com drill-down) e as telas do menu
  Administrador (Planilha EACE, Usuários).
- Tela "Administrador > Usuários" ganha uma ação para ligar/desligar cada
  usuário, ao lado da troca de perfil (FEAT-028); ação restrita a
  Administrador e bloqueada para a própria conta logada.
- Testes: usuário Ligado vê dado normalmente; usuário Desligado vê o aviso
  em pelo menos 1 tela de cada área (Dashboard, Grid de INEPs, RI,
  Administrador); liga/desliga funciona nos 2 sentidos; bloqueio de
  autotroca; migração não desliga usuário pré-existente.
**Regras relacionadas:** RN-045 (nova), RN-004, RN-043.
**Dependências:** FEAT-028 (tela "Administrador > Usuários" já existe e
recebe a ação nova).
**Tipo de validação:** QA (QA-029) — feature de segurança/permissão,
revisão ampla de todas as telas cobertas.
**Entrega do Dev (2026-08-28):**
- Bloqueio aplicado de uma vez só (middleware), cobrindo toda tela
  autenticada sem mexer view por view — telas futuras já nascem cobertas.
- Ação de ligar/desligar somada à tela "Administrador > Usuários", ao lado
  da troca de perfil.
- Migração liga todo usuário que já existia; cadastro novo (`/admin/` ou
  login automático via AD) nasce desligado.
- **Nota técnica (não é critério de aceite):** criação de usuário direto
  por código (bootstrap do primeiro Administrador do ambiente, e os
  usuários dos testes) nasce Ligada — sem essa exceção nenhum ambiente
  novo teria um Administrador pra liberar os outros. Fica para você
  formalizar em RN-045, se concordar.
- 15 testes novos, suíte completa (352 testes) sem regressão; validado
  ponta a ponta no servidor real (usuário nasceu desligado, viu o aviso,
  Administrador ligou pela tela, dado passou a aparecer).
- **Pendência:** validação visual em navegador não executada — mesma
  limitação já registrada na FEAT-028.
**Pendência atual:** aguardando revisão do QA.

---

### FEAT-030 — Bug: usuário autenticado vê o menu lateral sobreposto na tela de login
**Descrição:** Usuário com sessão já ativa que acessa `/login/` continua
vendo o formulário de login, mas como qualquer usuário autenticado enxerga
o menu lateral (`base.html`), a tela de login aparece com o menu do sistema
sobreposto ao fundo. A `LoginView` do Django não redireciona por padrão
quem já está logado.
**Tipo:** backend-only
**Status:** 🔍 Aguardando QA
**Prioridade:** Alta — bug reportado pelo usuário, com print, na tela de
login (fluxo entregue pela FEAT-001).
**Critérios de aceite:**
- Usuário autenticado que acessa `/login/` é redirecionado direto para o
  dashboard, sem ver o formulário nem o menu simultaneamente.
- Usuário não autenticado continua vendo somente o formulário de login,
  sem menu lateral.
- Login com usuário/senha inválidos continua exibindo a mensagem de erro
  normalmente (sem regressão).
**Regras relacionadas:** RN-047 (nova).
**Dependências:** nenhuma.
**Tipo de validação:** QA (QA-030).
**Entrega do Dev (2026-08-29):**
- `LoginView` (`apps/core/urls.py`) ganhou `redirect_authenticated_user=True`;
  já usa `LOGIN_REDIRECT_URL = "home"` existente, sem mudança de settings.
- Usuário autenticado que acessa `/login/` agora é redirecionado direto ao
  dashboard, sem o formulário nem o menu aparecerem juntos.
- 3 testes novos (`apps/core/tests.py`): redireciona autenticado, formulário
  normal para não autenticado, erro de credencial inválida sem regressão.
- Suíte completa (367 testes) sem regressão.
- Não é tela nova nem alteração visual — não coube validação visual em
  navegador (o bug era de redirecionamento, não de layout).
**Pendência atual:** aguardando revisão do QA.

---

## Histórico de Alterações
| Data | Alteração |
|---|---|
| 2026-08-29 | FEAT-030 entregue pelo Dev, `🔍 Aguardando QA` — `LoginView` ganhou `redirect_authenticated_user=True`; 3 testes novos, suíte completa (367 testes) sem regressão | Correção de uma linha em `apps/core/urls.py`, sem tela nova; validação visual em navegador não se aplica (bug era de redirecionamento, não de layout) |
| 2026-08-28 | Criada FEAT-030 (bug: usuário autenticado via o menu lateral sobreposto na tela de login) a partir de print enviado pelo usuário; `business_rules.md` recebe RN-047 (nova) | Causa identificada por leitura direta do template (`core/base.html` já condiciona o menu a `user.is_authenticated` corretamente) e da rota (`apps/core/urls.py` usa `LoginView` padrão do Django, que não redireciona usuário já logado); `⬜ Pendente`, sem código ainda — fora do escopo do Orquestrador corrigir |
| 2026-08-28 | FEAT-029 entregue pelo Dev, `🔍 Aguardando QA` — bloqueio por middleware cobrindo toda tela autenticada, ação de ligar/desligar na tela "Administrador > Usuários", migração liga usuário já existente; 15 testes novos, suíte completa (352 testes) sem regressão | Validado ponta a ponta contra o servidor real (usuário criado como no `/admin/` nasceu desligado, viu o aviso, Administrador ligou, dado passou a aparecer); Dev deixou nota técnica para o Orquestrador formalizar em RN-045: criação de usuário direto por código (bootstrap/testes) nasce Ligada, para sempre existir um Administrador capaz de liberar os demais; validação visual em navegador não executada (mesma limitação da FEAT-028) |
| 2026-08-28 | Criada FEAT-029 (liberação de acesso aos dados — controle Ligado/Desligado por usuário, separado do perfil; Desligado vê o menu mas nenhuma tela com dado, com aviso de "aguardando liberação"); `business_rules.md` recebe RN-045 (nova) e RN-043 ganha nota de ampliação; depende de FEAT-028 (tela "Administrador > Usuários") | Usuário pediu que toda conta nova entre sem ver informação nenhuma até o Administrador liberar; confirmado com o usuário (CLAUDE.md §9, 3 perguntas): vale para Administrador também, só conta nova (não afeta quem já usa o sistema hoje), aviso claro em vez de tela vazia sem explicação; `⬜ Pendente`, sem código ainda |
| 2026-08-28 | FEAT-028 entregue pelo Dev, `🔍 Aguardando QA` — item "Usuários" no menu "Administrador", tela lista usuário/e-mail/perfil com botão para trocar perfil, bloqueado para Analista e para autotroca; 8 testes novos, suíte completa (340 testes) sem regressão | Validado ponta a ponta contra o servidor real (login, listagem, troca de perfil persistida), sem ferramenta de navegador/Playwright disponível nesta sessão — validação visual em navegador não executada, fica como pendência para o QA/usuário |
| 2026-08-28 | Criada FEAT-028 (Administrador > Usuários — trocar perfil Administrador ↔ Analista, sem criar/editar outros campos/desativar); `business_rules.md` recebe ampliação da RN-004 | Usuário pediu, depois de descobrir que a troca de perfil só existia pelo `/admin/` do Django, uma opção equivalente dentro do menu Administrador; confirmado com o usuário (CLAUDE.md §9): escopo mínimo (listar + trocar perfil, sem CRUD completo); `⬜ Pendente`, sem código ainda |
| 2026-08-28 | FEAT-027 → `🔍 Aguardando QA` — validação end-to-end com a conta real do usuário: login via AD cria usuário com perfil Analista, sincroniza e-mail/nome (RN-044), recusa senha errada, bloqueia usuário desativado mesmo com senha certa; verificação de certificado TLS desativada na conexão LDAPS (mesma solução do `modulo-posVenda`); 68 testes automatizados passam no host e dentro do container com `USE_AD_AUTH=true` | Decisão do TLS confirmada explicitamente pelo usuário (CLAUDE.md §9 — segurança); `.env` real preenchido a pedido do usuário, copiado do `.env` do `modulo-posVenda`, sem expor valores no chat; `ADR-002` atualizada por Dev nesta sessão — recomenda-se revisão do Orquestrador, já que alterar ADR normalmente não é papel do Dev (CLAUDE.md §1) |
| 2026-08-28 | FEAT-027 (infra) resolvida pelo DevOps — `python-ldap==3.4.3`/`django-auth-ldap==4.8.0` no `requirements.txt`, `libldap2-dev`/`libsasl2-dev` no `Dockerfile`, 6 variáveis `AD_*`/`USE_AD_AUTH` adicionadas ao `docker-compose.yml` (serviço `web`); build da imagem e `manage.py check` com `USE_AD_AUTH=true` verificados dentro do container, sem erro | `ADR-002` atualizada; ainda falta preencher os valores reais de `AD_*` no `.env` (tarefa manual de quem tem acesso aos dois `.env` reais) e recriar o container `web` local (`docker compose up -d --build web`) — feature segue `🔄 Em andamento`, não vai para QA sem isso |
| 2026-08-28 | FEAT-027 iniciada pelo Dev, `🔄 Em andamento` — `AUTHENTICATION_BACKENDS` condicional a `USE_AD_AUTH` (`config/settings.py`, degrada sozinho se a lib LDAP faltar), `apps/integracoes/ad/ad_sync.py` (RN-044, reaproveitado do `modulo-posVenda`) conectado via `apps/core/apps.py`; criação automática de usuário via AD fica Analista sem código novo (`perfil` já é o default do model, RN-004/RN-043); 18 testes novos, suíte completa sem regressão nova | Bloqueio de DevOps (`ADR-002`) segue de pé — `requirements.txt`/`Dockerfile`/`.env` real ainda faltam; os critérios de aceite que dependem de LDAP de verdade não puderam ser executados, por isso a feature não foi para `🔍 Aguardando QA`; TLS sem verificação de certificado (usado no `modulo-posVenda`) não foi copiado — decisão de segurança fora do pedido original, fica pendente de confirmação |
| 2026-08-28 | Criação de FEAT-027 (integração com Active Directory — autenticação via LDAP + sincronização de e-mail/nome pós-login) | Usuário pediu a integração; resolve pendência aberta em `lixo.md` (item 7); RN-043/RN-044 criadas, RN-004 recebe exceção, `ADR-002` registra a decisão de reaproveitar a mesma conta de serviço/config do `modulo-posVenda` |
| 2026-08-27 | FEAT-026 ampliada: gráfico "Faturado por Estado" expande, ao clicar num estado, mostrando "Faturado por Município" (mesma informação, drill-down de 1 nível, `?estado=UF&municipio=Nome`); **correção**: comentário Django de múltiplas linhas vazava como texto na tela real (limitação do `{# #}`, corrigida com `{% comment %}`) — usuário reportou com captura de tela; suíte completa (265 testes) sem regressão | Usuário pediu o drill-down por Município com a mesma informação do gráfico de estado; reportou com print o texto vazado na tela, causa identificada e corrigida no mesmo atendimento |
| 2026-08-27 | FEAT-026 ampliada: gráfico "Faturado por Estado" (1 barra por UF, valor faturado + meta do estado) dentro de "Faturamento", clicável para filtrar os 2 cards por estado (`?estado=UF`); `business_rules.md` precisa da RN-027 nova; suíte completa (258 testes) sem regressão | Usuário pediu, direto ao Dev: gráfico de quanto já faturou por estado, clicável para filtrar os cards com o programado e o já faturado daquele estado; layout do gráfico ajustado a pedido do usuário (valor faturado e, no final da linha, a meta do estado) |
| 2026-08-27 | FEAT-026 entregue pelo Dev, `🔍 Aguardando QA` — cards "Valor Total do Projeto" e "Valor já Faturado" (`core/home.html`), cálculo em `apps/ri/services.py`; Dashboard ganha submenus Faturamento/Equipamentos/Relatórios (pedido do usuário durante a implementação); valores em R$ com separador de milhar pt-BR; suíte completa (260 testes) sem regressão | Usuário pediu, direto ao Dev: 3 submenus no Dashboard com os cards dentro de "Faturamento", e números mais legíveis com R$; Orquestrador ainda precisa formalizar esses 2 ajustes no critério de aceite da FEAT-026 (nota deixada pelo Dev no checklist) |
| 2026-08-27 | Criada FEAT-026 (dashboard financeiro — cards "Valor Total do Projeto" e "Valor já faturado" com diferença para a meta); `business_rules.md` recebe RN-025 e RN-026, e RN-017 é corrigida (Nobreak inicial passa a ter valor, só não exibido nas telas onde já aparece); `⬜ Pendente`, sem código ainda | Usuário pediu cards contando a "história" do projeto; confirmado com o usuário (CLAUDE.md §9, 3 perguntas): Nobreak tem valor no catálogo apesar da RN-017 anterior, "aprovado pela EACE" exige RI em Faturamento Concluído, soma é visão global; usuário sinalizou mais cards a caminho para este mesmo dashboard |
| 2026-08-27 | FEAT-024 e FEAT-025 recebem critério de aceite adicional: INEP com "Conectada" na coluna "Status escola" da Planilha EACE muda o RI para "Faturamento Concluído" (RN-024, nova) ao sincronizar, com `concluido_em` gravado; `business_rules.md` recebe RN-024; ambas as features seguem `🔍 Aguardando QA`, correção é do Dev antes de o QA revisar | Usuário pediu que a coluna T (Status escola) do `doc/EACE.csv` dispare essa troca ao clicar em qualquer um dos 2 botões de sincronização; confirmado com o usuário (CLAUDE.md §9): vale a partir de qualquer status atual do RI (inclusive pulando etapas da RN-001), sobrepõe "Correção MEGA" em aberto e grava `concluido_em` igual a uma conclusão manual |
| 2026-08-27 | Criada FEAT-025 (Sincronizador em lote — botão "Sincronizar todas as RI" no card "Arquivo ativo" da tela Planilha EACE, reaproveitando a lógica da FEAT-024 para cada RI); `business_rules.md` recebe RN-023; `⬜ Pendente`, sem código ainda, depende de FEAT-024 estar `✅ Concluída` | Usuário pediu um botão dentro do "arquivo ativo" para sincronizar todas as RI de uma vez, sem precisar entrar RI por RI; escopo do lote (todas as RI existentes) e nível de resumo (agregado + lista de pendências) definidos pelo Orquestrador como opção mais simples e conservadora (CLAUDE.md §9), sujeitos a ajuste do usuário na validação |
| 2026-08-27 | FEAT-024 recebe critério de aceite adicional: item sincronizado (KIT ou Produto) passa a guardar Num OSP, Validação OSP e Nota Fiscal (colunas N/O/Q da planilha, por item), campos fechados exibidos como rótulo verde; `business_rules.md` recebe a ampliação de RN-022; feature segue `🔍 Aguardando QA`, correção é do Dev antes de o QA revisar | Usuário pediu para trazer as 3 colunas ao Lado 3, só como exibição, preenchidas só pelo Sincronizador; confirmado com o usuário (CLAUDE.md §9) que ficam por item (não por RI), pois a Nota Fiscal real varia entre o KIT e cada Produto da mesma planilha/INEP |
| 2026-08-27 | FEAT-022 recebe correção: editar/excluir no Lado Relatório EACE, antes só do KIT, passa a valer também para Produtos (exclusão continua só Administrador); `business_rules.md` recebe a ampliação de RN-003/RN-018 | Usuário testou o Sincronizador (FEAT-024) e reportou não conseguir excluir um Produto (ex.: "Nobreak"); confirmado com o usuário (CLAUDE.md §9) estender a mesma regra do KIT; Dev já tinha entregue o código nesse mesmo atendimento — Orquestrador formalizou a regra |
| 2026-08-27 | FEAT-024 entregue pelo Dev, `🔍 Aguardando QA` — botão "Sincronizador" no Lado Relatório EACE, casa a Planilha EACE ativa (FEAT-023) com o catálogo `KitPadrao` pelo INEP (KIT por Access Points, produto por prefixo da Descrição curta) e lança os itens com valor do catálogo; sem duplicar, respeitando RN-015; suíte completa do app `ri` (197 testes) sem regressão | Validado no navegador real (Playwright, servidor local) com uma Planilha EACE de teste (sufixo real de fornecedor/UF na Descrição), KIT e produto lançados corretamente, sem erro de console; dados de teste (usuários, escola, RI, catálogo, banco sqlite descartável) removidos depois da validação |
| 2026-08-27 | FEAT-023 entregue pelo Dev, `🔍 Aguardando QA` — menu "Administrador > Planilha EACE", upload de `.csv` validado (4 colunas mínimas), model `PlanilhaEace` singleton (novo upload substitui o anterior), ação restrita a Administrador; suíte completa dos apps `ri`/`core`/`escolas` (205 testes) sem regressão nova | Validado no navegador real (Playwright, servidor local), desktop e celular, upload real do `doc/EACE.csv`; dados de teste (usuários admin-visual/analista-visual, banco sqlite descartável) removidos depois da validação |
| 2026-08-27 | Criadas FEAT-023 (Administrador > Planilha EACE — upload) e FEAT-024 (Sincronizador do Lado Relatório EACE a partir da Planilha EACE, casando por INEP com o catálogo `KitPadrao`); `business_rules.md` recebe RN-021 e RN-022, RN-004 recebe nota de extensão | Usuário pediu para importar `doc/EACE.csv` (Projeto/INEP, Descrição do Item, Qtde Produto, Valor Unit UR) e sincronizar o Lado 3 do RI por INEP, sem remover o preenchimento manual; confirmado com o usuário (CLAUDE.md §9): upload pela tela (não caminho fixo de servidor), sem tabela de linhas — só o arquivo ativo é guardado e reprocessado a cada sincronização — e sem integração externa; ambas `⬜ Pendente`, sem código ainda |
| 2026-08-27 | FEAT-009 corrigida pelo Dev — resposta do financeiro (PDF + XML) passa a ficar disponível para download dentro do próprio card do e-mail na linha do tempo do RI (`RiHistorico.documentos`, M2M para `Documento`, migração `0018`), sem duplicar arquivo; suíte completa do app `ri` (172 testes) passando | Orquestrador repassou ao Dev a pendência de correção registrada em 2026-08-26; usuário testou uma primeira versão (2 cards de anexo separados) e pediu para ficar no mesmo card do e-mail — redesenhado ainda no mesmo dia; feature segue `🔍 Aguardando QA`, aguardando o QA revisar |
| 2026-08-26 | FEAT-009 recebe pendência de correção: NF (PDF) e XML recebidos do financeiro (`Documento`, RF-08) são gravados no banco, mas nenhuma tela expõe link de download — nem a linha do tempo (FEAT-014/RN-008), nem outra tela do RI; critério "NF (PDF) e XML ficam disponíveis no INEP" não está cumprido | Usuário testou a tela do RI e reportou que o e-mail do financeiro tem anexo de PDF e XML, mas os logs não oferecem opção de baixá-los; feature segue `🔍 Aguardando QA`, correção é do Dev antes de o QA revisar |
| 2026-08-26 | FEAT-005 entregue pelo Dev, `🔍 Aguardando QA` — confronto 2 (RN-003): KIT/Produtos do Lado IXC × Lado Relatório EACE, divergência persistida (`RiDivergencia`) e recalculada a cada mudança, destaque vermelho no Lado IXC, bloqueio do envio ao financeiro e destaque no grid funcionando de ponta a ponta; suíte completa do app `ri` (164 testes) passando | Validado no navegador real (Playwright contra servidor local): divergência destacada, status bloqueado com a mensagem da RN-003, grid contando e destacando o INEP; confronto 1 (RN-002) continua fora do escopo |
| 2026-08-26 | FEAT-005 atualizada — critérios do confronto 2 (Relatório EACE × IXC, RN-003) fechados: Descrição + Quantidade, sem Valor Unitário; `business_rules.md` recebe a reescrita da RN-003 | Usuário pediu o bloqueio do envio ao financeiro quando o KIT/Produtos do Lado 3 divergem do Lado 2, com destaque vermelho no Lado IXC; confirmado com o usuário (CLAUDE.md §9) que Valor Unitário sai do confronto e Quantidade continua; ainda `⬜ Pendente` — falta o Dev implementar |
| 2026-08-26 | FEAT-022 entregue pelo Dev, `🔍 Aguardando QA` — painel "Relatório EACE (3º lado)" com KIT Instalado + Produtos do catálogo `KitPadrao`, Valor Unitário resolvido automaticamente, limite de 1 KIT e edição/exclusão liberada só para o item KIT; suíte completa do app `ri` (159 testes) passando | Validado no navegador real (Playwright contra servidor local), desktop e celular, sem erro de console; dados de teste (usuário/escola/RI/catálogo) usados num banco sqlite descartável, não commitado |
| 2026-08-26 | Criada FEAT-022 (Lado Relatório EACE ganha o formulário do Lado IXC — KIT Instalado + Produtos, sem Data Ativação/Município/Estado); `business_rules.md` recebe RN-018 | Usuário pediu paridade de campos com o Lado IXC; confirmado com o usuário (CLAUDE.md §9): limite de 1 KIT (RN-015) também vale aqui, com edição/exclusão liberada só para o item KIT (senão a correção ficaria bloqueada), e Valor Unitário vindo do catálogo `KitPadrao` (não zero, diferente do Lado IXC) |
| 2026-08-26 | FEAT-021 entregue pelo Dev, `🔍 Aguardando QA` — campo `Escola.nobreak_inicial` (padrão "Nobreak", migration `0002` já backfilla as 2.622 escolas existentes), exibido junto ao Kit no card "Kit declarado (1º lado)" (tela do RI e drill-down do grid), sempre 1 un.; 4 testes novos, suíte completa (170 testes) passando | Validado no app real (Docker), desktop e celular, com usuário e RI de teste temporários (removidos depois); usuário pediu, durante a implementação, que a quantidade seja sempre 1 — implementado, mas formalização em `business_rules.md`/critério de aceite é pendência do Orquestrador |
| 2026-08-26 | Criada FEAT-021 (Nobreak declarado, item padrão fixo no Kit Declarado/1º lado); `business_rules.md` recebe RN-017 | Usuário pediu que toda Escola já nasça também com um Nobreak, além do Kit, exibido no lado 1; confirmado com o usuário (CLAUDE.md §9): mesmo Nobreak para todas as escolas, sem variação por lote, e sem valor financeiro (só informativo) |
| 2026-08-26 | FEAT-020 entregue pelo Dev, `🔍 Aguardando QA` — status renomeado para "Resposta Financeiro" (migração `0016`, só metadado), gatilho automático estendido para resposta fora do padrão, 3º card no grid com contagem e link de filtro; suíte completa (163 testes) passando | Validado contra o app real (Docker): RI de teste criado, movido para "Resposta Financeiro", card mostrou a contagem correta e o clique filtrou o grid; dados de teste (escola/RI/usuário) removidos depois da validação |
| 2026-08-26 | Criada FEAT-020 (status "Resposta Financeiro" + card de contagem no grid); `business_rules.md` recebe RN-016, RN-001 e RN-005 atualizadas; FEAT-009 recebe nota de divergência (critério do status automático desatualizado pela RN-016) | Usuário pediu que o status "Aguardando financeiro" mude para "Resposta Financeiro" quando o financeiro responder o e-mail, e um card de contagem igual aos 2 já existentes no topo do grid (`grid_inep.html:19-28`), clicável para filtrar; confirmado com o usuário: é renomeação do status já existente (posição 5 da RN-001, hoje "Aguardando Anexo portal EACE"), sem status novo; gatilho passa a valer também para resposta fora do padrão; card fica no topo do Grid de INEPs |
| 2026-08-26 | FEAT-005 recebe critério de aceite adicional: alerta de campo único do KIT (RN-002 esclarecida) — mesma mecânica visual já usada no município (FEAT-018/RN-014), amarelo em vez de vermelho | Usuário pediu que, na divergência entre o KIT declarado antes do projeto e o KIT instalado, o campo do KIT fique amarelo, do mesmo jeito já feito para município; resolve a favor de manter os campos `Ri.kit_informado_ixc`/`Ri.divergencia_kit`, hoje sem uso; não muda o Confronto 1 item a item já documentado; implementação continua pendente (FEAT-005 `⬜ Pendente`) |
| 2026-08-26 | FEAT-019 entregue pelo Dev, `🔍 Aguardando QA` — status do RI, responsável e histórico atualizam sem reload (HTMX, out-of-band); suíte completa (150 testes) passando | Validado no navegador real (Docker, claro e escuro); senha do usuário local `admin` redefinida temporariamente durante a validação, mesmo precedente da FEAT-013 |
| 2026-08-26 | Criada FEAT-019 (atualizações sem reload completo — HTMX), a partir de `ri_status_update_view`/`ri_responsavel_update_view`/histórico (FEAT-014); `architecture.md` recebe a seção "Padrão de Interação Frontend" | Usuário pediu para não perder a posição na tela a cada troca de status/log; HTMX já era o padrão do Dev (`dev.md`) mas a decisão não estava registrada em `architecture.md`, nem havia feature para aplicá-la às telas já entregues |
| 2026-08-26 | FEAT-014 recebe novo critério de aceite e pendência de correção: cadastro/edição/exclusão dos itens do Lado IXC e cadastro do Relatório EACE não geram entrada na linha do tempo hoje, só a troca de status e a troca de responsável (RN-012); `business_rules.md` RN-008 esclarecida no mesmo sentido | Usuário testou a tela do RI e reportou que a linha do tempo mostra a troca de status mas não o que é cadastrado no Lado IXC/Relatório EACE (2º e 3º lado); feature segue `🔍 Aguardando QA`, correção é do Dev antes de o QA revisar |
| 2026-08-26 | Orquestrador consolidou FEAT-017/FEAT-018: critérios de aceite reescritos para o desenho final (aba criada automaticamente, exigência de KIT/Data de Ativação/Município/Estado só no envio/download, limite de 1 KIT por INEP); as 6 notas de "Ajuste"/"Correção" acumuladas no dia (registradas pelo Dev, cada uma sinalizando "atualização formal é pendência do Orquestrador") foram substituídas por um resumo único de "Entrega do Dev" e um "Histórico" de até 3 linhas por feature, conforme CLAUDE.md §7. `business_rules.md`: RN-013 reescrita, RN-014 ganha nota de amendment, RN-015 criada (1 KIT por INEP); `architecture.md` e `modelo-dados.md` também sincronizados | Usuário chamou o Orquestrador sem pedido específico — entendido como pedido para colocar em dia a documentação que o Dev vinha sinalizando como pendente ao longo do dia |
| 2026-08-26 | Criadas FEAT-017 (anexo do financeiro em planilha, substitui PDF) e FEAT-018 (Município/Estado manuais no Lado IXC); RN-013 e RN-014 criadas em `business_rules.md` | Usuário pediu que o e-mail ao financeiro leve a planilha-modelo `doc/FATURAMENTO MATERIAS EACE.xlsx` preenchida (uma aba por produto, mapeamento de células E/F/H da linha 10 e C/F/G/H/I da linha 16), em vez do PDF, mais um botão para baixar a planilha antes de enviar; estrutura da planilha real conferida (`doc/`, 7 abas fixas) antes de registrar os critérios; duas decisões tomadas com o usuário (CLAUDE.md §9): produto sem aba correspondente bloqueia o envio (a planilha-modelo precisa ganhar a aba antes) e Município/Estado do Lado IXC são campos novos, manuais, comparados ao cadastro da Escola com alerta visual não bloqueante |
| 2026-08-25 | Corrigido: o roteiro `docs/devops/AZURE_AD_GRAPH_FINANCEIRO.md`, reportado como entregue pelo DevOps na entrada abaixo, **não existe no repositório** — verificado agora (`git status`, busca no disco): não há pasta `docs/` no `Sistema_posvenda`, o arquivo não está commitado nem untracked. O serviço `email_scheduler`/`docker-compose.yml` e a variável `GRAPH_FINANCEIRO_POLL_INTERVAL_SECONDS`/`.env.example` são reais (working tree, ainda não commitados) — só o documento do roteiro foi relatado sem ter sido de fato criado | Usuário pediu instruções exatas para repassar ao time de infra; antes de repassar, Orquestrador conferiu o arquivo citado e não o encontrou — mesmo padrão de entrega não confirmada já visto na FEAT-012 (2026-08-22) |
| 2026-08-25 | FEAT-009: pendência de agendamento resolvida pelo DevOps (serviço `email_scheduler` em `docker-compose.yml`, variável `GRAPH_FINANCEIRO_POLL_INTERVAL_SECONDS`) e roteiro de provisionamento do app do Azure AD entregue em `docs/devops/AZURE_AD_GRAPH_FINANCEIRO.md`; pendência de leitura real segue aberta, agora só dependente de alguém com papel de admin do tenant executar o roteiro | Usuário pediu ao DevOps para resolver as duas causas do recebimento não funcionar; provisionar o app exige credencial real de admin (CLAUDE.md §6/§9) e não foi feito por nenhum agente — corretamente documentado como roteiro em vez de simulado |
| 2026-08-25 | Usuário reportou não conseguir receber e-mail no Sistema_posvenda (envio funciona normalmente). Orquestrador inspecionou `.env` e `config/settings.py` (só leitura, nada alterado) e confirmou que a causa é a mesma já registrada na pendência da FEAT-009: `GRAPH_FINANCEIRO_ENABLED=False` e `GRAPH_FINANCEIRO_CLIENT_ID`/`_CLIENT_SECRET`/`_TENANT_ID` em branco no `.env` real — não é bug de código, é a pendência de infraestrutura já conhecida (app do Azure AD dedicado + agendamento do polling, ambos ainda não provisionados) | Nenhum código ou `.env` foi alterado; ação corretiva é do DevOps, fora do escopo do Orquestrador |
| 2026-08-25 | FEAT-009 entregue pelo Dev, `🔍 Aguardando QA` — leitura automática da resposta do financeiro (RF-08/09/19), suíte completa (118 testes) passando | Usuário autorizou iniciar fora de ordem, sem esperar o QA de FEAT-008; IMAP com usuário/senha foi tentado e falhou contra a caixa real (Microsoft aposentou essa autenticação) — a leitura passou a usar Microsoft Graph, com um app do Azure AD exclusivo deste sistema (usuário confirmou que não pode depender do app do `modulo-posVenda`); esse app ainda não existe, então a sincronização real não foi validada ponta a ponta |
| 2026-08-25 | Corrigido `RiItemIxc.descricao_item` gravando a Descrição completa do catálogo (com parênteses) em vez da curta (RN-011); migration de dados `0011` limpou os 2 itens já lançados afetados | Usuário pediu para excluir do banco o texto entre parênteses; catálogo `KitPadrao` (fonte da planilha LPU, usado na reimportação) verificado e mantido intocado — só o bug de gravação no Lado IXC foi corrigido, plano confirmado com o usuário antes de executar |
| 2026-08-25 | Ajuste visual no Lado IXC (`ri_detail.html`) — resumo do item na lista não mostra mais o valor (R$), só a quantidade | Usuário pediu para tirar o "— R$ 0,00" que aparecia ao lançar KIT/produto; vale para todos os itens, mesmo os já com valor real editado (RN-004); formulário de edição do item continua com o campo de valor, sem mudança |
| 2026-08-25 | FEAT-016 ajustada — painel "Kit Declarado (1º lado)" passa a mostrar a Descrição curta do catálogo (RN-011), não a completa | Usuário pediu a mesma nomenclatura já usada no Lado IXC; a Descrição completa (com o qualificador entre parênteses) ficava cortada no campo |
| 2026-08-25 | FEAT-016 complementada — painel "Kit Declarado (1º lado)" (`ri_detail.html`) passa a mostrar a descrição completa resolvida pelo catálogo, não mais o número bruto; migration de dados `0010` preenche `numero_access_points` dos 80 registros do catálogo já existentes (criados antes do campo existir); 2 testes novos, suíte completa do app `ri` (85 testes) passando | Usuário testou o INEP 35275505 (kit "4") e reportou "não teve nada de diferente" — causa raiz eram duas: view não chamava o cruzamento, e o catálogo antigo nunca tinha sido salvo de novo para derivar o campo |
| 2026-08-25 | FEAT-016 entregue pelo Dev, `🔍 Aguardando QA` — campo `KitPadrao.numero_access_points` (derivado automaticamente) e método `resolver_kit_declarado` (cruza por número de Access Points ou por texto completo, conforme o formato de `Escola.kit_inicial`); 7 testes novos, suíte completa do app `ri` (83 testes) passando | Cruzamento ainda sem tela/comando que o chame — mesmo caso já registrado na FEAT-015 (não existe geração automática de `RiItemEace`); método fica pronto para quando essa geração existir |
| 2026-08-24 | Criada FEAT-016 (cruzamento por número de Access Points entre Kit Declarado e catálogo `KitPadrao`, RN-010 ampliada) | Usuário relatou que, para parte das escolas, `Escola.kit_inicial` traz só o número do KIT (ex.: `4`) em vez do texto completo do catálogo; confirmado que o número sempre corresponde à quantidade de Access Points e que "lote 1"/"lote 2" citados eram o 1º e 2º lado (RN-002), não `Escola.lote`; feature `⬜ Pendente`, sem dependências bloqueando |
| 2026-08-24 | FEAT-004 recebe novo critério de aceite e pendência: Lado IXC troca Descrição livre por "KIT Instalado" (obrigatório) + itens individuais via "+" (Serviço), ambos com origem no catálogo `KitPadrao`; ver `business_rules.md` (RN-011 criada) | Usuário pediu, no Lado IXC (chamado inicialmente de "lote 2", corrigido para "lado 2"), um input de KIT Instalado com valor unitário e um "+" para lançar serviço/quantidade/valor unitário de itens individuais; ainda não implementado — próximo passo é do Dev |
| 2026-08-24 | `modelo-dados-diagrama.html`/`.pdf` atualizados (entidade `kit_padrao` e relação pontilhada, não FK, com `escola`); PDF regerado via Edge headless e confirmado por captura de tela (nenhuma entidade/campo cortado) | Regra permanente de sincronização (linha 8) — atualização em `modelo-dados.md` (`kit_padrao`, FEAT-015) exigia atualizar os documentos derivados no mesmo turno |
| 2026-08-24 | Pendência da FEAT-015 sobre `RiItemEace` encerrada — usuário decidiu manter Valor Unitário único, sem discriminar Equipamento/Serviço (RN-010) |
| 2026-08-24 | FEAT-015 entregue pelo Dev, `🔍 Aguardando QA` — catálogo `KitPadrao` evoluído (lote/unidade/valor de equipamento e de serviço) e comando `importar_catalogo_lpu`; suíte completa do app `ri` (59 testes) passando; rodado contra a planilha real (80 registros). Orquestrador verificou e resolveu a pendência "Lote 1/2/3" (não é `Escola.lote`) nas duas features; ajustou os critérios de aceite da FEAT-015 para refletir que não há código de geração automática de `RiItemEace` a corrigir | Dev sinalizou divergência entre critério de aceite e código real; Orquestrador verificou os dados da planilha e os demais documentos antes de decidir, sem perguntar ao usuário algo já verificável |
| 2026-08-24 | Criada FEAT-015 (catálogo de preços fixos EACE — LPU, RN-010 ampliada); FEAT-004 recebe nota de pendência sobre "Lote 1/2/3" a confirmar | Usuário indicou a aba `LPU` de `CONSOLIDADO EACE.xlsx` (produto/lote/valor de equipamento/valor de serviço) como origem dos valores fixos do Kit e pediu integração com a tabela que já guarda o kit de cada escola |
| 2026-08-23 | FEAT-008 e FEAT-009 recebem RN-009 (código de rastreio do e-mail do RI) e critérios de aceite mais explícitos sobre como a resposta é associada ao INEP | Usuário pediu para trazer ao `Sistema_posvenda` a funcionalidade de e-mail (enviar, receber, código de rastreio e histórico) já existente no `modulo-posVenda`; mecanismo de rastreio reaproveita `apps/core/email_tracking.py` de lá (RN-042 original), adaptado para tratar só RI, sem a taxonomia de níveis RE/MC/Global; "tela de e-mail" e "histórico" já estavam cobertos pelo formulário da FEAT-008 e pela linha do tempo da FEAT-014 — não há tela de caixa de entrada separada, mesmo padrão do sistema de origem; features seguem `⬜ Pendente`, aguardando o usuário autorizar o início |
| 2026-08-22 | FEAT-014 entregue pelo Dev, `🔍 Aguardando QA` — linha do tempo do RI (mensagem com anexo opcional, anexo isolado, log automático de troca de status); suíte completa (49 testes) passando | Usuário autorizou adiar o critério de envio/recebimento de e-mail, que depende da FEAT-008/FEAT-009 (ainda `⬜ Pendente`); tipo "e-mail" já existe no modelo para quando essas features gravarem ali |
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
| 2026-08-24 | RN-010 criada (Kit Declarado: origem automática + catálogo de valores padrão); FEAT-004 recebe critério de aceite e pendência ligados a ela — não muda de status (Orquestrador não reprova; só QA pode) | Usuário apontou, revisando o card "Kit Declarado (1º Lado)", que descrição/Quantidade/Valor Unitário não devem ser digitados: descrição vem de `Escola.kit_inicial` (coluna H do `CONSOLIDADO EACE.xlsx`, mesma fonte da FEAT-002) e Quantidade/Valor Unitário vêm de um catálogo de valores padrão por kit, tanto no lançamento inicial quanto em correção; confirmado por pergunta direta (CLAUDE.md §9) |
| 2026-08-24 | FEAT-004 (RN-010) corrigida pelo Dev: painel "Kit declarado" deixa de aceitar descrição/Quantidade/Valor Unitário digitados; model `KitPadrao` (catálogo de valores) criado; suíte completa (63 testes) passando; status continua `🔍 Aguardando QA` | Dev chamado diretamente para corrigir a pendência da RN-010 registrada pelo Orquestrador; catálogo nasce vazio (nenhum valor inventado); validação visual em navegador não executada neste ambiente (sem Playwright disponível), só checagem via cliente de teste Django |
| 2026-08-24 | FEAT-004: botão "Lançar item do Kit declarado" e a ação `adicionar_eace` removidos pelo Dev — painel passa a só exibir `Escola.kit_inicial` (leitura). Usuário esclareceu que Lote 1 será gravado direto no banco (bloqueado até existir a planilha de Quantidade/Valor por kit) e Lote 2/3 continuam sendo cadastrados pelo administrador via Django admin, só na v1 | Usuário pediu a remoção do botão; RN-010/critérios de aceite da FEAT-004 ainda descrevem o fluxo antigo — atualização formal é pendência do Orquestrador, fora do escopo do Dev |
| 2026-08-25 | RN-012 criada (Responsável do RI); FEAT-007 volta de `🔍 Aguardando QA` para `🔄 Em andamento`, agora com 5 colunas na tabela principal (sem "Responsável") | Usuário viu, direto na tela real, a coluna "Responsável" ainda na tabela principal do grid e pediu que ela saia de lá e vire campo editável dentro do RI (drill-down e `ri_detail`), com um `<select>` dos usuários do sistema para reatribuir; mesmo padrão de permissão do campo "Status do RI" (RN-004); reabre, com decisão explícita do usuário, a discussão já registrada em 2026-08-22 sobre onde essa coluna deveria viver — implementação é do Dev, fora do escopo do Orquestrador |
