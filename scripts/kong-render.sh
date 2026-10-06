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

{
  echo "# Gerado por make kong-render (chart kong/kong $KONG_CHART_VERSION, valores em values.yaml). Nao edite."
  docker run --rm -i "$HELM_IMAGE" template kong kong \
    --repo https://charts.konghq.com --version "$KONG_CHART_VERSION" --namespace "$NAMESPACE" \
    --values - --skip-tests --api-versions networking.k8s.io/v1/IngressClass < k8s/base/kong/values.yaml
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
