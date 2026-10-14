"""Port-forwards de sessao do E2E: um que falha nao deixa os outros orfaos."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from e2e.ambiente import Portas
from e2e.apoio.kube import ErroDeComandoError, Kubectl
from e2e_apoio.falsos import pids_do_kubectl_falso, processo_vivo

if TYPE_CHECKING:
    from pathlib import Path


def test_portas_abre_os_tres_e_fecha_no_fim(kubectl_falso: Path) -> None:
    # O falso do jaeger morre; aqui os tres escutam: o jaeger e trocado por um
    # Service que o falso deixa subir.
    portas = Portas(Kubectl("kind-x", binario=str(kubectl_falso)))
    portas._pontes["jaeger"]._alvo = "svc/outro"  # o falso so morre em svc/jaeger
    try:
        portas.iniciar()
        assert len(pids_do_kubectl_falso(kubectl_falso)) == 3
    finally:
        portas.encerrar()

    assert not any(processo_vivo(pid) for pid in pids_do_kubectl_falso(kubectl_falso))


def test_portas_que_falha_no_segundo_fecha_o_primeiro(kubectl_falso: Path) -> None:
    portas = Portas(Kubectl("kind-x", binario=str(kubectl_falso)))

    with pytest.raises(ErroDeComandoError, match="svc/jaeger"):
        portas.iniciar()

    pids = pids_do_kubectl_falso(kubectl_falso)
    assert len(pids) == 2
    assert not any(processo_vivo(pid) for pid in pids)
