# Lixo — Mapa de Exclusão da Cópia (Gerenciador Pós-Venda)
_Última atualização: 2026-08-20_

> **O que é este arquivo:** um checklist de tudo que existe hoje em
> `modulo-posVenda` e que **não deve ir para o novo sistema** (ou, se for
> copiado por estar junto de algo que fica, deve ser apagado de lá depois).
> Base: `architecture.md` (seção "Módulos e Responsabilidades") e
> `requisitos.md` (bloco 0 e ITEM 13) — não é uma opinião nova, é a mesma
> decisão já registrada, só organizada por arquivo/pasta real do repositório
> para servir de guia de limpeza.
>
> **O que este arquivo NÃO autoriza:** apagar nada em `modulo-posVenda`
> agora. Este repositório continua em produção e intacto — a decisão de não
> tocar em `docs/` e no código daqui já está fechada em `requisitos.md`
> ITEM 13. A exclusão real acontece em dois momentos possíveis:
> 1. **No momento da cópia** — ao criar o repositório novo, simplesmente não
>    copiar o que está listado aqui como "não entra na cópia";
> 2. **Depois da v1 (ou v2/v3) validada** — se algo foi copiado "de carona"
>    (por estar no mesmo arquivo/app de algo que fica) e continua sem uso no
>    sistema novo, apagar **do repositório novo**, nunca deste.

---

## 1. Fica (referência — não é lixo)

O que a `architecture.md` já define como reaproveitado como código. Listado
aqui só para não haver ambiguidade na hora de separar o resto.

- `apps/escolas/models.py` — **somente a classe `Escola`** (campos `inep`,
  `kit_inicial`, `velocidade_dl_minima`).
- `apps/auditoria/models.py` — **somente a classe `LoginAuditoria`**, como
  base para o Dev estender (ou não) para auditoria de campo/status do INEP.
- `apps/core/models.py` — **somente `User`/`UserManager`** (autenticação) e o
  mecanismo de grupos do Django (`Group`) usado por
  `apps/core/templatetags/auth_extras.py` (`has_group`) e pelo menu de
  `apps/core/templates/core/base.html`.
- `apps/core/templates/core/base.html` e `login.html` — casca visual e tela
  de login.
- `apps/integracoes/email/sincronizar_respostas_email_cotacao.py` — não o
  arquivo em si (importa `apps.leads`/`apps.clientes`), mas o **padrão**
  (polling IMAP a cada ~5 min) a replicar para a caixa
  `posvendas@megainfraestrutura.com.br`.

## 2. Adiado, não é lixo (reaproveitável na v3)

- `apps/integracoes/ixc/client.py` e `apps/integracoes/ixc/services/*` —
  citado em `architecture.md` como reaproveitável quando a integração com o
  IXC (ITEM 3) voltar ao escopo, na v3 (10/09/2026). Não copiar agora; não
  apagar como lixo — revisitar nessa data.

---

## 3. Lixo confirmado — apps inteiros

Não fazem parte do recorte "Faturamento EACE por INEP" (só RI, v1). Ligados
ao sistema atual de Lastmile/cotação/IXC.

- **`apps/leads`** — `Lead`, `LeadEmpresa`, `LeadEndereco`, `AcessoSetor`,
  telas de Lastmile (`lastmile_views.py`, `enderecos_lastmile.html`).
- **`apps/partners`** — `Partner`, `PartnerPlan`, `Proposal`,
  `ProposalMotivoInviavel` (parceiros de instalação Lastmile).
- **`apps/clientes`** — `Cliente`, `Endereco`, `HistoricoSincronizacao`,
  `LogAlteracaoIXC`, `ClienteExcluido`, `EnderecoExcluido` (sync com IXC).
- **`apps/backoffice`** — hoje sem models próprios; views/serviços de apoio
  ao backoffice do Lastmile.
- **`apps/integracoes_api`** — API REST que expõe `Cliente`/`Endereco`/
  `Partner`/`Proposal` para integrações externas do sistema atual.
- **`apps/integracoes/google`** (`APIGoogle_BuscaFornecedores.py`,
  `buscaParceiro.py`) — busca de fornecedores/parceiros, fluxo de parceiros
  do Lastmile.
