#!/usr/bin/env bash
# Roda o pipeline do config/promtail.yaml (promtail -dry-run) sobre linhas de
# exemplo e confere que os tokens do link de decisao e do checkout saem como
# ***. Parte do make manifests. O job troca a descoberta do Kubernetes por um
# arquivo local; os estagios de pipeline sao os do arquivo, sem copia.
set -euo pipefail

IMAGEM="${PROMTAIL_IMAGE:?defina PROMTAIL_IMAGE}"
CONFIG=k8s/base/observabilidade/config/promtail.yaml

saida=$(docker run --rm -i --entrypoint sh "$IMAGEM" -c '
cat > /tmp/promtail.yaml
sed -e "/^    relabel_configs:/,\$d" \
    -e "s#^    kubernetes_sd_configs:#    static_configs:#" \
    -e "s#^      - role: pod#      - targets: [localhost]\n        labels: {job: teste, __path__: /tmp/teste.log}#" \
    -e "s#/run/promtail/positions.yaml#/tmp/positions.yaml#" /tmp/promtail.yaml > /tmp/teste.yaml
printf "%s\n" \
  "2026-10-06T20:00:00.000000000Z stdout F 172.22.0.1 - - [06/Oct/2026:20:00:00 +0000] \"GET /billing/api/v1/publico/orcamentos/eyJvIjoiOGYyZCJ9.SEGREDO1 HTTP/1.1\" 404 52" \
  "2026-10-06T20:00:01.000000000Z stdout F {\"path\": \"/api/v1/publico/orcamentos/SEGREDO2/decisao\", \"status\": 200}" \
  "2026-10-06T20:00:02.000000000Z stdout F \"GET /billing/simulador/checkout/SEGREDO3?token=SEGREDO4&x=1 HTTP/1.1\" 200 10" \
  "2026-10-06T20:00:03.000000000Z stdout F {\"path\": \"/api/v1/ordens-de-servico\", \"status\": 200}" > /tmp/teste.log
timeout 5 promtail -dry-run -config.file=/tmp/teste.yaml 2>/dev/null || true
' < "$CONFIG" | grep 'job="teste"' || true)

echo "$saida" | cut -f2-
if echo "$saida" | grep -q SEGREDO || [ "$(echo "$saida" | grep -c '\*\*\*')" -ne 3 ]; then
  echo "promtail-mascara: token sem mascara (ou linha perdida) no pipeline de $CONFIG" >&2
  exit 1
fi
echo "promtail-mascara: tokens mascarados nas 3 linhas que os traziam"
