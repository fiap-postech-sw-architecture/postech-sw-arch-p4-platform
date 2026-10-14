"""Prova: o que cada passo do sandbox faz, nos dois modos, com a API falsa."""

from __future__ import annotations

import itertools
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import httpx
import pytest

from e2e.apoio import segredos
from e2e.apoio.conferencias import DivergenciaComOMercadoPagoError
from e2e.apoio.espera import TempoEsgotadoError
from e2e.apoio.evidencia import RegistroDoCenario
from e2e.apoio.kube import ErroDeComandoError, Kubectl
from e2e.apoio.mercadopago import ClienteMercadoPago
from e2e.apoio.preflight_mp import Sandbox
from e2e.apoio.prova import PRAZO_DO_ESTORNO, SEM_CONSULTA, Prova
from e2e.servicos import Cenario
from e2e_apoio.falsos import ExecutorFalso

if TYPE_CHECKING:
    from collections.abc import Callable

    from e2e.servicos import Api, Json
    from e2e_apoio.falsos import Relogio

CHAVE_DO_MP = (
    "APP_USR-1234567890123456-101420-0a1b2c3d4e5f60718293a4b5c6d7e8f9-123456789"
)
AGORA = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
LINK_MP = "https://www.mercadopago.com.br/checkout/v1/redirect?pref_id=pref-1"
LINK_SIMULADO = (
    "https://localhost/billing/simulador/checkout/p-1?token=tok.en-do-simulador-1"
)


def _pagamento_billing(**campos: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "p-1",
        "ordem_id": "o-1",
        "status": "SOLICITADO",
        "provedor": "mercadopago",
        "valor": "210.00",
        "moeda": "BRL",
        "checkout_url": LINK_MP,
        "referencia_preferencia": "pref-1",
        "referencia_pagamento": None,
        "recusas": 0,
        "criado_em": "2026-10-20T12:00:00Z",
        "notificacoes": [],
    }
    return {**base, **campos}


def _pagamento_mp(**campos: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": 999,
        "status": "approved",
        "status_detail": "accredited",
        "transaction_amount": 210.0,
        "transaction_amount_refunded": 0,
        "currency_id": "BRL",
        "date_approved": "2026-10-20T08:00:00.000-04:00",
        "external_reference": "p-1",
        "live_mode": False,
        "payer": {"email": "comprador@testuser.com"},
    }
    return {**base, **campos}


class Mundo:
    """A API, o Billing e o Mercado Pago falsos de um cenario."""

    def __init__(self) -> None:
        self.ordem: dict[str, Any] = {
            "pagamento": None,
            "status": "aguardando_pagamento",
        }
        self.billing = _pagamento_billing()
        self.billing_depois: list[dict[str, Any]] = []
        self.saga: dict[str, Any] = {
            "etapa": "compensada",
            "motivo": "cancelamento",
            "passos": [],
        }
        self.historico: dict[str, Any] = {"mudancas": []}
        self.simulados: list[tuple[str, str, str]] = []
        self.chamadas_ao_mp: list[httpx.Request] = []
        self.mp_pagamento: Callable[[int], dict[str, Any]] = lambda _: _pagamento_mp()
        self.mp_busca: list[dict[str, Any]] = []
        self.mp_preferencia: dict[str, Any] = {"id": "pref-1"}
        self.mp_status = 200
        self._leituras = 0

    def api(self) -> Api:
        def pagamento(_pagamento_id: str) -> dict[str, Any]:
            if self.billing_depois:
                return self.billing_depois.pop(0)
            return self.billing

        def simular(pagamento_id: str, token: str, acao: str) -> dict[str, Any]:
            self.simulados.append((pagamento_id, token, acao))
            return {}

        return cast(
            "Api",
            SimpleNamespace(
                os=SimpleNamespace(
                    ordem=lambda _id: self.ordem,
                    saga=lambda _id: self.saga,
                    historico=lambda _id: self.historico,
                ),
                billing=SimpleNamespace(pagamento=pagamento, simular_pagamento=simular),
            ),
        )

    def mercado_pago(self) -> ClienteMercadoPago:
        def responder(requisicao: httpx.Request) -> httpx.Response:
            self.chamadas_ao_mp.append(requisicao)
            if self.mp_status != 200:
                return httpx.Response(self.mp_status, json={"message": "falhou"})
            caminho = requisicao.url.path
            if caminho == "/v1/payments/search":
                return httpx.Response(200, json={"results": self.mp_busca})
            if caminho.startswith("/checkout/preferences/"):
                return httpx.Response(200, json=self.mp_preferencia)
            self._leituras += 1
            return httpx.Response(200, json=self.mp_pagamento(self._leituras))

        return ClienteMercadoPago(
            CHAVE_DO_MP, transporte=httpx.MockTransport(responder)
        )


