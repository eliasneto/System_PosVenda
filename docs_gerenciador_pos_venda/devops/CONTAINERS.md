# Containers — Gerenciador Pós-Venda
_Última atualização: 2026-09-03_

## Ambiente local (`docker-compose.yml`)

- `db` — MySQL 8.0, porta `3315` no host, volume `posvenda_db_data`.
- `web` — mesma imagem do `Dockerfile`, mas roda `runserver` (não o
  `gunicorn` do `CMD`) com `DEBUG=True` — nesse modo o próprio Django
  serve `/static/`, sem precisar de Nginx. Porta `8000`. Código do host
  montado por bind mount (hot reload).
- `email_scheduler` — mesma imagem, roda `sincronizar_email_financeiro`
  (RF-08/RF-19) em loop.
- `rpa_eace_worker` — mesma imagem, roda `processar_fila_rpa_eace`
  (FEAT-033, RN-058) em loop (padrão `sleep 5` entre passadas, configurável
  por `RPA_EACE_POLL_INTERVAL_SECONDS`) — consumidor único da fila do RPA
  de anexo no portal EACE; **manter só 1 réplica** (RN-058: no máximo 1
  execução do RPA por vez em todo o sistema).

## Homologação (`docker-compose.hml.yml`, FEAT-012)

Sem bind mount — sobe a partir da imagem buildada do commit publicado.
`DEBUG=False` (obrigatório, `.env.hml`).

- `db` — MySQL 8.0, sem porta publicada no host (só a rede interna do
  compose acessa), volume `posvenda_db_data_hml`, com healthcheck.
- `web` — `CMD` padrão do `Dockerfile` (`gunicorn`). Gunicorn sozinho não
  serve arquivo estático — por isso não é exposto direto ao host, só via
  `nginx`. Volumes nomeados `staticfiles_hml`/`media_hml` (mesmo caminho
  de `STATIC_ROOT`/`MEDIA_ROOT` do `settings.py`, sem alterar nada lá).
- `nginx` — `nginx:1.27-alpine`, publica `HML_HTTP_PORT` (padrão `8010`)
  no host. Serve `/static/` e `/media/` direto dos volumes nomeados
  (`docker/nginx/homolog.conf`) e repassa o resto para `web:8000`.
  WhiteNoise foi descartado como alternativa por exigir mudança em
  `settings.py` — fora do escopo do DevOps (`.claude/agents/devops.md`).
- `email_scheduler` — mesmo papel do ambiente local.
- `rpa_eace_worker` — mesmo papel do ambiente local; usa `env_file:
  .env.hml` (não lista variável por variável, diferente do `web`/
  `email_scheduler` aqui) e monta o volume nomeado `media_hml` (precisa
  ler os mesmos arquivos de `Documento` que o `web` grava lá).

`staticfiles_hml` só é populado pelo `collectstatic` — rodado no deploy
(`scripts/deploy_homolog.sh`), não a cada `docker compose up`.

## Imagem — Playwright/Chromium (FEAT-033, `ADR-004`/`ADR-005`)

O `Dockerfile` roda `playwright install --with-deps chromium` depois do
`pip install`. Isso baixa o Chromium (~150–300 MB) e instala as
bibliotecas de sistema que ele precisa para rodar headless — a imagem
final fica sensivelmente maior e o build demora mais (validado localmente
com `docker compose build rpa_eace_worker`, ver histórico do checklist).
Como o projeto usa **1 Dockerfile só** para todos os serviços, `web` e
`email_scheduler` também carregam esse peso, mesmo não usando Playwright
— mesmo padrão já aceito para `python-ldap`/`libldap2-dev` (FEAT-027).

## Pendências conhecidas

- Sem domínio/certificado definido ainda — `nginx` serve só HTTP,
  `server_name _` genérico (`docker/nginx/homolog.conf`, marcado como TODO).
- `docker-compose.hml.yml` ainda não foi validado num servidor real
  (`docker compose config` validado neste ambiente; build/subida real
  ficam para quando o servidor de homologação estiver definido).
- `rpa_eace_worker` (FEAT-033) ainda não foi implantado em homologação
  nem em produção — precisa de `EACE_URL`/`EACE_USUARIO`/`EACE_SENHA`
  reais no `.env.hml` do servidor (hoje só existem no `.env` local) e de
  autorização explícita do Orquestrador antes do deploy (regra de
  produção, `.claude/agents/devops.md`).
