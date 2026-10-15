# Regras do Grafana, uma por objeto (uid, for, tipo e limiar do threshold, consulta),
# viram as regras do Prometheus que o promtool testa: `alert: <uid>`, a consulta
# comparada com o limiar (`> X` no gt, `< X` no lt) e o `for` da propria regra. Regra
# que o modelo de teste nao cobre reprova em vez de passar calada.
def regra:
  if (.for | test("^[0-9]+m$")) | not then error("rule \(.uid): unexpected for: \(.for)")
  elif (.limiar | type) != "number" then error("rule \(.uid): unexpected threshold \(.limiar)")
  elif .tipo == "gt" then {alert: .uid, expr: "(\(.expr)) > \(.limiar)", for: .for}
  elif .tipo == "lt" then {alert: .uid, expr: "(\(.expr)) < \(.limiar)", for: .for}
  else error("rule \(.uid): threshold type \(.tipo) is neither gt nor lt; the test rule only models those")
  end;
{groups: [{name: "alertas", rules: map(regra)}]}
