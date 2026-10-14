#!/usr/bin/env bash
# Prova a regra "Saga parada" (observabilidade/grafana/alertas.yaml, ADR-043)
# no promtool, com a consulta, o limiar e a janela (`for`) tirados do proprio
# arquivo: o prazo vencido dispara sem as outras series, a falha dispara sem a
# serie do prazo, o coletor das sagas em 0 (em uma das replicas) dispara, a
# serie do coletor ausente dispara se a API do OS Service esta de pe (inclusive
# com uma replica caida), e nao disparam atraso abaixo de 60 s, outra etapa,
# coletor sadio, queda do coletor mais curta que a janela e nenhum alvo da API
# na descoberta. Pod fora da descoberta (replicas 0, Pending, apagado) nao deixa
# serie `up`, e o `pytstop-alvo-fora` so dispara com `up = 0`: ali so o 5xx do
# gateway, com trafego, acusa. Cada replica da API repete o gauge: duas replicas
# a 40 s somam 80 s e nao disparam, o que reprova a troca de max por sum; uma
# replica com o coletor em 0 e outra em 1 reprova a troca de min por max; e uma
# replica com `up` em 0 e outra em 1, sem a serie do coletor, reprova a troca
# de max por min no `up`. O threshold do Grafana (so `gt` e o valor de
# params[0]) e a janela viram uma regra do Prometheus com a mesma consulta.
set -euo pipefail
: "${PROMETHEUS_IMAGE:?}" "${YQ_IMAGE:?}"

# consulta <yq>: o valor, no alertas.yaml, da regra pytstop-saga-parada.
consulta() {
  docker run --rm -i "$YQ_IMAGE" \
    ".groups[].rules[] | select(.uid == \"pytstop-saga-parada\") | $1" \
    < observabilidade/grafana/alertas.yaml
}
expr=$(consulta '.data[] | select(.refId == "A") | .model.expr')
janela=$(consulta '.for')
tipo=$(consulta '.data[] | select(.refId == "C") | .model.conditions[0].evaluator.type')
limiar=$(consulta '.data[] | select(.refId == "C") | .model.conditions[0].evaluator.params[0]')
if [ -z "$expr" ] || [ "$expr" = null ]; then
  echo "rule pytstop-saga-parada not found in observabilidade/grafana/alertas.yaml" >&2
  exit 1
fi
if [ "$tipo" != gt ]; then
  echo "rule pytstop-saga-parada: threshold type '$tipo' is not gt; the test rule only models gt" >&2
  exit 1
fi
case "$janela" in *[!0-9m]* | "" | null) echo "rule pytstop-saga-parada: unexpected for: '$janela'" >&2; exit 1 ;; esac
case "$limiar" in *[!0-9.]* | "") echo "rule pytstop-saga-parada: unexpected threshold '$limiar'" >&2; exit 1 ;; esac
echo "rule pytstop-saga-parada (for $janela, > $limiar): $expr"

# O teste vai pelo stdin e a regra pelo ambiente: o colima nao compartilha o
# TMPDIR do macOS com a VM.
docker run --rm -i -e EXPR="$expr" -e JANELA="$janela" -e LIMIAR="$limiar" --entrypoint sh "$PROMETHEUS_IMAGE" -c '
  cd /tmp && cat > teste.yml &&
  printf "groups:\n  - name: saga\n    rules:\n      - alert: SagaParada\n        for: %s\n        expr: |-\n          (%s) > %s\n" "$JANELA" "$EXPR" "$LIMIAR" > regras.yml &&
  promtool test rules teste.yml' <<'TESTE'
rule_files: [regras.yml]
evaluation_interval: 1m
tests:
  - name: prazo vencido ha 90 s, sem as series de falha_na_compensacao e do coletor
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
  - name: coletor das sagas em 0 numa das duas replicas, com as outras series sadias
    interval: 1m
    input_series:
      - series: pytstop_saga_coletor_disponivel{pod="os-api-1"}
        values: 1x10
      - series: pytstop_saga_coletor_disponivel{pod="os-api-2"}
        values: 0x10
      - series: up{job="os-service-api", pod="os-api-1"}
        values: 1x10
    alert_rule_test:
      - eval_time: 4m
        alertname: SagaParada
        exp_alerts: []
      - eval_time: 6m
        alertname: SagaParada
        exp_alerts:
          - exp_labels: {}
  - name: serie do coletor ausente com a API do OS Service de pe
    interval: 1m
    input_series:
      - series: up{job="os-service-api", pod="os-api-1"}
        values: 1x10
    alert_rule_test:
      - eval_time: 4m
        alertname: SagaParada
        exp_alerts: []
      - eval_time: 6m
        alertname: SagaParada
        exp_alerts:
          - exp_labels: {}
  - name: serie do coletor ausente no compose, onde o job da API e os-service
    interval: 1m
    input_series:
      - series: up{job="os-service"}
        values: 1x10
    alert_rule_test:
      - eval_time: 6m
        alertname: SagaParada
        exp_alerts:
          - exp_labels: {}
  - name: coletor sadio, atraso de 45 s e instancias so em outras etapas
    interval: 1m
    input_series:
      - series: up{job="os-service-api", pod="os-api-1"}
        values: 1x10
      - series: pytstop_saga_coletor_disponivel{pod="os-api-1"}
        values: 1x10
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
  - name: coletor fora por 3 minutos e de volta, menos que a janela de 5 min
    interval: 1m
    input_series:
      - series: up{job="os-service-api", pod="os-api-1"}
        values: 1x10
      - series: pytstop_saga_coletor_disponivel{pod="os-api-1"}
        values: 1 1 0 0 0 1 1 1 1 1 1
    alert_rule_test:
      - eval_time: 5m
        alertname: SagaParada
        exp_alerts: []
      - eval_time: 9m
        alertname: SagaParada
        exp_alerts: []
  - name: duas replicas da API, uma com up 0, sem a serie do coletor
    interval: 1m
    input_series:
      - series: up{job="os-service-api", pod="os-api-1"}
        values: 1x10
      - series: up{job="os-service-api", pod="os-api-2"}
        values: 0x10
    alert_rule_test:
      - eval_time: 4m
        alertname: SagaParada
        exp_alerts: []
      - eval_time: 6m
        alertname: SagaParada
        exp_alerts:
          - exp_labels: {}
  - name: API com up 0 e sem a serie do coletor (quem acusa e o pytstop-alvo-fora)
    interval: 1m
    input_series:
      - series: up{job="os-service-api", pod="os-api-1"}
        values: 0x10
    alert_rule_test:
      - eval_time: 6m
        alertname: SagaParada
        exp_alerts: []
  - name: nenhuma serie da saga e nenhum alvo da API na descoberta (OS Service fora)
    interval: 1m
    input_series:
      # Relay e consumidor de pe nao contam: so a API exporta o coletor.
      - series: up{job="os-service-relay"}
        values: 1x10
      - series: up{job="rabbitmq"}
        values: 1x10
    alert_rule_test:
      - eval_time: 6m
        alertname: SagaParada
        exp_alerts: []
TESTE
