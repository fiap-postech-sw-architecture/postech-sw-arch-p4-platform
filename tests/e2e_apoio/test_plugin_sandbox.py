"""Plugin do sandbox: interrupcao, resultado do cenario, pulos e diagnostico."""

from __future__ import annotations

import signal
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

from e2e.apoio import plugin_sandbox
from e2e.apoio.modo_billing import SINAIS_DE_INTERRUPCAO


@pytest.fixture
def sinais(monkeypatch: pytest.MonkeyPatch) -> list[tuple[int, object]]:
    registrados: list[tuple[int, object]] = []
    monkeypatch.setattr(
        signal,
        "signal",
        lambda numero, tratador: registrados.append((numero, tratador)),
    )
    return registrados


# --- sinais -------------------------------------------------------------------------


def test_no_sandbox_sighup_interrompe_como_o_ctrl_c(
    sinais: list[tuple[int, object]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("E2E_MP_MODO", "real")

    plugin_sandbox.pytest_configure(None)  # type: ignore[arg-type]  # o gancho descarta a config

    assert sinais == [(signal.SIGHUP, signal.default_int_handler)]


def test_fora_do_sandbox_nenhum_sinal_muda(
    sinais: list[tuple[int, object]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("E2E_MP_MODO", raising=False)

    plugin_sandbox.pytest_configure(None)  # type: ignore[arg-type]  # o gancho descarta a config
    plugin_sandbox.pytest_keyboard_interrupt(None)

    assert sinais == []


def test_depois_da_primeira_interrupcao_nada_mais_interrompe_o_desmonte(
    sinais: list[tuple[int, object]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("E2E_MP_MODO", "ensaio")

    plugin_sandbox.pytest_keyboard_interrupt(None)

    assert sorted(sinais) == sorted(
        (sinal, signal.SIG_IGN)
        for sinal in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
    )
    assert set(SINAIS_DE_INTERRUPCAO) == {signal.SIGINT, signal.SIGTERM, signal.SIGHUP}


# --- o relatorio de cada fase ---------------------------------------------------------


@dataclass
class ItemFalso:
    """So o que os ganchos leem e escrevem de um ``pytest.Item``."""

    marcadores: set[str] = field(default_factory=set)
    adicionados: list[Any] = field(default_factory=list)
    name: str = "test_x"

    def get_closest_marker(self, nome: str) -> object | None:
        return object() if nome in self.marcadores else None

    def add_marker(self, marcador: Any) -> None:
        self.adicionados.append(marcador)


def _guardar_relatorio(item: ItemFalso, fase: str, resultado: str) -> None:
    ciclo = plugin_sandbox.pytest_runtest_makereport(item)  # type: ignore[arg-type]  # item falso
    next(ciclo)
    relatorio = SimpleNamespace(
        when=fase, outcome=resultado, failed=resultado == "failed"
    )
    with pytest.raises(StopIteration) as fim:
        ciclo.send(relatorio)  # type: ignore[arg-type]  # falso do TestReport
    assert fim.value.value is relatorio


@pytest.mark.parametrize(
    "fase",
    [
        pytest.param("setup", id="preparacao"),
        pytest.param("call", id="chamada"),
        pytest.param("teardown", id="encerramento"),
    ],
)
def test_o_relatorio_de_cada_fase_fica_no_item(fase: str) -> None:
    item = ItemFalso()

    _guardar_relatorio(item, fase, "passed")

    assert getattr(item, f"rep_{fase}").outcome == "passed"


@pytest.mark.parametrize(
    "resultado",
    [pytest.param("passed", id="passou"), pytest.param("failed", id="falhou")],
)
def test_o_desfecho_e_o_da_chamada_e_nao_o_do_setup_nem_do_teardown(
    resultado: str,
) -> None:
    item = ItemFalso()
    _guardar_relatorio(item, "setup", "passed")
    _guardar_relatorio(item, "call", resultado)
    _guardar_relatorio(item, "teardown", "failed")

    assert plugin_sandbox.desfecho_da_chamada(item) == resultado  # type: ignore[arg-type]  # item falso


def test_sem_relatorio_da_chamada_e_com_a_sessao_interrompida_o_desfecho_e_nenhum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(plugin_sandbox._ESTADO, "interrompida", True)
    item = ItemFalso()
    _guardar_relatorio(item, "setup", "passed")  # o Ctrl-C veio antes da chamada acabar

    assert plugin_sandbox.desfecho_da_chamada(item) is None  # type: ignore[arg-type]  # item falso


def test_sem_relatorio_da_chamada_e_sem_interrupcao_a_ligacao_quebrada_reprova(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Se rep_call deixar de ser guardado, dizer "passou" ou "interrompido" mentiria.
    monkeypatch.setitem(plugin_sandbox._ESTADO, "interrompida", False)
    item = ItemFalso(name="test_cenario")
    _guardar_relatorio(item, "setup", "passed")

    with pytest.raises(
        plugin_sandbox.LigacaoDoResultadoError,
        match=r"não registrou a chamada de test_cenario.*\(rep_call\) está quebrada",
    ):
        plugin_sandbox.desfecho_da_chamada(item)  # type: ignore[arg-type]  # item falso


def test_cenario_que_falhou_no_preparo_falhou_e_nao_foi_interrompido(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(plugin_sandbox._ESTADO, "interrompida", False)
    item = ItemFalso()
    _guardar_relatorio(item, "setup", "failed")

    assert plugin_sandbox.desfecho_da_chamada(item) == "failed"  # type: ignore[arg-type]  # item falso


def test_a_primeira_interrupcao_fica_registrada_e_a_configuracao_a_zera(
    sinais: list[tuple[int, object]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("E2E_MP_MODO", raising=False)
    monkeypatch.setitem(plugin_sandbox._ESTADO, "interrompida", False)

    plugin_sandbox.pytest_keyboard_interrupt(None)

    assert plugin_sandbox._ESTADO["interrompida"] is True
    plugin_sandbox.pytest_configure(None)  # type: ignore[arg-type]  # o gancho descarta a config
    assert plugin_sandbox._ESTADO["interrompida"] is False
    assert sinais == [], "fora do sandbox nenhum sinal muda"


# --- o que roda em cada modo --------------------------------------------------


def _razoes(item: ItemFalso) -> list[str]:
    return [marcador.kwargs["reason"] for marcador in item.adicionados]


def test_sem_modo_os_cenarios_do_sandbox_sao_pulados_e_os_da_saga_seguem(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("E2E_MP_MODO", raising=False)
    sandbox, saga = ItemFalso({"mp_sandbox"}), ItemFalso()

    plugin_sandbox.pytest_collection_modifyitems([sandbox, saga])  # type: ignore[list-item]  # itens falsos

    assert _razoes(sandbox) == ["sandbox do Mercado Pago: use make mp-sandbox"]
    assert saga.adicionados == []


def test_com_modo_so_os_cenarios_do_sandbox_rodam(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("E2E_MP_MODO", "ensaio")
    sandbox, saga = ItemFalso({"mp_sandbox"}), ItemFalso()

    plugin_sandbox.pytest_collection_modifyitems([sandbox, saga])  # type: ignore[list-item]  # itens falsos

    assert sandbox.adicionados == []
    assert _razoes(saga) == ["E2E_MP_MODO definido: so o sandbox roda"]


def test_modo_esquecido_no_shell_sem_cenario_do_sandbox_e_erro_e_nao_verde(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("E2E_MP_MODO", "real")
    saga = ItemFalso()

    with pytest.raises(pytest.exit.Exception) as erro:
        plugin_sandbox.pytest_collection_modifyitems([saga])  # type: ignore[list-item]  # item falso

    assert erro.value.returncode == 2
    assert "E2E_MP_MODO=real esta no seu shell" in str(erro.value)
    assert "unset E2E_MP_MODO" in str(erro.value)
    assert saga.adicionados == []


def test_modo_definido_sem_nenhum_item_selecionado_nao_e_erro(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("E2E_MP_MODO", "real")

    plugin_sandbox.pytest_collection_modifyitems([])


# --- o diagnostico do passo que falhou -------------------------------------------


class ProvaFalsa:
    def __init__(self, *, levanta: Exception | None = None) -> None:
        self.falhas: list[tuple[str, Exception]] = []
        self._levanta = levanta

    def falha_no_passo(self, passo: str, erro: Exception) -> None:
        if self._levanta is not None:
            raise self._levanta
        self.falhas.append((passo, erro))


def _requisicao(prova: ProvaFalsa | Exception) -> Any:
    def getfixturevalue(nome: str) -> ProvaFalsa:
        assert nome == "prova"
        if isinstance(prova, Exception):
            raise prova
        return prova

    return SimpleNamespace(getfixturevalue=getfixturevalue)


def _cenario(*tags: str) -> Any:
    return SimpleNamespace(tags=set(tags))


def _passo() -> Any:
    return SimpleNamespace(keyword="Então", name="o Billing confirma o pagamento")


def test_passo_que_falha_no_sandbox_imprime_o_diagnostico() -> None:
    prova, erro = ProvaFalsa(), AssertionError("x")

    plugin_sandbox.pytest_bdd_step_error(
        _requisicao(prova),
        _cenario("mp_sandbox", "pagamento"),
        _passo(),
        erro,
    )

    assert prova.falhas == [("Então o Billing confirma o pagamento", erro)]


def test_passo_que_falha_na_saga_nao_pede_a_prova() -> None:
    pedidos: list[str] = []
    requisicao: Any = SimpleNamespace(getfixturevalue=pedidos.append)
    plugin_sandbox.pytest_bdd_step_error(
        requisicao,
        _cenario("bloco-1"),
        _passo(),
        AssertionError("x"),
    )

    assert pedidos == [], "a fixture prova nao existe fora do sandbox"


@pytest.mark.parametrize(
    "falha",
    [
        pytest.param(LookupError("prova"), id="fixture-que-quebrou-antes"),
        pytest.param(RuntimeError("coleta"), id="diagnostico-que-quebra"),
    ],
)
def test_diagnostico_que_quebra_nao_esconde_a_falha_original(
    falha: Exception, capsys: pytest.CaptureFixture[str]
) -> None:
    requisicao = (
        _requisicao(falha)
        if isinstance(falha, LookupError)
        else _requisicao(ProvaFalsa(levanta=falha))
    )

    plugin_sandbox.pytest_bdd_step_error(
        requisicao, _cenario("mp_sandbox"), _passo(), AssertionError("x")
    )

    assert f"[mp-sandbox] sem diagnóstico: {type(falha).__name__}" in (
        capsys.readouterr().out
    )
