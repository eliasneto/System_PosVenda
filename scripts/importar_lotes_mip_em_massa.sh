#!/usr/bin/env bash
# Cria em massa os LOTEs do MIP ja faturados (pedido do usuario,
# 2026-10-07) - roda o comando `importar_lotes_mip_em_massa
# --incluir-divergentes` dentro do container "web", a partir da planilha
# doc/BASE CONSOLIDADA MIP 2026.xlsb. Objetivo: o total de "Processo
# Concluido" do sistema bater com o total da planilha.
#
# Uso (na pasta do projeto, local ou no servidor via SSH):
#   scripts/importar_lotes_mip_em_massa.sh <usuario>            # so simula
#   scripts/importar_lotes_mip_em_massa.sh <usuario> --aplicar  # grava
#
# <usuario> = username do sistema gravado como autor dos LOTEs e historicos.
#
# Com --aplicar o script: (1) simula e mostra o resumo + a conferencia de
# valores (planilha x "Processo Concluido"); (2) pede para digitar SIM;
# (3) o comando faz o backup de seguranca do banco (o mesmo da tela
# Administrador > Backup, restauravel por ela) - se falhar, nada e gravado;
# (4) aplica, tudo numa transacao so. INEP ja em LOTE nunca e mexido, entao
# rodar de novo nao duplica nada. O relatorio .csv de cada execucao fica em
# backups_banco/ (pasta do projeto, fora do git).
#
# Stack: usa docker-compose.hml.yml (+ override, se existir) quando houver
# .env.hml na pasta (servidor); senao, docker-compose.yml (local/"plain").
set -euo pipefail

USUARIO="${1:-}"
MODO="${2:-}"
PLANILHA="doc/BASE CONSOLIDADA MIP 2026.xlsb"

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
# Mesmo nome do arquivo original - fica gravado no LOTE e no historico.
DESTINO="/tmp/$(basename "${PLANILHA}")"
"${COMPOSE[@]}" cp "${PLANILHA}" "web:${DESTINO}" < /dev/null

rodar() {
    local relatorio="$1"; shift
    "${COMPOSE[@]}" exec -T web python manage.py importar_lotes_mip_em_massa \
        "${DESTINO}" --usuario "${USUARIO}" --incluir-divergentes \
        --relatorio "/tmp/${relatorio}" "$@" < /dev/null
    "${COMPOSE[@]}" cp "web:/tmp/${relatorio}" "backups_banco/${relatorio}" < /dev/null
    echo "Relatorio salvo em backups_banco/${relatorio}"
}

echo "==> Simulacao (nada e gravado)"
rodar "lotes_mip_simulacao_${CARIMBO}.csv"

if [ "${MODO}" != "--aplicar" ]; then
    echo "==> Fim da simulacao. Para gravar: $0 ${USUARIO} --aplicar"
    exit 0
fi

echo
echo "Confirma a criacao dos LOTEs acima? Digite SIM para gravar:"
read -r RESPOSTA
if [ "${RESPOSTA}" != "SIM" ]; then
    echo "Cancelado - nada foi gravado."
    exit 1
fi

echo "==> Backup do banco + criando os LOTEs"
rodar "lotes_mip_aplicado_${CARIMBO}.csv" --aplicar
