#!/usr/bin/env bash
# Smoke da plataforma num cluster so com a plataforma implantada (make kind-up
# deploy smoke). Aplica o exemplo de borda de k8s/exemplos/ com um servidor de
# eco no lugar da API e confere borda, rate limiting, mascara de token no
# Loki, policies e redrive do RabbitMQ, fallback do Kong e o endurecimento dos
# pods. A saida e a evidencia: cada linha diz o que foi pedido e o que voltou.
#
# Os objetos de teste vao para o pytstop-plataforma (o Kong so le Ingress dos
# namespaces da fase 4), com o rotulo part-of=pytstop-smoke, e saem no fim.
set -euo pipefail

CONTEXTO="${KUBE_CONTEXT:-kind-pytstop-p4}"
BORDA="${BORDA:-http://localhost}"
NS=pytstop-plataforma
ROTULO=app.kubernetes.io/part-of=pytstop-smoke
K="kubectl --context $CONTEXTO"
limpa() {
  $K delete kongclusterplugin smoke-plugin-invalido --ignore-not-found >/dev/null
  $K -n "$NS" delete deployment,service,ingress -l "$ROTULO" --ignore-not-found >/dev/null
  rm -rf "$TMP"
}

# O exemplo usa os caminhos /os do OS Service de verdade.
if [ -n "$($K -n pytstop-os get ingress -o name 2>/dev/null)" ]; then
  echo "pytstop-os already has Ingresses: the smoke would reuse the /os paths. Run it on a platform-only cluster." >&2
  exit 1
fi
TMP="$(mktemp -d)"
trap limpa EXIT

titulo() { printf '\n== %s\n' "$*"; }

cabecalho() { tr -d '\r' < "$TMP/h" | awk -v nome="$1:" 'tolower($1) == nome {print $2}'; }

# pede <metodo> <caminho>: status, o caminho que o eco recebeu e o balde de
# rate limiting da rota (limite por minuto e quanto sobra nele).
pede() {
  local status recebido limite resta
  status=$(curl -s -X "$1" -D "$TMP/h" -o "$TMP/b" -w '%{http_code}' "$BORDA$2")
  recebido=$(jq -r '.path // "-"' "$TMP/b" 2>/dev/null || echo -)
  limite=$(cabecalho x-ratelimit-limit-minute)
  resta=$(cabecalho x-ratelimit-remaining-minute)
  printf '%-4s %-37s -> %s  upstream got: %-30s bucket: %s/min, %s left\n' \
    "$1" "$2" "$status" "$recebido" "${limite:--}" "${resta:--}"
}

titulo "edge: k8s/exemplos/borda-os-service.yaml as is, with an echo server in place of the API"
$K -n "$NS" apply -f - >/dev/null <<'YAML'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: os-service-api
  labels:
    app.kubernetes.io/part-of: pytstop-smoke
spec:
  selector:
    matchLabels:
      app: os-service-api
  template:
    metadata:
      labels:
        app: os-service-api
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
$K -n "$NS" apply -f k8s/exemplos/borda-os-service.yaml
$K -n "$NS" label -f k8s/exemplos/borda-os-service.yaml "$ROTULO" >/dev/null
$K -n "$NS" rollout status deployment/os-service-api --timeout=180s
# O controller leva alguns segundos para empurrar as rotas novas ao Kong.
for _ in $(seq 60); do
  [ "$(curl -s -o /dev/null -w '%{http_code}' "$BORDA/os/openapi.json")" = 200 ] && break
  sleep 2
done

titulo "published and blocked paths"
pede GET /os/api/v1/ordens-de-servico
pede GET /os/docs
pede GET /os/openapi.json
pede GET /os/.well-known/jwks.json
pede POST /os/api/v1/publico/acompanhamento
pede POST /os/api/v1/autenticacao/refresh
pede POST /os/api/v1/autenticacao/login
pede GET /os/metrics
pede GET /os/api/v1/admin/outbox
pede GET /os/saude

titulo "X-Request-ID: same id in the response and in what the upstream got"
curl -s -D "$TMP/h" -o "$TMP/b" "$BORDA/os/api/v1/ordens-de-servico"
printf 'response:       %s\n' "$(cabecalho x-request-id)"
printf 'upstream got:   %s\n' "$(jq -r '.headers["x-request-id"]' "$TMP/b")"

titulo "login rate limit (5/min, x10 on kind): 51 POSTs in a row (the POST above counts if it fell in the same minute)"
# Janela fixa por minuto: comeca longe da virada para a rajada caber nela.
while [ "$((10#$(date +%S)))" -ge 50 ]; do sleep 1; done
for _ in $(seq 51); do
  curl -s -o /dev/null -w '%{http_code}\n' -X POST "$BORDA/os/api/v1/autenticacao/login"
done | sort | uniq -c
echo "separate bucket: refresh still answers"
pede POST /os/api/v1/autenticacao/refresh
printf 'client IP seen by Kong (last access log line): '
$K -n pytstop-plataforma logs deployment/kong -c proxy --tail=1 | awk '{print $1}'