def _prova(
    mundo: Mundo,
    relogio: Relogio,
    *,
    real: bool,
    executor: ExecutorFalso | None = None,
    numeros: Any = None,
    descrever: Callable[[Api, Cenario], str] | None = None,
) -> tuple[Prova, list[str], list[str]]:
    avisos: list[str] = []
    esperas: list[str] = []
    cenario = Cenario(numero=1, execucao="ABC123", ordem_id="o-1", inicio=relogio())
    sandbox = Sandbox(
        modo="real" if real else "ensaio",
        max_recusas=3,
        mercadopago=mundo.mercado_pago() if real else None,
    )

    def esperar_status(api: Api, cenario: Cenario, status: str) -> Json:
        esperas.append(status)
        return {"status": status}

    prova = Prova(
        api=mundo.api(),
        kubectl=Kubectl("kind-x", executor=executor or ExecutorFalso()),
        sandbox=sandbox,
        cenario=cenario,
        registro=RegistroDoCenario(nome="Cenário de teste"),
        esperar_status=esperar_status,
        descrever_estado=descrever
        or (lambda _api, _cenario: "OS o-1: status=x etapa=y"),
        avisar=avisos.append,
        numeros=numeros,
        relogio=relogio,
        dormir=relogio.dormir,
        agora=lambda: AGORA,
    )
    return prova, avisos, esperas


# --- a cobranca aberta ---------------------------------------------------------------


def test_cobranca_aberta_espera_o_resumo_na_os_e_le_o_pagamento_no_billing(
    relogio: Relogio,
) -> None:
    leituras = iter([None, None, {"pagamento_id": "p-1", "status": "solicitado"}])
    prova, _, esperas = _prova(Mundo(), relogio, real=True)
    prova.api.os.ordem = lambda _id: {"pagamento": next(leituras)}  # type: ignore[assignment]

    pagamento = prova.cobranca_aberta()

    assert pagamento["id"] == "p-1"
    assert esperas == ["aguardando_pagamento"]
    assert relogio.dormidas == [1.0, 1.0]
    assert prova.cenario.pagamento_id == "p-1"
    assert prova.registro.ordem_id == "o-1"
    assert prova.registro.pagamento_id == "p-1"
    assert prova.registro.transicoes[-1][1].startswith(
        "script: cobrança criada no provedor"
    )


def test_cobranca_aberta_no_ensaio_aceita_o_provedor_simulado(relogio: Relogio) -> None:
    mundo = Mundo()
    mundo.ordem["pagamento"] = {"pagamento_id": "p-1"}
    mundo.billing = _pagamento_billing(provedor="simulado")
    prova, _, _ = _prova(mundo, relogio, real=False)

    assert prova.cobranca_aberta()["provedor"] == "simulado"


