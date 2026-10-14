#!/usr/bin/env bash
# Prova no promtool as consultas e as regras de alerta de observabilidade/
# (ADR-043), com a imagem do Prometheus e a do yq pinadas pelo Makefile:
#
# 1. `promtool check rules`: o expr de cada painel dos dashboards e de cada regra
#    de alerta e uma consulta PromQL valida ($__range vira 1h e $__rate_interval
#    vira 5m, como o smoke faz). Pega parentese, funcao e tipo de argumento
#    errados, que a regex de nomes do teste de consistencia nao pega.
# 2. `promtool test rules tests/alertas.promtool.yml`: cada regra de
#    observabilidade/grafana/alertas*.yaml, lida pelo yq, vira uma regra do
#    Prometheus com `alert: <uid>`, a consulta A comparada com o limiar do
#    threshold do Grafana (`> X` no gt, `< X` no lt) e o `for` da propria regra;
#    o arquivo de casos prova o que dispara e o que nao dispara em cada uma.
#    Threshold que nao seja gt nem lt, `for` fora de minutos e limiar que nao seja
#    numero reprovam, porque a regra de teste so modela esses.
#
# As regras e as consultas vao pelo ambiente e o arquivo de casos pelo stdin: o
# colima nao compartilha o TMPDIR do macOS com a VM.
set -euo pipefail
: "${PROMETHEUS_IMAGE:?}" "${YQ_IMAGE:?}"

# Uma linha de JSON por regra: uid, for, tipo e limiar do threshold e a consulta.
regras=""
for arquivo in observabilidade/grafana/alertas*.yaml; do
  regras+=$(docker run --rm -i "$YQ_IMAGE" -o=json -I=0 \
    '.groups[].rules[] | {"uid": .uid, "for": .for, "tipo": (.data[] | select(.refId == "C") | .model.conditions[0].evaluator.type), "limiar": (.data[] | select(.refId == "C") | .model.conditions[0].evaluator.params[0]), "expr": (.data[] | select(.refId == "A") | .model.expr)}' \
    < "$arquivo")$'\n'
done

grupos=$(printf '%s' "$regras" | jq -c -s '
  def regra:
    if (.for | test("^[0-9]+m$")) | not then error("rule \(.uid): unexpected for: \(.for)")
    elif (.limiar | type) != "number" then error("rule \(.uid): unexpected threshold \(.limiar)")
    elif .tipo == "gt" then {alert: .uid, expr: "(\(.expr)) > \(.limiar)", for: .for}
    elif .tipo == "lt" then {alert: .uid, expr: "(\(.expr)) < \(.limiar)", for: .for}
    else error("rule \(.uid): threshold type \(.tipo) is neither gt nor lt; the test rule only models those")
    end;
  {groups: [{name: "alertas", rules: map(regra)}]}')
printf '%s' "$regras" | jq -r '"rule \(.uid) (for \(.for), \(.tipo) \(.limiar)): \(.expr)"'

# Os mesmos exprs dos paineis e dos alertas, como regras de gravacao so para a
# checagem de sintaxe.
# shellcheck disable=SC2016 # $__range e $__rate_interval sao do Grafana, vao literais ao sed
consultas=$(
  {
    jq -r '.panels[].targets[].expr' observabilidade/dashboards/*.json
    printf '%s' "$regras" | jq -r '.expr'
  } | sed -e 's/\$__range/1h/g' -e 's/\$__rate_interval/5m/g'
)
consultas_json=$(printf '%s\n' "$consultas" | jq -c -R -s '
  split("\n") | map(select(length > 0)) | to_entries
  | {groups: [{name: "consultas", rules: map({record: "consulta:\(.key)", expr: .value})}]}')
echo "queries: $(printf '%s\n' "$consultas" | grep -c .) panel and alert expressions"

docker run --rm -i -e REGRAS="$grupos" -e CONSULTAS="$consultas_json" --entrypoint sh "$PROMETHEUS_IMAGE" -c '
  cd /tmp && cat > teste.yml &&
  printf "%s" "$CONSULTAS" > consultas.yml && promtool check rules consultas.yml &&
  printf "%s" "$REGRAS" > regras.yml && promtool check rules regras.yml &&
  promtool test rules teste.yml' < tests/alertas.promtool.yml
