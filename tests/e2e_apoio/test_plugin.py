"""Plugin do pytest do E2E: mascara do relatorio, SIGTERM e log do httpx."""

from __future__ import annotations

import logging
import signal
from dataclasses import dataclass, field

import pytest

from e2e.apoio import plugin, segredos


@dataclass
class RelatorioFalso:
    """So o que o hook le e escreve de um ``TestReport``."""

    failed: bool
    longrepr: object
    sections: list[tuple[str, str]] = field(default_factory=list)


def _rodar_hook(relatorio: RelatorioFalso) -> RelatorioFalso:
    ciclo = plugin.pytest_runtest_makereport(item=None, call=None)  # type: ignore[arg-type]  # o hook descarta os dois
    next(ciclo)
    with pytest.raises(StopIteration) as fim:
        ciclo.send(relatorio)  # type: ignore[arg-type]  # falso do TestReport
    resultado: RelatorioFalso = fim.value.value
    return resultado


def test_hook_mascara_a_falha_e_as_secoes_capturadas() -> None:
    segredos.registrar("senha-do-admin-123")
    relatorio = RelatorioFalso(
        failed=True,
        longrepr="assert 'senha-do-admin-123' == 'x'\nBearer abc.def",
        sections=[
            ("Captured stdout call", "login com senha-do-admin-123"),
            (
                "Captured log call",
                "POST /billing/api/v1/publico/orcamentos/TOK.en-1/decisao",
            ),
        ],
    )

    resultado = _rodar_hook(relatorio)

    assert resultado.longrepr == "assert '***' == 'x'\nBearer ***"
    assert resultado.sections == [
        ("Captured stdout call", "login com ***"),
        ("Captured log call", "POST /billing/api/v1/publico/orcamentos/***/decisao"),
    ]


def test_hook_converte_a_falha_estruturada_em_texto_mascarado() -> None:
    segredos.registrar("senha-do-admin-123")

    class Estruturada:
        def __str__(self) -> str:
            return "falhou com senha-do-admin-123"

    resultado = _rodar_hook(RelatorioFalso(failed=True, longrepr=Estruturada()))

    assert resultado.longrepr == "falhou com ***"


def test_hook_nao_mexe_no_que_passou_nem_no_que_foi_pulado() -> None:
    pulado = ("arquivo.py", 12, "Skipped: sem cluster")

    passou = _rodar_hook(RelatorioFalso(failed=False, longrepr=None))
    pulou = _rodar_hook(RelatorioFalso(failed=False, longrepr=pulado))

    assert passou.longrepr is None
    assert pulou.longrepr == pulado


def test_configure_faz_do_sigterm_um_keyboard_interrupt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registrados: list[tuple[int, object]] = []
    monkeypatch.setattr(
        signal,
        "signal",
        lambda numero, tratador: registrados.append((numero, tratador)),
    )

    plugin.pytest_configure(None)  # type: ignore[arg-type]  # o hook descarta a config

    assert registrados == [(signal.SIGTERM, signal.default_int_handler)]
    assert logging.getLogger("httpx").level == logging.WARNING
