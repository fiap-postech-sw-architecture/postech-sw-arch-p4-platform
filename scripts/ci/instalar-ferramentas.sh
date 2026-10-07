#!/usr/bin/env bash
# kind e kubectl com versao e sha256 fixados, no runner Linux amd64 do GitHub
# Actions (job deploy-kind, ADR-042). Os que vem no runner mudam com a imagem
# dele: o kind e mais novo que o que publicou o no pinado, e o kubectl fica
# duas minors acima do no, fora da distancia de uma minor que o Kubernetes
# suporta entre kubectl e apiserver.
#
# kind: a versao que publicou o kindest/node:v1.35.0 pinado em
# kind/cluster.yaml. kubectl: a mesma minor do no (1.35).
set -euo pipefail

KIND_VERSION=v0.31.0
KIND_SHA256=eb244cbafcc157dff60cf68693c14c9a75c4e6e6fedaf9cd71c58117cb93e3fa
KUBECTL_VERSION=v1.35.9
KUBECTL_SHA256=3cfeaf80be482b435b0aa214aff6e0b2c312ee23c0ff20810c75517b6004c6eb

# Fora do checkout: na raiz dele, kind e o diretorio do cluster.yaml.
dir=$(mktemp -d)
trap 'rm -rf "$dir"' EXIT

# instala <binario> <url> <sha256>
instala() {
  curl --proto '=https' --tlsv1.2 --retry 3 --retry-all-errors --connect-timeout 10 --max-time 120 \
    -sSfL -o "$dir/$1" "$2"
  echo "$3  $dir/$1" | sha256sum -c -
  sudo install -m 0755 "$dir/$1" "/usr/local/bin/$1"
}

instala kind "https://github.com/kubernetes-sigs/kind/releases/download/$KIND_VERSION/kind-linux-amd64" "$KIND_SHA256"
instala kubectl "https://dl.k8s.io/release/$KUBECTL_VERSION/bin/linux/amd64/kubectl" "$KUBECTL_SHA256"

# O PATH tem de achar os instalados, e nao outra copia do runner.
kind version | grep -F "kind $KIND_VERSION "
kubectl version --client
[ "$(kubectl version --client -o json | jq -r .clientVersion.gitVersion)" = "$KUBECTL_VERSION" ]
