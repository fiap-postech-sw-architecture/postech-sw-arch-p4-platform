#!/usr/bin/env bash
# Prova a regra "Saga parada" (observabilidade/grafana/alertas.yaml, ADR-043)
# no promtool, com a consulta tirada do proprio arquivo: o prazo vencido
# dispara sem a serie de falha_na_compensacao, a falha dispara sem a serie do
# prazo, e atraso abaixo de 60 s, outra etapa ou nenhuma serie da saga (OS
# Service ainda sem as metricas) nao disparam. Cada replica da API repete o
# gauge: duas replicas a 40 s somam 80 s e nao disparam, o que reprova a troca
# de max por sum. O threshold do Grafana (A > 0) e a janela de 5 min viram uma
# regra do Prometheus com a mesma consulta.
set -euo pipefail
: "${PROMETHEUS_IMAGE:?}" "${YQ_IMAGE:?}"

expr=$(docker run --rm -i "$YQ_IMAGE" \
  '.groups[].rules[] | select(.uid == "pytstop-saga-parada") | .data[] | select(.refId == "A") | .model.expr' \
  < observabilidade/grafana/alertas.yaml)
if [ -z "$expr" ] || [ "$expr" = null ]; then
  echo "rule pytstop-saga-parada not found in observabilidade/grafana/alertas.yaml" >&2
  exit 1
fi
echo "rule pytstop-saga-parada: $expr"

# O teste vai pelo stdin e a regra pelo ambiente: o colima nao compartilha o
# TMPDIR do macOS com a VM.
docker run --rm -i -e EXPR="$expr" --entrypoint sh "$PROMETHEUS_IMAGE" -c '
  cd /tmp && cat > teste.yml &&
  printf "groups:\n  - name: saga\n    rules:\n      - alert: SagaParada\n        for: 5m\n        expr: |-\n          (%s) > 0\n" "$EXPR" > regras.yml &&
  promtool test rules teste.yml' <<'TESTE'
rule_files: [regras.yml]
evaluation_interval: 1m
tests:
  - name: prazo vencido ha 90 s, sem a serie de falha_na_compensacao
    interval: 1m
    input_series:
      # Cada replica da API repete o valor do coletor.
      - series: pytstop_saga_prazo_vencido_segundos{pod="os-api-1"}
        values: 90x10
      - series: pytstop_saga_prazo_vencido_segundos{pod="os-api-2"}
        values: 90x10
    alert_rule_test:
      - eval_time: 4m
        alertname: SagaParada
        exp_alerts: []
      - eval_time: 6m
        alertname: SagaParada
        exp_alerts:
          - exp_labels: {}
  - name: instancia em falha_na_compensacao, sem a serie do prazo
    interval: 1m
    input_series:
      - series: pytstop_saga_ativas{pod="os-api-1", etapa="falha_na_compensacao"}
        values: 1x10
    alert_rule_test:
      - eval_time: 6m
        alertname: SagaParada
        exp_alerts:
          - exp_labels: {}
  - name: atraso de 45 s e instancias so em outras etapas
    interval: 1m
    input_series:
      - series: pytstop_saga_prazo_vencido_segundos{pod="os-api-1"}
        values: 45x10
      - series: pytstop_saga_ativas{pod="os-api-1", etapa="compensando"}
        values: 2x10
      - series: pytstop_saga_ativas{pod="os-api-1", etapa="falha_na_compensacao"}
        values: 0x10
    alert_rule_test:
      - eval_time: 6m
        alertname: SagaParada
        exp_alerts: []
  - name: duas replicas a 40 s, soma acima de 60 s e maximo abaixo
    interval: 1m
    input_series:
      - series: pytstop_saga_prazo_vencido_segundos{pod="os-api-1"}
        values: 40x10
      - series: pytstop_saga_prazo_vencido_segundos{pod="os-api-2"}
        values: 40x10
    alert_rule_test:
      - eval_time: 6m
        alertname: SagaParada
        exp_alerts: []
  - name: nenhuma serie da saga
    interval: 1m
    input_series:
      - series: up{job="os-service-api"}
        values: 1x10
    alert_rule_test:
      - eval_time: 6m
        alertname: SagaParada
        exp_alerts: []
TESTE
