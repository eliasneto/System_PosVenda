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

### FEAT-004 — Cadastro manual de RI e itens (lado EACE e lado IXC)
**Descrição:** Formulários para digitar manualmente, por INEP, os itens do
relatório EACE e os dados do atendimento IXC, na mesma granularidade
(item, quantidade, valor unitário).
**Tipo:** fullstack
**Status:** ⬜ Pendente
**Prioridade:** Alta
**Critérios de aceite:**
- RI nasce vinculado a um INEP já existente, status inicial "Implantação
  EACE".
- Cada lado (EACE e IXC) aceita múltiplos itens por INEP (1:N).
- Campo "Descrição do Item" é texto livre, sem validação de formato.
- Lado EACE não é editável depois de criado, exceto por um novo lançamento
  representando um relatório atualizado da EACE (RN-003).
**Regras relacionadas:** RN-003, RN-004, RF-02, RF-03.
**Dependências:** FEAT-002, FEAT-003.
**Tipo de validação:** QA (QA-004).
**Entrega do Dev:** nenhuma ainda.
**Pendência atual:** nenhuma.

---

### FEAT-005 — Confronto de divergências
**Descrição:** Comparar item a item os dois lados (EACE × IXC) em
quantidade e valor unitário, sem tolerância, e sinalizar divergência.
**Tipo:** fullstack
**Status:** ⬜ Pendente
**Prioridade:** Alta
**Critérios de aceite:**
- Diferença de quantidade ou valor unitário em qualquer item gera
  divergência formal.
- Comparação estrita — acentuação, espaço e caixa contam como divergência.
- Campo "Descrição do Item" não entra no confronto de valor/quantidade.
- INEP com divergência aberta aparece destacado (fundo vermelho) no grid
  (FEAT-007).
**Regras relacionadas:** RN-002, RN-003, RF-04, RF-06.
**Dependências:** FEAT-004.
**Tipo de validação:** QA (QA-005).
**Entrega do Dev:** nenhuma ainda.
**Pendência atual:** catálogo fechado dos tipos de divergência formal
confirmado pelo cliente em 2026-08-21 (P-03, RN-003) — sem pendência nesse
ponto. Resta o critério de casamento entre itens dos dois lados, ainda não
confirmado; implementar a comparação de quantidade/valor com o catálogo de
`tipo` já fechado.

---

### FEAT-006 — Ciclo de vida do RI (máquina de status)
**Descrição:** Os 8 status do RI (RN-001), incluindo o desvio manual
"Correção MEGA" e o bloqueio de transição enquanto houver divergência
aberta.
**Tipo:** fullstack
**Status:** ⬜ Pendente
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
**Dependências:** FEAT-004, FEAT-005.
**Tipo de validação:** QA (QA-006).
**Entrega do Dev:** nenhuma ainda.
**Pendência atual:** nenhuma.

---

### FEAT-007 — Grid de INEPs com drill-down
**Descrição:** Grid principal (INEP, Nome da escola, Endereço, Status,
Responsável) com filtro por status e detalhe dos itens por INEP.
**Tipo:** frontend-functional
**Status:** 🔍 Aguardando QA
**Prioridade:** Alta
**Critérios de aceite:**
- Uma linha do grid por INEP; botão de detalhe abre os itens (EACE e IXC)
  daquele INEP.
- Filtro por status disponível no grid principal (grid único de itens, não
  separado por tipo de validação).
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

## Histórico de Alterações
| Data | Alteração |
|---|---|
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
