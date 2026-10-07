#!/usr/bin/env bash
# Smoke da plataforma num cluster so com a plataforma implantada (make kind-up
# deploy smoke). Aplica os exemplos de borda de k8s/exemplos/ (OS, Billing e
# Execucao)
# com um servidor de eco no lugar de cada API e confere borda, rate limiting,
# barra codificada, mascara de token no Loki, policies, retry por atraso e
# redrive do RabbitMQ, fallback do Kong, regras do Grafana e o endurecimento dos
# pods. A prova do retry (scripts/prova_retry.py) roda com o uv, por um
# port-forward ao broker.
#
# A saida e a evidencia: cada linha diz o que foi pedido e o que voltou. Prova
# que nao vale vira uma linha CHECK FAILED; o script segue ate o fim, para a
# saida trazer todas, e sai com status 1 no final.
#
# Os objetos de teste vao para o pytstop-plataforma (o Kong so le Ingress dos
# namespaces da fase 4), com o rotulo part-of=pytstop-smoke, e saem no fim.
#
# OVERLAY e o overlay implantado (make smoke OVERLAY=kind-ci): o kind-ci nao
# tem Loki, Promtail e Grafana (ADR-042), e as provas deles pulam com aviso; as
# demais rodam igual.
set -euo pipefail

CONTEXTO="${KUBE_CONTEXT:-kind-pytstop-p4}"
OVERLAY="${OVERLAY:-kind}"
BORDA="${BORDA:-http://localhost}"
NS=pytstop-plataforma
ROTULO=app.kubernetes.io/part-of=pytstop-smoke
K="kubectl --context $CONTEXTO"
limpa() {
  [ -z "${port_forward:-}" ] || kill "$port_forward" 2>/dev/null || true
  $K delete kongclusterplugin smoke-plugin-invalido --ignore-not-found >/dev/null
  $K -n "$NS" delete deployment,service,ingress -l "$ROTULO" --ignore-not-found >/dev/null
  rm -rf "$TMP"
}

# A prova do retry roda com o uv: sem ele, o smoke so falharia no fim.
command -v uv >/dev/null || { echo "uv not found: the retry proof (scripts/prova_retry.py) runs with it, see https://docs.astral.sh/uv/" >&2; exit 1; }
# Os exemplos usam os caminhos /os, /billing e /execucao dos servicos de verdade.
for ns in pytstop-os pytstop-billing pytstop-execucao; do
  if [ -n "$($K -n "$ns" get ingress -o name 2>/dev/null)" ]; then
    echo "$ns already has Ingresses: the smoke would reuse its paths. Run it on a platform-only cluster." >&2
    exit 1
  fi
done
TMP="$(mktemp -d)"
trap limpa EXIT

FALHAS=0
RESUMO=""
# confere <o que> <esperado> <obtido>
confere() {
  if [ "$2" != "$3" ]; then
    FALHAS=$((FALHAS + 1))
    RESUMO+="  - $1: expected '$2', got '$3'"$'\n'
    printf 'CHECK FAILED: %s: expected %s, got %s\n' "$1" "$2" "$3" >&2
  fi
}

titulo() { printf '\n== %s\n' "$*"; }

# implantado <componente>: falso so no kind-ci, que nao tem Loki, Promtail e
# Grafana; la a prova pula com aviso, e a linha final diz quantas pulou. Nos
# outros overlays a prova roda, e componente ausente ou quebrado e CHECK
# FAILED.
PULADAS=0
PULADOS=""
implantado() {
  [ "$OVERLAY" = kind-ci ] || return 0
  echo "skipped: no $1 in the kind-ci overlay"
  PULADAS=$((PULADAS + 1))
  PULADOS="${PULADOS:+$PULADOS; }$1"
  return 1
}

cabecalho() { tr -d '\r' < "$TMP/h" | awk -v nome="$1:" 'tolower($1) == nome {print $2}'; }

