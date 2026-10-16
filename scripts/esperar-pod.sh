#!/usr/bin/env bash
# Espera um pod que acabou de ser apagado existir de novo e ficar Ready (fim do
# scripts/smoke.sh, com o rabbitmq-0). O StatefulSet o recria um instante depois
# do delete, e o kubectl wait logo em seguida sai com NotFound se o pod ainda
# nao existe: aqui o pod e esperado existir primeiro, e as duas esperas saem dos
# mesmos <segundos>. Pod que nao volta no prazo, pod que nao fica Ready e erro
# do cluster: status 1.
set -euo pipefail

pod="${1:?usage: esperar-pod.sh <pod> <seconds>}"
segundos="${2:?usage: esperar-pod.sh <pod> <seconds>}"
K="kubectl --context ${KUBE_CONTEXT:-kind-pytstop-p4} -n ${NAMESPACE:-pytstop-plataforma}"

fim=$((SECONDS + segundos))
while :; do
  # Com o --ignore-not-found, pod ausente sai 0 e sem nome; erro do cluster sai
  # com status e para o script aqui, em vez de passar por pod ausente.
  achado=$($K get pod "$pod" --ignore-not-found -o name)
  [ -z "$achado" ] || break
  if [ "$SECONDS" -ge "$fim" ]; then
    echo "pod $pod not recreated after ${segundos}s" >&2
    exit 1
  fi
  sleep 1
done
# No wait, --timeout zero confere uma vez e negativo espera uma semana: o que
# sobrou do prazo nunca desce de zero.
resta=$((fim - SECONDS))
$K wait --for=condition=Ready "pod/$pod" --timeout="$((resta > 0 ? resta : 0))s" >/dev/null
