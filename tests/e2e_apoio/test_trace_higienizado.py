"""O trace da saga na evidencia: so o que a lista de permissao deixa, nada mais."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from e2e.apoio import segredos
from e2e.apoio.evidencia import varrer
from e2e.apoio.jaeger import TraceIdInvalidoError
from e2e.apoio.mercadopago import URL_DA_API
from e2e.apoio.trace_higienizado import (
    HOST_DO_MERCADO_PAGO,
    OPERACAO_OMITIDA,
    TAGS_PERMITIDAS,
    ChaveDeArquivoInvalidaError,
    TraceDoCenario,
    arquivo_do_trace,
    chamada_ao_mercado_pago,
    escolher_trace,
    higienizar_trace,
    nome_do_arquivo,
    url_reduzida,
)
from e2e_apoio.falsos import CHAVE_APP_USR

RAIZ = Path(__file__).resolve().parents[2]
TRACE_REAL = RAIZ / "docs/entrega/fase4/evidencias/trace-saga-2026-10-19.json"

TRACE_ID = "36c945dd0cb1589e33ecc81badd2bd71"
OUTRO_TRACE_ID = "0123456789abcdef0123456789abcdef"
ORDEM_ID = "9f0c2d1e-3b4a-4c5d-8e6f-7a8b9c0d1e2f"
PAGAMENTO_ID = "5d1c7e2a-8b3f-4a6c-9d0e-1f2a3b4c5d6e"
PREFERENCIA = "1462278261-c5ca3674-5b81-4eef-bfb1-b4bfdccfa6b6"
CPF = "123.456.789-09"
EMAIL = "joao.silva@exemplo.com.br"
CREDENCIAL_DO_LINK = "kJ8x2Qw9ZlmN3pRt5VbYc7HdFgSaUeI1oXyWqLzP0nM"
SENHA = "s3nh4-do-comprador"
INICIO = 1_790_000_000_000_000
MP = "https://api.mercadopago.com"

# Tudo o que o trace de exemplo tem de sensivel; nada disto pode estar na saida.
SENSIVEIS = (
    CHAVE_APP_USR,
    "APP_USR",
    CPF,
    "12345678909",
    EMAIL,
    "joao.silva",
    "exemplo.com.br",
    ORDEM_ID,
    PAGAMENTO_ID,
    PREFERENCIA,
    "1462278261",
    CREDENCIAL_DO_LINK,
    SENHA,
    "access_token",
    "external_reference",
    "pref_id",
    "cpf=",
    "Bearer",
    "SELECT",
    "pod-os",
    "10.244",
    "Mozilla",
    "evil.example",
    "NullPointer",
)


TIPOS_DO_JAEGER: dict[type, str] = {bool: "bool", int: "int64", str: "string"}


def _tag(chave: str, valor: object) -> dict[str, Any]:
    return {"key": chave, "type": TIPOS_DO_JAEGER[type(valor)], "value": valor}


def _span(
    span_id: str,
    nome: str,
    processo: str,
    atributos: dict[str, object],
    **extra: Any,
) -> dict[str, Any]:
    return {
        "traceID": TRACE_ID,
        "spanID": span_id,
        "flags": 1,
        "operationName": nome,
        "references": [],
        "startTime": INICIO + int(span_id, 16),
        "duration": 1500,
        "tags": [_tag(chave, valor) for chave, valor in atributos.items()],
        "logs": [],
        "processID": processo,
        "warnings": None,
        **extra,
    }


def _processo(servico: str) -> dict[str, Any]:
    return {
        "serviceName": servico,
        "tags": [
            _tag("hostname", f"pod-os-7d9f8c-{SENHA}"),
            _tag("ip", "10.244.0.46"),
            _tag("service.version", "248c4071d357"),
        ],
    }


def _trace_cheio_de_dado_sensivel() -> dict[str, Any]:
    """Um trace do Jaeger como o da saga, com dado sensivel em tudo o que ele guarda."""
    url_do_mp = (
        f"{MP}/checkout/preferences?access_token={CHAVE_APP_USR}"
        f"&external_reference={PAGAMENTO_ID}&pref_id={PREFERENCIA}#{CPF}"
    )
    spans = [
        _span(
            "0000000000000001",
            "POST /api/v1/ordens-de-servico",
            "p1",
            {
                "span.kind": "server",
                "http.method": "POST",
                "http.route": "/api/v1/ordens-de-servico/{ordem_id}",
                "http.url": f"https://localhost/os/api/v1/ordens-de-servico/{ORDEM_ID}"
                f"?cpf={CPF}&email={EMAIL}",
                "http.target": f"/os/api/v1/ordens-de-servico/{ORDEM_ID}?cpf={CPF}",
                "http.status_code": 201,
                "http.user_agent": "Mozilla/5.0 (X11; Linux)",
                "net.peer.ip": "10.244.0.46",
                "http.host": "10.244.0.46:8000",
                "messaging.message.conversation_id": ORDEM_ID,
                "correlation_id": ORDEM_ID,
                "otel.scope.name": "opentelemetry.instrumentation.fastapi",
            },
            logs=[
                {
                    "timestamp": INICIO,
                    "fields": [
                        _tag("event", "exception"),
                        _tag("exception.message", f"NullPointer {EMAIL} {CPF}"),
                        _tag("authorization", f"Bearer {CHAVE_APP_USR}"),
                    ],
                }
            ],
            warnings=[f"Duplicate tag token={CREDENCIAL_DO_LINK}"],
        ),
        _span(
            "0000000000000002",
            "POST",
            "p2",
            {
                "span.kind": "client",
                "http.method": "POST",
                "http.url": url_do_mp,
                "http.status_code": 201,
                "net.peer.name": "api.mercadopago.com",
                "server.address": "api.mercadopago.com",
                "http.request.header.authorization": f"Bearer {CHAVE_APP_USR}",
                "exception.message": f"falhou para {EMAIL}",
                "error": True,
                "otel.status_code": "ERROR",
            },
            references=[
                {
                    "refType": "CHILD_OF",
                    "traceID": TRACE_ID,
                    "spanID": "0000000000000001",
                },
                {
                    "refType": "FOLLOWS_FROM",
                    "traceID": OUTRO_TRACE_ID,
                    "spanID": "00000000000000aa",
                },
            ],
        ),
        _span(
            "0000000000000003",
            f"GET /v1/payments/search?external_reference={PAGAMENTO_ID}",
            "p2",
            {"span.kind": "client", "url.full": f"{MP}/v1/payments/{PREFERENCIA}"},
        ),
        _span(
            "0000000000000004",
            "SELECT * FROM pagamentos WHERE email = 'joao.silva@exemplo.com.br'",
            "p2",
            {
                "span.kind": "client",
                "db.system": "mongodb",
                "db.statement": f"find {{cpf: '{CPF}', token: '{CREDENCIAL_DO_LINK}'}}",
                "db.user": "billing",
                "db.name": "pytstop_billing",
            },
        ),
        _span(
            "0000000000000005",
            "publish PagamentoSolicitado",
            "p3",
            {
                "span.kind": "producer",
                "messaging.system": "rabbitmq",
                "messaging.operation.type": "send",
                "messaging.destination.name": "pytstop.comandos",
                "messaging.rabbitmq.destination.routing_key": f"comando.{ORDEM_ID}",
                "messaging.message.id": PAGAMENTO_ID,
            },
        ),
        # Tag da lista com valor que nao tem a forma esperada: sai, e nao o valor.
        _span(
            "0000000000000006",
            "/clientes/123.456.789-09 vinte",
            "p3",
            {
                "span.kind": "client; token=abc",
                "http.method": f"GET {EMAIL}",
                "http.status_code": "200",
                "http.route": f"/clientes/{CPF}/{EMAIL}?x={CHAVE_APP_USR}",
                "http.url": f"https://joao:{SENHA}@x.test/x?y=z#{CPF}",
                "url.full": "ftp://evil.example/x",
                "server.address": "api.mercadopago.com.evil.example",
                "messaging.destination.name": f"os.eventos.{ORDEM_ID}",
                "messaging.system": "rabbitmq://u:p@h",
                "db.system": f"postgres://u:{SENHA}@h/db",
                "otel.status_code": f"ERROR {CPF}",
                "error": "true",
            },
        ),
    ]
    return {
        "traceID": TRACE_ID,
        "spans": spans,
        "processes": {
            "p1": _processo("os-service"),
            "p2": _processo("billing-service"),
            "p3": _processo("execution-service"),
        },
        "warnings": None,
    }


def _por_id(trace: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {span["spanID"]: span for span in trace["spans"]}


def _tags_de(span: dict[str, Any]) -> dict[str, Any]:
    return {tag["key"]: tag["value"] for tag in span["tags"]}


def _limpo() -> dict[str, Any]:
    limpo = higienizar_trace(_trace_cheio_de_dado_sensivel())
    assert limpo is not None
    return limpo


# --- nada sensivel sai ----------------------------------------------------------------


def test_nada_do_que_e_sensivel_sai_nem_a_varredura_da_evidencia_acha_algo() -> None:
    segredos.registrar(CHAVE_APP_USR)
    segredos.registrar(SENHA)
    segredos.registrar(CREDENCIAL_DO_LINK)

    texto = json.dumps(_limpo(), ensure_ascii=False)

    for sensivel in SENSIVEIS:
        assert sensivel not in texto, sensivel
    # Nenhum valor permitido pode carregar query, fragmento, e-mail ou credencial.
    for caractere in "?#@=&":
        assert caractere not in texto, caractere
    assert varrer(texto) == []


def test_o_arquivo_do_trace_tambem_nao_leva_nada_sensivel() -> None:
    segredos.registrar(CHAVE_APP_USR)

    nome, texto = arquivo_do_trace("pagamento", _limpo())

    assert nome == f"trace-pagamento-{TRACE_ID}.json"
    for sensivel in SENSIVEIS:
        assert sensivel not in nome + texto, sensivel
    assert varrer(texto) == []


def test_o_trace_higienizado_fica_so_com_as_chaves_da_lista() -> None:
    limpo = _limpo()

    assert set(limpo) == {"traceID", "spans", "processes"}
    assert limpo["traceID"] == TRACE_ID
    for span in limpo["spans"]:
        assert set(span) == {
            "traceID",
            "spanID",
            "operationName",
            "references",
            "startTime",
            "duration",
            "tags",
            "processID",
        }
        assert span["traceID"] == TRACE_ID
        for tag in span["tags"]:
            assert set(tag) == {"key", "type", "value"}
            assert tag["key"] in TAGS_PERMITIDAS
    assert limpo["processes"] == {
        "p1": {"serviceName": "os-service"},
        "p2": {"serviceName": "billing-service"},
        "p3": {"serviceName": "execution-service"},
    }


def test_sem_logs_sem_warnings_e_sem_tag_de_processo_em_lugar_nenhum() -> None:
    def chaves(valor: object) -> set[str]:
        if isinstance(valor, dict):
            return set(valor) | {c for v in valor.values() for c in chaves(v)}
        if isinstance(valor, list):
            return {c for v in valor for c in chaves(v)}
        return set()

    assert {"logs", "warnings", "fields", "flags"}.isdisjoint(chaves(_limpo()))


def test_o_host_do_mercado_pago_da_lista_e_o_do_cliente_da_evidencia() -> None:
    assert url_reduzida(URL_DA_API) == f"https://{HOST_DO_MERCADO_PAGO}"
    assert HOST_DO_MERCADO_PAGO == "api.mercadopago.com"


def test_a_lista_de_tags_permitidas_e_fechada() -> None:
    assert set(TAGS_PERMITIDAS) == {
        "span.kind",
        "http.method",
        "http.request.method",
        "http.status_code",
        "http.response.status_code",
        "http.route",
        "http.url",
        "url.full",
        "server.address",
        "otel.status_code",
        "error",
        "messaging.system",
        "messaging.operation",
        "messaging.operation.type",
        "messaging.destination.name",
        "db.system",
    }


def test_tag_fora_da_lista_sai_mesmo_com_valor_inofensivo() -> None:
    tags = _tags_de(_por_id(_limpo())["0000000000000004"])

    assert tags == {"span.kind": "client", "db.system": "mongodb"}


# --- o que fica -----------------------------------------------------------------------


def test_o_que_a_evidencia_precisa_mostrar_fica() -> None:
    spans = _por_id(_limpo())

    chamada = spans["0000000000000002"]
    assert chamada["operationName"] == "POST"
    assert chamada["processID"] == "p2"
    assert _tags_de(chamada) == {
        "span.kind": "client",
        "http.method": "POST",
        "http.url": "https://api.mercadopago.com/checkout/preferences",
        "http.status_code": 201,
        "server.address": "api.mercadopago.com",
        "error": True,
        "otel.status_code": "ERROR",
    }
    assert chamada["references"] == [
        {"refType": "CHILD_OF", "traceID": TRACE_ID, "spanID": "0000000000000001"},
        {
            "refType": "FOLLOWS_FROM",
            "traceID": OUTRO_TRACE_ID,
            "spanID": "00000000000000aa",
        },
    ]
    assert chamada["startTime"] == INICIO + 2
    assert chamada["duration"] == 1500
    servidor = spans["0000000000000001"]
    assert servidor["operationName"] == "POST /api/v1/ordens-de-servico"
    assert _tags_de(servidor)["http.route"] == "/api/v1/ordens-de-servico/{ordem_id}"
    assert _tags_de(servidor)["http.url"] == (
        "https://localhost/os/api/v1/ordens-de-servico/{id}"
    )
    mensagem = _tags_de(spans["0000000000000005"])
    assert mensagem == {
        "span.kind": "producer",
        "messaging.system": "rabbitmq",
        "messaging.operation.type": "send",
        "messaging.destination.name": "pytstop.comandos",
    }
    assert spans["0000000000000005"]["operationName"] == "publish PagamentoSolicitado"


def test_nome_de_operacao_com_query_perde_a_query_e_com_texto_livre_e_omitido() -> None:
    spans = _por_id(_limpo())

    assert spans["0000000000000003"]["operationName"] == "GET /v1/payments/search"
    assert spans["0000000000000004"]["operationName"] == OPERACAO_OMITIDA
    assert spans["0000000000000006"]["operationName"] == "/clientes/{id} vinte"


def test_valor_de_tag_permitida_fora_da_forma_esperada_sai_junto_com_a_tag() -> None:
    tags = _tags_de(_por_id(_limpo())["0000000000000006"])

    assert tags == {
        # O texto livre e a URL de outro esquema saem; a rota e a URL perdem o que
        # parece id, o usuario e a senha, a query e o fragmento.
        "http.route": "/clientes/{id}/{id}",
        "http.url": "https://x.test/x",
    }


@pytest.mark.parametrize(
    ("chave", "valor", "sai"),
    [
        pytest.param("span.kind", "client", True, id="kind"),
        pytest.param("span.kind", "CLIENT", False, id="kind-em-maiuscula"),
        pytest.param("span.kind", "client ", False, id="kind-com-espaco"),
        pytest.param("http.method", "GET", True, id="metodo"),
        pytest.param("http.request.method", "_OTHER", True, id="metodo-outro"),
        pytest.param("http.method", "get", False, id="metodo-minusculo"),
        pytest.param("http.method", "GET /x", False, id="metodo-com-caminho"),
        pytest.param("http.status_code", 200, True, id="status"),
        pytest.param("http.response.status_code", 503, True, id="status-novo"),
        pytest.param("http.status_code", 99, False, id="status-abaixo"),
        pytest.param("http.status_code", 600, False, id="status-acima"),
        pytest.param("http.status_code", True, False, id="status-booleano"),
        pytest.param("http.status_code", "200", False, id="status-em-texto"),
        pytest.param("otel.status_code", "ERROR", True, id="otel-erro"),
        pytest.param("otel.status_code", "OK", True, id="otel-ok"),
        pytest.param("otel.status_code", "ERROR: cpf", False, id="otel-com-texto"),
        pytest.param("error", True, True, id="erro"),
        pytest.param("error", "true", False, id="erro-em-texto"),
        pytest.param("messaging.system", "rabbitmq", True, id="sistema"),
        pytest.param("messaging.system", "rabbitmq://h", False, id="sistema-url"),
        pytest.param("messaging.operation", "publish", True, id="operacao"),
        pytest.param("messaging.operation.type", "process", True, id="tipo"),
        pytest.param("messaging.operation.type", "process 1", False, id="tipo-numero"),
        pytest.param("messaging.destination.name", "os.eventos", True, id="fila"),
        pytest.param(
            "messaging.destination.name", "billing.comandos.retry.15s", True, id="retry"
        ),
        pytest.param(
            "messaging.destination.name", f"os.eventos.{ORDEM_ID}", False, id="fila-id"
        ),
        pytest.param(
            "messaging.destination.name", "os.eventos.", False, id="fila-ponto"
        ),
        pytest.param("db.system", "postgresql", True, id="banco"),
        pytest.param("db.system", "postgresql://u:p@h", False, id="banco-url"),
        pytest.param("server.address", "api.mercadopago.com", True, id="host-do-mp"),
        pytest.param("server.address", "API.MercadoPago.com", True, id="host-em-caixa"),
        pytest.param("server.address", "billing-service", False, id="outro-host"),
        pytest.param(
            "server.address",
            "api.mercadopago.com.evil.example",
            False,
            id="host-sufixo",
        ),
        pytest.param(
            "server.address", "evil-api.mercadopago.com", False, id="host-prefixo"
        ),
        pytest.param("server.address", 5, False, id="host-numero"),
        pytest.param(
            "http.route", "/api/v1/pagamentos/{pagamento_id}", True, id="rota"
        ),
        pytest.param("http.route", "api/v1", False, id="rota-sem-barra"),
        pytest.param("http.route", 5, False, id="rota-numero"),
        pytest.param("http.url", 5, False, id="url-numero"),
        pytest.param("db.statement", "find", False, id="fora-da-lista"),
        pytest.param("http.target", "/x", False, id="fora-da-lista-2"),
        pytest.param("net.peer.ip", "10.0.0.1", False, id="fora-da-lista-3"),
    ],
)
def test_valor_de_cada_tag_so_passa_na_forma_esperada(
    chave: str, valor: object, sai: bool
) -> None:
    bruto = _trace_cheio_de_dado_sensivel()
    bruto["spans"] = [
        _span("0000000000000001", "GET", "p1", {}, tags=[_tag(chave, valor)])
    ]

    limpo = higienizar_trace(bruto)

    assert limpo is not None
    tags = _tags_de(limpo["spans"][0])
    assert (chave in tags) is sai
    if sai:
        assert tags[chave] == (
            str(valor).lower() if chave == "server.address" else valor
        )


@pytest.mark.parametrize(
    ("chave", "valor", "esperado"),
    [
        pytest.param(
            "http.route",
            "/pagamentos/{pagamento_id}?x=1#f",
            "/pagamentos/{pagamento_id}",
            id="rota-sem-query-nem-fragmento",
        ),
        pytest.param(
            "http.route", "/clientes/12345678909", "/clientes/{id}", id="rota-com-cpf"
        ),
        pytest.param(
            "http.route", "/a#12345678909/b", "/a", id="rota-com-fragmento-no-meio"
        ),
        pytest.param(
            "http.url",
            f"{MP}/v1/payments/9?access_token=x#f",
            f"{MP}/v1/payments/{{id}}",
            id="url-do-mp",
        ),
        pytest.param(
            "url.full",
            "/os/api/v1/ordens/9?cpf=1",
            "/os/api/v1/ordens/{id}",
            id="relativa",
        ),
    ],
)
def test_rota_e_url_das_tags_saem_reduzidas(
    chave: str, valor: str, esperado: str
) -> None:
    bruto = _trace_cheio_de_dado_sensivel()
    bruto["spans"] = [
        _span("0000000000000001", "GET", "p1", {}, tags=[_tag(chave, valor)])
    ]

    limpo = higienizar_trace(bruto)

    assert limpo is not None
    assert _tags_de(limpo["spans"][0]) == {chave: esperado}


def test_tag_com_o_tipo_trocado_sai() -> None:
    bruto = _trace_cheio_de_dado_sensivel()
    tags = [
        {"key": "http.status_code", "type": "string", "value": 200},
        {"key": "span.kind", "type": "int64", "value": "client"},
        {"key": "span.kind", "value": "client"},
    ]
    bruto["spans"] = [_span("0000000000000001", "GET", "p1", {}, tags=tags)]

    limpo = higienizar_trace(bruto)

    assert limpo is not None
    assert limpo["spans"][0]["tags"] == []


# --- a URL reduzida -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "esperada"),
    [
        pytest.param(
            f"{MP}/v1/payments/1234567890", f"{MP}/v1/payments/{{id}}", id="numero"
        ),
        pytest.param(
            f"{MP}/v1/payments/search", f"{MP}/v1/payments/search", id="palavra"
        ),
        pytest.param(
            f"{MP}/v1/payments/search?external_reference={PAGAMENTO_ID}&limit=1",
            f"{MP}/v1/payments/search",
            id="query",
        ),
        pytest.param(
            f"{MP}/v1/payments/{CPF}#{EMAIL}",
            f"{MP}/v1/payments/{{id}}",
            id="fragmento",
        ),
        pytest.param(
            f"{MP}/checkout/preferences/{PREFERENCIA}",
            f"{MP}/checkout/preferences/{{id}}",
            id="preferencia",
        ),
        pytest.param(
            f"{MP}/v1/payments/{PAGAMENTO_ID}/refunds",
            f"{MP}/v1/payments/{{id}}/refunds",
            id="uuid",
        ),
        pytest.param(
            f"https://x.test/publico/orcamentos/{CREDENCIAL_DO_LINK}",
            "https://x.test/publico/orcamentos/{id}",
            id="token",
        ),
        pytest.param(
            "https://x.test/placa/ABC1D23", "https://x.test/placa/{id}", id="placa"
        ),
        pytest.param("https://x.test/a/Maria", "https://x.test/a/{id}", id="maiuscula"),
        pytest.param(
            "https://x.test/a/b%2Fc", "https://x.test/a/{id}", id="codificado"
        ),
        pytest.param(
            "https://x.test/a;jsessionid=abc",
            "https://x.test/{id}",
            id="parametro-de-caminho",
        ),
        pytest.param(
            "https://x.test/oauth2/token",
            "https://x.test/{id}/token",
            id="digito-na-palavra",
        ),
        pytest.param(
            "https://x.test/v1/v123/v2", "https://x.test/v1/{id}/v2", id="versao"
        ),
        pytest.param(
            "https://x.test/" + "a" * 41, "https://x.test/{id}", id="palavra-longa"
        ),
        pytest.param(
            "https://x.test/api/{pagamento_id}/x",
            "https://x.test/api/{pagamento_id}/x",
            id="modelo",
        ),
        pytest.param("https://x.test/a/", "https://x.test/a/", id="barra-final"),
        pytest.param("https://x.test", "https://x.test", id="sem-caminho"),
        pytest.param(
            f"https://joao:{SENHA}@x.test/a", "https://x.test/a", id="usuario"
        ),
        pytest.param("HTTPS://API.MercadoPago.COM/v1", f"{MP}/v1", id="caixa"),
        pytest.param(
            "http://billing-service.pytstop-billing.svc.cluster.local:8000/api/v1/precos",
            "http://billing-service.pytstop-billing.svc.cluster.local:8000/api/v1/precos",
            id="porta",
        ),
        pytest.param(
            f"/api/v1/ordens-de-servico?cpf={CPF}",
            "/api/v1/ordens-de-servico",
            id="relativa",
        ),
        pytest.param(
            f"/api/v1/clientes/{CPF}/{EMAIL}",
            "/api/v1/clientes/{id}/{id}",
            id="relativa-com-dado",
        ),
        pytest.param("/", "/", id="raiz"),
    ],
)
def test_url_reduzida_a_esquema_host_e_caminho_sem_id(url: str, esperada: str) -> None:
    assert url_reduzida(url) == esperada


@pytest.mark.parametrize(
    "url",
    [
        pytest.param("ftp://x.test/a", id="esquema-ftp"),
        pytest.param(f"amqp://u:{SENHA}@rabbitmq/vhost", id="esquema-amqp"),
        pytest.param("javascript:alert(1)", id="esquema-javascript"),
        pytest.param("file:///etc/passwd", id="esquema-file"),
        pytest.param("x.test/a", id="sem-esquema"),
        pytest.param("", id="vazia"),
        pytest.param("https:///a", id="sem-host"),
        pytest.param("https://x_y.test/a", id="host-com-sublinhado"),
        pytest.param("https://[::1]:8000/a", id="host-ipv6"),
        pytest.param("https://x.test:99999999/a", id="porta-fora-da-faixa"),
        pytest.param("https://x.test:abc/a", id="porta-nao-numerica"),
        pytest.param("https://[x.test/a", id="colchete-aberto"),
        pytest.param("https://x.test;x/a", id="host-com-ponto-e-virgula"),
    ],
)
def test_url_que_nao_e_http_com_host_valido_nao_sai(url: str) -> None:
    assert url_reduzida(url) is None


# --- a chamada do Billing ao Mercado Pago ---------------------------------------------


def _trace_com(
    servico: str, tags: dict[str, object], *, spans_a_mais: int = 0
) -> dict[str, Any]:
    spans = [_span("0000000000000001", "POST", "p1", tags)]
    spans += [
        _span(f"{numero:016x}", "find", "p1", {"span.kind": "client"})
        for numero in range(2, 2 + spans_a_mais)
    ]
    limpo = higienizar_trace(
        {
            "traceID": TRACE_ID,
            "spans": spans,
            "processes": {"p1": {"serviceName": servico}},
        }
    )
    assert limpo is not None
    return limpo


@pytest.mark.parametrize(
    ("servico", "tags", "chamou"),
    [
        pytest.param(
            "billing-service",
            {"span.kind": "client", "http.url": f"{MP}/v1/payments/9"},
            True,
            id="http.url",
        ),
        pytest.param(
            "billing-service",
            {"span.kind": "client", "url.full": f"{MP}/v1/payments/9"},
            True,
            id="url.full",
        ),
        pytest.param(
            "billing-service",
            {"span.kind": "client", "server.address": "api.mercadopago.com"},
            True,
            id="server.address",
        ),
        pytest.param(
            "execution-service",
            {"span.kind": "client", "http.url": f"{MP}/v1/payments/9"},
            False,
            id="outro-servico",
        ),
        pytest.param(
            "billing-service",
            {"span.kind": "server", "http.url": f"{MP}/v1/payments/9"},
            False,
            id="span-de-servidor",
        ),
        pytest.param(
            "billing-service",
            {
                "span.kind": "client",
                "http.url": "https://api.mercadopago.com.evil.test/x",
            },
            False,
            id="host-parecido",
        ),
        pytest.param(
            "billing-service",
            {
                "span.kind": "client",
                "http.url": "https://evil.test/api.mercadopago.com",
            },
            False,
            id="host-no-caminho",
        ),
        pytest.param(
            "billing-service",
            {"span.kind": "client", "http.url": "http://billing-service:8000/api/v1/x"},
            False,
            id="chamada-interna",
        ),
        pytest.param(
            "billing-service",
            {"span.kind": "client", "db.system": "mongodb"},
            False,
            id="banco",
        ),
        pytest.param(
            "billing-service",
            {"http.url": f"{MP}/v1/payments/9"},
            False,
            id="sem-kind",
        ),
    ],
)
def test_chamada_ao_mercado_pago_exige_span_client_do_billing_para_o_host(
    servico: str, tags: dict[str, object], chamou: bool
) -> None:
    assert chamada_ao_mercado_pago(_trace_com(servico, tags)) is chamou


def test_chamada_ao_mercado_pago_olha_so_o_que_a_lista_deixou() -> None:
    # O host so aparece em ``net.peer.name`` e na URL com query: nada disso conta.
    bruto = _trace_cheio_de_dado_sensivel()
    for span in bruto["spans"]:
        span["tags"] = [
            t for t in span["tags"] if t["key"] in {"span.kind", "net.peer.name"}
        ]

    limpo = higienizar_trace(bruto)

    assert limpo is not None
    assert chamada_ao_mercado_pago(limpo) is False
    assert chamada_ao_mercado_pago(_limpo()) is True


def _tres_pecas(spans: int, *, com_chamada: bool) -> dict[str, Any]:
    marca: dict[str, object] = {
        "span.kind": "client",
        "http.url": f"{MP}/v1/payments/9",
    }
    bruto = {
        "traceID": TRACE_ID,
        "spans": [
            _span(f"{n:016x}", "find", p, marca if com_chamada and n == 1 else {})
            for n, p in enumerate(["p2"] * spans, start=1)
        ]
        + [
            _span(f"{spans + n:016x}", "find", p, {}) for n, p in ((1, "p1"), (2, "p3"))
        ],
        "processes": {
            "p1": {"serviceName": "os-service"},
            "p2": {"serviceName": "billing-service"},
            "p3": {"serviceName": "execution-service"},
        },
    }
    limpo = higienizar_trace(bruto)
    assert limpo is not None
    return limpo


def test_escolher_trace_prefere_o_que_tem_a_chamada_mesmo_com_menos_spans() -> None:
    grande_sem_chamada = _tres_pecas(30, com_chamada=False)
    pequeno_com_chamada = _tres_pecas(3, com_chamada=True)
    outro_com_chamada = _tres_pecas(2, com_chamada=True)

    assert (
        escolher_trace([grande_sem_chamada, outro_com_chamada, pequeno_com_chamada])
        is pequeno_com_chamada
    )


def test_escolher_trace_com_chamada_aceita_trace_sem_alguma_das_pecas() -> None:
    so_o_billing = _trace_com(
        "billing-service", {"span.kind": "client", "http.url": f"{MP}/v1/payments/9"}
    )

    assert (
        escolher_trace([_tres_pecas(30, com_chamada=False), so_o_billing])
        is so_o_billing
    )


def test_escolher_trace_sem_chamada_fica_com_o_completo_de_mais_spans() -> None:
    pequeno = _tres_pecas(3, com_chamada=False)
    grande = _tres_pecas(30, com_chamada=False)
    incompleto = _trace_com("os-service", {"span.kind": "server"}, spans_a_mais=200)

    assert escolher_trace([pequeno, incompleto, grande]) is grande


def test_escolher_trace_sem_trace_completo_nem_chamada_devolve_none() -> None:
    incompleto = _trace_com("os-service", {"span.kind": "server"}, spans_a_mais=3)

    assert escolher_trace([incompleto]) is None
    assert escolher_trace([]) is None


# --- o nome do arquivo ----------------------------------------------------------------


@pytest.mark.parametrize(
    "trace_id",
    [
        pytest.param(TRACE_ID, id="32-hex"),
        pytest.param("a2d7f57c7493014c", id="16-hex"),
    ],
)
def test_o_nome_do_arquivo_leva_a_chave_e_o_trace_id_hexadecimal(trace_id: str) -> None:
    assert nome_do_arquivo("estorno", trace_id) == f"trace-estorno-{trace_id}.json"
    assert nome_do_arquivo("cobranca-aberta", trace_id).startswith(
        "trace-cobranca-aberta-"
    )
    assert nome_do_arquivo("cenario-3", trace_id).startswith("trace-cenario-3-")


@pytest.mark.parametrize(
    "trace_id",
    [
        pytest.param("../../etc/passwd", id="caminho"),
        pytest.param(f"{TRACE_ID}/../x", id="sufixo"),
        pytest.param(TRACE_ID.upper(), id="maiusculas"),
        pytest.param(f"{TRACE_ID}.json", id="extensao"),
        pytest.param("abc123", id="curto"),
        pytest.param("a" * 33, id="longo"),
        pytest.param("", id="vazio"),
        pytest.param(f"{TRACE_ID}\n", id="quebra-de-linha"),
    ],
)
def test_o_nome_do_arquivo_recusa_trace_id_que_nao_e_hexadecimal(trace_id: str) -> None:
    with pytest.raises(TraceIdInvalidoError, match="fora do formato"):
        nome_do_arquivo("pagamento", trace_id)


@pytest.mark.parametrize(
    "chave",
    [
        pytest.param("", id="vazia"),
        pytest.param("../pagamento", id="caminho"),
        pytest.param("Pagamento", id="maiuscula"),
        pytest.param("pagamento.json", id="ponto"),
        pytest.param("pagamento\n", id="quebra-de-linha"),
        pytest.param("a" * 33, id="longa"),
    ],
)
def test_o_nome_do_arquivo_recusa_chave_de_cenario_fora_do_formato(chave: str) -> None:
    with pytest.raises(ChaveDeArquivoInvalidaError, match="fora do formato"):
        nome_do_arquivo(chave, TRACE_ID)


def test_arquivo_do_trace_e_o_formato_do_upload_do_jaeger() -> None:
    nome, texto = arquivo_do_trace("pagamento", _limpo())

    assert nome == f"trace-pagamento-{TRACE_ID}.json"
    assert texto.endswith("}\n")
    assert json.loads(texto) == {"data": [_limpo()]}


def test_trace_com_trace_id_invalido_nao_vira_arquivo() -> None:
    trace = _limpo()
    trace["traceID"] = "../x"

    with pytest.raises(TraceIdInvalidoError):
        arquivo_do_trace("pagamento", trace)


# --- aceito pelo upload do Jaeger -----------------------------------------------------


def _aceito_pelo_upload(texto: str) -> None:
    """O que o "JSON File" da tela de busca exige: o ``transformTraceData`` le isto."""
    arquivo = json.loads(texto)
    assert isinstance(arquivo["data"], list)
    for trace in arquivo["data"]:
        assert isinstance(trace["traceID"], str)
        assert isinstance(trace["processes"], dict)
        for span in trace["spans"]:
            assert isinstance(span["spanID"], str)
            assert isinstance(span["operationName"], str)
            assert isinstance(span["startTime"], int)
            assert isinstance(span["duration"], int)
            assert span["processID"] in trace["processes"]
            assert isinstance(span["references"], list)
            assert isinstance(span["tags"], list)
            for tag in span["tags"]:
                assert set(tag) == {"key", "type", "value"}
        for processo in trace["processes"].values():
            assert isinstance(processo["serviceName"], str)


def test_o_arquivo_tem_as_chaves_que_o_upload_do_jaeger_le() -> None:
    _aceito_pelo_upload(arquivo_do_trace("pagamento", _limpo())[1])


def test_o_trace_real_da_entrega_passa_inteiro_e_so_com_chaves_do_jaeger() -> None:
    """O Jaeger 1.76 real (245 spans da saga): so perde o que a lista corta."""
    real = json.loads(TRACE_REAL.read_text(encoding="utf-8"))["data"][0]

    limpo = higienizar_trace(real)

    assert limpo is not None
    assert len(limpo["spans"]) == len(real["spans"]) == 245
    assert [s["spanID"] for s in limpo["spans"]] == [s["spanID"] for s in real["spans"]]
    assert [s["references"] for s in limpo["spans"]] == [
        s["references"] for s in real["spans"]
    ]
    assert OPERACAO_OMITIDA not in {s["operationName"] for s in limpo["spans"]}
    # Chaves que o proprio Jaeger usa: nada inventado.
    assert set(limpo) <= set(real)
    assert {c for s in limpo["spans"] for c in s} <= {
        c for s in real["spans"] for c in s
    }
    assert {c for p in limpo["processes"].values() for c in p} <= {
        c for p in real["processes"].values() for c in p
    }
    assert {c for s in limpo["spans"] for t in s["tags"] for c in t} == {
        c for s in real["spans"] for t in s["tags"] for c in t
    }
    chaves = {t["key"] for s in limpo["spans"] for t in s["tags"]}
    assert chaves <= set(TAGS_PERMITIDAS)
    assert {"span.kind", "messaging.destination.name", "http.route"} <= chaves
    assert {t["key"] for s in real["spans"] for t in s["tags"]} - chaves, "algo saiu"
    texto = arquivo_do_trace("pagamento", limpo)[1]
    _aceito_pelo_upload(texto)
    # A varredura da pasta, no fim do make, apaga o arquivo em que acha segredo: o
    # trace real nao pode ser um falso positivo, ou a evidencia que so existe uma vez
    # some depois de gravada.
    assert varrer(texto) == []
    assert {"os-service", "billing-service", "execution-service"} == {
        p["serviceName"] for p in limpo["processes"].values()
    }
    assert chamada_ao_mercado_pago(limpo) is False


# --- o que o Jaeger devolve e desconhecido --------------------------------------------


def _com_spans(spans: object) -> dict[str, Any]:
    return {
        "traceID": TRACE_ID,
        "spans": spans,
        "processes": {"p1": {"serviceName": "os-service"}},
    }


@pytest.mark.parametrize(
    "lixo",
    [
        pytest.param(None, id="none"),
        pytest.param(5, id="numero"),
        pytest.param("texto", id="texto"),
        pytest.param([], id="lista"),
        pytest.param({}, id="vazio"),
        pytest.param({"traceID": 5}, id="id-numero"),
        pytest.param({"traceID": "../x"}, id="id-fora-do-formato"),
        pytest.param({"traceID": TRACE_ID}, id="sem-spans"),
        pytest.param(_com_spans(None), id="spans-none"),
        pytest.param(_com_spans("x"), id="spans-texto"),
        pytest.param(_com_spans([]), id="spans-vazio"),
        pytest.param(_com_spans([None, 5, "x", [], {}]), id="spans-lixo"),
        pytest.param(
            {
                "traceID": TRACE_ID,
                "spans": [_span("0000000000000001", "GET", "p1", {})],
            },
            id="sem-processos",
        ),
        pytest.param(
            {
                "traceID": TRACE_ID,
                "spans": [_span("0000000000000001", "GET", "p1", {})],
                "processes": ["p1"],
            },
            id="processos-lista",
        ),
        pytest.param(
            {
                "traceID": TRACE_ID,
                "spans": [_span("0000000000000001", "GET", "p1", {})],
                "processes": {
                    "p1": {"serviceName": "a b"},
                    "../": {"serviceName": "ok"},
                },
            },
            id="processo-fora-do-formato",
        ),
        pytest.param(
            {
                "traceID": TRACE_ID,
                "spans": [_span("0000000000000001", "GET", "p1", {})],
                "processes": {"p1": "os-service", "p2": {"serviceName": 5}},
            },
            id="processo-lixo",
        ),
    ],
)
def test_o_que_nao_e_trace_vira_none_sem_levantar(lixo: object) -> None:
    assert higienizar_trace(lixo) is None


@pytest.mark.parametrize(
    "campos",
    [
        pytest.param({"spanID": "xyz"}, id="span-id-fora-do-formato"),
        pytest.param({"spanID": "00000000000000AB"}, id="span-id-maiusculo"),
        pytest.param({"spanID": 1}, id="span-id-numero"),
        pytest.param({"traceID": OUTRO_TRACE_ID}, id="trace-id-de-outro-trace"),
        pytest.param({"processID": "p9"}, id="processo-desconhecido"),
        pytest.param({"processID": ["p1"]}, id="processo-lista"),
        pytest.param({"startTime": "1"}, id="inicio-texto"),
        pytest.param({"startTime": True}, id="inicio-booleano"),
        pytest.param({"startTime": -1}, id="inicio-negativo"),
        pytest.param({"duration": None}, id="duracao-none"),
        pytest.param({"duration": 1.5}, id="duracao-fracionada"),
    ],
)
def test_span_sem_o_que_o_jaeger_exige_sai_e_os_outros_ficam(
    campos: dict[str, object],
) -> None:
    bom = _span("0000000000000002", "find", "p1", {"span.kind": "client"})
    ruim = {**_span("0000000000000001", "GET", "p1", {}), **campos}

    limpo = higienizar_trace(_com_spans([ruim, bom]))

    assert limpo is not None
    assert [s["spanID"] for s in limpo["spans"]] == ["0000000000000002"]


@pytest.mark.parametrize(
    ("tags", "esperadas"),
    [
        pytest.param("texto", [], id="nao-e-lista"),
        pytest.param(None, [], id="none"),
        pytest.param([None, 5, "x", []], [], id="itens-lixo"),
        pytest.param(
            [{"key": ["span.kind"], "type": "string", "value": "client"}],
            [],
            id="chave-lista",
        ),
        pytest.param([{"key": 5}], [], id="chave-numero"),
        pytest.param([{"key": "span.kind"}], [], id="sem-valor"),
        pytest.param(
            [{"key": "span.kind", "type": "string", "value": "client", "x": "y"}],
            [{"key": "span.kind", "type": "string", "value": "client"}],
            id="campo-a-mais",
        ),
    ],
)
def test_tags_fora_do_formato_do_jaeger_nao_quebram(
    tags: object, esperadas: list[dict[str, str]]
) -> None:
    limpo = higienizar_trace(
        _com_spans([{**_span("0000000000000001", "GET", "p1", {}), "tags": tags}])
    )

    assert limpo is not None
    assert limpo["spans"][0]["tags"] == esperadas


@pytest.mark.parametrize(
    ("referencias", "esperadas"),
    [
        pytest.param("x", [], id="nao-e-lista"),
        pytest.param([None, 5, "x"], [], id="itens-lixo"),
        pytest.param(
            [{"refType": "OUTRO", "traceID": TRACE_ID, "spanID": "0000000000000001"}],
            [],
            id="tipo-desconhecido",
        ),
        pytest.param(
            [{"refType": "CHILD_OF", "traceID": "../x", "spanID": "0000000000000001"}],
            [],
            id="trace-id-fora-do-formato",
        ),
        pytest.param(
            [{"refType": "CHILD_OF", "traceID": TRACE_ID, "spanID": "../x"}],
            [],
            id="span-id-fora-do-formato",
        ),
        pytest.param(
            [
                {
                    "refType": "CHILD_OF",
                    "traceID": TRACE_ID,
                    "spanID": "0000000000000001",
                    "extra": "x",
                }
            ],
            [
                {
                    "refType": "CHILD_OF",
                    "traceID": TRACE_ID,
                    "spanID": "0000000000000001",
                }
            ],
            id="campo-a-mais",
        ),
    ],
)
def test_referencias_fora_do_formato_do_jaeger_sao_descartadas(
    referencias: object, esperadas: list[dict[str, str]]
) -> None:
    span = {**_span("0000000000000002", "GET", "p1", {}), "references": referencias}

    limpo = higienizar_trace(_com_spans([span]))

    assert limpo is not None
    assert limpo["spans"][0]["references"] == esperadas


@pytest.mark.parametrize(
    ("nome", "esperado"),
    [
        pytest.param("GET", "GET", id="metodo"),
        pytest.param("SELECT os", "SELECT os", id="banco"),
        pytest.param("billing.find", "billing.find", id="mongo"),
        pytest.param("iniciar diagnostico", "iniciar diagnostico", id="duas-palavras"),
        pytest.param(
            "process PagamentoConfirmado", "process PagamentoConfirmado", id="mensagem"
        ),
        pytest.param(
            "POST /api/v1/precos/validacao", "POST /api/v1/precos/validacao", id="rota"
        ),
        pytest.param("a b c d", "a b c d", id="quatro-palavras"),
        pytest.param("a b c d e", OPERACAO_OMITIDA, id="cinco-palavras"),
        pytest.param("", OPERACAO_OMITIDA, id="vazio"),
        pytest.param("GET  /x", OPERACAO_OMITIDA, id="espaco-duplo"),
        pytest.param("GET /a/123.456.789-09", "GET /a/{id}", id="cpf-no-caminho"),
        pytest.param("GET /a?x=1 b", "GET /a b", id="query-no-meio"),
        pytest.param("GET /a#CPF123", "GET /a", id="fragmento"),
        pytest.param("find 123", OPERACAO_OMITIDA, id="numero"),
        pytest.param("SELECT cpf FROM c WHERE e = 'a@b.c'", OPERACAO_OMITIDA, id="sql"),
        pytest.param("a" * 65, OPERACAO_OMITIDA, id="palavra-longa"),
        pytest.param("joao@exemplo.com", OPERACAO_OMITIDA, id="email"),
        pytest.param("x/y", OPERACAO_OMITIDA, id="barra-no-meio"),
    ],
)
def test_nome_de_operacao_so_passa_na_forma_de_nome(nome: str, esperado: str) -> None:
    limpo = higienizar_trace(_com_spans([_span("0000000000000001", nome, "p1", {})]))

    assert limpo is not None
    assert limpo["spans"][0]["operationName"] == esperado


def test_nome_de_operacao_que_nao_e_texto_e_omitido() -> None:
    span = {**_span("0000000000000001", "x", "p1", {}), "operationName": 5}

    limpo = higienizar_trace(_com_spans([span]))

    assert limpo is not None
    assert limpo["spans"][0]["operationName"] == OPERACAO_OMITIDA


# --- o trace de um cenario ------------------------------------------------------------


def test_trace_do_cenario_diz_arquivo_servicos_e_chamada() -> None:
    achado = TraceDoCenario("pagamento", _limpo())

    assert achado.arquivo == f"trace-pagamento-{TRACE_ID}.json"
    assert achado.servicos == ["billing-service", "execution-service", "os-service"]
    assert achado.chamou_o_mercado_pago is True


def test_trace_do_cenario_sem_trace_nao_tem_arquivo_nem_servicos_nem_chamada() -> None:
    achado = TraceDoCenario("pagamento", None, "motivo")

    assert achado.arquivo is None
    assert achado.servicos == []
    assert achado.chamou_o_mercado_pago is False
    assert achado.motivo == "motivo"
