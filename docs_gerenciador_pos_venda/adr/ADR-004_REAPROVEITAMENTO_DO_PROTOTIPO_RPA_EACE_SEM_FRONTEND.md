# ADR-004 - Reaproveitamento do protótipo RPA EACE (`doc/auto_eace_nf_servidor`), sem a camada de frontend

## Status
Aprovado. Gatilho de disparo definido em 2026-09-03 (RN-056) — ver
"Decisão", item 6 — e validação dos dados da NF contra o portal também
definida no mesmo dia (RN-057, item 8). Fase 1 da `FEAT-033` já
implementada e validada contra o portal real, exceto o upload em si — ver
"Pendências" para os pontos que ainda restam.

## Contexto
`architecture.md` já registrava, na seção "Fora do escopo da v1 (gap — Hub
de Integrações...)", que a Versão 2 (04/09/2026) incluiria uma "RPA de
anexo dos arquivos no portal EACE", substituindo a marcação manual hoje
feita pela `FEAT-010`: o usuário sobe NF (PDF) e XML no portal EACE por
fora do sistema e depois clica "anexo feito no EACE" para avançar o RI de
"Resposta Financeiro" para "Aguardando validação EACE" (RN-001).

Existe, fora do controle de versão deste repositório, uma pasta
`doc/auto_eace_nf_servidor/` com um protótipo funcional em Python/
Playwright que já automatiza esse mesmo portal (login, localização da OSP,
upload de PDF+XML por INEP/tipo KIT ou NOBREAK, clique em "Enviar notas").
O protótipo tem duas camadas: o núcleo de automação (`src/`) e um
dashboard web próprio (`web/`, FastAPI + frontend estático) que existe só
para operar o RPA manualmente fora do `Sistema_posvenda` (configurar
credenciais, subir arquivos, disparar execução, acompanhar log em tempo
real). Há também uma cópia antiga duplicada em `ProjetoFinal/`.

Em 2026-09-03 o usuário pediu, via Orquestrador, para reaproveitar esse
protótipo dentro do `Sistema_posvenda`, descartando a parte de frontend e
rodando a automação apenas em background.

## Decisão
1. **Reaproveitar o núcleo do protótipo** (`login.py`, `dashboard.py` —
   navegação no portal —, `extrair_dados_pdf.py` — extração de dados da
   NF, RN-057, com escopo reduzido: só a leitura do PDF, sem a planilha
   de controle/varredura de pasta em lote do protótipo, que não se aplica
   ao fluxo por log da RN-056 —, `config.py`), adaptado para um novo
   submódulo `apps/integracoes/eace/`, ao lado do já existente
   `apps/integracoes/ad/`. `arquivos.py`/`logger.py` do protótipo não
   foram portados (`logger.py` foi substituído pelo `logging` padrão,
   mesmo usado no resto do projeto, no lugar do `loguru` exclusivo do
   protótipo); `rpa.py` é novo (não existia no protótipo), orquestra as
   chamadas e concentra a extração/validação de erros da RN-057.
2. **Descartar a camada de frontend do protótipo** — o dashboard FastAPI
   (`web/app.py` e `web/static/`) e a cópia duplicada `ProjetoFinal/` não
   são portados; a automação passa a existir só como processo de backend
   do próprio sistema, sem API, tela ou dashboard próprios.
3. **Rodar apenas em background** — navegador Chromium headless (já era o
   padrão do protótipo) e sem qualquer interação manual durante a
   execução (sem prompt de terminal, sem tela de acompanhamento própria);
   log de execução segue o padrão já usado no projeto.
4. **Origem dos dados muda de arquivo/pasta manual para o banco do
   sistema** — em vez da estrutura manual `EACE/<INEP>/<KIT|NOBREAK>/
   *.pdf,*.xml` e do arquivo `input/osp.txt` do protótipo, a automação
   passa a ler os documentos já salvos (`Documento`, PDF/XML por INEP) e o
   número da OSP já modelado em `RiItemRelatorioEace.num_osp`.
5. **Credenciais do portal EACE via `.env`** deste repositório
   (`EACE_URL`/`EACE_USUARIO`/`EACE_SENHA`, mesmos nomes do protótipo),
   nunca em banco SQLite local nem em documentação versionada (CLAUDE.md
   §6).
6. **Gatilho de disparo (RN-056, 2026-09-03)** — a resposta do financeiro
   (RN-016) que traz N PDF/N XML gera, automaticamente, 1 log por Nota
   Fiscal esperada; cada log lista os XML e os PDF daquela resposta para
   o usuário escolher manualmente o par certo e disparar a RPA a partir
   do próprio log (1 disparo = 1 PDF + 1 XML). A criação dos logs é
   automática; a execução da RPA em si é sempre manual, por log.
