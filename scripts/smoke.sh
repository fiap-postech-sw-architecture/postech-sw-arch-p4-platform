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
TMP="$(mktemp -d)"
limpa() {
  $K delete kongclusterplugin smoke-plugin-invalido --ignore-not-found >/dev/null
  $K -n "$NS" delete deployment,service,ingress -l "$ROTULO" --ignore-not-found >/dev/null
  rm -rf "$TMP"
}

# O exemplo usa os caminhos /os do OS Service de verdade.
if [ -n "$($K -n pytstop-os get ingress -o name 2>/dev/null)" ]; then
  echo "pytstop-os ja tem Ingress: o smoke usaria os mesmos caminhos /os. Rode num cluster so com a plataforma." >&2
  exit 1
fi
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
  printf '%-4s %-37s -> %s  servico recebeu: %-30s balde: %s/min, resta %s\n' \
    "$1" "$2" "$status" "$recebido" "${limite:--}" "${resta:--}"
}

titulo "borda: k8s/exemplos/borda-os-service.yaml como esta, com eco no lugar da API"
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

titulo "caminhos publicados e bloqueados"
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

titulo "X-Request-ID: o mesmo id na resposta e no que o servico recebeu"
curl -s -D "$TMP/h" -o "$TMP/b" "$BORDA/os/api/v1/ordens-de-servico"
printf 'resposta:          %s\n' "$(cabecalho x-request-id)"
printf 'servico recebeu:   %s\n' "$(jq -r '.headers["x-request-id"]' "$TMP/b")"

titulo "rate limiting do login (5/min, x10 no kind): 51 POSTs seguidos (o POST da lista acima conta se cair no mesmo minuto)"
# Janela fixa por minuto: comeca longe da virada para a rajada caber nela.
while [ "$((10#$(date +%S)))" -ge 50 ]; do sleep 1; done
for _ in $(seq 51); do
  curl -s -o /dev/null -w '%{http_code}\n' -X POST "$BORDA/os/api/v1/autenticacao/login"
done | sort | uniq -c
echo "balde proprio: o refresh continua respondendo"
pede POST /os/api/v1/autenticacao/refresh
printf 'IP que o Kong viu (ultima linha do access log): '
$K -n pytstop-plataforma logs deployment/kong -c proxy --tail=1 | awk '{print $1}'

titulo "token do link de decisao e do checkout fora do Loki (Promtail mascara antes de enviar)"
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
printf 'linhas do Kong no Loki com o token %s: %s\n' "$segredo" "$(loki "{app=\"kong\"} |= \"$segredo\"" | grep -c . || true)"
echo "as mesmas requisicoes como o Loki guardou:"
loki '{app="kong"} |~ "/billing/(api/v1/publico/orcamentos|simulador/checkout)/"' | head -2

titulo "RabbitMQ: argumento so x-queue-type; TTL, dead-letter, overflow e tamanho por policy"
R="$K -n pytstop-plataforma exec -i rabbitmq-0 -c rabbitmq --"
# rabbitmqadmin como admin, com a senha lida no proprio pod (admin.json).
adm() {
  $R sh -c 'export RABBITMQADMIN_USERNAME=admin RABBITMQADMIN_PASSWORD="$(sed -n "s/.*\"password\": \"\([^\"]*\)\".*/\1/p" /etc/rabbitmq/definitions/admin.json)"; exec rabbitmqadmin "$@"' rabbitmqadmin "$@"
}
filas() { $R rabbitmqctl -q list_queues --no-table-headers name messages | grep "^billing" | tr '\n' ' '; echo; }
$R rabbitmqctl -q list_queues --no-table-headers name arguments policy | sort
$R rabbitmqctl -q list_policies --no-table-headers | cut -f2,5 | sort
printf 'max_message_size: '; $R rabbitmqctl -q eval 'application:get_env(rabbit, max_message_size).'
printf 'mensagem de 1,1 MiB: '
head -c 1153434 /dev/zero | tr '\0' x \
  | { adm publish message --exchange pytstop.dlx --routing-key billing.comandos --payload-file - 2>&1 || true; } \
  | grep -m1 PRECONDITION

titulo "retry: copia com expiration de 1 s no pytstop.retry volta para billing.comandos"
adm publish message --exchange pytstop.retry --routing-key billing.comandos --payload '{"smoke":"retry"}' --properties '{"expiration":"1000","headers":{"x-tentativa":1}}'
sleep 7  # a contagem das filas quorum e atualizada a cada 5 s
filas
$R rabbitmqctl -q purge_queue billing.comandos

