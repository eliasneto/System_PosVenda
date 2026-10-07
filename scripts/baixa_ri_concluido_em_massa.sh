#!/usr/bin/env bash
# Baixa em massa dos RIs ja faturados antes do sistema (pedido do usuario,
# 2026-10-07) - roda o comando `baixar_ri_concluido_em_massa` dentro do
# container "web", a partir da planilha doc/RelatorioRIBI.xlsx.
#
# Uso (na pasta do projeto, local ou no servidor via SSH):
#   scripts/baixa_ri_concluido_em_massa.sh <usuario>            # so simula
#   scripts/baixa_ri_concluido_em_massa.sh <usuario> --aplicar  # grava
#
# <usuario> = username do sistema gravado como autor no historico de cada INEP.
#
# Com --aplicar o script: (1) simula e mostra o resumo; (2) pede para
# digitar SIM; (3) o comando faz o backup de seguranca do banco (o mesmo da
# tela Administrador > Backup, restauravel por ela) - se o backup falhar,
# para sem gravar nada; (4) aplica, tudo numa transacao so. Rodar de novo e
# seguro: INEP ja concluido e desconsiderado. O relatorio .csv de cada
# execucao fica em backups_banco/ (pasta do projeto, fora do git).
#
# Stack: usa docker-compose.hml.yml (+ override, se existir) quando houver
# .env.hml na pasta (servidor); senao, docker-compose.yml (local/"plain").
set -euo pipefail

USUARIO="${1:-}"
MODO="${2:-}"
PLANILHA="doc/RelatorioRIBI.xlsx"

if [ -z "${USUARIO}" ] || { [ -n "${MODO}" ] && [ "${MODO}" != "--aplicar" ]; }; then
    echo "Uso: $0 <usuario> [--aplicar]" >&2
    exit 1
fi
if [ ! -f "${PLANILHA}" ]; then
    echo "ERRO: planilha ${PLANILHA} nao encontrada (rode o script na pasta do projeto)." >&2
    exit 1
fi

if [ -f ".env.hml" ]; then
    COMPOSE=(docker compose -f docker-compose.hml.yml)
    [ -f "docker-compose.hml.override.yml" ] && COMPOSE+=(-f docker-compose.hml.override.yml)
    COMPOSE+=(--env-file .env.hml)
else
    COMPOSE=(docker compose)
fi

CARIMBO="$(date +%Y%m%d_%H%M%S)"
mkdir -p backups_banco

# Copia a planilha para dentro do container - funciona tanto com bind mount
# (.:/app) quanto com imagem buildada/volume em /app/doc (ver TROUBLESHOOTING.md).
# (`< /dev/null` em todo comando docker: o `exec -T` le o stdin e engoliria
# a resposta da confirmacao abaixo.)
"${COMPOSE[@]}" cp "${PLANILHA}" web:/tmp/RelatorioRIBI.xlsx < /dev/null

rodar() {
    local relatorio="$1"; shift
    "${COMPOSE[@]}" exec -T web python manage.py baixar_ri_concluido_em_massa \
        /tmp/RelatorioRIBI.xlsx --usuario "${USUARIO}" --relatorio "/tmp/${relatorio}" "$@" < /dev/null
    "${COMPOSE[@]}" cp "web:/tmp/${relatorio}" "backups_banco/${relatorio}" < /dev/null
    echo "Relatorio salvo em backups_banco/${relatorio}"
}

echo "==> Simulacao (nada e gravado)"
rodar "baixa_ri_simulacao_${CARIMBO}.csv"

if [ "${MODO}" != "--aplicar" ]; then
    echo "==> Fim da simulacao. Para gravar: $0 ${USUARIO} --aplicar"
    exit 0
fi

echo
read -r -p "Confirma a baixa acima? Digite SIM para gravar: " RESPOSTA
if [ "${RESPOSTA}" != "SIM" ]; then
    echo "Cancelado - nada foi gravado."
    exit 1
fi

echo "==> Backup do banco + aplicando a baixa"
rodar "baixa_ri_aplicada_${CARIMBO}.csv" --aplicar
