# Regras de Negócio — Gerenciador Pós-Venda (Faturamento EACE por INEP)
_Última atualização: 2026-09-04_ (RN-053 criada — Mês da Operação do Lado IXC na planilha, ano sempre corrente; RN-054 criada — linhas de grade ocultas em toda aba criada automaticamente; RN-055 criada — produto sem valor de Equipamento sai da lista do Lado IXC; RN-056 criada — gatilho da RPA de anexo no portal EACE, log por Nota Fiscal com seleção manual de PDF/XML, ampliada com os motivos "OSP não encontrada"/"Documento já enviado"; RN-057 criada — validação dos dados da Nota Fiscal extraídos do PDF contra o portal EACE antes do anexo, ampliada em 2026-09-04 com Produto/Valor extraídos do PDF exibidos no select antes de escolher; RN-058 criada — fila de execução serializada do RPA EACE, com reprocessamento automático só de erro não mapeado, implementada e testada em 2026-09-03; RN-063 criada em 2026-09-04 — consulta somente-leitura das pendências do portal EACE antes de escolher a Nota Fiscal; RN-064 criada em 2026-09-04 — correção: OSP resolvida pelo item que bate com o Valor da NF, não mais "qualquer" OSP do RI, e consulta de pendências cobrindo todas as OSPs distintas do RI)

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
| 5 | Resposta Financeiro | Sistema | qualquer resposta do financeiro entra na caixa de entrada — válida (NF + XML) ou fora do padrão (RN-016) |
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
leitura de resposta na caixa de entrada do financeiro — RN-016 estende essa
2ª transição para cobrir também resposta fora do padrão, não só a válida).

**Features relacionadas:** FEAT-006.

**Status:** Ativa

### RN-016 — Status "Resposta Financeiro" e extensão do gatilho automático
**Descrição:** O status 5 do ciclo de vida do RI (RN-001), antes chamado
"Aguardando Anexo portal EACE", passa a se chamar "Resposta Financeiro".
Continua sendo o mesmo status na mesma posição da sequência — não é um
status novo. O gatilho automático que leva o RI até ele passa a valer para
qualquer resposta do financeiro identificada pelo código de rastreio
(RN-009), não só a resposta no padrão esperado (1 PDF + 1 XML): antes, uma
resposta fora do padrão deixava o RI parado em "Aguardando financeiro" e só
gerava alerta no log; agora ela também avança o RI para "Resposta
Financeiro".

**Contexto:** Usuário pediu, em 2026-08-26, visibilidade de quando o
financeiro responde ao e-mail — e um card no grid (FEAT-007) com a
contagem de INEPs nesse status, no mesmo padrão dos 2 cards já existentes
("Total de INEPs" e "Com divergência"). Confirmado que é renomeação do
status automático já existente (não um status novo, para não exigir uma
transição manual adicional que hoje não existe) e que o gatilho deve valer
também para resposta fora do padrão.

**Critérios:**
- Rótulo exibido em todo o sistema (filtro do grid, badge de status,
  drill-down, `ri_detail`, histórico do RI) passa de "Aguardando Anexo
  portal EACE" para "Resposta Financeiro"; valor interno gravado no banco
  não muda — RI já existentes nesse status continuam íntegros, sem
  necessidade de migração de dado.
- Qualquer resposta do financeiro identificada pelo código de rastreio
  (RN-009) muda o RI de "Aguardando financeiro" para "Resposta Financeiro"
  — resposta válida (1 PDF + 1 XML) e resposta fora do padrão.
- A 2ª validação da Nota Fiscal (RN-005) continua ocorrendo durante esse
  status, sem mudança de critério — só o nome do status muda.
- Grid de INEPs (FEAT-007) ganha um 3º card, mesmo estilo dos 2 já
  existentes no topo da tela, com a contagem de INEPs cujo RI atual está em
  "Resposta Financeiro"; clique no card filtra o grid por esse status
  (mesmo efeito de selecionar o valor no filtro "Status do RI" já
  existente).

**Exceções:** e-mail sem código de rastreio identificável no assunto
continua sem mudar o status de nenhum RI (RN-009) — a exceção é só para
resposta fora do padrão de anexo, que agora muda o status mesmo assim.

**Impacto técnico:** `apps/ri/models.py` (`Ri.STATUS_CHOICES`, rótulo do
valor `AGUARDANDO_ANEXO_PORTAL_EACE`); `apps/ri/services.py`
(`_processar_mensagem` chama `trocar_status_com_log` também no ramo "fora
do padrão", não só no ramo válido); `apps/ri/views.py`
(`grid_inep_view`) e `grid_inep.html` (3º card, contagem e link de
filtro).

**Features relacionadas:** FEAT-007, FEAT-009, FEAT-020.

**Status:** Ativa

**Correção (2026-09-02):** usuário reportou falso positivo (INEP 35271561)
— o RI avançava para "Resposta Financeiro" sem o financeiro ter respondido
de verdade. Causa: o código de rastreio (RN-009) identifica só o RI de
origem a partir do assunto, mas não confirma quem enviou a mensagem —
qualquer remetente com o código no assunto (reencaminhamento, "Responder a
todos", teste manual a partir de e-mail pessoal) avançava o status.
Corrigido exigindo que o remetente (cabeçalho "From") seja do domínio do
financeiro (`speedcsc.com.br`, mesmo domínio de `DESTINATARIOS_FINANCEIRO`
em `apps/ri/views.py`) para a mensagem contar como resposta de verdade;
remetente de outro domínio não muda o status, não grava
`EmailFinanceiroLog` nem entrada na linha do tempo — só alerta no log do
servidor, mesmo padrão já usado para "sem código"/"sem RI aguardando".
Decisão confirmada com o usuário (CLAUDE.md §9): validar por domínio, não
por lista fixa de endereços nem pelos destinatários do e-mail enviado
naquele RI específico. Implantado em produção em 2026-09-02 (commit
`f1c834a`, procedimento de `DEPLOYMENT.md`, backup antes do deploy).

### RN-019 — Exceção do Administrador: saída manual de "Aguardando financeiro"
**Descrição:** Enquanto o RI está no status "Aguardando financeiro" (RN-001),
a transição para o próximo status continua sendo, por padrão, só
automática — disparada pelo sistema quando chega qualquer resposta do
financeiro (RN-016). Um usuário com perfil Administrador (RN-004) ganha uma
exceção: pode forçar manualmente essa transição, levando o RI direto para
"Resposta Financeiro", sem esperar o gatilho automático. Usuário com perfil
Analista continua sem nenhuma opção manual nesse status, como já é hoje
para todo mundo.

**Contexto:** Usuário pediu, em 2026-08-26, que esse status ficasse
bloqueado a alterações e só um Administrador pudesse desbloquear.
Levantamento mostrou que "Aguardando financeiro" já não tem hoje transição
manual para nenhum perfil — fica de fora de `STATUS_RI_MANUAIS` (FEAT-006)
por ser 100% automático (RN-001). Confirmado com o usuário que a regra é,
então, uma exceção nova só para Administrador, e não o bloqueio de algo que
já existisse.

**Critérios:**
- Único destino permitido para essa transição manual: "Resposta
  Financeiro" — o mesmo destino que o gatilho automático (RN-016) usaria.
- Disponível só quando o RI está em "Aguardando financeiro"; usuário
  Administrador (RN-004, `is_administrador`) vê a opção; Analista não vê.
- Ação registra log na linha do tempo do RI (RN-008), igual às demais
  trocas de status, identificando o Administrador como autor.
- Se, depois dessa transição manual, o RI algum dia voltar a "Aguardando
  financeiro" (ex.: reenvio ao financeiro), a exceção volta a valer
  normalmente — não é um destravamento permanente do RI, é uma ação
  pontual de transição.

**Exceções:** não altera nenhuma outra regra do ciclo de vida (RN-001,
RN-003, RN-016); não libera edição dos demais dados do RI (Lado IXC, Kit,
anexos) — isso continua sem restrição própria, fora do escopo desta regra.

**Impacto técnico:** `apps/ri/views.py` — incluir "Aguardando financeiro"
como origem manual só quando `request.user.is_administrador` for
verdadeiro, com destino fixo "Resposta Financeiro" (não abre o mesmo
`<select>` genérico dos demais status manuais); `_validar_transicao_status_ri`
ganha esse caso específico; `STATUS_RI_MANUAIS`/`STATUS_RI_EDITAVEIS`
continuam sem essa opção para o perfil Analista.

**Features relacionadas:** FEAT-006.

**Status:** Ativa

### RN-020 — Bloqueio dos campos do Lado IXC e do Lado Relatório EACE em "Faturamento Concluído"
**Descrição:** Enquanto o RI está no status "Faturamento Concluído" (RN-001,
status 7), os campos do Lado IXC (RN-011, inclusive Data de Ativação/
Município/Estado da RN-014) e do Lado Relatório EACE (RN-018) — 2º e 3º lado
do RI — ficam bloqueados para edição, tanto para Administrador quanto para
Analista. Enquanto o RI estiver nesse status, só um usuário com perfil
Administrador (RN-004) pode trocar o status do RI; Analista perde, só nesse
status, a opção manual de troca que tem nos demais status editáveis
(RN-001). Assim que o Administrador troca o status para outro valor, os
campos do Lado IXC e do Lado Relatório EACE voltam a ficar liberados
normalmente, com as mesmas regras de permissão de hoje (RN-004) — o bloqueio
vale só enquanto o RI permanece em "Faturamento Concluído", não é um
travamento permanente do RI.

**Contexto:** Usuário pediu, em 2026-08-27, que "Faturamento Concluído"
funcione como um checkpoint: uma vez concluído o faturamento, os dados que
alimentaram esse fechamento (Lado IXC e Lado Relatório EACE) não podem mais
ser alterados por engano, e só o Administrador decide reabrir o processo.

**Critérios:**
- Bloqueio de campo: todo campo dos formulários do Lado IXC (KIT Instalado +
  Produtos + Data Ativação/Município/Estado) e do Lado Relatório EACE (KIT
  Instalado + Produtos) fica somente leitura enquanto
  `ri.status == "Faturamento Concluído"` — vale para Administrador e
  Analista, sem exceção de perfil.
- Bloqueio de status: com o RI em "Faturamento Concluído", só Administrador
  (RN-004, `is_administrador`) vê e usa a opção de trocar o status; Analista
  não vê a opção, mesmo "Faturamento Concluído" sendo hoje um dos status que
  ambos os perfis trocam livremente (`STATUS_RI_MANUAIS`).
- Ao Administrador trocar o status para qualquer outro valor, os campos do
  Lado IXC e do Lado Relatório EACE voltam a ficar editáveis normalmente.
- Se o RI voltar a "Faturamento Concluído" depois (novo ciclo), o bloqueio
  de campo e a exigência de Administrador para trocar o status valem de
  novo — não é um destravamento permanente.

**Exceções:** não altera as demais regras do ciclo de vida (RN-001, RN-003,
RN-016, RN-019) nem os destinos possíveis da transição — esta regra só
acrescenta quem pode acionar a troca de status a partir de "Faturamento
Concluído" e o bloqueio de campo associado a esse status. Campos fora do
Lado IXC e do Lado Relatório EACE (ex.: Responsável, RN-012) não são
afetados por este bloqueio.

**Impacto técnico:** `apps/ri/views.py` —
`_validar_transicao_status_ri` ganha guarda para
`ri.status == Ri.FATURAMENTO_CONCLUIDO` exigindo `usuario.is_administrador`;
views/formulários de edição do Lado IXC e do Lado Relatório EACE (RN-011/
RN-018) passam a checar `ri.status` antes de aceitar alteração (bloqueio
também no backend, não só ocultar campo no template); templates dos dois
lados renderizam os campos como somente leitura nesse status.

**Features relacionadas:** FEAT-006, FEAT-004.

**Status:** Ativa

### RN-012 — Responsável pelo RI (atribuição editável)
**Descrição:** O RI criado pela tela do sistema (`ri_iniciar`, FEAT-004)
nasce com o usuário que o criou como responsável (comportamento já
existente). Esse responsável pode ser trocado depois, manualmente, por
qualquer usuário autorizado a editar o RI — não é um dado fixo do cadastro.

**Contexto:** usuário identificou, em 2026-08-25, que a coluna
"Responsável" estava aparecendo na tabela principal do grid (FEAT-007) e
pediu que ela saia de lá e passe a viver dentro das informações do RI, como
campo editável.

**Critérios:** campo exibido dentro do RI (drill-down do grid da FEAT-007 e
tela de detalhe da FEAT-004), nunca como coluna da tabela principal do grid;
editável por meio de uma lista (`<select>`) com os usuários cadastrados no
sistema; mesma permissão de edição do restante do RI — Administrador e
Analista (RN-004), sem restrição adicional de perfil.

**Exceções:** RI criado fora da tela do sistema (Django admin, fixture,
carga de dados) pode ficar sem responsável — a tela mostra "Não atribuído"
até alguém escolher um usuário na lista; a atribuição automática ao criador
vale só para o fluxo normal (`ri_iniciar`). Não há forma de voltar um RI já
atribuído para "Não atribuído" pela tela — só reatribuir a outro usuário.

**Impacto técnico:** campo já existente `Ri.responsavel` (FK para o usuário do
sistema, `null=True`); view/endpoint de atualização (mesmo padrão do
`ri_status_update_view`, RN-001) e um `<select>` com `User.objects.all()` (ou
equivalente) no template do drill-down e do `ri_detail`.

**Features relacionadas:** FEAT-004, FEAT-007.

**Status:** Ativa

### RN-002 — Alerta de divergência entre Kit declarado e IXC (não bloqueia)
**Descrição:** O sistema compara a descrição do KIT declarado pela EACE
**antes do início do projeto** ("Kit declarado", 1º lado do RI) contra a
descrição do KIT instalado, informada pelo usuário a partir do chamado do
IXC (2º lado do RI, item com `eh_kit=True`). Divergência = destaque visual
amarelo no campo do KIT.

**Contexto:** Mesma regra já levantada em `requisitos.md` (ITEM 12): o que
a EACE declara antes da instalação pode diferir do que foi realmente
implantado em campo (registrado via IXC) — isso é só um alerta de atenção,
não um erro formal. O RI tem **3 lados** (Kit declarado, IXC, Relatório
EACE — ver RN-003); este é o confronto entre o 1º e o 2º.

**Critérios:** Campo único — "Kit declarado" (`Escola.kit_inicial`, ou o
item mais recente de `RiItemEace` quando houver lançamento via admin) ×
"KIT Instalado" do Lado IXC (item com `eh_kit=True`). Destaque amarelo só
quando os dois lados têm valor preenchido e divergem; comparação estrita
(acentuação, espaço e caixa contam como divergência). Não compara
Quantidade nem Valor Unitário — é comparação de descrição, não de item de
estoque.

**Exceções:** Não bloqueia nenhuma transição de status nem o avanço do
processo — é apenas indicador visual.

**Impacto técnico:** `divergencia_kit`, computado na renderização de
`ri_detail_view` — mesmo padrão do alerta de Município/Estado (RN-014),
não persiste em `RiDivergencia` (essa tabela é só para as divergências que
bloqueiam, RN-003). `RiItemEace` (model da FEAT-004) guarda no máximo o
histórico de descrições já lançadas via Django admin — nunca uma lista de
produtos avulsos (o lançamento manual foi removido pela RN-010 em
2026-08-24); por isso o confronto é de campo único, não item a item.

**Features relacionadas:** FEAT-004, FEAT-005, FEAT-006.

**Status:** Ativa (redação consolidada em 2026-08-31 — fecha a pendência
registrada em `checklist.md`/FEAT-005: o alerta já estava implementado e
confirmado em 2026-08-27, junto com a FEAT-006; a comparação nunca foi
"item a item" nem envolveu Valor Unitário — "Kit declarado" sempre
representou uma única descrição, nunca uma lista de itens)

### RN-051 — Status do RI e ação "Enviar e-mail" na tela de detalhe

**Descrição:** A tela de detalhe do RI (FEAT-004) ganha o status editável
direto por lá — mesmo padrão já usado pelo campo "Responsável" (RN-012):
`<select>` que salva sozinho ao trocar, via HTMX, sem sair da página. Ao
entrar no status "Envio de Email para Faturamento", o botão/modal "Enviar
e-mail" (mesmo modal de composição do Grid de INEPs — FEAT-008) aparece na
própria tela de detalhe, sem precisar voltar para o Grid nem recarregar a
página (F5). A opção "Envio de Email para Faturamento" só aparece na lista
do `<select>` quando as regras de negócio de hoje permitem enviar de fato
(RN-013).

**Contexto:** Pedido do usuário em 2026-09-02 — evitar sair da tela de
detalhe (onde ficam os 3 lados e o histórico) só para trocar o status e
compor o e-mail, que antes só existia no Grid de INEPs. Ajuste de layout
no mesmo dia: o bloco (status + "Enviar e-mail") saiu do cabeçalho, ao
lado do título — ficou apertado perto do campo "Responsável" — e passou
para logo abaixo dos 3 lados, acima do Histórico de Comunicação.

**Critérios:**
- `<select>` de status na tela de detalhe, abaixo dos 3 lados; troca salva
  sozinha ao selecionar (sem botão "Salvar" separado), sem recarregar a
  página.
- Opção "Envio de Email para Faturamento" só aparece quando: há KIT
  Instalado lançado no Lado IXC, Data de Ativação preenchida, Município e
  Estado (Lado IXC) preenchidos, CNPJ e CNPJ Fictício (RN-048)
  preenchidos, e não há divergência aberta bloqueante (RN-003) — mesma
  checagem de `gerar_planilha_faturamento` (RN-013). Continua aparecendo
  se já for o status atual do RI, mesmo que algo mude depois e deixe de
  estar "pronto" (não esconde o próprio valor selecionado).
- Ao entrar nesse status, o botão "Enviar e-mail" aparece automaticamente,
  sem F5; ao sair dele (ex.: e-mail enviado, status muda sozinho para
  "Aguardando financeiro"), o botão some do mesmo jeito.
- A regra de quem pode trocar de/para qual status (RN-001/RN-003/RN-020)
  não muda — só a disponibilidade da OPÇÃO nesta tela.

**Exceções:** nenhuma.

**Impacto técnico:** `_status_ri_opcoes_disponiveis`/`_pronto_para_envio_
email_financeiro` (apps/ri/views.py), reaproveita `itens_faltando_para_
planilha_faturamento` extraída de `gerar_planilha_faturamento` (RN-013,
apps/ri/services.py); partials `_status_pill_detail.html`,
`_acao_envio_email_detail.html`, `_modal_enviar_email.html` (extraído do
Grid — `grid_inep.html` passa a incluir o mesmo partial, sem duplicar
HTML); delegação de evento em `core/base.html` (troca de status/clique no
"Enviar e-mail" continuam funcionando mesmo depois de o próprio bloco ser
reposto por uma troca HTMX).

**Features relacionadas:** FEAT-004, FEAT-007, FEAT-008.

**Status:** Ativa

### RN-052 — Lado IXC só é editável com o RI em "Em Andamento"

**Descrição:** O status "Andamento" (RN-001) passa a se chamar "Em
Andamento" em toda a tela (rótulo de exibição — o valor interno gravado no
banco continua `andamento`, nenhum dado existente muda). Os campos do Lado
IXC (2º lado do RI: KIT Instalado + Produtos da RN-011, Município/Estado
da RN-014, CNPJ/CNPJ Fictício da RN-048) só aceitam lançamento/edição/
exclusão com o RI nesse status; em qualquer outro status (inclusive
"Implantação EACE", o status inicial, e "Faturamento Concluído", que já
tinha bloqueio próprio pela RN-020) os campos ficam somente leitura, para
Administrador e Analista sem distinção. Os itens já lançados continuam
visíveis — só deixam de ser editáveis/excluíveis — e o formulário de
lançamento (KIT/Produtos/Data Ativação/CNPJ/Município/Estado) continua
renderizado, com os campos desabilitados, em vez de sumir da tela: o
usuário precisa continuar vendo os dados já preenchidos mesmo fora de "Em
Andamento".

**Contexto:** Pedido do usuário em 2026-09-02 — formaliza, no código, o que
a RN-001 já descrevia (linha 2 da tabela do ciclo de vida: "chamado do IXC
chega; usuário digita no sistema os dados do chamado (lado IXC)" só depois
de o status virar "Andamento"), mas que nunca tinha sido tecnicamente
travado; até aqui o Lado IXC só era bloqueado em "Faturamento Concluído"
(RN-020).

**Critérios:**
- Bloqueio de campo: todo campo do formulário do Lado IXC (KIT Instalado +
  Produtos + Data Ativação/Município/Estado/CNPJ/CNPJ Fictício) fica
  somente leitura sempre que `ri.status != Ri.ANDAMENTO` — vale para
  Administrador e Analista, sem exceção de perfil.
- Diferente da RN-020 (Lado Relatório EACE, formulário some da tela), aqui
  o formulário continua visível e desabilitado — não escondido — porque
  Data de Ativação/CNPJ/Município/Estado são valores do próprio RI que o
  usuário precisa continuar consultando mesmo sem poder editar.
- Itens já lançados no Lado IXC continuam aparecendo na lista; só os
  ícones de editar/excluir de cada item somem fora de "Em Andamento".
- Backend também recusa a submissão fora desse status (bloqueio não é só
  visual) — tanto o "Salvar" do formulário único quanto a edição/exclusão
  direta de um item já lançado.
- Assim que o RI volta para "Em Andamento" (troca manual, RN-001), o Lado
  IXC volta a aceitar lançamento/edição normalmente — não é um travamento
  permanente.
- Não altera o Lado Relatório EACE (3º lado) — esse continua exclusivamente
  sob a RN-020 (bloqueado só em "Faturamento Concluído"), sem relação com
  esta regra.

**Exceções:** não altera as demais regras do ciclo de vida (RN-001, RN-003,
RN-020); não afeta campos fora do Lado IXC (ex.: Responsável, RN-012;
Status do RI, RN-051).

**Impacto técnico:** `apps/ri/models.py` — rótulo do `Ri.ANDAMENTO` muda
para "Em Andamento" em `STATUS_CHOICES` (migração `0026_alter_ri_status`,
só o `verbose_name` da choice, sem alterar o valor gravado). `apps/ri/
views.py` — `_lado_ixc_editavel(ri)` (equivalente ao `_bloqueado_
faturamento_concluido` da RN-020, mas para este lado); guarda a ação
"salvar_ixc" em `ri_detail_view` e as views `ri_item_ixc_update_view`/
`ri_item_ixc_delete_view`; campos de `kit_form`/`data_ativacao_form`/
`produto_formset` ganham `field.disabled = True` quando não editável, para
o template renderizar somente leitura sem esconder o formulário.
`ri_detail.html` — variável de contexto `lado_ixc_editavel` substitui, só
no bloco do Lado IXC, o antigo uso de `ri_bloqueado_faturamento_
concluido` (que continua exclusivo do bloco do Lado Relatório EACE).

**Features relacionadas:** FEAT-004, FEAT-006.

**Status:** Ativa

## Confronto de Divergências

### RN-003 — Confronto de divergências (Relatório EACE × IXC)
**Descrição:** O sistema compara o "KIT Instalado" e os "Produtos"
lançados no Lado Relatório EACE (3º lado, depois da instalação) contra os
lançados no Lado IXC (2º lado, atendimento) — mesmo critério nos dois:
Descrição (qual KIT/Produto do catálogo `KitPadrao`, RN-011/RN-018) e
Quantidade, sem tolerância. Valor Unitário fica fora deste confronto
(esclarecido em 2026-08-26 — ver abaixo). Divergência aparece destacada em
**vermelho nos itens do Lado IXC** (2º lado) — é ali que a correção deve
ser feita (editando/excluindo o item, RN-004). Bloqueia a transição do RI
de "Andamento" para "Envio de Email para faturamento" (RN-001) enquanto
estiver aberta.

**Contexto:** `requisitos.md`, ITEM 4 e "PROCESSO do Projeto" (correções 1
e 2, 2026-08-20). **Esclarecido em 2026-08-22:** o RI tem **3 lados**, não
2 — "Kit declarado" (1º, dado da EACE antes do projeto, RN-002), "IXC"
(2º) e "Relatório EACE" (3º, baixado depois da instalação). Este confronto
formal é sempre entre o 3º lado e o 2º; o 1º lado não participa dele — só
do confronto informal RN-002.

**Esclarecido em 2026-08-26:** a redação original (2026-08-22) previa
comparar quantidade **e valor unitário**. Usuário confirmou tirar Valor
Unitário do confronto — o Lado IXC nasce sempre com R$ 0,00 (RN-011,
criada depois desta regra), então comparar valor acusaria divergência em
todo item, sem relação nenhuma com o faturamento real. Quantidade
continua no confronto. Isso também fecha a pendência de casamento entre
itens que esta regra deixou em aberto desde 2026-08-22: com os dois lados
escolhendo a descrição no mesmo catálogo `KitPadrao` (RN-011/RN-018), o
casamento por Descrição igual deixou de ser uma aproximação arriscada.

**Ajustada em 2026-09-02 (pedido do usuário):** o confronto só é feito
quando os **dois** lados (IXC e Relatório EACE) já têm algum item lançado
(KIT ou Produto). Com um dos dois lados totalmente vazio, não há
divergência nenhuma — nem no KIT, nem nos Produtos — mesmo que o outro
lado já tenha itens. Antes deste ajuste, um RI recém-sincronizado (só o
Lado Relatório EACE preenchido, Lado IXC ainda não iniciado, ou o inverso)
já entrava como "Com divergência" no Grid de INEPs (FEAT-007) só por o
outro lado estar vazio — sem nenhuma inconsistência real entre os dois.
Verificado nos dados reais em 2026-09-02: 473 divergências abertas hoje,
471 delas (99,6%) eram esse falso positivo.

**Critérios:**
- Sem divergência quando o Lado IXC ou o Lado Relatório EACE está
  totalmente vazio (nenhum KIT nem Produto lançado ainda nesse lado) —
  ajuste de 2026-09-02, ver acima. Com os dois lados tendo algum item, os
  critérios abaixo valem normalmente.
- Comparação por Descrição (qual KIT/Produto do catálogo foi escolhido) +
  Quantidade — Valor Unitário não entra (ver esclarecimento acima).
- "KIT Instalado": comparado isoladamente — no máximo 1 de cada lado
  (RN-015/RN-018). Divergência quando um lado tem KIT lançado e o outro
  não (só quando os dois lados já têm algum item — ver acima), ou quando a
  Descrição do KIT difere entre os dois lados.
- "Produtos": comparados como conjunto — para cada Descrição de produto, a
  Quantidade total lançada no Lado IXC precisa ser igual à Quantidade
  total lançada no Lado Relatório EACE. Produto faltando, sobrando ou com
  quantidade diferente em qualquer um dos dois lados = divergência.
- Comparação estrita — acentuação, espaço e maiúscula/minúscula contam
  como divergência (a Descrição vem do mesmo catálogo nos dois lados, então
  isso só ocorre na prática via "Outro", com número de Access Points
  diferente).
- Recalculada automaticamente a cada lançamento, edição ou exclusão de
  item em qualquer um dos dois lados — não é uma ação manual de "conferir".
- O lado do Relatório EACE nunca é editado pelo pós-venda diretamente, a
  não ser pela exceção abaixo (RN-018, ampliada em 2026-08-27) — qualquer
  item, KIT ou Produto, pode ser editado/excluído.

**Exceção (RN-018, criada em 2026-08-26 para o KIT; ampliada em
2026-08-27 para os Produtos):** qualquer item do Relatório EACE — "KIT
Instalado" ou "Produto" — pode ser editado/excluído (mesmo padrão de
permissão da RN-004 já usado no Lado IXC; exclusão só Administrador). A
exceção nasceu só para o KIT: sem ela, o limite de 1 KIT por INEP
(RN-015, estendido ao Relatório EACE pela RN-018) tornaria impossível
corrigir o KIT pela tela. Ampliada para Produtos depois que o
Sincronizador (FEAT-024/RN-022) passou a casar itens da Planilha EACE
automaticamente — um Produto casado errado (ex.: "Nobreak" por outro
item) também precisa de correção pela tela, não só o KIT.

