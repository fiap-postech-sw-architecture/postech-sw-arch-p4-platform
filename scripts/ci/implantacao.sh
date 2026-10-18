# shellcheck shell=bash
# Funcoes comuns ao scripts/ci/implantar-servicos.sh (os servicos no kind do
# CD) e ao scripts/ci/deploy-remoto.sh (um servico num cluster persistente,
# opcional), carregadas por source: o kubectl com prazo e a implantacao de um
# namespace na ordem do contrato com os servicos (README). Quem carrega define
# CONTEXTO antes de chamar kc, k ou implanta.
#
# Prazos, em segundos, pelo ambiente: PRAZO_KUBECTL (cada chamada ao cluster,
# 120; nas esperas, somado ao tempo delas), ESPERA_BANCO (180), ESPERA_JOB
# (300) e ESPERA_DEPLOYMENT (300).

INICIALIZACAO=app.kubernetes.io/component=inicializacao
PRAZO_KUBECTL="${PRAZO_KUBECTL:-120}"
ESPERA_BANCO="${ESPERA_BANCO:-180}"
ESPERA_JOB="${ESPERA_JOB:-300}"
ESPERA_DEPLOYMENT="${ESPERA_DEPLOYMENT:-300}"
# Overlay que os dois scripts geram dentro do repositorio do servico (o
# kustomize so le resources por caminho relativo) e apagam no fim.
# shellcheck disable=SC2034 # usado por quem carrega este arquivo
EXECUCAO=k8s/overlays/execucao

# prazo <segundos> <comando>...: timeout no Linux; no macOS, sem ele, o alarm do
# perl. Estouro: status 124 (timeout) ou 142 (SIGALRM).
prazo() {
  if command -v timeout >/dev/null; then timeout "$@"; else perl -e 'alarm shift; exec @ARGV' "$@"; fi
}

# kc <segundos> <argumento>...: kubectl no contexto, com prazo; no estouro, diz
# qual chamada.
kc() {
  local segundos=$1 status=0
  shift
  prazo "$segundos" kubectl --context "$CONTEXTO" "$@" || status=$?
  if [ "$status" = 124 ] || [ "$status" = 142 ]; then
    echo "kubectl $* exceeded ${segundos}s" >&2
  fi
  return "$status"
}

# k <argumento>...: kc com o prazo de uma chamada comum.
k() { kc "$PRAZO_KUBECTL" "$@"; }

# namespace <servico>
namespace() {
  case "$1" in
    os-service) echo pytstop-os ;;
    billing-service) echo pytstop-billing ;;
    execution-service) echo pytstop-execucao ;;
    *) return 1 ;;
  esac
}

# segredo_do_banco <namespace>: o Secret das senhas do banco do servico.
segredo_do_banco() {
  case "$1" in
    pytstop-os) echo os-postgres ;;
    pytstop-billing) echo billing-mongo ;;
    pytstop-execucao) echo execucao-postgres ;;
  esac
}

# espera_job <namespace> <job>: 0 quando o Job completa, 1 quando ele falha
# (backoffLimit ou prazo esgotados) ou nao completa em ESPERA_JOB segundos. Um
# kubectl wait pelo Complete nao ve o Job Failed e esperaria os 300 s inteiros.
espera_job() {
  local fim=$((SECONDS + ESPERA_JOB)) condicoes
  echo "waiting for $2 (up to ${ESPERA_JOB}s)"
  while :; do
    condicoes=$(k -n "$1" get "$2" -o jsonpath='{range .status.conditions[?(@.status=="True")]}{.type} {end}') || return
    case "$condicoes" in
      *Complete*) return 0 ;;
      *Failed*) echo "$2 failed" >&2; return 1 ;;
    esac
    if [ "$SECONDS" -ge "$fim" ]; then
      echo "$2 not complete after ${ESPERA_JOB}s" >&2
      return 1
    fi
    sleep 2
  done
}

# implanta <namespace> <dir do overlay>: a ordem do namespace. Cada lista vem
# antes do laco: erro do cluster dentro do $( ) do for passaria calado. Nas
# esperas, o prazo da chamada e o --timeout dela mais o de uma chamada comum.
# Cada comando que falha devolve o status com o return, porque quem chama pode
# rodar a funcao onde o set -e nao vale (num if ou do lado esquerdo de um ||).
implanta() {
  local ns=$1 recurso recursos jobs banco
  banco=$(segredo_do_banco "$ns")
  # Sem os Secrets (o make deploy os cria), os pods ficariam em
  # CreateContainerConfigError e o erro viria como timeout do banco.
  k -n "$ns" get secret rabbitmq "$banco" -o name > /dev/null \
    || { echo "Secrets rabbitmq and $banco are missing in $ns: run make deploy first" >&2; return 1; }
  k -n "$ns" delete job -l "$INICIALIZACAO" --ignore-not-found --timeout=60s || return
  k apply --server-side -k "$2" || return
  recursos=$(k -n "$ns" get statefulset -o name) || return
  if [ -z "$recursos" ]; then
    echo "no StatefulSet in $ns" >&2
    return 1
  fi
  for recurso in $recursos; do
    kc $((ESPERA_BANCO + PRAZO_KUBECTL)) -n "$ns" rollout status "$recurso" --timeout="${ESPERA_BANCO}s" || return
  done
  jobs=$(k -n "$ns" get job -l "$INICIALIZACAO" -o name) || return
  if [ -z "$jobs" ]; then
    echo "no Job labeled $INICIALIZACAO in $ns" >&2
    return 1
  fi
  for recurso in $jobs; do
    if ! espera_job "$ns" "$recurso"; then
      k -n "$ns" logs "$recurso" --all-containers --tail=50 >&2 || true
      return 1
    fi
  done
  recursos=$(k -n "$ns" get deployment -o name) || return
  if [ -z "$recursos" ]; then
    echo "no Deployment in $ns" >&2
    return 1
  fi
  for recurso in $recursos; do
    kc $((ESPERA_DEPLOYMENT + PRAZO_KUBECTL)) -n "$ns" rollout status "$recurso" --timeout="${ESPERA_DEPLOYMENT}s" || return
  done
}
