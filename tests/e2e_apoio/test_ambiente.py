"""O E2E e o Makefile falam do mesmo cluster e dos mesmos namespaces."""

from __future__ import annotations

import re
from pathlib import Path

from e2e import ambiente
from e2e.apoio.kube import NAMESPACE_DA_PLATAFORMA

RAIZ = Path(__file__).resolve().parents[2]
MAKEFILE = (RAIZ / "Makefile").read_text()


def _variavel(nome: str) -> str:
    achado = re.search(rf"^{nome}\s*(?:\?=|:=)\s*(.+)$", MAKEFILE, re.MULTILINE)
    assert achado, f"{nome} nao esta no Makefile"
    return achado.group(1).strip()


def test_contexto_padrao_e_o_kind_do_cluster_do_makefile() -> None:
    assert f"kind-{_variavel('CLUSTER')}" == ambiente.CONTEXTO_PADRAO


def test_cluster_do_makefile_e_o_do_kind_cluster_yaml() -> None:
    yaml = (RAIZ / "kind" / "cluster.yaml").read_text()

    assert re.search(rf"^name: {_variavel('CLUSTER')}$", yaml, re.MULTILINE)


def test_namespaces_dos_servicos_sao_os_do_makefile() -> None:
    do_makefile = set(_variavel("NAMESPACES_SERVICOS").split())

    assert do_makefile == {
        ambiente.NAMESPACE_OS,
        ambiente.NAMESPACE_BILLING,
        ambiente.NAMESPACE_EXECUCAO,
    }


def test_namespace_da_plataforma_e_o_do_makefile() -> None:
    assert _variavel("NAMESPACE") == NAMESPACE_DA_PLATAFORMA
