# Referência de frontend — Grid de INEPs (FEAT-007)

_Criado em 2026-08-22, a partir da `ADR-001` (emenda do mesmo dia)._

Este diretório guarda **só referência visual e de código de UI**, trazida do
`modulo-posVenda` (tela "Endereços", menu Projeto → LastMile) para orientar
a implementação real da `FEAT-007` (Grid de INEPs com drill-down).

**Não é código funcional.** `grid_inep_referencia.html` é um arquivo HTML
estático (Tailwind via CDN, dado de exemplo fictício) — não é um template
Django, não está ligado a nenhuma view/URL deste repositório, e não deve
ser servido pela aplicação. `FEAT-007` continua `⬜ Pendente` no
`checklist.md`.

## O que foi trazido
- Layout de cabeçalho (breadcrumb, título, card de total).
- Formulário de busca/filtro (texto livre, UF/município, status).
- Grid principal com badge de status colorido e linha expansível
  (drill-down) — mesmo padrão visual da tela de origem (RN-043/067 do
  `modulo-posVenda`: rótulo e cor do indicador de status).
- Estado vazio, paginação e toast de feedback (sucesso/erro).

## O que foi deliberadamente excluído
Trechos que dependem de Parceiro, cotação de Parceiro ou Setor — descontinuados
pela `ADR-001` e não reaproveitados:
- Modal de vínculo de Parceiro e modal de cotação.
- Modal/aba de Campos personalizados por Setor.
- Seleção de Setor e a cascata Setor → Responsável.

## Ao implementar a FEAT-007 de verdade
- Portar a estrutura para um template Django em `apps/ri/templates/ri/`,
  ligado a view/URL reais.
- Substituir os dados de exemplo pelos campos reais (`Escola`, `RI`, itens
  EACE/IXC — ver `modelo-dados.md`).
- Usar o catálogo real de 8 status da `RN-001` no lugar dos textos de
  exemplo do filtro/badge.
- Resolver as classes de cor de marca (`bg-pv-black`/`text-pv-yellow`, já
  definidas em `core/base.html`) nos elementos que hoje usam utilitários
  genéricos do Tailwind (`amber-400`/`neutral-900`) só para este arquivo
  renderizar sozinho, sem depender do `base.html`.
