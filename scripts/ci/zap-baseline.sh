#!/usr/bin/env bash
# ZAP baseline na borda do kind (job e2e do cd.yml, ADR-041, RNF-049): um scan
# passivo por servico, no /openapi.json que o Kong publica (o /docs e o HTML do
# Swagger e nao lista rota), com as regras de e2e/zap/regras.conf. O alvo e a
# borda como um cliente de fora a ve, https://localhost no runner, onde o Kong
# responde com o certificado padrao dele: o ZAP tem de aceita-lo, e um scan que
# nao leu pagina nenhuma (certificado recusado, borda fora) reprova em vez de
# passar por "nada a reportar".
#
#   scripts/ci/zap-baseline.sh [<servico>...]   (sem argumento, os tres)
#
# Reprova (status 1, nomeando os servicos) se alguma regra em FAIL do
# regras.conf disparar ou se o ZAP nao conseguir varrer. Relatorios em
# reports/zap (html, json e md por servico, mais o log do ZAP); a tabela e o md
# de cada servico vao para o summary do job. O ZAP sobe com -silent: sem
# verificar atualizacao, sem baixar add-on e sem telemetria, entao a varredura
# nao fala com a internet. Variaveis: BORDA (https://localhost), ZAP_REDE (rede
# do container, host: o localhost do runner), RELATORIOS (reports/zap) e
# PRAZO_ZAP (segundos por servico, 600).
set -euo pipefail

# Versao e digest do indice multi-arquitetura; a mesma imagem esta na tabela
# "Componentes e versoes" do README (um teste confere).
ZAP_IMAGE="ghcr.io/zaproxy/zaproxy:2.17.0@sha256:7aaa659b0d43078febd82e29bad112285c370727e86ab8340444220e17d9f0d2"

raiz=$(cd "$(dirname "$0")/../.." && pwd)
BORDA="${BORDA:-https://localhost}"
ZAP_REDE="${ZAP_REDE:-host}"
destino="${RELATORIOS:-$raiz/reports/zap}"
PRAZO_ZAP="${PRAZO_ZAP:-600}"

# prefixo <servico>: onde o Kong publica o servico (o ROOT_PATH dele).
prefixo() {
  case "$1" in
    os-service) echo /os ;;
    billing-service) echo /billing ;;
    execution-service) echo /execucao ;;
    *) return 1 ;;
  esac
}

# prazo <segundos> <comando>...: timeout no Linux; no macOS, sem ele, o alarm do perl.
prazo() {
  if command -v timeout >/dev/null; then timeout "$@"; else perl -e 'alarm shift; exec @ARGV' "$@"; fi
}

if [ "$#" -eq 0 ]; then set -- os-service billing-service execution-service; fi
for nome in "$@"; do
  prefixo "$nome" >/dev/null || { echo "unknown service $nome (os-service, billing-service or execution-service)" >&2; exit 2; }
done

mkdir -p "$destino"
# O container roda como o uid 1000 e o runner, como outro: sem isto o ZAP nao
# grava os relatorios na pasta.
chmod 777 "$destino"
cp -f "$raiz/e2e/zap/regras.conf" "$destino/regras.conf"

TABELA=""
FALHARAM=""
for nome in "$@"; do
  alvo="$BORDA$(prefixo "$nome")/openapi.json"
  log="$destino/zap-$nome.log"
  codigo=0
  # O -t, o -c e os relatorios sao caminhos de dentro do container (/zap/wrk).
  # -I: aviso nao reprova, so FAIL; -m 1: o spider para em 1 minuto.
  prazo "$PRAZO_ZAP" docker run --rm --network "$ZAP_REDE" -v "$destino:/zap/wrk" "$ZAP_IMAGE" \
    zap-baseline.py -t "$alvo" -c regras.conf -m 1 -I -z "-silent" \
    -r "zap-$nome.html" -J "zap-$nome.json" -w "zap-$nome.md" 2>&1 | tee "$log" || codigo=$?
  # A linha final do ZAP: FAIL-NEW: 0  FAIL-INPROG: 0  WARN-NEW: 2 ... PASS: 51
  contagem=$(sed -n 's/^FAIL-NEW: \([0-9]*\).*WARN-NEW: \([0-9]*\).*/fail=\1 warn=\2/p' "$log" | tail -n 1)
  falhas=$(sed -n 's/.*fail=\([0-9]*\).*/\1/p' <<< "$contagem")
  avisos=$(sed -n 's/.*warn=\([0-9]*\)/\1/p' <<< "$contagem")
  # Pagina lida: o relatorio json lista o alvo entre os sites quando ao menos um
  # alerta saiu; sem alerta algum, o ZAP diz "Total of N URLs" no log.
  lidas=$(sed -n 's/^Total of \([0-9][0-9]*\) URLs.*/\1/p' "$log" | tail -n 1)
  if [ "$codigo" -ne 0 ]; then
    resultado="FAILED (ZAP exit $codigo)"
  elif [ -z "$contagem" ]; then
    resultado="FAILED (no summary line from ZAP)"
  elif [ "${lidas:-0}" -lt 1 ]; then
    resultado="FAILED (no URL scanned: certificate refused or edge down)"
  else
    resultado=ok
  fi
  case "$resultado" in
    ok) ;;
    *) FALHARAM="${FALHARAM:+$FALHARAM }$nome" ;;
  esac
  TABELA+="| $nome | \`$alvo\` | ${falhas:--} | ${avisos:--} | ${lidas:--} | $resultado |"$'\n'
  printf '%-18s %s fail=%s warn=%s urls=%s: %s\n' "$nome" "$alvo" "${falhas:--}" "${avisos:--}" "${lidas:--}" "$resultado"
done

{
  echo "### ZAP baseline"
  echo
  echo "| Service | Target | FAIL | WARN | URLs | Result |"
  echo "|---|---|---|---|---|---|"
  printf '%s' "$TABELA"
  for nome in "$@"; do
    if [ -s "$destino/zap-$nome.md" ]; then
      echo
      echo "#### $nome"
      echo
      cat "$destino/zap-$nome.md"
    fi
  done
} >> "${GITHUB_STEP_SUMMARY:-/dev/null}"

if [ -n "$FALHARAM" ]; then
  echo "ZAP baseline FAILED: $FALHARAM" >&2
  exit 1
fi
echo "ZAP baseline OK: $*"
