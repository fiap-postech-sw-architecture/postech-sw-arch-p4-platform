"""O que o cenario derruba com kubectl scale volta ao que era."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from e2e.apoio.espera import TempoEsgotadoError
from e2e.apoio.kube import (
    ErroDeComandoError,
    Escalas,
    Kubectl,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

from e2e_apoio.falsos import ClusterFalso, Relogio


def _escalas(cluster: ClusterFalso, relogio: Relogio) -> Escalas:
    return Escalas(
        Kubectl("c", executor=cluster), relogio=relogio, dormir=relogio.dormir
    )


def test_escalas_zerar_derruba_e_restaurar_volta_ao_original(relogio: Relogio) -> None:
    cluster = ClusterFalso({"billing-api": 2})
    escalas = _escalas(cluster, relogio)

    escalas.zerar("ns", "billing-api")
    assert cluster.replicas["billing-api"] == 0

    escalas.restaurar("ns", "billing-api")
    assert cluster.replicas["billing-api"] == 2
    assert cluster.escalas() == [
        "deployment/billing-api --replicas=0",
        "deployment/billing-api --replicas=2",
    ]
    assert cluster.prontos() == ["deployment/billing-api"]


def test_escalas_zerar_espera_o_ultimo_pod_sair(relogio: Relogio) -> None:
    cluster = ClusterFalso({"dep": 1}, pods_demoram=3)

    _escalas(cluster, relogio).zerar("ns", "dep")

    assert sum(1 for c in cluster.comandos if "pods" in c) == 4


def test_escalas_zerar_pod_que_nao_sai_reprova_pelo_prazo(relogio: Relogio) -> None:
    cluster = ClusterFalso({"dep": 1}, pods_demoram=10_000)

    with pytest.raises(TempoEsgotadoError, match="pods de dep encerrados"):
        _escalas(cluster, relogio).zerar("ns", "dep", prazo=10)


def test_escalas_zerar_duas_vezes_guarda_o_original_da_primeira(
    relogio: Relogio,
) -> None:
    cluster = ClusterFalso({"dep": 3})
    escalas = _escalas(cluster, relogio)

    escalas.zerar("ns", "dep")
    escalas.zerar("ns", "dep")
    escalas.restaurar("ns", "dep")

    assert cluster.replicas["dep"] == 3


def test_escalas_restaurar_o_que_nao_foi_zerado_nao_faz_nada(relogio: Relogio) -> None:
    cluster = ClusterFalso({"dep": 1})

    _escalas(cluster, relogio).restaurar("ns", "dep")

    assert cluster.comandos == []


def test_escalas_restaurar_com_falha_do_kubectl_mantem_o_registro(
    relogio: Relogio,
) -> None:
    cluster = ClusterFalso({"dep": 2})
    escalas = _escalas(cluster, relogio)
    escalas.zerar("ns", "dep")
    falhar = {"vez": True}

    def executor_que_falha(argumentos: Sequence[str], prazo: float) -> str:
        if "scale" in argumentos and falhar["vez"]:
            falhar["vez"] = False
            raise ErroDeComandoError("kubectl fora do ar")
        return cluster(argumentos, prazo)

    escalas._kubectl = Kubectl("c", executor=executor_que_falha)

    with pytest.raises(ErroDeComandoError):
        escalas.restaurar("ns", "dep")
    assert cluster.replicas["dep"] == 0

    assert escalas.restaurar_todas() == ["dep"]
    assert cluster.replicas["dep"] == 2


def test_escalas_restaurar_e_idempotente(relogio: Relogio) -> None:
    cluster = ClusterFalso({"dep": 1})
    escalas = _escalas(cluster, relogio)
    escalas.zerar("ns", "dep")

    escalas.restaurar("ns", "dep")
    escalas.restaurar("ns", "dep")

    assert len(cluster.escalas()) == 2


def test_escalas_restaurar_todas_devolve_tudo_que_ficou_derrubado(
    relogio: Relogio,
) -> None:
    cluster = ClusterFalso({"a": 1, "b": 2})
    escalas = _escalas(cluster, relogio)
    escalas.zerar("ns", "a")
    escalas.zerar("ns", "b")

    restauradas = escalas.restaurar_todas()

    assert sorted(restauradas) == ["a", "b"]
    assert cluster.replicas == {"a": 1, "b": 2}
    assert escalas.restaurar_todas() == []


def test_escalas_zerar_deployment_ja_em_zero_restaura_para_um(relogio: Relogio) -> None:
    cluster = ClusterFalso({"dep": 0})
    escalas = _escalas(cluster, relogio)

    escalas.zerar("ns", "dep")
    escalas.restaurar("ns", "dep")

    assert cluster.replicas["dep"] == 1


def test_escalas_recuperar_do_inicio_religa_so_o_que_ficou_em_zero(
    relogio: Relogio,
) -> None:
    cluster = ClusterFalso({"parado": 0, "de-pe": 1})

    religados = _escalas(cluster, relogio).recuperar_do_inicio(
        [("ns", "parado"), ("ns", "de-pe")]
    )

    assert religados == [("ns", "parado")]
    assert cluster.replicas == {"parado": 1, "de-pe": 1}
    assert cluster.prontos() == ["deployment/parado"]
