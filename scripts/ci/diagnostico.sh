#!/usr/bin/env bash
# Diagnostico de um deploy no kind que falhou ou foi cancelado (passo final
# do job deploy-kind, aqui e no CD dos servicos; roda tambem na maquina
# local): pods, ultimos eventos, logs do Kong e do RabbitMQ e, dos pods que
# nao ficaram prontos ou que reiniciaram, o describe e os logs, inclusive da
# execucao anterior. Nenhum comando le Secret.
#
# Melhor esforco: sem errexit, um comando que falha (cluster que nem subiu,
# pod que nao existe) nao esconde os seguintes, e cada chamada ao apiserver
# tem timeout, para o diagnostico nao gastar o resto do timeout do job.
set -uo pipefail

K="kubectl --context ${KUBE_CONTEXT:-kind-pytstop-p4} --request-timeout=20s"
NS="${NAMESPACE:-pytstop-plataforma}"

echo "::group::pods"
$K get pods -A -o wide
echo "::endgroup::"
echo "::group::events (last 100)"
$K get events -A --sort-by=.lastTimestamp | tail -n 100
echo "::endgroup::"
# A borda e o broker, mesmo com os pods prontos: um smoke ou E2E que falha
# com tudo de pe costuma ter a causa num dos dois.
echo "::group::$NS/kong (last 100 lines of each container)"
$K -n "$NS" logs deployment/kong --all-containers --prefix --tail=100
echo "::endgroup::"
echo "::group::$NS/rabbitmq-0 (last 100 lines)"
$K -n "$NS" logs rabbitmq-0 -c rabbitmq --tail=100
echo "::endgroup::"
# Pod que nao terminou com sucesso e tem container nao pronto, que reiniciou
# ou que nem chegou a ser criado.
$K get pods -A -o json | jq -r '.items[]
  | select(.status.phase != "Succeeded")
  | select(.status.containerStatuses == null
      or any(.status.containerStatuses[]; .ready == false or .restartCount > 0))
  | "\(.metadata.namespace) \(.metadata.name)"' \
| while read -r ns pod; do
    echo "::group::$ns/$pod"
    $K -n "$ns" describe pod "$pod" | tail -n 40
    $K -n "$ns" logs "$pod" --all-containers --tail=200
    $K -n "$ns" logs "$pod" --all-containers --previous --tail=100 2>/dev/null
    echo "::endgroup::"
  done