- **`apps/integracoes/dashboard_eace`** — cliente da API do **DashboardEACE**.
  Confirmado em `requisitos.md` (bloco 0): é um **portal diferente** do
  sistema novo, não a mesma integração.
- **`apps/core_admin`** — telas administrativas do sistema atual:
  `import_services.py` (import de leads por planilha), `quotes_views.py`
  (cotações), `escola_email_views.py` (e-mail a partir da tela de
  Escola/RE/RI/Mapa Calor — RN-042, fluxo do Lastmile, não o fluxo
  pós-venda↔financeiro do sistema novo — mas serve de referência do padrão
  de envio SMTP com `EmailMessage`/`get_connection`), `TabelaAcessoBanco`/
  `AcessoBancoDados` (ADR-028/030 — permissão granular por setor individual,
  mais fina do que os 2 perfis Administrador/Analista do sistema novo).

## 4. Lixo confirmado — dentro de apps que ficam (recorte parcial)

O app fica, mas só uma parte do conteúdo. Sinalizar no código-fonte da cópia
qual trecho sai.

- **`apps/escolas/models.py`** — sai tudo, exceto `Escola`: `ProcessoRedeBase`,
  `RedeExterna`, `RedeInterna`, `MapaCalor`, `TargetRedeExterna`, `Processo`,
  `Setor`, `SetorStatus`, `Campo`, `CampoObrigatoriedadeTransicao`,
  `SetorEscopo`, `CampoValor`, `CotacaoParceiro` — tudo específico do
  Lastmile (RN-025 e correlatas).
- **`apps/auditoria/models.py`** — sai tudo, exceto `LoginAuditoria`:
  `RestoreBackupAuditoria`, `CotacaoStatusAuditoria`,
  `RegistroHistoricoAuditoria`, `EmailCotacaoRespostaSyncAuditoria`,
  `EmailCotacaoRespostaImportacaoAuditoria`, `IntegrationAuditAuditoria`,
  `IntegrationAuditItemAuditoria`, `DesativacaoAtendimentoIXCAuditoria`,
  `CadastroClienteIXCAuditoria`, `EdicaoLoginIXCAuditoria`,
  `EdicaoAtendimentoIXCAuditoria`, `HistoricoSincronizacaoAuditoria`,
  `LogAlteracaoIXCAuditoria` — tudo espelha auditoria de IXC/cotação.
- **`apps/core/models.py`** — sai tudo, exceto `User`/`UserManager`:
  `RegistroHistorico`, `EmailCotacaoRespostaSync`,
  `EmailCotacaoRespostaImportacao`, `EmailEscolaRespostaImportacao`,
  `IntegrationAudit`, `IntegrationAuditItem`, `AutomacaoMenu`,
  `RestoreBackupAuditoria`, `CotacaoStatusAuditoria`.
- **`apps/core/` (arquivos auxiliares)** — sai: `admin_integration_exports.py`,
  `automacoes_registry.py`, `email_tracking.py`, `integration_audit.py`,
  `middleware.py` (guarda upload de restauração de backup — específico do
  sistema atual).
- **`apps/core/templates/core/`** — sai tudo, exceto `base.html`/`login.html`:
  `gestao_home.html`, `gestao_log_integracao_detail.html`,
  `gestao_logs_integracoes.html`, `gestao_relatorio_cotacao_endereco.html`,
  `gestao_relatorio_login_usuario.html`, `gestao_relatorio_proposta_status.html`,
  `gestao_relatorio_proposta_status_real.html`,
  `gestao_relatorio_status_cliente.html`, `home.html`, `minhas_cotacoes.html`,
  `timeline_global.html`, `docs_index.html`.

---

## 5. Lixo confirmado — scripts, ferramentas e infraestrutura de operação

Ligados ao ambiente/negócio deste repositório, não ao sistema novo (que nasce
com repositório e banco próprios).

