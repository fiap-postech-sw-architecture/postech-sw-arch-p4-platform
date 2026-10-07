#!/usr/bin/env bash
# Plataforma no kind do runner, com o overlay kind-ci (job deploy-kind,
# ADR-042): instala o kind e o kubectl fixados, cria o cluster e roda o make
# deploy, marcando cada etapa para o scripts/medir-kind.sh. E o ponto de
# entrada do CD da plataforma e do CD dos servicos, que chamam o resumo da
# medicao num passo proprio, depois do smoke ou do E2E, e o
# scripts/ci/diagnostico.sh se algo falhar. Roda de qualquer diretorio.
set -euo pipefail

[ "$#" -eq 0 ] || { echo "usage: deploy-kind.sh (no arguments)" >&2; exit 2; }
raiz=$(cd "$(dirname "$0")/../.." && pwd)

"$raiz/scripts/ci/instalar-ferramentas.sh"
"$raiz/scripts/medir-kind.sh" etapa kind-up
make -C "$raiz" kind-up
"$raiz/scripts/medir-kind.sh" etapa deploy
make -C "$raiz" deploy OVERLAY=kind-ci
