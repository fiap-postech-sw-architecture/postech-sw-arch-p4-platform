"""Leitura de uma serie no formato texto do Prometheus (o ``/metrics`` de uma API)."""

from __future__ import annotations

import re


def valor_da_serie(texto: str, nome: str, **rotulos: str) -> float | None:
    """Valor da serie ``nome`` com exatamente estes ``rotulos``; ``None`` se nao existe.

    Compara os rotulos como conjunto: ``{a="1",b="2"}`` casa ``a="1", b="2"`` em
    qualquer ordem, mas nao ``a="1"`` sozinho (outra serie).
    """
    padrao = re.compile(
        rf"^{re.escape(nome)}(?:\{{(?P<rotulos>[^}}]*)\}})?\s+(?P<valor>\S+)",
        re.MULTILINE,
    )
    for achado in padrao.finditer(texto):
        lidos = dict(
            re.findall(r'(\w+)="((?:[^"\\]|\\.)*)"', achado.group("rotulos") or "")
        )
        if lidos == rotulos:
            return float(achado.group("valor"))
    return None
