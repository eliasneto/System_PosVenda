# CI/CD — Gerenciador Pós-Venda
_Última atualização: 2026-08-28_

Pipeline `.github/workflows/homolog.yml`, branch `homolog`.

## Fluxo

```
Push/PR na branch homolog
→ job "ci": instala dependências, manage.py check, manage.py test
  (SQLite, fallback do próprio settings.py — sem MySQL no runner),
  valida build da imagem Docker
→ [só em push direto, não PR, e só se "ci" passou] job "deploy":
  SSH no servidor de homologação → scripts/deploy_homolog.sh
  (atualiza código → sobe containers → migrations → collectstatic)
```

## Secrets necessários (GitHub → Settings → Secrets and variables → Actions)

| Secret | Descrição |
|---|---|
| `HML_HOST` | IP ou domínio do servidor de homologação |
| `HML_USER` | Usuário SSH |
| `HML_PORT` | Porta SSH |
| `HML_SSH_KEY` | Chave privada SSH (par dedicado, nunca a chave pessoal) |
| `HML_DEPLOY_DIR` | Caminho do checkout no servidor (opcional — o script usa `/srv/sistema_posvenda` como padrão) |

Nenhum desses secrets foi criado ainda — preencher antes de o job
"deploy" rodar pela primeira vez (até lá, um push na branch `homolog`
falha no job "deploy" por falta de credencial, o que é o comportamento
esperado, não um bug do pipeline).

## Decisões

- Testes em CI usam SQLite (fallback do `settings.py`, sem `DB_ENGINE`
  definido) para não depender de um serviço MySQL no runner — ambiente
  real (local/homologação/produção) continua MySQL 8.0
  (`architecture.md`, "Banco de Dados").
- Deploy só a partir de push direto na branch `homolog`, nunca de Pull
  Request — evita publicar código ainda não revisado.
