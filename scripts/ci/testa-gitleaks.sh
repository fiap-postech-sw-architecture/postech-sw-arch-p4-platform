#!/usr/bin/env bash
# Teste negativo das regras do .gitleaks.toml (job gitleaks do CI; roda tambem
# na maquina local, com o gitleaks do PATH): a URL AMQP com a senha que o make
# deploy gera reprova num manifesto, e a senha de demonstracao so passa no
# compose. Sem ele, uma regra que nao casa mais nada passaria verde.
set -euo pipefail

raiz=$(cd "$(dirname "$0")/../.." && pwd)
dir=$(mktemp -d)
trap 'rm -rf "$dir"' EXIT
mkdir -p "$dir/k8s" "$dir/compose"

# url <senha>: a linha do Secret rabbitmq de um servico.
url() { printf 'RABBITMQ_URL: "amqp://os:%s@rabbitmq.pytstop-plataforma.svc.cluster.local:5672/%%2F"\n' "$1"; }
url "$(openssl rand -hex 24)" > "$dir/k8s/senha-gerada.yaml"
url pytstop-os-demo-2026 > "$dir/k8s/senha-de-demonstracao.yaml"
url pytstop-os-demo-2026 > "$dir/compose/senha-de-demonstracao.yaml"

gitleaks dir "$dir" --config "$raiz/.gitleaks.toml" --no-banner --redact --exit-code 0 \
  --report-format json --report-path "$dir/achados.json"
achados=$(jq -r '[.[] | .RuleID + " " + (.File | split("/") | .[-2:] | join("/"))] | sort | join(", ")' "$dir/achados.json")
esperado="pytstop-url-amqp-com-senha k8s/senha-de-demonstracao.yaml, pytstop-url-amqp-com-senha k8s/senha-gerada.yaml"
if [ "$achados" != "$esperado" ]; then
  echo "gitleaks found [$achados], expected [$esperado]" >&2
  exit 1
fi
echo "gitleaks rules hold: generated and demo passwords flagged in k8s/, demo password allowed in compose/"