@pytest.mark.parametrize(
    ("real", "provedor", "esperado"),
    [(True, "simulado", "mercadopago"), (False, "mercadopago", "simulado")],
)
def test_cobranca_no_provedor_errado_reprova_dizendo_qual_era_o_esperado(
    real: bool, provedor: str, esperado: str, relogio: Relogio
) -> None:
    mundo = Mundo()
    mundo.ordem["pagamento"] = {"pagamento_id": "p-1"}
    mundo.billing = _pagamento_billing(provedor=provedor)
    prova, _, _ = _prova(mundo, relogio, real=real)

    with pytest.raises(
        AssertionError, match=f"provedor '{provedor}'.*esperado era '{esperado}'"
    ):
        prova.cobranca_aberta()


def test_cobranca_que_nao_aparece_estoura_o_prazo_do_modo(relogio: Relogio) -> None:
    mundo = Mundo()
    prova, _, _ = _prova(mundo, relogio, real=False)

    with pytest.raises(TempoEsgotadoError, match=r"nao ocorreu em 30 s"):
        prova.cobranca_aberta()


# --- pagar ---------------------------------------------------------------------------


def test_pagar_no_modo_real_imprime_o_link_e_nao_aprova_nada(relogio: Relogio) -> None:
    mundo = Mundo()
    prova, avisos, _ = _prova(mundo, relogio, real=True, numeros=itertools.count(1))

    prova.pagar(_pagamento_billing())
    prova.pagar(_pagamento_billing())

    assert "PAGAMENTO 1 de 2" in avisos[0]
    assert "PAGAMENTO 2 de 2" in avisos[1]
    assert LINK_MP in avisos[0]
    assert "BRL 210.00" in avisos[0]
    assert mundo.simulados == []
    assert (
        prova.registro.transicoes[-1][1]
        == "script: link impresso; esperando o comprador de teste"
    )


def test_pagar_sem_contador_comeca_no_um(relogio: Relogio) -> None:
    prova, avisos, _ = _prova(Mundo(), relogio, real=True)

    prova.pagar(_pagamento_billing())

    assert "PAGAMENTO 1 de 2" in avisos[0]


def test_pagar_no_ensaio_o_simulador_aprova_com_o_token_do_link_e_o_token_sai_mascarado(
    relogio: Relogio,
) -> None:
    mundo = Mundo()
    prova, avisos, _ = _prova(mundo, relogio, real=False)

    prova.pagar(_pagamento_billing(checkout_url=LINK_SIMULADO))

    assert mundo.simulados == [("p-1", "tok.en-do-simulador-1", "aprovar")]
    assert segredos.mascarar("tok.en-do-simulador-1") == "***"
    assert "simulador do Billing aprova" in avisos[0]
    assert LINK_SIMULADO not in " ".join(avisos)
    assert prova.registro.transicoes[-1][1] == "script: simulador aprovou o pagamento"


# --- esperar a confirmacao -----------------------------------------------------------


def test_esperar_confirmacao_no_modo_real_guarda_o_id_do_mercado_pago(
    relogio: Relogio,
) -> None:
    mundo = Mundo()
    mundo.billing_depois = [
        _pagamento_billing(),
        _pagamento_billing(status="CONFIRMADO", referencia_pagamento=999),
    ]
    prova, avisos, _ = _prova(mundo, relogio, real=True)

    pagamento = prova.esperar_confirmacao()

    assert pagamento["status"] == "CONFIRMADO"
    assert prova.registro.pagamento_mp_id == "999"
    assert relogio.dormidas == [5.0]
    assert avisos[0].startswith("aguardando o pagamento: restam 15 min 00 s")
    assert (
        prova.registro.transicoes[-1][1]
        == "script: Billing mostra o pagamento CONFIRMADO"
    )


def test_esperar_confirmacao_no_ensaio_e_curta_e_nao_registra_id_no_mercado_pago(
    relogio: Relogio,
) -> None:
    mundo = Mundo()
    mundo.billing = _pagamento_billing(
        status="CONFIRMADO", referencia_pagamento="sim-pay-1"
    )
    prova, _, _ = _prova(mundo, relogio, real=False)

    pagamento = prova.esperar_confirmacao()

    assert pagamento["referencia_pagamento"] == "sim-pay-1"
    assert prova.registro.pagamento_mp_id == ""


