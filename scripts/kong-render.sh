#!/usr/bin/env bash
# Gera, em <destino>, o kong.yaml (helm template do chart pinado com o
# values.yaml), o crds.yaml (CRDs do mesmo chart) e o schema do
# KongClusterPlugin que o kubeconform usa (do crds.yaml, com
# additionalProperties: false onde o CRD nao aceita campo livre). O make
# kong-render escreve em k8s/base/kong; o make manifests gera num diretorio
# temporario e compara com o versionado.
set -euo pipefail

destino="${1:?uso: kong-render.sh <destino>}"
: "${KONG_CHART_VERSION:?}" "${HELM_IMAGE:?}" "${YQ_IMAGE:?}" "${NAMESPACE:?}"
mkdir -p "$destino/schemas"

# O chart poe `list` e `watch` em Secrets na Role de cada namespace de
# watchNamespaces, sem valor que os desligue; a plataforma nao usa Secret em
# Ingress nem em plugin, e a regra sai aqui. Sem nenhum casamento o render
# falha, em vez de deixar a regra passar calada se o chart mudar o texto; o
# tests/test_kong_rbac.py reprova Role do Kong que liste ou observe Secrets.
sem_secrets() {
  perl -0777 -pe '$n += s/^- apiGroups:\n  - ""\n  resources:\n  - secrets\n  verbs:\n  - list\n  - watch\n//mg;
    END { $n or die "kong-render.sh: Secrets rule not found in the chart output\n" }'
}

{
  echo "# Gerado por make kong-render (chart kong/kong $KONG_CHART_VERSION, valores em values.yaml). Nao edite."
  docker run --rm -i "$HELM_IMAGE" template kong kong \
    --repo https://charts.konghq.com --version "$KONG_CHART_VERSION" --namespace "$NAMESPACE" \
    --values - --skip-tests --api-versions networking.k8s.io/v1/IngressClass < k8s/base/kong/values.yaml \
    | sem_secrets
} > "$destino/kong.yaml"

{
  echo "# Gerado por make kong-render (CRDs do chart kong/kong $KONG_CHART_VERSION). Nao edite."
  docker run --rm "$HELM_IMAGE" show crds kong --repo https://charts.konghq.com --version "$KONG_CHART_VERSION"
} > "$destino/crds.yaml"

docker run --rm -i "$YQ_IMAGE" -o=json '
  select(.kind == "CustomResourceDefinition" and .spec.names.kind == "KongClusterPlugin")
  | .spec.versions[] | select(.name == "v1") | .schema.openAPIV3Schema
  | (.. | select(tag == "!!map" and has("properties") and (has("x-kubernetes-preserve-unknown-fields") | not)))
    |= . + {"additionalProperties": false}' < "$destino/crds.yaml" > "$destino/schemas/kongclusterplugin_v1.json"