# pede <metodo> <caminho> [<status esperado> [<caminho que o servico deve
# receber>]]: status, o caminho que o eco recebeu e o balde de rate limiting da
# rota (limite por minuto e quanto sobra nele). Com o status esperado, confere
# o status e o caminho recebido; sem o ultimo, o esperado e que o servico nao
# tenha sido chamado ("-"). Todo curl do smoke tem --max-time: pedido
# pendurado falha em segundos, em vez de gastar o timeout do job.
pede() {
  local status recebido limite resta
  status=$(curl -s --max-time 10 --path-as-is -X "$1" -D "$TMP/h" -o "$TMP/b" -w '%{http_code}' "$BORDA$2")
  recebido=$(jq -r '.path // "-"' "$TMP/b" 2>/dev/null || echo -)
  limite=$(cabecalho x-ratelimit-limit-minute)
  resta=$(cabecalho x-ratelimit-remaining-minute)
  printf '%-4s %-40s -> %s  upstream got: %-34s bucket: %s/min, %s left\n' \
    "$1" "$2" "$status" "$recebido" "${limite:--}" "${resta:--}"
  if [ -n "${3:-}" ]; then
    confere "$1 $2 status" "$3" "$status"
    confere "$1 $2 path the service got" "${4:--}" "$recebido"
  fi
}

# Token que so existe neste smoke: a prova de que nao chega ao Loki. A marca vai
# em run=<marca> nas requisicoes com token (a mascara nao a toca) e deixa achar
# no Loki as linhas desta execucao, sem confundir com as de uma anterior.
segredo="tokensmoke$(date +%s)"
marca="run$(date +%s)"

# eco <nome>: servidor de eco no lugar da API do servico (label app = nome).
# O rotulo do smoke vai tambem no pod: o medir-kind.sh o tira da tabela por
# pod, onde o eco passaria pela memoria da API.
eco() {
  $K -n "$NS" apply -f - >/dev/null <<YAML
apiVersion: apps/v1
kind: Deployment
metadata:
  name: $1
  labels:
    app.kubernetes.io/part-of: pytstop-smoke
spec:
  selector:
    matchLabels:
      app: $1
  template:
    metadata:
      labels:
        app: $1
        app.kubernetes.io/part-of: pytstop-smoke
    spec:
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        seccompProfile:
          type: RuntimeDefault
      automountServiceAccountToken: false
      containers:
        - name: eco
          image: mendhak/http-https-echo:42
          env:
            - name: HTTP_PORT
              value: "8000"
          ports:
            - containerPort: 8000
          readinessProbe:
            httpGet:
              path: /
              port: 8000
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities:
              drop: ["ALL"]
YAML
}

titulo "edge: k8s/exemplos/borda-os-service.yaml, borda-billing-service.yaml and borda-execution-service.yaml as is, with an echo server in place of each API"
eco os-service-api
eco billing-service-api
eco execution-service-api
for exemplo in k8s/exemplos/borda-os-service.yaml k8s/exemplos/borda-billing-service.yaml k8s/exemplos/borda-execution-service.yaml; do
  $K -n "$NS" apply -f "$exemplo"
  $K -n "$NS" label -f "$exemplo" "$ROTULO" >/dev/null
