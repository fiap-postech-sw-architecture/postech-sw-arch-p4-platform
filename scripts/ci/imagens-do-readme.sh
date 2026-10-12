#!/usr/bin/env bash
# As imagens da tabela "Componentes e versoes" do README, uma por linha: o
# primeiro trecho entre crases da coluna "Versao" de cada linha. So essa coluna
# vale, porque o resto do README cita entre crases nomes que nao sao imagem,
# como o papel `postgres` do banco ou o chart `kong/kong` da linha do Kong.
# Quem confere imagem contra a tabela (scripts/versoes.sh e
# scripts/ci/implantar-servicos.sh) le por aqui.
set -euo pipefail

raiz=$(cd "$(dirname "$0")/../.." && pwd)
awk -F'|' '
  /^[|] Componente [|] Vers/ { t = 1 }
  t && !/^[|]/ { t = 0 }
  t && match($3, /`[^`]+`/) { print substr($3, RSTART + 1, RLENGTH - 2) }
' "$raiz/README.md"
