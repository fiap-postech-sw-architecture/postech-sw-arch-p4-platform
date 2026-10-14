"""Guarda do cluster: so kind descartavel, e o kind que publica a 443 do loopback."""

from __future__ import annotations

import pytest

from e2e.apoio.contexto import (
    ESCAPE,
    ContextoNaoDescartavelError,
    conferir_borda_local,
    conferir_contexto,
    escape_do_ambiente,
    publicacao_esperada,
)
from e2e.apoio.kube import ErroDeComandoError, Kubectl
from e2e_apoio.falsos import ExecutorFalso

PRODUCAO = "arn:aws:eks:us-east-1:111122223333:cluster/producao"


@pytest.mark.parametrize(
    "contexto",
    [
        pytest.param("kind-pytstop-p4", id="kind-padrao"),
        pytest.param("kind-x", id="kind-x"),
    ],
)
def test_conferir_contexto_aceita_contexto_de_kind(contexto: str) -> None:
    conferir_contexto(contexto, {})


@pytest.mark.parametrize(
    "contexto",
    [
        pytest.param(PRODUCAO, id="eks"),
        pytest.param("k3s-azure", id="k3s"),
        pytest.param("minikube", id="minikube"),
        pytest.param("my-kind-cluster", id="kind-no-meio"),
        pytest.param("", id="vazio"),
    ],
)
def test_conferir_contexto_recusa_o_que_nao_e_kind(contexto: str) -> None:
    with pytest.raises(ContextoNaoDescartavelError, match=ESCAPE):
        conferir_contexto(contexto, {})


def test_conferir_contexto_escape_exige_o_proprio_contexto() -> None:
    conferir_contexto(PRODUCAO, {ESCAPE: PRODUCAO})

    for valor in ("1", "true", "outro-contexto", ""):
        with pytest.raises(ContextoNaoDescartavelError):
            conferir_contexto(PRODUCAO, {ESCAPE: valor})


def test_conferir_contexto_mensagem_diz_o_que_o_e2e_faz_e_o_escape() -> None:
    with pytest.raises(ContextoNaoDescartavelError) as erro:
        conferir_contexto(PRODUCAO, {})

    texto = str(erro.value)
    assert "derruba o Billing" in texto
    assert f"{ESCAPE}={PRODUCAO}" in texto


def _kubectl(
    nos: str, contexto: str = "kind-pytstop-p4"
) -> tuple[Kubectl, ExecutorFalso]:
    executor = ExecutorFalso({"get nodes": nos})
    return Kubectl(contexto, executor=executor), executor


def test_conferir_borda_local_aceita_o_kind_que_publica_a_443() -> None:
    kubectl, executor = _kubectl("node/pytstop-p4-control-plane\n")
    docker = ExecutorFalso({"docker port": "127.0.0.1:443\n"})

    conferir_borda_local(kubectl, {}, docker)

    assert docker.comandos == [
        ["docker", "port", "pytstop-p4-control-plane", "30443/tcp"]
    ]
    assert "--context" in executor.comandos[0]


def test_conferir_borda_local_recusa_contexto_cujo_no_nao_e_o_do_kind() -> None:
    kubectl, _ = _kubectl("node/ip-10-0-0-5.ec2.internal\n")

    with pytest.raises(
        ContextoNaoDescartavelError, match="node/pytstop-p4-control-plane"
    ):
        conferir_borda_local(
            kubectl, {}, ExecutorFalso({"docker port": "127.0.0.1:443"})
        )


def test_conferir_borda_local_recusa_kind_que_nao_publica_a_443() -> None:
    kubectl, _ = _kubectl("node/pytstop-p4-control-plane")
    docker = ExecutorFalso({"docker port": "127.0.0.1:8443\n"})

    with pytest.raises(ContextoNaoDescartavelError, match="nao publica a borda"):
        conferir_borda_local(kubectl, {}, docker)


def test_conferir_borda_local_recusa_publicacao_fora_do_loopback_e_vazia() -> None:
    kubectl, _ = _kubectl("node/pytstop-p4-control-plane")

    for saida in ("0.0.0.0:443\n", ""):
        with pytest.raises(ContextoNaoDescartavelError):
            conferir_borda_local(kubectl, {}, ExecutorFalso({"docker port": saida}))