titulo "make redrive FILA=billing.comandos: a DLQ volta para a fila"
adm publish message --exchange pytstop.dlx --routing-key billing.comandos --payload '{"smoke":"dlq"}' --properties '{"message_id":"smoke-dlq","headers":{"x-tentativa":5}}'
sleep 7
make --no-print-directory redrive FILA=billing.comandos KUBE_CONTEXT="$CONTEXTO"
$R rabbitmqctl -q purge_queue billing.comandos

titulo "policies convergem no boot: muda a da DLQ em tempo de execucao e reinicia o broker"
$R rabbitmqctl -q set_policy --apply-to queues dlq '\.dlq$' '{"message-ttl":60000}'
printf 'antes do restart: '; $R rabbitmqctl -q list_policies --no-table-headers | awk -F'\t' '$2 == "dlq" {print $5}'
$K -n pytstop-plataforma delete pod rabbitmq-0 --wait=true >/dev/null
$K -n pytstop-plataforma wait --for=condition=Ready pod/rabbitmq-0 --timeout=300s >/dev/null
printf 'depois do restart: '; $R rabbitmqctl -q list_policies --no-table-headers | awk -F'\t' '$2 == "dlq" {print $5}'

titulo "configuracao invalida de um servico nao derruba as outras (FallbackConfiguration)"
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
echo "Ingress valido criado depois do invalido:"
$K -n "$NS" create ingress smoke-novo --class=kong --rule='/os/novo*=os-service-borda-api:8000' \
  --annotation=konghq.com/strip-path=true
$K -n "$NS" label ingress smoke-novo "$ROTULO" >/dev/null
sleep 10
pede GET /os/api/v1/ordens-de-servico
pede GET /os/novo/x
pede GET /os/quebrado/x
echo "make kong-check com o plugin invalido no cluster:"
if KUBE_CONTEXT="$CONTEXTO" ESPERA=15 scripts/kong-check.sh; then
  echo "ERRO: o kong-check deveria ter falhado"; exit 1
fi
$K delete kongclusterplugin smoke-plugin-invalido
$K -n "$NS" delete ingress smoke-quebrado smoke-novo
echo "make kong-check depois de apagar o plugin invalido:"
KUBE_CONTEXT="$CONTEXTO" ESPERA=10 scripts/kong-check.sh

titulo "Grafana: dashboards e regras de alerta carregados do provisioning"
grafana() { $K get --raw "/api/v1/namespaces/$NS/services/grafana:3000/proxy$1"; }
grafana "/api/search?type=dash-db" | jq -r '.[] | "dashboard \(.uid): \(.title) (pasta \(.folderTitle))"'
grafana "/api/prometheus/grafana/api/v1/rules" | jq -r '.data.groups[].rules[] | "regra: \(.name) [\(.state), \(.health)]"'

titulo "Prometheus: series que cada consulta do dashboard e dos alertas devolve agora"
prometheus() {
  $K get --raw "/api/v1/namespaces/$NS/services/prometheus:9090/proxy/api/v1/query?query=$(jq -rn --arg q "$1" '$q|@uri')" \
    | jq '.data.result | length'
}
{ jq -r '.panels[].targets[].expr' observabilidade/dashboards/*.json; sed -n 's/^ *expr: //p' observabilidade/grafana/alertas.yaml; } \
  | sed 's/\$__rate_interval/5m/g' | sort -u | while read -r consulta; do
    printf '%3s series  %s\n' "$(prometheus "$consulta")" "$consulta"
  done

titulo "endurecimento: securityContext efetivo de cada container da plataforma"
$K -n "$NS" get pods -o json | jq -r '
  def v(x): if x == null then "-" else (x | tostring) end;
  ["POD", "CONTAINER", "NAO_ROOT", "ESCALA_PRIV", "RAIZ_SO_LEITURA", "CAP_DROP", "SECCOMP", "TOKEN_SA"],
  (.items[] | select(.metadata.labels.app != "os-service-api") | . as $p | .spec.containers[]
    | (.securityContext // {}) as $c | ($p.spec.securityContext // {}) as $ps
    | [($p.metadata.labels.app // $p.metadata.name), .name,
       v(if $c.runAsNonRoot != null then $c.runAsNonRoot else $ps.runAsNonRoot end),
       v($c.allowPrivilegeEscalation), v($c.readOnlyRootFilesystem),
       (($c.capabilities.drop // []) | join(",") | if . == "" then "-" else . end),
       v($c.seccompProfile.type // $ps.seccompProfile.type),
       v(if $p.spec.automountServiceAccountToken == null then true else $p.spec.automountServiceAccountToken end)])
  | @tsv' | sort -u | column -t

titulo "Pod Security restricted como enforce (dry-run no servidor): so o Promtail fica fora"
$K label --dry-run=server --overwrite namespace "$NS" pod-security.kubernetes.io/enforce=restricted 2>&1 \
  | grep -i 'warning' || echo "nenhum pod fora do perfil restricted"
