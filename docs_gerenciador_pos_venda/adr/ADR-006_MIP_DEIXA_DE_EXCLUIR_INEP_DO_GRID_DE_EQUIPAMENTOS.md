# ADR-006 - MIP deixa de excluir INEP do Grid de Equipamentos (grids voltam a espelhar o mesmo universo)

## Status
Aprovado

## Contexto
A RN-092 (2026-09-10) fez o INEP "sair" do Grid de Equipamentos (RI)
assim que `Escola.status_mip` chegava em "Aguardando Validação EACE"/
"Faturamento Concluído" (ou qualquer valor do ciclo do LOTE criado
depois, RN-098/RN-101) — dali em diante, o INEP só aparecia no MIP. Isso
deu ao grid do MIP um universo PRÓPRIO e menor: só quem já tinha passado
pelo handoff (`status_mip` preenchido); quem ainda não chegou lá não
aparecia em nenhum dos dois filtros de "Status (MIP)".

O usuário pediu para essa separação deixar de existir: quer o MIP como
uma "imagem" do RI — todos os INEPs, todas as informações dos lados —
sem o INEP sumir de uma tela quando aparece na outra, com o mesmo
card e o mesmo histórico para as duas.

## Decisão
Remover as duas exclusões de grid introduzidas pela RN-092/RN-074:

- Grid de Equipamentos volta a listar toda Escola, independente de
  `status_mip`.
- Grid do MIP passa a listar toda Escola cadastrada (não só quem já tem
  `status_mip` preenchido).

O campo `Escola.status_mip` e toda a lógica de handoff/ciclo de LOTE
(RN-092/RN-098/RN-101) continuam existindo e sendo gravados exatamente
como hoje — usados para elegibilidade de LOTE, para a coluna/filtro
"Status (MIP)" e para a exceção do equipamento só-valor-de-serviço. Só a
VISIBILIDADE do INEP nos 2 grids muda: de "um ou outro" para "os dois,
sempre".

A coluna/filtro "Status (MIP)" passa a mostrar o Status do RI real
(RN-001) enquanto `status_mip` for `None`, em vez de ficar em branco —
decisão explícita do usuário entre 3 alternativas apresentadas (Status
do RI real / branco sem filtro dedicado / coluna nova ao lado, ver
RN-103).

Investigação prévia confirmou que o item de equipamento "só valor de
serviço" lançado via MIP (exceção da RN-092) já grava em `RiItemIxc` — a
mesma tabela do Lado IXC do RI. Não existe hoje nenhuma tabela duplicada
para esse dado; o "mesmo card" já era compartilhado, só a linha do grid
é que ficava escondida. Por isso esta decisão não exige nenhuma migração
de dado nem model novo.

## Consequências positivas
- Usuário nunca mais perde de vista um INEP: qualquer um dos dois grids
  mostra todos.
- Itens lançados via MIP (equipamento só-valor-de-serviço) deixam de
  ficar "escondidos" no card do RI, sem nenhuma migração de dado.
- Nenhuma mudança de schema: só query de visibilidade e rótulo exibido.

## Consequências negativas / riscos
- Grid de Equipamentos volta a crescer para o tamanho da base inteira
  (antes filtrado para excluir INEPs pós-"Aguardando Validação EACE") —
  a paginação/consulta atual precisa aguentar o volume total de novo
  (mesma situação de antes da RN-092, não é regressão nova introduzida
  por esta ADR).
- Coluna "Status (MIP)" passa a misturar 2 catálogos de rótulo (6 do RI
  + 5 do MIP) — qualquer consumo desse filtro fora da tela (relatório,
  integração) precisa passar a considerar os 2 conjuntos.
- Quem usava o Grid de Equipamentos como "fila do que falta fazer"
  (RN-092 tirava automaticamente quem já tinha passado da etapa) perde
  esse recorte automático — passa a depender do filtro manual de Status
  do RI para o mesmo efeito.

## Alternativas consideradas
- **Manter a exclusão do Grid de Equipamentos e só ampliar o MIP para
  mostrar todo mundo** — descartada: o usuário pediu explicitamente que
  o INEP "não vá mais para o MIP" (não suma do RI), não só que o MIP
  ganhasse mais linhas.
- **Coluna "Status (MIP)" em branco antes do handoff (mudar menos)** —
  descartada: o usuário preferiu mostrar o Status do RI real, para o
  MIP funcionar de fato como imagem do RI em qualquer etapa.
- **Duas colunas lado a lado (Status do RI dedicado + Status (MIP)
  dedicado)** — descartada por ora: o usuário preferiu a leitura mais
  literal (uma coluna só, mostrando o que for mais específico em cada
  momento); pode ser revisitada se a mistura de rótulos confundir na
  prática.

## Pendências
- Confirmar com o usuário, depois do Dev entregar, se a paginação/
  desempenho do Grid de Equipamentos aguenta bem o volume total de novo
  (mesmo comportamento de antes da RN-092) — sem indício de problema
  conhecido, só não foi testado sob este volume desde a mudança.

Regenerar/revisar esta ADR se a mistura de rótulos "Status (MIP)"
(6 do RI + 5 do MIP) se mostrar confusa na prática e o usuário pedir a
alternativa de 2 colunas lado a lado.
