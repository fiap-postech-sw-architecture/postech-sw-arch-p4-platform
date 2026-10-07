"""Prova, no broker, das filas de retry por atraso com o usuario do servico.

Publica como o consumidor do Billing publica a copia de uma nova tentativa
(exchange pytstop.retry, routing key igual ao nome da fila de retry do nivel,
user_id da propria conexao, header x-tentativa, sem expiration) e confere:

1. a copia em billing.comandos.retry.1s volta a billing.comandos em ~1 s, com
   o user_id e o x-tentativa;
2. uma copia em billing.comandos.retry.5s publicada antes de outra em
   billing.comandos.retry.1s nao segura a de 1 s, que volta primeiro;
3. o broker recusa (403) a copia do billing na fila de retry de outro servico
   e com a routing key antiga, o nome da fila de trabalho.

Uso, num broker so com a plataforma (o script le e descarta o que houver em
billing.comandos):

    AMQP_URL=amqp://billing:<senha>@127.0.0.1:<porta>/%2F \\
        uv run python scripts/prova_retry.py

O make smoke roda o script no kind, por um port-forward. Prova que nao vale
vira uma linha CHECK FAILED, e o status de saida e 1.
"""

from __future__ import annotations

import os
import sys
import time
import uuid
from typing import Any

import pika
from pika.exceptions import ChannelClosedByBroker, UnroutableError

USUARIO = "billing"
FILA = "billing.comandos"
FILA_ALHEIA = "execucao.comandos"
# Tempo que o broker pode levar alem do TTL para devolver a copia.
FOLGA_S = 2.0

falhas: list[str] = []


def confere(o_que: str, valeu: bool, obtido: str) -> None:
    if not valeu:
        falhas.append(o_que)
        sys.stdout.flush()  # a falha sai depois da linha que a explica
        print(f"CHECK FAILED: {o_que}: got {obtido}", file=sys.stderr)


def publica(canal: Any, chave: str, tentativa: int) -> str:
    """Publica a copia como o consumidor e devolve o message_id dela."""
    message_id = str(uuid.uuid4())
    # Com confirm_delivery, o basic_publish espera a confirmacao do broker.
    canal.basic_publish(
        exchange="pytstop.retry",
        routing_key=chave,
        body=b'{"prova": "retry"}',
        properties=pika.BasicProperties(
            message_id=message_id,
            user_id=USUARIO,
            content_type="application/json",
            delivery_mode=2,
            headers={"x-tentativa": tentativa},
        ),
        mandatory=True,
    )
    return message_id


def voltas(canal: Any, ids: set[str], inicio: float, limite_s: float) -> dict[str, Any]:
    """Le a fila ate os ids voltarem: id -> (segundos desde o inicio, propriedades)."""
    chegou: dict[str, Any] = {}
    while set(chegou) != ids and time.monotonic() - inicio < limite_s:
        metodo, propriedades, _ = canal.basic_get(FILA, auto_ack=True)
        if metodo is None:
            time.sleep(0.05)
        elif propriedades.message_id in ids:
            chegou[propriedades.message_id] = (time.monotonic() - inicio, propriedades)
    return chegou


def segundos(volta: Any) -> str:
    return "never" if volta is None else f"{volta[0]:.1f} s"


def no_prazo(volta: Any, atraso: int) -> bool:
    return volta is not None and atraso * 0.9 <= volta[0] <= atraso + FOLGA_S


def main() -> int:
    conexao = pika.BlockingConnection(pika.URLParameters(os.environ["AMQP_URL"]))
    canal = conexao.channel()
    canal.confirm_delivery()

    inicio = time.monotonic()
    um = publica(canal, f"{FILA}.retry.1s", 1)
    volta = voltas(canal, {um}, inicio, 1 + FOLGA_S + 1).get(um)
    print(f"{USUARIO} -> {FILA}.retry.1s: back in {FILA} after {segundos(volta)}")
    confere("1 s copy back after ~1 s", no_prazo(volta, 1), segundos(volta))
    if volta is not None:
        propriedades = volta[1]
        tentativa = (propriedades.headers or {}).get("x-tentativa")
        print(f"  user_id={propriedades.user_id} x-tentativa={tentativa}")
        confere(
            "user_id and x-tentativa kept",
            propriedades.user_id == USUARIO and tentativa == 1,
            f"user_id={propriedades.user_id} x-tentativa={tentativa}",
        )

    inicio = time.monotonic()
    cinco = publica(canal, f"{FILA}.retry.5s", 2)
    um = publica(canal, f"{FILA}.retry.1s", 1)
    chegou = voltas(canal, {cinco, um}, inicio, 5 + FOLGA_S + 1)
    print(
        f"{USUARIO} -> {FILA}.retry.5s, then {FILA}.retry.1s: back in {FILA} "
        f"after {segundos(chegou.get(um))} (1 s copy) "
        f"and {segundos(chegou.get(cinco))} (5 s copy)"
    )
    confere(
        "1 s copy published after a 5 s copy back after ~1 s",
        no_prazo(chegou.get(um), 1),
        segundos(chegou.get(um)),
    )
    confere(
        "5 s copy back after ~5 s",
        no_prazo(chegou.get(cinco), 5),
        segundos(chegou.get(cinco)),
    )

    for chave in (f"{FILA_ALHEIA}.retry.1s", FILA):
        canal = conexao.channel()
        canal.confirm_delivery()
        try:
            publica(canal, chave, 1)
            resultado = "accepted"
        except ChannelClosedByBroker as erro:
            resultado = f"{erro.reply_code} {erro.reply_text}"
        except UnroutableError:
            # Permissao aceitou e nenhuma fila tem a chave (mandatory devolveu).
            resultado = "accepted, then returned as unroutable"
        print(f"{USUARIO} -> {chave}: {resultado}")
        confere(f"{chave} refused", resultado.startswith("403 "), resultado)

    conexao.close()
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
