"""Plugin do pytest do sandbox do Mercado Pago (make mp-sandbox e mp-sandbox-ensaio).

Carregado pelo ``conftest.py`` (``pytest_plugins``). O E2E da saga passa por aqui sem
mudar nada: cada gancho so age com ``E2E_MP_MODO`` definido ou no cenario com a tag
``mp_sandbox``. Fica em ``e2e/apoio`` (e nao no ``conftest.py``) para ter teste e
entrar na cobertura: e daqui que sai o que decide o resultado de cada cenario no
``resumo.md`` e o que garante o desfazer do modo real.
"""

from __future__ import annotations

import os
import signal
from typing import TYPE_CHECKING, Final

import pytest

from e2e.apoio.modo_billing import SINAIS_DE_INTERRUPCAO

if TYPE_CHECKING:
    from collections.abc import Generator

    from _pytest.fixtures import FixtureRequest
    from _pytest.reports import TestReport
    from pytest_bdd.parser import Scenario, Step

# Estado da sessao: o pytest roda uma por processo. ``interrompida`` vale a partir do
# primeiro Ctrl-C (ou kill, ou fechar a janela): so ai um cenario sem relatorio da
# chamada e "interrompido"; em outro caso, a ligacao do resultado esta quebrada.
_ESTADO: Final = {"interrompida": False}
TAG_DO_SANDBOX: Final = "mp_sandbox"
SEM_MODO: Final = "sandbox do Mercado Pago: use make mp-sandbox"
COM_MODO: Final = "E2E_MP_MODO definido: so o sandbox roda"


class LigacaoDoResultadoError(AssertionError):
    """O pytest nao registrou a chamada do cenario e ninguem interrompeu a sessao."""


def _modo() -> str:
    # Lido a cada chamada, e nao no import: o pytest cru e os testes mudam o ambiente.
    return os.environ.get("E2E_MP_MODO", "")


def pytest_configure(config: pytest.Config) -> None:
    """No sandbox, fechar a janela (SIGHUP) interrompe como o Ctrl-C."""
    del config
    _ESTADO["interrompida"] = False
    if _modo():
        signal.signal(signal.SIGHUP, signal.default_int_handler)


def pytest_keyboard_interrupt(excinfo: object) -> None:
    """Depois da primeira interrupcao so resta o desmonte, e nada mais o interrompe.

    O pytest desmonta as fixtures em ordem inversa; um segundo Ctrl-C no teardown de
    uma delas pularia as que faltam, o desfazer do modo real entre elas. O
    ``KeyboardInterrupt`` dentro de um finalizer nao e capturado pelo pytest.
    """
    del excinfo
    _ESTADO["interrompida"] = True
    if _modo():
        for sinal in SINAIS_DE_INTERRUPCAO:
            signal.signal(sinal, signal.SIG_IGN)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item,
) -> Generator[None, TestReport, TestReport]:
    """Guarda o relatorio de cada fase no item: a fixture ``prova`` le o da chamada."""
    relatorio = yield
    setattr(item, f"rep_{relatorio.when}", relatorio)
    return relatorio


def desfecho_da_chamada(item: pytest.Item) -> str | None:
    """``passed`` ou ``failed``; ``None`` so se a sessao foi interrompida (Ctrl-C).

    Sem relatorio da chamada, um cenario que falhou no setup falhou; interrompido so
    vale com a interrupcao registrada. Fora disso a ligacao do resultado esta
    quebrada, e dizer "passou" ou "interrompido" seria mentir: a execucao reprova.
    """
    chamada = getattr(item, "rep_call", None)
    if chamada is not None:
        return str(chamada.outcome)
    preparo = getattr(item, "rep_setup", None)
    if preparo is not None and preparo.failed:
        return "failed"
    if _ESTADO["interrompida"]:
        return None
    msg = (
        f"o pytest não registrou a chamada de {item.name} e a sessão não foi "
        "interrompida: a ligação do resultado do cenário (rep_call) está quebrada"
    )
    raise LigacaoDoResultadoError(msg)


@pytest.hookimpl(trylast=True)  # depois do -m, que tira os deselecionados
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """O sandbox do Mercado Pago e o E2E da saga nao rodam na mesma execucao.

    Sem ``E2E_MP_MODO`` os cenarios ``@mp_sandbox`` ficam de fora (nao ha token no
    CI e eles mexem no modo do Billing); com ele, so eles rodam. O ``make e2e`` e o
    ``make demo`` ja os excluem pelo marker, e isto cobre quem roda o pytest cru.
    Fica como ``skip`` (e nao fora da lista) para o ``--generate-missing`` do
    ``make test`` continuar vendo os passos do feature.

    ``E2E_MP_MODO`` esquecido no shell, com nenhum cenario do sandbox selecionado
    (o ``-m "not mp_sandbox"`` do ``make e2e``), pularia o E2E da saga inteiro com
    saida 0: isso e erro, e nao um verde.
    """
    modo = _modo()
    do_sandbox = [item.get_closest_marker(TAG_DO_SANDBOX) is not None for item in items]
    if modo and items and not any(do_sandbox):
        pytest.exit(
            f"E2E_MP_MODO={modo} esta no seu shell, mas nenhum cenario do sandbox "
            "do Mercado Pago foi selecionado: make e2e e make demo nao o usam. "
            "Rode `unset E2E_MP_MODO` e tente de novo.",
            returncode=2,
        )
    for item, e_sandbox in zip(items, do_sandbox, strict=True):
        if e_sandbox and not modo:
            item.add_marker(pytest.mark.skip(reason=SEM_MODO))
        elif modo and not e_sandbox:
            item.add_marker(pytest.mark.skip(reason=COM_MODO))


def pytest_bdd_step_error(
    request: FixtureRequest,
    scenario: Scenario,
    step: Step,
    exception: Exception,
) -> None:
    """No sandbox, a falha vem com o diagnostico: estado, logs filtrados e a dica."""
    if TAG_DO_SANDBOX not in scenario.tags:
        return
    try:
        request.getfixturevalue("prova").falha_no_passo(
            f"{step.keyword} {step.name}", exception
        )
    except Exception as erro:  # o diagnostico nunca esconde a falha original
        # Uma fixture que quebrou antes (o login, por exemplo) quebra de novo aqui.
        print(f"[mp-sandbox] sem diagnóstico: {type(erro).__name__}", flush=True)
