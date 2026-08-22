# ADR-001 - Convergência para um único sistema (Gerenciador Pós-Venda absorve o que precisar; `modulo-posVenda` é eliminado ao final)

## Status
Aprovado

## Contexto
`requisitos.md` (bloco 0, revisado em 2026-08-20) já havia decidido que o
Gerenciador Pós-Venda é um **sistema novo e separado** (repositório
`Sistema_posvenda`, banco próprio), criado copiando código do
`modulo-posVenda` — só frontend, e-mail e permissão — e que **os dois
sistemas não vão se comunicar depois de prontos**. Essa decisão não dizia,
porém, o que aconteceria com o `modulo-posVenda` e com os módulos dele sem
equivalente no Pós-Venda (Leads, Escolas, cadastro de Parceiros/Provedores,
integração IXC) depois que o sistema novo estivesse pronto.

Em 2026-08-22, ao investigar por que existiam duas telas de login visíveis
no mesmo dia e por que o Dev estava trabalhando no "módulo de parceiro"
(bug de logo no `modulo-posVenda`), o usuário esclareceu o objetivo final.

## Decisão
O sistema definitivo, ao final, é **um único sistema**: o Gerenciador
Pós-Venda (repositório `Sistema_posvenda`), com o escopo que já está
documentado em `docs_gerenciador_pos_venda/architecture.md` (faturamento
EACE por INEP — v1 processo RI, v2 RPAs, v3 IXC/RE limitado a esse fluxo).
**Não é uma expansão de escopo do Pós-Venda para absorver as demais
funcionalidades do `modulo-posVenda`.**

O `modulo-posVenda` passa a ser tratado como **fonte de reaproveitamento
incremental**, não como um segundo sistema mantido em paralelo
indefinidamente:

- à medida que o Gerenciador Pós-Venda precisar de uma funcionalidade
  equivalente a algo que já existe no `modulo-posVenda`, ela é trazida
  (copiada/adaptada) para o repositório novo, sob demanda;
- quando o Gerenciador Pós-Venda estiver completo para o uso esperado dele,
  **o `modulo-posVenda` inteiro é eliminado** — não só o que não tiver sido
  reaproveitado.

**Confirmado explicitamente em 2026-08-22:** isso inclui as funcionalidades
do `modulo-posVenda` que não têm nenhuma relação com faturamento EACE —
Leads, cadastro de Provedores/Parceiros e a integração IXC de uso geral.
Decisão do usuário: **essas funcionalidades não são reconstruídas dentro do
`Sistema_posvenda` nem em nenhum outro lugar — o negócio deixa de precisar
delas.** Não é reaproveitamento parcial com descarte do excedente; é
descontinuação do sistema de Parceiro/Provedor como um todo, junto com o
fim do `modulo-posVenda`.

Isso refina — não contradiz — o bloco 0 de `requisitos.md`: o
reaproveitamento continua sendo só de código (nunca integração em tempo de
execução entre os dois), mas agora há um destino final definido para o
repositório doador, e esse destino é o desaparecimento completo dele.

## Consequências positivas
- Um único sistema para manter, documentar e implantar ao final.
- Elimina a confusão de ter duas telas de login e nomes de container
  cruzados (`posvenda_*` vs. `parceiro_*`) rodando ao mesmo tempo sem um
  motivo declarado.
- Dá ao Dev um critério claro de prioridade: trabalho novo é no
  `Sistema_posvenda`; o `modulo-posVenda` só recebe atenção quando algo de
  lá precisa ser trazido, ou para correções pontuais enquanto ele ainda
  está em uso (ex.: o bug de logo corrigido em 2026-08-22).

## Consequências negativas / riscos
- Enquanto a convergência não termina, o `modulo-posVenda` continua em uso
  e pode exigir manutenção pontual mesmo estando "em extinção" — risco de
  investir esforço em algo que será descartado.
- Ainda não há critério objetivo de "quando o sistema novo está completo",
  nem lista do que precisa ser reaproveitado — sem isso, o momento da
  eliminação fica indefinido (ver Pendências).
- **Esta decisão é também uma descontinuação de produto, não só uma
  consolidação técnica:** Leads, cadastro de Provedores/Parceiros e a
  integração IXC de uso geral deixam de existir quando o `modulo-posVenda`
  for eliminado — ninguém reconstrói isso em outro lugar. Se houver
  usuário, processo operacional ou integração externa ainda dependendo
  dessas funcionalidades no momento da eliminação, a perda é real e
  definitiva, não só uma reorganização de código.