done
$K -n "$NS" rollout status deployment/os-service-api --timeout=180s
$K -n "$NS" rollout status deployment/billing-service-api --timeout=180s
$K -n "$NS" rollout status deployment/execution-service-api --timeout=180s
# O controller leva alguns segundos para empurrar as rotas novas ao Kong, e o
# alvo de cada Service so entra quando os endpoints dele chegam ao controller:
# ate la, a rota responde 404 (sem rota) ou 503 (sem alvo), e um Service pode
# ficar pronto antes de outro. Espera um caminho de cada Service dos exemplos
# (Service novo num exemplo entra na lista, com o nome dele) responder 200, sem
# token e sem a marca do Loki; o login vai por ultimo, porque o balde dele e o
# menor. Esgotado o prazo, o smoke sai com status 1 e diz qual Service nao
# respondeu: sem isso, a espera acabaria calada e as provas seguintes
# falhariam uma a uma, sem dizer por que.
nao_respondeu=""
bordas_prontas() {
  local servico caminho status
  while read -r servico caminho; do
    # Sem resposta (recusa, prazo), o curl sai com erro e o -w imprime 000.
    status=$(curl -s --max-time 10 -o /dev/null -w '%{http_code}' "$BORDA$caminho" || true)
    if [ "$status" != 200 ]; then
      [ "$status" != 000 ] || status="no response"
      nao_respondeu="Service $servico, GET $caminho: expected 200, got $status"
      return 1
    fi
  done <<'SERVICES'
os-service-borda-api /os/api/v1/ordens-de-servico
os-service-borda-docs /os/docs
os-service-borda-openapi /os/openapi.json
os-service-borda-jwks /os/.well-known/jwks.json
os-service-borda-publico /os/api/v1/publico/acompanhamento
os-service-borda-autenticacao /os/api/v1/autenticacao/refresh
billing-service-borda-api /billing/api/v1/orcamentos
billing-service-borda-docs /billing/docs
billing-service-borda-openapi /billing/openapi.json
billing-service-borda-publico /billing/api/v1/publico/x
billing-service-borda-webhook /billing/api/v1/webhooks/mercadopago
billing-service-borda-simulador-api /billing/api/v1/simulador/x
billing-service-borda-simulador-checkout /billing/simulador/checkout/x
execution-service-borda-api /execucao/api/v1/estoque
execution-service-borda-docs /execucao/docs
execution-service-borda-openapi /execucao/openapi.json
os-service-borda-login /os/api/v1/autenticacao/login
SERVICES
  nao_respondeu=""
}
for _ in $(seq 60); do
  bordas_prontas && break
  sleep 2
done
if [ -n "$nao_respondeu" ]; then
  echo "edge not ready after 60 tries, 2 s apart: $nao_respondeu" >&2
  exit 1
fi

titulo "published and blocked paths: the expected status, and the path the service got (the Kong strips the prefix)"
pede GET /os/api/v1/ordens-de-servico 200 /api/v1/ordens-de-servico
pede GET /os/docs 200 /docs
pede GET /os/openapi.json 200 /openapi.json
pede GET /os/.well-known/jwks.json 200 /.well-known/jwks.json
pede POST /os/api/v1/publico/acompanhamento 200 /api/v1/publico/acompanhamento
pede POST /os/api/v1/autenticacao/refresh 200 /api/v1/autenticacao/refresh
pede POST /os/api/v1/autenticacao/login 200 /api/v1/autenticacao/login
pede GET /os/metrics 404
pede GET /os/api/v1/admin/outbox 404
pede GET /os/saude 404
pede GET /billing/api/v1/orcamentos 200 /api/v1/orcamentos
pede POST /billing/api/v1/webhooks/mercadopago 200 /api/v1/webhooks/mercadopago
pede POST /billing/api/v1/simulador/pagamentos/123/aprovar 200 /api/v1/simulador/pagamentos/123/aprovar
pede GET /billing/metrics 404
pede GET /billing/api/v1/admin/outbox 404
pede GET /execucao/api/v1/fila 200 /api/v1/fila
pede GET /execucao/docs 200 /docs
pede GET /execucao/openapi.json 200 /openapi.json
pede GET /execucao/metrics 404
pede GET /execucao/api/v1/admin/outbox 404

titulo "encoded slash (%2F, %5C) in the path never gets past the gateway: bloqueia-barra-codificada answers 404, in any case"
pede GET /os/api/v1/admin%2Foutbox 404
pede GET /os/api/v1/admin%2foutbox 404
pede GET /os/api/v1/admin%5Coutbox 404
pede POST /os/api/v1/autenticacao%2Flogin 404
pede POST /os/api/v1/publico%2Facompanhamento 404
pede GET "/billing/api/v1/publico%2Forcamentos/$segredo?run=$marca" 404
pede GET "/billing/simulador%2Fcheckout/123?token=$segredo&run=$marca" 404
echo "only the path counts: %2F in the query string goes through"
pede GET "/os/api/v1/ordens-de-servico?proximo=%2Fadmin" 200 /api/v1/ordens-de-servico
echo "other spellings of the admin path: the Kong normalizes them before matching, so fora-da-borda still answers"
pede GET //os//api/v1//admin/outbox 404
pede GET /os/api/v1/./admin/outbox 404
pede GET /os/api/v1/%61dmin/outbox 404

