"""Guarda do cluster: o E2E so roda num kind descartavel e que seja o da borda local.

O E2E derruba o Billing com ``kubectl scale``, le o Secret ``os-admin``,
registra usuarios, cadastra precos, estoque e OS e nao limpa nada. Num cluster
que nao seja descartavel isso e dano, e as chamadas HTTP vao sempre para
``https://localhost``: se o contexto for de um cluster e a porta 443 for de
outro, a senha de admin de um seria enviada ao outro.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final
from urllib.parse import urlsplit

from e2e.apoio.kube import ErroDeComandoError, executar_processo

if TYPE_CHECKING:
    from collections.abc import Mapping

    from e2e.apoio.kube import Executor, Kubectl

PREFIXO_DO_KIND: Final = "kind-"
# O unico escape: o valor tem de ser o proprio contexto, para nao virar um "=1"
# esquecido no ambiente do shell.
ESCAPE: Final = "E2E_CONTEXTO_NAO_DESCARTAVEL"
# Os NodePorts do Kong que o kind/cluster.yaml publica no loopback (443 e 80 do host).
NODEPORT_HTTPS: Final = "30443/tcp"
NODEPORT_HTTP: Final = "30080/tcp"
# Hosts da borda que o kind publica: o loopback do proprio host.
HOSTS_DA_BORDA_LOCAL: Final = frozenset({"localhost", "127.0.0.1"})


class ContextoNaoDescartavelError(AssertionError):
    """O contexto escolhido nao e um kind descartavel (ou nao e o da borda local)."""


def escape_do_ambiente(ambiente: Mapping[str, str]) -> dict[str, str]:
    """So o escape do ambiente: o resto pode ter credencial, e o guarda que recusa
    mostra os argumentos no traceback."""
    return {ESCAPE: ambiente.get(ESCAPE, "")}


def publicacao_esperada(url_da_borda: str) -> tuple[str, str]:
    """NodePort e ``host:porta`` que o no do kind tem de publicar para ``url_da_borda``.

    ``https://localhost`` e a 443 do loopback (NodePort 30443); com ``E2E_URL`` em
    outra porta (``https://localhost:18443``) e essa porta do host. Um host fora do
    loopback nao e de um kind local: o guarda o recusa.
    """
    partes = urlsplit(url_da_borda)
    if partes.hostname not in HOSTS_DA_BORDA_LOCAL:
        msg = (
            f"a borda {url_da_borda!r} não é o loopback do kind "
            f"({sorted(HOSTS_DA_BORDA_LOCAL)}): a senha do admin iria para outro "
            f"host. Para rodar assim mesmo, exporte {ESCAPE}=<o contexto>."
        )
        raise ContextoNaoDescartavelError(msg)
    https = partes.scheme == "https"
    porta = partes.port or (443 if https else 80)
    return (NODEPORT_HTTPS if https else NODEPORT_HTTP), f"127.0.0.1:{porta}"


def escapou(contexto: str, ambiente: Mapping[str, str]) -> bool:
    """O usuario assumiu o risco de rodar no ``contexto``, que nao e um kind."""
    return ambiente.get(ESCAPE) == contexto


def conferir_contexto(contexto: str, ambiente: Mapping[str, str]) -> None:
    """Recusa o contexto que nao comeca por ``kind-``, salvo o escape explicito."""
    if contexto.startswith(PREFIXO_DO_KIND) or escapou(contexto, ambiente):
        return
    msg = (
        f"o contexto {contexto!r} não é um kind descartável (kind-<cluster>): o E2E "
        "derruba o Billing, cria usuários e não limpa. Para rodar assim mesmo, "
        f"exporte {ESCAPE}={contexto}."
    )
    raise ContextoNaoDescartavelError(msg)


def conferir_borda_local(
    kubectl: Kubectl,
    ambiente: Mapping[str, str],
    executor: Executor = executar_processo,
    url_da_borda: str = "https://localhost",
) -> None:
    """O contexto e o kind que publica a borda que o E2E usa (``E2E_URL``).

    O no de um kind ``kind-<cluster>`` chama-se ``<cluster>-control-plane`` e e um
    container do Docker; ``docker port`` diz se ele publica o NodePort do Kong na
    porta do loopback de ``url_da_borda`` (a 443, por padrao). Com o escape, a
    conferencia nao se aplica (cluster que nao e kind): quem escapou sabe qual
    borda esta usando.
    """
    contexto = kubectl.contexto
    if escapou(contexto, ambiente):
        return
    nodeport, publicacao_do_loopback = publicacao_esperada(url_da_borda)
    cluster = contexto.removeprefix(PREFIXO_DO_KIND)
    no = f"{cluster}-control-plane"
    nos = kubectl.executar("get", "nodes", "-o", "name", prazo=30).split()
    if f"node/{no}" not in nos:
        msg = (
            f"o contexto {contexto!r} não é o kind {cluster!r}: o kubectl enxerga os "
            f"nós {nos or 'nenhum'}, e o esperado era node/{no}."
        )
        raise ContextoNaoDescartavelError(msg)
    try:
        publicacao = executor(["docker", "port", no, nodeport], 20)
    except ErroDeComandoError as erro:
        msg = f"não consegui conferir a borda do nó {no}: {erro}"
        raise ContextoNaoDescartavelError(msg) from erro
    if publicacao_do_loopback not in publicacao.split():
        msg = (
            f"o nó {no} não publica a borda em {publicacao_do_loopback} "
            f"(docker port: {publicacao.strip() or 'vazio'}): o {url_da_borda} "
            "do E2E não seria deste cluster."
        )
        raise ContextoNaoDescartavelError(msg)
