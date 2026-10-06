#!/usr/bin/env bash
# Confere se o Kong recusou configuracao (make kong-check, no fim do make
# deploy). Sem o webhook de admissao, Ingress ou KongClusterPlugin invalido
# nao falha no kubectl apply: o controller registra evento no objeto e, com o
# gate FallbackConfiguration, aplica o resto. Falha se algum objeto que ainda
# existe tem evento de recusa nos ultimos 15 minutos, em qualquer namespace
# (inclusive os dos servicos).
set -euo pipefail

K="kubectl --context ${KUBE_CONTEXT:-kind-pytstop-p4}"
# O controller leva alguns segundos para empurrar a configuracao nova.
sleep "${ESPERA:-10}"

recusas=$($K get events -A -o json | jq -r '.items[]
  | select(.reason == "KongConfigurationApplyFailed" or .reason == "KongConfigurationTranslationFailed")
  | select(.involvedObject.kind != "Pod")
  | select(((.lastTimestamp // .eventTime) | sub("\\.[0-9]+"; "") | fromdateiso8601) > now - 900)
  | [.involvedObject.namespace // "-", .involvedObject.kind, .involvedObject.name, .message] | @tsv' | sort -u)

encontradas=""
# Namespace "-" e objeto de cluster (KongClusterPlugin). Sem campo vazio: o
# read juntaria tabs seguidos.
while IFS=$'\t' read -r ns tipo nome mensagem; do
  [ -n "$nome" ] || continue
  escopo=""
  [ "$ns" = "-" ] || escopo="--namespace=$ns"
  # Objeto ja apagado nao conta: o evento dura ate 1 hora.
  if $K get "$tipo" "$nome" ${escopo:+"$escopo"} >/dev/null 2>&1; then
    encontradas+="$tipo/$nome${escopo:+ (namespace $ns)}: $mensagem"$'\n'
  fi
done <<< "$recusas"

if [ -n "$encontradas" ]; then
  echo "Kong recusou configuracao (o resto foi aplicado pelo fallback):"
  printf '%s' "$encontradas"
  exit 1
fi
echo "kong-check: nenhum objeto com configuracao recusada pelo Kong nos ultimos 15 minutos"
