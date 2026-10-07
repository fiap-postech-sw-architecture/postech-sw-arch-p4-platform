#!/usr/bin/env bash
# Teste negativo das regras do .gitleaks.toml (job gitleaks do CI; roda tambem
# na maquina local, com o gitleaks do PATH): a URL AMQP com a senha que o make
# deploy gera reprova num manifesto, e a senha de demonstracao so passa no
# compose, e senha apagada no commit seguinte ainda reprova no historico. Sem
# ele, uma regra que nao casa mais nada passaria verde.
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
# Historico: senha commitada e apagada no commit seguinte continua reprovando
# com o mesmo escopo do CI (--log-opts="HEAD").
repo="$dir/historico"
git init -q "$repo"
git -C "$repo" -c user.name=teste -c user.email=teste@example.invalid commit -q --allow-empty -m inicio
mkdir -p "$repo/k8s"
url "$(openssl rand -hex 24)" > "$repo/k8s/vazou.yaml"
git -C "$repo" add k8s/vazou.yaml
git -C "$repo" -c user.name=teste -c user.email=teste@example.invalid commit -q -m vaza
git -C "$repo" rm -q k8s/vazou.yaml
git -C "$repo" -c user.name=teste -c user.email=teste@example.invalid commit -q -m apaga
if gitleaks git "$repo" --log-opts="HEAD" --config "$raiz/.gitleaks.toml" --no-banner --redact >/dev/null 2>&1; then
  echo "gitleaks passed a password committed and deleted in the next commit" >&2
  exit 1
fi
echo "gitleaks rules hold: generated and demo passwords flagged in k8s/, demo password allowed in compose/, deleted password still flagged in history"
