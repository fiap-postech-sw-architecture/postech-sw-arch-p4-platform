"""Prova, no broker, das filas de retry por atraso com o usuario do servico.

Publica como o consumidor do Billing publica a copia de uma nova tentativa
(exchange pytstop.retry, routing key igual ao nome da fila de retry do nivel,
user_id da propria conexao, header x-tentativa, sem expiration) e confere:

1. a copia em billing.comandos.retry.1s volta a billing.comandos em ~1 s, com
   o user_id e o x-tentativa;
2. uma copia em billing.comandos.retry.5s publicada antes de outra em
   billing.comandos.retry.1s nao segura a de 1 s, que volta primeiro;
3. o broker recusa (403) a copia do billing na fila de retry de outro servico,
   com a routing key antiga (o nome da fila de trabalho) e com a chave da
   propria fila de 1 s seguida de uma quebra de linha: o padrao da permissao
   acaba no fim exato do nome, e com $ no lugar essa chave passaria.

O script le e descarta o que houver em billing.comandos. Por isso so roda num
broker sem consumidor nessa fila: com o Billing conectado, recusa e sai com
status 2.

    AMQP_URL=amqp://billing:<senha>@127.0.0.1:<porta>/%2F \\
        uv run python scripts/prova_retry.py

O make smoke roda o script no kind, por um port-forward, e o make prova-retry
num RabbitMQ avulso (scripts/prova-retry-avulso.sh, tambem no CI). Prova que
nao vale vira uma linha CHECK FAILED, e o status de saida e 1.
"""

from __future__ import annotations

import os
import sys
import time
import uuid
from typing import TYPE_CHECKING

import pika
from pika.exceptions import AMQPChannelError, ChannelClosedByBroker, UnroutableError

if TYPE_CHECKING:
    from pika.adapters.blocking_connection import BlockingChannel

USUARIO = "billing"
FILA = "billing.comandos"
FILA_ALHEIA = "execucao.comandos"
# Fracao do atraso que a copia pode levar a mais para voltar: no 4.3.6 a de
# 1 s volta em 1,0 a 1,1 s, e a de 5 s em 5,0 a 5,1 s. Com 0,5, um TTL de
# 1,6 s na fila de 1 s ja reprova.
FOLGA = 0.5

# pika nao publica tipos (sem py.typed nem stubs): para o mypy, BlockingChannel,
# BlockingConnection e BasicProperties sao Any. As anotacoes ficam pelo leitor.
type Volta = tuple[float, pika.BasicProperties]  # segundos ate voltar, propriedades

falhas: list[str] = []


def confere(o_que: str, valeu: bool, obtido: str) -> None:
    """Registra a prova; se nao valeu, imprime a linha CHECK FAILED."""
    if not valeu:
        falhas.append(o_que)
        sys.stdout.flush()  # a falha sai depois da linha que a explica
        print(f"CHECK FAILED: {o_que}: got {obtido}", file=sys.stderr)


def canal_com_confirmacao(conexao: pika.BlockingConnection) -> BlockingChannel:
    """Canal novo em que o basic_publish espera a confirmacao do broker."""
    canal = conexao.channel()
    canal.confirm_delivery()
    return canal


def publica(canal: BlockingChannel, chave: str, tentativa: int) -> str:
    """Publica a copia como o consumidor e devolve o message_id dela.

    Com confirm_delivery e mandatory, a recusa do broker (403), a copia sem
    fila de destino e o nack levantam excecao em vez de passarem calados.
    """
    message_id = str(uuid.uuid4())
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


def voltas(
    canal: BlockingChannel, ids: set[str], inicio: float, atraso: int
) -> dict[str, Volta]:
    """Le a fila ate os ids voltarem: id -> (segundos desde o inicio, propriedades).

    Espera 2 s alem da folga do maior atraso, para medir a volta atrasada em
    vez de responder never.
    """
    limite_s = atraso * (1 + FOLGA) + 2
    chegou: dict[str, Volta] = {}
    while set(chegou) != ids and time.monotonic() - inicio < limite_s:
        metodo, propriedades, _ = canal.basic_get(FILA, auto_ack=True)
        if metodo is None:
            time.sleep(0.05)
        elif propriedades.message_id in ids:
            chegou[propriedades.message_id] = (time.monotonic() - inicio, propriedades)
    return chegou


def segundos(volta: Volta | None) -> str:
    """Tempo da volta para a saida, ou never."""
    return "never" if volta is None else f"{volta[0]:.1f} s"


