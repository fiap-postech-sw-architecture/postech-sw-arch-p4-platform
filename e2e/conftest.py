"""Fixtures do E2E: kubectl, port-forwards de sessao, usuarios e dados por cenario.

Tudo o que e de sessao (login, port-forwards, o que o cenario derruba) nasce uma
vez e e desfeito no fim; tudo o que e de cenario (cliente, veiculo, precos,
estoque, OS) nasce no cenario com codigos unicos, para nenhum depender de outro.
``E2E_NARRAR=1`` (make demo) imprime o status da OS depois de cada Entao.
"""

from __future__ import annotations

import itertools
import os
import time
from typing import TYPE_CHECKING, Any, NoReturn

import pytest

from e2e.ambiente import (
    ALVOS_DE_FALHA,
    CONTEXTO,
    DURACAO_DOS_BLOCOS,
    LIMITE_DO_BLOCO,
    MP_MODO,
    NARRAR,
    RELATORIOS,
    URL_DA_BORDA,
    Portas,
    narrar,
)
from e2e.apoio import dados
from e2e.apoio.contexto import (
    ContextoNaoDescartavelError,
    conferir_borda_local,
    conferir_contexto,
    escape_do_ambiente,
)
from e2e.apoio.credenciais import Credenciais
from e2e.apoio.http import ClienteHttp
from e2e.apoio.kube import ErroDeComandoError, Escalas, Kubectl
from e2e.apoio.preflight import conferir_dlqs_vazias, conferir_overlay_kind_ci
from e2e.apoio.preflight_mp import (
    PreflightDoSandboxError,
    Sandbox,
    ambiente_do_sandbox,
    preparar_sandbox,
)
from e2e.apoio.relatorio import Registro
from e2e.apoio.segredos import mascarar
from e2e.servicos import Api, Cenario

if TYPE_CHECKING:
    from collections.abc import Iterator

    from _pytest.fixtures import FixtureRequest
    from pytest_bdd.parser import Feature, Scenario, Step

# Mascara no relatorio, SIGTERM e log do httpx: e2e/apoio/plugin.py.
pytest_plugins = ["e2e.apoio.plugin"]


def _recusar_o_sandbox(erro: AssertionError) -> NoReturn:
    """No sandbox, o preflight que reprova encerra a sessao so com a mensagem.

    Sem traceback e sem repetir o erro em cada cenario: quem roda o script le o que
    mudar. A mensagem sai mascarada, como todo texto do E2E.
    """
    pytest.exit(f"sandbox do Mercado Pago: {mascarar(str(erro))}", returncode=2)


@pytest.fixture(scope="session")
def kubectl() -> Kubectl:
    """kubectl no contexto escolhido, depois de provado: um kind que e o da borda."""
    # So o escape entra no guarda: o ambiente inteiro apareceria no traceback.
    escape = escape_do_ambiente(os.environ)
    try:
        conferir_contexto(CONTEXTO, escape)
        kubectl = Kubectl(CONTEXTO)
        conferir_borda_local(kubectl, escape, url_da_borda=URL_DA_BORDA)
    except (ContextoNaoDescartavelError, ErroDeComandoError) as erro:
        if MP_MODO:
            _recusar_o_sandbox(erro)
        raise
    return kubectl


@pytest.fixture(scope="session")
def preflight(kubectl: Kubectl, borda: ClienteHttp) -> Sandbox | None:
    """A conferencia previa do cluster, antes de qualquer ``kubectl scale``.

    O E2E da saga exige o overlay ``kind-ci`` e as DLQs vazias. Com
    ``E2E_MP_MODO`` (sandbox do Mercado Pago), o overlay ``kind`` e, no modo real,
    o token: devolve o que o preflight decidiu.
    """
    if MP_MODO:
        try:
            return preparar_sandbox(kubectl, borda, ambiente_do_sandbox(os.environ))
        except PreflightDoSandboxError as erro:
            _recusar_o_sandbox(erro)
    conferir_overlay_kind_ci(kubectl)
    conferir_dlqs_vazias(kubectl)
    return None


@pytest.fixture(scope="session")
def execucao() -> str:
    """Identificador desta execucao: vai nos codigos e e-mails que ela cria."""
    return dados.id_da_execucao()


@pytest.fixture(scope="session", autouse=True)
def escalas(kubectl: Kubectl, preflight: Sandbox | None) -> Iterator[Escalas]:
    """O que um cenario derruba volta no fim; o que sobrou de antes, no inicio."""
    del preflight  # so garante a ordem: a conferencia vem antes de qualquer scale
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
def borda() -> Iterator[ClienteHttp]:
    cliente = ClienteHttp(URL_DA_BORDA)
    yield cliente
    cliente.fechar()