- Risco operacional de eliminar algo do `modulo-posVenda` que ainda estava
  em uso por engano, se a eliminação não for feita com confirmação
  explícita antes.

## Alternativas consideradas
- **Manter os dois sistemas rodando permanentemente em paralelo** —
  rejeitada agora pelo usuário: "o correto é apenas um sistema".
- **Migrar tudo de uma vez** (big-bang) em vez de incrementalmente — não
  escolhida; o usuário optou pelo reaproveitamento sob demanda, à medida
  que o novo sistema for precisando.
- **Criar um app novo (ex.: `apps/pos_venda`) dentro do próprio
  `modulo-posVenda`, abandonando o repositório `Sistema_posvenda`** —
  levantada de novo em 2026-08-22 e descartada: o usuário confirmou manter
  o repositório separado, preservando o trabalho já feito lá (FEAT-001 a
  FEAT-012, Docker/CI próprios). Não recriar esse app dentro do
  `modulo-posVenda` sem uma nova decisão explícita.

## Emenda (2026-08-22) — Reaproveitamento pontual do frontend da tela "Endereços"

**Contexto:** mais tarde no mesmo dia, o usuário pediu para levar ao
`Sistema_posvenda` o frontend da tela "Endereços" do `modulo-posVenda`
(menu Projeto → LastMile — grid de Escola + RE/RI/Mapa Calor). Perguntado,
confirmou duas coisas: (1) o escopo é só essa tela, não a tela Provedores
(cadastro de Parceiro); (2) não é mais só referência visual (como havia
sido registrado antes, no mesmo dia, em `checklist.md`/`FEAT-007`) — é
reaproveitamento de código de fato.

**Decisão:** abre-se uma exceção pontual dentro da descontinuação de Leads
já decidida acima. Podem ser copiados/adaptados para o `Sistema_posvenda`:
- o **frontend** (templates) da tela "Endereços" —
  `apps/leads/templates/leads/enderecos_lastmile.html` e os partials
  associados a ela em `apps/leads/templates/leads/partials/` (histórico,
  linha de RE/RI/Mapa Calor, opções de status/responsável);
- as **regras de frontend** que essa tela aplica — exibição/cor do
  indicador de status (RN-067), rótulo do badge (RN-043), filtros do grid
  (RN-035/066) e a cascata Setor→Responsável (RN-060).

Isso **não** muda o restante já decidido: Provedores/cadastro de Parceiro,
a integração IXC de uso geral e as demais telas de Leads continuam
descontinuados, sem reaproveitamento.

**Risco técnico identificado (não resolvido nesta emenda):** o frontend
dessa tela, na versão atual, também referencia recursos que esta ADR
descontinua — vínculo de Parceiro (RN-030), cotação de Parceiro (RN-044) e
permissão por Setor. Cabe ao Dev, ao implementar, decidir se remove esses
trechos do template copiado ou os adapta ao modelo de dados do
`Sistema_posvenda` (Escola/INEP, sem Parceiro/Setor) — ver pendência
abaixo.

## Pendências
- Definir o que efetivamente precisa ser reaproveitado do
  `modulo-posVenda` (lista ou critério), e em qual ordem.
- Definir o critério objetivo de "sistema novo completo" que dispara a
  eliminação do `modulo-posVenda`. Hoje (2026-08-22) esse critério está
  longe de ser atingido: só o FEAT-001 (esqueleto) está de fato commitado
  no `Sistema_posvenda`; FEAT-002 a FEAT-012 (toda a funcionalidade de
  faturamento RI e a infraestrutura) ainda não existem no repositório —
  ver `checklist.md`.
- Nenhuma exclusão de código ou dado do `modulo-posVenda` deve ocorrer sem
  pedido explícito do usuário, mesmo depois desta decisão — isto não é
  autorização para o Dev ou o DevOps apagarem algo por conta própria.
- (2026-08-22) Ao copiar o template de "Endereços" para o `Sistema_posvenda`
  (FEAT-007), remover ou adaptar as partes dependentes de Parceiro/cotação/
  Setor (ver Emenda acima) — decisão de implementação ainda não tomada.
