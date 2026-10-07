#!/usr/bin/env bash
# Minutos e memoria de um deploy no kind: o job deploy-kind do CD e o mesmo
# fluxo na maquina local.
#
#   scripts/medir-kind.sh etapa <nome>   marca o inicio de uma etapa; a primeira
#                                        liga a amostragem (a cada 5 s)
#   scripts/medir-kind.sh resumo         para a amostragem, escreve o resumo em
#                                        Markdown na saida e, no GitHub Actions,
#                                        no summary do job, e zera as marcas
#
# Memoria do no do kind, o container onde rodam todos os pods: o memory.peak do
# cgroup dele, o maior uso que o kernel registrou, inclusive o cache de
# arquivos (imagens descompactadas, logs), que o kernel devolve sob pressao; e
# o maior working set amostrado (memory.current menos inactive_file, a conta
# que o kubelet usa para despejar pod). Por pod, o maior uso que o kubectl top
# mostrou nas amostras.
set -euo pipefail

CLUSTER="${CLUSTER:-pytstop-p4}"
NO="$CLUSTER-control-plane"
K="kubectl --context ${KUBE_CONTEXT:-kind-$CLUSTER}"
DIR="${MEDICAO:-${RUNNER_TEMP:-${TMPDIR:-/tmp}}/medicao-kind}"

mib() { if [ -n "$1" ]; then echo $(($1 / 1048576)); else echo -; fi; }

case "${1:-}" in
  etapa)
    nome="${2:?usage: medir-kind.sh etapa <name>}"
    mkdir -p "$DIR"
    if [ ! -s "$DIR/etapas" ]; then
      : > "$DIR/no"
      : > "$DIR/pods"
      nohup "$0" amostra >/dev/null 2>&1 &
      echo $! > "$DIR/amostrador"
    fi
    echo "$nome $(date +%s)" >> "$DIR/etapas"
    ;;
  amostra)
    while :; do
      # O no ainda nao existe antes do kind-up e o metrics-server so responde
      # depois do deploy: amostra que falha fica de fora.
      docker exec "$NO" sh -c 'cat /sys/fs/cgroup/memory.current; grep "^inactive_file " /sys/fs/cgroup/memory.stat' 2>/dev/null \
        | awk 'NR == 1 {atual = $1} NR == 2 {print atual - $2}' >> "$DIR/no" || true
      $K top pod -A --no-headers 2>/dev/null | awk '{print $1 "/" $2, $4 + 0}' >> "$DIR/pods" || true
      sleep 5
    done
    ;;
  resumo)
    [ -s "$DIR/etapas" ] || { echo "no stage recorded in $DIR"; exit 0; }
    kill "$(cat "$DIR/amostrador")" 2>/dev/null || true
    fim=$(date +%s)
    pico=$(docker exec "$NO" cat /sys/fs/cgroup/memory.peak 2>/dev/null || true)
    {
      echo "### Deploy on kind: minutes and memory"
      echo
      echo "| Stage | Duration |"
      echo "|---|---|"
      awk -v fim="$fim" '
        { nome[NR] = $1; inicio[NR] = $2 }
        END {
          for (i = 1; i <= NR; i++) {
            d = (i < NR ? inicio[i + 1] : fim) - inicio[i]
            printf "| %s | %d min %02d s |\n", nome[i], d / 60, d % 60
          }
          d = fim - inicio[1]
          printf "| total | %d min %02d s |\n", d / 60, d % 60
        }' "$DIR/etapas"
      echo
      echo "| Memory of the kind node ($NO) | MiB |"
      echo "|---|---|"
      echo "| cgroup peak (memory.peak, file cache included) | $(mib "$pico") |"
      echo "| highest sampled working set ($(wc -l < "$DIR/no" | tr -d ' ') samples, every 5 s) | $(mib "$(sort -n "$DIR/no" | tail -1)") |"
      echo "| memory of the Docker host | $(mib "$(docker info --format '{{.MemTotal}}')") |"
      echo
      echo "| Pod | Highest sampled memory (MiB, kubectl top) |"
      echo "|---|---|"
      # Pod de Job que ja terminou aparece com 0 e fica de fora.
      awk '$2 > 0 && $2 > maior[$1] {maior[$1] = $2} END {for (pod in maior) print maior[pod], pod}' "$DIR/pods" \
        | sort -rn | awk '{printf "| %s | %d |\n", $2, $1}'
    } | tee -a "${GITHUB_STEP_SUMMARY:-/dev/null}"
    # A proxima etapa comeca outra medicao.
    rm -f "$DIR/etapas"
    ;;
  *)
    echo "usage: medir-kind.sh etapa <name> | resumo" >&2
    exit 2
    ;;
esac
