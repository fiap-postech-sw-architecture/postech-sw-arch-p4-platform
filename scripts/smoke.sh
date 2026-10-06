#!/usr/bin/env bash
# Smoke da plataforma num cluster ja implantado (make kind-up deploy smoke).
# Aplica o exemplo de borda de k8s/exemplos/ com um servidor de eco no lugar
# da API, num namespace proprio que sai no fim, e confere a borda e o rate
# limiting. A saida e a evidencia: cada linha diz o que foi pedido e o que
# voltou.
set -euo pipefail

CONTEXTO="${KUBE_CONTEXT:-kind-pytstop-p4}"
BORDA="${BORDA:-http://localhost}"
NS_SMOKE=pytstop-smoke
K="kubectl --context $CONTEXTO"
TMP="$(mktemp -d)"
trap '$K delete namespace "$NS_SMOKE" --ignore-not-found --wait=false >/dev/null; rm -rf "$TMP"' EXIT

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

titulo "borda: k8s/exemplos/borda-os-service.yaml em $NS_SMOKE, com eco no lugar da API"
$K create namespace "$NS_SMOKE" --dry-run=client -o yaml | $K apply -f - >/dev/null
$K -n "$NS_SMOKE" apply -f - >/dev/null <<'YAML'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: os-service-api
spec:
  selector:
    matchLabels:
      app: os-service-api
  template:
    metadata:
      labels:
        app: os-service-api
    spec:
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
YAML
$K -n "$NS_SMOKE" apply -f k8s/exemplos/borda-os-service.yaml
$K -n "$NS_SMOKE" rollout status deployment/os-service-api --timeout=180s
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
