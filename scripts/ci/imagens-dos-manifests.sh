#!/usr/bin/env bash
# As imagens que os manifests usam, uma por linha: lê no stdin a saída do
# kubectl kustomize e devolve o valor de cada chave image: (container,
# initContainer) e reference: (volume de imagem, o image.reference do pod).
# O kustomize ordena as chaves: sem args, command, env nem envFrom antes dele, o
# image: abre o item da lista ("- image: x"), e um nome só de dígitos sai entre
# aspas. Quem confere imagem contra a tabela de versoes (scripts/versoes.sh e
# scripts/ci/implantar-servicos.sh) lê por aqui, para os dois enxergarem a mesma
# forma. Um reference: de outro uso também seria lido como imagem, e nenhum
# manifest da plataforma ou dos serviços tem um.
set -euo pipefail

sed -nE 's/^[ -]*(image|reference): *"?([^" ]+)"? *$/\2/p'