**Exceções:** o catálogo fechado dos tipos de divergência formal (`valor`,
`quantidade`, `kit_relatorio`, `nf_financeiro`) foi **confirmado pelo
cliente em 2026-08-21 (P-03)** — ver `requisitos.md`, "PROCESSO do
Projeto"; pode ser ajustado ao longo do projeto se necessário, mas vale
para a v1 a partir de agora. Este confronto usa o tipo `kit_relatorio`.

**Impacto técnico:** tabela `ri_divergencia` (`modelo-dados.md`) — um
registro por RI para este confronto (`tipo=kit_relatorio`,
`bloqueia=True`), sincronizado (criado, atualizado ou resolvido) a cada
mudança em `RiItemIxc` ou `RiItemRelatorioEace`, não acumulado por item
divergente. O bloqueio da transição "Andamento" → "Envio de Email para
faturamento" já está implementado (`_validar_transicao_status_ri`, `apps/
ri/views.py`, checa `ri.divergencias.filter(resolvida_em__isnull=True,
bloqueia=True).exists()`) — falta só o gerador da divergência descrito
aqui. O grid de INEPs (FEAT-007) já destaca (fundo vermelho) o INEP com
divergência aberta — também só falta o gerador alimentar isso. Destaque
vermelho nos itens do Lado IXC (`ri_detail.html`) usa a mesma mecânica de
acessibilidade já usada na RN-014 (borda + texto, não só cor).
`comparar_kit_e_produtos_ixc_relatorio` (`apps/ri/services.py`) ganha a
checagem de lado vazio (ajuste 2026-09-02) antes de montar o confronto.
Correção pontual dos dados já gravados: management command
`recalcular_divergencia_kit_relatorio` (modo simulação por padrão,
`--aplicar` para gravar), já rodado com `--aplicar` (autorizado pelo
usuário) contra o banco real em 2026-09-02 — das 473 divergências abertas,
471 foram resolvidas (falso positivo), restam 2 divergências reais.

**Features relacionadas:** FEAT-004, FEAT-005, FEAT-006, FEAT-007.

**Status:** Ativa (redação reescrita em 2026-08-26 — confronto por
Descrição + Quantidade, sem Valor Unitário; pendência de casamento entre
itens encerrada) — **extensão (RN-018, 2026-08-27):** exceção de editar/
excluir do Relatório EACE deixou de valer só para o KIT, passa a valer
também para Produtos — **ajuste (2026-09-02):** lado vazio deixa de ser
divergência.

## Permissões

### RN-004 — Permissões por perfil de usuário
**Descrição:** Dois perfis fixos — Administrador (acesso total) e Analista
(tudo, exceto excluir). Aplica-se ao CRUD de INEP/item, aos documentos
anexados (NF/XML) e ao cadastro de usuário.

**Contexto:** `requisitos.md`, ITEM 13.

**Critérios:** exclusão de INEP/item e de usuário — só Administrador;
criação, edição e leitura de INEP/item, documentos e marcações manuais
(inclusive "Correção MEGA", RN-001) — Administrador e Analista; cadastro de
usuário (criar/editar/desativar) — só Administrador. **Ampliação (FEAT-028,
2026-08-28):** troca de perfil (Administrador ↔ Analista) de outro usuário
pode ser feita pela tela interna "Administrador > Usuários", sem precisar do
`/admin/` do Django; escopo dessa tela é só listar usuário e trocar perfil —
criar usuário, editar username/e-mail e ativar/desativar continuam só pelo
`/admin/`. Administrador não pode trocar o próprio perfil por essa tela
(evita se autorrebaixar sem outro Administrador por perto para reverter).

**Exceções:** login via Active Directory (RN-043) cria automaticamente o
usuário local com perfil Analista no primeiro acesso — único caso em que a
criação de usuário não depende do Administrador; edição e desativação
continuam exclusivas dele, inclusive para usuário criado assim.

**Impacto técnico:** campo `usuario.perfil` (`administrador`/`analista`,
`modelo-dados.md`); checagem de permissão nas ações de exclusão e no
cadastro de usuário; view da tela "Administrador > Usuários" (FEAT-028)
bloqueia troca de perfil da própria conta logada.

**Features relacionadas:** FEAT-003, FEAT-004, FEAT-006, FEAT-010, FEAT-027,
FEAT-028.

**Status:** Ativa — **extensão (RN-021, 2026-08-27):** upload/gestão da
Planilha EACE (Administrador > Planilha EACE) também restrita a
Administrador. **Exceção (RN-043, 2026-08-28):** criação automática de
usuário via login AD, sempre com perfil Analista. **Ampliação (FEAT-028,
2026-08-28):** tela interna para trocar perfil de outro usuário, com bloqueio
de autopromoção/autorrebaixamento.

### RN-045 — Liberação de acesso aos dados (liga/desliga)
**Descrição:** Além do perfil (RN-004), toda conta de usuário tem um segundo
controle, independente do perfil: acesso aos dados **Ligado**/**Desligado**.
Com login válido mas conta **Desligada**, a pessoa entra no sistema e vê o
menu normalmente, mas nenhuma tela com informação real do projeto mostra
dado nenhum — em vez disso, mostra um aviso claro de que o acesso depende da
liberação do Administrador. Vale para Analista **e também para
Administrador** (perfil não isenta do controle).

**Contexto:** pedido do usuário em 2026-08-28 — quer um controle manual do
Administrador antes de qualquer conta nova (inclusive as criadas sozinhas
pelo login via Active Directory, RN-043) enxergar dado real do projeto.

**Critérios:** toda tela com informação do projeto fica bloqueada (aviso de
"aguardando liberação", não tela vazia sem explicação, nem erro) para
usuário Desligado — inclui os 3 submenus do Dashboard, o Grid de INEPs e o
detalhe do RI (com drill-down), e também as telas do próprio menu
Administrador (Planilha EACE, Usuários — RN-004/RN-021/FEAT-028). O menu
lateral continua visível normalmente. Administrador liga/desliga qualquer
outra conta pela tela "Administrador > Usuários" (mesma tela da RN-004
ampliada, FEAT-028) — não pode ligar/desligar a própria conta pela tela
(mesmo motivo da RN-004: evita se desligar sem outro Administrador já ligado
por perto para reverter).

**Exceções:** conta de usuário que já existia **antes** desta regra entrar
em vigor continua exatamente como está hoje — com acesso aos dados, sem
precisar de nenhuma liberação manual. O padrão "nasce Desligado" vale só
para conta criada a partir de agora, seja pelo `/admin/` do Django, seja
pelo login automático via Active Directory (RN-043). Essa exceção também
garante que sempre existe pelo menos um Administrador já Ligado capaz de
liberar as contas novas — sem isso, ninguém conseguiria ligar ninguém.

**Impacto técnico:** novo campo booleano no model `User`, ausente do
`modelo-dados.md` atual — precisa ser somado lá (nome técnico a critério do
Dev, seguindo o padrão de `perfil`); migração de dado (não só de schema)
para marcar todo usuário já existente como Ligado, já que o valor padrão do
campo (Desligado) só vale para linha nova — mesmo padrão já usado em
`ri.migrations.0010_backfill_numero_access_points`; checagem de acesso
precisa cobrir toda tela autenticada com dado, não só uma view isolada
(mecanismo de aplicação — decorator, mixin ou middleware — é decisão técnica
do Dev); toggle na tela "Administrador > Usuários" (FEAT-028) bloqueia
autotroca da própria conta logada, mesmo padrão já usado ali para o perfil.

**Features relacionadas:** FEAT-004, FEAT-006, FEAT-007, FEAT-010, FEAT-026,
FEAT-027, FEAT-028, FEAT-029.

**Status:** Ativa

## Autenticação

### RN-043 — Autenticação via Active Directory (login)
**Descrição:** O login do sistema passa a validar usuário e senha contra o
Active Directory (LDAP), reaproveitando o padrão do `modulo-posVenda`
(`django_auth_ldap.backend.LDAPBackend`), com `ModelBackend` (login local)
como fallback quando `USE_AD_AUTH` estiver desligado ou a biblioteca LDAP
não estiver disponível.

**Contexto:** decisão do usuário em 2026-08-28, resolvendo a pendência
registrada em `lixo.md` (item 7) sobre se haveria integração com AD.

**Critérios:** primeiro login bem-sucedido de um usuário válido no AD que
ainda não tem cadastro local cria o usuário automaticamente, com perfil
Analista (RN-004) — nunca Administrador; usuário já existente localmente
autentica normalmente pelo AD, sem duplicar cadastro; usuário desativado
localmente (`is_active=False`) não consegue logar mesmo com senha correta
no AD, mesma regra que já vale hoje para login local.

**Exceções:** RN-004 — cadastro automático via AD é a única forma de
criação de usuário que não depende do Administrador; edição e desativação
continuam exclusivas dele.

**Impacto técnico:** `AUTHENTICATION_BACKENDS` condicional a `USE_AD_AUTH`
(`config/settings.py`); variáveis `AD_SERVER_URI`, `AD_BIND_DN`,
`AD_BIND_PASSWORD`, `AD_USER_SEARCH_BASE`, `AD_DEFAULT_DOMAIN`
reaproveitadas com os mesmos valores já usados no `.env` do
`modulo-posVenda` — decisão explícita do usuário, ver `ADR-002`; perfil
Analista atribuído no momento da criação automática do usuário.

**Features relacionadas:** FEAT-027, FEAT-029.

**Status:** Ativa — **ampliação (RN-045, 2026-08-28):** usuário criado
automaticamente por este login nasce também com acesso aos dados Desligado,
mesmo critério de qualquer conta nova a partir de agora.

### RN-044 — Sincronização de e-mail e nome via Active Directory (pós-login)
**Descrição:** A cada login bem-sucedido (via AD ou local), o sistema busca
no AD, pela mesma conta de serviço de bind da RN-043, o e-mail e o nome
(`displayName`/`sn`) do usuário e atualiza o cadastro local quando
diferente — reaproveita `apps/integracoes/ad/ad_sync.py` do
`modulo-posVenda`.

**Contexto:** mesma decisão de 2026-08-28 (RN-043).

**Critérios:** não sobrescreve e-mail já em uso por outro usuário local — a
atualização é ignorada nesse caso, sem erro visível ao usuário; falha ou
indisponibilidade do LDAP não bloqueia o login, só deixa de sincronizar
naquele acesso.

**Exceções:** se `USE_AD_AUTH` estiver desligado ou o LDAP indisponível, a
sincronização não ocorre — sem isso não há como consultar o AD.

**Impacto técnico:** reaproveita `sincronizar_email_usuario`,
`sincronizar_nome_usuario` e o receiver do signal `user_logged_in` de
`apps/integracoes/ad/ad_sync.py`.

**Features relacionadas:** FEAT-027.

**Status:** Ativa

### RN-047 — Redirecionamento de usuário já autenticado na tela de login
**Descrição:** Usuário com sessão já autenticada que acessar a URL de login
(`/login/`) deve ser redirecionado automaticamente para o dashboard, sem ver
o formulário de login.

**Contexto:** bug reportado pelo usuário em 2026-08-28 — usuário logado que
acessava `/login/` via `LoginView` do Django (que, por padrão, não
redireciona quem já tem sessão ativa) via o formulário de login normalmente;
como o `base.html` exibe o menu lateral para qualquer usuário autenticado
(independente da página), a tela de login aparecia com o menu do sistema
sobreposto.

**Critérios:** requisição a `/login/` com usuário autenticado retorna
redirecionamento para a rota `home`, sem exibir o formulário; usuário não
autenticado continua vendo somente o formulário de login, sem menu lateral;
comportamento de erro de credenciais inválidas não é alterado.

**Exceções:** nenhuma.

**Impacto técnico:** configuração da `LoginView` em `apps/core/urls.py`
(ou view equivalente em `apps/core/views.py`).

**Features relacionadas:** FEAT-030.

**Status:** Ativa

## Envio e Rastreio de E-mail

### RN-009 — Código de rastreio do e-mail do RI
**Descrição:** Todo e-mail enviado ao financeiro (FEAT-008) carrega, no
assunto, um código de rastreio que identifica o INEP de origem. Ao chegar
a resposta (FEAT-009), o sistema extrai esse código do assunto para
associar a resposta ao RI correto, sem depender de remetente ou corpo do
texto.

**Contexto:** pedido do usuário em 2026-08-23 para trazer ao
`Sistema_posvenda` a funcionalidade de e-mail (enviar, receber, rastreio e
histórico) já em produção no `modulo-posVenda` — mecanismo formalizado lá
como RN-042/PO-066 (`apps/core/email_tracking.py`).

**Critérios:** código no formato `RI-AAAAMMDD-INEP` (data do envio + INEP
do RI), prefixado ao assunto como `#{codigo} - {assunto original}` — mesma
mecânica de `montar_codigo_rastreio`/`montar_assunto_com_codigo` do
`modulo-posVenda`, adaptada: sem a taxonomia de níveis RE/RI/MC/Global do
RN-042 original, porque este sistema só trata RI (RN-008, exceção). Na
leitura da resposta (FEAT-009), o assunto é varrido com o mesmo padrão de
regex (`extrair_codigos_rastreio`) para localizar o RI de origem.

**Exceções:** resposta sem código de rastreio identificável no assunto
segue a exceção já registrada em RN-005 — não bloqueia o fluxo, só gera
alerta no log de e-mail.

**Impacto técnico:** geração do código no envio (FEAT-008) e extração na
leitura (FEAT-009); reaproveita `apps/core/email_tracking.py` do
`modulo-posVenda` como base, sem dependência de model (mesmo desenho
original).

