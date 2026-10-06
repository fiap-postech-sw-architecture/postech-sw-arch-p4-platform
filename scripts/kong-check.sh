#!/usr/bin/env bash
# Confere se o Kong recusou configuracao (make kong-check, no fim do make
# deploy). Sem o webhook de admissao, Ingress ou KongClusterPlugin invalido
# nao falha no kubectl apply: o controller registra evento no objeto e, com o
# gate FallbackConfiguration, aplica o resto. Falha se algum objeto, de
# qualquer namespace (inclusive os dos servicos), tem evento de recusa dos
# ultimos 15 minutos mais novo que a ultima mudanca dele: objeto apagado,
# recriado ou corrigido depois do evento nao conta.
set -euo pipefail

K="kubectl --context ${KUBE_CONTEXT:-kind-pytstop-p4}"
# O controller leva alguns segundos para empurrar a configuracao nova.
sleep "${ESPERA:-10}"

recusas=$($K get events -A -o json | jq -r '.items[]
  | select(.reason == "KongConfigurationApplyFailed" or .reason == "KongConfigurationTranslationFailed")
  | select(.involvedObject.kind != "Pod")
  | ((.lastTimestamp // .eventTime // .firstTimestamp // "1970-01-01T00:00:00Z") | sub("\\.[0-9]+"; "") | fromdateiso8601) as $quando
  | select($quando > now - 900)
  | [.involvedObject.namespace // "-", .involvedObject.kind, .involvedObject.name, ($quando | tostring), .message]
  | @tsv' | sort -u)

encontradas=""
# Namespace "-" e objeto de cluster (KongClusterPlugin). Sem campo vazio: o
# read juntaria tabs seguidos.
while IFS=$'\t' read -r ns tipo nome quando mensagem; do
  [ -n "$nome" ] || continue
  escopo=""
  [ "$ns" = "-" ] || escopo="--namespace=$ns"
  # Ultima mudanca do objeto (criacao ou qualquer escrita); vazio se nao existe.
  mudanca=$($K get "$tipo" "$nome" ${escopo:+"$escopo"} -o json 2>/dev/null | jq -r '
    [.metadata.creationTimestamp, (.metadata.managedFields // [])[].time]
    | map(select(. != null) | fromdateiso8601) | max' || true)
  if [ -n "$mudanca" ] && [ "$mudanca" -le "$quando" ]; then
    encontradas+="$tipo/$nome${escopo:+ (namespace $ns)}: $mensagem"$'\n'
  fi
done <<< "$recusas"

if [ -n "$encontradas" ]; then
  echo "Kong rejected configuration (the fallback applied the rest):"
  printf '%s' "$encontradas"
  exit 1
fi
echo "kong-check: no object with configuration rejected by Kong in the last 15 minutes"