def test_esperar_confirmacao_no_ensaio_tem_prazo_de_um_minuto(relogio: Relogio) -> None:
    prova, _, _ = _prova(Mundo(), relogio, real=False)

    with pytest.raises(TempoEsgotadoError, match=r"nao ocorreu em 60 s"):
        prova.esperar_confirmacao()


# --- o que o Mercado Pago diz --------------------------------------------------------


def test_conferir_aprovado_no_ensaio_nao_fala_com_o_mercado_pago(
    relogio: Relogio,
) -> None:
    mundo = Mundo()
    prova, avisos, _ = _prova(mundo, relogio, real=False)

    prova.conferir_aprovado(_pagamento_billing())

    assert avisos == [SEM_CONSULTA]
    assert mundo.chamadas_ao_mp == []


def test_conferir_aprovado_no_real_guarda_so_os_campos_permitidos(
    relogio: Relogio,
) -> None:
    mundo = Mundo()
    prova, _, _ = _prova(mundo, relogio, real=True)

    prova.conferir_aprovado(_pagamento_billing(referencia_pagamento=999))

    assert mundo.chamadas_ao_mp[0].url.path == "/v1/payments/999"
    assert prova.registro.pagamento_mp_id == "999"
    assert prova.registro.mercadopago == {
        "id": "999",
        "status": "approved",
        "transaction_amount": "210.0",
        "currency_id": "BRL",
        "date_approved": "2026-10-20T08:00:00.000-04:00",
        "external_reference": "p-1",
        "live_mode": False,
    }
    assert "comprador@" not in json.dumps(prova.registro.mercadopago)
    assert (
        prova.registro.transicoes[-1][1]
        == "script: Mercado Pago: approved, live_mode=False"
    )


def test_conferir_aprovado_que_diverge_guarda_o_que_o_mp_disse_antes_de_reprovar(
    relogio: Relogio,
) -> None:
    mundo = Mundo()
    mundo.mp_pagamento = lambda _: _pagamento_mp(
        status="rejected", status_detail="cc_rejected_other_reason"
    )
    prova, _, _ = _prova(mundo, relogio, real=True)

    with pytest.raises(DivergenciaComOMercadoPagoError, match="rejected"):
        prova.conferir_aprovado(_pagamento_billing(referencia_pagamento=999))

    assert prova.registro.mercadopago["status"] == "rejected"


def test_conferir_estornado_no_ensaio_nao_fala_com_o_mercado_pago(
    relogio: Relogio,
) -> None:
    mundo = Mundo()
    prova, avisos, _ = _prova(mundo, relogio, real=False)

    prova.conferir_estornado(_pagamento_billing())

    assert avisos == [SEM_CONSULTA]
    assert mundo.chamadas_ao_mp == []


def test_conferir_estornado_espera_o_estorno_aparecer(relogio: Relogio) -> None:
    mundo = Mundo()
    mundo.mp_pagamento = lambda n: _pagamento_mp(
        status="approved" if n < 3 else "refunded"
    )
    prova, _, _ = _prova(mundo, relogio, real=True)

    prova.conferir_estornado(_pagamento_billing(referencia_pagamento=999))

    assert relogio.dormidas == [3.0, 3.0]
    assert prova.registro.mercadopago["status"] == "refunded"
    assert (
        prova.registro.transicoes[-1][1]
        == "script: Mercado Pago mostra o pagamento estornado"
    )


def test_conferir_estornado_que_nunca_aparece_diz_o_que_o_mp_mostra(
    relogio: Relogio,
) -> None:
    mundo = Mundo()
    prova, _, _ = _prova(mundo, relogio, real=True)

    with pytest.raises(
        DivergenciaComOMercadoPagoError, match=r"não aparece estornado.*approved"
    ):
        prova.conferir_estornado(_pagamento_billing(referencia_pagamento=999))

    assert sum(relogio.dormidas) == PRAZO_DO_ESTORNO