def no_prazo(volta: Volta | None, atraso: int) -> bool:
    """Voltou entre 90 % do atraso e o atraso mais a folga."""
    return volta is not None and atraso * 0.9 <= volta[0] <= atraso * (1 + FOLGA)


def prova_volta_no_atraso(conexao: pika.BlockingConnection) -> None:
    """Prova 1: a copia de 1 s volta em ~1 s com o user_id e o x-tentativa."""
    canal = canal_com_confirmacao(conexao)
    inicio = time.monotonic()
    id_1s = publica(canal, f"{FILA}.retry.1s", 1)
    volta = voltas(canal, {id_1s}, inicio, 1).get(id_1s)
    print(f"{USUARIO} -> {FILA}.retry.1s: back in {FILA} after {segundos(volta)}")
    confere("1 s copy back after ~1 s", no_prazo(volta, 1), segundos(volta))
    if volta is not None:
        propriedades = volta[1]
        tentativa = (propriedades.headers or {}).get("x-tentativa")
        obtido = f"user_id={propriedades.user_id} x-tentativa={tentativa}"
        print(f"  {obtido}")
        confere(
            "user_id and x-tentativa kept",
            propriedades.user_id == USUARIO and tentativa == 1,
            obtido,
        )


def prova_sem_head_of_line(conexao: pika.BlockingConnection) -> None:
    """Prova 2: a copia de 5 s publicada antes nao segura a de 1 s."""
    canal = canal_com_confirmacao(conexao)
    inicio = time.monotonic()
    id_5s = publica(canal, f"{FILA}.retry.5s", 2)
    id_1s = publica(canal, f"{FILA}.retry.1s", 1)
    chegou = voltas(canal, {id_5s, id_1s}, inicio, 5)
    volta_1s, volta_5s = chegou.get(id_1s), chegou.get(id_5s)
    print(
        f"{USUARIO} -> {FILA}.retry.5s, then {FILA}.retry.1s: back in {FILA} "
        f"after {segundos(volta_1s)} (1 s copy) and {segundos(volta_5s)} (5 s copy)"
    )
    confere(
        "1 s copy published after a 5 s copy back after ~1 s",
        no_prazo(volta_1s, 1),
        segundos(volta_1s),
    )
    confere("5 s copy back after ~5 s", no_prazo(volta_5s, 5), segundos(volta_5s))


def numa_linha(texto: str) -> str:
    """O texto com a quebra de linha escrita como \\n, para sair numa linha so."""
    return texto.encode("unicode_escape").decode()


def prova_recusas(conexao: pika.BlockingConnection) -> None:
    """Prova 3: 403 na fila de outro servico, na chave antiga e na com \\n no fim."""
    for chave in (f"{FILA_ALHEIA}.retry.1s", FILA, f"{FILA}.retry.1s\n"):
        canal = canal_com_confirmacao(conexao)  # a recusa fecha o canal
        try:
            publica(canal, chave, 1)
            resultado = "accepted"
        except ChannelClosedByBroker as erro:
            resultado = f"{erro.reply_code} {erro.reply_text}"
        except UnroutableError:
            # Permissao aceitou e nenhuma fila tem a chave (mandatory devolveu).
            resultado = "accepted, then returned as unroutable"
        # O broker repete a chave no texto da recusa, quebra de linha inclusa.
        nome, resultado = numa_linha(chave), numa_linha(resultado)
        print(f"{USUARIO} -> {nome}: {resultado}")
        confere(f"{nome} refused", resultado.startswith("403 "), resultado)


def main() -> int:
    """Roda as provas: 0 se todas valeram, 1 se alguma falhou, 2 se recusou."""
    conexao = pika.BlockingConnection(pika.URLParameters(os.environ["AMQP_URL"]))
    try:
        declarada = conexao.channel().queue_declare(FILA, passive=True)
        if declarada.method.consumer_count:
            print(
                f"refusing to run: {FILA} has "
                f"{declarada.method.consumer_count} consumer(s), and this proof "
                "reads and discards the messages in it",
                file=sys.stderr,
            )
            return 2
        for o_que, prova in (
            ("1 s copy published and read back", prova_volta_no_atraso),
            ("5 s and 1 s copies published and read back", prova_sem_head_of_line),
        ):
            try:
                prova(conexao)
            except AMQPChannelError as erro:  # 403, copia sem rota ou nack
                confere(o_que, False, f"{type(erro).__name__}: {erro}")
        prova_recusas(conexao)
    finally:
        if conexao.is_open:
            conexao.close()
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