- `scripts/integracoes/` inteiro — `ixc_*.py` (client, exportação, faxina,
  sync de clientes, finalização de OS), `importar_leads_planilha.py`,
  `sincronizar_respostas_email_cotacao.py`, `debug_primeira_os_ixc.py`,
  `backup_manual.py`.
- `scripts/ai_usage_report.py`, `scripts/verificar_repositorio.py`.
- `ops/` inteiro — `setup_speed.py`, `backup_manual.py`,
  `migrar_credenciais_mysql_legado.sql`, `.tmp_prod_apply.sh`,
  `.tmp_prod_fastvalidate.sh`.
- Raiz do repositório: `buca_ID_IXC.csv`, `servidorEACE.md`,
  `backup_diario.sh`, `deploy_servidor`, `uritemplate.py`.
- `.env`/`.env.example` — recriar do zero no repositório novo, com as
  credenciais do sistema novo; nunca copiar valores reais deste.

## 6. Lixo confirmado — dados e artefatos

Dados operacionais deste sistema, sem relação com o Gerenciador Pós-Venda.

- `historicos_anexos/` — anexos de histórico do Lastmile.
- `media/backups/`, `media/historicos_anexos/`, `media/integration_logs/`.
- `staticfiles/` — build de estático do sistema atual (gerado, não fonte).
- `static/` — avaliar na cópia: ícones/CSS genéricos podem servir de base
  visual (ligado ao item "frontend" que fica), mas qualquer asset com
  marca/texto do sistema atual sai.

---

## 7. Aguardando decisão do Dev (não classificar como lixo ainda)

Depende de decisão técnica na hora de implementar (CLAUDE.md §9 — decisão
reversível e de baixo risco, mas melhor não presumir aqui):

- `apps/integracoes/ad/ad_sync.py` — sincroniza e-mail de usuário via Active
  Directory. O sistema novo tem cadastro de usuário manual (Administrador
  cria/edita/desativa, ITEM 13); não está definido se haverá integração com
  AD. Se não houver, sai; se houver, fica.
- `apps/core/models.RegistroHistorico` — pode servir de base genérica para o
  mecanismo de auditoria de campo/status do RN-001/ITEM 10, em vez de criar
  um log específico do zero. Decisão do Dev na hora de codar (ver ITEM 10).
- `apps/core_admin/models.ConfiguracaoEmailEnvio` — pode servir de referência
  de como guardar a configuração SMTP da caixa própria do financeiro
  (`posvendas@megainfraestrutura.com.br`), mesmo que o model em si não seja
  copiado literalmente.

---

## 8. Fora deste arquivo — não tocar

- **`docs/` deste repositório** (`ARCHITECTURE.md`, `BACKLOG.md`,
  `BACKLOG_ARCHIVE.md`, `business_rules.md`, `CURRENT_STATUS.md`,
  `DOCUMENTATION_INDEX.md`, `PRODUCT_BRIEF.md`, `adr/`, `diagrams/`,
  `modules/`, `devops/`) — documenta o sistema atual, que continua em
  produção. Fica só de consulta; a decisão de apagar (se um dia acontecer) é
  do usuário, ao final do projeto novo, e nunca automática (`requisitos.md`
  ITEM 13).
- **`requisitos.md`** e todo o conteúdo de `docs_gerenciador_pos_venda/` —
  são a documentação do sistema novo, não candidatos a exclusão.

## 9. Regra de segurança

Antes de apagar qualquer item marcado aqui **no repositório novo**:

1. confirmar que nenhum import cruzado ficou apontando para o que foi
   removido (`grep` por `apps.leads`, `apps.partners`, `apps.clientes`,
   `apps.backoffice`, `apps.integracoes_api`, `apps.integracoes.google`,
   `apps.integracoes.dashboard_eace` no código copiado);
2. confirmar que a versão então vigente (v1, v2 ou v3) não passou a depender
   de algo listado na seção 7;
3. rodar a suíte de testes do sistema novo depois da remoção, não antes.

## Histórico de Alterações
| Data | Alteração |
|---|---|
| 2026-08-20 | Criação do documento — primeiro levantamento do que não faz parte do recorte v1/v2/v3, organizado por app, por trecho de model/template e por artefato de operação |
