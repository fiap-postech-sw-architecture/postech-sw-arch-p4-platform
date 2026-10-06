#!/usr/bin/env bash
# Confere as versoes fixadas (make manifests): cada imagem tem uma tag so entre
# k8s/ (os dois overlays), o compose e as ferramentas do Makefile que rodam a
# mesma imagem (argumentos); a tabela "Componentes e versoes" do README cita
# cada uma; e o no do kind roda o Kubernetes que o kubeconform valida.
set -euo pipefail
: "${KUBERNETES_VERSION:?}"

imagens=$(
  {
    for overlay in kind k3s; do kubectl kustomize "k8s/overlays/$overlay"; done \
      | sed -n 's/^ *image: *"\{0,1\}\([^" ]*\)"\{0,1\} *$/\1/p'
    docker compose -f compose/docker-compose.yml --profile servicos config --images
    printf '%s\n' "$@"
  } | grep -v '^pytstop-' | sort -u
)

erro=0
duplicadas=$(sed 's/:[^:/]*$//' <<< "$imagens" | sort | uniq -d)
if [ -n "$duplicadas" ]; then
  echo "image with more than one tag across k8s, compose and Makefile:"
  grep -F "$duplicadas" <<< "$imagens"
  erro=1
fi
while read -r imagem; do
  if ! grep -qF "\`$imagem\`" README.md; then
    echo "$imagem missing from the README versions table"
    erro=1
  fi
done <<< "$imagens"
if ! grep -q "image: kindest/node:v$KUBERNETES_VERSION@sha256:" kind/cluster.yaml; then
  echo "kind/cluster.yaml does not pin kindest/node:v$KUBERNETES_VERSION by digest (kubeconform validates against $KUBERNETES_VERSION)"
  erro=1
fi
[ "$erro" = 0 ] && echo "versions: $(wc -l <<< "$imagens" | tr -d ' ') images, one tag each, all in the README; kind node v$KUBERNETES_VERSION"
exit "$erro"