titulo "X-Request-ID: same id in the response and in what the upstream got"
curl -s --max-time 10 -D "$TMP/h" -o "$TMP/b" "$BORDA/os/api/v1/ordens-de-servico"
id_resposta=$(cabecalho x-request-id)
id_servico=$(jq -r '.headers["x-request-id"]' "$TMP/b")
printf 'response:       %s\n' "$id_resposta"
printf 'upstream got:   %s\n' "$id_servico"
confere "X-Request-ID the Kong generated" "present" "$([ -n "$id_resposta" ] && echo present || echo missing)"
confere "X-Request-ID in the response vs at the service" "$id_resposta" "$id_servico"

titulo "login rate limit (5/min, x10 on kind): POSTs in a row until the first 429 (the login requests above count if they fell in the same minute)"
# Janela fixa por minuto: se a rajada atravessar a virada, o contador zera e o
# 429 vem um pouco depois; 120 POSTs sempre passam do limite de duas janelas.
primeiro_429=""
for n in $(seq 120); do
  if [ "$(curl -s --max-time 10 -o /dev/null -w '%{http_code}' -X POST "$BORDA/os/api/v1/autenticacao/login")" = 429 ]; then
    primeiro_429=$n
    break
  fi
done
echo "first 429 at login POST #${primeiro_429:-none}"
confere "login reached 429 (rate-limiting-login)" "yes" "$([ -n "$primeiro_429" ] && echo yes || echo no)"
echo "separate bucket: refresh still answers"
pede POST /os/api/v1/autenticacao/refresh 200 /api/v1/autenticacao/refresh
printf 'client IP seen by Kong (last access log line): '
$K -n pytstop-plataforma logs deployment/kong -c proxy --tail=1 | awk '{print $1}'

titulo "decision link and checkout tokens kept out of Loki (Promtail masks before pushing)"
pede GET "/billing/api/v1/publico/orcamentos/$segredo?run=$marca" 200 "/api/v1/publico/orcamentos/$segredo"
pede GET "/billing/simulador/checkout/123?token=$segredo&run=$marca" 200 /simulador/checkout/123
if implantado "Loki and Promtail"; then
  # loki <LogQL>: linhas dos ultimos 5 minutos, pela API do Kubernetes (sem port-forward).
  loki() {
    $K get --raw "/api/v1/namespaces/pytstop-plataforma/services/loki:3100/proxy/loki/api/v1/query_range?limit=100&since=5m&query=$(jq -rn --arg q "$1" '$q|@uri')" \
      | jq -r '.data.result[].values[][1]'
  }
  # As quatro requisicoes com token desta execucao (duas publicadas, duas barradas
  # pelo %2F) levam run=<marca>: espera as quatro no Loki (o Promtail empurra em
  # lotes), mascaradas ou nao, e so entao conta. Sem a espera, um vazamento ainda
  # no caminho passaria calado.
  linhas_da_execucao="{app=\"kong\"} |= \"run=$marca\""
  for _ in $(seq 30); do
    [ "$(loki "$linhas_da_execucao" | grep -c .)" -ge 4 ] && break
    sleep 2
  done
  com_token=$(loki "{app=\"kong\"} |= \"$segredo\"" | grep -c . || true)
  mascaradas=$(loki "$linhas_da_execucao |= \"***\"" | grep -c . || true)
  printf 'Kong lines in Loki with token %s: %s\n' "$segredo" "$com_token"
  printf 'Kong lines in Loki of the 4 requests with the token, masked as ***: %s\n' "$mascaradas"
  echo "the same requests as stored in Loki:"
  # sed e nao head: head fecharia o pipe antes de o jq terminar (SIGPIPE com pipefail).
  loki "$linhas_da_execucao" | sed -n 1,4p
  confere "Kong lines in Loki with the token" 0 "$com_token"
  confere "Kong lines in Loki of the 4 requests with the token masked" 4 "$mascaradas"
