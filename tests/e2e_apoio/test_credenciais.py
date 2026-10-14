"""Credenciais do E2E: login uma vez, usuarios registrados pelo admin, renovacao."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import httpx
import pytest

from e2e.apoio.credenciais import VIDA_DO_TOKEN, Credenciais
from e2e.apoio.http import ClienteHttp
from e2e.apoio.segredos import mascarar

if TYPE_CHECKING:
    from e2e_apoio.falsos import Relogio

SENHA_DO_ADMIN = "senha-do-admin-123456"


class OsFalso:
    """O que o OS responde ao login e ao registro, e o que ele recebeu."""

    def __init__(self) -> None:
        self.pedidos: list[httpx.Request] = []
        self.logins = 0

    def __call__(self, pedido: httpx.Request) -> httpx.Response:
        self.pedidos.append(pedido)
        if pedido.url.path.endswith("/registrar"):
            return httpx.Response(201, json={"id": "u1"})
        self.logins += 1
        return httpx.Response(
            200, json={"access_token": f"eyJ-jwt-numero-{self.logins}-x"}
        )

    def corpos(self, final: str) -> list[dict[str, str]]:
        return [
            json.loads(p.content) for p in self.pedidos if p.url.path.endswith(final)
        ]


def _credenciais(os_falso: OsFalso, relogio: Relogio) -> Credenciais:
    http = ClienteHttp(
        "http://os.local",
        transporte=httpx.MockTransport(os_falso),
        relogio=relogio,
        dormir=relogio.dormir,
    )
    return Credenciais(
        http,
        admin_email="admin@pytstop.dev",
        admin_senha=SENHA_DO_ADMIN,
        execucao="3FA9C1",
        relogio=relogio,
    )


def test_construtor_mascara_a_senha_do_admin(relogio: Relogio) -> None:
    _credenciais(OsFalso(), relogio)

    assert mascarar(f"senha {SENHA_DO_ADMIN}") == "senha ***"


def test_preparar_registra_atendente_e_mecanico_pelo_admin(relogio: Relogio) -> None:
    os_falso = OsFalso()
    credenciais = _credenciais(os_falso, relogio)

    credenciais.preparar()

    registros = os_falso.corpos("/registrar")
    assert [(r["email"], r["papel"]) for r in registros] == [
        ("e2e-3fa9c1-atendente@e2e.pytstop.dev", "atendente"),
        ("e2e-3fa9c1-mecanico@e2e.pytstop.dev", "mecanico"),
    ]
    assert all(len(r["senha"]) >= 12 for r in registros)
    assert registros[0]["senha"] != registros[1]["senha"]


def test_preparar_manda_o_token_do_admin_no_registro(relogio: Relogio) -> None:
    os_falso = OsFalso()

    _credenciais(os_falso, relogio).preparar()

    registros = [p for p in os_falso.pedidos if p.url.path.endswith("/registrar")]
    assert {p.headers["authorization"] for p in registros} == {
        "Bearer eyJ-jwt-numero-1-x"
    }
    assert os_falso.logins == 1


def test_senhas_geradas_e_tokens_entram_na_mascara(relogio: Relogio) -> None:
    os_falso = OsFalso()
    credenciais = _credenciais(os_falso, relogio)

    credenciais.preparar()
    token = credenciais.token("atendente")

    for registro in os_falso.corpos("/registrar"):
        assert mascarar(f"senha {registro['senha']}") == "senha ***"
    assert mascarar(f"token {token}") == "token ***"
    assert mascarar("Bearer eyJ-jwt-numero-1-x") == "Bearer ***"


def test_login_usa_o_email_e_a_senha_de_cada_papel(relogio: Relogio) -> None:
    os_falso = OsFalso()
    credenciais = _credenciais(os_falso, relogio)
    credenciais.preparar()

    credenciais.token("atendente")
    credenciais.token("mecanico")

    logins = os_falso.corpos("/login")
    registros = os_falso.corpos("/registrar")
    assert logins[0] == {"email": "admin@pytstop.dev", "senha": SENHA_DO_ADMIN}
    assert logins[1] == {"email": registros[0]["email"], "senha": registros[0]["senha"]}
    assert logins[2] == {"email": registros[1]["email"], "senha": registros[1]["senha"]}


def test_token_e_reaproveitado_ate_os_12_minutos(relogio: Relogio) -> None:
    os_falso = OsFalso()
    credenciais = _credenciais(os_falso, relogio)
    primeiro = credenciais.token("admin")

    relogio.agora += VIDA_DO_TOKEN
    assert credenciais.token("admin") == primeiro

    assert os_falso.logins == 1


def test_token_e_renovado_depois_dos_12_minutos(relogio: Relogio) -> None:
    os_falso = OsFalso()
    credenciais = _credenciais(os_falso, relogio)
    primeiro = credenciais.token("admin")

    relogio.agora += VIDA_DO_TOKEN + 1
    segundo = credenciais.token("admin")

    assert segundo != primeiro
    assert os_falso.logins == 2
    assert mascarar(f"token {segundo}") == "token ***"


def test_login_recusado_reprova_com_a_resposta_mascarada(relogio: Relogio) -> None:
    def recusa(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"erro": {"codigo": "NAO_AUTENTICADO"}})

    http = ClienteHttp("http://os.local", transporte=httpx.MockTransport(recusa))
    credenciais = Credenciais(
        http,
        admin_email="admin@pytstop.dev",
        admin_senha=SENHA_DO_ADMIN,
        execucao="3FA9C1",
        relogio=relogio,
    )

    with pytest.raises(AssertionError, match="HTTP 401"):
        credenciais.token("admin")
