# Containers — Gerenciador Pós-Venda
_Última atualização: 2026-08-28_

## Ambiente local (`docker-compose.yml`)

- `db` — MySQL 8.0, porta `3315` no host, volume `posvenda_db_data`.
- `web` — mesma imagem do `Dockerfile`, mas roda `runserver` (não o
  `gunicorn` do `CMD`) com `DEBUG=True` — nesse modo o próprio Django
  serve `/static/`, sem precisar de Nginx. Porta `8000`. Código do host
  montado por bind mount (hot reload).
- `email_scheduler` — mesma imagem, roda `sincronizar_email_financeiro`
  (RF-08/RF-19) em loop.

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

`staticfiles_hml` só é populado pelo `collectstatic` — rodado no deploy
(`scripts/deploy_homolog.sh`), não a cada `docker compose up`.

## Pendências conhecidas

- Sem domínio/certificado definido ainda — `nginx` serve só HTTP,
  `server_name _` genérico (`docker/nginx/homolog.conf`, marcado como TODO).
- `docker-compose.hml.yml` ainda não foi validado num servidor real
  (`docker compose config` validado neste ambiente; build/subida real
  ficam para quando o servidor de homologação estiver definido).
