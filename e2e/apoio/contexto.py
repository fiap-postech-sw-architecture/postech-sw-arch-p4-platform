"""Guarda do cluster: o E2E so roda num kind descartavel e que seja o da borda local.

O E2E derruba o Billing com ``kubectl scale``, le o Secret ``os-admin``,
registra usuarios, cadastra precos, estoque e OS e nao limpa nada. Num cluster
que nao seja descartavel isso e dano, e as chamadas HTTP vao sempre para
``https://localhost``: se o contexto for de um cluster e a porta 443 for de
outro, a senha de admin de um seria enviada ao outro.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from e2e.apoio.kube import ErroDeComandoError, executar_processo

if TYPE_CHECKING:
    from collections.abc import Mapping

    from e2e.apoio.kube import Executor, Kubectl

PREFIXO_DO_KIND: Final = "kind-"
# O unico escape: o valor tem de ser o proprio contexto, para nao virar um "=1"
# esquecido no ambiente do shell.
ESCAPE: Final = "E2E_CONTEXTO_NAO_DESCARTAVEL"
# Porta do NodePort do Kong que o kind/cluster.yaml publica em 127.0.0.1:443.
NODEPORT_DA_BORDA: Final = "30443/tcp"
PUBLICACAO_DA_BORDA: Final = "127.0.0.1:443"


class ContextoNaoDescartavelError(AssertionError):
    """O contexto escolhido nao e um kind descartavel (ou nao e o da borda local)."""


def escapou(contexto: str, ambiente: Mapping[str, str]) -> bool:
    """O usuario assumiu o risco de rodar no ``contexto``, que nao e um kind."""
    return ambiente.get(ESCAPE) == contexto


def conferir_contexto(contexto: str, ambiente: Mapping[str, str]) -> None:
    """Recusa o contexto que nao comeca por ``kind-``, salvo o escape explicito."""
    if contexto.startswith(PREFIXO_DO_KIND) or escapou(contexto, ambiente):
        return
    msg = (
        f"o contexto {contexto!r} nao e um kind descartavel (kind-<cluster>): o E2E "
        "derruba o Billing, cria usuarios e nao limpa. Para rodar assim mesmo, "
        f"exporte {ESCAPE}={contexto}."
    )
    raise ContextoNaoDescartavelError(msg)


def conferir_borda_local(
    kubectl: Kubectl,
    ambiente: Mapping[str, str],
    executor: Executor = executar_processo,
) -> None:
    """O contexto e o kind que publica a 443 do loopback, a borda que o E2E usa.

    O no de um kind ``kind-<cluster>`` chama-se ``<cluster>-control-plane`` e e um
    container do Docker; ``docker port`` diz se ele publica o NodePort do Kong em
    ``127.0.0.1:443``. Com o escape, a conferencia nao se aplica (cluster que nao
    e kind): quem escapou sabe qual borda esta usando.
    """
    contexto = kubectl.contexto
    if escapou(contexto, ambiente):
        return
    cluster = contexto.removeprefix(PREFIXO_DO_KIND)
    no = f"{cluster}-control-plane"
    nos = kubectl.executar("get", "nodes", "-o", "name", prazo=30).split()
    if f"node/{no}" not in nos:
        msg = (
            f"o contexto {contexto!r} nao e o kind {cluster!r}: o kubectl enxerga os "
            f"nos {nos or 'nenhum'}, e o esperado era node/{no}."
        )
        raise ContextoNaoDescartavelError(msg)
    try:
        publicacao = executor(["docker", "port", no, NODEPORT_DA_BORDA], 20)
    except ErroDeComandoError as erro:
        msg = f"nao consegui conferir a porta 443 do no {no}: {erro}"
        raise ContextoNaoDescartavelError(msg) from erro
    if PUBLICACAO_DA_BORDA not in publicacao.split():
        msg = (
            f"o no {no} nao publica a borda em {PUBLICACAO_DA_BORDA} "
            f"(docker port: {publicacao.strip() or 'vazio'}): o https://localhost "
            "do E2E nao seria deste cluster."
        )
        raise ContextoNaoDescartavelError(msg)
