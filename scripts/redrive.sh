#!/usr/bin/env bash
# Devolve para a fila de trabalho as mensagens da DLQ dela (make redrive
# FILA=<fila>, ADR-036), depois de corrigida a causa. Usa um shovel do proprio
# broker: move com confirmacao (se a fila recusar, a mensagem fica na DLQ),
# preserva as propriedades (user_id, message_id, x-tentativa) e se apaga
# sozinho depois de mover o que havia na DLQ quando comecou.
set -euo pipefail

fila="${1:?uso: redrive.sh <fila de trabalho>}"
R="kubectl --context ${KUBE_CONTEXT:-kind-pytstop-p4} -n ${NAMESPACE:-pytstop-plataforma} exec rabbitmq-0 -c rabbitmq --"

mensagens() { $R rabbitmqctl -q list_queues --no-table-headers name messages | awk -v fila="$1" '$1 == fila {print $2}'; }

printf 'antes:  %s.dlq=%s  %s=%s\n' "$fila" "$(mensagens "$fila.dlq")" "$fila" "$(mensagens "$fila")"
$R rabbitmqctl -q set_parameter shovel "redrive-$fila" \
  "{\"src-uri\": \"amqp://\", \"src-queue\": \"$fila.dlq\", \"dest-uri\": \"amqp://\", \"dest-queue\": \"$fila\", \"src-delete-after\": \"queue-length\"}"
for _ in $(seq 60); do
  $R rabbitmqctl -q list_parameters --no-table-headers | grep -q "redrive-$fila" || break
  sleep 1
done
if $R rabbitmqctl -q list_parameters --no-table-headers | grep -q "redrive-$fila"; then
  echo "o shovel redrive-$fila nao terminou em 60 s; veja rabbitmqctl shovel_status" >&2
  exit 1
fi
# A contagem das filas quorum e atualizada a cada 5 s.
sleep 6
printf 'depois: %s.dlq=%s  %s=%s\n' "$fila" "$(mensagens "$fila.dlq")" "$fila" "$(mensagens "$fila")"
