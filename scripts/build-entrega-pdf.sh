#!/usr/bin/env bash
# Receita versionada: ensaio por padrão; --final exige provas e tags.
# Uso de qualquer diretório: scripts/build-entrega-pdf.sh --output /tmp/entrega.pdf
# Requer Python 3.14, pandoc, weasyprint e npx; Mermaid CLI fixado no módulo.
set -euo pipefail
cd "$(dirname "$0")/.."
exec python3 -m scripts.evidencias.pdf "$@"
