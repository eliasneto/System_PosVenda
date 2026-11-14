# Sistema Pós-venda — Manual do Usuário

O **Gerenciador Pós Venda** acompanha o faturamento do projeto EACE escola por escola (cada escola é identificada pelo seu **INEP**). No processo **RI** (equipamentos), ele compara o que foi instalado (Lado IXC) com o que a EACE reconhece (Relatório EACE), gera a planilha de faturamento e a envia por e-mail ao financeiro, recebe de volta as Notas Fiscais e anexa essas notas no portal da EACE por um robô. No processo **MIP** (serviço de implantação), ele agrupa os INEPs em LOTEs por cidade, gera as planilhas de faturamento e envia as notas ao portal. O sistema também controla os Boletins de manutenção (BDO), mostra painéis de faturamento e traz relatórios para o Administrador.

## Como entrar no sistema

1. Abra o endereço do Gerenciador Pós Venda no navegador (peça o endereço ao seu Administrador).
2. Na tela **Login**, preencha **Usuário** e **Senha** (o mesmo usuário e senha que você usa na rede da empresa).
3. Clique em **Entrar no Sistema**.

O que pode acontecer:

- **"Usuário ou senha inválidos."** — confira o usuário e a senha e tente de novo. Se continuar, fale com o Administrador.
- **"Aguardando liberação do Administrador"** — no primeiro acesso o seu usuário é criado com o perfil **Analista**, mas o acesso aos dados fica desligado. Peça a um Administrador para ligar o seu acesso em **Administrador › Usuários**.

Para sair, clique em **Sair do Sistema**, no fim do menu lateral. O botão com a lua/sol, no topo da tela, liga e desliga o **modo escuro**.

## O menu do sistema

O menu fica na lateral esquerda (no celular, abra pelo botão de menu no topo). No fim do menu aparecem o seu usuário e o seu perfil (**Administrador**, **Analista** ou **Visualizador**). O que cada perfil vê:

- **Administrador**: tudo.
- **Analista**: Dashboard e Projeto (não vê os menus Administrador e Automações IXC).
- **Visualizador**: só **Projeto › Equipamentos** e **Projeto › MIP**, apenas para consulta e sem valores em R$.

Itens do menu:

- **Dashboard**
  - **Faturamento RI** — valor total do projeto, valor já faturado e faturamento por status do RI, por estado e município.
  - **Faturamento MIP** — mesma visão para o serviço de implantação (MIP).
  - **Equipamentos** — kits programados x instalados, nobreaks e equipamentos complementares.
  - **Relatórios** — ainda sem conteúdo.
- **Projeto**
  - **Equipamentos** — lista de INEPs (tela "Pagamentos a Receber") e o RI de cada escola.
  - **MIP** — INEPs do processo MIP, com o Status (MIP) e criação de LOTE.
  - **MIP (LOTE)** — LOTEs criados, planilhas, status e envio das notas ao portal EACE.
  - **Fila** — fila do robô que anexa as Notas Fiscais no portal EACE.
  - **Validação MIP (NF)** — situação das Notas Fiscais do MIP por município no portal EACE.
  - **BDO** — faturamento mensal das manutenções de RI e RE (Boletins).
- **Administrador** (só Administrador)
  - **Relatório EACE (RI)** — envio da Planilha EACE usada pelo RI.
  - **Relatório EACE (MIP)** — envio do relatório EACE do MIP e das Notas Fiscais do MIP.
  - **Relatório BDO** — importação dos Boletins (planilha FR_XXXX) e da Pro rata.
  - **Relatório** — relatórios de faturamento para exportar.
  - **NFs canceladas no financeiro** — notas que o financeiro cancelou depois de enviar, para dar baixa.
  - **Usuários** — perfil e acesso de cada usuário.
  - **Backup** — exportar e importar a cópia completa dos dados.
- **Automações IXC** (só Administrador)
  - **Login (Endereços)** — criação em massa de logins (endereços) no IXC a partir de planilha.
  - **Atendimentos** — criação em massa de atendimentos no IXC a partir de planilha.

## Como encontrar um INEP na lista de equipamentos (RI)

Caminho: **Projeto › Equipamentos** (tela **Pagamentos a Receber**).

1. No campo de busca, digite o INEP, o nome da escola, o município ou a UF.
2. Se quiser, escolha **Status de conexão** (Desconectado, Parcialmente conectado, Conectado) e **Status do RI**.
3. Clique em **Filtrar**. Para voltar à lista completa, clique em **Limpar filtros**.
4. Os quadros do topo também filtram: **Com divergência** mostra só os INEPs com divergência aberta e **Resposta Financeiro** mostra só os RIs que já receberam resposta do financeiro.
5. Clique na linha do INEP para abrir o resumo: status, responsável, envio ao financeiro e os itens dos três lados (**Kit declarado**, **IXC** e **Relatório EACE**). Clique em **Ver histórico completo** para abrir a tela do RI.

A coluna **Data Faturamento** mostra a data em que o financeiro respondeu o e-mail. Linha em vermelho indica divergência aberta.

## Como iniciar o RI de uma escola

Caminho: **Projeto › Equipamentos**.

1. Encontre o INEP e abra a linha. Se aparecer **"RI ainda não iniciado para este INEP."**, clique em **Iniciar RI**.
2. O sistema mostra **"RI iniciado para este INEP."** e o RI começa no status **Implantação EACE**.

O Visualizador não pode iniciar RI.

## Como funcionam os status do RI

Caminho: **Projeto › Equipamentos**, na linha do INEP ou na tela do RI (campo **Status do RI**).

A ordem normal é:

1. **Implantação EACE** — status inicial. Daqui só é possível ir para **Em Andamento**.
2. **Em Andamento** — o Lado IXC e o Relatório EACE estão sendo preenchidos e conferidos.
3. **Envio de Email para faturamento** — pronto para enviar a planilha ao financeiro. Só aparece na lista quando o RI está pronto para envio.
4. **Aguardando financeiro** — automático, depois que o e-mail é enviado.
5. **Resposta Financeiro** — automático, quando o financeiro responde o e-mail com as Notas Fiscais.
6. **Faturamento RI Concluído** — automático quando todas as Notas Fiscais forem anexadas no portal EACE com sucesso (ou marcado à mão a partir de "Resposta Financeiro").
7. **Correção MEGA** — usado a partir de "Em Andamento" quando algo precisa ser corrigido; volta só para "Em Andamento".

Para trocar o status, escolha o novo valor em **Status do RI**; a mudança é salva na hora e aparece **"Status do RI atualizado."**

Mensagens comuns:

