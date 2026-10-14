"""Steps do E2E da saga (``features/saga_atendimento.feature``).

Cada step fala com os servicos pela borda, como um usuario: o atendente e o
mecanico por JWT, o cliente pelo link do e-mail. Toda espera e por polling com
prazo (``esperar``); a unica em tempo corrido e a dos 20 s do consumidor parado,
e mesmo ela afirma, a cada amostra, que a saga nao andou.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any, Final, Literal
from urllib.parse import parse_qs, urlsplit

import httpx
from pytest_bdd import given, parsers, scenarios, then, when

from e2e.ambiente import NAMESPACE_BILLING, NAMESPACE_OS, RELATORIOS, narrar
from e2e.apoio.dados import (
    codigo,
    cpf_invalido,
    cpf_valido,
    email_de_cliente,
    placa_mercosul,
)
from e2e.apoio.espera import esperar, manter
from e2e.apoio.jaeger import SERVICOS, melhor_trace, servicos_do_trace
from e2e.apoio.metricas import valor_da_serie
from e2e.apoio.segredos import mascarar, registrar
from e2e.apoio.texto import sem_acentos

if TYPE_CHECKING:
    from collections.abc import Callable

    from e2e.ambiente import Portas
    from e2e.apoio.http import Cliente
    from e2e.apoio.kube import Escalas, Kubectl
    from e2e.servicos import Api, Cenario, Json

scenarios("features/saga_atendimento.feature")

CONSUMIDOR_DO_BILLING: Final = "billing-service-consumidor"
API_DO_BILLING: Final = "billing-service-api"
STATUS_EM_ORDEM: Final = (
    "recebida",
    "em_diagnostico",
    "aguardando_aprovacao",
    "aguardando_pagamento",
    "aguardando_execucao",
    "em_execucao",
    "finalizada",
    "entregue",
)
COMPENSACOES: Final = frozenset(
    {
        "CancelarExecucao",
        "EstornarPagamento",
        "LiberarReserva",
        "CancelarOrcamento",
        "DescartarDiagnostico",
    }
)
# Prazos por salto da saga: cada um leva cerca de 1 s no kind; o resto e folga
# para o runner do CI, que e mais lento.
PRAZO_DO_SALTO: Final = 30.0
PRAZO_DA_EXPIRACAO: Final = 180.0
PRAZO_DO_TRACE: Final = 90.0
CIRCUITO_ABERTO: Final = 1.0
CIRCUITO_FECHADO: Final = 0.0
# Os mesmos 503 do circuito: a Execucao devolve 503 com o Billing fora.
HTTP_INDISPONIVEL: Final = 503
ERROS_DE_REDE: Final = (httpx.TransportError,)


# --- ajudantes ------------------------------------------------------------------


def diagnostico(api: Api, cenario: Cenario) -> str:
    """Onde a OS e a saga estao, para a mensagem de um cenario que nao chegou la."""
    try:
        ordem = api.ordem(cenario.ordem_id)
        saga = api.saga(cenario.ordem_id)
    except AssertionError as erro:
        return f"({erro})"
    passos = [f"{p['gatilho']}->{p['para']}" for p in saga["passos"][-4:]]
    return (
        f"{cenario.resumo}: status={ordem['status']} etapa={saga['etapa']} "
        f"motivo={saga['motivo']} falha={saga['falha']} ultimos passos={passos}"
    )


def esperar_status(
    api: Api, cenario: Cenario, status: str, prazo: float = PRAZO_DO_SALTO
) -> Json:
    """Espera a OS chegar a ``status``; cancelada pelo caminho, reprova na hora."""

    def condicao() -> Json | None:
        ordem = api.ordem(cenario.ordem_id)
        if ordem["status"] == status:
            return ordem
        if ordem["status"] == "cancelada":
            msg = (
                f"a OS foi cancelada antes de chegar a {status}: "
                f"{diagnostico(api, cenario)}"
            )
            raise AssertionError(msg)
        return None

    try:
        ordem = esperar(
            condicao,
            prazo=prazo,
            intervalo=0.5,
            descricao=f"{cenario.resumo} com status {status}",
            ignorar=ERROS_DE_REDE,
        )
    except AssertionError as erro:
        if "cancelada antes" in str(erro):
            raise
        raise AssertionError(f"{erro}; {diagnostico(api, cenario)}") from erro
    cenario.orcamento_id = (ordem["orcamento"] or {}).get(
        "orcamento_id", cenario.orcamento_id
    )
    narrar(f"      . {cenario.resumo} chegou a {status}")
    return ordem


def esperar_saga(
    api: Api, cenario: Cenario, etapa: str, prazo: float = PRAZO_DO_SALTO
) -> Json:
    """Espera a saga chegar a ``etapa`` (``compensada``, ``concluida``...)."""

    def condicao() -> Json | None:
        saga = api.saga(cenario.ordem_id)
        return saga if saga["etapa"] == etapa else None

    try:
        return esperar(
            condicao,
            prazo=prazo,
            intervalo=0.5,
            descricao=f"saga da {cenario.resumo} na etapa {etapa}",
            ignorar=ERROS_DE_REDE,
        )
    except AssertionError as erro:
        raise AssertionError(f"{erro}; {diagnostico(api, cenario)}") from erro


def comandos_de_compensacao(saga: Json) -> list[str]:
    return [p["comando"] for p in saga["passos"] if p["comando"] in COMPENSACOES]


def itens_do_diagnostico(cenario: Cenario, servicos: int, pecas: int) -> list[Json]:
    return [
        {"tipo": "servico", "codigo": cenario.servico, "quantidade": servicos},
        {"tipo": "peca", "codigo": cenario.peca, "quantidade": pecas},
    ]


def abrir_ordem(api: Api, cenario: Cenario) -> None:
    resposta = api.abrir_ordem(
        cenario.cliente_id, cenario.veiculo_id, "Barulho ao frear"
    )
    corpo = resposta.json()
    cenario.ordem_id = corpo["id"]
    cenario.request_id_da_abertura = resposta.headers["x-request-id"]
    assert corpo["status"] == "recebida"
    assert corpo["etapa"] == "aguardando_diagnostico"
    narrar(f"      . {cenario.resumo} aberta")


def esperar_pedido_de_diagnostico(api: Api, cenario: Cenario) -> None:
    esperar(
        lambda: any(
            d["ordem_id"] == cenario.ordem_id for d in api.diagnosticos("AGUARDANDO")
        ),
        prazo=PRAZO_DO_SALTO,
        intervalo=0.5,
        descricao=f"{cenario.resumo} na fila de diagnostico da Execucao",
        ignorar=ERROS_DE_REDE,
    )


def iniciar_diagnostico(api: Api, cenario: Cenario) -> None:
    esperar_pedido_de_diagnostico(api, cenario)
    assert api.iniciar_diagnostico(cenario.ordem_id)["status"] == "EM_ANDAMENTO"
    esperar_status(api, cenario, "em_diagnostico")


def concluir_diagnostico(api: Api, cenario: Cenario, servicos: int, pecas: int) -> None:
    resposta = api.concluir_diagnostico(
        cenario.ordem_id, itens_do_diagnostico(cenario, servicos, pecas)
    )
    assert resposta.status_code == httpx.codes.OK, (
        f"conclusao do diagnostico: HTTP {resposta.status_code} "
        f"{mascarar(resposta.text[:300])}"
    )


def ler_email_de_decisao(api: Api, portas: Portas, cenario: Cenario) -> None:
    """O cliente abre o e-mail do orcamento; o link dele e o mesmo da OS."""
    link = esperar(
        lambda: portas.mailpit.link_de_decisao(cenario.contato),
        prazo=PRAZO_DO_SALTO,
        intervalo=1.0,
        descricao=f"e-mail com o link de decisao para a {cenario.resumo}",
        ignorar=ERROS_DE_REDE,
    )
    registrar(link.rsplit("/", 1)[1])
    cenario.link_de_decisao = link
    assert link == api.ordem(cenario.ordem_id)["orcamento"]["link_decisao"], (
        "o link do e-mail difere do link do orcamento da OS"
    )


def esperar_orcamento(api: Api, portas: Portas, cenario: Cenario) -> None:
    """A OS chega a aguardando_aprovacao e o cliente recebe o e-mail com o link."""
    esperar_status(api, cenario, "aguardando_aprovacao")
    ler_email_de_decisao(api, portas, cenario)


def esperar_pagamento_solicitado(api: Api, cenario: Cenario) -> str:
    """Token do checkout do simulador, quando o pagamento fica ``solicitado``."""
    esperar_status(api, cenario, "aguardando_pagamento")

    def solicitado() -> Json | None:
        resumo = api.ordem(cenario.ordem_id)["pagamento"]
        return resumo if resumo and resumo["status"] == "solicitado" else None

    resumo = esperar(
        solicitado,
        prazo=PRAZO_DO_SALTO,
        intervalo=0.5,
        descricao=f"pagamento solicitado da {cenario.resumo}",
        ignorar=ERROS_DE_REDE,
    )
    cenario.pagamento_id = resumo["pagamento_id"]
    checkout = api.pagamento(cenario.pagamento_id)["checkout_url"]
    token = parse_qs(urlsplit(checkout).query)["token"][0]
    registrar(token)
    return str(token)


def ate_o_orcamento(
    api: Api, portas: Portas, cenario: Cenario, servicos: int, pecas: int
) -> None:
    abrir_ordem(api, cenario)
    iniciar_diagnostico(api, cenario)
    concluir_diagnostico(api, cenario, servicos, pecas)
    esperar_orcamento(api, portas, cenario)


def ate_o_pagamento(api: Api, portas: Portas, cenario: Cenario, pecas: int) -> str:
    ate_o_orcamento(api, portas, cenario, 1, pecas)
    api.decidir_pelo_link(cenario.link_de_decisao, "aprovar")
    return esperar_pagamento_solicitado(api, cenario)


def esperar_na_fila(api: Api, cenario: Cenario) -> None:
    esperar(
        lambda: any(i["ordem_id"] == cenario.ordem_id for i in api.fila()),
        prazo=PRAZO_DO_SALTO,
        intervalo=0.5,
        descricao=f"{cenario.resumo} na fila de execucao",
        ignorar=ERROS_DE_REDE,
    )


def metricas_do_circuito(portas: Portas) -> float | None:
    return valor_da_serie(
        portas.metricas_da_execucao(),
        "pytstop_circuit_breaker_aberto",
        dependencia="billing",
    )


def esperar_circuito(
    portas: Portas, aceita: Callable[[float], bool], descricao: str, prazo: float
) -> float:
    """Espera o gauge do circuito do Billing chegar a um valor que ``aceita``."""

    def lido() -> tuple[float] | None:
        # 0,0 (fechado) e falso: a tupla e o que o esperar reconhece como "achou".
        valor = metricas_do_circuito(portas)
        return (valor,) if valor is not None and aceita(valor) else None

    return esperar(
        lido, prazo=prazo, intervalo=1.0, descricao=descricao, ignorar=ERROS_DE_REDE
    )[0]


# --- contexto -------------------------------------------------------------------


@given("que os três serviços respondem pela borda")
def _servicos_respondem(api: Api, portas: Portas) -> None:
    for prefixo in ("/os", "/billing", "/execucao"):

        def saudavel(prefixo: str = prefixo) -> bool:
            resposta = api.http.pedir("GET", f"{prefixo}/api/v1/saude")
            return resposta.status_code == httpx.codes.OK

        esperar(
            saudavel,
            prazo=60,
            intervalo=2.0,
            descricao=f"{prefixo}/api/v1/saude pela borda",
            ignorar=ERROS_DE_REDE,
        )
    # Uma execucao anterior pode ter deixado o circuito do Billing aberto: espera a
    # janela de 30 s passar, para a primeira conclusao nao tomar 503 por causa dela.
    esperar_circuito(
        portas,
        lambda valor: valor < CIRCUITO_ABERTO,
        "circuito do Billing barrando",
        45,
    )


@given("que há um atendente e um mecânico autenticados")
def _usuarios_autenticados(api: Api) -> None:
    # A fixture da sessao ja fez o login; aqui o cenario prova que os tokens valem
    # (fila da Execucao: o mecanico; estoque: o admin escreveu no passo anterior).
    api.fila()


@given(
    parsers.parse(
        'que o Billing tem o preço de um serviço de "{servico}" '
        'e de uma peça de "{peca}"'
    )
)
def _precos(api: Api, cenario: Cenario, servico: str, peca: str) -> None:
    cenario.servico = codigo("SRV", cenario.execucao, cenario.numero)
    cenario.peca = codigo("PEC", cenario.execucao, cenario.numero)
    cenario.preco_servico, cenario.preco_peca = servico, peca
    api.cadastrar_preco_do_servico(cenario.servico, servico)
    api.cadastrar_preco_da_peca(cenario.peca, peca)


@given(parsers.parse("que o estoque tem {quantidade:d} unidades da peça"))
def _estoque(api: Api, cenario: Cenario, quantidade: int) -> None:
    cenario.estoque_inicial = quantidade
    api.cadastrar_estoque(cenario.peca, quantidade)


@given("que o cliente tem um veículo cadastrado")
def _cliente_com_veiculo(api: Api, cenario: Cenario) -> None:
    cenario.documento = cpf_valido()
    cenario.contato = email_de_cliente(cenario.execucao, cenario.numero)
    cenario.placa = placa_mercosul()
    cliente = api.cadastrar_cliente(
        "Cliente de teste E2E", cenario.documento, cenario.contato
    )
    cenario.cliente_id = cliente["id"]
    cenario.veiculo_id = api.cadastrar_veiculo(cliente["id"], cenario.placa)["id"]


# --- dados do cenario -----------------------------------------------------------


@given(parsers.parse("que o estoque da peça passa a ter {quantidade:d} unidade"))
def _estoque_ajustado(api: Api, cenario: Cenario, quantidade: int) -> None:
    api.ajustar_estoque(cenario.peca, quantidade)


@given(
    parsers.parse(
        "uma OS com o orçamento de {servicos:d} serviço e {pecas:d} unidades da peça "
        "aguardando a decisão do cliente"
    )
)
def _os_com_orcamento(
    api: Api, portas: Portas, cenario: Cenario, servicos: int, pecas: int
) -> None:
    ate_o_orcamento(api, portas, cenario, servicos, pecas)


@given(
    parsers.parse(
        "uma OS aguardando o pagamento, com {pecas:d} unidades da peça reservadas"
    )
)
def _os_aguardando_pagamento(
    api: Api, portas: Portas, cenario: Cenario, pecas: int
) -> None:
    ate_o_pagamento(api, portas, cenario, pecas)
    assert api.estoque(cenario.peca)["quantidade_reservada"] == pecas


@given("uma OS paga e na fila de execução")
def _os_paga(api: Api, portas: Portas, cenario: Cenario) -> None:
    token = ate_o_pagamento(api, portas, cenario, 2)
    api.simular_pagamento(cenario.pagamento_id, token, "aprovar")
    esperar_status(api, cenario, "aguardando_execucao")
    esperar_na_fila(api, cenario)


@given("uma OS com o diagnóstico iniciado")
def _os_com_diagnostico_iniciado(api: Api, kubectl: Kubectl, cenario: Cenario) -> None:
    cenario.filas_mortas_antes = kubectl.filas_mortas()
    abrir_ordem(api, cenario)
    iniciar_diagnostico(api, cenario)


# --- quando: o atendente, o mecanico e o cliente -------------------------------------


@when("o atendente abre uma OS para o veículo do cliente")
def _abrir(api: Api, cenario: Cenario) -> None:
    abrir_ordem(api, cenario)


@when("o mecânico inicia o diagnóstico")
def _iniciar_diagnostico(api: Api, cenario: Cenario) -> None:
    iniciar_diagnostico(api, cenario)


@when(
    parsers.parse(
        "o mecânico conclui o diagnóstico com {servicos:d} serviço "
        "e {pecas:d} unidades da peça"
    )
)
def _concluir(api: Api, cenario: Cenario, servicos: int, pecas: int) -> None:
    concluir_diagnostico(api, cenario, servicos, pecas)


@when("o cliente aprova o orçamento pelo link do e-mail")
def _aprovar_pelo_link(api: Api, cenario: Cenario) -> None:
    decisao = api.decidir_pelo_link(cenario.link_de_decisao, "aprovar")
    assert decisao["status"] == "APROVADO"


@when("o cliente recusa o orçamento pelo link do e-mail")
def _recusar_pelo_link(api: Api, cenario: Cenario) -> None:
    decisao = api.decidir_pelo_link(cenario.link_de_decisao, "recusar")
    assert decisao["status"] == "RECUSADO"


def pagar(api: Api, cenario: Cenario, acao: Literal["aprovar", "recusar"]) -> None:
    """O cliente clica no botao do checkout simulado."""
    token = esperar_pagamento_solicitado(api, cenario)
    api.simular_pagamento(cenario.pagamento_id, token, acao)


@when("o pagamento é aprovado no simulador do Mercado Pago")
def _pagamento_aprovado(api: Api, cenario: Cenario) -> None:
    pagar(api, cenario, "aprovar")


@when("o pagamento é recusado no simulador do Mercado Pago")
def _pagamento_recusado(api: Api, cenario: Cenario) -> None:
    pagar(api, cenario, "recusar")


@when("o mecânico inicia a execução")
def _iniciar_execucao(api: Api, cenario: Cenario) -> None:
    assert api.iniciar_execucao(cenario.ordem_id)["status"] == "EM_EXECUCAO"


@when("o mecânico finaliza a execução")
def _finalizar_execucao(api: Api, cenario: Cenario) -> None:
    assert api.finalizar_execucao(cenario.ordem_id)["status"] == "FINALIZADA"


@when("o atendente registra a entrega do veículo")
def _entregar(api: Api, cenario: Cenario) -> None:
    assert api.entregar(cenario.ordem_id)["status"] == "entregue"


@when(parsers.parse('o atendente cancela a OS com o motivo "{motivo}"'))
def _cancelar(api: Api, cenario: Cenario, motivo: str) -> None:
    cenario.ultima_resposta = api.cancelar(cenario.ordem_id, motivo)


@when("o atendente tenta cancelar a OS")
def _tentar_cancelar(api: Api, cenario: Cenario) -> None:
    cenario.ultima_resposta = api.cancelar(
        cenario.ordem_id, "Cliente desistiu tarde demais"
    )


@when("o prazo de validade do orçamento passa sem decisão do cliente")
def _prazo_sem_decisao(api: Api, cenario: Cenario) -> None:
    # Nada a fazer: o Billing vence o orcamento sozinho (72 s no kind-ci). O passo
    # prova que ate aqui ninguem decidiu, e o Entao espera o vencimento.
    assert api.ordem(cenario.ordem_id)["status"] == "aguardando_aprovacao"
    narrar("      . esperando o orçamento vencer (72 s no kind-ci)")


# --- quando: falhas injetadas ----------------------------------------------------


@given("o consumidor do Billing parado")
def _consumidor_parado(escalas: Escalas, kubectl: Kubectl, cenario: Cenario) -> None:
    cenario.filas_mortas_antes = cenario.filas_mortas_antes or kubectl.filas_mortas()
    escalas.zerar(NAMESPACE_BILLING, CONSUMIDOR_DO_BILLING)
    narrar("      . consumidor do Billing em 0 replicas")


@when("o consumidor do Billing volta")
def _consumidor_volta(escalas: Escalas) -> None:
    escalas.restaurar(NAMESPACE_BILLING, CONSUMIDOR_DO_BILLING)
    narrar("      . consumidor do Billing de volta")


@given("a API do Billing parada")
def _api_parada(escalas: Escalas) -> None:
    escalas.zerar(NAMESPACE_BILLING, API_DO_BILLING)
    narrar("      . API do Billing em 0 replicas")


@when("a API do Billing volta")
def _api_volta(escalas: Escalas) -> None:
    escalas.restaurar(NAMESPACE_BILLING, API_DO_BILLING)
    narrar("      . API do Billing de volta")


@when("o mecânico tenta concluir o diagnóstico duas vezes")
def _concluir_duas_vezes(api: Api, cenario: Cenario) -> None:
    # O circuito abre com 5 falhas e cada conclusao tenta ate 3 vezes: duas bastam.
    cenario.respostas = [
        api.concluir_diagnostico(cenario.ordem_id, itens_do_diagnostico(cenario, 1, 2))
        for _ in range(2)
    ]


@when("o circuito do Billing deixa de barrar")
def _circuito_meia_abertura(portas: Portas) -> None:
    # Aberto, o circuito barra por 30 s a partir da ultima falha (RFC-004 6.1 e
    # 10.3). Passada a janela o gauge cai a 0,5 (meia-abertura): a proxima
    # conclusao e a chamada de prova. Esperar o gauge, e nao 30 s fixos, acompanha
    # o relogio do proprio servico.
    inicio = time.monotonic()
    esperar_circuito(
        portas,
        lambda valor: valor < CIRCUITO_ABERTO,
        "circuito do Billing em meia-abertura",
        60,
    )
    narrar(
        f"      . circuito liberou a prova depois de {time.monotonic() - inicio:.0f} s"
    )


# --- entao: a OS e a saga ---------------------------------------------------


@then(parsers.parse('a OS fica com status "{status}"'))
def _status(api: Api, cenario: Cenario, status: str) -> None:
    prazo = PRAZO_DA_EXPIRACAO if "expiracao" in cenario.tags else PRAZO_DO_SALTO
    esperar_status(api, cenario, status, prazo)


@then(parsers.parse('a OS continua com status "{status}"'))
def _status_imediato(api: Api, cenario: Cenario, status: str) -> None:
    assert api.ordem(cenario.ordem_id)["status"] == status


@then(
    parsers.parse(
        'a OS segue em "{status}", com a saga em "{etapa}", '
        "durante {segundos:d} segundos"
    )
)
def _segue_parada(
    api: Api, cenario: Cenario, status: str, etapa: str, segundos: int
) -> None:
    # O DiagnosticoConcluido chega ao OS pelo consumidor dele: primeiro a saga
    # entra na etapa, depois se prova que ela fica ali.
    esperar_saga(api, cenario, etapa)

    def parada() -> bool:
        return bool(
            api.ordem(cenario.ordem_id)["status"] == status
            and api.saga(cenario.ordem_id)["etapa"] == etapa
        )

    manter(
        parada,
        duracao=segundos,
        intervalo=2.0,
        descricao=f"{cenario.resumo} em {status}/{etapa} com o consumidor parado",
    )


@then("a Execução recebe o pedido de diagnóstico da OS")
def _execucao_recebe(api: Api, cenario: Cenario) -> None:
    esperar_pedido_de_diagnostico(api, cenario)


@then(parsers.parse('o orçamento da OS soma "{total}"'))
def _total(cenario: Cenario, api: Api, total: str) -> None:
    assert api.ordem(cenario.ordem_id)["orcamento"]["total"] == total


@then("o cliente recebe o e-mail com o link de decisão do orçamento")
def _email_com_link(api: Api, portas: Portas, cenario: Cenario) -> None:
    ler_email_de_decisao(api, portas, cenario)
    assert cenario.link_de_decisao.startswith(
        "https://localhost/billing/api/v1/publico/"
    )


@then(
    parsers.parse(
        "o estoque da peça tem saldo de {saldo:d} com {reservadas:d} reservadas"
    )
)
def _estoque_da_peca(api: Api, cenario: Cenario, saldo: int, reservadas: int) -> None:
    def condicao() -> bool:
        item = api.estoque(cenario.peca)
        return bool(
            item["quantidade_disponivel"] == saldo
            and item["quantidade_reservada"] == reservadas
        )

    esperar(
        condicao,
        prazo=PRAZO_DO_SALTO,
        intervalo=0.5,
        descricao=f"estoque da peca com saldo {saldo} e {reservadas} reservadas",
        ignorar=ERROS_DE_REDE,
    )


@then("a OS aparece na fila de execução")
def _na_fila(api: Api, cenario: Cenario) -> None:
    esperar_na_fila(api, cenario)


@then("a OS não está mais na fila de execução")
def _fora_da_fila(api: Api, cenario: Cenario) -> None:
    assert all(i["ordem_id"] != cenario.ordem_id for i in api.fila())


@then(parsers.parse('a saga terminou como "{etapa}"'))
def _saga_terminou(api: Api, cenario: Cenario, etapa: str) -> None:
    saga = esperar_saga(api, cenario, etapa)
    assert saga["falha"] is None


@then(parsers.parse('a saga terminou como "{etapa}" pelo motivo "{motivo}"'))
def _saga_terminou_pelo_motivo(
    api: Api, cenario: Cenario, etapa: str, motivo: str
) -> None:
    saga = esperar_saga(api, cenario, etapa, PRAZO_DO_SALTO)
    assert saga["motivo"] == motivo
    assert saga["falha"] is None
    assert saga["plano_compensacao"] == []


@then(parsers.parse('a saga registrou o evento "{evento}"'))
def _saga_registrou(api: Api, cenario: Cenario, evento: str) -> None:
    gatilhos = [p["gatilho"] for p in api.saga(cenario.ordem_id)["passos"]]
    assert evento in gatilhos, f"{evento} nao esta nos passos da saga: {gatilhos}"


@then(parsers.parse('as compensações enviadas foram, nesta ordem: "{lista}"'))
def _ordem_das_compensacoes(api: Api, cenario: Cenario, lista: str) -> None:
    esperadas = [nome.strip() for nome in lista.split(",")]
    assert comandos_de_compensacao(api.saga(cenario.ordem_id)) == esperadas


@then("nenhum pagamento foi solicitado para a OS")
def _sem_pagamento(api: Api, cenario: Cenario) -> None:
    assert api.ordem(cenario.ordem_id)["pagamento"] is None
    comandos = [p["comando"] for p in api.saga(cenario.ordem_id)["passos"]]
    assert "SolicitarPagamento" not in comandos


@then(parsers.parse('o orçamento no Billing está "{status}"'))
def _orcamento_no_billing(api: Api, cenario: Cenario, status: str) -> None:
    esperar(
        lambda: api.orcamento(cenario.orcamento_id)["status"] == status,
        prazo=PRAZO_DO_SALTO,
        intervalo=0.5,
        descricao=f"orcamento do Billing em {status}",
        ignorar=ERROS_DE_REDE,
    )


@then(parsers.parse('o pagamento no Billing está "{status}"'))
def _pagamento_no_billing(api: Api, cenario: Cenario, status: str) -> None:
    pagamento_id = api.ordem(cenario.ordem_id)["pagamento"]["pagamento_id"]
    esperar(
        lambda: api.pagamento(pagamento_id)["status"] == status,
        prazo=PRAZO_DO_SALTO,
        intervalo=0.5,
        descricao=f"pagamento do Billing em {status}",
        ignorar=ERROS_DE_REDE,
    )


@then(parsers.parse('o pagamento no Billing está "{status}" e não registra estorno'))
def _pagamento_sem_estorno(api: Api, cenario: Cenario, status: str) -> None:
    _pagamento_no_billing(api, cenario, status)
    pagamento = api.pagamento(api.ordem(cenario.ordem_id)["pagamento"]["pagamento_id"])
    assert pagamento["estornado_em"] is None
    assert pagamento["motivo_estorno"] is None


@then(parsers.parse('o diagnóstico da OS está "{status}"'))
def _diagnostico_da_os(api: Api, cenario: Cenario, status: str) -> None:
    esperar(
        lambda: any(
            d["ordem_id"] == cenario.ordem_id for d in api.diagnosticos(status)
        ),
        prazo=PRAZO_DO_SALTO,
        intervalo=0.5,
        descricao=f"diagnostico da {cenario.resumo} em {status}",
        ignorar=ERROS_DE_REDE,
    )


@then(parsers.parse('o cancelamento é aceito com a etapa "{etapa}"'))
def _cancelamento_aceito(cenario: Cenario, etapa: str) -> None:
    resposta = cenario.ultima_resposta
    assert resposta is not None
    assert resposta.status_code == httpx.codes.ACCEPTED, resposta.status_code
    assert resposta.json()["etapa"] == etapa


@then(
    parsers.parse(
        'a API responde {codigo:d} com o código "{erro}" e a mensagem "{mensagem}"'
    )
)
def _erro_da_api(cenario: Cenario, codigo: int, erro: str, mensagem: str) -> None:
    resposta = cenario.ultima_resposta
    assert resposta is not None
    assert resposta.status_code == codigo, f"HTTP {resposta.status_code}"
    corpo = resposta.json()["erro"]
    assert corpo["codigo"] == erro
    # A mensagem e texto de produto (acentuado); o que o cenario fixa e o sentido.
    assert sem_acentos(corpo["mensagem"]) == sem_acentos(mensagem)


@then('o histórico da OS mostra os oito status em ordem, de "recebida" a "entregue"')
def _historico(api: Api, cenario: Cenario) -> None:
    mudancas = api.historico(cenario.ordem_id)["mudancas"]
    assert [m["para"] for m in mudancas] == list(STATUS_EM_ORDEM)
    assert mudancas[0]["de"] is None


# --- entao: rastreio ------------------------------------------------------------------


def log_da_abertura(kubectl: Kubectl, request_id: str) -> Json | None:
    """A linha de acesso da api do OS com este ``X-Request-ID``, ou ``None``."""
    saida = kubectl.logs(NAMESPACE_OS, "os-service-api", container="api", desde="15m")
    for linha in saida.splitlines():
        if request_id not in linha:
            continue
        try:
            registro = json.loads(linha)
        except json.JSONDecodeError:
            continue
        if (
            registro.get("request_id") == request_id
            and registro.get("event") == "http_request"
        ):
            achado: Json = registro
            return achado
    return None


@then("o X-Request-ID devolvido pelo Kong aparece no log da API do OS")
def _request_id_no_log(kubectl: Kubectl, cenario: Cenario) -> None:
    registro = esperar(
        lambda: log_da_abertura(kubectl, cenario.request_id_da_abertura),
        prazo=30,
        intervalo=2.0,
        descricao="X-Request-ID da abertura no log da api do OS",
    )
    assert registro["path"].endswith("/ordens-de-servico")
    # O span do POST e a raiz do trace da saga: o trace_id do log e o do Jaeger.
    assert registro["trace_id"] == cenario.trace_id, (
        "o trace_id do log difere do trace da saga"
    )


@then(
    "o trace da saga no Jaeger tem spans do os-service, do billing-service "
    "e do execution-service"
)
def _trace(portas: Portas, cenario: Cenario) -> None:
    trace = esperar(
        lambda: melhor_trace(portas.jaeger.traces_da_ordem(cenario.ordem_id)),
        prazo=PRAZO_DO_TRACE,
        intervalo=3.0,
        descricao=f"trace da {cenario.resumo} no Jaeger com {', '.join(SERVICOS)}",
        ignorar=ERROS_DE_REDE,
    )
    assert servicos_do_trace(trace) >= set(SERVICOS)
    cenario.trace_id = str(trace["traceID"])
    RELATORIOS.mkdir(parents=True, exist_ok=True)
    (RELATORIOS / f"trace-{cenario.trace_id}.json").write_text(
        portas.baixar_trace(cenario.trace_id)
    )
    narrar(f"      . trace {cenario.trace_id} com {len(trace['spans'])} spans")


# --- entao: resiliencia ---------------------------------------------------------------


@then("nenhuma mensagem nova foi parar nas filas de mensagens mortas")
def _sem_mensagens_mortas(kubectl: Kubectl, cenario: Cenario) -> None:
    depois = kubectl.filas_mortas()
    novas = {
        fila: total - cenario.filas_mortas_antes.get(fila, 0)
        for fila, total in depois.items()
        if total > cenario.filas_mortas_antes.get(fila, 0)
    }
    assert not novas, f"mensagens novas nas DLQs: {novas}"
    narrar(f"      . DLQs: {depois}")


@then("as duas respostas são 503")
def _duas_respostas_503(cenario: Cenario) -> None:
    assert [r.status_code for r in cenario.respostas] == [
        HTTP_INDISPONIVEL,
        HTTP_INDISPONIVEL,
    ]


@then("o circuito do Billing está aberto na Execução")
def _circuito_aberto(portas: Portas) -> None:
    esperar_circuito(
        portas, lambda valor: valor == CIRCUITO_ABERTO, "circuito do Billing aberto", 15
    )


@then("o circuito do Billing está fechado na Execução")
def _circuito_fechado(portas: Portas) -> None:
    esperar_circuito(
        portas,
        lambda valor: valor == CIRCUITO_FECHADO,
        "circuito do Billing fechado",
        15,
    )


# --- entao: validacao e borda --------------------------------------------------------


@when("o atendente cadastra um cliente com um CPF de dígito verificador errado")
def _cadastrar_cpf_invalido(api: Api, cenario: Cenario) -> None:
    cenario.ultima_resposta = api.cadastrar_cliente_bruto(
        "Cliente com CPF invalido", cpf_invalido(), "cpf-invalido@clientes.pytstop.dev"
    )


@then(parsers.parse("a API responde {codigo:d}"))
def _api_responde(cenario: Cenario, codigo: int) -> None:
    resposta = cenario.ultima_resposta
    assert resposta is not None
    assert resposta.status_code == codigo, f"HTTP {resposta.status_code}"


def sem_id_da_requisicao(resposta: httpx.Response) -> Any:
    """Corpo do erro sem o ``id_requisicao``, que muda a cada pedido."""
    corpo = resposta.json()
    corpo.get("erro", {}).pop("id_requisicao", None)
    return corpo


@then(
    "o acompanhamento público dá o mesmo 404 para um CPF inválido "
    "e para um CPF inexistente"
)
def _acompanhamento_igual(api: Api, cenario: Cenario) -> None:
    invalido = api.acompanhar(cenario.placa, cpf_invalido())
    inexistente = api.acompanhar(cenario.placa, cpf_valido())
    assert invalido.status_code == inexistente.status_code == httpx.codes.NOT_FOUND
    assert sem_id_da_requisicao(invalido) == sem_id_da_requisicao(inexistente)
    # O CPF valido do dono, com a placa dele, ainda nao tem OS: tambem 404, igual.
    assert (
        api.acompanhar(cenario.placa, cenario.documento).status_code
        == httpx.codes.NOT_FOUND
    )


@then(parsers.parse('o Swagger de "{prefixo}" abre pelo Kong sob o próprio prefixo'))
def _swagger(borda: Cliente, prefixo: str) -> None:
    docs = borda.pedir("GET", f"{prefixo}/docs", esperado=[200])
    assert f"{prefixo}/openapi.json" in docs.text
    especificacao = borda.pedir("GET", f"{prefixo}/openapi.json", esperado=[200]).json()
    assert {"url": prefixo} in especificacao["servers"]
    assert especificacao["paths"], "o openapi.json nao lista nenhuma rota"
