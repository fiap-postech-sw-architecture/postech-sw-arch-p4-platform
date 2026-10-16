"""Verificacao dos paineis de negocio no Prometheus do kind, depois do E2E."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from e2e.apoio import paineis
from e2e.apoio.kube import ErroDeComandoError, Kubectl
from e2e.apoio.paineis import (
    Consulta,
    Resultado,
    carregar,
    contar_series,
    gerar_resumo,
    principal,
    resolver,
    verificar,
)
from e2e_apoio.falsos import ExecutorFalso

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

CAMINHO = "/api/v1/namespaces/pytstop-plataforma/services/prometheus:9090/proxy"


def resposta(series: int) -> str:
    resultado = [{"metric": {}, "value": [1, "1"]}] * series
    return json.dumps({"status": "success", "data": {"result": resultado}})


class PrometheusFalso:
    """Executor do kubectl: o Prometheus responde por um trecho da consulta."""

    def __init__(
        self, vazias: Sequence[str] = (), quebradas: Sequence[str] = ()
    ) -> None:
        self.consultas: list[str] = []
        self._vazias = vazias
        self._quebradas = quebradas

    def __call__(self, argumentos: Sequence[str], prazo: float) -> str:
        assert prazo > 0
        self.consultas.append(argumentos[-1])
        if any(trecho in argumentos[-1] for trecho in self._quebradas):
            msg = "kubectl get --raw: saiu com 1: bad_data"
            raise ErroDeComandoError(msg)
        if any(trecho in argumentos[-1] for trecho in self._vazias):
            return resposta(0)
        return resposta(2)


def test_resolver_poe_o_periodo_e_a_taxa_como_o_grafana_resolveria() -> None:
    assert resolver("sum(increase(x[$__range])) / rate(y[$__rate_interval])") == (
        "sum(increase(x[1h])) / rate(y[5m])"
    )


def test_carregar_marca_so_os_paineis_de_negocio_como_obrigatorios() -> None:
    consultas = carregar()
    obrigatorias = [c for c in consultas if c.obrigatoria]

    assert obrigatorias
    assert all(c.origem.startswith("pytstop-negocio-") for c in obrigatorias)
    assert any(c.origem.startswith("pytstop-saga ") for c in consultas)
    assert any(c.origem.startswith("alerta pytstop-saga-parada") for c in consultas)
    assert not [
        c
        for c in consultas
        if c.origem.startswith(("pytstop-saga ", "pytstop-servicos ", "alerta "))
        and c.obrigatoria
    ]
    assert (
        Consulta(
            "pytstop-negocio-atendimento 1 Volume diário de OS",
            "round(sum(increase(pytstop_os_criadas_total[1d])))",
            obrigatoria=True,
        )
        in consultas
    )


def test_contar_series_manda_a_consulta_resolvida_pelo_proxy_do_apiserver() -> None:
    executor = PrometheusFalso()

    total = contar_series(
        Kubectl("kind-teste", executor=executor), "sum(increase(x[$__range]))"
    )

    assert total == 2
    assert executor.consultas == [
        f"{CAMINHO}/api/v1/query?query=sum%28increase%28x%5B1h%5D%29%29"
    ]


def test_contar_series_reprova_resposta_que_nao_e_sucesso() -> None:
    erro = json.dumps({"status": "error", "errorType": "bad_data", "error": "x"})

    with pytest.raises(ErroDeComandoError, match="bad_data"):
        contar_series(
            Kubectl("c", executor=ExecutorFalso({"get --raw": erro})), "sum(x)"
        )


def test_verificar_registra_serie_vazia_e_erro_sem_parar_nas_demais() -> None:
    consultas = [
        Consulta("a", "sum(boa)", obrigatoria=True),
        Consulta("b", "sum(vazia)", obrigatoria=True),
        Consulta("c", "sum(quebrada)", obrigatoria=True),
    ]

    resultados = verificar(
        Kubectl(
            "c",
            executor=PrometheusFalso(vazias=["vazia"], quebradas=["quebrada"]),
        ),
        consultas,
    )

    assert [(r.series, r.ok) for r in resultados] == [
        (2, True),
        (0, False),
        (None, False),
    ]
    assert "bad_data" in resultados[2].erro
    assert resultados[0].erro == ""


def test_verificar_trata_resposta_que_nao_e_json_como_erro() -> None:
    resultados = verificar(
        Kubectl("c", executor=ExecutorFalso({"get --raw": "<html>"})),
        [Consulta("a", "sum(x)", obrigatoria=True)],
    )

    assert resultados[0].series is None
    assert not resultados[0].ok


def test_gerar_resumo_lista_o_painel_de_negocio_e_so_os_tecnicos_sem_serie() -> None:
    negocio_ok = Resultado(Consulta("negocio 1 Volume", "round(sum(a|b))", True), 3)
    negocio_vazio = Resultado(Consulta("negocio 2 Funil", "sum(c)", True), 0)
    negocio_erro = Resultado(
        Consulta("negocio 3 Taxa", "sum(d)", True), None, "bad_data"
    )
    tecnico_ok = Resultado(Consulta("tecnico 1 X", "sum(e)", False), 1)
    tecnico_vazio = Resultado(Consulta("alerta y", "sum(f)", False), 0)
    tecnico_erro = Resultado(Consulta("tecnico 2 Z", "sum(g)", False), None, "falhou")

    texto = gerar_resumo(
        [
            negocio_ok,
            negocio_vazio,
            negocio_erro,
            tecnico_ok,
            tecnico_vazio,
            tecnico_erro,
        ]
    )

    assert "3 consultas de painel de negócio, 2 sem série." in texto
    assert "| ok | 3 | negocio 1 Volume | `round(sum(a\\|b))` |" in texto
    assert "| SEM SÉRIE | 0 | negocio 2 Funil | `sum(c)` |" in texto
    assert "| SEM SÉRIE | bad_data | negocio 3 Taxa | `sum(d)` |" in texto
    assert "3 consultas, 2 sem série (informativo, não reprova)." in texto
    assert "- alerta y: `sum(f)`\n" in texto
    assert "- tecnico 2 Z: `sum(g)` (falhou)" in texto
    assert "sum(e)" not in texto


def test_principal_escreve_o_resumo_e_sai_com_zero_quando_todo_painel_tem_serie(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executor = PrometheusFalso()
    contextos: list[str] = []

    def kubectl(contexto: str) -> Kubectl:
        contextos.append(contexto)
        return Kubectl(contexto, executor=executor)

    resumo_do_actions = tmp_path / "summary.md"
    monkeypatch.setattr(paineis, "Kubectl", kubectl)
    monkeypatch.setenv("KUBE_CONTEXT", "kind-meu")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(resumo_do_actions))

    status = principal([str(tmp_path / "reports")])

    texto = (tmp_path / "reports" / "paineis.md").read_text(encoding="utf-8")
    assert status == 0
    assert contextos == ["kind-meu"]
    assert "0 sem série." in texto
    assert resumo_do_actions.read_text(encoding="utf-8").startswith(texto)
    assert len(executor.consultas) == len(carregar())


def test_principal_reprova_se_um_painel_de_negocio_vier_vazio_e_usa_o_contexto_padrao(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    contextos: list[str] = []

    def kubectl(contexto: str) -> Kubectl:
        contextos.append(contexto)
        return Kubectl(
            contexto, executor=PrometheusFalso(vazias=["pytstop_os_criadas"])
        )

    monkeypatch.setattr(paineis, "Kubectl", kubectl)
    monkeypatch.delenv("KUBE_CONTEXT", raising=False)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    status = principal([str(tmp_path)])

    assert status == 1
    assert contextos == ["kind-pytstop-p4"]
    assert "SEM SÉRIE" in (tmp_path / "paineis.md").read_text(encoding="utf-8")


def test_principal_nao_reprova_serie_vazia_de_painel_tecnico_nem_de_alerta(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def kubectl(contexto: str) -> Kubectl:
        return Kubectl(contexto, executor=PrometheusFalso(vazias=["circuit_breaker"]))

    monkeypatch.setattr(paineis, "Kubectl", kubectl)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    assert principal([str(tmp_path)]) == 0


def test_principal_pede_o_diretorio_dos_relatorios(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert principal([]) == 2
    assert "uso: python -m e2e.paineis" in capsys.readouterr().err
