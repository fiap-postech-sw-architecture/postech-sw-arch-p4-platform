"""Leituras puras da saga e dos logs: ordem das compensacoes, acesso e corpo de erro."""

from __future__ import annotations

import json

import pytest

from e2e.apoio.saga import (
    COMPENSACOES,
    STATUS_DA_OS,
    STATUS_EM_ORDEM,
    achar_acesso,
    comandos_de_compensacao,
    divergencias_das_metricas,
    sem_id_da_requisicao,
)


def _saga(*comandos: str | None) -> dict[str, object]:
    return {"passos": [{"comando": c} for c in comandos]}


def test_comandos_de_compensacao_ignora_os_comandos_do_fluxo_normal() -> None:
    saga = _saga(
        "SolicitarDiagnostico",
        "GerarOrcamento",
        None,
        "ReservarPecas",
        "CancelarExecucao",
        "EstornarPagamento",
        None,
        "LiberarReserva",
        "CancelarOrcamento",
        "DescartarDiagnostico",
    )

    assert comandos_de_compensacao(saga) == [
        "CancelarExecucao",
        "EstornarPagamento",
        "LiberarReserva",
        "CancelarOrcamento",
        "DescartarDiagnostico",
    ]


def test_comandos_de_compensacao_sem_compensacao_e_lista_vazia() -> None:
    assert comandos_de_compensacao(_saga("SolicitarDiagnostico", None)) == []


def test_as_cinco_compensacoes_e_os_oito_status() -> None:
    assert len(COMPENSACOES) == 5
    assert len(STATUS_EM_ORDEM) == 8
    assert STATUS_EM_ORDEM[0] == "recebida"
    assert STATUS_EM_ORDEM[-1] == "entregue"


def _acesso(request_id: str, **extra: object) -> str:
    return json.dumps(
        {"event": "http_request", "request_id": request_id, "path": "/x", **extra}
    )


def test_achar_acesso_pega_a_linha_do_request_id() -> None:
    saida = "\n".join(
        [
            "texto solto",
            _acesso("outro", trace_id="t0"),
            _acesso("abc-123", trace_id="t1"),
        ]
    )

    achado = achar_acesso(saida, "abc-123")

    assert achado is not None
    assert achado["trace_id"] == "t1"


def test_achar_acesso_ignora_linha_que_so_cita_o_id() -> None:
    citacao = json.dumps(
        {"event": "saga transition", "request_id": "abc-123", "path": "/x"}
    )
    solta = "linha de texto com abc-123 no meio"
    json_sem_ser_objeto = json.dumps(["abc-123"])

    assert (
        achar_acesso("\n".join([citacao, solta, json_sem_ser_objeto]), "abc-123")
        is None
    )


def test_achar_acesso_sem_a_linha_devolve_none() -> None:
    assert achar_acesso(_acesso("outro"), "abc-123") is None
    assert achar_acesso("", "abc-123") is None


def test_sem_id_da_requisicao_tira_so_o_id_e_nao_mexe_no_original() -> None:
    corpo = {"erro": {"codigo": "X", "mensagem": "m", "id_requisicao": "r1"}}

    limpo = sem_id_da_requisicao(corpo)

    assert limpo == {"erro": {"codigo": "X", "mensagem": "m"}}
    assert corpo["erro"]["id_requisicao"] == "r1"


def test_sem_id_da_requisicao_dois_erros_iguais_ficam_iguais() -> None:
    primeiro = {"erro": {"codigo": "X", "id_requisicao": "r1"}}
    segundo = {"erro": {"codigo": "X", "id_requisicao": "r2"}}

    assert sem_id_da_requisicao(primeiro) == sem_id_da_requisicao(segundo)


def test_sem_id_da_requisicao_corpo_sem_envelope_passa_como_esta() -> None:
    assert sem_id_da_requisicao({"detail": "422", "id_requisicao": "r1"}) == {
        "detail": "422",
        "id_requisicao": "r1",
    }


def _metricas(**mudancas: object) -> dict[str, object]:
    base: dict[str, object] = {
        "total": 3,
        "por_status": dict.fromkeys(STATUS_DA_OS, 0) | {"recebida": 3},
        "tempo_medio_por_status_segundos": {"em_diagnostico": 12.5},
    }
    return base | mudancas


def test_os_nove_status_sao_os_oito_do_fluxo_e_a_cancelada() -> None:
    assert (*STATUS_EM_ORDEM, "cancelada") == STATUS_DA_OS
    assert len(set(STATUS_DA_OS)) == 9


def test_metricas_conformes_nao_tem_divergencia() -> None:
    assert divergencias_das_metricas(_metricas()) == []
    # Sem permanencia concluida no periodo o tempo medio vem vazio.
    assert (
        divergencias_das_metricas(_metricas(tempo_medio_por_status_segundos={})) == []
    )


@pytest.mark.parametrize(
    ("corpo", "trecho"),
    [
        pytest.param({"total": 0}, "chaves", id="chave-que-falta"),
        pytest.param(_metricas(extra=1), "chaves", id="chave-a-mais"),
        pytest.param(
            _metricas(
                por_status=dict.fromkeys(STATUS_DA_OS[:-1], 0) | {"cancelad": 0},
                total=0,
            ),
            "status",
            id="status-renomeado",
        ),
        pytest.param(
            _metricas(por_status=dict.fromkeys(STATUS_DA_OS[:-1], 0), total=0),
            "status",
            id="so-oito-status",
        ),
        pytest.param(
            _metricas(por_status=dict.fromkeys(STATUS_DA_OS, 0.5), total=4.5),
            "inteiro",
            id="contagem-fracionada",
        ),
        pytest.param(
            _metricas(por_status=dict.fromkeys(STATUS_DA_OS, -1), total=-9),
            "inteiro",
            id="contagem-negativa",
        ),
        pytest.param(_metricas(total=4), "soma", id="total-maior-que-a-soma"),
        pytest.param(_metricas(total=2), "soma", id="total-menor-que-a-soma"),
        pytest.param(
            _metricas(tempo_medio_por_status_segundos={"emdiagnostico": 1.0}),
            "desconhecido",
            id="status-do-tempo-medio-desconhecido",
        ),
        pytest.param(
            _metricas(tempo_medio_por_status_segundos={"recebida": "12"}),
            "numero",
            id="tempo-medio-em-texto",
        ),
        pytest.param(
            _metricas(tempo_medio_por_status_segundos={"recebida": -1.0}),
            "numero",
            id="tempo-medio-negativo",
        ),
    ],
)
def test_metricas_com_divergencia_dizem_qual(
    corpo: dict[str, object], trecho: str
) -> None:
    (divergencia,) = divergencias_das_metricas(corpo)

    assert trecho in divergencia
