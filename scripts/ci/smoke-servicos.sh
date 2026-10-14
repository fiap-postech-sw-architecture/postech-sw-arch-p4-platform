#!/usr/bin/env bash
# Smoke dos servicos implantados no kind (scripts/ci/implantar-servicos.sh),
# por namespace: o Job de inicializacao completo; os Deployments e o banco com
# todas as replicas prontas e atualizadas; pela borda, a saude em 200 (ate 1
# min), o Swagger (/docs e /openapi.json) em 200 e o /metrics e o
# /api/v1/admin/* em 404 com o corpo do Kong (o Ingress fora-da-borda); cada
# pod anotado com up = 1 no Prometheus e o exporter do banco com pg_up
# (PostgreSQL) ou mongodb_up (MongoDB) em 1, as duas esperas juntas por ate
# 45 s; no PostgreSQL, o 127.0.0.1 do pod do banco
# pedindo senha (sem trust); e a NetworkPolicy barrando o banco a quem vem de
# outro namespace, numa conexao do rabbitmq-0 da plataforma que tem de esgotar
# o prazo (recusa ou nome que nao resolve nao provam a regra), depois de uma
# conexao do pod da API ao mesmo banco ter funcionado (sem esse controle, o
# prazo esgotado poderia ser a sonda quebrada). README, "Contrato com os
# servicos".
#
#   scripts/ci/smoke-servicos.sh [<servico>...]   (sem argumento, os tres)
#
# A tabela Service | Stage | Result sai na saida e, no GitHub Actions, no
# summary do job; o script sai com status 1 nomeando os servicos que falharam,
# e com 2 se falta jq, curl, timeout ou perl.
set -euo pipefail

CLUSTER="${CLUSTER:-pytstop-p4}"
K="kubectl --context ${KUBE_CONTEXT:-kind-$CLUSTER} --request-timeout=20s"
BORDA="${BORDA:-https://localhost}"
PLATAFORMA=pytstop-plataforma
INICIALIZACAO=app.kubernetes.io/component=inicializacao
# Corpo que o plugin request-termination do fora-da-borda devolve (message em
# k8s/base/kong/plugins.yaml; o teste confere os dois).
MENSAGEM_DO_KONG="no Route matched with those values"
# Esperas, em segundos, e o intervalo entre as tentativas de cada uma.
ESPERA_SAUDE=60
INTERVALO_SAUDE=2
ESPERA_PROMETHEUS=45
INTERVALO_PROMETHEUS=5

for ferramenta in jq curl; do
  command -v "$ferramenta" >/dev/null || { echo "$ferramenta is required" >&2; exit 2; }
done
command -v timeout >/dev/null || command -v perl >/dev/null || { echo "timeout or perl is required" >&2; exit 2; }

# O Kong do kind responde com o certificado padrao dele: sem verificacao so
# para o localhost, com porta ou sem (nada depois dela: "@" faria de outro host o
# destino).
if [[ "$BORDA" =~ ^https://localhost(:[0-9]+)?$ ]]; then tls=-k; else tls=""; fi

# servico <nome>: namespace, prefixo na borda, host e porta do banco e a metrica
# com que o exporter dele diz se entrou no banco.
servico() {
  case "$1" in
    os-service) echo "pytstop-os /os os-postgres.pytstop-os.svc.cluster.local 5432 pg_up" ;;
    billing-service) echo "pytstop-billing /billing billing-mongo.pytstop-billing.svc.cluster.local 27017 mongodb_up" ;;
    execution-service) echo "pytstop-execucao /execucao execucao-postgres.pytstop-execucao.svc.cluster.local 5432 pg_up" ;;
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

# status <caminho> <segundos>: o status HTTP pela borda, 000 sem resposta.
status() { curl -s ${tls:+"$tls"} --max-time "$2" -o /dev/null -w '%{http_code}' "$BORDA$1" || true; }

# borda <servico> <caminho> <status esperado>: um GET pela borda.
borda() {
  local obtido
  obtido=$(status "$2" 10)
  registra "$1" "GET $2" "$obtido" "$([ "$obtido" = "$3" ] && echo sim)"
}