7. **Entrega em 2 fases, nessa ordem, a pedido do usuário** — Fase 1:
   núcleo da automação (item 1) funcional e validado via terminal, sem
   nenhum model de log nem tela. Fase 2: o mecanismo de log/seleção do
   item 6, com tela própria. `FEAT-033` (`checklist.md`) detalha os
   critérios de aceite de cada fase.
8. **Validação dos dados da NF contra o portal antes do upload (RN-057,
   2026-09-03)** — o núcleo extrai INEP/Produto/Valor de dentro do PDF
   (`pdfplumber`, nova dependência) e bloqueia o disparo se o PDF não
   tiver esses dados, se o INEP do PDF não bater com o INEP do log, ou
   se o Valor do PDF não bater com o valor exibido na linha do portal.
   Os dados extraídos ficam sempre disponíveis (`ResultadoRpaEace.
   dados_pdf`), inclusive em erro, para a Fase 2 exibir no log.

## Consequências positivas
- Reaproveita a parte mais custosa de acertar (navegação real num portal
  SPA em Bubble.io, sem API pública), já validada no protótipo.
- Elimina a etapa manual de organizar PDF/XML em pastas — a automação usa
  dados que o sistema já guarda.
- Fecha metade do gap "Hub de Integrações v2" já previsto em
  `architecture.md`.

## Consequências negativas / riscos
- Portal EACE é uma SPA sem API pública (Bubble.io) — a automação
  depende de seletores de tela que podem quebrar se o portal mudar de
  layout, sem aviso prévio.
- Execução com navegador real (Chromium/Playwright) é mais pesada que uma
  automação via API — falta decidir onde/como esse processo roda em
  produção (mesmo container do `web` ou serviço dedicado), decisão
  técnica do DevOps ainda não tomada.
- `doc/auto_eace_nf_servidor/` está fora do controle de versão hoje; o
  código só passa a existir de forma rastreável quando portado para
  `apps/integracoes/eace/`.
- Esta decisão cobre só a metade "anexo de arquivos" do gap de v2 — a
  outra metade ("RPA de download do relatório EACE") segue em aberto, sem
  decisão própria.

## Alternativas consideradas
- **Reescrever a automação do zero dentro de `apps/integracoes`**, sem
  aproveitar o protótipo — descartada: o protótipo já resolve a parte
  mais frágil (navegação real no portal), refazer do zero jogaria fora
  trabalho já validado.
- **Manter o dashboard próprio do protótipo (FastAPI)** como ferramenta
  separada, só integrando os dados — descartada pelo usuário, que pediu
  explicitamente para descartar a parte de frontend e rodar só em
  background.

## Pendências
- ~~Gatilho de execução ainda não definido pelo usuário~~ — definido em
  2026-09-03 (RN-056, ver "Decisão" item 6): log por Nota Fiscal com
  seleção manual de PDF/XML, disparo por log.
- ~~Se a conclusão dos logs avança o status automaticamente~~ — definido
  em 2026-09-03: RI avança para "Aguardando validação EACE" só quando
  **todos** os logs do RI estiverem "Sucesso"; 1 "Erro" mantém o status
  atual (RN-056). Agregação "todos os logs" e permanência do botão manual
  da `FEAT-010` como alternativa são interpretação do Orquestrador
  (CLAUDE.md §9), ainda sujeita a confirmação do usuário.
- Onde/como o processo roda em produção (mesmo container do `web` ou
  serviço dedicado com Chromium) — decisão técnica do DevOps, ainda não
  tomada; agora inclui também instalar `pdfplumber` (RN-057) na imagem,
  além do Chromium/Playwright.
- Escopo do "RPA de download do relatório EACE" (outra metade do gap v2)
  não foi endereçado por esta decisão.
- ~~Migração do código de `doc/auto_eace_nf_servidor/` para
  `apps/integracoes/eace/` ainda não iniciada~~ — feita em 2026-09-03
  pelo Dev (`config.py`, `login.py`, `dashboard.py`,
  `extrair_dados_pdf.py`, `rpa.py`); comando de terminal
  `eace_anexar_nota_fiscal` (`apps/ri/management/commands/`, já que
  `apps.integracoes` ainda não é um app Django instalado).
- **Falta só 1 teste de upload real para fechar a Fase 1 por completo**
  — login, navegação, extração de linha, extração/validação dos dados do
  PDF (RN-057), detecção de OSP inexistente e de documento já enviado
  (RN-056) já foram validados contra o portal real (`eace.org.br`,
  2026-09-03); falta um par PDF/XML correto de um INEP genuinamente
  pendente para validar o clique de upload em si — o único par disponível
  (INEP 35083938) já tinha sido enviado antes de começar os testes.
- **Confirmado contra o portal real que "credenciais inválidas" não é
  separável de uma falha genérica de login** — ao testar com senha
  errada, o portal não exibe nenhuma mensagem de erro capturável (nem
  como texto, nem como elemento visível); o motivo `login` continua
  genérico de propósito, para não gerar diagnóstico incorreto.
