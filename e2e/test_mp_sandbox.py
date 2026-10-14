"""Steps do sandbox do Mercado Pago (``features/mercadopago_sandbox.feature``).

So roda por ``make mp-sandbox`` (modo real: o dono do projeto paga no navegador, com
o comprador de teste) e ``make mp-sandbox-ensaio`` (o simulador do Billing paga no
lugar dele). O Contexto e os passos da OS e da saga sao os do E2E (``test_saga.py``),
registrados de novo aqui com o mesmo texto. O resto e ligacao: a logica de cada
passo esta em ``e2e/apoio/prova.py``, e o modo do Billing, em ``modo_billing.py``,
ambos testados sem cluster.
"""

from __future__ import annotations

import itertools
from typing import TYPE_CHECKING

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from e2e import test_saga as saga
from e2e.ambiente import RELATORIOS
from e2e.apoio.plugin_sandbox import desfecho_da_chamada
from e2e.apoio.prova import Prova, gravar_evidencia_da_sessao

if TYPE_CHECKING:
    from collections.abc import Iterator

    from _pytest.fixtures import FixtureRequest

    from e2e.ambiente import Portas
    from e2e.apoio.evidencia import RegistroDoCenario
    from e2e.apoio.http import ClienteHttp
    from e2e.apoio.kube import Kubectl
    from e2e.apoio.modo_billing import ModoDoBilling
    from e2e.apoio.preflight_mp import Sandbox
    from e2e.servicos import Api, Cenario, Json

scenarios("features/mercadopago_sandbox.feature")

# Os passos do Contexto e da saga que o sandbox reaproveita do E2E, com o mesmo texto.
given("que os três microsserviços respondem pela borda")(saga._servicos_respondem)
given("que há um atendente e um mecânico autenticados")(saga._usuarios_autenticados)
given(
    parsers.parse(
        'que o Billing tem o preço de um serviço de "{servico}" '
        'e de uma peça de "{peca}"'
    )
)(saga._precos)
given(parsers.parse("que o estoque tem {quantidade:d} unidades da peça"))(saga._estoque)
given("que o cliente tem um veículo cadastrado")(saga._cliente_com_veiculo)
when(parsers.parse('o atendente cancela a OS com o motivo "{motivo}"'))(saga._cancelar)
then(parsers.parse('a OS fica com status "{status}"'))(saga._status)
then(parsers.parse('a saga terminou como "{etapa}" pelo motivo "{motivo}"'))(
    saga._saga_terminou_pelo_motivo
)
then(parsers.parse('as compensações enviadas foram, nesta ordem: "{lista}"'))(
    saga._ordem_das_compensacoes
)
then(parsers.parse('o pagamento no Billing está "{status}"'))(
    saga._pagamento_no_billing
)

# Numera os pagamentos que a pessoa faz, na sessao toda ("pagamento 1 de 2").
_NUMEROS_DO_PAGAMENTO = itertools.count(1)


def anunciar(texto: str) -> None:
    """Fala com quem roda o script, com ou sem ``E2E_NARRAR``."""
    print(texto, flush=True)


@pytest.fixture(scope="session")
def modo_billing(
    preflight: Sandbox | None, kubectl: Kubectl, borda: ClienteHttp
) -> Iterator[ModoDoBilling]:
    """O modo do Billing da sessao: real (e desfeito no fim) ou o simulador."""
    assert preflight is not None, "E2E_MP_MODO sem o preflight do sandbox"
    with preflight.sessao_do_billing(kubectl, borda, anunciar) as modo:
        yield modo


@pytest.fixture(scope="session")
def evidencia(
    preflight: Sandbox | None, kubectl: Kubectl
) -> Iterator[list[RegistroDoCenario]]:
    """Os registros dos cenarios; no fim viram ``resumo.md`` e ``evidencia.json``."""
    assert preflight is not None
    registros: list[RegistroDoCenario] = []
    yield registros
    gravar_evidencia_da_sessao(
        RELATORIOS, registros, preflight, contexto=kubectl.contexto, avisar=anunciar
    )


@pytest.fixture
def prova(
    request: FixtureRequest,
    api: Api,
    kubectl: Kubectl,
    preflight: Sandbox | None,
    cenario: Cenario,
    evidencia: list[RegistroDoCenario],
) -> Iterator[Prova]:
    assert preflight is not None
    atual = Prova.abrir(
        nome=cenario.nome or request.node.name,
        evidencia=evidencia,
        api=api,
        kubectl=kubectl,
        sandbox=preflight,
        cenario=cenario,
        esperar_status=saga.esperar_status,
        descrever_estado=saga.descrever_estado,
        avisar=anunciar,
        numeros=_NUMEROS_DO_PAGAMENTO,
    )
    yield atual
    atual.concluir(desfecho_da_chamada(request.node))


@given("que o Billing está no modo de pagamento desta execução")
def _modo_do_billing(modo_billing: ModoDoBilling) -> None:
    del modo_billing  # a fixture liga o modo e o desfaz no fim da sessao


@given(
    "uma OS aguardando o pagamento no checkout do Mercado Pago",
    target_fixture="cobranca",
)
def _os_aguardando_pagamento(
    api: Api, portas: Portas, cenario: Cenario, prova: Prova
) -> Json:
    saga.ate_o_orcamento(api, portas, cenario, 1, 2)
    api.billing.decidir_pelo_link(cenario.link_de_decisao, "aprovar")
    return prova.cobranca_aberta()


@given("uma OS paga no Mercado Pago e na fila de execução", target_fixture="cobranca")
def _os_paga(api: Api, portas: Portas, cenario: Cenario, prova: Prova) -> Json:
    saga.ate_o_orcamento(api, portas, cenario, 1, 2)
    api.billing.decidir_pelo_link(cenario.link_de_decisao, "aprovar")
    prova.pagar(prova.cobranca_aberta())
    pagamento = prova.esperar_confirmacao()
    saga.esperar_status(api, cenario, "aguardando_execucao")
    saga.esperar_na_fila(api, cenario)
    prova.conferir_aprovado(pagamento)
    return pagamento


@when("o comprador de teste paga o link do checkout")
def _pagar(prova: Prova, cobranca: Json) -> None:
    prova.pagar(cobranca)


@then("o Billing confirma o pagamento", target_fixture="cobranca")
def _billing_confirma(prova: Prova) -> Json:
    return prova.esperar_confirmacao()


@then("o Mercado Pago informa o pagamento como aprovado, no valor do orçamento")
def _mp_aprovado(prova: Prova, cobranca: Json) -> None:
    prova.conferir_aprovado(cobranca)


@then("o Mercado Pago informa o pagamento como estornado")
def _mp_estornado(prova: Prova, cobranca: Json) -> None:
    prova.conferir_estornado(cobranca)


@then("o Mercado Pago informa a preferência do checkout como expirada")
def _mp_preferencia_expirada(prova: Prova) -> None:
    prova.conferir_preferencia_expirada()
