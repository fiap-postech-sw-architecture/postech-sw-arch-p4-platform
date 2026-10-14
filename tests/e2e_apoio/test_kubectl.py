"""kubectl do E2E: contexto explicito, executor injetado e leitura das DLQs."""

from __future__ import annotations

from typing import TYPE_CHECKING

from e2e.apoio.kube import (
    Kubectl,
    ler_filas_mortas,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

from e2e_apoio.falsos import ExecutorFalso


def test_kubectl_executar_sempre_leva_o_contexto() -> None:
    executor = ExecutorFalso()

    Kubectl("kind-teste", executor=executor).executar("get", "pods")

    assert executor.comandos == [["kubectl", "--context", "kind-teste", "get", "pods"]]


def test_kubectl_segredo_decodifica_o_base64() -> None:
    executor = ExecutorFalso({"get secret": "c2VuaGEtMTIz\n"})

    valor = Kubectl("c", executor=executor).segredo(
        "pytstop-os", "os-admin", "ADMIN_PASSWORD"
    )

    assert valor == "senha-123"
    assert "jsonpath={.data.ADMIN_PASSWORD}" in executor.comandos[0]
    assert executor.comandos[0][3:5] == ["-n", "pytstop-os"]


def test_kubectl_valor_de_configmap_pega_o_primeiro_valor_nao_vazio() -> None:
    executor = ExecutorFalso({"configmap": "admin@pytstop.dev"})

    assert Kubectl("c", executor=executor).valor_de_configmap(
        "pytstop-os", "ADMIN_EMAIL"
    ) == ("admin@pytstop.dev")
    assert (
        Kubectl("c", executor=ExecutorFalso()).valor_de_configmap("pytstop-os", "X")
        is None
    )


def test_kubectl_replicas_le_o_spec() -> None:
    assert (
        Kubectl(
            "c", executor=ExecutorFalso({"jsonpath={.spec.replicas}": "3"})
        ).replicas("n", "d")
        == 3
    )
    assert Kubectl("c", executor=ExecutorFalso()).replicas("n", "d") == 0


def test_kubectl_escalar_monta_o_comando() -> None:
    executor = ExecutorFalso()

    Kubectl("c", executor=executor).escalar("pytstop-billing", "billing-service-api", 0)

    assert executor.comandos[0][3:] == [
        "-n",
        "pytstop-billing",
        "scale",
        "deployment/billing-service-api",
        "--replicas=0",
    ]


def test_kubectl_pods_seleciona_pelo_label_app() -> None:
    executor = ExecutorFalso({"get pods": "pod/a pod/b\n"})

    assert Kubectl("c", executor=executor).pods("ns", "app-x") == ["pod/a", "pod/b"]
    assert "app=app-x" in executor.comandos[0]


def test_kubectl_aguardar_pronto_pede_o_rollout_com_prazo_maior_no_processo() -> None:
    prazos: list[float] = []

    def executor(argumentos: Sequence[str], prazo: float) -> str:
        prazos.append(prazo)
        assert "--timeout=120s" in argumentos
        return ""

    Kubectl("c", executor=executor).aguardar_pronto("ns", "dep")

    assert prazos == [150.0]


def test_kubectl_logs_pede_todos_os_pods_sem_corte() -> None:
    executor = ExecutorFalso({"logs": "linha"})

    assert (
        Kubectl("c", executor=executor).logs("ns", "app-x", container="api", desde="3m")
        == "linha"
    )
    comando = " ".join(executor.comandos[0])
    assert "-l app=app-x" in comando
    assert "-c api" in comando
    assert "--since=3m" in comando
    assert "--tail=-1" in comando


_SAIDA_FILAS = """\
os.eventos\t0
os.eventos.dlq\t0
billing.comandos.dlq\t2
execucao.comandos.dlq\t11
billing.comandos.retry.5s\t1
linha com mais colunas aqui
"""


def test_ler_filas_mortas_so_pega_as_dlq() -> None:
    assert ler_filas_mortas(_SAIDA_FILAS) == {
        "os.eventos.dlq": 0,
        "billing.comandos.dlq": 2,
        "execucao.comandos.dlq": 11,
    }
    assert ler_filas_mortas("") == {}
    assert ler_filas_mortas("x.dlq\tmuitas") == {}


def test_kubectl_filas_mortas_executa_no_pod_do_broker() -> None:
    executor = ExecutorFalso({"rabbitmqctl": _SAIDA_FILAS})

    filas = Kubectl("c", executor=executor).filas_mortas()

    assert filas["billing.comandos.dlq"] == 2
    comando = " ".join(executor.comandos[0])
    assert (
        "-n pytstop-plataforma exec rabbitmq-0 -c rabbitmq -- rabbitmqctl -q "
        "list_queues" in comando
    )
