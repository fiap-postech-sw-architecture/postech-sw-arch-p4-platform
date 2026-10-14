"""Traces do Jaeger: a saga aparece como um trace com os tres servicos."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Iterable

    from e2e.apoio.http import Cliente

SERVICOS: Final = ("os-service", "billing-service", "execution-service")
# Atributo do span de mensagem: o ordem_id (= correlation_id da saga).
ATRIBUTO_DA_SAGA: Final = "messaging.message.conversation_id"

type Trace = dict[str, Any]


def servicos_do_trace(trace: Trace) -> set[str]:
    return {str(p["serviceName"]) for p in trace.get("processes", {}).values()}


def melhor_trace(
    traces: Iterable[Trace], obrigatorios: Iterable[str] = SERVICOS
) -> Trace | None:
    """O trace com todos os servicos obrigatorios e mais spans; ``None`` se nenhum."""
    precisa = set(obrigatorios)
    completos = [t for t in traces if precisa <= servicos_do_trace(t)]
    return max(completos, key=lambda t: len(t.get("spans", [])), default=None)


class Jaeger:
    """API de consulta do Jaeger, por um port-forward do Service ``jaeger`` (16686)."""

    def __init__(self, http: Cliente) -> None:
        self._http = http

    def traces_da_ordem(self, ordem_id: str) -> list[Trace]:
        """Traces com um span de mensagem da saga ``ordem_id``, de qualquer servico."""
        achados: dict[str, Trace] = {}
        for servico in SERVICOS:
            resposta = self._http.pedir(
                "GET",
                "/api/traces",
                params={
                    "service": servico,
                    "tags": json.dumps({ATRIBUTO_DA_SAGA: ordem_id}),
                    "lookback": "1h",
                    "limit": 20,
                },
                esperado=(200,),
            )
            for trace in resposta.json().get("data") or []:
                achados[str(trace["traceID"])] = trace
        return list(achados.values())