- **"A partir de "Implantação EACE", só é possível mudar o status para "Em Andamento"…"** — passe primeiro para "Em Andamento".
- **"Esse status só é alterado automaticamente pelo sistema."** — "Aguardando financeiro" e "Resposta Financeiro" não são escolhidos à mão.
- **"Bloqueado: há divergência aberta que impede o envio ao financeiro…"** — corrija a divergência entre o Lado IXC e o Relatório EACE antes de ir para "Envio de Email para faturamento".
- **"Bloqueado: há log de RPA EACE ainda pendente ou com erro para este RI…"** — resolva ou reprocesse as Notas Fiscais pendentes antes de marcar o RI como concluído.
- **"INEP no MIP: o RI fica em "Faturamento RI Concluído" — altere o Status (MIP) na tela do MIP."** — o INEP já está no processo MIP; o status é controlado em **Projeto › MIP**.

O Administrador tem o botão **Forçar Resposta Financeiro** quando o RI está em "Aguardando financeiro", para seguir sem esperar o e-mail do financeiro.

## Como trocar o responsável por um RI

Caminho: **Projeto › Equipamentos** (abra a linha do INEP) ou a tela do RI.

1. No campo **Responsável**, escolha o usuário.
2. A troca é salva na hora e aparece **"Responsável do RI atualizado."**

Se o INEP estiver em "Processo Concluído" no MIP, só o Administrador pode alterar.

## Como preencher o Lado IXC do RI

Caminho: **Projeto › Equipamentos** › abra o INEP › **Ver histórico completo** (tela do RI), bloco **IXC (2º lado)**.

1. Em **KIT Instalado**, escolha o **Kit** (se for "Outro", informe o **Número de Access Points**).
2. Em **Produtos**, clique em **Adicionar produto** para cada equipamento extra e informe **Produto** e **Quantidade**.
3. Em **Itens só com valor de serviço (uso no MIP)**, use **Adicionar item** para equipamentos que não têm valor de equipamento na tabela de preços.
4. Preencha **Data Ativação**, **Mês da Operação**, **CNPJ**, **CNPJ Fictício**, **Município (Lado IXC)** e **Estado (UF)**.
5. Clique em **Salvar**.

Regras:

- Só Administrador e Analista editam o Lado IXC. Para os outros aparece **"Os campos do Lado IXC só podem ser editados por Administrador ou Analista."**
- Só é permitido **1 KIT por INEP**. Para trocar, use **Editar** ou **Excluir item** no KIT já lançado. Mensagem: **"Este RI já tem um KIT lançado — só é permitido um KIT por INEP…"**
- **KIT, Data de Ativação, Município, Estado, CNPJ e CNPJ Fictício** precisam estar preenchidos para enviar o e-mail ou baixar a planilha do financeiro.
- Se o KIT ou os produtos forem diferentes do Relatório EACE, eles ficam em vermelho e o envio ao financeiro fica bloqueado até a correção.
- Se o KIT for diferente do Kit declarado ou o município for diferente do cadastro da escola, aparece um aviso apenas para conferência (não bloqueia).
- Excluir item do Lado IXC é permitido só ao Administrador.

## Como preencher o Relatório EACE do RI

Caminho: **Projeto › Equipamentos** › abra o INEP › **Ver histórico completo** (tela do RI), bloco **Relatório EACE (3º lado)**.

Forma rápida (recomendada):

1. Clique em **Sincronizador (KIT)**. O sistema busca os itens do INEP na Planilha EACE enviada pelo Administrador e lança os que forem encontrados.
2. Confira os itens: cada um mostra **Num OSP**, **Validação OSP**, **Nota Fiscal** e **Status Equip**.

Forma manual:

1. Em **KIT Instalado**, escolha o **Kit**; em **Produtos**, clique em **Adicionar produto** e informe **Produto** e **Quantidade**.
2. Clique em **Salvar**. Aparece **"Relatório EACE atualizado."**

Regras:

- Só 1 KIT por INEP também neste lado. O KIT lançado pode ser corrigido (editar/excluir); os demais produtos só aceitam lançamento novo.
- Se o INEP estiver em "Processo Concluído" no MIP, o lançamento fica bloqueado: **"INEP em "Processo Concluído" (MIP) — os campos do Lado Relatório EACE ficam bloqueados até o Administrador trocar o status."**
- **"Selecione um KIT ou um produto para lançar."** — nada foi escolhido antes de salvar.
- Aviso **"Divergência Status EACE"** — produtos do INEP têm "Status Equip" diferentes na Planilha EACE.
- Sem **Num OSP** o robô não consegue anexar a nota no portal (mensagem **"RI sem "Num OSP"…"**). Rode o Sincronizador depois que o Administrador enviar uma Planilha EACE atualizada.

## Como enviar a planilha de faturamento ao financeiro (escolha do CFOP)

Caminho: **Projeto › Equipamentos** (linha do INEP, botão **Compor e-mail**) ou tela do RI (botão **Enviar e-mail**, no bloco **Financeiro**).

O botão só aparece quando o RI está em **Envio de Email para faturamento**.

1. Clique em **Compor e-mail** (ou **Enviar e-mail**). Abre a janela **Enviar e-mail — INEP ...**.
2. Confira **Para**, **Cc** e **Assunto** (já vêm preenchidos). O campo **De** é automático.
3. Em **CFOP da planilha**, escolha:
   - **5117 – antigo (entrega futura)** (padrão), ou
   - **5102-004 – novo (venda)**.
   O CFOP escolhido vai no CFOP do destinatário e do local de entrega de todas as abas da planilha.
4. Para conferir antes, clique em **Baixar planilha** (baixa a planilha com o CFOP escolhido, sem enviar nada).
5. Se quiser, anexe mais um arquivo em **Anexo** (opcional; a planilha de faturamento já vai anexada automaticamente) e escreva uma **Mensagem**.
6. Clique em **Enviar e-mail**. Na tela **Confirmar envio ao financeiro**, revise e clique em **Confirmar envio** (ou **Voltar** para corrigir).
7. Aparece **"E-mail enviado ao financeiro. Status do RI atualizado."** e o RI passa para **Aguardando financeiro**.

Regras:

- Depois de enviado, o e-mail não pode ser editado.
- O assunto sempre leva um código de rastreio do INEP; mesmo que você o apague, o sistema coloca de volta. É por ele que a resposta do financeiro volta para o RI certo.
- O vencimento na planilha é a data de geração + 30 dias.
- O envio fica registrado no **Histórico de comunicação** com o CFOP usado.

Mensagens comuns:

- **"Antes de enviar o e-mail ou baixar a planilha, preencha no Lado IXC: ..."** — complete os campos citados no Lado IXC e tente de novo.
- **"Esse RI não está em "Envio de Email para faturamento"."** — troque o status antes de enviar.
- **"Informe ao menos um destinatário."** — preencha o campo **Para**.

## O que acontece quando o financeiro responde com as Notas Fiscais

Caminho: **Projeto › Equipamentos** › tela do RI.