**Features relacionadas:** FEAT-008, FEAT-009.

**Status:** Ativa

### RN-013 — Anexo do financeiro em planilha (substitui o PDF)
**Descrição:** O e-mail enviado ao financeiro (FEAT-008) — e o botão
"Baixar planilha" da mesma tela — passam a gerar uma cópia preenchida da
planilha-modelo `doc/FATURAMENTO MATERIAS EACE.xlsx`, no lugar do PDF
gerado antes. A cópia tem uma aba por produto distinto lançado no Lado
IXC daquele RI (KIT incluso); produto sem aba já cadastrada **não
bloqueia** — ganha uma aba nova, criada na hora. O envio/download só é
bloqueado quando falta KIT lançado, Data de Ativação, Município ou
Estado do Lado IXC (RN-014/RN-015).

**Contexto:** Usuário pediu, em 2026-08-26, para o e-mail ao financeiro
levar a planilha-modelo em vez do PDF, porque o conteúdo dela é copiado
direto para a Nota Fiscal — a estrutura, o texto fixo e o espaçamento da
planilha não podem mudar. Regra revisada 2× no mesmo dia depois da
entrega inicial: (1) bloquear por falta de aba cadastrada se mostrou
impraticável — catálogo real tem produtos cujo nome não bate com nenhuma
aba do modelo, e usuário reportou o erro em produção ao lançar "Nobreak";
(2) a exigência de KIT/Data de Ativação/Município/Estado tentou travar o
"Salvar" do Lado IXC antes de o usuário esclarecer que deve travar só o
envio/download, para não impedir lançar um Produto novo por causa de um
campo sem relação com aquela ação.

**Critérios:**
- Linha 10 de cada aba: `E10` (VENCIMENTO) recebe a data do envio do
  e-mail (ou do clique em "Baixar planilha"); `H10` (VALOR R$) recebe a
  soma do subtotal (quantidade × valor unitário do catálogo `KitPadrao`,
  mesmo produto e Lote da escola, RN-010) de todo item lançado que caia
  naquela aba — não usa `RiItemIxc.valor_unitario` gravado no item (nasce
  0,00 por padrão, RN-011, sujeito a correção manual avulsa); `F10`
  (OBSERVAÇÕES DA NOTA FISCAL) é o mesmo texto fixo do modelo, com 4
  trechos substituídos: INEP da escola, ITEM LPU (nome do produto/KIT
  daquela aba), MUNICIPIO/UF (RN-014) e VENCIMENTO (mesma data de `E10`)
  — todo o resto do texto (nº de contrato, texto legal) é copiado sem
  alteração.
- `H12` mantém a fórmula já existente no modelo (`=SUM(H10:H11)`) — não é
  sobrescrita com um valor fixo.
- Linha 16 de cada aba: `C16` (RAZÃO SOCIAL) recebe o nome da escola,
  `F16` (ENDEREÇO) o endereço da escola, `G16` (MUNICIPIO) e `H16` (UF)
  os valores do Lado IXC (RN-014), `I16` (ITEM LPU) o mesmo nome do
  produto/KIT usado no `F10`.
- `A20` ("OPERAÇÃO COMPRA E VENDA - MÊS/ANO") passa a ser gerada a cada
  geração — ver RN-053.
- Demais células da planilha-modelo (inclusive `G10`, "CONTRATO EACE")
  são copiadas exatamente como estão — o sistema não gera nem altera o
  que não foi listado acima.
- **Nome da aba:** KIT sempre usa a aba fixa "NF KIT", com o texto "KIT
  N" (N = número de Access Points, extraído da descrição do item — RN-015
  garante no máximo 1 KIT por RI, então não há ambiguidade de qual
  prevalece). Produto avulso usa `KitPadrao.aba_planilha_financeiro`
  quando cadastrado (permite juntar produtos parecidos numa aba
  compartilhada, ex.: "Rack 3U"/"Rack 5U"/"Rack 7U" → aba "RACK" — quando
  2+ produtos caem na mesma aba, o valor de `H10` soma o subtotal de cada
  um, não só a quantidade de um deles); sem cadastro, usa a própria
  descrição do produto como nome da aba.
- **Aba sem correspondência no modelo é criada, não bloqueia:** quando o
  nome resolvido (fixo do KIT, ou de `aba_planilha_financeiro`, ou do
  próprio produto) não bate com nenhuma aba já existente no arquivo
  modelo, o sistema cria uma aba nova clonando o layout (célula,
  formatação, mesclagem e imagem — a logo do financeiro, presente em toda
  aba do modelo) de uma aba já existente; nome da aba truncado a 31
  caracteres (limite do Excel), mas o texto completo continua no `F10`/
  `I16`. Só as abas dos produtos realmente lançados neste RI entram na
  cópia final — as demais abas do modelo (produtos não lançados) saem.
