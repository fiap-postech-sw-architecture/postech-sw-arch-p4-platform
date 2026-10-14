"""Cliente HTTP do E2E: TLS so para localhost, 429 com espera e erro sem segredo."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import httpx
import pytest

from e2e.apoio.http import (
    Cliente,
    RespostaInesperadaError,
    verificar_tls,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from e2e_apoio.falsos import Relogio


def _cliente(
    tratador: Callable[[httpx.Request], httpx.Response],
    relogio: Relogio,
    **opcoes: Any,
) -> Cliente:
    return Cliente(
        "http://servico.local",
        transporte=httpx.MockTransport(tratador),
        relogio=relogio,
        dormir=relogio.dormir,
        **opcoes,
    )


def test_pedir_manda_o_token_como_bearer(relogio: Relogio) -> None:
    vistos: list[httpx.Request] = []

    def tratador(pedido: httpx.Request) -> httpx.Response:
        vistos.append(pedido)
        return httpx.Response(200, json={"ok": True})

    credencial = "abc123"
    resposta = _cliente(tratador, relogio).pedir("GET", "/x", token=credencial)

    assert resposta.json() == {"ok": True}
    assert vistos[0].headers["authorization"] == "Bearer abc123"


def test_fechar_encerra_o_cliente_http(relogio: Relogio) -> None:
    cliente = _cliente(lambda _: httpx.Response(200), relogio)

    cliente.fechar()

    with pytest.raises(RuntimeError, match="closed"):
        cliente.pedir("GET", "/x")


def test_pedir_sem_token_nao_manda_authorization(relogio: Relogio) -> None:
    vistos: list[httpx.Request] = []

    def tratador(pedido: httpx.Request) -> httpx.Response:
        vistos.append(pedido)
        return httpx.Response(200)

    _cliente(tratador, relogio).pedir("GET", "/x")

    assert "authorization" not in vistos[0].headers


def test_pedir_envia_json_e_parametros(relogio: Relogio) -> None:
    vistos: list[httpx.Request] = []

    def tratador(pedido: httpx.Request) -> httpx.Response:
        vistos.append(pedido)
        return httpx.Response(201)

    _cliente(tratador, relogio).pedir("POST", "/x", json={"a": 1}, params={"q": "v"})

    assert json.loads(vistos[0].content) == {"a": 1}
    assert vistos[0].url.params["q"] == "v"


def test_pedir_status_fora_do_esperado_reprova_sem_vazar_credencial(
    relogio: Relogio,
) -> None:
    def tratador(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            409,
            headers={"x-request-id": "req-1"},
            json={"link": "https://h/api/v1/publico/orcamentos/SEGREDO.tok"},
        )

    with pytest.raises(RespostaInesperadaError) as erro:
        _cliente(tratador, relogio).pedir("POST", "/x", esperado=[200, 201])

    mensagem = str(erro.value)
    assert "HTTP 409" in mensagem
    assert "[200, 201]" in mensagem
    assert "req-1" in mensagem
    assert "SEGREDO" not in mensagem


def test_pedir_status_esperado_nao_levanta(relogio: Relogio) -> None:
    resposta = _cliente(lambda _: httpx.Response(204), relogio).pedir(
        "DELETE", "/x", esperado=(204,)
    )

    assert resposta.status_code == 204


def test_pedir_sem_esperado_devolve_qualquer_status(relogio: Relogio) -> None:
    resposta = _cliente(lambda _: httpx.Response(503), relogio).pedir("GET", "/x")

    assert resposta.status_code == 503


def test_pedir_429_espera_a_janela_e_tenta_de_novo(relogio: Relogio) -> None:
    respostas = iter([429, 429, 200])

    def tratador(_: httpx.Request) -> httpx.Response:
        return httpx.Response(next(respostas))

    resposta = _cliente(tratador, relogio, intervalo_429=5).pedir(
        "GET", "/x", esperado=[200]
    )

    assert resposta.status_code == 200
    assert relogio.dormidas == [5, 5]


def test_pedir_429_respeita_o_retry_after(relogio: Relogio) -> None:
    respostas = iter(
        [httpx.Response(429, headers={"retry-after": "12"}), httpx.Response(200)]
    )

    _cliente(lambda _: next(respostas), relogio).pedir("GET", "/x", esperado=[200])

    assert relogio.dormidas == [12]


def test_pedir_429_retry_after_invalido_usa_o_intervalo(relogio: Relogio) -> None:
    respostas = iter(
        [httpx.Response(429, headers={"retry-after": "logo"}), httpx.Response(200)]
    )

    _cliente(lambda _: next(respostas), relogio, intervalo_429=3).pedir("GET", "/x")

    assert relogio.dormidas == [3]


def test_pedir_429_desiste_quando_a_janela_acaba(relogio: Relogio) -> None:
    chamadas = []

    def tratador(_: httpx.Request) -> httpx.Response:
        chamadas.append(1)
        return httpx.Response(429, json={"erro": {"codigo": "RATE_LIMIT_EXCEDIDO"}})

    with pytest.raises(RespostaInesperadaError, match="HTTP 429"):
        _cliente(tratador, relogio, espera_429=12, intervalo_429=5).pedir(
            "POST", "/x", esperado=[200]
        )

    # 5 + 5 + 2: a ultima espera e cortada no que resta da janela.
    assert relogio.dormidas == [5, 5, 2]
    assert len(chamadas) == 4


@pytest.mark.parametrize(
    ("url", "verifica"),
    [
        ("https://localhost", False),
        ("https://127.0.0.1:8443", False),
        ("https://[::1]", False),
        ("https://localhost.evil.example", True),
        ("https://exemplo.com.br", True),
        ("https://10.0.0.5", True),
    ],
)
def test_verificar_tls_so_dispensa_para_localhost(url: str, verifica: bool) -> None:
    assert verificar_tls(url) is verifica
