"""Leituras puras da saga e dos logs que os steps usam, testadas sem cluster."""

from __future__ import annotations

import json
from typing import Any, Final

type Json = dict[str, Any]

STATUS_EM_ORDEM: Final = (
    "recebida",
    "em_diagnostico",
    "aguardando_aprovacao",
    "aguardando_pagamento",
    "aguardando_execucao",
    "em_execucao",
    "finalizada",
    "entregue",
)
# Os comandos de compensacao da saga (RFC-004 4.4); os demais comandos dos passos
# (SolicitarDiagnostico, GerarOrcamento, ...) sao do fluxo normal.
COMPENSACOES: Final = frozenset(
    {
        "CancelarExecucao",
        "EstornarPagamento",
        "LiberarReserva",
        "CancelarOrcamento",
        "DescartarDiagnostico",
    }
)


def comandos_de_compensacao(saga: Json) -> list[str]:
    """Os comandos de compensacao enviados, na ordem dos passos da saga."""
    return [p["comando"] for p in saga["passos"] if p["comando"] in COMPENSACOES]


def achar_acesso(saida_do_log: str, request_id: str) -> Json | None:
    """A linha de acesso HTTP (JSON) da API com este ``X-Request-ID``, ou ``None``."""
    for linha in saida_do_log.splitlines():
        if request_id not in linha:
            continue
        try:
            registro = json.loads(linha)
        except json.JSONDecodeError:
            continue
        if (
            isinstance(registro, dict)
            and registro.get("request_id") == request_id
            and registro.get("event") == "http_request"
        ):
            return registro
    return None


def sem_id_da_requisicao(corpo: Json) -> Json:
    """Copia do corpo de erro sem o ``id_requisicao``, que muda a cada pedido."""
    erro = corpo.get("erro")
    if not isinstance(erro, dict):
        return dict(corpo)
    return {**corpo, "erro": {k: v for k, v in erro.items() if k != "id_requisicao"}}
