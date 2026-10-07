#!/usr/bin/env bash
# Smoke dos servicos implantados no kind (scripts/ci/implantar-servicos.sh),
# por namespace: o Job de inicializacao completo; os Deployments e o banco com
# todas as replicas prontas e atualizadas; pela borda, a saude em 200 e o
# /metrics em 404; cada pod anotado com up = 1 no Prometheus (ate 45 s); e a
# NetworkPolicy barrando o banco a quem vem de outro namespace, numa conexao do
# rabbitmq-0 da plataforma que tem de esgotar o prazo (recusa ou nome que nao
# resolve nao provam a regra). README, "Contrato com os servicos".
#
#   scripts/ci/smoke-servicos.sh [<servico>...]   (sem argumento, os tres)
#
# A tabela servico | etapa | resultado sai na saida e, no GitHub Actions, no
# summary do job; o script sai com status 1 nomeando os servicos que falharam.
set -euo pipefail

K="kubectl --context ${KUBE_CONTEXT:-kind-pytstop-p4} --request-timeout=20s"
BORDA="${BORDA:-https://localhost}"
PLATAFORMA=pytstop-plataforma
INICIALIZACAO=app.kubernetes.io/component=inicializacao
# O Kong do kind responde com o certificado padrao dele: sem verificacao so
# para o localhost.
case "$BORDA" in https://localhost | https://localhost:*) tls=-k ;; *) tls="" ;; esac

# servico <nome>: namespace, prefixo na borda, host e porta do banco.
servico() {
  case "$1" in
    os-service) echo "pytstop-os /os os-postgres.pytstop-os.svc.cluster.local 5432" ;;
    billing-service) echo "pytstop-billing /billing billing-mongo.pytstop-billing.svc.cluster.local 27017" ;;
    execution-service) echo "pytstop-execucao /execucao execucao-postgres.pytstop-execucao.svc.cluster.local 5432" ;;
    *) return 1 ;;
  esac
}

# prazo <segundos> <comando>...: timeout no Linux; no macOS, sem ele, o alarm do perl.
prazo() {
  if command -v timeout >/dev/null; then timeout "$@"; else perl -e 'alarm shift; exec @ARGV' "$@"; fi
}

TABELA=""
FALHARAM=""
# registra <servico> <etapa> <detalhe> <ok?>: uma linha da tabela.
registra() {
  local resultado=ok
  if [ "$4" != sim ]; then
    resultado=FAILED
    case " $FALHARAM " in *" $1 "*) ;; *) FALHARAM="${FALHARAM:+$FALHARAM }$1" ;; esac
  fi
  TABELA+="| $1 | $2 | $resultado: $3 |"$'\n'
  printf '%-18s %-26s %s: %s\n' "$1" "$2" "$resultado" "$3"
}

# junta: as linhas da entrada numa so, para a celula da tabela.
junta() { tr '\n' ' ' | sed 's/ *$//'; }

# status <caminho>: o status HTTP pela borda, 000 sem resposta.
status() { curl -s ${tls:+"$tls"} --max-time 10 -o /dev/null -w '%{http_code}' "$BORDA$1" || true; }

# ups <namespace>: os pods do namespace com up = 1 no Prometheus.
ups() {
  local consulta
  consulta=$(jq -rn --arg q "up{namespace=\"$1\"}" '$q | @uri')
  $K get --raw "/api/v1/namespaces/$PLATAFORMA/services/prometheus:9090/proxy/api/v1/query?query=$consulta" \
    | jq -r '.data.result[] | select(.value[1] == "1") | .metric.pod' | sort -u
}

if [ "$#" -eq 0 ]; then set -- os-service billing-service execution-service; fi
for nome in "$@"; do
  servico "$nome" >/dev/null || { echo "unknown service $nome (os-service, billing-service or execution-service)" >&2; exit 2; }
done