1. O sistema lê a resposta do financeiro sozinho, guarda o PDF e o XML de cada Nota Fiscal no RI e muda o status para **Resposta Financeiro**.
2. A resposta aparece no **Histórico de comunicação** (com os botões para baixar cada documento).
3. No bloco **Notas Fiscais para anexar no portal EACE** aparece um card por Nota Fiscal.

Se aparecer **"Resposta do financeiro sem Nota Fiscal anexada"**, o e-mail do financeiro chegou sem PDF/XML. Reenvie o e-mail ao financeiro pedindo o PDF e o XML da Nota Fiscal.

Para conferir as notas recebidas, clique em **Validar Notas Fiscais**: o sistema compara Descrição, Quantidade, Valor Unitário e Valor Total de cada nota com o Relatório EACE. Resultados:

- **"... Nota(s) Fiscal(is) conferem com o Relatório EACE."** — tudo certo.
- **"... Nota(s) Fiscal(is) com divergência — ver detalhes no Histórico de comunicação."** — veja no histórico qual nota diverge e o motivo.
- **"Nenhuma Nota Fiscal (PDF) recebida do financeiro para validar."**

## Como fazer um faturamento complementar

Use quando um INEP já foi faturado e é preciso pedir ao financeiro **Notas Fiscais a mais** (itens que ficaram de fora). Pode haver vários complementares no mesmo INEP: o primeiro é o **C1**, o segundo o **C2**, e assim por diante.

Caminho: **Projeto › Equipamentos** › tela do RI › botão **Faturamento complementar** (bloco **Financeiro**, ao lado do status do RI).

Quem pode: **Administrador** e **Analista**. Com o INEP em "Processo Concluído" no MIP, só o **Administrador**. O botão funciona em qualquer status do RI.

1. Clique em **Faturamento complementar**. Abre a janela **Faturamento complementar — INEP ...**.
2. Em **Complementares já enviados**, veja os que já existem (C1, C2...), com a situação (**Enviado ao financeiro** ou **Respondido pelo financeiro**), a data e o link **Planilha**.
3. Em **Novo: complementar C...**, preencha cada item:
   - **KIT / produto**: escolha na lista (é a mesma lista do Lado IXC).
   - **Qtd.**: a quantidade.
   - **Num OSP**: escolha a OSP do item. É obrigatório quando o RI tem mais de uma OSP; com uma OSP só, ela já vem escolhida.
   O valor unitário vem da tabela de preços e não pode ser alterado; o total aparece embaixo. Use **Adicionar item** para mais linhas e o **x** para tirar uma linha.
4. Escolha o **CFOP da planilha** (**5117 – antigo (entrega futura)** ou **5102-004 – novo (venda)**) e, se quiser, escreva **Observações**.
5. Para conferir antes, clique em **Baixar planilha**. A planilha se chama "FATURAMENTO MATERIAS EACE - COMPLEMENTAR C... - INEP - escola". Nada é enviado; o complementar fica guardado como rascunho com o mesmo número.
6. Clique em **Enviar ao financeiro**. Na tela **Confirmar envio do complementar C...**, confira **Para**, **Cc** e **Assunto** e clique em **Confirmar envio** (ou **Voltar** para corrigir).
7. Aparece **"Faturamento complementar C1 enviado ao financeiro. O status do RI não mudou."**

O que o complementar NÃO muda:

- Os itens do **Lado IXC** e do **Relatório EACE** continuam iguais.
- O **status do RI** e o **Status (MIP)** continuam iguais.
- Tudo fica registrado no **Histórico de comunicação** do RI (itens, CFOP, total e a planilha enviada).

Regras:

- O assunto leva um código próprio terminado em **-C1**, **-C2**... Mesmo que você apague, o sistema coloca de volta. É por ele que a resposta volta para o complementar certo.
- O vencimento na planilha é a data de geração + 30 dias.
- A planilha usa os dados do Lado IXC do RI (CNPJ, CNPJ Fictício, Município, Estado).

Mensagens comuns:

- **"Faturamento complementar: Item 1: escolha o Num OSP (este RI tem mais de uma OSP)."** — escolha a OSP do item indicado.
- **"Faturamento complementar: Item 1: escolha um KIT/produto da lista."** ou **"... informe a quantidade (1 ou mais)."** — complete a linha indicada.
- **"Antes de gerar a planilha do faturamento complementar, preencha no Lado IXC: ..."** — complete os campos citados no Lado IXC e tente de novo.
- **"O faturamento complementar só pode ser feito por Administrador ou Analista."**
- **"INEP em "Processo Concluído" (MIP) — só o Administrador pode alterar."**

## O que acontece quando o financeiro devolve a NF complementar

Caminho: **Projeto › Equipamentos** › tela do RI.

1. O sistema lê a resposta do financeiro sozinho e guarda o PDF e o XML de cada Nota Fiscal no RI.
2. No **Histórico de comunicação** aparece **"Resposta do faturamento complementar C... recebida do financeiro"**, com os botões para baixar cada documento.
3. No bloco **Notas Fiscais para anexar no portal EACE**, em **Notas Fiscais complementares**, aparece um card **NF complementar C... #...** para cada Nota Fiscal desse complementar, já com o PDF, o XML e a OSP escolhidos.
4. Clique em **Processar** em cada card, como nas outras notas.

Regras:

- O status do RI **não muda** com a resposta nem com o envio das notas complementares.
- Só abrem cards para as notas desse complementar; as notas do faturamento normal não são tocadas.
- Cada nota vai para a OSP do item do complementar. Com mais de uma OSP, o sistema escolhe pela nota que tem o mesmo valor do item.
- No relatório **Faturamento EACE Materiais (NOVO)**, a nota complementar **soma** com as outras notas do INEP (não substitui). Se ela for cancelada no financeiro e receber baixa, sai do relatório como as demais.

Mensagens comuns:

- **✗ Erro — "O portal não tem linha Pendente com o valor desta NF complementar..."** — confira no portal EACE se a OSP tem a linha do item complementar com o mesmo valor da nota. Depois de acertar, clique em **Tentar novamente**.
- **"Não foi possível definir a OSP desta NF complementar C...: o valor do PDF não bate com nenhum item do complementar."** — confira se o PDF escolhido é mesmo deste complementar.

## Como anexar a Nota Fiscal do RI no portal EACE (robô)

Caminho: **Projeto › Equipamentos** › tela do RI › bloco **Notas Fiscais para anexar no portal EACE**.

1. No card **Nota Fiscal #...**, confira o **Nota fiscal (PDF)** e o **XML** escolhidos.
2. Clique em **Processar** (ou **Tentar novamente**, se o card estiver com erro).
3. Aparece **"Nota Fiscal enviada para a fila do RPA EACE."** O card mostra **Na fila** (com a posição), depois **Processando** e o resultado. O card se atualiza sozinho.

Situações do card:

- **✓ Sucesso** — nota anexada. Quando todas as notas do RI ficam em sucesso, o RI passa sozinho para **Faturamento RI Concluído**.
- **⚠ Atenção** — a nota já estava no portal.
- **✗ Erro** — o card diz se foi **"Falha no portal EACE (não é erro da Nota Fiscal)"** ou **"Erro de validação da Nota Fiscal"** e o motivo.
- **Cancelado** — não conta mais para o INEP.

Mensagens comuns:

- **"Escolha 1 PDF e 1 XML antes de disparar a RPA."**
- **"Esta Nota Fiscal já foi processada com sucesso e não pode ser reenviada."**
- **"RI sem "Num OSP"… não é possível disparar a RPA sem saber a OSP no portal."** — rode o **Sincronizador** do Relatório EACE.

## O que fazer quando a Nota Fiscal do RI já foi anexada à mão no portal EACE

Caminho: **Projeto › Equipamentos** › tela do RI › card da Nota Fiscal.

1. Clique em **Marcar como concluído manualmente** e confirme.
2. Aparece **"Nota Fiscal marcada como concluída manualmente."**

Não é possível marcar como manual uma nota em Sucesso, Atenção, Na fila ou Processando.

## O que fazer quando o financeiro mandou a Nota Fiscal do RI errada ou corrigida

Caminho: **Projeto › Equipamentos** › tela do RI › bloco **Notas Fiscais para anexar no portal EACE**.

Para cancelar o processamento da nota errada:

1. No card da nota errada (só se estiver **Pendente** ou com **Erro**), clique em **Cancelar**.
2. Preencha **Motivo do cancelamento** (ex.: "NF com valor errado, financeiro enviou a corrigida") e clique em **Confirmar cancelamento**.
3. Aparece **"Processamento cancelado — não conta mais para este INEP."**

Para enviar a nota corrigida que chegou por fora do e-mail:

1. Em **Novo processamento manual**, escolha a **Nota fiscal (PDF)** e o **XML**.
2. Clique em **Processar**. Aparece **"Processamento manual criado e enviado para a fila do RPA EACE."**

Mensagens comuns: **"Informe o motivo do cancelamento."** e **"Só é possível cancelar processamento Pendente ou com Erro…"**. Se o INEP estiver em "Processo Concluído" no MIP, só o Administrador pode fazer essas ações.

## Como registrar uma mensagem ou anexo no histórico do RI

Caminho: **Projeto › Equipamentos** › tela do RI › **Histórico de comunicação**.

1. Escreva em **Mensagem** e, se quiser, escolha um arquivo em **Anexo (opcional)**.
2. Clique em **Enviar**. Aparece **"Registro adicionado ao histórico do RI."**

O histórico mostra, do mais recente para o mais antigo, mensagens, anexos, e-mails com o financeiro, trocas de status e alterações de campos. Os documentos (PDF, XML, planilhas) podem ser baixados por ali. Se tentar enviar sem nada, aparece **"Escreva uma mensagem ou anexe um arquivo."**

## Como acompanhar a fila de envio de Notas Fiscais ao portal EACE

Caminho: **Projeto › Fila**.

A tela mostra a fila do robô que anexa as Notas Fiscais no portal EACE, do RI e do MIP (LOTE), e se atualiza sozinha a cada 10 segundos.

1. Use **INEP**, **Status** e **Data processamento** e clique em **Filtrar**. Por padrão aparecem só os itens **Em andamento (Na fila + Processando)**. Outras opções de **Status**: Na fila, Processando, Processado, Atenção (NF já estava no portal), Erro e Todos.
2. Clique em **Ver RI →** ou **Ver LOTE →** para ir ao item.
3. A parte **Envios do MIP (LOTE)** mostra os envios das notas dos LOTEs.

O botão **Modo TV** abre um painel da fila para deixar numa televisão (abre sem precisar entrar no sistema; copie o endereço da nova aba).

## Como acompanhar o processo MIP de um INEP

Caminho: **Projeto › MIP**.

A tela lista os INEPs do Relatório EACE (MIP) e os que estão em **Aguardando Validação EACE**, com o **Status (MIP)** e os valores de serviço dos três lados.

1. Filtre por busca (INEP, escola, município ou UF), **Estado**, **Município**, **Status (MIP)**, **Data inicial** e **Data final** e clique em **Filtrar**.
2. O quadro **Com divergência** mostra os INEPs em que o valor de serviço do IXC é diferente do Relatório EACE.
3. Clique na linha para ver os três lados; clique no INEP para abrir a tela do MIP do INEP.

Status (MIP): **Em Andamento MIP**, **Aguardando Validação EACE**, **Em Faturamento**, **Processo Concluído** e **Reprovado**.

Na tela do INEP (**Projeto › MIP** › INEP):

- O **Status (MIP)** pode ser trocado ali, a não ser que o INEP já esteja num LOTE (aí aparece **"O INEP está no LOTE ... — altere o status pela tela MIP (LOTE)."**). A partir de "Processo Concluído", só o Administrador altera.
- Com o Status (MIP) em **Aguardando Validação EACE**, é possível lançar ali **Equipamento (só valor de serviço)** e clicar em **Salvar** (**"Equipamento lançado."**).
- **Baixar Nota Fiscal** aparece quando a Nota Fiscal do MIP do INEP já foi sincronizada.

Outras ações na lista (Administrador e Analista): **Pausar** (o INEP fica fora da criação de LOTE), **Retomar** e **Retirar da lista** / **Retirar selecionados**.

## Como criar um LOTE no MIP

Caminho: **Projeto › MIP**.

Só entram no LOTE os INEPs em **Aguardando Validação EACE** com **Valor Total (IXC) igual ao Valor Total (EACE)** e que não estejam pausados.

1. Preencha **Estado** e **Município** (as datas são opcionais) e clique em **Filtrar**.
2. Clique em **Criar LOTE**. Na janela **Revisar INEPs do LOTE**, desmarque quem não deve entrar (use **Marcar todos** / **Desmarcar todos** ou busque pelo INEP).
3. Se um INEP precisa ter o valor dividido entre cidades, clique em **Ratear**, use **Adicionar parte** e informe a cidade e o valor de cada parte (a soma tem que ser igual ao valor do INEP; mínimo de 2 partes).
4. Clique em **Criar LOTE**. O sistema mostra a confirmação com o número de INEPs e abre **Projeto › MIP (LOTE)**. Os INEPs passam para **Em Andamento MIP**.

Para criar vários LOTEs de uma vez (1 por cidade): clique em **Criar LOTE em massa**, revise a lista em **Revisar LOTEs em massa**, desmarque o LOTE que não atende e clique em **Criar LOTE**.

Mensagens comuns:

- **"Informe Estado e Município para criar o LOTE."**
- **"Nenhum INEP elegível (Aguardando Validação EACE, com Valor Total IXC = EACE) para ..."** — confira os valores dos INEPs e o filtro.
- **"Nenhum INEP selecionado para o LOTE — marque ao menos 1 na lista."**
- **"Rateio do INEP ...: a soma das partes (R$ ...) tem que ser igual ao valor total do INEP (R$ ...)."**