def test_conferir_estornado_que_aparece_so_na_ultima_leitura_ainda_reprova_pelo_prazo(
    relogio: Relogio,
) -> None:
    mundo = Mundo()
    # 21 leituras na espera (0 s a 60 s, de 3 em 3); a 22a, a de conferencia, ja
    # vem estornada.
    mundo.mp_pagamento = lambda n: _pagamento_mp(
        status="refunded" if n > 21 else "approved"
    )
    prova, _, _ = _prova(mundo, relogio, real=True)

    with pytest.raises(TempoEsgotadoError, match="estorno visível no Mercado Pago"):
        prova.conferir_estornado(_pagamento_billing(referencia_pagamento=999))


def test_conferir_preferencia_expirada_no_ensaio_nao_fala_com_o_mercado_pago(
    relogio: Relogio,
) -> None:
    mundo = Mundo()
    prova, avisos, _ = _prova(mundo, relogio, real=False)

    prova.conferir_preferencia_expirada()

    assert avisos == [SEM_CONSULTA]
    assert mundo.chamadas_ao_mp == []


def test_conferir_preferencia_expirada_prova_pela_consulta(relogio: Relogio) -> None:
    mundo = Mundo()
    mundo.mp_preferencia = {
        "id": "pref-1",
        "expires": True,
        "expiration_date_to": (AGORA - timedelta(minutes=1)).isoformat(),
    }
    prova, avisos, _ = _prova(mundo, relogio, real=True)
    prova.cenario.pagamento_id = "p-1"

    prova.conferir_preferencia_expirada()

    assert mundo.chamadas_ao_mp[0].url.path == "/checkout/preferences/pref-1"
    assert prova.registro.preferencia["expires"] is True
    assert prova.registro.observacoes == []
    assert avisos == []
    assert (
        prova.registro.transicoes[-1][1]
        == "script: Mercado Pago mostra a preferência expirada"
    )


def test_preferencia_que_a_consulta_nao_prova_vira_observacao_e_aviso_sem_reprovar(
    relogio: Relogio,
) -> None:
    mundo = Mundo()
    prova, avisos, _ = _prova(mundo, relogio, real=True)
    prova.cenario.pagamento_id = "p-1"

    prova.conferir_preferencia_expirada()

    assert "NÃO foi provada" in prova.registro.observacoes[0]
    assert avisos[0].startswith("[mp-sandbox] atenção:")


def test_preferencia_ainda_valida_reprova_mas_guarda_o_que_viu(
    relogio: Relogio,
) -> None:
    mundo = Mundo()
    mundo.mp_preferencia = {
        "id": "pref-1",
        "expires": True,
        "expiration_date_to": (AGORA + timedelta(minutes=50)).isoformat(),
    }
    prova, _, _ = _prova(mundo, relogio, real=True)
    prova.cenario.pagamento_id = "p-1"

    with pytest.raises(DivergenciaComOMercadoPagoError):
        prova.conferir_preferencia_expirada()

    assert prova.registro.preferencia["id"] == "pref-1"


# --- o diagnostico -------------------------------------------------------------------


def _executor_do_cluster(**logs: str) -> ExecutorFalso:
    respostas = {
        "rabbitmqctl": (
            "billing.comandos.dlq\t1\nexecucao.comandos.dlq\t0\nos.eventos.dlq\t0\n"
        ),
        **{
            f"app=billing-service-{processo}": texto for processo, texto in logs.items()
        },
    }
    return ExecutorFalso(respostas)