fi

titulo "RabbitMQ: arguments are x-queue-type, plus x-message-ttl on the retry queues; dead-letter, overflow, length and delivery limit come from policies"
R="$K -n pytstop-plataforma exec -i rabbitmq-0 -c rabbitmq --"
# rabbitmqadmin como admin, com a senha lida no proprio pod (admin.json).
# shellcheck disable=SC2016 # o sh -c roda no pod: $(...) e "$@" expandem la
adm() {
  $R sh -c 'export RABBITMQADMIN_USERNAME=admin RABBITMQADMIN_PASSWORD="$(sed -n "s/.*\"password\": \"\([^\"]*\)\".*/\1/p" /etc/rabbitmq/definitions/admin.json)"; exec rabbitmqadmin "$@"' rabbitmqadmin "$@"
}
filas() { $R rabbitmqctl -q list_queues --no-table-headers name messages | grep "^billing" | tr '\n' ' '; echo; }
# mensagens <regex>: soma das mensagens das filas cujo nome casa a regex (awk).
mensagens() { $R rabbitmqctl -q list_queues --no-table-headers name messages | awk -v padrao="$1" '$1 ~ padrao {soma += $2} END {print soma + 0}'; }
$R rabbitmqctl -q list_queues --no-table-headers name arguments policy | sort
$R rabbitmqctl -q list_policies --no-table-headers | cut -f2,5 | sort
printf 'max_message_size: '; $R rabbitmqctl -q eval 'application:get_env(rabbit, max_message_size).'
printf '1.1 MiB message: '
head -c 1153434 /dev/zero | tr '\0' x \
  | { adm publish message --exchange pytstop.dlx --routing-key billing.comandos --payload-file - 2>&1 || true; } \
  | grep -m1 PRECONDITION

titulo "retry: one queue per delay; copies published as the billing user (scripts/prova_retry.py, through a port-forward)"
# Publica pelo AMQP com o usuario do servico, nao pelo admin: so assim valem a
# permissao de topico e a conferencia do user_id. Porta local livre, lida da
# saida do port-forward.
senha_billing=$($K -n "$NS" get secret rabbitmq-credenciais -o jsonpath='{.data.senha-billing}' | base64 -d)
# O arquivo nasce antes: o redirecionamento do job em segundo plano so acontece
# no processo filho, e o sed abaixo sairia com erro se chegasse primeiro.
: > "$TMP/port-forward"
$K -n "$NS" port-forward svc/rabbitmq :5672 > "$TMP/port-forward" 2>&1 &
port_forward=$!
porta=""
for _ in $(seq 30); do
  porta=$(sed -n 's/^Forwarding from 127\.0\.0\.1:\([0-9]*\) .*/\1/p' "$TMP/port-forward")
  [ -n "$porta" ] && break
  sleep 1
done
[ -n "$porta" ] || cat "$TMP/port-forward" >&2
if RABBITMQ_URL="amqp://billing:$senha_billing@127.0.0.1:${porta:-0}/%2F" uv run --frozen python scripts/prova_retry.py; then
  prova_retry=held
else
  prova_retry=failed
fi
kill "$port_forward" 2>/dev/null || true
wait "$port_forward" 2>/dev/null || true  # sem o aviso "Terminated" do bash
port_forward=""
confere "retry proofs (scripts/prova_retry.py)" held "$prova_retry"
# A contagem das filas quorum no list_queues atualiza a cada ~5 s: espera as
# filas de retry do billing zerarem, por ate 30 s.
for _ in $(seq 15); do
  retidas=$(mensagens '^billing[.]comandos[.]retry[.]')
  [ "$retidas" = 0 ] && break
  sleep 2