## Como trabalhar com os LOTEs do MIP (planilhas, status, desfazer e reprovar)

Caminho: **Projeto › MIP (LOTE)**.

1. Filtre por **INEP**, **Estado**, **Município** e **Nota Fiscal** (Com/Sem Nota Fiscal) e clique em **Filtrar**. Os quadros de status no topo mostram o valor total de cada status.
2. Clique na linha do LOTE para ver os INEPs dele.
3. Ações de cada LOTE (Administrador e Analista):
   - **Baixar planilha** — planilha de faturamento de implantação do LOTE.
   - **Notas Fiscais (.zip/.rar)** — baixa as notas do LOTE, quando já recebidas. A marca **NF do financeiro** mostra quando a nota chegou do financeiro.
   - **Mudar status** — Em Andamento MIP, Em Faturamento ou Processo Concluído. Se vários LOTEs estiverem marcados, o status escolhido vale para todos os marcados (e para os INEPs deles).
   - **Desfazer LOTE** — só em "Em Andamento MIP"; os INEPs voltam para "Aguardando Validação EACE".
   - **Reprovar LOTE** (só Administrador, em "Processo Concluído") — informe o **Motivo da reprovação**. O valor sai dos relatórios de faturamento, as notas ficam guardadas no LOTE e os INEPs podem entrar num LOTE novo. **Desfazer reprovação** volta o LOTE para "Processo Concluído".
4. **Baixar Em Andamento (.zip)** — sem LOTE marcado, baixa as planilhas de todos os LOTEs em "Em Andamento MIP"; com LOTEs marcados, só as dos marcados.

Regras e mensagens: um LOTE em "Processo Concluído" só o Administrador altera; LOTE reprovado só volta por **Desfazer reprovação**. **"Nenhum LOTE em "Em Andamento MIP" para baixar."** aparece quando não há o que baixar.

## Como enviar a Nota Fiscal de um LOTE do MIP ao portal EACE

Caminho: **Projeto › MIP (LOTE)**.

1. Na linha do LOTE (com a Nota Fiscal já recebida), clique no botão **Enviar ao portal EACE**.
2. Leia a confirmação: a nota é anexada no card do município do pedido mais recente do portal EACE, só se o card estiver **Pendente** e o valor bater. Com rateio, todas as notas vão para a fila, uma de cada vez.
3. Clique em **Enviar ao portal**. A linha mostra **Na fila**, depois **Enviando ...%** e, no fim, **NF enviada em ...** ou **NF já estava no portal**.
4. Em caso de erro, o botão vira **Tentar de novo** e mostra o motivo.

Você pode acompanhar também em **Projeto › Fila**, parte **Envios do MIP (LOTE)**.

## Como conferir as Notas Fiscais do MIP no portal EACE

Caminho: **Projeto › Validação MIP (NF)**.

A tela mostra, por município, o **Valor** e o **Status** da Nota Fiscal no pedido do portal EACE (**● Pendente**, em análise ou **✓ Aprovado**) e o total.

1. Filtre por **Município** e status e clique em **Filtrar**.
2. Para ler o portal agora, informe (opcional) o **Nº do pedido** e clique em **Rodar agora**. Aparece **"Validação ... colocada na fila. A tela se atualiza sozinha quando terminar."**
3. O quadro **Última rotina** mostra quando foi a última leitura, a origem e o resultado. A leitura automática roda de hora em hora no horário indicado na tela.

Mensagens: **"Já existe uma validação em andamento - aguarde ela terminar."** e **"Nº do pedido inválido - informe só números (ex.: 506) ou deixe em branco."**

## Como acompanhar o faturamento das manutenções (BDO)

Caminho: **Projeto › BDO**.

A tela abre no Boletim mais recente. Para ver todos juntos, escolha **Todos os Boletins** no filtro **Boletim**.

Com um Boletim escolhido, o quadro **andamento** mostra as etapas do processo, na ordem:

1. **Planilha do Boletim**: municípios, INEPs e tipo (RE ou RI).
2. **Mês de referência**: o Administrador pode informar aqui mesmo, se estiver faltando.
3. **Pro rata do cliente**: o Administrador envia ou reenvia a planilha aqui mesmo.
4. **Divergências**: quantos INEPs têm status e quantos ainda estão pendentes. O link **Ver os pendentes** leva direto a eles.
5. **Portal EACE**: o status dos cards dos municípios no portal (Aprovado, Pendente).
6. **Medição**: número, data e quem gerou.

Cada etapa aparece verde quando está concluída, amarela quando precisa de atenção e cinza quando falta fazer. Ao lado ficam os totais para comparar: **Planilha do cliente**, **Total MEGA (sistema)**, **Portal EACE** e **Medição**.

Abaixo das etapas, **Por motivo** mostra quantos INEPs há em cada motivo de divergência e quantos estão **Sem valor no sistema**. Clique em um deles para ver só aqueles INEPs.

Como usar a tela:

- Filtre por **Boletim**, **INEP**, **UF**, **Município**, **Ativação de**, **Ativação até** e **Status** (inclui os motivos e **Sem valor no sistema**) e clique em **Filtrar**.
- Em **Agrupar**, escolha ver por INEP, por município ou por UF.
- Use **Mostrar valores da planilha** para ver os valores de serviços, créditos, descontos e descontos proporcionais do município. Eles ficam escondidos para o grid caber na tela.
- Clique em **Excel** para baixar as linhas com os filtros escolhidos.
- Clique em **Atualizar do portal EACE** para trazer o status, o Valor total a ser emitido e o arquivo da Nota Fiscal de cada município. A tela informa se o número de municípios da planilha confere com o número de cards no portal.

No agrupamento **Por INEP**, as colunas vêm em grupos:

- **Escola**: INEP, Município e UF.
- **Conferência**: Status e Valor faltando.
- **Sistema**: Data de ativação, Dias proporcionais, Valor assinatura e Valor proporcional.
- **Cliente (Pro rata)**: Ativado em, Desconto e Valor pago.
- **Planilha do município**: os valores da planilha FR.
- **Boletim**: número, tipo e situação do faturamento.

Cores: verde = confere, vermelho = diferente, amarelo = pendente de decisão.

Se não houver Boletim, aparece **"Nenhum Boletim importado"**: o Administrador importa a planilha em **Administrador › Relatório BDO**.

## Quando um INEP do BDO tem divergência

Só recebe **Status** o INEP que tem uma divergência de verdade. O motivo aparece embaixo do campo:

