"""kubectl do E2E: contexto explicito, executor injetado e leitura das DLQs."""

from __future__ import annotations

import base64
import json
from typing import TYPE_CHECKING

import pytest

from e2e.apoio.kube import (
    FILAS_MORTAS,
    ErroDeComandoError,
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
    executor = ExecutorFalso(
        {"get secret": base64.b64encode(b"senha-123").decode() + "\n"}
    )

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


def test_ler_filas_mortas_exige_o_ponto_antes_de_dlq() -> None:
    assert ler_filas_mortas("xdlq\t3\nsemponto-dlq\t1\n") == {}


def test_kubectl_filas_mortas_executa_no_pod_do_broker() -> None:
    executor = ExecutorFalso({"rabbitmqctl": _SAIDA_FILAS})

    filas = Kubectl("c", executor=executor).filas_mortas()

    assert filas["billing.comandos.dlq"] == 2
    comando = " ".join(executor.comandos[0])
    assert (
        "-n pytstop-plataforma exec rabbitmq-0 -c rabbitmq -- rabbitmqctl -q "
        "list_queues" in comando
    )


def test_kubectl_filas_mortas_falha_se_uma_dlq_conhecida_nao_aparece() -> None:
    saida = "os.eventos.dlq\t0\nbilling.comandos.dlq\t0\n"
    executor = ExecutorFalso({"rabbitmqctl": saida})

    with pytest.raises(ErroDeComandoError, match=r"execucao\.comandos\.dlq"):
        Kubectl("c", executor=executor).filas_mortas()


def test_kubectl_filas_mortas_saida_vazia_nao_vira_zero_mensagens() -> None:
    with pytest.raises(ErroDeComandoError, match="nao listou as DLQs"):
        Kubectl("c", executor=ExecutorFalso()).filas_mortas()


def test_kubectl_segredo_de_chave_ausente_diz_qual_chave_falta() -> None:
    executor = ExecutorFalso({"get secret": "\n"})

    with pytest.raises(
        ErroDeComandoError, match=r"ADMIN_PASSWORD.*os-admin.*pytstop-os"
    ):
        Kubectl("c", executor=executor).segredo(
            "pytstop-os", "os-admin", "ADMIN_PASSWORD"
        )


@pytest.mark.parametrize("ausente", FILAS_MORTAS)
def test_kubectl_filas_mortas_exige_cada_uma_das_tres_dlq(ausente: str) -> None:
    saida = "".join(f"{fila}\t0\n" for fila in FILAS_MORTAS if fila != ausente)

    with pytest.raises(ErroDeComandoError, match=ausente.replace(".", r"\.")):
        Kubectl("c", executor=ExecutorFalso({"rabbitmqctl": saida})).filas_mortas()


def test_as_dlq_conhecidas_sao_as_tres_do_broker() -> None:
    assert set(FILAS_MORTAS) == {
        "billing.comandos.dlq",
        "execucao.comandos.dlq",
        "os.eventos.dlq",
    }


class _ExecutorComEntrada:
    """Registra a chamada que leva o texto do stdin."""

    def __init__(self) -> None:
        self.chamadas: list[tuple[list[str], float, str]] = []

    def __call__(self, argumentos: Sequence[str], prazo: float, entrada: str) -> str:
        self.chamadas.append((list(argumentos), prazo, entrada))
        return "ok"


def test_kubectl_executar_com_entrada_usa_o_executor_do_stdin_e_so_ele() -> None:
    sem_entrada = ExecutorFalso()
    com_entrada = _ExecutorComEntrada()
    kubectl = Kubectl("kind-x", executor=sem_entrada, executor_com_entrada=com_entrada)

    assert kubectl.executar("apply", "-f", "-", prazo=7, entrada="{}") == "ok"

    assert com_entrada.chamadas == [
        (["kubectl", "--context", "kind-x", "apply", "-f", "-"], 7, "{}")
    ]
    assert sem_entrada.comandos == []
    kubectl.executar("get", "pods")
    assert len(com_entrada.chamadas) == 1
    assert sem_entrada.comandos == [["kubectl", "--context", "kind-x", "get", "pods"]]


def test_kubectl_aplicar_json_manda_o_manifesto_so_pelo_stdin() -> None:
    com_entrada = _ExecutorComEntrada()
    kubectl = Kubectl("kind-x", executor_com_entrada=com_entrada)

    kubectl.aplicar_json({"kind": "Secret", "data": {"a": "segredo-123"}})

    comando, prazo, entrada = com_entrada.chamadas[0]
    assert comando[-5:] == ["apply", "--server-side", "--force-conflicts", "-f", "-"]
    assert prazo == 60.0
    assert json.loads(entrada) == {"kind": "Secret", "data": {"a": "segredo-123"}}
    assert "segredo-123" not in " ".join(comando)


def test_kubectl_apagar_segredo_ignora_o_que_nao_existe() -> None:
    executor = ExecutorFalso()

    Kubectl("c", executor=executor).apagar_segredo(
        "pytstop-billing", "billing-mercadopago"
    )

    assert executor.comandos[0][3:] == [
        "-n",
        "pytstop-billing",
        "delete",
        "secret",
        "billing-mercadopago",
        "--ignore-not-found",
    ]


def test_kubectl_deployments_devolve_so_o_nome() -> None:
    executor = ExecutorFalso(
        {
            "get deployment": (
                "deployment.apps/billing-service-api\n"
                "deployment.apps/billing-service-relay\n"
            )
        }
    )

    assert Kubectl("c", executor=executor).deployments("pytstop-billing") == [
        "billing-service-api",
        "billing-service-relay",
    ]
    assert Kubectl("c", executor=ExecutorFalso()).deployments("vazio") == []


def test_kubectl_variaveis_do_deployment_entram_e_saem_com_set_env() -> None:
    executor = ExecutorFalso()
    kubectl = Kubectl("c", executor=executor)

    kubectl.definir_variaveis(
        "ns", {"MP_MODE": "mercadopago", "SIMULADOR_PERMITIDO": "false"}
    )
    kubectl.remover_variaveis("ns", ["MP_MODE", "SIMULADOR_PERMITIDO"])

    assert executor.comandos[0][3:] == [
        "-n", "ns", "set", "env", "deployment", "--all",
        "MP_MODE=mercadopago", "SIMULADOR_PERMITIDO=false",
    ]  # fmt: skip
    assert executor.comandos[1][3:] == [
        "-n", "ns", "set", "env", "deployment", "--all",
        "MP_MODE-", "SIMULADOR_PERMITIDO-",
    ]  # fmt: skip


def test_kubectl_reiniciar_pede_o_rollout_restart_de_todos() -> None:
    executor = ExecutorFalso()

    Kubectl("c", executor=executor).reiniciar("pytstop-billing")

    assert executor.comandos[0][3:] == [
        "-n", "pytstop-billing", "rollout", "restart", "deployment"
    ]  # fmt: skip


def test_kubectl_ultimas_linhas_pede_o_corte_explicito() -> None:
    # Com seletor de label o kubectl corta em 10 linhas se --tail nao vier.
    executor = ExecutorFalso({"logs": "linha"})

    saida = Kubectl("c", executor=executor).ultimas_linhas(
        "ns", "billing-service-api", container="api", quantidade=25
    )

    assert saida == "linha"
    comando = " ".join(executor.comandos[0])
    assert "-l app=billing-service-api" in comando
    assert "-c api" in comando
    assert "--tail=25" in comando
    assert "--since" not in comando
