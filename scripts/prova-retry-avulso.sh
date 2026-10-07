#!/usr/bin/env bash
# Prova do retry num RabbitMQ avulso (make prova-retry, que o CI e o make check
# rodam): a imagem do broker com o rabbitmq.conf, os plugins e o
# definitions.json deste repositorio, montados como no compose; os usuarios dos
# servicos pelo criar-usuarios.sh, com o permissoes.json; e
# scripts/prova_retry.py como o billing. Assim o JSON que derruba o boot ou
# afrouxa a permissao reprova sem cluster. Container com nome proprio e porta
# aleatoria no loopback, apagado no fim; as senhas dos servicos sao geradas a
# cada execucao.
set -euo pipefail
: "${RABBITMQ_IMAGE:?}"

nome="pytstop-prova-retry-$$"
config=k8s/base/rabbitmq
trap 'docker rm -f "$nome" >/dev/null 2>&1 || true' EXIT

docker run -d --name "$nome" --hostname "$nome" --user 999:999 -p 127.0.0.1::5672 \
  -v "$PWD/$config/rabbitmq.conf:/etc/rabbitmq/conf.d/20-pytstop.conf:ro" \
  -v "$PWD/$config/enabled_plugins:/etc/rabbitmq/enabled_plugins:ro" \
  -v "$PWD/$config/definitions.json:/etc/rabbitmq/definitions/definitions.json:ro" \
  -v "$PWD/compose/rabbitmq-admin.json:/etc/rabbitmq/definitions/admin.json:ro" \
  -v "$PWD/$config/criar-usuarios.sh:/scripts/criar-usuarios.sh:ro" \
  -v "$PWD/$config/permissoes.json:/scripts/permissoes.json:ro" \
  "$RABBITMQ_IMAGE" >/dev/null

# pytstop.retry so existe se o definitions.json entrou (como no healthcheck do
# compose); importacao com erro derruba o broker, e o log diz por que.
carregou() { docker exec "$nome" rabbitmqctl -s list_exchanges name 2>/dev/null | grep -qx pytstop.retry; }
for _ in $(seq 60); do
  carregou && break
  [ "$(docker inspect -f '{{.State.Running}}' "$nome")" = true ] || break
  sleep 1
done
carregou || { echo "RabbitMQ did not load the definitions:" >&2; docker logs --tail 30 "$nome" >&2; exit 1; }

# Senhas pelo ambiente, nao pela linha de comando do docker exec.
RABBITMQADMIN_PASSWORD=$(sed -n 's/.*"password": "\([^"]*\)".*/\1/p' compose/rabbitmq-admin.json)
RABBITMQ_OS_PASSWORD=$(openssl rand -hex 16)
RABBITMQ_BILLING_PASSWORD=$(openssl rand -hex 16)
RABBITMQ_EXECUCAO_PASSWORD=$(openssl rand -hex 16)
export RABBITMQADMIN_PASSWORD RABBITMQ_OS_PASSWORD RABBITMQ_BILLING_PASSWORD RABBITMQ_EXECUCAO_PASSWORD
docker exec -e RABBITMQADMIN_TARGET_HOST=localhost -e RABBITMQADMIN_TARGET_PORT=15672 \
  -e RABBITMQADMIN_NON_INTERACTIVE_MODE=true -e RABBITMQADMIN_USERNAME=admin -e RABBITMQADMIN_PASSWORD \
  -e RABBITMQ_OS_PASSWORD -e RABBITMQ_BILLING_PASSWORD -e RABBITMQ_EXECUCAO_PASSWORD \
  "$nome" sh /scripts/criar-usuarios.sh

porta=$(docker port "$nome" 5672/tcp | sed -n 's/^127\.0\.0\.1:\([0-9]*\)$/\1/p' | head -1)
RABBITMQ_URL="amqp://billing:$RABBITMQ_BILLING_PASSWORD@127.0.0.1:$porta/%2F" \
  uv run --frozen python scripts/prova_retry.py