@pytest.fixture(scope="session")
def api(borda: ClienteHttp, kubectl: Kubectl, execucao: str) -> Api:
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


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """O sandbox do Mercado Pago e o E2E da saga nao rodam na mesma execucao.

    Sem ``E2E_MP_MODO`` os cenarios ``@mp_sandbox`` ficam de fora (nao ha token no
    CI e eles mexem no modo do Billing); com ele, so eles rodam. O ``make e2e`` e o
    ``make demo`` ja os excluem pelo marker, e isto cobre quem roda o pytest cru.
    Fica como ``skip`` (e nao fora da lista) para o ``--generate-missing`` do
    ``make test`` continuar vendo os passos do feature.
    """
    for item in items:
        e_sandbox = item.get_closest_marker("mp_sandbox") is not None
        if e_sandbox and not MP_MODO:
            item.add_marker(
                pytest.mark.skip(reason="sandbox do Mercado Pago: use make mp-sandbox")
            )
        elif MP_MODO and not e_sandbox:
            item.add_marker(
                pytest.mark.skip(reason="E2E_MP_MODO definido: so o sandbox roda")
            )


def pytest_bdd_step_error(
    request: FixtureRequest,
    feature: Feature,
    scenario: Scenario,
    step: Step,
    step_func: Any,
    step_func_args: dict[str, Any],
    exception: Exception,
) -> None:
    """No sandbox, a falha vem com o diagnostico: estado, logs filtrados e a dica."""
    if "mp_sandbox" not in scenario.tags:
        return
    try:
        request.getfixturevalue("prova").falha_no_passo(
            f"{step.keyword} {step.name}", exception
        )
    except Exception as erro:  # o diagnostico nunca esconde a falha original
        # Uma fixture que quebrou antes (o login, por exemplo) quebra de novo aqui.
        print(f"[mp-sandbox] sem diagnóstico: {type(erro).__name__}", flush=True)


def pytest_bdd_before_scenario(
    request: FixtureRequest, feature: Feature, scenario: Scenario
) -> None:
    atual = request.getfixturevalue("cenario")
    atual.nome = scenario.name
    atual.tags = frozenset(scenario.tags)
    atual.inicio = time.monotonic()
    marcas = " ".join(f"@{tag}" for tag in sorted(scenario.tags))
    narrar(f"\n=== {scenario.name} ({marcas})")
    narrar("  (contexto: servicos no ar, usuarios, precos, estoque e cliente prontos)")


def do_contexto(feature: Feature, step: Step) -> bool:
    """O passo e do Contexto (Background) da feature: o video o resume numa linha."""
    contexto = feature.background
    return contexto is not None and step.line_number in {
        passo.line_number for passo in contexto.steps
    }


def pytest_bdd_after_scenario(
    request: FixtureRequest, feature: Feature, scenario: Scenario
) -> None:
    """Soma a duracao do cenario no bloco do video a que ele pertence."""
    atual: Cenario = request.getfixturevalue("cenario")
    duracao = time.monotonic() - atual.inicio
    for bloco in ("bloco-1", "bloco-2"):
        if bloco in atual.tags:
            DURACAO_DOS_BLOCOS[bloco] = DURACAO_DOS_BLOCOS.get(bloco, 0.0) + duracao
    narrar(f"  (cenario concluido em {duracao:.0f} s)")


def pytest_bdd_before_step(
    request: FixtureRequest,
    feature: Feature,
    scenario: Scenario,
    step: Step,
    step_func: Any,
) -> None:
    """Com ``E2E_NARRAR=1``: o passo do cenario (o contexto fica numa linha so)."""
    if NARRAR and not do_contexto(feature, step):
        narrar(f"  {step.keyword} {step.name}")


def pytest_bdd_after_step(
    request: FixtureRequest,
    feature: Feature,
    scenario: Scenario,
    step: Step,
    step_func: Any,
    step_func_args: dict[str, Any],
) -> None:
    """Com ``E2E_NARRAR=1``: o status e a etapa da OS depois de cada ``Entao``.

    So o ``Entao`` espera o estado que afirma; depois de um ``Quando`` assincrono
    o status ainda e o de antes e a narracao do video sairia incoerente.
    """
    if not NARRAR or step.type != "then" or do_contexto(feature, step):
        return
    atual: Cenario = request.getfixturevalue("cenario")
    if atual.ordem_id:
        ordem = request.getfixturevalue("api").os.ordem(atual.ordem_id)
        estado = f"status={ordem['status']} etapa={ordem['etapa']}"
        narrar(f"      -> {atual.resumo}: {estado}")


def pytest_sessionfinish(session: pytest.Session) -> None:
    """Com ``E2E_NARRAR=1``: o tempo de cada bloco do video contra o limite de 4 min."""
    del session
    for bloco, duracao in sorted(DURACAO_DOS_BLOCOS.items()):
        narrar(
            f"[e2e] {bloco}: {duracao:.0f} s (limite do video: {LIMITE_DO_BLOCO:.0f} s)"
        )