- **Sem data de ativação no sistema**: o INEP não tem data de ativação (ou não tem escola no sistema).
- **Data diferente da Pro rata**: o "Ativado em" do cliente é diferente da data de ativação do sistema.
- **Valor pago menor que o do sistema**: o cliente pagou menos que o Valor proporcional (mais de R$ 0,01 de diferença).
- **Ativado depois do mês do Boletim**: a ativação é depois do mês de referência e mesmo assim o INEP está no Boletim.
- **Ativado no mês e fora da Pro rata**: a ativação foi no mês de referência, mas o cliente não deu desconto (cobrou o mês cheio).

O INEP ativado antes do mês e fora da Pro rata não tem divergência: o cliente cobrou o mês cheio, que é o mesmo que o sistema calcula.

Enquanto a Pro rata do Boletim não for importada, não há com o que comparar a data e o valor pago: só aparecem os INEPs sem data de ativação e os ativados depois do mês.

## Como tratar as divergências do BDO (Aprovado ou Contestado)

Caminho: **Projeto › BDO** (agrupado por INEP).

As linhas pendentes ficam com o fundo amarelo claro.

1. Escolha **Aprovado** ou **Contestado** no **Status** da linha. Ou marque vários INEPs, escolha em **Alterar status para** e clique em **Aplicar**.
2. Escolheu errado? Escolha **Pendente** para desfazer.
3. Cada troca fica registrada (passe o mouse no campo para ver quem alterou e quando).

No INEP **Contestado** em que o cliente pagou menos, a coluna **Valor faltando** mostra o valor a cobrar em outro Boletim. O Visualizador não pode alterar o status.

## Como gerar a Medição dos Recebíveis do BDO

Caminho: **Projeto › BDO** › botão **Recebíveis**. O modal já abre com o Boletim escolhido na tela.

1. Escolha um ou mais **Boletins**.
2. Escolha a **Visão** e use **Retirar** nos municípios que não entram (use **Voltar todos** para desfazer).
3. Confira os totais. O valor de cada município é o Valor total do card dele no portal EACE.
4. Clique em **Gerar Medição (.xlsx)**. Com mais de um Boletim, vem um .zip com uma planilha por Boletim.

O card do EACE é do município inteiro, por isso o município entra com todos os INEPs do card. Com um período de ativação escolhido, o período só define quais municípios entram. O selo **"x no período"** mostra quantos INEPs do município estão dentro do período.

Se o Boletim já tem Medição, o modal avisa o número, a data, quem gerou e o valor. Gerar de novo mantém o mesmo número e substitui a anterior.

A Medição só é gerada quando o número de municípios da planilha bate com o número de cards no portal EACE. Se não bater, aparece **"Medição não gerada: ... Atualize do portal EACE na tela BDO (Boletim escolhido)."**

## Como enviar as NFs do BDO para o portal EACE

Caminho: **Projeto › BDO**, com o Boletim escolhido. Use a seção **NFs do financeiro no portal EACE**.

O financeiro devolve um **.zip** (ou .rar) com as NFs do Boletim: uma NF por município, de RE e de RI. Cada NF traz em "Informações complementares" o número do Boletim e o município, por exemplo "CODIGO DE LIBERACAO 3657 UF ITOBI/SP".

1. Clique em **Enviar NFs do financeiro (.zip)** e escolha o arquivo. Ele pode trazer as NFs do RE e do RI juntas: cada uma vai para o Boletim do código de liberação dela.
2. O sistema liga cada NF ao município do Boletim e confere o valor com o card do município no portal. A NF fica **Pronta** quando o município da NF e o valor do card concordam. Erros de digitação no nome do município são aceitos (ex.: "CHAPADA DA NATVIDADE").
3. As que não concordam ficam como **Divergente: decidir** ou **Sem município: decidir**, com a explicação. Exemplo: "A NF diz HEITORAI/GO, mas o valor é diferente do card de Heitoraí/GO. O valor bate com o card de Cândido Rodrigues/SP". Escolha o município certo na lista e clique em **Confirmar**, ou em **Descartar**.
4. Clique em **Colocar N prontas na fila**. O robô do portal EACE anexa cada NF no card do município, uma por vez, depois dos envios de RI e MIP.
5. Quando o robô confirma, a NF fica **Anexada** e o município recebe a baixa. O quadro de andamento mostra **NFs no portal: x de y municípios com NF**.

Bom saber:

- **Card que já tem NF no portal** (Aguardando aprovação, Aprovado): a NF fica como "Card já com NF no portal" e não vai para a fila.
- **Erro do robô** (valor diferente no portal, portal fora do ar): a NF mostra o motivo e o botão **Enviar de novo**.
- **Mesmo arquivo enviado de novo:** as NFs já enviadas ao portal ficam de fora, e as que ainda não foram são substituídas.
- **NF de Boletim não importado:** importe o Boletim em **Administrador › Relatório BDO** e envie o arquivo de novo.

## Como importar um Boletim do BDO e a Pro rata

Caminho: **Administrador › Relatório BDO** (só Administrador).

1. Em **Enviar arquivo**, escolha a planilha **.xlsx** (FR_XXXX), o **Tipo do Boletim** (RE ou RI) e o **Mês de referência**.
2. Clique em **Importar**. Aparece a confirmação com o número do Boletim, municípios e INEPs.
3. Envie a planilha Pro rata do cliente (colunas INEP, Ativado em, Dias Descontados e Valor). Pode ser pela coluna **Pro rata** da lista **Boletins importados** ou pelo quadro **andamento** do Boletim em **Projeto › BDO**. Reenviar substitui a anterior.
4. O mês de referência pode ser corrigido na própria lista.

Um Boletim já importado é recusado. Use **Ver no BDO** para abrir o Boletim em **Projeto › BDO**.

## Como atualizar a Planilha EACE usada pelo RI

Caminho: **Administrador › Relatório EACE (RI)** (só Administrador).

1. Em **Enviar arquivo** (ou **Substituir arquivo**), escolha o arquivo **.csv** com as colunas Projeto (INEP), Descrição do Item, Qtde Produto e Valor Unit UR.
2. Clique em **Importar**. Aparece **"Planilha EACE importada com sucesso."** O novo envio substitui o anterior.
3. Clique em **Sincronizar todas as RI** para atualizar o Relatório EACE de todos os RIs de uma vez (**"Sincronização em lote: ... INEP(s) atualizado(s)."**).

Erros comuns: **"Envie um arquivo .csv."**, **"Não foi possível ler o arquivo — verifique se a codificação é UTF-8."**, **"Arquivo vazio."** e **"Colunas obrigatórias ausentes: ..."**.

## Como atualizar o Relatório EACE do MIP e as Notas Fiscais do MIP

Caminho: **Administrador › Relatório EACE (MIP)** (só Administrador).

Relatório EACE (MIP):

1. Envie o arquivo **.xlsx** ("Base MIP.xlsx") com as colunas Projeto (INEP), Descrição do Item, Qtde Produto, Valor Unit UR, Data Emissão ACS, UF e CIDADE e clique em **Importar**.
2. Se já houver INEPs preenchidos, escolha **Sim, sobrepor** ou **Não, só os vazios**. O botão **Sincronizar todos os INEPs** refaz a sincronização.

