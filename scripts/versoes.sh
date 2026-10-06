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
  echo "imagem com mais de uma tag entre k8s, compose e Makefile:"
  grep -F "$duplicadas" <<< "$imagens"
  erro=1
fi
while read -r imagem; do
  if ! grep -qF "\`$imagem\`" README.md; then
    echo "$imagem nao esta na tabela de versoes do README"
    erro=1
  fi
done <<< "$imagens"
if ! grep -q "image: kindest/node:v$KUBERNETES_VERSION@sha256:" kind/cluster.yaml; then
  echo "kind/cluster.yaml nao fixa kindest/node:v$KUBERNETES_VERSION por digest (o kubeconform valida contra $KUBERNETES_VERSION)"
  erro=1
fi
[ "$erro" = 0 ] && echo "versoes: $(wc -l <<< "$imagens" | tr -d ' ') imagens com tag unica e no README; kind em v$KUBERNETES_VERSION"
exit "$erro"