- **Exigência para gerar (envio de e-mail ou "Baixar planilha"):** o RI
  precisa ter, até esse momento — não a cada "Salvar" do Lado IXC — pelo
  menos 1 item lançado, sendo 1 deles o KIT (RN-015), mais `Ri.
  data_ativacao`, `Ri.municipio_ixc` e `Ri.estado_ixc` preenchidos
  (RN-014). Falta de qualquer um bloqueia com 1 mensagem só, listando
  exatamente o que falta (ex.: "Antes de enviar o e-mail ou baixar a
  planilha, preencha no Lado IXC: o KIT Instalado, a Data de Ativação, o
  Município (Lado IXC) e o Estado (Lado IXC)."). Produto avulso nunca é
  obrigatório.
- Tela de composição de e-mail (FEAT-008) tem um botão "Baixar planilha",
  que gera e baixa a mesma cópia que seria anexada, sem enviar o e-mail —
  para o usuário validar antes de confirmar o envio; sujeito à mesma
  exigência acima.

**Exceções:** nenhuma além do critério de exigência acima — não há mais
bloqueio por produto sem aba cadastrada (revisto em 2026-08-26).

**Impacto técnico:** `apps/ri/services.py` — `gerar_planilha_faturamento`
(orquestra a geração e a checagem de exigência), `_obter_ou_criar_aba`
(usa a aba existente ou clona, copiando imagem manualmente — `Workbook.
copy_worksheet` do openpyxl não copia imagem), `_item_lpu_e_aba`,
`_resolver_catalogo_ixc`, exceção `PlanilhaFaturamentoError`; `apps/ri/
models.py` — `KitPadrao.aba_planilha_financeiro` (opcional, migration
`0014`/`0015`) e `RiItemIxc.eh_kit` (migration `0014`); anexo do e-mail
(FEAT-008) passa a ser esse arquivo, no lugar do PDF de
`gerar_pdf_dados_financeiro` (removida).

**Features relacionadas:** FEAT-008, FEAT-017, FEAT-018.

**Status:** Ativa

### RN-053 — Mês da Operação (Lado IXC) na planilha de faturamento

**Descrição:** A célula `A20` de cada aba da planilha de faturamento
(RN-013), texto fixo "OPERAÇÃO COMPRA E VENDA - MÊS/ANO", deixa de vir
copiada sem alteração do modelo e passa a ser gerada a cada envio de
e-mail/"Baixar planilha". O MÊS vem de um novo campo do Lado IXC — select
com os 12 meses, no mesmo bloco de Data de Ativação/Município/Estado/CNPJ
— nasce selecionado no mês corrente, mas continua editável. O ANO nunca
vem de campo nenhum: é sempre o ano corrente no momento de gerar a
planilha.

**Contexto:** Pedido do usuário em 2026-09-03 — o texto vinha fixo do
arquivo-modelo (`doc/FATURAMENTO MATERIAS EACE.xlsx`) e exigia edição
manual do modelo todo mês para não sair desatualizado na Nota Fiscal.

**Critérios:**
- Novo campo `Ri.mes_operacao_ixc` (1 a 12, opcional) — mesmo bloco do
  Lado IXC de Data de Ativação/Município/Estado (RN-014)/CNPJ (RN-048),
  mesmo formulário (`RiDataAtivacaoForm`). Nasce com o mês corrente como
  valor inicial quando o RI ainda não tem valor próprio salvo (mesmo
  padrão de pré-preenchimento do Município/Estado a partir do INEP,
  RN-014) — uma vez salvo, o pré-preenchimento não entra mais em ação.
  Não trava o "Salvar" do Lado IXC (mesmo padrão de Município/Estado/
  CNPJ) nem a geração da planilha — sem valor salvo, `gerar_planilha_
  faturamento` usa o mês corrente direto, nunca fica sem texto.
- `A20` de cada aba recebe `"OPERAÇÃO COMPRA E VENDA  - <MÊS>/<ANO>"`
  (mesmo espaçamento do texto original do modelo) — MÊS em maiúsculas
  por extenso (ex.: "AGOSTO"), ANO sempre `timezone.now().year` no
  momento da geração — não o ano de `data_vencimento` nem de nenhum outro
  campo do RI. Depois de 31/12, a próxima geração já usa o ano seguinte
  sozinha, sem qualquer ação manual.
- Alteração do campo gera entrada na linha do tempo (RN-008), com o NOME
  do mês (ex.: "Agosto"), não o número salvo.

**Exceções:** nenhuma além do critério acima — não altera nenhuma outra
célula ou regra da RN-013.

**Impacto técnico:** `apps/ri/models.py` — `Ri.mes_operacao_ixc`
(`MESES_OPERACAO_CHOICES`, migration `0027`); `apps/ri/forms.py` —
`RiDataAtivacaoForm` (campo `mes_operacao_ixc`, pré-preenchimento no
`__init__`); `apps/ri/services.py` — `gerar_planilha_faturamento` (monta
o texto e grava `A20`); `apps/ri/views.py` —
`ROTULOS_CAMPO_ATIVACAO_IXC`/`_texto_campo_ativacao` (log com o nome do
mês); `ri_detail.html` (novo campo no bloco do Lado IXC).

**Features relacionadas:** FEAT-008, FEAT-017, FEAT-018.

**Status:** Ativa

### RN-054 — Linhas de grade ocultas em toda aba criada automaticamente na planilha de faturamento

**Descrição:** Toda aba da planilha-modelo (RN-013) nasce sem linhas de
grade do Excel visíveis (visual mais limpo, igual à Nota Fiscal final).
Uma aba criada na hora — produto sem aba já cadastrada, clonada de
`aba_modelo` (RN-013) — nascia com a grade visível, diferente da aba "NF
KIT" e das demais já existentes no modelo: limitação do `Workbook.
copy_worksheet` do openpyxl, que não copia a configuração de exibição da
aba (mesma limitação já conhecida para imagem, RN-013).

**Contexto:** Usuário reportou em 2026-09-03: a aba "NF KIT" (sempre já
existente no modelo) vinha sem grade, mas qualquer aba criada na hora
para um produto novo vinha com grade — inconsistência visual entre abas
da mesma planilha.

**Critérios:** ao clonar uma aba nova, `nova.sheet_view.showGridLines`
recebe o mesmo valor de `aba_modelo.sheet_view.showGridLines` (hoje,
sempre desligado) — mesmo padrão já usado para copiar a imagem/logo.

**Exceções:** nenhuma.

**Impacto técnico:** `apps/ri/services.py` — `_obter_ou_criar_aba`.

**Features relacionadas:** FEAT-008, FEAT-017, FEAT-018.

**Status:** Ativa

### RN-055 — Produto sem valor de Equipamento sai da lista do Lado IXC

**Descrição:** O select "Produtos" do Lado IXC (RN-011) deixa de listar
item do catálogo `KitPadrao` sem valor de Equipamento cadastrado na LPU
(`valor_equipamento` nulo — coluna "Equipamentos (R$)" vazia no
`CONSOLIDADO EACE.xlsx`, aba LPU).

**Contexto:** Pedido do usuário em 2026-09-03 — parte do catálogo real
(ex.: item 19 "Manutenção de Rede Interna", item 25 "Injetor PoE", item
26 "Interligação por fibra-drop", entre outros com só a coluna "Serviços
(R$)" preenchida) aparecia na lista de Produtos do Lado IXC, mas a
planilha de faturamento (RN-013) usa só `KitPadrao.valor_faturavel`
(= valor de Equipamento, ajuste de 2026-08-31) — lançar um desses
produtos sempre gerava R$ 0,00 na Nota Fiscal, sem nenhuma explicação
visível pra quem lançou.

**Critérios:**
- `KitPadrao` sem `valor_equipamento` sai só do select "Produtos"
  (`kit=False`) do Lado IXC — não do select "KIT Instalado" (`kit=True`,
  sem necessidade prática: todo KIT real da LPU já tem valor de
  Equipamento, e a opção "Outro" continua funcionando fora do catálogo).
- Item já lançado antes desta regra (`RiItemIxc` existente) não é
  afetado — o filtro vale só para a lista de opções de um lançamento
  novo, não apaga nem bloqueia o que já está salvo.

**Exceções:** o Lado Relatório EACE (3º lado, RN-018) continua sem esse
filtro — usa `KitPadrao.valor_total` (Equipamento + Serviço), então um
produto só-com-Serviço continua faturável e continua na lista de lá.

**Impacto técnico:** `apps/ri/forms.py` — `_catalogo_ixc` (parâmetro
`exigir_valor_equipamento`, `True` só na chamada de `RiItemIxcProdutoForm`
— Produtos do Lado IXC; `RiItemIxcKitForm`, o Lado Relatório EACE e o
próprio filtro de KIT continuam sem alteração).

**Features relacionadas:** FEAT-004, FEAT-015.

**Status:** Ativa

### RN-056 — Gatilho da RPA de anexo no portal EACE: log por Nota Fiscal com seleção manual de PDF/XML

**Descrição:** Quando o financeiro responde (RN-016) trazendo N arquivos
PDF e N arquivos XML, o sistema conta quantos arquivos de cada tipo
vieram naquela resposta e cria um log de processamento da RPA para cada
Nota Fiscal esperada (ex.: resposta com 4 XML gera 4 logs). Cada log tem
2 campos de lista: um lista todos os XML da resposta, outro lista todos
os PDF da resposta. O usuário escolhe, em cada log, qual XML e qual PDF
formam aquela Nota Fiscal, e aciona no próprio log o disparo da RPA —
cada execução da RPA processa exatamente 1 PDF + 1 XML (upload no portal
EACE).

**Contexto:** Definido pelo usuário em 2026-09-03, resolvendo a
pendência de gatilho registrada em `ADR-004`. Substitui a hipótese de
disparo totalmente automático ou de um único botão por RI (`FEAT-010`):
a seleção manual do par PDF/XML por log é necessária porque a resposta do
financeiro pode trazer N arquivos de cada tipo (RN-005) sem garantia de
que já cheguem pareados ou na ordem certa.

**Critérios:**
- A criação dos logs é automática, disparada pela mesma resposta do
  financeiro que já muda o RI para "Resposta Financeiro" (RN-016) —
  quantidade de logs = quantidade de arquivos de cada tipo recebidos
  (RN-005 já exige quantidade de PDF igual à de XML).
- Cada log tem uma lista com os XML da resposta e outra com os PDF da
  resposta — nenhum arquivo é pré-selecionado automaticamente.
- A ação de disparo da RPA fica dentro do próprio log, só habilitada
  depois de escolhido 1 XML e 1 PDF nesse log.
- Cada execução da RPA processa 1 único par PDF+XML — nunca mais de um
  por disparo; ao terminar, o log grava o resultado ("Sucesso" ou "Erro").
- **Avanço automático de status (definido em 2026-09-03):** o RI só avança
  sozinho de "Resposta Financeiro" para "Aguardando validação EACE"
  (RN-001) quando o retorno da automação é "Sucesso"; em caso de "Erro", o
  status do RI não muda — continua em "Resposta Financeiro" até o log ser
  reprocessado com sucesso.
- **Disparo bloqueado sem sequer tentar o upload (validado contra o
  portal real em 2026-09-03)** quando: a OSP informada não existe no
  portal (motivo "OSP não encontrada"); ou a linha correspondente no
  portal já não está mais "Pendente" — já enviada, aprovada, reprovada
  etc. (motivo "Documento já enviado"). Ver também RN-057 para os
  motivos de bloqueio ligados aos dados do próprio PDF.
- **Visibilidade na tela (pedido do usuário, 2026-09-03):** a seção com os
  logs de Nota Fiscal só aparece na tela de detalhe do RI enquanto o
  status for "Resposta Financeiro" (RN-016). Os logs continuam existindo
  depois que o RI avança (item acima) ou é destravado manualmente
  (FEAT-010) — só deixam de ser exibidos nessa tela.
- **Imutabilidade após "Sucesso":** ver RN-060 — log com resultado
  "Sucesso" não aceita novo disparo nem troca de PDF/XML.

**Exceções:** Interpretação assumida pelo Orquestrador (opção mais
simples e conservadora, CLAUDE.md §9, sujeita a confirmação do usuário):
como um RI pode ter N logs (N Notas Fiscais, RN-005), o avanço automático
de status só ocorre quando **todos** os logs daquele RI estiverem com
resultado "Sucesso" — 1 log com "Erro" mantém o RI em "Resposta
Financeiro", mesmo que os demais logs já tenham sido processados com
sucesso. Também fica assumido, até o usuário dizer o contrário, que o
botão manual "anexo feito no EACE" (`FEAT-010`) continua disponível como
alternativa manual (ex.: para um Administrador destravar um RI cujo RPA
não consiga concluir) — mesmo padrão de exceção manual já usado em
RN-019.

**Impacto técnico:** novo model de log de execução da RPA (nome a definir
pelo Dev), vinculado ao RI/INEP e aos documentos (PDF/XML) da resposta do
financeiro (RN-005/RN-016), com campo de resultado (Sucesso/Erro); núcleo
da automação em `apps/integracoes/eace/` (`ADR-004`). Fase 1 da
`FEAT-033` valida o núcleo da RPA via terminal (management command), sem
o model de log nem a tela; Fase 2 implementa o log, a tela e o avanço
automático de status descritos nesta regra.

**Features relacionadas:** FEAT-033, FEAT-009, FEAT-010.

**Status:** Ativa

### RN-057 — Validação dos dados da Nota Fiscal (PDF) contra o portal EACE antes do anexo

**Descrição:** Antes de subir o PDF+XML no portal EACE (RN-056), o
sistema extrai do próprio PDF os dados da Nota Fiscal — INEP, Produto e
Valor Total da Nota — e usa essa extração em duas conferências, cada uma
capaz de bloquear o disparo daquele log: (1) o INEP extraído do PDF
precisa ser igual ao INEP do log/RI, verificado antes de abrir o portal;
(2) o Valor extraído do PDF precisa ser igual ao valor exibido na linha
correspondente do portal EACE, verificado depois de localizar a linha, e
antes do upload em si. Os dados extraídos (INEP/Produto/Valor) ficam
gravados no próprio log da Nota Fiscal (RN-056) — visíveis ao usuário
ali, em sucesso ou em erro.

**Contexto:** Pedido do usuário em 2026-09-03, na sequência da definição
do gatilho (RN-056). A extração de dados do PDF já existia como etapa
isolada no protótipo `doc/auto_eace_nf_servidor` (validação de valor
antes do upload em lote, via planilha de controle); o usuário pediu para
trazer essa mesma conferência para dentro do fluxo por log, com os dados
extraídos visíveis no próprio log — não só em log técnico da aplicação.

**Critérios:**
- Extração via leitura do texto do PDF (INEP, Produto, Valor Total da
  Nota) acontece antes de abrir o navegador — falha rápido, sem gastar
  tempo/rede, se o PDF não tiver os dados mínimos ou não bater com o
  INEP esperado.
- PDF sem INEP reconhecível, ou sem Valor Total da Nota reconhecível,
  bloqueia o disparo daquele log ("Sem INEP no PDF"/"Sem valor no PDF").
- INEP do PDF diferente do INEP do log/RI bloqueia o disparo, antes de
  abrir o portal ("INEP do PDF não bate com o INEP do log").
- Valor do PDF diferente do valor exibido na linha do portal (mesma Nota
  Fiscal, já localizada) bloqueia o upload, mesmo com o portal já aberto
  ("Valor divergente entre PDF e portal").
- Os 3 dados extraídos (INEP, Produto, Valor) ficam sempre gravados no
  log, mesmo quando o resultado é "Erro" — o usuário confere o que foi
  lido do PDF sem precisar abrir o arquivo.

**Exceções:** Nenhuma divergência usa tolerância além da já necessária
para normalizar formatação (ex.: "22.644,43" e "22644.43" contam como o
mesmo valor); não há arredondamento nem tolerância de centavos além
dessa normalização de formato.

**Impacto técnico:** `apps/integracoes/eace/extrair_dados_pdf.py`
(extração via `pdfplumber`, nova dependência); `apps/integracoes/eace/
rpa.py` — `anexar_nota_fiscal` retorna `ResultadoRpaEace` (`sucesso`,
`motivo`, `dados_pdf`, `valor_portal`) em vez de booleano simples. Fase 1
(`FEAT-033`) valida a extração e as duas conferências via terminal,
inclusive contra o portal real; Fase 2 (entregue em 2026-09-03) grava
`dados_pdf`/`motivo` no model `LogRpaEace` e exibe no próprio log.

**Melhoria (2026-09-04):** usuário reportou não ter como saber, antes de
escolher o PDF no select de "Disparar RPA", qual Nota Fiscal correspondia
a qual produto/valor — só descobria depois de um "Erro (valor
divergente)". O select do PDF (`_logs_rpa_eace_detail.html`) passou a
mostrar Produto/Valor extraídos do próprio arquivo junto do nome
(`apps/ri/views.py`, `_rotular_documentos_pdf`) — mesma extração desta
RN-057, sem abrir portal nem gastar rede; falha de leitura (PDF
ilegível, lib ausente) só omite o complemento, nunca quebra a tela.

**Features relacionadas:** FEAT-033.

**Status:** Ativa

### RN-058 — Fila de execução do RPA EACE, com reprocessamento automático de erro não mapeado

**Descrição:** A execução do RPA de anexo no portal EACE (RN-056) é
serializada por uma fila — no máximo 1 execução por vez em todo o
sistema, mesmo com várias pessoas disparando "Disparar RPA" ao mesmo
tempo, em RIs diferentes. Cada disparo (novo ou "Tentar novamente") entra
no final da fila; um único processo consome a fila, um log de cada vez,
na ordem de chegada (FIFO). Quando um log falha com um erro **não
mapeado** (falha técnica/de ambiente — ver Critérios), ele não vira
"Erro" definitivo de imediato: volta para o **final** da fila para 1
reprocessamento automático. Só vira "Erro" definitivo se esse
reprocessamento também falhar. Erros **mapeados** (regra de negócio —
RN-056/RN-057) nunca entram nesse reprocessamento automático: viram
"Erro" definitivo já na 1ª tentativa.

**Contexto:** Pedido do usuário em 2026-09-03, logo após a entrega da
Fase 2 (log por Nota Fiscal com disparo manual): com a tela já
funcionando, várias pessoas podem clicar em "Disparar RPA" ao mesmo
tempo para RIs diferentes — mas o núcleo da automação abre um navegador
Chromium por execução e usa o mesmo login no mesmo portal externo;
execuções simultâneas colocam em risco tanto o consumo de recursos do
servidor quanto a consistência da navegação no portal (dois fluxos
mexendo na mesma tela ao mesmo tempo). O usuário também pediu que falhas
passageiras (ambiente, rede, timeout de UI) ganhem 1 nova chance
automática, sem exigir clique manual de novo — mas só para esse tipo de
falha, nunca para um erro que já é sabidamente uma questão de dado
(regra de negócio), porque repetir a mesma tentativa sem o usuário
corrigir nada (trocar o PDF/XML, aguardar o portal mudar) não muda o
resultado.

**Critérios:**
- No máximo 1 execução do núcleo do RPA (`anexar_nota_fiscal`) roda por
  vez, em todo o sistema — não por RI: o Chromium/portal é um recurso
  compartilhado único.
- Fila em ordem de chegada (FIFO); log reprocessado volta para o
  **final** da fila, não fura a frente de quem ainda não tentou nenhuma
  vez.
- **Motivos NÃO mapeados** (falha de ambiente/técnica, sem relação com o
  dado da Nota Fiscal ou regra de negócio) — reprocessam automaticamente
  1 vez: `login`, `selecao_perfil`, `abrir_medicoes`, `abrir_osps`,
  `expandir_resultado_osp`, `expandir_notas_fiscais`, `upload`,
  `enviar_notas`, `credenciais_ausentes`, `erro_playwright`,
  `ambiente_indisponivel` (Playwright/Chromium/pdfplumber ausente).
- **Motivos mapeados** (regra de negócio — RN-056/RN-057) — nunca
  reprocessam sozinhos, viram "Erro" definitivo na 1ª tentativa:
  `pdf_sem_inep`, `pdf_sem_valor`, `inep_divergente_do_pdf`,
  `valor_divergente`, `osp_nao_encontrada`, `inep_nao_encontrado`,
  `documento_ja_enviado`, `indice_invalido`.
- Um log só reprocessa automaticamente 1 vez. Se a 2ª tentativa falhar
  de novo — com motivo mapeado ou não mapeado — o resultado fica "Erro"
  definitivo; não há 3ª tentativa automática.
- Enquanto aguarda a fila (antes da 1ª tentativa) ou aguarda o
  reprocessamento (depois de um erro não mapeado), o log aparece como
  "Na fila" — nem "Pendente" (sem arquivo escolhido ainda) nem "Erro"
  (só depois de esgotar as tentativas); a tela mostra a posição do log
  na fila (1 = próximo a ser processado), calculada entre **todos** os
  logs "Na fila" do sistema, não só os do mesmo RI.
- O botão "Tentar novamente" (Fase 2, para erro definitivo) continua
  existindo e entra na fila do mesmo jeito que um disparo novo.
- Enquanto a execução está de fato rodando, o log fica "Processando" —
  estado gravado e comitado **antes** de chamar o núcleo do RPA, para
  aparecer na tela mesmo que a execução em si demore dezenas de segundos
  (ver também RN-061, barra de progresso por etapa).

**Exceções:** Nenhuma — a serialização vale para todo log de toda a
fila, sem prioridade por RI, usuário ou urgência.

**Correção (2026-09-03):** usuário reportou, testando ao vivo (INEP
90000002, 2 Notas Fiscais na fila), 3 problemas reais: (1) o status
pulava direto de "Na fila" para "Erro", sem nunca mostrar "Processando"
— corrigido gravando esse estado antes de chamar a RPA, não só depois;
(2) a posição na fila não aparecia — critério acima, implementado; (3) a
tela só atualizava com F5 — bug real de HTMX: o mesmo elemento era alvo
do próprio polling (`hx-trigger`) e também vinha marcado `hx-swap-oob`
na resposta desse polling, e as duas coisas competiam entre si; corrigido
suprimindo o `hx-swap-oob` quando a resposta é a do próprio polling.

**Impacto técnico:** implementado em 2026-09-03 —
`LogRpaEace.tentativas`/`enfileirado_em` (migração `0029`);
`MOTIVOS_REGRA_DE_NEGOCIO` em `apps/integracoes/eace/rpa.py`;
`apps.ri.services.processar_proximo_da_fila_rpa_eace` (consumidor único,
`select_for_update(skip_locked=True)` garante 1 execução por vez mesmo
com 2 processos por engano); comando de terminal
`processar_fila_rpa_eace` (1 passada por chamada). A tela atualiza
sozinha enquanto um log está "Na fila"/"Processando" via polling HTMX a
cada 5s (decisão do Dev, opção mais simples/reversível). Processo
consumidor rodando de verdade via serviço `rpa_eace_worker` no
`docker-compose.yml` (entregue pelo DevOps em 2026-09-03, mesmo padrão
do `email_scheduler`) — validado processando 1 item real da fila contra
o portal em produção.

**Features relacionadas:** FEAT-033.

**Status:** Ativa

### RN-059 — Registro de cada execução do RPA EACE no histórico do RI e na Auditoria

**Descrição:** A cada tentativa de execução do núcleo do RPA (RN-058) —
inclusive as que voltam para a fila para reprocessamento, não só as que
terminam em "Sucesso" ou "Erro" definitivo — o sistema grava 1 entrada
na linha do tempo do RI (RN-008) e 1 registro em Auditoria (RN-006), com
o resultado daquela tentativa, o número da tentativa e os dados da Nota
Fiscal (INEP/Produto/Valor extraídos do PDF e valor exibido no portal),
incluindo o motivo do erro quando houver. Diferente do próprio
`LogRpaEace` (RN-056), que só guarda o estado mais recente — uma nova
tentativa sobrescreve os dados da anterior —, este registro é permanente:
continua visível mesmo depois de reprocessamentos.

**Contexto:** Pedido do usuário em 2026-09-03: "toda vez que rodar o
processamento, as informações da NF e status tem que ficar salvo nos
logs do sistema para saber que em algum momento foi rodado". Primeira
implementação gravou só em Auditoria (sem tela própria); o usuário
corrigiu que o lugar certo é a mesma linha do tempo onde já aparecem as
trocas de status e outras descrições do RI (RN-008) — Auditoria continua
recebendo o mesmo registro, como trilha técnica adicional, mesmo padrão
de dupla gravação já usado por RN-008/RN-006.

**Critérios:**
- Toda chamada de `processar_proximo_da_fila_rpa_eace` (RN-058) que
  processa 1 log gera exatamente 1 entrada na linha do tempo do RI (tipo
  "Mudança de campo", autor "Sistema") e 1 registro em Auditoria (ação
  "Execução RPA EACE") — inclusive no caminho de estado inconsistente
  (log sem OSP/documento).
- Reprocessamento soma uma nova entrada/registro a cada tentativa — nunca
  substitui nem apaga o anterior.
- Ambos trazem: resultado da tentativa, número da tentativa, INEP/
  Produto/Valor extraídos do PDF, valor exibido no portal e o motivo do
  erro, quando houver.

**Exceções:** nenhuma.

**Impacto técnico:** `apps/auditoria/models.py` (ação
`execucao_rpa_eace`, migração `0003`); `apps/ri/services.py`
(`_registrar_execucao_rpa_eace`, chamada de dentro de
`processar_proximo_da_fila_rpa_eace`).

**Features relacionadas:** FEAT-033.

**Status:** Ativa

### RN-060 — Log de Nota Fiscal "Sucesso" é imutável

**Descrição:** Uma vez que um log de Nota Fiscal (RN-056) tem resultado
"Sucesso", o par PDF/XML e o disparo daquele log não podem mais ser
alterados nem reenviados — nem pela tela nem por uma requisição direta ao
backend.

**Contexto:** Pedido do usuário em 2026-09-03: "caso o processamento seja
dado como sucesso, os inputs não podem mais ser editados" — depois de
confirmado no portal, os dados não podem ser trocados por engano.

**Critérios:**
- Tela: com resultado "Sucesso", o log mostra só um resumo somente
  leitura (INEP/Produto/Valor extraídos) — sem formulário de seleção de
  PDF/XML nem botão de disparo.
- Backend: a view de disparo recusa a requisição (mensagem de erro, sem
  alterar o log) quando o resultado já é "Sucesso", mesmo que a tela
  tenha sido contornada — defesa em profundidade, não depende só do que
  a tela esconde.

**Exceções:** nenhuma — não existe hoje um fluxo para "desfazer" um log
com "Sucesso".

**Impacto técnico:** `apps/ri/views.py`
(`ri_log_rpa_eace_disparar_view`); `apps/ri/templates/ri/
_logs_rpa_eace_detail.html`.

**Features relacionadas:** FEAT-033.

**Status:** Ativa

### RN-061 — Barra de progresso por etapa da execução do RPA EACE

**Descrição:** Enquanto o núcleo do RPA está em execução ("Processando",
RN-058), a tela mostra uma barra de progresso percentual e o nome da
etapa em andamento (ex.: "62% — Anexando o PDF e o XML"), atualizada em
tempo real (mesmo polling HTMX de 5s da RN-058) a cada etapa concluída —
login, preenchimento de usuário/senha, navegação, upload etc.

**Contexto:** Pedido do usuário em 2026-09-04: acompanhar cada etapa da
RPA como uma porcentagem numa barra de progresso, "até pra que o usuário
possa ver se não está travado" — uma execução pode levar dezenas de
segundos.

**Critérios:**
- O núcleo do RPA (`anexar_nota_fiscal`) é dividido em 16 etapas fixas,
  na ordem em que acontecem de verdade (ex.: "Preenchendo usuário",
  "Preenchendo senha", "Selecionando o perfil Fornecedor"...); a cada
  etapa concluída, percentual = posição da etapa / total de etapas.
- O progresso é zerado no início de cada nova tentativa, inclusive
  reprocessamento (RN-058) — não herda o valor da tentativa anterior.
- Falha no meio do caminho deixa a barra parada na última etapa
  concluída — não retrocede nem avança sozinha.

**Exceções:** nenhuma.

**Impacto técnico:** `apps/integracoes/eace/rpa.py` (`ETAPAS_RPA_EACE`,
`ProgressoRpaEace`); `apps/integracoes/eace/login.py` (`fazer_login`
reporta 3 sub-etapas: usuário, senha, aguardar resposta do portal);
`LogRpaEace.etapa_atual`/`progresso_pct` (migração `0031`).

**Features relacionadas:** FEAT-033.

**Status:** Ativa

### RN-063 — Consulta somente-leitura das pendências do portal EACE antes de escolher a Nota Fiscal

**Descrição:** Na tela de "Disparar RPA" (RN-056), um botão "Consultar
pendências" dispara 1 leitura somente-consulta do grid do portal EACE
para a OSP do RI — mesma navegação até "Lendo as linhas do grid" de
`anexar_nota_fiscal` (RN-057), sem nunca subir arquivo. O resultado
(Status/Descrição/Valor de cada linha) fica gravado no próprio RI e
exibido ao lado do Produto/Valor de cada NF (RN-062, melhoria da
RN-057), para o usuário casar a NF certa com a linha certa ANTES de
escolher, em vez de descobrir só depois de um "Erro (valor divergente)".

**Contexto:** Usuário testou ao vivo o RPA EACE (INEP 53005090, RI 202,
3 Notas Fiscais) e reportou: só descobriu qual NF (Kit Wi-Fi, Nobreak
etc.) batia com qual linha do portal depois de tentar uma errada e
receber "Erro (valor divergente)". Pediu para o sistema informar isso
antes, ou casar sozinho — ver a alternativa mais completa (casamento
automático, sem select manual) registrada como melhoria futura, não
implementada agora por mexer na arquitetura da fila (RN-058).

**Critérios:**
- Consulta sob demanda (botão), nunca automática — pode levar dezenas de
  segundos (mesma ordem de grandeza de "Disparar RPA"), roda dentro da
  própria requisição, sem passar pela fila do RPA (RN-058): não sobe
  nada, então não precisa da mesma exclusividade dos uploads reais.
- Recusa rodar (mensagem de erro, sem tentar) se já existir um log
  "Processando" no sistema — evita 2 navegadores abertos ao mesmo tempo
  contra o mesmo login do portal.
- Resultado (linhas do grid, motivo de erro, data/hora) fica gravado no
  RI (`Ri.pendencias_portal_eace`/`_consultado_em`/`_motivo_erro`) — não
  é recalculado a cada carregamento de tela, só quando o usuário pede.
- Falha (OSP não encontrada, ambiente sem Playwright, credenciais
  ausentes etc.) só mostra mensagem — nunca quebra a tela nem impede o
  fluxo manual de "Disparar RPA" continuar funcionando do jeito de
  sempre.

**Exceções:** Nenhuma — mesmas condições de erro de `anexar_nota_fiscal`
(RN-057), só que sem chegar a subir nada.

**Impacto técnico:** `apps/integracoes/eace/rpa.py`
(`consultar_pendencias_eace`, `ResultadoConsultaPendencias` — reaproveita
`.dashboard`/`.login` de `anexar_nota_fiscal`); `apps/ri/services.py`
(`consultar_pendencias_portal_eace`); `apps/ri/views.py`
(`ri_consultar_pendencias_eace_view`); `Ri.pendencias_portal_eace`/
`_consultado_em`/`_motivo_erro` (migração `0033`);
`_logs_rpa_eace_detail.html`.

**Features relacionadas:** FEAT-033.

**Status:** Ativa

### RN-064 — Resolução da OSP pelo item da Nota Fiscal, não "qualquer" OSP do RI

**Descrição:** Ao disparar a RPA (RN-056) ou consultar pendências
(RN-063), a OSP usada é a do **item do Relatório EACE que bate com o
Valor extraído do PDF** desta Nota Fiscal específica — não mais "a 1ª
OSP não vazia" encontrada entre todos os itens do RI. Quando o RI tem
itens em OSPs diferentes, a consulta de pendências (RN-063) cobre TODAS
as OSPs distintas do RI, não só uma.

**Contexto:** Usuário testou ao vivo (INEP 53005090, RI 202, 3 Notas
Fiscais) e reportou: corrigiu o "Num OSP" do item errado, mas a RPA
continuava usando a OSP antiga. Causa: o RI tinha itens em 2 OSPs
diferentes (Nobreak numa, Kit Wi-Fi/Access Point Adicional em outra) — o
código sempre pegava a 1ª OSP não vazia do RI inteiro, ignorando qual
Nota Fiscal estava sendo processada; o item mais antigo (de outra OSP)
sempre "ganhava", mesmo com a OSP certa já cadastrada no item certo.

**Critérios:**
- RI com só 1 OSP entre os itens: comportamento igual a antes (usa essa
  OSP, sem custo extra de comparação).
- RI com mais de 1 OSP: casa o Valor extraído do PDF (RN-057) contra
  `valor_unitario × quantidade` de cada item — usa a OSP do item cujo
  valor TOTAL bate (a NF traz o valor total do item, não o unitário;
  usuário reportou um item de 3 Access Points com Valor Unitário R$
  699,09 — comparar só o unitário nunca bate, o valor certo pra casar é
  R$ 2.097,27 = 699,09 × 3).
- PDF ilegível ou valor que não bate com nenhum item: cai no
  comportamento antigo (1ª OSP não vazia) como último recurso — nunca
  bloqueia o disparo por causa de um valor que não foi possível ler.
- Consulta de pendências (RN-063): 1 leitura por OSP distinta do RI,
  cada linha devolvida marcada com a OSP de origem; só registra erro se
  TODAS as OSPs falharem — falha parcial mostra o que deu certo.

**Exceções:** Nenhuma.

**Impacto técnico:** `apps/ri/services.py`
(`_resolver_osp_da_nota_fiscal`, usada por
`processar_proximo_da_fila_rpa_eace`; `consultar_pendencias_portal_eace`
ampliada pra iterar todas as OSPs distintas do RI).

**Features relacionadas:** FEAT-033.

**Status:** Ativa

### RN-050 — Assunto do e-mail ao financeiro inclui o nome da escola

**Descrição:** O assunto sugerido do e-mail de faturamento ao financeiro
(FEAT-008) passa a incluir o nome da escola, além do INEP — código de
rastreio (RN-009) continua igual, no início do assunto.

**Contexto:** Pedido do usuário em 2026-09-01 — o financeiro recebe
muitos e-mails com INEPs parecidos; o nome da escola ajuda a identificar
do que se trata sem precisar abrir o e-mail.

**Critérios:** assunto sugerido segue o formato `#RI-AAAAMMDD-INEP -
Faturamento EACE — INEP <inep> — <nome da escola>`; mesmo texto tanto no
Grid de INEPs quanto na tela de detalhe do RI (RN-051).

**Exceções:** nenhuma.

**Impacto técnico:** `_assunto_sugerido_email` (apps/ri/views.py),
reaproveitada pelo Grid (FEAT-007) e pela tela de detalhe (RN-051).

**Features relacionadas:** FEAT-008.

**Status:** Ativa

## Segunda Validação Financeira

### RN-005 — Segunda validação da Nota Fiscal recebida
**Descrição:** Antes de liberar a marcação de anexo no portal EACE, o
sistema confere se a Nota Fiscal e o XML recebidos do financeiro
correspondem ao que foi solicitado no e-mail enviado para aquele INEP.

**Contexto:** `requisitos.md`, ITEM 7 e "PROCESSO do Projeto".

**Critérios:** validação ocorre durante o status "Resposta Financeiro"
(RN-001, RN-016 — mesmo status antes chamado "Aguardando Anexo portal
EACE"); encontrar divergência classifica como o tipo "NF × financeiro" no
catálogo de divergências (RN-003).

**Exceções:** e-mail de resposta fora do padrão (quantidade de PDF
diferente da de XML, ou sem INEP identificável) não bloqueia o fluxo, só
gera alerta no log de e-mail — mas, a partir da RN-016, também muda o
status para "Resposta Financeiro".

**Impacto técnico:** tabelas `email_financeiro_log` e `documento`
(`modelo-dados.md`).

**Features relacionadas:** FEAT-009, FEAT-020.

**Status:** Ativa

**Correção (2026-09-02):** usuário reportou (INEP 35095874) que o
financeiro respondeu com 2 Notas Fiscais no mesmo e-mail (2 PDF + 2 XML,
pareados pelo número da NF no nome do arquivo) e o sistema descartou os 4
arquivos — "no padrão" exigia **exatamente** 1 PDF + 1 XML; qualquer outra
quantidade (mesmo 2+2, corretamente detectado) não salvava nenhum
`Documento`, só avançava o status (RN-016) sem guardar os anexos de
verdade. Corrigido: "no padrão" passa a ser quantidade de PDF igual à de
XML (1+1, 2+2, N+N), todos salvos como `Documento`; fora do padrão de
verdade volta a ser só quantidade diferente (algo de fato incompleto, ex.:
2 PDF e 1 XML). `Documento` também deixou de aposentar (`ativo=False`) o
anterior do mesmo tipo ao salvar um novo — antes pensado para "resposta
corrigida" substituindo a antiga, mas isso apagaria a 1ª NF ao salvar a
2ª dentro da mesma resposta; decisão confirmada com o usuário (CLAUDE.md
§9): guardar todos os pares PDF+XML, sem substituir os anteriores.
Implantado em produção em 2026-09-02 (commit `f1c834a`, junto com a
correção da RN-016 acima); os 3 e-mails reais já recebidos antes da
correção (INEPs 35095874, 52032043, 17002109) tiveram os documentos
buscados de novo na caixa e salvos retroativamente, sem alterar o status
(já estava correto).

## Auditoria

### RN-006 — Escopo da auditoria
**Descrição:** O sistema audita alteração de campo, transição de status,
execução de ação manual que hoje substitui um RPA futuro, envio/recebimento
de e-mail, login no sistema e erros.

**Contexto:** `requisitos.md`, ITEM 10.

**Critérios:** reaproveita `apps/auditoria` do `modulo-posVenda` como
código-base; retenção indefinida (sem expiração); consulta aos registros só
por acesso direto ao banco nesta versão, sem tela própria.

**Exceções:** decisão de implementação exercida pelo Dev em 2026-08-31
(FEAT-011) — estendeu o `apps/auditoria` já existente (login, transição de
status, alteração de campo/item, envio/recebimento de e-mail e erro não
tratado), em vez de criar um log específico à parte.

**Impacto técnico:** tabela `auditoria` (`modelo-dados.md`); ação
`execucao_rpa_eace` (migração `0003`, 2026-09-03) — o RPA de anexo no
portal EACE (`FEAT-033`) é o "RPA futuro" antecipado na Descrição acima;
cada execução gera 1 registro aqui (RN-059).

**Features relacionadas:** FEAT-011, FEAT-033.

**Status:** Ativa

## Histórico de Comunicação

### RN-008 — Histórico de comunicação por RI
**Descrição:** Cada RI tem uma linha do tempo própria, visível na tela do
RI (FEAT-004), com três tipos de registro: mensagem escrita pelo usuário
(comentário livre, com anexo opcional), anexo isolado, e log automático do
sistema — mudança de status (FEAT-006), atribuição/troca de responsável
(RN-012), cadastro e alteração dos itens do Lado IXC e do Relatório EACE
(2º e 3º lado, FEAT-004), e envio/recebimento de e-mail. Mais recente
primeiro.

**Contexto:** pedido do usuário em 2026-08-22, para reaproveitar o padrão
de `RegistroHistorico` do `modulo-posVenda` (lá documentado como RN-029/
RN-041) — mensagem, anexo e log estruturado (rótulo + valor anterior/novo)
num único feed por entidade.

**Critérios:** log automático de mudança de status/campo grava rótulo do
campo e valor anterior/novo, em vez de só uma frase livre; envio de e-mail
(FEAT-008) e recebimento (FEAT-009) também geram entrada nesta linha do
tempo, além do que já é registrado em `email_financeiro_log`; anexo fica
disponível para download. **Esclarecimento (2026-08-26):** "campo
relevante" cobre também o **cadastro** de um dado, não só a alteração de
um valor já existente — todo lançamento novo no Lado IXC (KIT Instalado,
Produto avulso, Data de Ativação, Município/Estado) e no Relatório EACE
gera entrada própria na linha do tempo com o valor cadastrado; edição e
exclusão de item do Lado IXC também geram entrada, com valor anterior e
novo (exclusão grava o valor removido). Kit Declarado (1º lado) fica de
fora: não é cadastrado nesta tela, vem pronto da EACE (RN-010).

**Exceções:** distinto do Auditoria/RN-006 — aquele continua sem tela
própria, só trilha técnica; este histórico é a tela do usuário. Pode haver
sobreposição de dado entre os dois (ex.: uma mudança de status gera entrada
em ambos) — aceitável, propósitos diferentes. Mesma sobreposição vale para
cada execução do RPA EACE (RN-059): 1 entrada aqui, 1 registro em
Auditoria. RE não entra aqui: quando a v3 for planejada, RE ganha sua
própria linha do tempo (mesmo critério já registrado em `architecture.md`
para não misturar RE dentro da estrutura da RI).

**Impacto técnico:** nova tabela `ri_historico` (`modelo-dados.md`), FK
direta a `ri` (sem `GenericForeignKey` — só RI existe hoje).

**Features relacionadas:** FEAT-014, FEAT-033.

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

## Kit Declarado e Catálogo de Valores

### RN-010 — Kit Declarado: origem automática e catálogo de valores padrão
**Descrição:** O Kit Declarado (1º lado do RI, RN-002) não é digitado
livremente pelo usuário. A descrição do item vem do dado que a EACE já
informou antes do início do projeto — o mesmo texto da coluna H do
`CONSOLIDADO EACE.xlsx` (cabeçalho "KIT WIFI ESTIMADO"), já importado em
`Escola.kit_inicial` (FEAT-002). Quantidade e Valor Unitário nunca são
digitados: vêm de um catálogo próprio, com os valores padrão de cada tipo
de kit, cruzado pela descrição do kit. Isso vale tanto para o item inicial
quanto para qualquer item lançado depois para corrigi-lo (RN-002: "não
editável após lançado, para corrigir lance um novo item").

**Contexto:** Usuário revisou a tela do Kit Declarado (card "1º Lado") e
apontou que o formulário atual ("Lançar item do Kit Declarado") deixa
digitar Quantidade e Valor Unitário livremente — isso não deveria
acontecer, pois esses valores são padronizados por tipo de kit, não
informados manualmente a cada lançamento.

**Critérios:**
- Descrição do item = texto de `Escola.kit_inicial` (mesma fonte da coluna
  H do `CONSOLIDADO EACE.xlsx`, já mapeada na FEAT-002) — não é campo de
  texto livre para o usuário.
- Quantidade e Valor Unitário = busca no catálogo de valores padrão pelo
  tipo/descrição do kit — nunca digitados à mão, nem no lançamento inicial
  nem numa correção (novo item lançado sobre o Kit Declarado).
- O valor de cada kit é fixo por Lote: a mesma descrição de kit tem preço
  diferente em lotes diferentes (confirmado com `LOTE 9` e `LOTE 11` na
  planilha). O cruzamento com o catálogo passa a usar `Escola.kit_inicial`
  **junto com** `Escola.lote` — não só a descrição.
- **Ampliação (2026-08-24):** em parte das escolas, `Escola.kit_inicial`
  não traz o texto completo do kit, só o número informado pela EACE (ex.:
  `4`) — o usuário chamou informalmente essas duas situações de "lote 1"/
  "lote 2", mas o termo já usado no projeto é **1º lado**/**2º lado**
  (RN-002), não o campo `Escola.lote`. Esse número sempre corresponde à
  quantidade de Access Points do kit (regra fixa, confirmada pelo
  usuário) — o mesmo conceito já usado no campo "Número de Access Points"
  da opção "Outro" do Lado IXC (RN-011). Quando `Escola.kit_inicial` for
  só um número, o cruzamento com o catálogo passa a usar a nova coluna
  `KitPadrao.numero_access_points` (inteiro, derivado automaticamente da
  Descrição — mesmo padrão de `descricao_curta`/RN-011) em vez do texto
  completo.
- O catálogo guarda o valor de Equipamento e o valor de Serviço separados
  (não um valor único), conforme as colunas da planilha de origem.
- A coluna "Unidade" da planilha define o tipo do valor: quando é `Escola`
  ou `Escola/Mês`, o valor da linha é o preço fechado do KIT completo
  daquela escola (quantidade = 1); quando não é `Escola` (`Unidade`, `km`,
  `enlace`, `metro`, `par`), o valor é preço unitário de item avulso/
  complementar — essas linhas entram no catálogo como referência de preço,
  mas não são resolvidas automaticamente pelo Kit Declarado (fora do
  escopo desta regra, que cobre só o kit fechado da escola).
- Regra vale só para o Kit Declarado (1º lado). Não altera IXC (2º lado)
  nem Relatório EACE (3º lado), que continuam com lançamento manual.

**Exceções:** kit sem correspondência no catálogo — comportamento (bloquear
lançamento vs. permitir sem valor padrão) ainda não definido pelo usuário;
**pendência de decisão**.

**Impacto técnico:** novo model de catálogo (tipo/descrição do kit →
quantidade padrão + valor unitário padrão); ajuste em `RiItemEace`
(`apps/ri/models.py`) e no formulário "Lançar item do Kit Declarado"
(`apps/ri/forms.py`, `ri_detail.html`) para que Quantidade e Valor Unitário
deixem de ser campos digitáveis e passem a ser resolvidos pelo cruzamento
com o catálogo; feature já entregue pelo Dev e hoje `🔍 Aguardando QA`
(FEAT-004) — mudança exige correção antes da validação do QA nessa parte.
**Fonte de carga do catálogo resolvida (2026-08-24):** aba `LPU` de
`CONSOLIDADO EACE.xlsx` ("TABELA 1 - LISTA DE PREÇOS UNITÁRIOS"), mesmo
padrão de importação em lote já usado por `Escola` (FEAT-002). O model
`KitPadrao` existente precisa evoluir para guardar `lote`, `unidade` e os
valores de Equipamento/Serviço separados (hoje só tem um valor único, sem
lote) — ver FEAT-015 (entregue pelo Dev em 2026-08-24). **Decidido
(2026-08-24):** `RiItemEace` continua com um único Valor Unitário — não
discrimina Equipamento/Serviço. Usuário optou pela opção de menor risco
(sem migração de dado existente, sem impacto no confronto RN-002/RN-003
nem no financeiro); pode ser revisto no futuro se surgir necessidade
concreta.
**Cruzamento por número de Access Points (2026-08-24):** requer novo
campo `KitPadrao.numero_access_points`, derivado automaticamente da
Descrição — ver FEAT-016 (`⬜ Pendente`; não altera a FEAT-015, já
entregue e em QA).

**Features relacionadas:** FEAT-002, FEAT-004, FEAT-015, FEAT-016.

**Status:** Ativa (pendências de decisão registradas acima)

### RN-017 — Nobreak declarado (1º lado): item padrão para toda escola
**Descrição:** Toda Escola (INEP) nasce, ao lado do Kit Declarado (RN-002/
RN-010), também com um Nobreak declarado — um item padrão único, igual
para todas as escolas, sem variação por escola ou lote e sem valor
financeiro. É só informativo, exibido junto do Kit no card "Kit declarado
(1º lado)".

**Contexto:** Usuário identificou que o cadastro de Escola só guarda o Kit
declarado (`Escola.kit_inicial`), mas todo INEP também já é definido com
um Nobreak — informação hoje ausente do sistema, que precisa ser
preenchida retroativamente nas 2.622 escolas já migradas (FEAT-002) e
entrar por padrão em toda escola nova. Confirmado com o usuário: o Nobreak
é o mesmo para todas as escolas (sem variação por lote, ao contrário do
Kit) e não entra no cálculo financeiro.

**Critérios:**
- Nobreak é um único valor padrão, igual para todas as escolas — não
  varia por escola, lote ou tipo de Kit.
- Não tem quantidade nem valor unitário; não entra no catálogo
  `KitPadrao` (RN-010) nem no cálculo financeiro do RI — é só informativo.
- Dado persistido em cada Escola (não um texto fixo só na tela): backfill
  aplicado às 2.622 escolas já migradas (FEAT-002) e valor padrão aplicado
  a toda escola nova.
- Exibido junto ao Kit Declarado, no mesmo card "Kit declarado (1º lado)"
  onde o Kit já aparece hoje: tela do RI (`ri_detail.html`) e drill-down do
  grid (`grid_inep.html`, FEAT-007).
- Não altera IXC (2º lado) nem Relatório EACE (3º lado) — mesmo escopo
  restrito já usado em RN-010/RN-011.
- **Correção (2026-08-27):** o trecho acima ("sem valor financeiro... não
  entra no catálogo `KitPadrao` nem no cálculo financeiro") está
  **superado**. Usuário confirmou que o Nobreak inicial tem sim valor
  cadastrado no catálogo `KitPadrao`, pelo mesmo mecanismo do Kit
  Declarado (RN-010): item "Nobreak (serviço, material, equipamento)" na
  aba LPU do `CONSOLIDADO EACE.xlsx`, com valor de Equipamento/Serviço por
  Lote (confirmado nas colunas do LOTE 9 e do LOTE 11). A partir de agora,
  o valor do Nobreak inicial é resolvido pelo catálogo (descrição fixa do
  Nobreak + `Escola.lote`, mesmo cruzamento da RN-010) e usado no cálculo
  do dashboard/relatórios financeiros (RN-025). Continua **sem mudança
  visual** nas telas onde já aparece hoje — `ri_detail.html` e
  `grid_inep.html` (card "Kit declarado (1º lado)") seguem mostrando só a
  descrição, sem exibir valor ali.

**Exceções:** nenhuma — regra fixa para 100% das escolas.

**Impacto técnico:** novo campo em `Escola` (`apps/escolas/models.py`),
análogo a `kit_inicial`; migration de dados para preencher o valor padrão
nas 2.622 escolas já existentes; `ri_detail.html` e `grid_inep.html`
passam a exibir o valor junto ao card do 1º lado. **Correção
(2026-08-27):** conferir se o catálogo `KitPadrao` já tem a entrada do
Nobreak para os lotes existentes (reimportar `importar_catalogo_lpu`,
FEAT-015, se faltar) antes de implementar a RN-025.

**Features relacionadas:** FEAT-002, FEAT-004, FEAT-007, FEAT-021, FEAT-026.

**Status:** Ativa — correção 2026-08-27 (Nobreak passa a ter valor
financeiro, usado só no dashboard/relatórios; ver RN-025)

### RN-011 — Lado IXC: formulário único (KIT Instalado + Produtos + Data Ativação)
**Descrição:** O lançamento do Lado IXC (2º lado do RI) usa um único
formulário com um único botão "Salvar" (ação `salvar_ixc`), que grava, na
mesma submissão, até três coisas independentes e opcionais: (1) um "KIT
Instalado" (no máximo um por submissão — e no máximo um por RI/INEP no
total, RN-015, criada em 2026-08-26: com um já lançado, o campo some da
tela), (2) 0 ou mais "Produtos" individuais abertos pelo botão "+", e (3)
a "Data Ativação" do RI. A
Descrição livre que existia antes deixou de existir para lançamento
novo — a descrição do KIT/Produto vem sempre de uma lista (catálogo ou
"Outro"). Texto consolidado em 2026-08-24 depois de 8 entregas do Dev no
mesmo dia; substitui a versão anterior desta regra (KIT obrigatório com
Valor Unitário digitado, dois botões separados), que não refletia mais o
que está implementado.

**Contexto:** Usuário pediu, para o Lado IXC, um input "KIT Instalado"
com valor unitário e um "+" para lançar itens individuais instalados além
do kit; ao longo do mesmo dia, testando a tela real, pediu para tirar o
campo de valor, unificar num só botão de salvar, acrescentar um campo
"Data Ativação", uma opção "Outro" para kit fora do catálogo, e um jeito
de remover uma linha de produto aberta por engano.

**Critérios:**
- Formulário único, botão único "Salvar". Submissão sem nada preenchido
  (nenhum KIT, nenhum produto, Data Ativação sem mudança) mostra erro
  ("Selecione um KIT, um produto ou informe a Data de Ativação.") e não
  grava nada. **Correção (2026-09-02, bug reportado pelo usuário — INEP
  35275505):** essa mesma mensagem aparecia também quando o KIT e/ou a
  Data de Ativação **já estavam lançados/preenchidos** e o usuário só
  reenviava a tela sem mudar nada (ex.: clique duplo em "Salvar") — ficava
  enganosa, dando a entender que nada tinha sido preenchido. Nesse caso
  (KIT já lançado ou Data de Ativação já preenchida, mas nada novo na
  submissão), a mensagem passa a ser "Nenhuma alteração para salvar."; a
  mensagem original continua valendo só quando de fato nada foi
  preenchido ainda.
- "KIT Instalado": opcional a cada submissão (não trava o "Salvar" quando
  em branco). Quando selecionado, Quantidade é sempre 1 e a descrição vem
  de uma lista — catálogo `KitPadrao` (LPU) filtrado à Unidade
  "Escola"/"Escola-Mês" (mesmo critério de
  `KitPadrao.kit_fechado_por_escola`, RN-010) e ao Lote da escola quando
  ela tiver um valor definido. A lista sempre inclui "Outro — kit não
  cadastrado": ao escolher, abre o campo "Número de Access Points" e a
  descrição gravada segue o padrão "Kit Cobertura Wi-Fi - N Access
  Points". Sem nenhuma entrada de KIT no catálogo para o Lote da escola,
  o painel avisa, mas "Outro" continua disponível.
- "Produtos": 0 ou mais linhas por submissão, abertas pelo botão "+" — a
  lista nasce vazia, nenhuma linha visível até o primeiro clique. Cada
  linha tem "Produto" (mesmo catálogo `KitPadrao`, excluída a Unidade
  "Escola"/"Escola-Mês", também filtrado por Lote) e "Quantidade" digitada
  manualmente. Cada linha aberta pode ser removida (botão "x") antes de
  enviar. Lista com altura travada e rolagem própria — não estica o
  painel indefinidamente conforme produtos são adicionados.
- "Data Ativação": campo de data novo, valor único por RI — não por item
  nem por produto (`Ri.data_ativacao`). Fica no mesmo formulário do bloco
  Produtos, mas é salvo independente de haver ou não produto lançado
  junto na mesma submissão.
- Valor Unitário deixou de ser digitado pelo usuário, tanto no KIT quanto
  em cada Produto — decisão do usuário (2026-08-24): "não é informação
  necessária agora". Todo item lançado por este fluxo nasce com Valor
  Unitário 0,00; correção posterior é feita editando o item já lançado
  (RN-004), que continua com o campo de valor, sem mudança.
- Descrição do KIT/Produto nunca é texto livre — sempre escolhida numa
  lista (catálogo `KitPadrao`, ou "Outro" para o KIT). Edição de item já
  lançado (RN-004) continua com Descrição livre, sem mudança — a regra
  acima vale só para o lançamento novo.
- Regra vale só para o Lado IXC (2º lado). Não altera Kit Declarado (1º
  lado, RN-010) nem Relatório EACE (3º lado), que continuam como estão.
  **Extensão (RN-018, 2026-08-26):** o mesmo mecanismo (KIT Instalado +
  Produtos) passa a valer também para o Relatório EACE (3º lado), sem
  Data Ativação/Município/Estado — ver RN-018.

**Exceções:** catálogo `KitPadrao` sem entrada correspondente ao Lote da
escola — "Outro" cobre o caso do KIT; "Produtos" fica só com a lista
vazia até existir entrada no catálogo para aquele Lote (sem aviso
dedicado, diferente do KIT).

**Impacto técnico:** `apps/ri/forms.py` (`RiItemIxcKitForm`,
`RiItemIxcProdutoForm`/`RiItemIxcProdutoFormSet`, `RiDataAtivacaoForm`,
`_CatalogoIxcChoiceField`); `apps/ri/views.py` (`ri_detail_view`, ação
`salvar_ixc`); `apps/ri/templates/ri/ri_detail.html` (bloco único do
Lado IXC, JS do "+"/"x" e do campo condicional "Outro");
`apps/ri/models.py` — `Ri.data_ativacao` (migration `0008`) e
`KitPadrao.descricao_curta` (migration `0007`, preenchida
automaticamente ao salvar a partir da Descrição completa, usada como
rótulo nos selects em vez dela).

**Features relacionadas:** FEAT-004.

**Status:** Ativa

### RN-015 — Um KIT por INEP
**Descrição:** Cada RI (INEP) só pode ter 1 "KIT Instalado" lançado no
Lado IXC (RN-011) — do catálogo ou pela opção "Outro". Com um já lançado,
o formulário deixa de oferecer o campo "Kit" (select + "Outro") e mostra
só um aviso; para trocar, o usuário edita ou exclui o item já lançado
(RN-004, mesmos ícones já usados na lista de itens). Não afeta
"Produtos" — continuam sem limite de quantidade de linhas.

**Contexto:** Usuário pediu, em 2026-08-26: "cada INEP só pode ter um
KIT... não pode adicionar outro caso já tenha escolhido um".

**Critérios:**
- RI com pelo menos 1 `RiItemIxc.eh_kit=True` não pode lançar outro KIT —
  bloqueado na tela (campo escondido, substituído pelo aviso) e no
  servidor (submissão direta com um KIT selecionado é rejeitada com
  mensagem objetiva, mesmo que o campo não devesse existir na tela).
- Bloqueio vale tanto para KIT escolhido do catálogo quanto para "Outro".
- Lançar Produto, e editar/excluir o KIT já lançado, continuam liberados
  normalmente.

**Exceções:** nenhuma.

**Impacto técnico:** `apps/ri/views.py` (`ri_detail_view` — variável
`kit_ja_lancado`, checagem antes de criar o item na ação `salvar_ixc`);
`apps/ri/templates/ri/ri_detail.html` (campo "Kit" condicional).

**Features relacionadas:** FEAT-004, FEAT-017, FEAT-018 (mesma tela/
formulário do Lado IXC).

**Status:** Ativa — **extensão (RN-018, 2026-08-26):** mesmo limite passa a
valer também para o Lado Relatório EACE (3º lado), com uma diferença: lá o
item marcado como KIT pode ser editado/excluído (exceção à imutabilidade da
RN-003) para permitir correção — ver RN-018.

### RN-014 — Município/Estado do Lado IXC e divergência com o cadastro da Escola
**Descrição:** O Lado IXC (RN-011) ganha dois campos manuais — Município e
Estado (UF, 2 letras) — usados na planilha de faturamento (RN-013). Não
reaproveitam direto `Escola.municipio`/`Escola.estado`: são digitados à
parte e comparados contra o cadastro da Escola; quando os dois lados têm
valor e divergem, o campo fica com alerta visual (borda vermelha), sem
bloquear o RI.

**Contexto:** Usuário pediu, em 2026-08-26, um jeito de conferir se o
Município/Estado usados no faturamento batem com o cadastro oficial da
Escola, sem travar o processo quando não baterem — mesmo princípio já
usado no alerta de KIT divergente (RN-002, informal, não bloqueia).

**Critérios:**
- Campos opcionais a cada submissão do formulário único do Lado IXC
  (RN-011) — não travam o "Salvar" quando vazios. Chegou a existir uma
  versão que travava (com 3 correções no meio do caminho: idioma da
  mensagem nativa do navegador, depois mensagem duplicada), revertida no
  mesmo dia (2026-08-26) quando o usuário esclareceu que a exigência real
  é só na hora de enviar o e-mail/baixar a planilha, não a cada "Salvar"
  — ver RN-013, que passa a ser quem efetivamente exige Município/Estado
  preenchidos (junto com KIT e Data de Ativação) para gerar a planilha.
- Alerta visual só aparece quando os dois lados (Lado IXC ×
  `Escola.municipio`/`Escola.estado`) têm valor preenchido e são
  diferentes; campo vazio de qualquer um dos lados não gera alerta.
- Alerta é só visual — não bloqueia o avanço de status do RI. Não bloqueia
  a geração/envio da planilha de faturamento por divergência (só por
  campo vazio, RN-013).

**Exceções:** nenhuma além do critério acima.

**Impacto técnico:** novos campos no Lado IXC (mesmo formulário/model de
`Ri.data_ativacao`, RN-011); comparação contra `Escola.municipio`/
`Escola.estado` (`apps/escolas/models.py`).

**Features relacionadas:** FEAT-017, FEAT-018.

**Status:** Ativa

**Revisão (2026-09-02):** Município/Estado do Lado IXC nascem preenchidos
com `Escola.municipio`/`Escola.estado` (dado do INEP) em vez de vazios —
usuário pediu para não repetir na digitação um dado que o sistema já tem.
Continuam campo livre e editável pelo usuário; o pré-preenchimento só
acontece quando o Lado IXC ainda não tem valor próprio salvo (uma vez
salvo, esse valor passa a mandar) e só no formulário exibido (GET) — o
formulário que processa o "Salvar" (POST) não recebe esse valor no
`initial`, para o log por campo alterado (RN-008) continuar comparando
contra o valor anterior de verdade do RI, não contra a sugestão da Escola.
Não muda a comparação de divergência (ainda contra o valor salvo em `Ri`)
nem a exigência de preenchimento da RN-013.

### RN-018 — Lado Relatório EACE: mesmo formulário do Lado IXC (KIT Instalado + Produtos)
**Descrição:** O lançamento do Lado Relatório EACE (3º lado do RI) passa a
usar o mesmo mecanismo já implementado no Lado IXC (RN-011): "KIT
Instalado" (catálogo `KitPadrao`, Unidade "Escola"/"Escola-Mês", + opção
"Outro") e "Produtos" individuais via botão "+" (catálogo `KitPadrao`
excluída a Unidade "Escola"/"Escola-Mês"), ambos filtrados pelo Lote da
escola quando ela tiver um valor definido. Não ganha Data Ativação,
Município nem Estado — campos exclusivos do Lado IXC (RN-011/RN-014), sem
uso no Relatório EACE.

**Contexto:** Usuário pediu, em 2026-08-26, que o Lado 3 (Relatório EACE)
tenha os mesmos campos do Lado 2 (IXC), exceto Data de Ativação, Município
e Estado.

**Critérios:**
- Descrição livre deixa de existir para lançamento novo no Lado Relatório
  EACE — mesma mudança que a RN-011 já fez no Lado IXC; cada opção mostra a
  Descrição curta do catálogo (RN-011).
- Valor Unitário do KIT/Produto do Lado Relatório EACE é preenchido
  automaticamente a partir do `KitPadrao` (mesmo preço cadastrado por
  Lote) — diferente do Lado IXC (RN-011), que nasce com R$ 0,00. Decisão
  do usuário (2026-08-26): "o valor unitário é o mesmo do kit já
  cadastrado no sistema". Quantidade do KIT é sempre 1 (mesmo critério do
  Lado IXC); Quantidade dos Produtos é digitada manualmente.
- Limite de 1 KIT por INEP (RN-015) passa a valer também para o Lado
  Relatório EACE — campo "KIT" some da tela quando já existe um item
  marcado como KIT nesse lado.
- Exceção à imutabilidade da RN-003: o item marcado como KIT desse lado
  pode ser editado/excluído (mesma permissão da RN-004 já usada no Lado
  IXC — exclusão só para Administrador). Sem essa exceção, o limite de 1
  KIT tornaria qualquer correção impossível pela tela, já que o campo
  desaparece depois do 1º lançamento. Decisão do usuário (2026-08-26).
- **Ampliação (2026-08-27):** a mesma exceção passa a valer também para
  os itens "Produtos" desse lado — editar/excluir liberado, exclusão só
  Administrador. Usuário pediu depois de sincronizar a Planilha EACE
  (FEAT-024/RN-022) e não conseguir corrigir um Produto casado errado
  (ex.: "Nobreak") pela tela — o mesmo problema vale para qualquer
  Produto lançado manualmente, não só os vindos do Sincronizador.
- Regra vale só para o Lado Relatório EACE (3º lado). Não altera Kit
  Declarado (1º lado, RN-010) nem o próprio Lado IXC (RN-011), que
  continuam como estão.

**Exceções:** a edição/exclusão de qualquer item (KIT ou Produto) descrita
acima é a única exceção à imutabilidade geral da RN-003 para este lado.

**Impacto técnico:** `RiItemRelatorioEace` precisa de um campo equivalente
a `RiItemIxc.eh_kit` para identificar o item KIT desse lado (pendência
técnica já antecipada na RN-003); reaproveita o padrão de
`RiItemIxcKitForm`/`RiItemIxcProdutoForm`/`_catalogo_ixc` (ou equivalente)
e a view `ri_detail_view`; `ri_detail.html` (bloco do Lado Relatório EACE)
e `grid_inep.html` (card "Relatório EACE (3º)") passam a exibir o Valor
Unitário resolvido do catálogo em vez de um valor digitado manualmente.

**Features relacionadas:** FEAT-004, FEAT-022, FEAT-024.

**Status:** Ativa — **ampliação (2026-08-27):** editar/excluir passa a
valer também para Produtos, não só o KIT (ver Critérios).

### RN-021 — Importação da Planilha EACE (upload, Administrador)
**Descrição:** A tela "Administrador > Planilha EACE" permite upload de um
arquivo `.csv` (mesmo layout do `doc/EACE.csv` real: colunas "Projeto",
"Descrição do Item", "Qtde Produto", "Valor Unit UR", entre outras), que
substitui o arquivo ativo anterior. O sistema não copia as linhas para uma
tabela própria — guarda só o arquivo enviado; a leitura acontece sob
demanda, no momento do Sincronizador (RN-022).

**Contexto:** Usuário pediu, em 2026-08-27, para trazer a planilha real de
faturamento por INEP (`doc/EACE.csv`) para dentro do sistema. Confirmado
com o usuário (CLAUDE.md §9): upload pela tela (não comando de servidor
lendo caminho fixo) e sem tabela intermediária — só o arquivo é guardado,
reprocessado a cada sincronização.

**Critérios:**
- Upload aceita só `.csv` com as colunas mínimas esperadas (Projeto,
  Descrição do Item, Qtde Produto, Valor Unit UR); arquivo sem essas
  colunas é rejeitado com mensagem objetiva, sem gravar.
- Cada novo upload bem-sucedido substitui o arquivo ativo anterior — existe
  no máximo 1 arquivo ativo por vez.
- Tela exibe nome do arquivo ativo, data/hora e usuário do último upload.
- Ação de upload restrita a Administrador (extensão da RN-004).
- Ampliação (2026-09-02, pedido do usuário): aceita também o arquivo
  **bruto**, exportado direto do sistema da EACE, sem precisar tratar à
  mão antes de subir — vírgula como delimitador e campos entre aspas (a
  vírgula também aparece dentro dos valores numéricos, formato BR:
  `"21.765,83"`, só funciona por causa das aspas). O sistema detecta
  sozinho, pelo cabeçalho, qual dos dois formatos foi enviado — o já
  tratado (`;`, sem aspas) continua aceito do mesmo jeito.

**Exceções:** nenhuma.

**Impacto técnico:** novo model de metadado do arquivo ativo (nome,
caminho, enviado_por, enviado_em) — sem tabela de linhas da planilha; nova
rota/tela sob o grupo de menu "Administrador". Detecção de delimitador
(2026-09-02): `detectar_delimitador_planilha_eace` (apps/ri/services.py),
usada tanto na validação do upload (`PlanilhaEaceUploadForm`) quanto na
leitura de fato (`_agrupar_linhas_planilha_eace_por_inep`, RN-022).

**Features relacionadas:** FEAT-023.

**Status:** Ativa

### RN-022 — Sincronizador do Lado Relatório EACE a partir da Planilha EACE
**Descrição:** No painel "Relatório EACE (3º lado)" da tela do RI, um botão
"Sincronizador" reprocessa o arquivo ativo da Planilha EACE (RN-021),
filtra as linhas cujo "Projeto" seja igual ao INEP da escola do RI atual
e, para cada linha, casa a "Descrição do Item" com o catálogo `KitPadrao`:
KIT pelo número de Access Points (reaproveita `numero_access_points`/
`resolver_kit_declarado`, RN-010 ampliada/FEAT-016); produto avulso por
palavra-chave. Quantidade vem da planilha (coluna "Qtde Produto"); Valor
Unitário vem do catálogo (RN-018), não da planilha — a coluna "Valor Unit
UR" é só conferência (o valor já deve bater com o do catálogo, como o
próprio usuário observou ao descrever a coluna). Item sem correspondência
não é lançado automaticamente. Itens sincronizados são gravados como
`RiItemRelatorioEace` normal — aparecem e se comportam exatamente como um
item lançado manualmente da lista (RN-018), inclusive as regras de 1 KIT
por INEP (RN-015) e edição/exclusão restrita a Administrador (RN-004).
Lançamento manual continua disponível, antes ou depois de sincronizar.

**Contexto:** Usuário pediu, em 2026-08-27, para o Lado 3 buscar
automaticamente os dados "pelo INEP" a partir da planilha, sem substituir
a opção de preenchimento manual. Confirmado com o usuário (CLAUDE.md §9)
que a busca é sempre na planilha ativa local (RN-021), sem integração
externa nem tabela intermediária, e que a estratégia de casamento de texto
fica a critério do Dev/Orquestrador ("do jeito que ficar melhor e mais
assertível") — adotado o mesmo padrão já usado na RN-010 ampliada (Access
Points) para reduzir falso-negativo, já que a Descrição real da planilha
traz sufixos que o texto limpo do catálogo não tem (ex.: "Kit Cobertura
Wi-Fi - 12 Access Points - Equip - MEGA - CO").

**Critérios:**
- Botão "Sincronizador" avisa, sem travar a tela, quando não há Planilha
  EACE ativa (RN-021) ou quando não há linha para o INEP do RI.
- Item da planilha casado com o catálogo é gravado com a Descrição curta
  do catálogo (RN-011), Quantidade da planilha e Valor Unitário do
  catálogo (RN-018) — nunca o valor bruto da planilha.
- Item sem correspondência no catálogo não é lançado automaticamente; fica
  listado para o usuário decidir/lançar manualmente.
- Itens sincronizados respeitam RN-015 (1 KIT por INEP) e RN-004 (exclusão
  só Administrador).
- Sincronizar de novo não duplica item já lançado idêntico (mesma
  descrição + quantidade já existente no Lado 3 para aquele INEP).
- **Ampliação (2026-08-27):** cada item sincronizado (KIT ou Produto)
  também guarda, só para exibição, 3 dados adicionais lidos da mesma
  linha da planilha que o originou: Num OSP (coluna "Num OSP"), Validação
  OSP (coluna "Validação OSP") e Nota Fiscal (coluna "Nota Fiscal"). São
  campos fechados — nunca digitados nem editados manualmente, mesmo com a
  exceção de edição já valendo para o item (RN-003/RN-018 ampliada); só o
  Sincronizador os preenche. 1 Nota Fiscal cobre a Quantidade inteira
  daquele item (mesma linha da planilha já soma as unidades) — não é por
  unidade. Item lançado manualmente (fora do Sincronizador) nasce sem
  esses 3 dados (em branco). Exibidos na lista do Lado 3 como rótulo,
  valor em destaque verde.

**Exceções:** nenhuma.

**Impacto técnico:** leitura sob demanda do arquivo ativo (RN-021) na view
do RI; reaproveita `KitPadrao.resolver_kit_declarado`/
`numero_access_points` (FEAT-016) e o fluxo de gravação já existente do
Lado Relatório EACE (FEAT-022); `RiItemRelatorioEace` ganha 3 campos novos
(Num OSP, Validação OSP, Nota Fiscal), opcionais, preenchidos só pelo
Sincronizador.

**Features relacionadas:** FEAT-024.

**Status:** Ativa — **ampliação (2026-08-27):** 3 campos de exibição
(Num OSP, Validação OSP, Nota Fiscal) adicionados ao item sincronizado.

### RN-023 — Sincronização em lote do Relatório EACE (todas as RI) a partir da tela Planilha EACE

**Descrição:** O card "Arquivo ativo" da tela "Administrador > Planilha
EACE" (RN-021) ganha um botão "Sincronizar todas as RI", que aplica a
mesma lógica do Sincronizador individual (RN-022) a cada RI existente no
sistema, sem precisar abrir RI por RI. Reaproveita a mesma função de
casamento e gravação já usada pelo Lado Relatório EACE do RI — não é uma
lógica nova. Ao final, mostra um resumo agregado (RIs com item novo
lançado, RIs já sincronizados sem novidade, RIs sem correspondência no
catálogo, RIs sem linha na planilha para o INEP, RIs bloqueados pelo
status "Faturamento Concluído") e lista, à parte, os INEPs que precisam de
atenção manual (sem correspondência ou sem linha na planilha).

**Contexto:** Usuário pediu, em 2026-08-27, um botão dentro do card
"Arquivo ativo" para sincronizar todas as RI de uma vez, sem precisar
entrar RI por RI — hoje o Sincronizador (RN-022/FEAT-024) só roda por RI,
dentro da tela de cada RI. Escopo do lote (todas as RI existentes, sem
filtro) e nível de resumo (agregado + lista de pendências) definidos pelo
Orquestrador como opção mais simples e conservadora (CLAUDE.md §9): a
lógica de casamento por INEP já ignora RI sem linha correspondente, então
"todas as RI" e "só as RI com INEP na planilha" produzem o mesmo
resultado; sujeito a ajuste do usuário após validação.

**Critérios:**
- Botão "Sincronizar todas as RI" visível só para Administrador (mesma
  restrição da tela, RN-021), aparece só quando há Planilha EACE ativa.
- Roda a mesma lógica de casamento e gravação da RN-022 (KIT por número de
  Access Points, produto avulso por palavra-chave, Valor Unitário sempre
  do catálogo, Num OSP/Validação OSP/Nota Fiscal só do Sincronizador) para
  cada RI existente, sem alterar o comportamento já validado por RI.
- RI sem linha na planilha para o INEP dele entra no resumo como "sem
  linha na planilha", sem interromper o processamento dos demais.
- RI bloqueado pelo status "Faturamento Concluído" (RN-020) entra no
  resumo como "bloqueado pelo status", sem tentar gravar.
- Sincronizar de novo não duplica item já lançado (mesma regra da RN-022).
- Resultado final mostra resumo agregado com as contagens acima e a lista
  dos INEPs que precisam de atenção manual (sem correspondência no
  catálogo ou sem linha na planilha).
- Cada item lançado pelo lote é registrado no histórico do RI
  correspondente (RN-008), igual ao Sincronizador individual.

**Exceções:** nenhuma.

**Impacto técnico:** nova ação na view `planilha_eace_view`; reaproveita
`sincronizar_relatorio_eace_da_planilha` (FEAT-024) em laço sobre os RIs
existentes, sem duplicar a lógica de casamento; usar `select_related`/
`prefetch_related` ao carregar RIs/escolas/itens existentes para evitar
N+1 (mesmo padrão do grid, FEAT-007).

**Features relacionadas:** FEAT-025.

**Status:** Ativa

### RN-024 — Conclusão automática do RI pela coluna "Status escola" da Planilha EACE (RETIRADA em 2026-09-02)

**Retirada em 2026-09-02, pedido do usuário:** esta regra foi removida —
sincronizar o Relatório EACE (individual ou em lote) **não altera mais o
status do RI**, nem quando a coluna "Status escola" traz "Conectada"; só
lança os itens do Lado 3, como antes de existir esta regra. Motivo: o
usuário identificou que a troca automática estava acontecendo sempre que
havia KIT alterado no Lado 3, sem o controle esperado sobre quando o
faturamento é de fato concluído. **Impacto conhecido, não resolvido nesta
mudança:** os cards "Kits Instalados" (dashboard Equipamentos, RN-026-
style) e "Valor já Faturado" (RN-026) contam a partir de
`Ri.status == FATURAMENTO_CONCLUIDO` — sem a conclusão automática, esse
status só é alcançado pelo ciclo manual completo (RN-001), então esses
números tendem a ficar bem menores até o usuário decidir se quer uma nova
fonte para eles. Texto original da regra preservado abaixo, para
referência histórica — nada dele vale mais a partir desta data.

**Descrição (histórico, não vale mais):** O Sincronizador individual (RN-022/FEAT-024) e o
Sincronizador em lote (RN-023/FEAT-025) passam a ler também a coluna
"Status escola" (coluna T) do arquivo ativo da Planilha EACE (RN-021).
Quando o valor dessa coluna for exatamente "Conectada" para o INEP do RI,
o sistema muda automaticamente o status do RI para "Faturamento Concluído"
(RN-001, status 7) e grava a data/hora da sincronização em
`Ri.concluido_em` — mesmo efeito de uma conclusão manual.

**Contexto:** Usuário pediu, em 2026-08-27, que a conclusão do faturamento
deixe de depender só da confirmação manual (RN-001) quando a própria EACE
já sinaliza a escola como conectada na planilha usada pelo Sincronizador.
Confirmado com o usuário (CLAUDE.md §9) que a troca vale a partir de
qualquer status atual do RI — inclusive pulando etapas da sequência
principal — e mesmo quando o RI está em "Correção MEGA" (status 8), caso
em que a correção pendente é encerrada automaticamente, sem exigir o
retorno manual para "Andamento".

**Critérios:**
- A troca vale a partir de qualquer status atual do RI (RN-001), inclusive
  "Correção MEGA" — decisão explícita do usuário, que aceitou pular etapas
  intermediárias e encerrar uma correção em aberto quando a EACE já
  sinaliza a escola conectada.
- RI já em "Faturamento Concluído" não é afetado — mesmo bloqueio já
  existente na RN-020/`RI_BLOQUEADO_FATURAMENTO_CONCLUIDO` (nada muda).
- Comparação exata com "Conectada"; qualquer outro valor ("Em
  planejamento", "Em implantação", vazio ou variação de texto) não aciona
  a troca e não bloqueia o restante do Sincronizador (lançamento de itens
  continua normalmente).
- Vale para os dois botões — Sincronizador individual (FEAT-024) e
  Sincronizador em lote "Sincronizar todas as RI" (FEAT-025) — mesma
  verificação, sem duplicar lógica entre os dois.
- Independe do resultado do lançamento de itens da mesma sincronização
  (item sem correspondência no catálogo ou quantidade inválida não impede
  a troca de status) — são duas verificações independentes sobre a mesma
  linha da planilha.
- Cada troca automática é registrada no histórico do RI (RN-008), igual a
  uma troca manual de status.

**Exceções:** nenhuma — a troca é incondicional quando a coluna indica
"Conectada" para o INEP, inclusive sobrepondo o bloqueio manual de saída de
"Correção MEGA" (decisão explícita do usuário, ver Contexto).

**Impacto técnico:** leitura da coluna "Status escola" na mesma passada que
já agrupa as linhas da Planilha EACE por INEP
(`_agrupar_linhas_planilha_eace_por_inep`); nova escrita em `Ri.status` e
`Ri.concluido_em` dentro de `sincronizar_relatorio_eace_da_planilha`. Não
confundir com `Escola.status_conexao` (RN-007) — campo homônimo
("status de conexão" vs. "Status escola"), mas de origem e regra
totalmente diferentes (RN-007 é manual, a partir das datas de instalação
RE/RI; RN-024 é automático, a partir da planilha).

**Features relacionadas:** FEAT-024, FEAT-025.

**Status:** Retirada (2026-09-02) — ver nota no topo desta regra.

### RN-046 — Divergência de "Status escola" entre produtos do mesmo INEP (Lado 3)
**Descrição:** Cada item lançado no Lado Relatório EACE (3º lado,
`RiItemRelatorioEace`) passa a guardar também o valor da coluna "Status
escola" (coluna T) da linha da Planilha EACE que o originou — mesmo
mecanismo já usado para Num OSP/Validação OSP/Nota Fiscal (RN-022
ampliada): campo fechado, só o Sincronizador preenche, exibido por item no
painel. Quando os itens de um mesmo RI têm valores diferentes de "Status
escola" entre si, o sistema exibe um alerta "Divergência Status EACE" no
topo do painel e destaca em **vermelho todos os itens do Lado 3** desse RI
— não só o(s) item(ns) que diverge(m) da maioria.

**Contexto:** Usuário pediu, em 2026-08-28, que o "Status escola" (hoje já
lido pelo Sincronizador só para a conclusão automática do RI, RN-024)
também apareça por produto no Lado 3, já que a planilha traz esse valor
por linha (por produto), não 1 valor único por INEP. Confirmado com o
usuário (CLAUDE.md §9) que, ao detectar divergência, **todos** os itens do
Lado 3 ficam vermelhos — não há um lado de referência "correto" nessa
comparação (é entre produtos do mesmo lado, diferente da RN-002/RN-003,
que comparam lados diferentes).

**Critérios:**
- Valor de "Status escola" gravado por item no momento da sincronização
  (Sincronizador individual, FEAT-024, ou em lote, FEAT-025) — mesma linha
  da planilha que originou o item; item lançado manualmente não tem valor.
- Exibido por item no painel do Lado 3, mesmo padrão visual (rótulo com o
  valor) já usado para Num OSP/Validação OSP/Nota Fiscal.
- Divergência = pelo menos 2 itens do mesmo RI com "Status escola"
  preenchido e diferente entre si (comparação estrita, mesmo critério das
  RN-002/RN-003). Item sem valor (lançado manualmente) não entra na
  comparação.
- Havendo divergência: alerta "Divergência Status EACE" no topo do painel
  do Lado 3 (mesmo padrão visual do alerta já existente da RN-003) e todos
  os itens do Lado 3 do RI destacados em vermelho — não só os que diferem
  da maioria.
- Não bloqueia nenhuma transição de status do RI nem altera a RN-024
  (conclusão automática por "Conectada" continua incondicional e
  independente desta divergência).

**Exceções:** RI com nenhum item no Lado 3, ou com só 1 item, nunca aciona
o alerta (não há o que comparar).

**Impacto técnico:** novo campo em `RiItemRelatorioEace` (ex.:
`status_escola`) gravado dentro de `sincronizar_relatorio_eace_da_planilha`
a partir de `linha.get("Status escola")`, reaproveitado pelos dois
Sincronizadores (RN-022/RN-023); nova verificação de divergência entre os
itens do mesmo RI (mesma camada de `sincronizar_divergencia_kit_relatorio`,
RN-002/RN-003) exposta ao template do Lado 3.

**Features relacionadas:** FEAT-024, FEAT-025.

**Status:** Ativa

### RN-048 — CNPJ e CNPJ Fictício do Lado IXC

**Descrição:** O Lado IXC (2º lado) ganha dois campos de texto livre,
digitados manualmente: CNPJ e CNPJ Fictício. Vão para a planilha de
faturamento (RN-013): CNPJ na célula A16, CNPJ Fictício na B16, de cada
aba gerada.

**Contexto:** Pedido do usuário em 2026-09-01 — os dois valores precisam
constar na planilha de faturamento enviada ao financeiro.

**Critérios:**
- Campos exibidos no formulário do Lado IXC, logo abaixo de "Data
  Ativação".
- Preenchimento opcional para "Salvar" o Lado IXC — mesmo padrão de
  Município/Estado (RN-014): exigidos só na hora de gerar a planilha/
  enviar o e-mail (RN-013), nunca a cada "Salvar".
- Alteração de qualquer um dos dois gera entrada na linha do tempo
  (RN-008).

**Exceções:** texto livre — sem validação de dígito verificador (não
pedida pelo usuário).

**Impacto técnico:** campos `Ri.cnpj`/`Ri.cnpj_ficticio` (migration
`0025`); `RiDataAtivacaoForm`; `gerar_planilha_faturamento` (RN-013) grava
nas células A16/B16 de cada aba.

**Features relacionadas:** FEAT-008, FEAT-017.

**Status:** Ativa

### RN-049 — RI criado pelo Sincronizador em lote nasce "Implantação EACE"

**Descrição:** Ao rodar o Sincronizador em lote (FEAT-025) sobre uma
Escola que ainda não tem nenhum RI, mas que tem linha na Planilha EACE
ativa (RN-021) para o INEP dela, o sistema cria o RI ali mesmo — com
status "Implantação EACE" (RN-001), mesmo status do "Iniciar RI" manual
— e já processa os itens do Lado Relatório EACE nele, na mesma passada.

**Contexto:** Pedido do usuário em 2026-09-02 — antes, uma Escola sem RI
era sempre pulada silenciosamente pelo Sincronizador em lote, mesmo tendo
dado pronto para sincronizar; alguém precisava abrir a tela e clicar
"Iniciar RI" manualmente para cada Escola nova antes do lote conseguir
processá-la.

**Critérios:**
- Escola sem RI e **sem** linha na Planilha EACE continua sem RI — não
  cria um RI vazio sem motivo.
- Escola sem RI e **com** linha: RI novo nasce "Implantação EACE".
- RI recém-criado entra no restante do processamento do Sincronizador
  daquela mesma passada (itens lançados, "Status escola" conferido,
  RN-024).

**Exceções:** nenhuma.

**Impacto técnico:** `sincronizar_relatorio_eace_de_todas_as_ri`
(apps/ri/services.py).

**Features relacionadas:** FEAT-025.

**Status:** Ativa

## Dashboard e Relatórios Financeiros

### RN-025 — Card "Valor Total do Projeto" (Kit + Nobreak inicial, 1º lado)
**Descrição:** O dashboard (tela inicial, `core/home.html`) exibe um card
com o valor total que a empresa vai faturar com o projeto inteiro: soma,
para todas as Escolas cadastradas no sistema (visão global, sem filtro de
período/lote/status), o valor do Kit Declarado (RN-010) mais o valor do
Nobreak inicial (RN-017, correção 2026-08-27) — os dois resolvidos pelo
catálogo `KitPadrao`, cruzando descrição + `Escola.lote`. É o valor-alvo
do projeto, usado como referência do card "Valor já faturado" (RN-026).

**Contexto:** Usuário pediu, em 2026-08-27, um dashboard com cards
contando "a história" do projeto; o primeiro card é este valor total,
juntando Kit inicial e Nobreak inicial (1º lado). Confirmado com o
usuário (CLAUDE.md §9) que o Nobreak, apesar de a RN-017 dizer "sem valor
financeiro", tem valor cadastrado no mesmo catálogo do Kit — só não é
exibido nas telas onde já aparece hoje (correção da RN-017).

**Critérios:**
- Soma percorre todas as Escolas do sistema — visão global, sem filtro de
  período, lote ou status de RI.
- Cada Escola contribui com: valor do Kit Declarado (RN-010) + valor do
  Nobreak inicial (RN-017 corrigida), ambos via `KitPadrao` (descrição +
  `Escola.lote`).
- Escola cujo Kit ou Nobreak não tem correspondência no catálogo contribui
  com R$ 0,00 nessa parte do total — opção mais simples e conservadora
  (CLAUDE.md §9), mesma pendência de decisão ainda aberta na RN-010
  ("bloquear vs. permitir sem valor"); não trava o dashboard.
- Card mostra só o valor total consolidado (sem abrir por escola) — o
  detalhamento por escola já existe no grid de INEPs (FEAT-007).

**Exceções:** nenhuma.

**Impacto técnico:** consulta agregada em `apps/escolas`/`apps/ri` (soma
de `KitPadrao.valor_total` por Escola, sem N+1); nova seção em
`apps/core` (view/template de `home.html`); depende de o catálogo
`KitPadrao` já ter a entrada do Nobreak (ver correção da RN-017).

**Features relacionadas:** FEAT-026, FEAT-010, FEAT-015.

**Status:** Ativa (pendência herdada da RN-010: comportamento de kit/
nobreak sem correspondência no catálogo)

### RN-026 — Card "Valor já faturado" e diferença para a meta
**Descrição:** Segundo card do dashboard: soma o valor dos itens do Lado
Relatório EACE (3º lado, `RiItemRelatorioEace`, quantidade × valor
unitário) de todo RI cujo status é "Faturamento Concluído" (RN-001,
status 7) — visão global, todos os RIs do sistema. Item do Lado 3 de um
RI que não está em "Faturamento Concluído" não entra na soma. Dentro do
mesmo card, mostra a diferença entre esse valor e a meta do card "Valor
Total do Projeto" (RN-025): valor faturado menor que a meta mostra
"quanto falta" em vermelho; valor igual ou maior que a meta deixa o
indicador verde (sem "falta" a mostrar). O card usa uma divisão visual
proporcional à razão faturado/meta: parte verde (valor já faturado) na
fração de cima, parte vermelha (o que falta) na fração de baixo; ao
atingir ou ultrapassar a meta, o card fica inteiramente verde.

**Contexto:** Usuário pediu, em 2026-08-27, o segundo card do dashboard:
valor já ganho (produtos aprovados pela EACE, Lado 3, com RI em
Faturamento Concluído) e a diferença para a meta do primeiro card, com
cor indicando se falta ou já bateu a meta. Confirmado com o usuário
(CLAUDE.md §9) que "aprovado pela EACE" = item lançado no Lado 3 **e** a
RI daquele item estar em "Faturamento Concluído" — hoje não existe campo
de aprovação separado; item do Lado 3 de RI que não chegou nesse status
não conta, mesmo que o item já exista.

**Critérios:**
- Soma percorre todos os RIs do sistema com status "Faturamento
  Concluído" — visão global, sem filtro de período ou lote.
- Para cada um desses RIs, soma `quantidade × valor_unitario` de cada
  `RiItemRelatorioEace` vinculado.
- RI com item no Lado 3 mas status diferente de "Faturamento Concluído"
  não contribui para a soma, nem parcialmente.
- Diferença = valor do card "Valor Total do Projeto" (RN-025) menos o
  valor faturado deste card. Diferença positiva (falta faturar) em
  vermelho; diferença zero ou negativa (meta atingida/ultrapassada) —
  card fica verde, sem mostrar valor negativo de "falta".
- Divisão visual proporcional dentro do card: área verde proporcional ao
  valor faturado sobre a meta, área vermelha proporcional ao que falta;
  verde sempre posicionado acima, vermelho abaixo.

**Exceções:** nenhuma.

**Impacto técnico:** consulta agregada em `apps/ri` (soma de
`RiItemRelatorioEace.quantidade * valor_unitario` filtrada por
`Ri.status == Ri.FATURAMENTO_CONCLUIDO`, sem N+1); mesma
view/seção do dashboard da RN-025 (`apps/core`, `home.html`).

**Features relacionadas:** FEAT-026, FEAT-006, FEAT-022.

**Status:** Ativa

## Histórico de Alterações
| Data | Regra | Alteração |
|---|---|---|
| 2026-09-04 | RN-061 criada (barra de progresso por etapa da execução do RPA EACE, 16 etapas fixas, percentual = posição/total, zerada a cada nova tentativa); RN-058 ganha referência cruzada | Usuário pediu para acompanhar cada etapa da RPA (login, usuário, senha, navegação, upload...) como uma porcentagem numa barra de progresso, "até pra que o usuário possa ver se não está travado" |
| 2026-09-03 | RN-059 criada (cada tentativa de execução do RPA EACE gera 1 entrada na linha do tempo do RI — RN-008 — e 1 registro em Auditoria — RN-006 —, mesmo em reprocessamento); RN-060 criada (log "Sucesso" não aceita novo disparo nem troca de PDF/XML, validado também no backend); RN-006/RN-008 ganham referência cruzada e FEAT-033 | Usuário pediu que toda rodada de processamento fique registrada "nos logs do sistema" e que, após "Sucesso", os inputs não possam mais ser editados; 1ª implementação gravou só em Auditoria (sem tela própria) — usuário corrigiu que o lugar certo é a mesma linha do tempo onde já aparecem as trocas de status e descrições do RI (RN-008), mantendo Auditoria como trilha técnica adicional |
| 2026-09-03 | RN-056 ganha critério de visibilidade (seção de logs só aparece com o RI em "Resposta Financeiro") e referência cruzada a RN-060; RN-058 ganha critério de posição na fila, nota de correção de 3 bugs reais (estado "Processando" não aparecia, posição na fila ausente, tela não atualizava sozinha — conflito real de `hx-swap-oob` com o próprio polling HTMX) e registra a entrega do DevOps (serviço `rpa_eace_worker` no `docker-compose.yml`, processo consumidor rodando de verdade) | Usuário pediu, testando ao vivo (INEP 90000002, 2 Notas Fiscais na fila), que a opção de disparar a RPA só apareça com o RI em "Resposta Financeiro", e reportou os 3 bugs; Orquestrador formaliza documentação de trabalho já entregue e testado pelo Dev/DevOps em turnos anteriores desta mesma sessão |
| 2026-09-02 | Correção pontual de dados em produção (sem RN nova), 2ª rodada: usuário reportou que o financeiro respondeu o INEP 52032043 e a resposta não apareceu no sistema nem deu baixa no status — investigação revelou uma consequência mais grave do mesmo bug: quando o eco falso avança o status antes da resposta real chegar, a resposta real é descartada silenciosamente (`Ri` deixa de estar "Aguardando financeiro", único status aceito pra receber resposta), sem gravar nada, só aviso no log do servidor; varredura completa em produção encontrou mais 6 RIs com o mesmo eco ainda pendente (INEPs 52008649, 53005384, 17002109, 52049574, 17004810, 35278312, revertidos para "Aguardando financeiro") e, ao buscar direto na caixa de e-mail (Graph, fora da delta query já consumida) por resposta real perdida em cada um, recuperou 2 respostas genuínas do financeiro que tinham sido descartadas (INEP 52032043, RI 546; INEP 17002109, RI 1396) — reprocessadas com a mesma função de produção (`_processar_mensagem`), avançando o status corretamente para "Resposta Financeiro"; os outros 4 INEPs revertidos não tinham nenhuma resposta real na caixa ainda, então ficam corretamente em "Aguardando financeiro" | Usuário autorizou expressamente a varredura completa após reportar o caso do INEP 52032043; critério confirmado: reverter só quando for de fato eco (sem resposta legítima registrada), recuperar quando houver resposta real perdida; correção de código (domínio do remetente, RN-016) implantada em produção no mesmo dia (commit `f1c834a`) — ver linha da RN-016 corrigida, abaixo |
| 2026-09-02 | Correção pontual de dados em produção (sem RN nova): 9 RIs revertidos de "Resposta Financeiro" para "Aguardando financeiro" (INEPs 35009730, 35417051, 52032043, 52108880, 35050611, 35010337, 35399474, 35095874, 35234643) | Mesma causa da correção da RN-016 (linha abaixo): a cópia do e-mail enviado (remetente `posvendas@megainfraestrutura.com.br`) estava voltando para a própria caixa monitorada e sendo lida como resposta do financeiro; confirmado por leitura direta (só leitura) que nenhum dos 9 tinha resposta real do domínio `speedcsc.com.br` antes de reverter; usuário autorizou explicitamente a correção em produção, com o critério "se for falso positivo corrige, se realmente veio do financeiro deixa"; RiHistorico de cada RI ganhou entrada explicando o motivo; correção de código (fix do domínio) ainda não implantada em produção nesta data — pendência de deploy formal (DEPLOYMENT.md) para não repetir |
| 2026-09-02 | RN-016 corrigida (resposta do financeiro só conta se o remetente for do domínio `speedcsc.com.br`) | Usuário reportou falso positivo real (INEP 35271561): RI avançava para "Resposta Financeiro" sem o financeiro ter respondido — o código de rastreio (RN-009) identificava o RI pelo assunto, mas não validava o remetente; qualquer e-mail com o código (mesmo de fora do financeiro) avançava o status; confirmado com o usuário (CLAUDE.md §9): validar por domínio, não por lista fixa de endereços nem pelos destinatários específicos daquele envio |
| 2026-09-02 | RN-014 revisada (Município/Estado do Lado IXC nascem preenchidos com o cadastro da Escola — INEP —, continuam campo livre e editável) | Usuário pediu para não precisar digitar de novo Município/Estado quando o sistema já tem o dado do INEP; muda só o valor inicial exibido (`initial` do formulário) — não altera a comparação de divergência nem a exigência de preenchimento na hora de gerar a planilha/enviar o e-mail (RN-013), que continuam olhando o valor de fato salvo em `Ri`; pré-preenchimento só se aplica quando o campo do Lado IXC ainda está vazio, e só na renderização (GET) — o formulário do POST continua sem esse valor no `initial`, para não afetar o log por campo alterado (RN-008) |
| 2026-09-02 | RN-024 retirada (Sincronizador do Relatório EACE deixa de mudar o status do RI — só lança os itens do Lado 3, mesmo com "Status escola" = "Conectada"); RN-003 ajustada (Lado IXC ou Lado Relatório EACE totalmente vazio deixa de contar como divergência — confronto só faz sentido com os dois lados tendo algum valor) | Usuário pediu os dois ajustes explicitamente; RN-003 corrige bug real identificado nos dados (473 divergências "Com divergência" abertas, 471 delas falso positivo por lado vazio, já corrigidas nos dados gravados); afeta FEAT-024/FEAT-025 (RN-024) e FEAT-005/FEAT-007 (RN-003); impacto conhecido e não resolvido nesta mudança: cards "Kits Instalados"/"Valor já Faturado" (RN-026) dependem do RI estar "Faturamento Concluído", que agora só é alcançado pelo ciclo manual completo — usuário avisado |
| 2026-09-02 | RN-052 criada (rótulo do status "Andamento" passa a "Em Andamento"; Lado IXC só aceita lançamento/edição/exclusão com o RI nesse status — qualquer outro status fica somente leitura, formulário continua visível e desabilitado, não escondido) | Usuário pediu explicitamente os dois ajustes; formaliza no código o que a RN-001 já descrevia (dados do Lado IXC digitados só depois do status virar "Andamento"), mas que nunca tinha sido tecnicamente travado — antes só "Faturamento Concluído" bloqueava (RN-020); Lado Relatório EACE não afetado, continua só sob a RN-020; afeta FEAT-004/FEAT-006 |
| 2026-09-02 | RN-021 ampliada (aceita também o arquivo bruto exportado direto da EACE — vírgula + aspas, detectado sozinho pelo cabeçalho, sem precisar tratar à mão antes de subir) | Usuário anexou um arquivo real da EACE ("Documento correto.csv") mostrando que o formato bruto difere do já tratado só no delimitador (vírgula + aspas vs. ponto e vírgula sem aspas) — mesmas colunas/nomes nos dois; validado contra o arquivo real (1.783 linhas) sem alterar a Planilha EACE já ativa no ambiente local |
| 2026-09-02 | RN-051 criada (status do RI e ação "Enviar e-mail" editáveis direto na tela de detalhe, sem sair da página); RN-049 criada (RI do Sincronizador em lote nasce "Implantação EACE"); RN-011 recebe correção (mensagem de erro ao reenviar formulário sem mudanças) | Usuário pediu trocar o status e compor o e-mail sem sair da tela de detalhe do RI (bloco reposicionado no mesmo dia, do cabeçalho para abaixo dos 3 lados); testando a tela, reportou bug real (INEP 35275505) — mensagem "Selecione um KIT..." aparecia mesmo com tudo já preenchido, ao reenviar sem mudar nada; RN-049 resolve um pedido separado: Escola sem RI, mas com linha na Planilha EACE, ganha um RI automaticamente ao rodar o Sincronizador em lote, em vez de ficar pulada até alguém abrir a tela e clicar "Iniciar RI" à mão; gera FEAT-031 |
| 2026-09-01 | RN-048 criada (CNPJ e CNPJ Fictício do Lado IXC, gravados nas células A16/B16 da planilha de faturamento); RN-050 criada (assunto do e-mail ao financeiro passa a incluir o nome da escola) | Usuário pediu os dois campos novos no Lado IXC, mesmo padrão opcional de Município/Estado (RN-014) — confirmado com o usuário: exigidos só na hora de gerar a planilha/enviar o e-mail (RN-013), não a cada "Salvar"; assunto do e-mail ganhou o nome da escola no mesmo pedido, pra facilitar identificação pelo financeiro |
| 2026-09-01 | Correção pontual de dados (sem RN nova): importadas 96 escolas novas de "Nova BASE EACE.xlsx" (formato de planilha diferente do CONSOLIDADO EACE.xlsx já coberto pela RN-007) | Usuário autorizou explicitamente rodar em produção; comando novo (`importar_nova_base_eace`) segue a mesma regra de segurança do importador existente — só cria INEP que ainda não existe, nunca sobrescreve; backup do banco tirado antes, validado contra o banco real antes de aplicar; estende FEAT-002 |
| 2026-08-31 | RN-002 consolidada — confronto 1 (Kit declarado × IXC) é comparação de campo único (descrição do KIT), não item a item; fecha a pendência da FEAT-005 sem código novo | Investigação confirmou que `RiItemEace` nunca guardou lista de produtos avulsos (RN-010 removeu o lançamento manual em 2026-08-24) e que o alerta (`divergencia_kit`) já estava implementado e confirmado desde 2026-08-27 (FEAT-006); usuário confirmou que não há mais nada a fazer |
| 2026-08-31 | RN-006, campo "Exceções" atualizado | FEAT-011 entregue pelo Dev — decisão de implementação exercida (estendeu o `apps/auditoria` já existente, sem log específico à parte); aguardando QA |
| 2026-08-28 | RN-047 criada (usuário já autenticado que acessar `/login/` deve ser redirecionado ao dashboard, sem ver o formulário) | Usuário reportou, com print, que a tela de login aparecia com o menu lateral (sidebar) sobreposto; causa: `LoginView` do Django não redireciona por padrão quem já tem sessão ativa; gera `FEAT-030`, correção pendente do Dev |
| 2026-08-28 | RN-045 criada (liberação de acesso aos dados — todo usuário tem um controle Ligado/Desligado, independente do perfil; Desligado vê o menu mas nenhuma tela com dado, com aviso de "aguardando liberação"); RN-043 recebe ampliação (conta criada via AD também nasce Desligada) | Usuário pediu que toda conta nova (login solto ou via AD) entre no sistema sem ver nenhuma informação até o Administrador liberar manualmente; confirmado com o usuário (CLAUDE.md §9, 3 perguntas): vale para Administrador também, não só Analista; só conta criada a partir de agora nasce desligada — quem já usa o sistema hoje não é afetado; tela mostra aviso claro, não fica vazia sem explicação; gera `FEAT-029` |
| 2026-08-28 | RN-004 ampliada — tela interna "Administrador > Usuários" pode trocar perfil (Administrador ↔ Analista) de outro usuário, sem precisar do `/admin/` do Django; Administrador não pode trocar o próprio perfil por essa tela | Usuário pediu, depois de descobrir que a troca de perfil só existia pelo `/admin/` do Django, uma opção equivalente dentro do próprio menu Administrador; confirmado com o usuário (CLAUDE.md §9): escopo mínimo — só listar usuário e trocar perfil, sem criar/editar outros campos/desativar (isso continua só pelo `/admin/`); bloqueio de autotroca é decisão do Orquestrador (opção mais simples e conservadora, evita lockout acidental), a confirmar na validação; gera `FEAT-028` |
| 2026-08-28 | RN-043 e RN-044 criadas (autenticação via Active Directory e sincronização pós-login de e-mail/nome); RN-004 recebe exceção (criação automática de usuário via login AD, perfil Analista) | Usuário pediu a integração com AD; resolve pendência aberta em `lixo.md` (item 7) desde 2026-08-20; decisão de reaproveitar a mesma conta de serviço/config do `modulo-posVenda` registrada em `ADR-002`; gera `FEAT-027` |
| 2026-08-27 | RN-025 e RN-026 criadas (dashboard: card "Valor Total do Projeto" — Kit + Nobreak inicial — e card "Valor já faturado" com diferença para a meta); RN-017 corrigida (Nobreak inicial passa a ter valor financeiro, usado só no cálculo, sem mudança visual onde já aparece) | Usuário pediu cards do dashboard contando a "história" do projeto; confirmado com o usuário (CLAUDE.md §9, 3 perguntas): Nobreak tem valor no catálogo `KitPadrao` mesmo a RN-017 dizendo o contrário (só não exibe no frontend existente), "aprovado pela EACE" = item no Lado 3 com RI em Faturamento Concluído, e a soma é visão global (todas as escolas/RIs); gera FEAT-026 |
| 2026-08-27 | RN-024 criada (conclusão automática do RI a partir da coluna "Status escola" da Planilha EACE) | Usuário pediu que INEP com "Conectada" na coluna T do `doc/EACE.csv` mude o RI para "Faturamento Concluído" ao clicar em qualquer um dos 2 botões de sincronização (individual FEAT-024, ou em lote FEAT-025); confirmado com o usuário (CLAUDE.md §9, 3 perguntas): a troca vale a partir de qualquer status atual (inclusive pulando etapas), sobrepõe "Correção MEGA" em aberto e grava `concluido_em`; ordem corrigida no documento — a "Ampliação (2026-08-27)" da RN-022 (Num OSP/Validação OSP/Nota Fiscal) estava com o rodapé (Features relacionadas/Status) deslocado para depois da RN-023 por engano; movido para o lugar certo, sem mudar o conteúdo da regra; gera critério de aceite adicional em FEAT-024 e FEAT-025 |
| 2026-08-27 | RN-023 criada (Sincronização em lote do Relatório EACE — botão "Sincronizar todas as RI" no card "Arquivo ativo" da tela Planilha EACE) | Usuário pediu um botão dentro do card "Arquivo ativo" para sincronizar todas as RI de uma vez, sem precisar entrar RI por RI; reaproveita a lógica já existente do Sincronizador individual (RN-022/FEAT-024), rodando para cada RI e devolvendo um resumo agregado; gera FEAT-025, dependente da conclusão de FEAT-024 (hoje `🔍 Aguardando QA`) |
| 2026-08-27 | RN-022 ampliada — item sincronizado (KIT ou Produto) passa a guardar também Num OSP, Validação OSP e Nota Fiscal (colunas N/O/Q da planilha), campos fechados só para exibição, 1 Nota Fiscal por item (cobre a Quantidade inteira, não por unidade) | Usuário pediu para trazer essas 3 colunas da planilha para o Lado 3, só como rótulo (valor em verde), preenchidas só pelo Sincronizador; confirmado com o usuário (CLAUDE.md §9) que os 3 campos ficam por item lançado (não 1 só por RI), porque a Nota Fiscal pode variar entre o KIT e cada Produto da mesma planilha/INEP; gera critério de aceite adicional na FEAT-024 |
| 2026-08-27 | RN-003 e RN-018 ampliadas — a exceção de editar/excluir no Lado Relatório EACE, antes só do item KIT, passa a valer também para os itens "Produtos" (exclusão continua restrita a Administrador, RN-004) | Usuário testou o Sincronizador (FEAT-024) e reportou não conseguir excluir um Produto casado errado (ex.: "Nobreak"), só o KIT; confirmado com o usuário (CLAUDE.md §9) estender a mesma regra do KIT para qualquer Produto desse lado, não só os vindos do Sincronizador; Dev já entregou o código (`ri_item_relatorio_eace_update_view`/`_delete_view`, `ri_detail.html`) — este registro só formaliza a regra |
| 2026-08-27 | RN-021 criada (upload da Planilha EACE, sem tabela intermediária — só o arquivo é guardado) e RN-022 criada (Sincronizador do Lado Relatório EACE, casa a planilha com o catálogo `KitPadrao` pelo INEP); RN-004 recebe nota de extensão | Usuário pediu para importar `doc/EACE.csv` (Projeto/INEP, Descrição do Item, Qtde Produto, Valor Unit UR) via tela "Administrador > Planilha EACE" e um botão "Sincronizador" no Lado 3 que preenche os itens a partir do INEP, sem remover o preenchimento manual; confirmado com o usuário (CLAUDE.md §9, 3 rodadas de pergunta): upload pela tela (não caminho fixo de servidor), sem tabela de linhas (só o arquivo ativo é guardado, reprocessado a cada sincronização) e sem integração externa (sempre a planilha local); estratégia de casamento de texto delegada ao Dev/Orquestrador, adotado o padrão de Access Points já usado na RN-010 ampliada; gera FEAT-023 e FEAT-024 |
| 2026-08-27 | RN-020 criada (bloqueio dos campos do Lado IXC e do Lado Relatório EACE em "Faturamento Concluído"; troca de status nesse status passa a ser só do Administrador) | Usuário pediu que "Faturamento Concluído" vire um checkpoint: campos do 2º e 3º lado ficam bloqueados para os dois perfis enquanto o RI estiver nesse status, e só Administrador pode trocar o status a partir dele; ao trocar, os campos voltam a ficar liberados; afeta FEAT-006, ainda `🔄 Em andamento` |
| 2026-08-26 | RN-019 criada (exceção do Administrador: saída manual de "Aguardando financeiro" para "Resposta Financeiro") | Usuário pediu que o status "Aguardando financeiro" ficasse bloqueado a alterações e só um Administrador pudesse desbloquear; levantamento mostrou que esse status já não tem transição manual para nenhum perfil hoje (100% automático, RN-001); confirmado com o usuário (CLAUDE.md §9) que é uma exceção nova só para Administrador, com destino fixo "Resposta Financeiro", e que Analista continua sem opção manual, como já é hoje; afeta FEAT-006, ainda `🔄 Em andamento` |
| 2026-08-26 | RN-003 reescrita (confronto Relatório EACE × IXC passa a comparar Descrição + Quantidade, sem Valor Unitário); FEAT-005 atualizada com os critérios agora fechados | Usuário pediu para bloquear o envio ao financeiro quando o KIT/Produtos do Lado 3 divergem do Lado 2, com destaque vermelho no Lado IXC; confirmado com o usuário (CLAUDE.md §9): Valor Unitário sai do confronto (Lado IXC nasce sempre 0,00 desde a RN-011, criada depois desta regra — comparar valor seria sempre divergente) e Quantidade continua entrando; fecha a pendência de casamento entre itens em aberto desde 2026-08-22 |
| 2026-08-26 | RN-018 criada (Lado Relatório EACE ganha o mesmo formulário do Lado IXC — KIT Instalado + Produtos, sem Data Ativação/Município/Estado); RN-003, RN-011 e RN-015 recebem nota de extensão | Usuário pediu paridade de campos com o Lado IXC; confirmado com o usuário: limite de 1 KIT (RN-015) também vale para este lado, com exceção pontual de editar/excluir liberada só para o item KIT (senão a correção ficaria bloqueada, já que o Lado Relatório EACE não tem editar/excluir), e Valor Unitário preenchido automaticamente pelo catálogo `KitPadrao` (não zero, diferente do Lado IXC); gera FEAT-022 |
| 2026-08-26 | RN-017 criada (Nobreak declarado, item padrão fixo no Kit Declarado/1º lado) | Usuário pediu que toda Escola, além do Kit já declarado (RN-002/RN-010), também nasça com um Nobreak, exibido no card "Kit declarado (1º lado)"; confirmado com o usuário: mesmo Nobreak para todas as escolas (sem variação por lote) e sem valor financeiro (só informativo); gera FEAT-021 |
| 2026-08-26 | RN-016 criada (status "Resposta Financeiro" e extensão do gatilho automático); RN-001 e RN-005 atualizadas | Usuário pediu visibilidade de quando o financeiro responde ao e-mail e um card de contagem no grid; confirmado que é renomeação do status já existente (antes "Aguardando Anexo portal EACE", posição 5 de RN-001), sem status novo, e que o gatilho automático passa a valer também para resposta fora do padrão (antes só a válida mudava o status); gera FEAT-020 |
| 2026-08-26 | RN-002 esclarecida (alerta de campo único do KIT) | Usuário pediu, com a mesma mecânica já usada na RN-014 (município): quando o KIT declarado antes do projeto (`Escola.kit_inicial`) divergir do KIT instalado (Lado IXC), o campo do KIT fica com destaque amarelo (município usa vermelho); resolve a favor de manter os campos `Ri.kit_informado_ixc`/`Ri.divergencia_kit`, hoje sem uso; não altera o Confronto 1 item a item já documentado, só acrescenta o alerta de campo único; sem mudança de escopo na FEAT-005 |
| 2026-08-26 | RN-008 esclarecida (log cobre cadastro, não só alteração) | Usuário reportou que a linha do tempo (FEAT-014) só mostra troca de status, sem os itens cadastrados no Lado IXC e no Relatório EACE, nem a edição/exclusão deles; critério reescrito para deixar explícito que "campo relevante" inclui o cadastro inicial desses itens, não só mudança de um valor já existente; gera correção na FEAT-014, ainda `🔍 Aguardando QA` |
| 2026-08-26 | RN-013 revisada (2 vezes) e consolidada; RN-014 ganha nota de amendment; RN-015 criada (1 KIT por INEP) | Orquestrador consolidou o dia inteiro de ajustes reportados pelo Dev: (1) bloqueio por produto sem aba virou criação automática de aba, depois de o usuário reportar erro real em produção; (2) exigência de KIT/Data de Ativação/Município/Estado, que tentou travar o "Salvar" do Lado IXC (com 2 correções no meio), passou a travar só o envio de e-mail/download da planilha, por esclarecimento direto do usuário; (3) novo limite de 1 KIT por INEP, pedido separado do usuário no mesmo dia — texto de RN-013 reescrito para refletir o estado final, sem manter as versões abandonadas |
| 2026-08-26 | RN-013 criada (Anexo do financeiro em planilha, substitui PDF) | Usuário pediu que o e-mail ao financeiro leve a planilha-modelo `doc/FATURAMENTO MATERIAS EACE.xlsx` preenchida, em vez do PDF; mapeamento de células e regra de aba por produto confirmados contra a planilha real; produto sem aba correspondente bloqueia o envio (decisão do usuário, **revista no mesmo dia** — ver entrada acima); gera FEAT-017 |
| 2026-08-26 | RN-014 criada (Município/Estado do Lado IXC, com alerta de divergência contra o cadastro da Escola) | Usuário pediu 2 campos manuais no Lado IXC para conferência contra `Escola.municipio`/`Escola.estado`; decisão explícita: divergência é só alerta visual, não bloqueia; gera FEAT-018 |
| 2026-08-25 | RN-012 corrigida: exceção reescrita — RI criado fora da tela do sistema (admin/fixture) pode ficar sem responsável ("Não atribuído"); atribuição automática ao criador vale só para o fluxo `ri_iniciar` | Dev reportou, na entrega, que o texto original ("não há RI sem responsável") não correspondia ao comportamento real (`Ri.responsavel` é `null=True`); corrigido a regra para refletir o código, sem mudança de comportamento |
| 2026-08-25 | RN-012 criada (Responsável do RI: sai da tabela principal do grid, vira campo editável dentro do RI) | Usuário apontou que "Responsável" estava exibido como coluna do grid (FEAT-007) e pediu que passe a viver dentro das informações do RI (drill-down e `ri_detail`), editável por meio de lista dos usuários do sistema; reabre a discussão já registrada em FEAT-007 sobre onde essa coluna deveria viver, agora com uma decisão explícita do usuário |
| 2026-08-24 | RN-010 ampliada (cruzamento por número de Access Points) | Usuário identificou que, para parte das escolas, `Escola.kit_inicial` traz só o número do KIT (ex.: `4`) em vez do texto completo do catálogo `KitPadrao`; número sempre corresponde à quantidade de Access Points; proposto novo campo `KitPadrao.numero_access_points` para o cruzamento; confirmado que "lote 1"/"lote 2" citados pelo usuário são o 1º e 2º lado (RN-002), não `Escola.lote`; implementação pendente de autorização de feature |
| 2026-08-24 | RN-011 criada (Lado IXC: KIT Instalado + itens individuais via catálogo) | Usuário pediu, no Lado IXC, um input "KIT Instalado" (com valor unitário) e um "+" para lançar serviços individuais (serviço, quantidade, valor unitário); decisões confirmadas com o usuário: catálogo reaproveitado é o `KitPadrao` (RN-010), valor unitário digitado manualmente (não vem do catálogo) e o novo formato substitui o formulário de Descrição livre atual; afeta FEAT-004 |
| 2026-08-24 | RN-010 resolvida | Usuário decidiu manter `RiItemEace` com Valor Unitário único, sem discriminar Equipamento/Serviço como o catálogo `KitPadrao` — menor risco, sem migração de dado existente nem impacto no confronto RN-002/RN-003 ou no financeiro |
| 2026-08-24 | RN-010 ampliada | Fonte de carga do catálogo definida (aba `LPU` de `CONSOLIDADO EACE.xlsx`); cruzamento passa a considerar `Escola.lote` além da descrição; catálogo guarda valor de Equipamento e de Serviço separados; nova pendência sobre `RiItemEace` discriminar ou não os dois valores; gera FEAT-015 |
| 2026-08-20 | RN-001, RN-002 criadas | Usuário detalhou o ciclo de vida completo de status do RI; confirmado que o confronto de quantidade/valor (RF-04) acontece durante "Andamento" e bloqueia a transição para "Envio de Email para faturamento" |
| 2026-08-21 | RN-001 ampliada (8º status "Correção MEGA") | Usuário pediu um status para sinalizar RI com divergência EACE×IXC devolvido à MEGA para correção; confirmado como status oficial (não flag), retorno manual para "Andamento", permissão de Analista e Administrador |
| 2026-08-21 | RN-003, RN-004, RN-005, RN-006 criadas | Orquestrador formalizou como regra de negócio decisões já registradas em `requisitos.md` (confronto RF-04, permissões RF-13, segunda validação RF-09, auditoria RF-12), para vincular ao `checklist.md` recém-criado |
| 2026-08-21 | RN-007 criada | Usuário respondeu a pendência de campos adicionais de `Escola` (requisitos.md, ITEM 11) com a regra de status de conexão (desconectado/parcialmente conectado/conectado) |
| 2026-08-21 | RN-003 e RN-005 perdem a pendência do catálogo de divergência; RN-003 mantém só a pendência do critério de casamento entre itens | Cliente confirmou o catálogo (P-03: `valor`, `quantidade`, `kit_relatorio`, `nf_financeiro`), podendo ajustar ao longo do projeto se necessário |
| 2026-08-22 | RN-002 e RN-003 reescritas: RI passa de 2 para 3 "lados" — "Kit declarado" (1º, dado da EACE antes do projeto), "IXC" (2º) e "Relatório EACE" (3º, novo, baixado depois da instalação); RN-002 vira confronto informal 1º×2º (amarelo, não bloqueia); RN-003 vira confronto formal 3º×2º (vermelho do lado do IXC, bloqueia) | Usuário esclareceu que o model já implementado na FEAT-004 (`RiItemEace`) representa o 1º lado, não "o relatório" como estava documentado; confirmado que as duas comparações usam a mesma mecânica item a item; falta o Dev implementar o 3º lado (model novo) e ajustar FEAT-004/FEAT-007 |
| 2026-08-23 | RN-009 criada (código de rastreio do e-mail do RI) | Usuário pediu para trazer ao `Sistema_posvenda` a funcionalidade de e-mail do `modulo-posVenda`; formaliza o mecanismo de rastreio (RN-042 original de lá) adaptado para tratar só RI, vinculado a FEAT-008/FEAT-009 |
| 2026-08-24 | RN-010 criada (Kit Declarado: origem automática + catálogo de valores padrão) | Usuário apontou que o formulário do Kit Declarado não deve deixar digitar Quantidade/Valor Unitário; confirmado que a descrição vem da coluna H do `CONSOLIDADO EACE.xlsx` (mesma fonte de `Escola.kit_inicial`, FEAT-002) e que a regra vale também para itens de correção, não só o lançamento inicial; afeta FEAT-004, já `🔍 Aguardando QA` |
