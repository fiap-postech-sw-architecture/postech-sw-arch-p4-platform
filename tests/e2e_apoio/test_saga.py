"""Leituras puras da saga e dos logs: ordem das compensacoes, acesso e corpo de erro."""

from __future__ import annotations

import json

from e2e.apoio.saga import (
    COMPENSACOES,
    STATUS_EM_ORDEM,
    achar_acesso,
    comandos_de_compensacao,
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