def test_falha_no_passo_imprime_o_diagnostico_e_marca_a_falha(relogio: Relogio) -> None:
    mundo = Mundo()
    mundo.billing = _pagamento_billing()
    mundo.mp_busca = [
        _pagamento_mp(status="rejected", status_detail="cc_rejected_other_reason")
    ]
    consumidor = json.dumps(
        {
            "event": (
                "HTTP Request: POST https://api.mercadopago.com/checkout/preferences "
                '"HTTP/1.1 400 Bad Request"'
            ),
            "level": "info",
            "timestamp": "2026-10-20T12:00:01.000000Z",
        }
    )
    executor = _executor_do_cluster(consumidor=consumidor)
    prova, avisos, _ = _prova(mundo, relogio, real=True, executor=executor)
    prova.cenario.pagamento_id = "p-1"

    prova.falha_no_passo(
        "Então o Billing confirma o pagamento",
        AssertionError(f"falhou com {CHAVE_DO_MP}"),
    )

    assert prova.falhou == "Então o Billing confirma o pagamento"
    texto = avisos[0]
    assert "==== Diagnóstico: Cenário de teste" in texto
    assert "Falhou: AssertionError" in texto
    assert CHAVE_DO_MP not in texto
    assert "OS o-1: status=x etapa=y" in texto
    assert "Pagamento no Billing: status=SOLICITADO" in texto
    assert (
        "Mercado Pago: pagamento 999 status=rejected detalhe=cc_rejected_other_reason"
        in texto
    )
    assert "Filas mortas: {'billing.comandos.dlq': 1" in texto
    assert "Log do consumidor" in texto
    assert "Mercado Pago: POST /checkout/preferences respondeu 400" in texto
    assert "notification_url local" in texto
    assert "comprador@" not in texto
    pedidos = [" ".join(c) for c in executor.comandos if "logs" in c]
    assert [
        ("app=billing-service-" + p) in " ".join(pedidos)
        for p in ("api", "consumidor", "prazos")
    ] == [True] * 3
    assert all("--tail=40" in pedido for pedido in pedidos)


def test_diagnostico_no_ensaio_nao_consulta_o_mercado_pago(relogio: Relogio) -> None:
    mundo = Mundo()
    prova, _, _ = _prova(mundo, relogio, real=False)
    prova.cenario.pagamento_id = "p-1"

    texto = prova.diagnostico("Então algo", AssertionError("x"))

    assert mundo.chamadas_ao_mp == []
    assert "Mercado Pago: (sem leitura)" not in texto


def test_diagnostico_sem_pagamento_ainda_nao_le_o_billing(relogio: Relogio) -> None:
    prova, _, _ = _prova(Mundo(), relogio, real=True)

    texto = prova.diagnostico("Dado algo", AssertionError("x"))

    assert "Pagamento no Billing: (sem leitura ou ainda não criado)" in texto
    assert "Mercado Pago: (sem leitura)" in texto


def test_diagnostico_nunca_levanta_mesmo_com_tudo_fora_do_ar(relogio: Relogio) -> None:
    def cai(*_: Any, **__: Any) -> Any:
        msg = "api fora"
        raise httpx.ConnectError(msg)

    mundo = Mundo()
    mundo.mp_status = 500

    class ExecutorQueFalha(ExecutorFalso):
        def __call__(self, argumentos: Any, prazo: float) -> str:
            msg = "kubectl caiu"
            raise ErroDeComandoError(msg)

    prova, _, _ = _prova(
        mundo, relogio, real=True, executor=ExecutorQueFalha(), descrever=cai
    )
    prova.cenario.pagamento_id = "p-1"
    prova.api.billing.pagamento = cai  # type: ignore[method-assign]

    texto = prova.diagnostico("Então algo", AssertionError("x"))

    assert "OS e saga: (sem leitura)" in texto
    assert "Pagamento no Billing: (sem leitura ou ainda não criado)" in texto
    assert "Mercado Pago: (sem leitura)" in texto
    assert "Filas mortas" not in texto
    assert "(nada que interesse)" in texto


# --- concluir ------------------------------------------------------------------------


