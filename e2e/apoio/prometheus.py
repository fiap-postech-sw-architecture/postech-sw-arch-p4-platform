"""Prometheus do kind pelo proxy do apiserver: consulta e espera de uma raspagem.

O gate dos paineis (``paineis.py``) e a espera do cenario do consumidor parado leem o
Prometheus da plataforma como o ``make smoke``: ``kubectl get --raw`` no proxy do
apiserver, sem port-forward e sem credencial.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import quote

from e2e.apoio.espera import TempoEsgotadoError, esperar
from e2e.apoio.kube import NAMESPACE_DA_PLATAFORMA, ErroDeComandoError
from e2e.apoio.segredos import mascarar

if TYPE_CHECKING:
    from collections.abc import Callable

    from e2e.apoio.kube import Kubectl

PRAZO_DA_CONSULTA: Final = 30.0
INTERVALO_DA_ESPERA: Final = 1.0
_TAMANHO_DO_ERRO: Final = 160


def consultar(kubectl: Kubectl, expr: str) -> dict[str, Any]:
    """O ``data`` de ``/api/v1/query`` do Prometheus do kind; erro levanta."""
    caminho = (
        f"/api/v1/namespaces/{NAMESPACE_DA_PLATAFORMA}/services/prometheus:9090"
        f"/proxy/api/v1/query?query={quote(expr, safe='')}"
    )
    resposta: dict[str, Any] = json.loads(
        kubectl.executar("get", "--raw", caminho, prazo=PRAZO_DA_CONSULTA)
    )
    if resposta.get("status") != "success":
        msg = f"o Prometheus respondeu {str(resposta)[:_TAMANHO_DO_ERRO]}"
        raise ErroDeComandoError(msg)
    dados: dict[str, Any] = resposta["data"]
    return dados


def agora(kubectl: Kubectl) -> float:
    """O ``time()`` do Prometheus, em segundos: o relogio dele, nao o do E2E."""
    return float(consultar(kubectl, "time()")["result"][1])


def expressao_da_raspagem(namespace: str, job: str) -> str:
    """Instante da raspagem mais antiga entre os pods de ``job``; 0 se alguma falhou.

    O ``timestamp()`` so devolve o instante da amostra (a raspagem) quando recebe o
    seletor sozinho: de uma expressao (``timestamp(up == 1)``) devolve o da propria
    consulta, e a espera passaria na hora. Por isso a raspagem que falhou (``up`` 0)
    zera pelo produto, e nao por um filtro dentro do ``timestamp()``. Provada no
    promtool (``tests/alertas.promtool.yml``).
    """
    seletor = f'up{{job="{job}", namespace="{namespace}"}}'
    return f"min(timestamp({seletor}) * {seletor})"


def ultima_raspagem(kubectl: Kubectl, namespace: str, job: str) -> float | None:
    """Instante da raspagem mais antiga entre os pods; ``None`` sem a serie ``up``."""
    resultado = consultar(kubectl, expressao_da_raspagem(namespace, job))["result"]
    return float(resultado[0]["value"][1]) if resultado else None


def esperar_raspagem(
    kubectl: Kubectl,
    namespace: str,
    job: str,
    *,
    prazo: float,
    relogio: Callable[[], float] = time.monotonic,
    dormir: Callable[[float], None] = time.sleep,
) -> None:
    """Espera o Prometheus raspar, com sucesso, os pods de ``job`` depois de agora.

    O contador de um pod mora na memoria dele e so chega ao Prometheus na raspagem, a
    cada 15 s: o pod derrubado antes da seguinte leva o que contou desde a ultima, e o
    painel mostra menos que o servico que nao caiu (6 estornos no Billing contra 8 no
    OS). Quem vai derrubar um pod espera aqui. "Agora" e o ``time()`` do proprio
    Prometheus e a raspagem e a que ele registrou: o relogio de quem roda o E2E (um
    runner, ou um Mac com a VM do Docker) nao entra na comparacao.
    """
    descricao = (
        f"raspagem de {job} ({namespace}) pelo Prometheus depois do inicio da espera"
    )
    referencia: float | None = None
    relato = "o Prometheus nao respondeu"

    def raspou() -> bool:
        nonlocal referencia, relato
        try:
            if referencia is None:
                referencia = agora(kubectl)
            ultima = ultima_raspagem(kubectl, namespace, job)
        except (ErroDeComandoError, ValueError) as erro:
            # Proxy do apiserver passageiro ou resposta que nao e JSON: tenta de novo.
            relato = f"{type(erro).__name__}: {erro}"
            return False
        if ultima is None:
            relato = (
                "o Prometheus nao tem a serie up deste alvo: ele nao esta sendo raspado"
            )
        elif ultima == 0:
            relato = "a ultima raspagem de algum pod falhou (up 0)"
        else:
            antes = referencia - ultima
            relato = f"a ultima raspagem foi {antes:.0f} s antes do inicio"
        return ultima is not None and ultima > referencia

    try:
        esperar(
            raspou,
            prazo=prazo,
            intervalo=INTERVALO_DA_ESPERA,
            descricao=descricao,
            relogio=relogio,
            dormir=dormir,
        )
    except TempoEsgotadoError as erro:
        msg = f"{descricao}: nao ocorreu em {prazo:g} s; {relato}"
        raise TempoEsgotadoError(mascarar(msg)) from erro