for nome in "$@"; do
  read -r ns prefixo banco porta <<< "$(servico "$nome")"

  # Erro do cluster numa consulta vira FAILED na linha, sem parar o smoke.
  jobs=$($K -n "$ns" get job -l "$INICIALIZACAO" -o json \
    | jq -r '.items[] | "\(.metadata.name)=\(any(.status.conditions[]?; .type == "Complete" and .status == "True"))"' || true)
  completos=$(grep -c '=true$' <<< "$jobs" || true)
  registra "$nome" "initialization Job" "$(junta <<< "${jobs:-no Job labeled $INICIALIZACAO}")" \
    "$([ -n "$jobs" ] && [ "$completos" = "$(grep -c . <<< "$jobs")" ] && echo sim)"

  # Toda replica pronta e atualizada, na geracao atual do objeto.
  pendentes=$($K -n "$ns" get deployment,statefulset -o json | jq -r '.items[]
    | select((.status.observedGeneration // 0) < .metadata.generation
        or (.status.updatedReplicas // 0) < (.spec.replicas // 1)
        or (.status.readyReplicas // 0) < (.spec.replicas // 1))
    | "\(.kind)/\(.metadata.name)"' || true)
  total=$($K -n "$ns" get deployment,statefulset -o name | grep -c . || true)
  registra "$nome" "rollouts" "$(junta <<< "${pendentes:-$total ready}")" \
    "$([ "$total" -gt 0 ] && [ -z "$pendentes" ] && echo sim)"

  obtido=$(status "$prefixo/api/v1/saude")
  registra "$nome" "GET $prefixo/api/v1/saude" "$obtido" "$([ "$obtido" = 200 ] && echo sim)"
  obtido=$(status "$prefixo/metrics")
  registra "$nome" "GET $prefixo/metrics" "$obtido" "$([ "$obtido" = 404 ] && echo sim)"

  # O Prometheus raspa a cada 15 s: pod que acabou de subir ainda pode faltar.
  esperados=$($K -n "$ns" get pods -o json | jq -r '.items[]
    | select(.metadata.annotations["prometheus.io/scrape"] == "true" and .status.phase == "Running")
    | .metadata.name' | sort -u || true)
  faltam=$esperados
  for _ in $(seq 9); do
    faltam=$(comm -23 <(printf '%s\n' "$esperados") <(ups "$ns") | grep . || true)
    [ -z "$faltam" ] && break
    sleep 5
  done
  if [ -z "$esperados" ]; then
    detalhe="no annotated pod running"
  elif [ -n "$faltam" ]; then
    detalhe="missing $(junta <<< "$faltam")"
  else
    detalhe="$(grep -c . <<< "$esperados") pods"
  fi
  registra "$nome" "up = 1 in Prometheus" "$detalhe" "$([ -n "$esperados" ] && [ -z "$faltam" ] && echo sim)"

  # 124 e o codigo do timeout: o pacote sumiu, a NetworkPolicy barrou.
  # $K separa as palavras de proposito (o comando com o contexto); $0, $1 e
  # $? expandem no bash do pod.
  # shellcheck disable=SC2016,SC2086
  codigo=$(prazo 20 $K -n "$PLATAFORMA" exec rabbitmq-0 -c rabbitmq -- \
    bash -c 'timeout 3 bash -c "</dev/tcp/$0/$1" 2>/dev/null; echo "code=$?"' "$banco" "$porta" \
    | sed -n 's/^code=//p' || true)
  case "$codigo" in
    124) detalhe="blocked (connection timed out)" ;;
    0) detalhe="connected: no NetworkPolicy denies it" ;;
    "") detalhe="no answer from rabbitmq-0" ;;
    *) detalhe="refused or unknown host (code $codigo), which does not prove the rule" ;;
  esac
  registra "$nome" "rabbitmq-0 -> $banco:$porta" "$detalhe" "$([ "$codigo" = 124 ] && echo sim)"
done

{
  echo "### Services smoke"
  echo
  echo "| Service | Stage | Result |"
  echo "|---|---|---|"
  printf '%s' "$TABELA"
} >> "${GITHUB_STEP_SUMMARY:-/dev/null}"
if [ -n "$FALHARAM" ]; then
  echo "services smoke FAILED: $FALHARAM" >&2
  exit 1
fi
echo "services smoke OK: $*"