done
filas
confere "billing.comandos retry queues drained" 0 "$retidas"
$R rabbitmqctl -q purge_queue billing.comandos

titulo "make redrive FILA=billing.comandos: the DLQ goes back to the queue"
adm publish message --exchange pytstop.dlx --routing-key billing.comandos --payload '{"smoke":"dlq"}' --properties '{"message_id":"smoke-dlq","headers":{"x-tentativa":5}}'
sleep 7
redrive=$(make --no-print-directory redrive FILA=billing.comandos KUBE_CONTEXT="$CONTEXTO")
printf '%s\n' "$redrive"
confere "redrive result" "after:  billing.comandos.dlq=0  billing.comandos=1" "$(printf '%s\n' "$redrive" | tail -1)"
$R rabbitmqctl -q purge_queue billing.comandos

titulo "an invalid object from one service does not take the others down (FallbackConfiguration)"
$K apply -f - <<YAML
apiVersion: configuration.konghq.com/v1
kind: KongClusterPlugin
metadata:
  name: smoke-plugin-invalido
  annotations:
    kubernetes.io/ingress.class: kong
plugin: rate-limiting
config:
  minute: -5
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: smoke-quebrado
  namespace: $NS
  labels:
    app.kubernetes.io/part-of: pytstop-smoke
  annotations:
    konghq.com/strip-path: "true"
    konghq.com/plugins: smoke-plugin-invalido
spec:
  ingressClassName: kong
  rules:
    - http:
        paths:
          - path: /os/quebrado
            pathType: Prefix
            backend:
              service:
                name: os-service-borda-api
                port:
                  number: 8000
YAML
sleep 5
echo "valid Ingress created after the invalid one:"
$K -n "$NS" create ingress smoke-novo --class=kong --rule='/os/novo*=os-service-borda-api:8000' \
  --annotation=konghq.com/strip-path=true
$K -n "$NS" label ingress smoke-novo "$ROTULO" >/dev/null
sleep 10
pede GET /os/api/v1/ordens-de-servico 200 /api/v1/ordens-de-servico
pede GET /os/novo/x 200 /api/v1/x
pede GET /os/quebrado/x 404
echo "make kong-check with the invalid plugin in the cluster:"
if KUBE_CONTEXT="$CONTEXTO" ESPERA=15 scripts/kong-check.sh; then
  echo "ERROR: kong-check should have failed"; exit 1
fi
$K delete kongclusterplugin smoke-plugin-invalido
$K -n "$NS" delete ingress smoke-quebrado smoke-novo
echo "make kong-check after deleting the invalid plugin:"
KUBE_CONTEXT="$CONTEXTO" ESPERA=10 scripts/kong-check.sh

titulo "Grafana: dashboards and alert rules loaded from provisioning"
if implantado Grafana; then
  grafana() { $K get --raw "/api/v1/namespaces/$NS/services/grafana:3000/proxy$1"; }
  grafana "/api/search?type=dash-db" | jq -r '.[] | "dashboard \(.uid): \(.title) (folder \(.folderTitle))"'
  # Logo depois do deploy a primeira avaliacao pega o Prometheus ainda sem dado
  # (erro ou sem dado); espera a avaliacao de regime, ate 3 minutos.
  for _ in $(seq 18); do
    grafana "/api/prometheus/grafana/api/v1/rules" \
      | jq -e '[.data.groups[].rules[] | select(.health != "ok" or .state != "inactive")] | length == 0' >/dev/null && break
    sleep 10
  done
  grafana "/api/prometheus/grafana/api/v1/rules" > "$TMP/regras.json"
  jq -r '.data.groups[].rules[] | "rule: \(.name) [\(.state), \(.health)]"' "$TMP/regras.json"
  # Uma regra por "- uid:" nos arquivos de observabilidade/grafana: sem a conta, um
  # arquivo que o Grafana nao carregou passaria calado.
  esperadas=$(cat observabilidade/grafana/alertas*.yaml | grep -c '^      - uid: ')
  confere "Grafana alert rules loaded" "$esperadas" "$(jq '[.data.groups[].rules[]] | length' "$TMP/regras.json")"
  confere "Grafana alert rules not healthy" "" "$(jq -r '[.data.groups[].rules[] | select(.health != "ok") | .name] | join(", ")' "$TMP/regras.json")"
