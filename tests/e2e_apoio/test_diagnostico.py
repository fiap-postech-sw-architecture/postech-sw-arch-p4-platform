"""Diagnostico de falha: log filtrado, causa provavel e texto sem segredo."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pytest

from e2e.apoio import segredos
from e2e.apoio.diagnostico import (
    CAMPOS_DO_LOG,
    LINHAS_DE_LOG,
    LinhaDeLog,
    Sinais,
    coletar,
    dicas,
    filtrar_log,
    montar,
)
from e2e.apoio.mercadopago import PagamentoMp

CHAVE_DO_MP = (
    "APP_USR-1234567890123456-101420-0a1b2c3d4e5f60718293a4b5c6d7e8f9-123456789"
)


def _log(evento: str, nivel: str = "info", **campos: Any) -> str:
    """Uma linha do log estruturado do Billing, como o kubectl a devolve."""
    return json.dumps(
        {
            "event": evento,
            "git_sha": "264da4e537f7",
            "level": nivel,
            "logger": "src.x",
            "timestamp": "2026-10-20T12:34:56.789012Z",
            **campos,
        }
    )


def _mp(metodo: str, caminho: str, status: int, motivo: str = "Bad Request") -> str:
    url = (
        f"https://api.mercadopago.com{caminho}?external_reference=abc&sort=date_created"
    )
    return _log(f'HTTP Request: {metodo} {url} "HTTP/1.1 {status} {motivo}"')


def _pagamento_mp(status: str, detalhe: str | None = None) -> PagamentoMp:
    return PagamentoMp(
        id="1",
        status=status,
        status_detail=detalhe,
        valor=Decimal("210.00"),
        valor_estornado=Decimal(0),
        moeda="BRL",
        date_approved=None,
        external_reference="p-1",
        live_mode=False,
    )


def _sinais(**campos: Any) -> Sinais:
    base: dict[str, Any] = {
        "cenario": "Pagamento aprovado",
        "passo": "Então o Billing confirma o pagamento",
        "erro": "TempoEsgotadoError: pagamento CONFIRMADO no Billing: nao ocorreu",
        "esperado": "Então o Billing confirma o pagamento",
        "real": True,
        "contexto": "kind-x",
    }
    return Sinais(**{**base, **campos})


def _linhas(*brutas: str) -> list[LinhaDeLog]:
    return filtrar_log("\n".join(brutas))


# --- o filtro do log ------------------------------------------------------------------


def test_rotina_do_consumidor_e_requisicao_ok_nao_entram() -> None:
    linhas = _linhas(
        _log(
            "command_consumed",
            tipo="GerarOrcamento",
            resultado="processada",
            tentativa=0,
        ),
        _log("http_request", method="GET", path="/billing/api/v1/saude", status=200),
        _log("deadlines_started", intervalo=30.0),
        _log("x", resultado="sucesso"),
    )

    assert linhas == []


def test_entra_o_que_nao_e_rotina_por_nivel_erro_status_ou_resultado() -> None:
    linhas = _linhas(
        _log("payment_reconciliation_refused", "error"),
        _log(
            "command_retry_scheduled",
            "warning",
            tipo="SolicitarPagamento",
            erro="GatewayPagamentoIndisponivelError",
        ),
        _log("algo", erro="X"),
        _log(
            "http_request",
            method="POST",
            path="/billing/api/v1/webhooks/mercadopago",
            status=401,
        ),
        _log(
            "command_consumed",
            tipo="EstornarPagamento",
            resultado="duplicada",
            tentativa=1,
        ),
    )

    assert [linha.evento for linha in linhas] == [
        "payment_reconciliation_refused",
        "command_retry_scheduled",
        "algo",
        "http_request",
        "command_consumed",
    ]


def test_so_os_campos_da_lista_saem_e_os_outros_ficam_na_linha() -> None:
    linha = _linhas(
        _log(
            "command_dead_lettered",
            "error",
            tipo="SolicitarPagamento",
            erro="GatewayPagamentoRecusouError",
            codigo="GATEWAY_PAGAMENTO_RECUSOU",
            correlation_id="c-1",
            trace_id="t-1",
            ator="uuid-do-atendente",
            contato="cliente@clientes.pytstop.dev",
        )
    )[0]

    assert set(linha.campos) <= set(CAMPOS_DO_LOG)
    assert linha.campos == {
        "tipo": "SolicitarPagamento",
        "erro": "GatewayPagamentoRecusouError",
        "codigo": "GATEWAY_PAGAMENTO_RECUSOU",
    }
    texto = linha.texto()
    for fora in ("correlation_id", "trace_id", "ator", "cliente@"):
        assert fora not in texto


def test_texto_da_linha_tem_hora_nivel_evento_e_campos() -> None:
    linha = _linhas(_log("command_retry_scheduled", "warning", tipo="X", tentativa=2))[
        0
    ]

    assert (
        linha.texto() == "12:34:56 warning command_retry_scheduled tipo=X tentativa=2"
    )


def test_chamada_ao_mercado_pago_vira_metodo_caminho_e_status_sem_a_query() -> None:
    linhas = _linhas(
        _mp("POST", "/checkout/preferences", 400),
        _mp("GET", "/v1/payments/search", 401, "Unauthorized"),
    )

    assert [linha.chamada_ao_mp for linha in linhas] == [
        ("POST", "/checkout/preferences", 400),
        ("GET", "/v1/payments/search", 401),
    ]
    assert linhas[0].texto() == (
        "12:34:56 info    Mercado Pago: POST /checkout/preferences respondeu 400"
    )
    assert "external_reference" not in linhas[1].texto()


def test_chamada_a_outro_host_e_linha_que_nao_e_json_nao_entram() -> None:
    linhas = _linhas(
        _log('HTTP Request: GET https://example.com/x "HTTP/1.1 200 OK"'),
        ">>> pytstop billing prazos | commit 264da4e",
        "Traceback (most recent call last):",
        "[1, 2, 3]",
        "",
    )

    assert linhas == []


def test_excecao_entra_so_com_a_ultima_linha() -> None:
    linha = _linhas(
        _log(
            "deadlines_cycle_failed",
            "error",
            exception=(
                "Traceback (most recent call last):\n  File x\n"
                "httpx.ConnectError: [Errno 61] Connection refused\n"
            ),
        )
    )[0]

    assert (
        linha.campos["excecao"] == "httpx.ConnectError: [Errno 61] Connection refused"
    )


def test_valor_comprido_e_cortado_e_sem_quebra_de_linha() -> None:
    linha = _linhas(_log("x", "warning", erro="a\n" * 200))[0]

    assert len(linha.campos["erro"]) == 160
    assert "\n" not in linha.campos["erro"]


def test_so_as_ultimas_linhas_contam() -> None:
    antiga = _log("antiga", "error")
    recentes = [_log("rotina", resultado="processada")] * LINHAS_DE_LOG

    assert _linhas(antiga, *recentes) == []
    assert [x.evento for x in _linhas(antiga, *recentes[1:])] == ["antiga"]
    todas = filtrar_log("\n".join([antiga, *recentes]), ultimas=LINHAS_DE_LOG + 1)
    assert [x.evento for x in todas] == ["antiga"]


def test_linha_sem_hora_nem_nivel_ainda_e_formatada() -> None:
    linha = filtrar_log(json.dumps({"event": "x", "erro": "E"}))[0]

    assert linha.quando == ""
    assert linha.texto().endswith("x erro=E")


def test_o_texto_da_linha_sai_mascarado() -> None:
    segredos.registrar("segredo-no-log-123")
    linha = _linhas(
        _log("x", "error", erro=f"falhou com {CHAVE_DO_MP} e segredo-no-log-123")
    )[0]

    assert CHAVE_DO_MP not in linha.texto()
    assert "segredo-no-log-123" not in linha.texto()


# --- as dicas ------------------------------------------------------------------------


def _com_logs(**processos: list[str]) -> Sinais:
    return _sinais(logs={nome: _linhas(*linhas) for nome, linhas in processos.items()})


def test_preferencia_recusada_pelo_mercado_pago_aponta_a_notification_url_local() -> (
    None
):
    sinais = _com_logs(consumidor=[_mp("POST", "/checkout/preferences", 400)])

    achadas = dicas(sinais)

    assert len(achadas) == 1
    assert "POST /checkout/preferences" in achadas[0]
    assert "notification_url local" in achadas[0]
    assert (
        "E2E_MP_NOTIFICATION_URL=https://example.com/api/v1/webhooks/mercadopago"
        in achadas[0]
    )
    assert (
        "set env deployment --all MP_NOTIFICATION_URL=https://example.com/api/v1/webhooks/mercadopago"
        in achadas[0]
    )


def test_comando_morto_por_recusa_do_provedor_tambem_aponta_a_notification_url() -> (
    None
):
    sinais = _com_logs(
        consumidor=[
            _log(
                "command_dead_lettered",
                "error",
                tipo="SolicitarPagamento",
                erro="GatewayPagamentoRecusouError",
                codigo="GATEWAY_PAGAMENTO_RECUSOU",
            )
        ]
    )

    assert "notification_url local" in dicas(sinais)[0]


def test_comando_morto_por_outro_motivo_nao_acusa_a_notification_url() -> None:
    sinais = _com_logs(
        consumidor=[
            _log(
                "command_dead_lettered",
                "error",
                erro="ContractError",
                codigo="CONTRATO",
            )
        ]
    )

    assert "notification_url" not in " ".join(dicas(sinais))


def test_get_com_4xx_nao_e_criacao_recusada() -> None:
    sinais = _com_logs(
        consumidor=[_mp("GET", "/checkout/preferences", 404, "Not Found")]
    )

    assert "notification_url" not in " ".join(dicas(sinais))


@pytest.mark.parametrize("status", [401, 403])
def test_token_recusado_na_criacao_vence_a_hipotese_da_notification_url(
    status: int,
) -> None:
    sinais = _com_logs(
        consumidor=[_mp("POST", "/checkout/preferences", status, "Unauthorized")]
    )

    achadas = dicas(sinais)

    assert len(achadas) == 1
    assert "não aceitou o token" in achadas[0]
    assert "read -rs MP_ACCESS_TOKEN" in achadas[0]
    assert "notification_url" not in achadas[0]


def test_conciliacao_recusada_no_prazos_aponta_o_token() -> None:
    sinais = _com_logs(prazos=[_log("payment_reconciliation_refused", "error")])

    assert "não aceitou o token" in dicas(sinais)[0]


@pytest.mark.parametrize(
    "linhas",
    [
        pytest.param(
            {"prazos": [_log("payment_reconciliation_paused", "warning")]},
            id="conciliacao-pausada",
        ),
        pytest.param(
            {
                "consumidor": [
                    _log(
                        "command_retry_scheduled",
                        "warning",
                        erro="GatewayPagamentoIndisponivelError",
                    )
                ]
            },
            id="retry",
        ),
        pytest.param(
            {
                "consumidor": [
                    _mp("POST", "/checkout/preferences", 503, "Service Unavailable")
                ]
            },
            id="5xx",
        ),
        pytest.param(
            {"prazos": [_mp("GET", "/v1/payments/search", 429, "Too Many Requests")]},
            id="429",
        ),
    ],
)
def test_provedor_indisponivel_diz_para_esperar(linhas: dict[str, list[str]]) -> None:
    achadas = dicas(_com_logs(**linhas))

    assert any("indisponível" in dica and "5xx ou 429" in dica for dica in achadas)


def test_pagamento_recusado_no_mercado_pago_traz_o_detalhe_e_o_que_conferir() -> None:
    sinais = _sinais(
        mercadopago=[_pagamento_mp("rejected", "cc_rejected_bad_filled_other")],
        pagamento={"status": "SOLICITADO"},
    )

    achadas = dicas(sinais)

    assert "cc_rejected_bad_filled_other" in achadas[0]
    assert "APRO aprova" in achadas[0]
    assert "janela anônima" in achadas[0]
    assert "conta real logada recusa" in achadas[0]


def test_pagamento_recusado_sem_detalhe() -> None:
    achadas = dicas(
        _sinais(
            mercadopago=[_pagamento_mp("rejected")], pagamento={"status": "SOLICITADO"}
        )
    )

    assert "(sem detalhe)" in achadas[0]


def test_aprovado_no_mercado_pago_e_solicitado_no_billing_e_conciliacao_parada() -> (
    None
):
    sinais = _sinais(
        mercadopago=[_pagamento_mp("approved")], pagamento={"status": "SOLICITADO"}
    )

    achadas = dicas(sinais)

    assert len(achadas) == 1
    assert "conciliação do `prazos` está parada" in achadas[0]
    assert "billing-service-prazos" in achadas[0]


def test_aprovado_no_mercado_pago_e_confirmado_no_billing_nao_acusa_a_conciliacao() -> (
    None
):
    sinais = _sinais(
        mercadopago=[_pagamento_mp("approved")], pagamento={"status": "CONFIRMADO"}
    )

    assert "conciliação" not in " ".join(dicas(sinais))


def test_sem_pagamento_no_mp_com_cobranca_solicitada_pergunta_se_pagou() -> None:
    achadas = dicas(_sinais(mercadopago=[], pagamento={"status": "SOLICITADO"}))

    assert "não recebeu nenhum pagamento deste link" in achadas[0]
    assert "APRO" in achadas[0]


def test_sem_pagamento_com_cobranca_encerrada_nao_pergunta_se_pagou() -> None:
    sinais = _sinais(mercadopago=[], pagamento={"status": "CANCELADO"})

    assert "não recebeu nenhum pagamento" not in " ".join(dicas(sinais))


def test_sem_leitura_do_mercado_pago_nao_inventa_causa() -> None:
    achadas = dicas(_sinais(mercadopago=None, pagamento=None))

    assert len(achadas) == 1
    assert "Sem causa óbvia nos logs" in achadas[0]
    assert "billing-service-consumidor --tail=50" in achadas[0]


def test_mensagem_na_dlq_do_billing_e_dica() -> None:
    achadas = dicas(
        _sinais(filas_mortas={"billing.comandos.dlq": 2, "os.eventos.dlq": 0})
    )

    assert any("billing.comandos.dlq tem 2 mensagem(ns)" in dica for dica in achadas)


def test_dlq_com_mensagem_nova_diz_quantas_a_mais_que_no_inicio() -> None:
    achadas = dicas(
        _sinais(
            filas_mortas={"billing.comandos.dlq": 3},
            filas_mortas_antes={"billing.comandos.dlq": 1},
        )
    )

    assert any(
        "billing.comandos.dlq tem 3 mensagem(ns) (2 a mais que no início do cenário)"
        in dica
        for dica in achadas
    )


def test_dlq_que_ja_tinha_a_mensagem_antes_do_cenario_nao_e_dica() -> None:
    achadas = dicas(
        _sinais(
            filas_mortas={"billing.comandos.dlq": 2},
            filas_mortas_antes={"billing.comandos.dlq": 2},
        )
    )

    assert len(achadas) == 1
    assert "Sem causa óbvia nos logs" in achadas[0]


def test_dlq_vazia_ou_de_outro_servico_nao_e_dica() -> None:
    achadas = dicas(
        _sinais(filas_mortas={"billing.comandos.dlq": 0, "os.eventos.dlq": 4})
    )

    assert achadas == [
        (
            "Sem causa óbvia nos logs. Veja o do consumidor: "
            "`kubectl --context kind-x -n pytstop-billing "
            "logs deploy/billing-service-consumidor --tail=50`."
        )
    ]


def test_varias_causas_aparecem_juntas() -> None:
    sinais = _sinais(
        logs={"consumidor": _linhas(_mp("POST", "/checkout/preferences", 400))},
        filas_mortas={"billing.comandos.dlq": 1},
    )

    assert len(dicas(sinais)) == 2


# --- o texto -------------------------------------------------------------------------


def test_diagnostico_completo_no_modo_real() -> None:
    sinais = _sinais(
        estado_da_os="OS 6bc7dbe7: status=aguardando_pagamento etapa=x",
        pagamento={
            "status": "SOLICITADO",
            "recusas": 1,
            "expira_em": "2026-10-20T13:00:00Z",
            "referencia_pagamento": None,
            "checkout_url": "https://www.mercadopago.com.br/checkout?pref_id=123",
        },
        mercadopago=[_pagamento_mp("rejected", "cc_rejected_other_reason")],
        filas_mortas={"billing.comandos.dlq": 0},
        logs={
            "api": [],
            "consumidor": _linhas(_mp("POST", "/checkout/preferences", 400)),
        },
    )

    texto = montar(sinais)

    assert texto.splitlines()[0] == (
        '==== Diagnóstico: Pagamento aprovado, passo "Então o Billing '
        'confirma o pagamento" ===='
    )
    assert "Falhou: TempoEsgotadoError" in texto
    assert "Esperado: Então o Billing confirma o pagamento" in texto
    assert "OS e saga: OS 6bc7dbe7: status=aguardando_pagamento" in texto
    assert (
        "Pagamento no Billing: status=SOLICITADO recusas=1 "
        "expira_em=2026-10-20T13:00:00Z referencia_pagamento=None"
    ) in texto
    assert (
        "Mercado Pago: pagamento 1 status=rejected "
        "detalhe=cc_rejected_other_reason valor=210.00 BRL"
    ) in texto
    assert "Filas mortas: {'billing.comandos.dlq': 0}" in texto
    assert "Log do api (últimas 40 linhas, filtradas):\n  (nada que interesse)" in texto
    assert "Log do consumidor (últimas 40 linhas, filtradas):" in texto
    assert "Mercado Pago: POST /checkout/preferences respondeu 400" in texto
    assert "Dica provável:" in texto
    assert "pref_id" not in texto, "o link do checkout nunca entra no diagnostico"


def test_diagnostico_mostra_as_filas_mortas_do_inicio_do_cenario() -> None:
    texto = montar(
        _sinais(
            filas_mortas={"billing.comandos.dlq": 2},
            filas_mortas_antes={"billing.comandos.dlq": 1},
        )
    )

    assert "Filas mortas: {'billing.comandos.dlq': 2}" in texto
    assert "Filas mortas no início do cenário: {'billing.comandos.dlq': 1}" in texto


def test_diagnostico_sem_nenhuma_leitura_diz_que_nao_leu() -> None:
    texto = montar(_sinais())

    assert "OS e saga: (sem leitura)" in texto
    assert "Pagamento no Billing: (sem leitura ou ainda não criado)" in texto
    assert "Mercado Pago: (sem leitura)" in texto
    assert "Filas mortas" not in texto


def test_diagnostico_com_mercado_pago_sem_pagamento() -> None:
    texto = montar(_sinais(mercadopago=[]))

    assert "Mercado Pago: nenhum pagamento com esta referência" in texto


def test_diagnostico_do_ensaio_nao_fala_do_mercado_pago() -> None:
    texto = montar(_sinais(real=False, mercadopago=None))

    assert "Mercado Pago: (sem leitura)" not in texto
    assert "Mercado Pago: nenhum pagamento" not in texto


def test_diagnostico_sai_mascarado() -> None:
    segredos.registrar("senha-que-vazou-123")

    texto = montar(_sinais(erro=f"AssertionError: {CHAVE_DO_MP} e senha-que-vazou-123"))

    assert CHAVE_DO_MP not in texto
    assert "senha-que-vazou-123" not in texto
    assert "***" in texto


# --- coletar -------------------------------------------------------------------------


def test_coletar_devolve_o_valor_e_engole_a_falha() -> None:
    def falha() -> int:
        msg = "kubectl caiu"
        raise RuntimeError(msg)

    assert coletar(lambda: 42) == 42
    assert coletar(falha) is None


# --- todo kubectl sugerido leva o --context do script --------------------------


def test_todo_kubectl_sugerido_leva_o_contexto_do_cluster_do_script() -> None:
    sinais = _sinais(
        contexto="kind-pytstop-mp",
        mercadopago=[_pagamento_mp("approved")],
        pagamento={"status": "SOLICITADO"},
        logs={"consumidor": _linhas(_mp("POST", "/checkout/preferences", 400))},
    )

    textos = " ".join(dicas(sinais))

    comandos = [parte for parte in textos.split("`") if parte.startswith("kubectl")]
    assert len(comandos) == 2, comandos
    for comando in comandos:
        assert comando.startswith(
            "kubectl --context kind-pytstop-mp -n pytstop-billing"
        )
