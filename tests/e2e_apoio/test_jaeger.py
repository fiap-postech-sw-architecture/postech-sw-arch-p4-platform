"""Traces do Jaeger: a saga como um trace com os tres servicos."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import httpx

from e2e.apoio.http import (
    Cliente,
)
from e2e.apoio.jaeger import Jaeger, melhor_trace, servicos_do_trace

if TYPE_CHECKING:
    from collections.abc import Sequence

    from e2e_apoio.falsos import Relogio


def _trace(identificador: str, servicos: Sequence[str], spans: int) -> dict[str, Any]:
    return {
        "traceID": identificador,
        "spans": [{"spanID": str(i)} for i in range(spans)],
        "processes": {
            f"p{i}": {"serviceName": nome} for i, nome in enumerate(servicos)
        },
    }


def test_servicos_do_trace_une_os_processos() -> None:
    trace = _trace("t1", ["os-service", "billing-service", "os-service"], 3)

    assert servicos_do_trace(trace) == {"os-service", "billing-service"}
    assert servicos_do_trace({"traceID": "vazio"}) == set()


def test_melhor_trace_escolhe_o_completo_com_mais_spans() -> None:
    todos = ["os-service", "billing-service", "execution-service"]
    traces = [
        _trace("curto", ["os-service", "billing-service"], 50),
        _trace("completo-pequeno", todos, 5),
        _trace("completo-grande", todos, 45),
    ]

    escolhido = melhor_trace(traces)

    assert escolhido is not None
    assert escolhido["traceID"] == "completo-grande"


def test_melhor_trace_sem_trace_completo_devolve_none() -> None:
    assert melhor_trace([_trace("t", ["os-service"], 3)]) is None
    assert melhor_trace([]) is None


def test_jaeger_traces_da_ordem_consulta_cada_servico_e_junta_sem_repetir(
    relogio: Relogio,
) -> None:
    consultas: list[httpx.Request] = []

    def tratador(pedido: httpx.Request) -> httpx.Response:
        consultas.append(pedido)
        return httpx.Response(200, json={"data": [_trace("t1", ["os-service"], 1)]})

    jaeger = Jaeger(
        Cliente(
            "http://jaeger.local",
            transporte=httpx.MockTransport(tratador),
            relogio=relogio,
        )
    )

    traces = jaeger.traces_da_ordem("ordem-1")

    assert [t["traceID"] for t in traces] == ["t1"]
    assert [c.url.params["service"] for c in consultas] == [
        "os-service",
        "billing-service",
        "execution-service",
    ]
    assert json.loads(consultas[0].url.params["tags"]) == {
        "messaging.message.conversation_id": "ordem-1"
    }


def test_jaeger_resposta_sem_data_vira_lista_vazia(relogio: Relogio) -> None:
    jaeger = Jaeger(
        Cliente(
            "http://jaeger.local",
            transporte=httpx.MockTransport(
                lambda _: httpx.Response(200, json={"data": None})
            ),
            relogio=relogio,
        )
    )

    assert jaeger.traces_da_ordem("ordem-1") == []