fi

titulo "Prometheus: series returned now by each dashboard and alert query"
prometheus() {
  $K get --raw "/api/v1/namespaces/$NS/services/prometheus:9090/proxy/api/v1/query?query=$(jq -rn --arg q "$1" '$q|@uri')" \
    | jq '.data.result | length'
}
# shellcheck disable=SC2016 # $__rate_interval e do Grafana, vai literal ao sed
{ jq -r '.panels[].targets[].expr' observabilidade/dashboards/*.json; sed -n 's/^ *expr: //p' observabilidade/grafana/alertas*.yaml; } \
  | sed 's/\$__rate_interval/5m/g' | sort -u | while read -r consulta; do
    printf '%3s series  %s\n' "$(prometheus "$consulta")" "$consulta"
  done

titulo "hardening: effective securityContext of each platform container"
$K -n "$NS" get pods -o json | jq -r '
  def v(x): if x == null then "-" else (x | tostring) end;
  ["POD", "CONTAINER", "NON_ROOT", "PRIV_ESC", "RO_ROOTFS", "CAP_DROP", "SECCOMP", "SA_TOKEN"],
  (.items[] | select((.metadata.labels.app // "") as $app | $app != "os-service-api" and $app != "billing-service-api" and $app != "execution-service-api")
    | . as $p | .spec.containers[]
    | (.securityContext // {}) as $c | ($p.spec.securityContext // {}) as $ps
    | [($p.metadata.labels.app // $p.metadata.name), .name,
       v(if $c.runAsNonRoot != null then $c.runAsNonRoot else $ps.runAsNonRoot end),
       v($c.allowPrivilegeEscalation), v($c.readOnlyRootFilesystem),
       (($c.capabilities.drop // []) | join(",") | if . == "" then "-" else . end),
       v($c.seccompProfile.type // $ps.seccompProfile.type),
       v(if $p.spec.automountServiceAccountToken == null then true else $p.spec.automountServiceAccountToken end)])
  | @tsv' | sort -u | column -t

titulo "Pod Security restricted as enforce (server dry-run): only Promtail falls outside"
$K label --dry-run=server --overwrite namespace "$NS" pod-security.kubernetes.io/enforce=restricted 2>&1 \
  | grep -i 'warning' || echo "no pod outside the restricted profile"

# Por ultimo: reinicia o broker, e as consultas acima precisam dele de pe.
titulo "policies converge on boot: change the DLQ policy at runtime and restart the broker"
$R rabbitmqctl -q set_policy --apply-to queues dlq '\.dlq$' '{"message-ttl":60000}'
printf 'before restart: '; $R rabbitmqctl -q list_policies --no-table-headers | awk -F'\t' '$2 == "dlq" {print $5}'
$K -n pytstop-plataforma delete pod rabbitmq-0 --wait=true >/dev/null
$K -n pytstop-plataforma wait --for=condition=Ready pod/rabbitmq-0 --timeout=300s >/dev/null
depois=$($R rabbitmqctl -q list_policies --no-table-headers | awk -F'\t' '$2 == "dlq" {print $5}')
printf 'after restart:  %s\n' "$depois"
confere "DLQ policy back to the file value after the restart" '{"message-ttl":604800000}' "$depois"

pulados=""
[ "$PULADAS" -eq 0 ] || pulados=" ($PULADAS group(s) of checks skipped: $PULADOS)"
if [ "$FALHAS" -gt 0 ]; then
  printf '\nsmoke FAILED: %s check(s) did not hold%s:\n%s' "$FALHAS" "$pulados" "$RESUMO" >&2
  exit 1
fi
printf '\nsmoke OK: every check held%s\n' "$pulados"