Notas Fiscais (.zip/.rar):

1. Envie o arquivo **.zip** (recomendado) ou **.rar** com as Notas Fiscais do MIP devolvidas pelo financeiro e clique em **Importar**.
2. Clique em **Sincronizar Notas Fiscais dos INEPs**. Só são atualizados INEPs de LOTE em "Em Andamento MIP"; o download da nota fica na tela do INEP no MIP.

Arquivos **.rar** podem não ser lidos em alguns casos; prefira **.zip**.

## Como gerar o relatório Faturamento EACE Materiais (NOVO)

Caminho: **Administrador › Relatório** › card **Faturamento EACE Materiais (NOVO)** › **Abrir relatório** (só Administrador).

O relatório lista, uma linha por Nota Fiscal, as notas recebidas do financeiro com a data da NF no período, com o mesmo valor do relatório do financeiro.

1. Preencha **Data da NF - início** e **Data da NF - fim**.
2. Se quiser, informe **Hora início** e **Hora fim** (para separar dentro do mesmo dia pela hora de autorização da nota) e o **Processo** (**Todos**, **Clássico** ou **Especial**).
3. Clique em **Gerar relatório**. A tela mostra **INEP**, **NF**, **Data da NF**, **Processo**, **Valor**, **Nº OSP** e o **Total**.
4. Clique em **Exportar Excel** para baixar a planilha, ou em **Exportar Arquivos (.zip)** para baixar o PDF e o XML das notas, por INEP.

Regras:

- Quando o financeiro refatura um item (manda uma nota nova no lugar de outra), vale só a nota mais recente daquele item.
- Nota de processamento cancelado no RI não conta, e a mesma nota recebida duas vezes conta uma vez.
- Nota cancelada no financeiro continua contando **até alguém dar baixa** em **Administrador › NFs canceladas no financeiro**.
- O **Nº OSP** é só informativo e não muda o valor.

Mensagens: **"A Data início não pode ser depois da Data fim."**, **"No mesmo dia, a Hora início não pode ser depois da Hora fim."** e **"Nenhuma nota fiscal recebida do financeiro com data nesse período."**

## Como gerar o relatório Faturamento EACE Materiais (antigo)

Caminho: **Administrador › Relatório** › card **Faturamento EACE Materiais** › **Abrir relatório** (só Administrador).

1. Preencha **Data início** e **Data fim** e clique em **Gerar relatório**.
2. A tela lista os INEPs que entraram em "Aguardando validação EACE" no período, com lote, UF, município, escola, equipamentos, valor (**Equipamentos R$**), status, data de ativação, as notas fiscais de cada tipo de equipamento e os números de OSP.
3. Use **Exportar Excel** ou **Exportar Arquivos (.zip)**.

A baixa de NFs canceladas no financeiro vale para o relatório **(NOVO)**, não para este.

## Como dar baixa numa NF cancelada pelo financeiro

Caminho: **Administrador › NFs canceladas no financeiro** ou **Administrador › Relatório** › card **NFs canceladas no financeiro** › **Abrir lista** (só Administrador).

Quando o Módulo Financeiro cancela uma Nota Fiscal que já tinha enviado ao pós-venda, ele avisa o sistema sozinho e a nota aparece nesta lista com o status **Aguardando baixa**. O topo da tela mostra quantas notas estão aguardando baixa.

1. Abra a tela. Por padrão, o **Status** mostra **Aguardando baixa** (as outras opções são **Baixadas** e **Todas**).
2. Para achar uma nota, digite em **Buscar** o INEP, o nome da escola ou o número da NF e clique em **Filtrar**.
3. Confira os dados da linha: **INEP**, **Escola**, **Item**, **NF / Série**, **Chave de acesso**, **Valor**, **Cancelada em**, **Por** (quem cancelou no financeiro), **Motivo** e **E-mail financeiro** (número do e-mail na saída do financeiro). Clique no INEP para abrir o RI da escola, quando houver.
4. Clique em **Dar baixa**.
5. Na janela **Dar baixa na NF ...**, leia: "Confirma que a NF ... do INEP ... foi cancelada no financeiro? Depois da baixa ela deixa de contar no relatório Faturamento EACE Materiais (NOVO)." Clique em **Dar baixa** para confirmar (ou **Cancelar**).
6. Aparece **"Baixa dada na NF ... (INEP ...): ela deixa de contar no relatório Faturamento EACE Materiais (NOVO)."** A linha passa para **Baixada**, com **"Baixada por [nome] em [data e hora]"**.

Regras importantes:

- **A baixa NÃO cancela nada no sistema da EACE (portal do cliente).** Ela só tira a nota do faturamento no Gerenciador Pós Venda. Se a nota já estava anexada no portal EACE, o ajuste lá continua sendo feito por quem opera o portal.
- A baixa grava quem deu a baixa e quando. Se o INEP tem RI, o **Histórico de comunicação** do RI recebe a mensagem "Baixa da NF ... cancelada no financeiro (motivo: ...): deixa de contar no faturamento."
- Não há botão para desfazer a baixa na tela. Confira a nota antes de confirmar.
- Se a nota já tinha baixa, aparece **"A NF ... (INEP ...) já estava baixada."** e nada muda.
- Se o financeiro reenviar o aviso da mesma nota, a baixa já dada é mantida.
- Para ver as baixas já feitas, escolha **Baixadas** (ou **Todas**) em **Status** e clique em **Filtrar**.
- **"Nenhuma NF cancelada no financeiro com esse filtro."** — não há notas para o filtro escolhido.

## O que muda no relatório de faturamento depois da baixa

Caminho do relatório: **Administrador › Relatório** › **Faturamento EACE Materiais (NOVO)** › **Abrir relatório**.

- **Antes da baixa**: a nota cancelada no financeiro **continua aparecendo** no relatório Faturamento EACE Materiais (NOVO) e entra no **Total**, mesmo já estando na lista **Administrador › NFs canceladas no financeiro** como "Aguardando baixa".
- **Depois da baixa**: a nota **deixa de aparecer** no relatório (na tela, no **Exportar Excel** e no **Exportar Arquivos (.zip)**) e o **Total** do período diminui o valor dela.
- O sistema reconhece a nota pela **chave de acesso**; quando a chave não está disponível, pelo **número da NF e o INEP**.
- O relatório é montado na hora: se você já tinha gerado ou exportado o relatório antes da baixa, clique em **Gerar relatório** de novo (e exporte de novo) para ver os valores atualizados.
- Se o financeiro emitir uma nota nova no lugar da cancelada, a nota nova entra normalmente no relatório quando for recebida.
- A baixa não altera o relatório **Faturamento EACE Materiais** (antigo), nem nada no portal EACE.

