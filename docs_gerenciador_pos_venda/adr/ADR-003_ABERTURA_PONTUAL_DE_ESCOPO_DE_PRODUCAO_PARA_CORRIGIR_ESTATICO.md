# ADR-003 - Abertura pontual de escopo de produção para corrigir estático

## Status
`Aprovado` (escopo restrito — não é abertura geral de produção)

## Contexto
`architecture.md` ("Banco de Dados") já registrava que produção está fora do
escopo atual do DevOps e que construir o deploy de produção "continua
exigindo pedido explícito do usuário quando chegar a hora". Em 2026-08-28 o
usuário reportou logo quebrada num servidor real (`192.168.90.109`, pasta
`/home/Sistem_PosVenda`) e, ao longo do atendimento (Dev → DevOps →
Orquestrador), confirmou que esse servidor é **produção**, não homologação
como vinha sendo tratado nos registros do dia (ver `checklist.md`,
FEAT-012).

Diagnóstico já confirmado por DevOps: o servidor roda `runserver` com
`DEBUG=False`, que não serve arquivo estático sozinho — mesma causa raiz já
resolvida para homologação via `docker-compose.hml.yml` + Nginx
(`staticfiles_hml`/`media_hml` populados por `collectstatic`), validado de
ponta a ponta neste repositório.

Não há, até esta data, `docker-compose.prod.yml`, branch de produção, pipeline
de CI/CD de produção nem segregação de secrets entre homologação e produção
— o mandato de DevOps continua sendo "ESCOPO — HOMOLOGAÇÃO APENAS"
(`.claude/agents/devops.md`).

## Decisão
Autorizar o DevOps a aplicar, **somente neste servidor e somente para
resolver a falha de estático**, o mesmo stopgap já validado para
homologação: subir `docker-compose.hml.yml` (Nginx servindo `/static` e
`/media` dos volumes nomeados, populados por `collectstatic`) nesse
servidor.

Esta decisão **não abre** mandato para:
- criar `docker-compose.prod.yml`, branch ou pipeline de produção formal;
- migrar outros aspectos do servidor além do necessário para servir
  estático corretamente;
- qualquer operação destrutiva.

Condições obrigatórias (não negociáveis, fazem parte desta autorização):
1. Backup do banco MySQL do servidor real antes de qualquer `docker compose
   up`/`migrate` nele.
2. Reaproveitar o volume de dados existente do MySQL desse servidor — nunca
   subir um volume novo vazio no lugar dele.
3. Confirmar que `/home/Sistem_PosVenda` é checkout git com `origin`
   correto antes de rodar `scripts/deploy_homolog.sh`; se não for, aplicar
   os comandos manualmente, pulando o `git fetch`/`reset --hard`.
4. Nenhum comando destrutivo (`docker compose down -v`, remoção de volume,
   `DROP DATABASE`).
5. Registrar no `checklist.md` (FEAT-012) o resultado real da execução.

## Consequências positivas
- Corrige a falha visível para os usuários reais do sistema sem esperar a
  construção de um ambiente de produção formal.
- Reaproveita infraestrutura já criada e validada para homologação, sem
  trabalho duplicado.

## Consequências negativas / riscos
- Produção passa a rodar a partir do compose e (presumivelmente) da branch
  nomeados "homolog" — mistura de nomenclatura entre os dois ambientes, risco
  de confusão futura sobre qual ambiente é qual.
- Produção continua sem pipeline de CI/CD dedicado, sem secrets próprios e
  sem segregação formal em relação à homologação.
- Enquanto isso não for resolvido, um deploy futuro na branch `homolog`
  pode impactar produção sem um processo de aprovação equivalente ao de um
  ambiente de produção formal.

## Alternativas consideradas
- **Construir `docker-compose.prod.yml` e pipeline de produção completos
  agora** — descartado nesta rodada porque o pedido do usuário foi
  específico e urgente (logo quebrada), não uma solicitação de
  infraestrutura de produção completa. Fica como pendência explícita abaixo.

## Pendências
- Definir ambiente de produção formal (compose próprio, branch própria,
  pipeline de CI/CD, secrets segregados) — requer novo pedido explícito do
  usuário, conforme já previsto em `architecture.md`.
- Após a correção pontual, avaliar se o servidor `192.168.90.109` deve
  passar a ser tratado como o único ambiente real do sistema (produção) daqui
  em diante, e ajustar a documentação de arquitetura/DevOps para refletir
  isso sem ambiguidade com "homologação".
