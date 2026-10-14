"""Espera por polling com prazo: a unica forma de esperar no E2E.

Nenhum ``sleep`` fixo para "dar tempo" ao sistema: cada espera testa uma
condicao observavel, de ``intervalo`` em ``intervalo``, e reprova com a
descricao do que faltou quando o prazo acaba. A unica espera em tempo corrido
e ``manter``, que prova que uma condicao SEGUE verdadeira por um tempo (os 20 s
do consumidor parado).
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from e2e.apoio.segredos import mascarar

if TYPE_CHECKING:
    from collections.abc import Callable


class TempoEsgotadoError(AssertionError):
    """A condicao nao ficou verdadeira (ou deixou de ser) dentro do prazo."""


def esperar[T](
    condicao: Callable[[], T | None],
    *,
    prazo: float,
    descricao: str,
    intervalo: float = 1.0,
    ignorar: tuple[type[Exception], ...] = (),
    progresso: Callable[[float, object], None] | None = None,
    relogio: Callable[[], float] = time.monotonic,
    dormir: Callable[[float], None] = time.sleep,
) -> T:
    """Repete ``condicao`` ate ela devolver um valor verdadeiro, ate ``prazo`` segundos.

    Devolve o primeiro valor verdadeiro. A condicao roda ao menos uma vez e uma
    ultima vez no fim do prazo; nunca se dorme alem dele. ``ignorar`` lista as
    excecoes que contam como "ainda nao" (rede, port-forward reiniciando); as
    demais propagam, porque escondem defeito. ``progresso(restante, visto)`` roda
    antes de cada pausa, com os segundos que faltam e o ultimo valor visto: e o
    gancho da contagem regressiva de quem espera uma pessoa.
    """
    limite = relogio() + prazo
    visto: object = None
    while True:
        try:
            valor = condicao()
        except ignorar as erro:
            visto = f"{type(erro).__name__}: {erro}"
        else:
            if valor:
                return valor
            visto = valor
        restante = limite - relogio()
        if restante <= 0:
            msg = f"{descricao}: nao ocorreu em {prazo:g} s (ultimo valor: {visto!r})"
            raise TempoEsgotadoError(mascarar(msg))
        if progresso is not None:
            progresso(restante, visto)
        dormir(min(intervalo, restante))


def manter(
    condicao: Callable[[], object],
    *,
    duracao: float,
    descricao: str,
    intervalo: float = 2.0,
    relogio: Callable[[], float] = time.monotonic,
    dormir: Callable[[float], None] = time.sleep,
) -> None:
    """Exige que ``condicao`` seja verdadeira em toda amostra durante ``duracao`` s.

    A primeira amostra e imediata e a ultima cai no fim da janela. E a espera
    em tempo corrido do cenario de resiliencia: o que se prova e que o estado
    nao mudou enquanto o servico estava parado.
    """
    fim = relogio() + duracao
    while True:
        valor = condicao()
        if not valor:
            raise TempoEsgotadoError(
                mascarar(
                    f"{descricao}: deixou de valer antes de {duracao:g} s ({valor!r})"
                )
            )
        restante = fim - relogio()
        if restante <= 0:
            return
        dormir(min(intervalo, restante))