## Como gerenciar os usuários (perfil e acesso)

Caminho: **Administrador › Usuários** (só Administrador).

1. Na lista, veja **Usuário**, **E-mail**, **Perfil** e **Acesso**.
2. Para mudar o perfil, use **Ação de Perfil** e escolha **Administrador**, **Analista** ou **Visualizador**. Aparece **"Perfil de ... alterado para ..."**.
3. Para liberar ou bloquear os dados, use **Ação de Acesso**: **Ligar** ou **Desligar**. Aparece **"Acesso de ... alterado para ..."**.

Usuário novo entra como Analista e com o acesso **Desligado** até um Administrador ligar. Você não pode trocar o próprio perfil nem ligar/desligar o próprio acesso (**"Você não pode trocar o próprio perfil por esta tela."**).

## Como exportar ou importar um backup dos dados

Caminho: **Administrador › Backup** (só Administrador).

Exportar:

1. Em **Exportar backup**, clique em **Exportar e baixar**. O arquivo **.sql.gz** com todos os dados é baixado no seu computador.

Importar (substitui TODOS os dados do ambiente — use com muito cuidado):

1. Em **Importar backup**, escolha o arquivo **.sql** ou **.sql.gz**.
2. Marque **"Estou ciente de que isso apaga todos os dados atuais deste ambiente e os substitui pelo arquivo enviado."**
3. Digite exatamente **IMPORTAR E APAGAR TUDO**.
4. Clique em **Importar e substituir tudo** e confirme.

Antes de cada importação o sistema grava um **backup de segurança**, que aparece em **Backups de segurança** com o botão **Baixar**.

Mensagens: **"Selecione um arquivo de backup (.sql ou .sql.gz)."**, **"Arquivo inválido — envie um .sql ou .sql.gz."** e **"Importação cancelada — marque a confirmação e digite a frase exatamente como pedido."**

## Como criar logins (endereços) ou atendimentos em massa no IXC

Caminho: **Automações IXC › Login (Endereços)** ou **Automações IXC › Atendimentos** (só Administrador).

1. Clique em **Baixar modelo** e preencha a planilha modelo.
2. Em **Upload da planilha**, escolha o arquivo **.xlsx** num dos processamentos. Aparece **"Planilha enviada — Processamento ... pronto para iniciar."**
3. Clique em **Start**. A coluna **Progresso** mostra o andamento.
4. Para interromper, clique em **Stop** (só quem iniciou pode parar).
5. Quando terminar, baixe a planilha de saída em **Histórico de execuções** (botão **Baixar**), que mostra quantas linhas deram certo e quantas deram erro.

Mensagens comuns:

- **"Processamento ... está em andamento — espere terminar (ou pare) antes de enviar outra planilha."**
- **"Não foi possível importar a planilha (Processamento ...): ..."** — com o motivo, por exemplo **"Envie um arquivo .xlsx."**, **"Colunas obrigatórias ausentes: ..."** ou **"Corrija a planilha antes de enviar (nenhuma linha foi enviada ao IXC): ..."**.

## Como consultar os painéis (Dashboard)

Caminho: **Dashboard** (Administrador e Analista).

- **Faturamento RI**: **Valor Total do Projeto**, **Valor já Faturado**, quanto falta para a meta, **Faturamento por status do RI**, **Faturado por Estado** e **Faturado por Município**. Clique num estado para filtrar; use **Ver todos os estados** para voltar.
- **Faturamento MIP**: **Valor Total do Projeto**, **Processo Concluído**, **Faturamento por status do MIP** e **Concluído por Estado** / **Por Município**.
- **Equipamentos**: **Kits Programados**, **Kits Instalados**, **Nobreaks Programados**, **Kits Instalados por Estado**, **Kits por Equipamento** e **Equipamentos Complementares**. Clique num kit ou estado para filtrar.
- **Relatórios**: ainda sem conteúdo.

## O que fazer quando aparece "INEP em "Processo Concluído" (MIP) — só o Administrador pode alterar."

Caminho: qualquer tela do RI em **Projeto › Equipamentos**.

Quando o INEP chega a **Processo Concluído** no MIP, o RI fica travado para o Analista: status, responsável, Lado IXC, Relatório EACE e processamentos de Nota Fiscal. Só o Administrador pode alterar. Peça a um Administrador para fazer a correção ou para trocar o status do LOTE em **Projeto › MIP (LOTE)**.

## Perguntas frequentes

**Não vejo o menu Administrador. Por quê?**
Esse menu (e Automações IXC) aparece só para o perfil Administrador. Veja seu perfil no rodapé do menu lateral.

**Entrei, mas a tela diz "Aguardando liberação do Administrador".**
Seu acesso aos dados ainda está desligado. Peça a um Administrador para ligar em **Administrador › Usuários**.

**Por que não aparece o botão para enviar o e-mail ao financeiro?**
Ele só aparece com o RI em **Envio de Email para faturamento**. Passe o RI por "Em Andamento" e resolva as divergências antes.

**Qual CFOP devo escolher no envio ao financeiro?**
O sistema oferece **5117 – antigo (entrega futura)** (padrão) e **5102-004 – novo (venda)**. Siga a orientação do financeiro; use **Baixar planilha** para conferir antes de enviar.

**O e-mail foi enviado com dado errado. Posso editar?**
Não. Depois de enviado o e-mail não pode ser editado. Registre a correção no **Histórico de comunicação** e combine com o financeiro.

**O financeiro respondeu, mas o RI não mudou para "Resposta Financeiro".**
O sistema só avança o status se o RI estava em "Aguardando financeiro". A resposta continua registrada no Histórico de comunicação. O Administrador também pode usar **Forçar Resposta Financeiro**.

**A nota cancelada no financeiro ainda aparece no relatório (NOVO). É erro?**
Não. Ela só sai depois que um Administrador clica em **Dar baixa** em **Administrador › NFs canceladas no financeiro**. Depois, gere o relatório de novo.

**Dar baixa cancela a nota no portal EACE?**
Não. A baixa só tira a nota do faturamento do Gerenciador Pós Venda. Qualquer ajuste no portal da EACE continua sendo feito por quem opera lá.

**Dei baixa na nota errada. Como desfaço?**
A tela não tem botão para desfazer a baixa. Fale com o responsável pelo sistema.

**Por que um INEP não entrou no LOTE do MIP?**
Só entram INEPs em "Aguardando Validação EACE", com Valor Total (IXC) igual ao Valor Total (EACE) e que não estejam pausados.

**A Nota Fiscal está "Na fila" há muito tempo.**
O robô anexa uma nota por INEP de cada vez. Veja a posição em **Projeto › Fila**. Se der erro, o card mostra o motivo e o botão **Tentar novamente**.

**O Visualizador pode alterar alguma coisa?**
Não. Ele só consulta **Projeto › Equipamentos** e **Projeto › MIP**, sem valores em R$.
