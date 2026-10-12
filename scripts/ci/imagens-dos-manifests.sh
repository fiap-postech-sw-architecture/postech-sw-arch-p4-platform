#!/usr/bin/env bash
# As imagens que os manifests usam, uma por linha: lê no stdin a saída do
# kubectl kustomize e devolve o valor de cada chave image: (container,
# initContainer). O kustomize ordena as chaves: sem args, command, env nem
# envFrom antes dele, o image: abre o item da lista ("- image: x"), e um nome só
# de dígitos sai entre aspas. Quem confere imagem contra a tabela do README
# (scripts/versoes.sh e scripts/ci/implantar-servicos.sh) lê por aqui, para os
# dois enxergarem a mesma forma.
set -euo pipefail

sed -nE 's/^[ -]*image: *"?([^" ]+)"? *$/\1/p'
