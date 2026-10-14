"""Conferencia previa: o E2E so vale no overlay kind-ci."""

from __future__ import annotations

import pytest

from e2e.apoio.kube import Kubectl
from e2e.apoio.preflight import (
    LIMITE_DA_BORDA_POR_MINUTO,
    OverlayErradoError,
    conferir_overlay_kind_ci,
)
from e2e_apoio.falsos import ExecutorFalso

KIND_CI = {
    "ORCAMENTO_VALIDADE_HORAS": "0.02",
    "PAGAMENTO_MAX_RECUSAS": "1",
    "PRAZOS_INTERVALO_SEGUNDOS": "5",
    "kongclusterplugin": str(LIMITE_DA_BORDA_POR_MINUTO),
}


def _kubectl(**trocas: str) -> Kubectl:
    return Kubectl("kind-x", executor=ExecutorFalso({**KIND_CI, **trocas}))


def test_overlay_kind_ci_passa() -> None:
    conferir_overlay_kind_ci(_kubectl())


def test_overlay_kind_ci_aceita_a_validade_escrita_de_outro_jeito() -> None:
    conferir_overlay_kind_ci(_kubectl(ORCAMENTO_VALIDADE_HORAS="0.020"))


@pytest.mark.parametrize(
    ("troca", "trecho"),
    [
        pytest.param(
            {"ORCAMENTO_VALIDADE_HORAS": "24"},
            "ORCAMENTO_VALIDADE_HORAS",
            id="validade",
        ),
        pytest.param(
            {"PAGAMENTO_MAX_RECUSAS": "3"}, "PAGAMENTO_MAX_RECUSAS", id="recusas"
        ),
        pytest.param(
            {"PRAZOS_INTERVALO_SEGUNDOS": "30"},
            "PRAZOS_INTERVALO_SEGUNDOS",
            id="prazos",
        ),
        pytest.param({"kongclusterplugin": "60"}, "rate limit global", id="rate-limit"),
        pytest.param(
            {"ORCAMENTO_VALIDADE_HORAS": ""},
            "ORCAMENTO_VALIDADE_HORAS",
            id="validade-ausente",
        ),
        pytest.param(
            {"kongclusterplugin": "nao-e-numero"},
            "rate limit global",
            id="rate-limit-lixo",
        ),
    ],
)
def test_overlay_diferente_do_kind_ci_reprova_dizendo_o_que_mudar(
    troca: dict[str, str], trecho: str
) -> None:
    with pytest.raises(OverlayErradoError, match=trecho) as erro:
        conferir_overlay_kind_ci(_kubectl(**troca))

    assert "OVERLAY=kind-ci" in str(erro.value)


def test_overlay_com_varias_divergencias_lista_todas() -> None:
    kubectl = _kubectl(ORCAMENTO_VALIDADE_HORAS="24", kongclusterplugin="60")

    with pytest.raises(OverlayErradoError) as erro:
        conferir_overlay_kind_ci(kubectl)

    assert "ORCAMENTO_VALIDADE_HORAS" in str(erro.value)
    assert "rate limit global" in str(erro.value)