def test_concluir_guarda_duracao_resultado_e_o_que_os_servicos_registraram(
    relogio: Relogio,
) -> None:
    mundo = Mundo()
    mundo.billing = _pagamento_billing(
        status="CONFIRMADO",
        confirmado_em="2026-10-20T12:05:00Z",
        checkout_url=LINK_MP,
        notificacoes=[
            {
                "recebida_em": "x",
                "referencia_pagamento": "999",
                "status_provedor": "approved",
                "payer": "x",
            }
        ],
    )
    mundo.saga = {
        "etapa": "concluida",
        "motivo": None,
        "falha": "texto livre",
        "passos": [
            {
                "seq": 1,
                "em": "2026-10-20T12:00:01Z",
                "gatilho": "abertura",
                "ator": "uuid",
            }
        ],
    }
    mundo.historico = {
        "mudancas": [
            {
                "de": None,
                "para": "recebida",
                "origem": "atendimento",
                "ocorrido_em": "2026-10-20T12:00:00Z",
            }
        ]
    }
    prova, _, _ = _prova(mundo, relogio, real=True)
    prova.cenario.pagamento_id = "p-1"
    relogio.dormir(61.4)

    prova.concluir()

    registro = prova.registro
    assert registro.duracao == pytest.approx(61.4)
    assert registro.resultado == "passou"
    assert registro.ordem_id == "o-1"
    assert "checkout_url" not in registro.billing
    assert registro.billing["status"] == "CONFIRMADO"
    assert registro.saga["passos"] == [
        {"seq": 1, "em": "2026-10-20T12:00:01Z", "gatilho": "abertura"}
    ]
    textos = [texto for _, texto in registro.transicoes]
    assert "OS: (abertura) -> recebida (atendimento)" in textos
    assert "Billing: pagamento CONFIRMADO" in textos
    assert registro.observacoes == []


def test_concluir_de_cenario_que_falhou_diz_em_que_passo(relogio: Relogio) -> None:
    prova, _, _ = _prova(Mundo(), relogio, real=False)
    prova.falhou = "Então o Billing confirma o pagamento"

    prova.concluir()

    assert prova.registro.resultado == "falhou"
    assert prova.registro.observacoes == [
        "falhou no passo: Então o Billing confirma o pagamento"
    ]


def test_concluir_sem_ordem_nao_consulta_nada(relogio: Relogio) -> None:
    mundo = Mundo()
    prova, _, _ = _prova(mundo, relogio, real=False)
    prova.cenario.ordem_id = ""
    prova.api.os = None  # type: ignore[assignment]  # qualquer consulta quebraria

    prova.concluir()

    assert prova.registro.resultado == "passou"
    assert prova.registro.ordem_id == ""
    assert prova.registro.billing == {}


def test_concluir_sem_pagamento_ainda_guarda_a_saga(relogio: Relogio) -> None:
    mundo = Mundo()
    prova, _, _ = _prova(mundo, relogio, real=False)
    prova.api.billing = None  # type: ignore[assignment]  # sem pagamento_id, nao deve ser chamado

    prova.concluir()

    assert prova.registro.billing == {"notificacoes": []}
    assert prova.registro.saga["etapa"] == "compensada"


def test_concluir_com_os_servicos_fora_do_ar_nao_levanta(relogio: Relogio) -> None:
    def cai(*_: Any, **__: Any) -> Any:
        msg = "fora"
        raise httpx.ConnectError(msg)

    mundo = Mundo()
    prova, _, _ = _prova(mundo, relogio, real=False)
    prova.cenario.pagamento_id = "p-1"
    prova.api = cast(
        "Api",
        SimpleNamespace(
            os=SimpleNamespace(saga=cai, historico=cai),
            billing=SimpleNamespace(pagamento=cai),
        ),
    )

    prova.concluir()

    assert prova.registro.saga == {"passos": []}
    assert prova.registro.transicoes == []
