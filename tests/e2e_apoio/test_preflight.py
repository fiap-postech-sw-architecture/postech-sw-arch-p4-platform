"""Conferencia previa: o E2E so vale no overlay kind-ci."""

from __future__ import annotations

import pytest

from e2e.apoio.kube import FILAS_MORTAS, Kubectl
from e2e.apoio.preflight import (
    LIMITE_DA_BORDA_POR_MINUTO,
    DlqNaoVaziaError,
    OverlayErradoError,
    conferir_dlqs_vazias,
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


def _kubectl_das_dlqs(**mensagens: int) -> Kubectl:
    saida = "".join(
        f"{fila}\t{mensagens.get(fila.replace('.', '_'), 0)}\n" for fila in FILAS_MORTAS
    )
    return Kubectl("kind-x", executor=ExecutorFalso({"rabbitmqctl": saida}))


def test_dlqs_vazias_passam() -> None:
    conferir_dlqs_vazias(_kubectl_das_dlqs())


def test_dlq_com_mensagem_recusa_iniciar_e_diz_o_que_fazer() -> None:
    with pytest.raises(DlqNaoVaziaError) as erro:
        conferir_dlqs_vazias(_kubectl_das_dlqs(os_eventos_dlq=2))

    texto = str(erro.value)
    assert "os.eventos.dlq" in texto
    assert "make redrive" in texto
    assert "runbook-saga.md" in texto
    assert "recrie o cluster" in texto


def test_dlq_cheia_aparece_com_a_contagem_na_mensagem() -> None:
    with pytest.raises(DlqNaoVaziaError, match=r"billing\.comandos\.dlq': 3"):
        conferir_dlqs_vazias(_kubectl_das_dlqs(billing_comandos_dlq=3))