# cortada <servico> <caminho>: um GET pela borda que o Ingress fora-da-borda
# barra, com 404 e o corpo do Kong. O status sozinho nao prova o corte do
# /api/v1/admin/outbox: nenhum dos tres servicos tem essa rota, e o proprio
# servico tambem responderia 404, com o corpo dele. O corpo e o do plugin.
cortada() {
  local resposta obtido corpo detalhe ok=nao
  resposta=$(curl -s ${tls:+"$tls"} --max-time 10 -w '\n%{http_code}' "$BORDA$2" || true)
  obtido=${resposta##*$'\n'}
  corpo=${resposta%$'\n'*}
  if [ "$obtido" != 404 ]; then
    detalhe=$obtido
  elif [[ "$corpo" == *"$MENSAGEM_DO_KONG"* ]]; then
    detalhe="404 (Kong fora-da-borda)"
    ok=sim
  else
    detalhe="404 without the Kong fora-da-borda body"
  fi
  registra "$1" "GET $2" "$detalhe" "$ok"
}

# serie <metrica> <namespace>: "<pod> <valor>" de cada pod do namespace com a
# metrica no Prometheus.
serie() {
  local consulta
  consulta=$(jq -rn --arg q "${1}{namespace=\"$2\"}" '$q | @uri')
  $K get --raw "/api/v1/namespaces/$PLATAFORMA/services/prometheus:9090/proxy/api/v1/query?query=$consulta" \
    | jq -r '.data.result[] | "\(.metric.pod) \(.value[1])"' | sort -u
}

# ups <namespace>: os pods do namespace com up = 1 no Prometheus.
ups() { serie up "$1" | sed -n 's/ 1$//p'; }

# no_pod <argumento do kubectl>...: a saida de um kubectl exec, com prazo (vazia
# se ele falhou). $K separa as palavras de proposito (o comando com o contexto).
# shellcheck disable=SC2086
no_pod() { prazo 20 $K "$@" || true; }

# codigo <saida>: o "code=" que o sh -c do pod imprime; vazio se nao imprimiu.
codigo_de() { sed -n 's/^code=//p' <<< "$1"; }

if [ "$#" -eq 0 ]; then set -- os-service billing-service execution-service; fi
for nome in "$@"; do
  servico "$nome" >/dev/null || { echo "unknown service $nome (os-service, billing-service or execution-service)" >&2; exit 2; }
done

for nome in "$@"; do
  read -r ns prefixo banco porta conexao <<< "$(servico "$nome")"

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

  # O Kong recebe a rota de um Service novo antes do alvo, que so chega com os
  # endpoints dele: ate la a rota responde 503 (ou 404, sem rota). Espera a
  # saude pelo tempo de ESPERA_SAUDE antes de reprovar.
  fim=$(($(date +%s) + ESPERA_SAUDE))
  while :; do
    obtido=$(status "$prefixo/api/v1/saude" 3)
    [ "$obtido" = 200 ] && break
    [ "$(date +%s)" -lt "$fim" ] || break
    sleep "$INTERVALO_SAUDE"
  done
  registra "$nome" "GET $prefixo/api/v1/saude" "$obtido" "$([ "$obtido" = 200 ] && echo sim)"
  # Rotas que o Ingress fora-da-borda responde com 404 sem chamar o servico
  # (o admin/outbox nao existe em nenhum servico, que tambem responderia 404:
  # so o corpo distingue o corte do Kong), e o Swagger, que so sai pela borda
  # com o --root-path do servico certo.
  cortada "$nome" "$prefixo/metrics"
  cortada "$nome" "$prefixo/api/v1/admin/outbox"
  borda "$nome" "$prefixo/docs" 200
  borda "$nome" "$prefixo/openapi.json" 200

  # O Prometheus raspa a cada 15 s: pod que acabou de subir ainda pode faltar,
  # e o exporter que subiu antes do banco ainda pode dizer pg_up 0. Pod saindo
  # (o de antes de um rollout) nao conta.
  pods=$($K -n "$ns" get pods -o json || true)
  esperados=$(jq -r '.items[]
    | select(.metadata.annotations["prometheus.io/scrape"] == "true" and .status.phase == "Running"
        and .metadata.deletionTimestamp == null)
    | .metadata.name' <<< "$pods" | sort -u || true)
  faltam=$esperados
  fim=$(($(date +%s) + ESPERA_PROMETHEUS))
  while :; do
    faltam=$(comm -23 <(printf '%s\n' "$esperados") <(ups "$ns") | grep . || true)
    conexoes=$(serie "$conexao" "$ns" || true)
    desligados=$(awk 'NF && $2 != 1 { print $1 }' <<< "$conexoes")
    [ -z "$faltam" ] && [ -z "$desligados" ] && break
    [ "$(date +%s)" -lt "$fim" ] || break
    sleep "$INTERVALO_PROMETHEUS"
  done
  if [ -z "$esperados" ]; then
    detalhe="no annotated pod running"
  elif [ -n "$faltam" ]; then
    detalhe="missing $(junta <<< "$faltam")"
  else
    detalhe="$(grep -c . <<< "$esperados") pods"
  fi
  registra "$nome" "up = 1 in Prometheus" "$detalhe" "$([ -n "$esperados" ] && [ -z "$faltam" ] && echo sim)"

  # O alvo do exporter responde up = 1 mesmo sem entrar no banco (o
  # postgres_exporter e o mongodb_exporter servem o /metrics assim e so zeram
  # pg_up e mongodb_up): papel do exporter inexistente no PostgreSQL ou senha
  # errada no MongoDB so aparecem nessa metrica.
  if [ -z "$conexoes" ]; then
    detalhe="no $conexao series"
  elif [ -n "$desligados" ]; then
    detalhe="$conexao is not 1 on $(junta <<< "$desligados")"
  else
    detalhe="$(awk '{ print $1 }' <<< "$conexoes" | junta)"
  fi
  registra "$nome" "$conexao = 1 in Prometheus" "$detalhe" "$([ -n "$conexoes" ] && [ -z "$desligados" ] && echo sim)"

  # PostgreSQL sem trust (POSTGRES_INITDB_ARGS com scram-sha-256): o exporter e
  # sidecar do pod do banco e entra por 127.0.0.1, onde a imagem oficial deixa
  # trust; o pg_up acima passa com a senha certa do proprio papel mesmo assim.
  # O psql como postgres, sem senha, tem de ser recusado por falta dela.
  if [ "$conexao" = pg_up ]; then
    sts=${banco%%.*}
    # shellcheck disable=SC2016
    saida=$(no_pod -n "$ns" exec "$sts-0" -c postgres -- \
      sh -c 'psql -h 127.0.0.1 -U postgres -w -c "select 1" 2>&1; echo "code=$?"')
    codigo=$(codigo_de "$saida")
    recusado=""
    case "$codigo" in
      "") detalhe="no answer from $sts-0" ;;
      0) detalhe="postgres connected from 127.0.0.1 without a password: trust" ;;
      *)
        if grep -qi password <<< "$saida"; then
          detalhe="postgres on 127.0.0.1 without a password was refused"
          recusado=sim
        else
          # O sed sai 0 sem texto (um grep -v sairia 1 e, com o pipefail, o set -e
          # derrubaria o smoke no meio quando o psql morre sem escrever nada).
          primeira=$(sed -n '/^code=/!{p;q;}' <<< "$saida")
          detalhe="refused for another reason: ${primeira:-no message from psql (code $codigo)}"
        fi
        ;;
    esac
    registra "$nome" "$sts-0 127.0.0.1 asks for a password" "$detalhe" "$recusado"
  fi

  # Controle da prova abaixo: o pod da API, do proprio namespace, tem de chegar
  # ao banco com a mesma sonda que, a partir de outro namespace, tem de falhar.
  api=$(jq -r --arg app "$nome-api" '.items[]
    | select(.metadata.labels.app == $app and .status.phase == "Running"
        and .metadata.deletionTimestamp == null)
    | .metadata.name' <<< "$pods" | head -n 1 || true)
  if [ -z "$api" ]; then
    controle=""
    detalhe="no running pod labeled app=$nome-api"
  else
    # shellcheck disable=SC2016
    controle=$(codigo_de "$(no_pod -n "$ns" exec "$api" -- sh -c \
      'python -c "import socket, sys; socket.create_connection((sys.argv[1], int(sys.argv[2])), 3)" "$0" "$1" 2>/dev/null; echo "code=$?"' "$banco" "$porta")")
    case "$controle" in
      0) detalhe="connected (the namespace itself reaches the database)" ;;
      "") detalhe="no answer from $api" ;;
      *) detalhe="could not connect (code $controle)" ;;
    esac
  fi
  registra "$nome" "$nome-api pod -> $banco:$porta" "$detalhe" "$([ "$controle" = 0 ] && echo sim)"

  # 124 e o codigo do timeout: o pacote sumiu, a NetworkPolicy barrou. $0, $1 e
  # $? expandem no bash do pod.
  # shellcheck disable=SC2016
  codigo=$(codigo_de "$(no_pod -n "$PLATAFORMA" exec rabbitmq-0 -c rabbitmq -- \
    bash -c 'timeout 3 bash -c "</dev/tcp/$0/$1" 2>/dev/null; echo "code=$?"' "$banco" "$porta")")
  case "$codigo" in
    124) detalhe="blocked (connection timed out)" ;;
    0) detalhe="connected: no NetworkPolicy denies it" ;;
    "") detalhe="no answer from rabbitmq-0" ;;
    *) detalhe="refused or unknown host (code $codigo), which does not prove the rule" ;;
  esac
  if [ "$codigo" = 124 ] && [ "$controle" != 0 ]; then
    detalhe="timed out, but the control from $nome-api did not connect: the probe proves nothing"
  fi
  registra "$nome" "rabbitmq-0 -> $banco:$porta" "$detalhe" "$([ "$codigo" = 124 ] && [ "$controle" = 0 ] && echo sim)"
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
