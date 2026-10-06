#!/usr/bin/env bash
# Roda o pipeline de cada config do Promtail, a do cluster e a do compose
# (promtail -dry-run), sobre linhas de exemplo e confere que os tokens do link
# de decisao e do checkout saem como ***, inclusive com a barra como %2F (o
# Kong loga o caminho como chegou, tambem o que ele barra com 404). Parte do
# make manifests. O job troca a descoberta (Kubernetes ou Docker) por um
# arquivo local e tira o relabel; os estagios de pipeline sao os de cada
# arquivo, sem copia.
set -euo pipefail

IMAGEM="${PROMTAIL_IMAGE:?set PROMTAIL_IMAGE}"

# Roda dentro da imagem do Promtail; a config entra por stdin (o Colima nao
# monta o /tmp do macOS) e o PREFIXO vem do ambiente.
read -r -d '' PIPELINE <<'SCRIPT' || true
cat > /tmp/promtail.yaml
awk '
  /^    relabel_configs:/ {exit}
  /^    [a-z]+_sd_configs:/ {
    print "    static_configs:"
    print "      - targets: [localhost]"
    print "        labels: {job: teste, __path__: /tmp/teste.log}"
    dentro = 1
    next
  }
  dentro && /^     / {next}
  {dentro = 0; print}
' /tmp/promtail.yaml | sed 's#/run/promtail/positions.yaml#/tmp/positions.yaml#' > /tmp/teste.yaml
cat > /tmp/teste.log <<LINHAS
${PREFIXO}172.22.0.1 - - [06/Oct/2026:20:00:00 +0000] "GET /billing/api/v1/publico/orcamentos/eyJvIjoiOGYyZCJ9.SEGREDO1 HTTP/1.1" 404 52
${PREFIXO}{"path": "/api/v1/publico/orcamentos/SEGREDO2/decisao", "status": 200}
${PREFIXO}"GET /billing/simulador/checkout/SEGREDO3?token=SEGREDO4&x=1 HTTP/1.1" 200 10
${PREFIXO}172.22.0.1 - - [06/Oct/2026:20:00:01 +0000] "GET /billing/api/v1/publico%2Forcamentos/SEGREDO5 HTTP/1.1" 404 103
${PREFIXO}172.22.0.1 - - [06/Oct/2026:20:00:02 +0000] "GET /billing/simulador%2fcheckout/123?token=SEGREDO6 HTTP/1.1" 404 103
${PREFIXO}{"path": "/api/v1/ordens-de-servico", "status": 200}
LINHAS
timeout 5 promtail -dry-run -config.file=/tmp/teste.yaml 2>/dev/null || true
SCRIPT

# confere <config> <prefixo de cada linha>: o cluster le o log no formato CRI
# (data, stream e flag antes da linha); o compose le a linha crua.
confere() {
  local config=$1 prefixo=$2 saida
  saida=$(docker run --rm -i --entrypoint sh -e "PREFIXO=$prefixo" "$IMAGEM" -c "$PIPELINE" < "$config" \
    | grep 'job="teste"' || true)
  echo ">> $config"
  echo "$saida" | cut -f2-
  # 5 linhas levam token e saem mascaradas; a sexta nao leva e passa como esta.
  if echo "$saida" | grep -q SEGREDO || [ "$(echo "$saida" | grep -c '\*\*\*')" -ne 5 ] \
      || [ "$(echo "$saida" | grep -c .)" -ne 6 ]; then
    echo "promtail-mask: unmasked token (or lost line) in the $config pipeline" >&2
    exit 1
  fi
}

confere k8s/base/observabilidade/config/promtail.yaml "2026-10-06T20:00:00.000000000Z stdout F "
confere compose/promtail.yml ""
echo "promtail-mask: tokens masked in the 5 lines that carried them, in the cluster and compose configs"
