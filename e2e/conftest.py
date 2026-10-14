"""Fixtures do E2E: kubectl, port-forwards de sessao, usuarios e dados por cenario.

Tudo o que e de sessao (login, port-forwards, o que o cenario derruba) nasce uma
vez e e desfeito no fim; tudo o que e de cenario (cliente, veiculo, precos,
estoque, OS) nasce no cenario com codigos unicos, para nenhum depender de outro.
``E2E_NARRAR=1`` (make demo) imprime o status da OS depois de cada passo.
"""

from __future__ import annotations

import itertools
import os
from typing import TYPE_CHECKING, Any

import pytest

from e2e.ambiente import (
    ALVOS_DE_FALHA,
    CONTEXTO,
    NARRAR,
    RELATORIOS,
    URL_DA_BORDA,
    Portas,
    narrar,
)
from e2e.apoio import dados
from e2e.apoio.http import Cliente
from e2e.apoio.kube import Escalas, Kubectl
from e2e.apoio.relatorio import Registro
from e2e.servicos import Api, Cenario, Credenciais

if TYPE_CHECKING:
    from collections.abc import Iterator

    from _pytest.fixtures import FixtureRequest
    from pytest_bdd.parser import Feature, Scenario, Step


@pytest.fixture(scope="session")
def kubectl() -> Kubectl:
    return Kubectl(CONTEXTO)


@pytest.fixture(scope="session")
def execucao() -> str:
    """Identificador desta execucao: vai nos codigos e e-mails que ela cria."""
    return dados.id_da_execucao()


@pytest.fixture(scope="session", autouse=True)
def escalas(kubectl: Kubectl) -> Iterator[Escalas]:
    """O que um cenario derruba volta no fim; o que sobrou de antes, no inicio."""
    escalas = Escalas(kubectl)
    for _, deployment in escalas.recuperar_do_inicio(ALVOS_DE_FALHA):
        narrar(f"[e2e] {deployment} estava em 0 replicas (execucao anterior): religado")
    yield escalas
    escalas.restaurar_todas()


@pytest.fixture(autouse=True)
def desfazer_falhas(escalas: Escalas) -> Iterator[None]:
    """Cada cenario devolve o que derrubou antes do proximo comecar (isolamento)."""
    yield
    escalas.restaurar_todas()


@pytest.fixture(scope="session")
def portas(kubectl: Kubectl) -> Iterator[Portas]:
    portas = Portas(kubectl)
    portas.iniciar()
    yield portas
    portas.encerrar()


@pytest.fixture(scope="session")
def borda() -> Iterator[Cliente]:
    cliente = Cliente(URL_DA_BORDA)
    yield cliente
    cliente.fechar()


@pytest.fixture(scope="session")
def api(borda: Cliente, kubectl: Kubectl, execucao: str) -> Api:
    """Login do admin (Secret ``os-admin``) e registro do atendente e do mecanico."""
    senha = kubectl.segredo("pytstop-os", "os-admin", "ADMIN_PASSWORD")
    email = (
        os.environ.get("E2E_ADMIN_EMAIL")
        or kubectl.valor_de_configmap("pytstop-os", "ADMIN_EMAIL")
        or "admin@pytstop.dev"
    )
    credenciais = Credenciais(
        borda, admin_email=email, admin_senha=senha, execucao=execucao
    )
    credenciais.preparar()
    return Api(borda, credenciais)


@pytest.fixture(scope="session")
def registro() -> Iterator[Registro]:
    registro = Registro()
    yield registro
    RELATORIOS.mkdir(parents=True, exist_ok=True)
    registro.salvar(RELATORIOS / "cenarios.json")


@pytest.fixture(scope="session")
def contador() -> itertools.count[int]:
    """Numero do cenario na sessao: entra nos codigos de preco e estoque dele."""
    return itertools.count(1)


@pytest.fixture
def cenario(
    execucao: str, contador: itertools.count[int], registro: Registro
) -> Iterator[Cenario]:
    """Os dados do cenario; ao fim, a OS e o trace dele vao para o resumo."""
    atual = Cenario(numero=next(contador), execucao=execucao)
    yield atual
    registro.anotar(
        atual.nome, ordem_id=atual.ordem_id or "-", trace_id=atual.trace_id or "-"
    )


def pytest_bdd_before_scenario(
    request: FixtureRequest, feature: Feature, scenario: Scenario
) -> None:
    atual = request.getfixturevalue("cenario")
    atual.nome = scenario.name
    atual.tags = frozenset(scenario.tags)
    narrar(
        f"\n=== {scenario.name} ({' '.join(f'@{t}' for t in sorted(scenario.tags))})"
    )


def pytest_bdd_after_step(
    request: FixtureRequest,
    feature: Feature,
    scenario: Scenario,
    step: Step,
    step_func: Any,
    step_func_args: dict[str, Any],
) -> None:
    """Com ``E2E_NARRAR=1``: o passo e o status da OS logo depois dele."""
    if not NARRAR:
        return
    atual: Cenario = request.getfixturevalue("cenario")
    linha = f"  {step.keyword} {step.name}"
    if atual.ordem_id:
        ordem = request.getfixturevalue("api").ordem(atual.ordem_id)
        estado = f"status={ordem['status']} etapa={ordem['etapa']}"
        linha += f"\n      -> {atual.resumo}: {estado}"
    narrar(linha)
