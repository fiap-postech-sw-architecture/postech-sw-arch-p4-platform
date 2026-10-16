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
# Os nove status da OS (StatusOrdem do OS Service): os oito do fluxo e o cancelamento.
STATUS_DA_OS: Final = (*STATUS_EM_ORDEM, "cancelada")
CHAVES_DAS_METRICAS: Final = frozenset(
    {"total", "por_status", "tempo_medio_por_status_segundos"}
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


def divergencias_das_metricas(corpo: Json) -> list[str]:
    """O que a resposta de ``GET /ordens-de-servico/metricas`` difere do contrato.

    O contrato (RFC-004 6.1): ``total``, ``por_status`` com os nove status (zero onde
    nao ha OS, e o total e a soma deles) e ``tempo_medio_por_status_segundos``, esparso,
    so com status da OS e em segundos. Lista vazia = conforme.
    """
    if set(corpo) != CHAVES_DAS_METRICAS:
        return [f"chaves {sorted(corpo)}"]
    divergencias = []
    por_status = corpo["por_status"]
    if set(por_status) != set(STATUS_DA_OS):
        divergencias.append(f"status {sorted(por_status)}")
    elif not all(isinstance(n, int) and n >= 0 for n in por_status.values()):
        divergencias.append("contagem que nao e um inteiro nao negativo")
    elif corpo["total"] != sum(por_status.values()):
        divergencias.append("total diferente da soma dos status")
    tempo_medio = corpo["tempo_medio_por_status_segundos"]
    if not set(tempo_medio) <= set(STATUS_DA_OS):
        divergencias.append(f"tempo medio de status desconhecido {sorted(tempo_medio)}")
    if not all(isinstance(t, int | float) and t >= 0 for t in tempo_medio.values()):
        divergencias.append("tempo medio que nao e um numero nao negativo")
    return divergencias