titulo "decision link and checkout tokens kept out of Loki (Promtail masks before pushing)"
segredo="tokensmoke$(date +%s)"
pede GET "/billing/api/v1/publico/orcamentos/$segredo"
pede GET "/billing/simulador/checkout/123?token=$segredo"
# loki <LogQL>: linhas dos ultimos 5 minutos, pela API do Kubernetes (sem port-forward).
loki() {
  $K get --raw "/api/v1/namespaces/pytstop-plataforma/services/loki:3100/proxy/loki/api/v1/query_range?limit=10&since=5m&query=$(jq -rn --arg q "$1" '$q|@uri')" \
    | jq -r '.data.result[].values[][1]'
}
for _ in $(seq 30); do
  [ -n "$(loki '{app="kong"} |= "/billing/simulador/checkout/***"')" ] && break
  sleep 2
done
printf 'Kong lines in Loki with token %s: %s\n' "$segredo" "$(loki "{app=\"kong\"} |= \"$segredo\"" | grep -c . || true)"
echo "the same requests as stored in Loki:"
loki '{app="kong"} |~ "/billing/(api/v1/publico/orcamentos|simulador/checkout)/"' | head -2

titulo "RabbitMQ: x-queue-type is the only argument; TTL, dead-letter, overflow and length come from policies"
R="$K -n pytstop-plataforma exec -i rabbitmq-0 -c rabbitmq --"
# rabbitmqadmin como admin, com a senha lida no proprio pod (admin.json).
adm() {
  $R sh -c 'export RABBITMQADMIN_USERNAME=admin RABBITMQADMIN_PASSWORD="$(sed -n "s/.*\"password\": \"\([^\"]*\)\".*/\1/p" /etc/rabbitmq/definitions/admin.json)"; exec rabbitmqadmin "$@"' rabbitmqadmin "$@"
}
filas() { $R rabbitmqctl -q list_queues --no-table-headers name messages | grep "^billing" | tr '\n' ' '; echo; }
$R rabbitmqctl -q list_queues --no-table-headers name arguments policy | sort
$R rabbitmqctl -q list_policies --no-table-headers | cut -f2,5 | sort
printf 'max_message_size: '; $R rabbitmqctl -q eval 'application:get_env(rabbit, max_message_size).'
printf '1.1 MiB message: '
head -c 1153434 /dev/zero | tr '\0' x \
  | { adm publish message --exchange pytstop.dlx --routing-key billing.comandos --payload-file - 2>&1 || true; } \
  | grep -m1 PRECONDITION

titulo "retry: copy with 1 s expiration on pytstop.retry comes back to billing.comandos"
adm publish message --exchange pytstop.retry --routing-key billing.comandos --payload '{"smoke":"retry"}' --properties '{"expiration":"1000","headers":{"x-tentativa":1}}'
sleep 7  # a contagem das filas quorum e atualizada a cada 5 s
filas
$R rabbitmqctl -q purge_queue billing.comandos

titulo "make redrive FILA=billing.comandos: the DLQ goes back to the queue"
adm publish message --exchange pytstop.dlx --routing-key billing.comandos --payload '{"smoke":"dlq"}' --properties '{"message_id":"smoke-dlq","headers":{"x-tentativa":5}}'
sleep 7
make --no-print-directory redrive FILA=billing.comandos KUBE_CONTEXT="$CONTEXTO"
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
pede GET /os/api/v1/ordens-de-servico
pede GET /os/novo/x
pede GET /os/quebrado/x
echo "make kong-check with the invalid plugin in the cluster:"
if KUBE_CONTEXT="$CONTEXTO" ESPERA=15 scripts/kong-check.sh; then
  echo "ERROR: kong-check should have failed"; exit 1
fi
$K delete kongclusterplugin smoke-plugin-invalido
$K -n "$NS" delete ingress smoke-quebrado smoke-novo
echo "make kong-check after deleting the invalid plugin:"
KUBE_CONTEXT="$CONTEXTO" ESPERA=10 scripts/kong-check.sh

titulo "Grafana: dashboards and alert rules loaded from provisioning"
grafana() { $K get --raw "/api/v1/namespaces/$NS/services/grafana:3000/proxy$1"; }
grafana "/api/search?type=dash-db" | jq -r '.[] | "dashboard \(.uid): \(.title) (folder \(.folderTitle))"'
# Logo depois do deploy a primeira avaliacao pega o Prometheus ainda sem dado
# (erro ou sem dado); espera a avaliacao de regime, ate 3 minutos.
for _ in $(seq 18); do
  grafana "/api/prometheus/grafana/api/v1/rules" \
    | jq -e '[.data.groups[].rules[] | select(.health != "ok" or .state != "inactive")] | length == 0' >/dev/null && break
  sleep 10
done
grafana "/api/prometheus/grafana/api/v1/rules" | jq -r '.data.groups[].rules[] | "rule: \(.name) [\(.state), \(.health)]"'

titulo "Prometheus: series returned now by each dashboard and alert query"
prometheus() {
  $K get --raw "/api/v1/namespaces/$NS/services/prometheus:9090/proxy/api/v1/query?query=$(jq -rn --arg q "$1" '$q|@uri')" \
    | jq '.data.result | length'
}
{ jq -r '.panels[].targets[].expr' observabilidade/dashboards/*.json; sed -n 's/^ *expr: //p' observabilidade/grafana/alertas.yaml; } \
  | sed 's/\$__rate_interval/5m/g' | sort -u | while read -r consulta; do
    printf '%3s series  %s\n' "$(prometheus "$consulta")" "$consulta"
  done

titulo "hardening: effective securityContext of each platform container"
$K -n "$NS" get pods -o json | jq -r '
  def v(x): if x == null then "-" else (x | tostring) end;
  ["POD", "CONTAINER", "NON_ROOT", "PRIV_ESC", "RO_ROOTFS", "CAP_DROP", "SECCOMP", "SA_TOKEN"],
  (.items[] | select(.metadata.labels.app != "os-service-api") | . as $p | .spec.containers[]
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
printf 'after restart:  '; $R rabbitmqctl -q list_policies --no-table-headers | awk -F'\t' '$2 == "dlq" {print $5}'
