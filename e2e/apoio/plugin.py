"""Plugin do pytest do E2E: nenhuma credencial no relatorio, SIGTERM e log do httpx.

Carregado pelo ``conftest.py`` (``pytest_plugins``) e, nos testes, por ``-p``.
"""

from __future__ import annotations

import logging
import signal
from typing import TYPE_CHECKING

import pytest

from e2e.apoio.segredos import mascarar

if TYPE_CHECKING:
    from collections.abc import Generator

    from _pytest.reports import TestReport


def pytest_configure(config: pytest.Config) -> None:
    """SIGTERM roda os finalizadores; o httpx nao loga URL com token."""
    del config
    # kill, timeout ou o cancelamento do runner: sem isto o pytest morre sem rodar o
    # teardown, deixa o port-forward orfao e, no meio de um cenario de resiliencia,
    # o Deployment em 0. Como KeyboardInterrupt, o Ctrl-C e o SIGTERM saem iguais.
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    # Em INFO o httpx imprime cada URL, e algumas levam o token do link ou do checkout.
    logging.getLogger("httpx").setLevel(logging.WARNING)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None]
) -> Generator[None, TestReport, TestReport]:
    """Passa o relatorio da falha e as secoes capturadas pela mascara de segredos.

    O pytest escreve a falha (o ``assert`` mostra o valor das variaveis), o stdout e o
    log capturados no terminal, no ``junit.xml`` e no ``cucumber.json`` sem passar
    por ``mascarar``. Este e o ponto unico por onde os tres passam.
    """
    del item, call
    relatorio = yield
    if relatorio.failed and relatorio.longrepr is not None:
        relatorio.longrepr = mascarar(str(relatorio.longrepr))
    relatorio.sections = [(nome, mascarar(texto)) for nome, texto in relatorio.sections]
    return relatorio