def test_conferir_borda_local_docker_que_falha_vira_erro_de_contexto() -> None:
    kubectl, _ = _kubectl("node/pytstop-p4-control-plane")

    def docker_fora(argumentos: object, prazo: float) -> str:
        del argumentos, prazo
        raise ErroDeComandoError("docker: no such container")

    with pytest.raises(ContextoNaoDescartavelError, match="nao consegui conferir"):
        conferir_borda_local(kubectl, {}, docker_fora)


def test_conferir_borda_local_com_escape_nao_confere_nada() -> None:
    kubectl, executor = _kubectl("", contexto=PRODUCAO)

    conferir_borda_local(kubectl, {ESCAPE: PRODUCAO}, ExecutorFalso())

    assert executor.comandos == []


@pytest.mark.parametrize(
    ("url", "nodeport", "publicacao"),
    [
        pytest.param("https://localhost", "30443/tcp", "127.0.0.1:443", id="padrao"),
        pytest.param(
            "https://localhost:18443", "30443/tcp", "127.0.0.1:18443", id="porta"
        ),
        pytest.param("https://127.0.0.1", "30443/tcp", "127.0.0.1:443", id="ipv4"),
        pytest.param("http://localhost", "30080/tcp", "127.0.0.1:80", id="http"),
        pytest.param(
            "http://localhost:8080", "30080/tcp", "127.0.0.1:8080", id="http-porta"
        ),
    ],
)
def test_publicacao_esperada_deriva_a_porta_do_loopback_da_url(
    url: str, nodeport: str, publicacao: str
) -> None:
    assert publicacao_esperada(url) == (nodeport, publicacao)


@pytest.mark.parametrize(
    "url",
    [
        pytest.param("https://outro-host", id="host"),
        pytest.param("https://10.0.0.5", id="ip-privado"),
        pytest.param("https://[::1]", id="ipv6"),
        pytest.param("https://localhost.evil.example", id="parecido"),
        pytest.param("https://localhost@evil.example", id="userinfo"),
    ],
)
def test_publicacao_esperada_recusa_host_fora_do_loopback(url: str) -> None:
    with pytest.raises(ContextoNaoDescartavelError, match="senha do admin"):
        publicacao_esperada(url)


def test_conferir_borda_local_usa_a_porta_da_e2e_url() -> None:
    kubectl, _ = _kubectl("node/pytstop-p4-control-plane")
    docker = ExecutorFalso({"docker port": "127.0.0.1:18443\n"})

    conferir_borda_local(kubectl, {}, docker, "https://localhost:18443")

    assert docker.comandos == [
        ["docker", "port", "pytstop-p4-control-plane", "30443/tcp"]
    ]


def test_conferir_borda_local_recusa_a_443_quando_a_url_pede_outra_porta() -> None:
    kubectl, _ = _kubectl("node/pytstop-p4-control-plane")
    docker = ExecutorFalso({"docker port": "127.0.0.1:443\n"})

    with pytest.raises(ContextoNaoDescartavelError, match=r"127\.0\.0\.1:18443"):
        conferir_borda_local(kubectl, {}, docker, "https://localhost:18443")


def test_conferir_borda_local_recusa_url_de_outro_host_sem_o_escape() -> None:
    kubectl, executor = _kubectl("node/pytstop-p4-control-plane")

    with pytest.raises(ContextoNaoDescartavelError, match="outro-host"):
        conferir_borda_local(kubectl, {}, ExecutorFalso(), "https://outro-host")

    assert executor.comandos == []


def test_conferir_borda_local_url_de_outro_host_passa_com_o_escape() -> None:
    contexto = "kind-pytstop-p4"
    kubectl, executor = _kubectl("", contexto=contexto)

    conferir_borda_local(
        kubectl, {ESCAPE: contexto}, ExecutorFalso(), "https://outro-host"
    )

    assert executor.comandos == []


def test_escape_do_ambiente_leva_so_a_chave_do_escape() -> None:
    ambiente = {"PATH": "/bin", "VARIAVEL_DO_CI": "valor-do-ci", ESCAPE: "kind-x"}

    assert escape_do_ambiente(ambiente) == {ESCAPE: "kind-x"}
    assert escape_do_ambiente({"PATH": "/bin"}) == {ESCAPE: ""}
