#!/usr/bin/env bash
# Deploy de homologacao do Gerenciador Pos-Venda (FEAT-012).
#
# Rodado no SERVIDOR de homologacao (via SSH, disparado pelo pipeline
# .github/workflows/homolog.yml) - nao roda localmente. Segue o fluxo
# documentado em .claude/agents/devops.md:
#   Atualiza codigo -> Sobe containers -> Migrations -> Collectstatic
#
# Caminho conhecido no servidor de homologacao (docs_gerenciador_pos_venda/
# devops/DEPLOYMENT.md) - exporte DEPLOY_DIR antes de chamar o script se
# for outro servidor/caminho.
set -euo pipefail

DEPLOY_DIR="${DEPLOY_DIR:-/home/Sistem_PosVenda}"
COMPOSE_FILE="docker-compose.hml.yml"
ENV_FILE=".env.hml"

echo "==> Entrando em ${DEPLOY_DIR}"
cd "${DEPLOY_DIR}"

echo "==> Atualizando codigo (branch homolog)"
git fetch origin homolog
git reset --hard origin/homolog

if [ ! -f "${ENV_FILE}" ]; then
    echo "ERRO: ${ENV_FILE} nao encontrado em ${DEPLOY_DIR}." >&2
    echo "Copie de .env.hml.example e preencha os TODO antes do primeiro deploy." >&2
    exit 1
fi

echo "==> Subindo containers (build)"
docker compose -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}" up -d --build

echo "==> Aguardando o banco ficar saudavel"
docker compose -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}" up -d --wait db

echo "==> Rodando migrations"
docker compose -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}" exec -T web python manage.py migrate --noinput

echo "==> Rodando collectstatic (Nginx serve o resultado, docker/nginx/homolog.conf)"
docker compose -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}" exec -T web python manage.py collectstatic --noinput

echo "==> Status dos containers"
docker compose -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}" ps

echo "==> Deploy de homologacao concluido"
