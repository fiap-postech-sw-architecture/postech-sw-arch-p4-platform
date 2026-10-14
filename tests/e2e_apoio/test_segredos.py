"""Mascara de segredos: o que o runner registra e os padroes de credencial."""

from __future__ import annotations

import sys

import pytest

from e2e.apoio import segredos
from e2e_apoio.falsos import CHAVE_APP_USR, CHAVE_DO_MP


def test_mascarar_troca_segredo_registrado() -> None:
    segredos.registrar("abcdef123456")

    assert segredos.mascarar("senha=abcdef123456 fim") == "senha=*** fim"


@pytest.mark.parametrize(
    ("valor", "mascarado"),
    [
        pytest.param("abc", False, id="3-caracteres"),
        pytest.param("abcde", False, id="5-caracteres"),
        pytest.param("abcdef", True, id="6-caracteres"),
        pytest.param("abcdefg", True, id="7-caracteres"),
    ],
)
def test_mascarar_so_registra_valor_de_6_caracteres_ou_mais(
    valor: str, mascarado: bool
) -> None:
    segredos.registrar(valor)

    esperado = "x *** x" if mascarado else f"x {valor} x"
    assert segredos.mascarar(f"x {valor} x") == esperado


def test_mascarar_linha_curta_de_segredo_de_varias_linhas_fica_de_fora() -> None:
    segredos.registrar("abcde\nabcdef")

    assert segredos.mascarar("abcde abcdef") == "abcde ***"


def test_mascarar_o_maior_segredo_primeiro() -> None:
    segredos.registrar("segredo-longo")
    segredos.registrar("segredo-longo-demais")

    assert segredos.mascarar("x segredo-longo-demais y") == "x *** y"


def test_mascarar_segredo_de_varias_linhas_mascara_cada_linha() -> None:
    segredos.registrar("linha-um-123\nlinha-dois-456\nab")

    assert (
        segredos.mascarar("a linha-um-123 b linha-dois-456 c ab") == "a *** b *** c ab"
    )


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        pytest.param(
            "https://localhost/billing/api/v1/publico/orcamentos/abc.123.XYZ-_/decisao",
            "https://localhost/billing/api/v1/publico/orcamentos/***/decisao",
            id="link-de-decisao-no-meio",
        ),
        pytest.param(
            "POST /billing/api/v1/publico/orcamentos/tok.en-1_2",
            "POST /billing/api/v1/publico/orcamentos/***",
            id="link-de-decisao-no-fim",
        ),
        pytest.param(
            "https://localhost/billing/simulador/checkout/84ea5cc1?token=abc123&x=1",
            "https://localhost/billing/simulador/checkout/84ea5cc1?token=***&x=1",
            id="checkout",
        ),
        pytest.param(
            "/aprovar?token=segredo", "/aprovar?token=***", id="token-na-query"
        ),
        pytest.param(
            "/aprovar?a=1&token=segredo",
            "/aprovar?a=1&token=***",
            id="token-apos-outro",
        ),
        pytest.param(
            "Authorization: Bearer abc.def-ghi",
            "Authorization: Bearer ***",
            id="bearer",
        ),
        pytest.param(
            "authorization: bearer abc.def-ghi",
            "authorization: bearer ***",
            id="bearer-minusculo",
        ),
        pytest.param(
            "token eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiIxIn0.c2ln fim",
            "token *** fim",
            id="jwt",
        ),
        pytest.param(
            "token eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiIxIn0. fim",
            "token *** fim",
            id="jwt-sem-assinatura",
        ),
        pytest.param("sem credencial nenhuma", "sem credencial nenhuma", id="nada"),
    ],
)
def test_mascarar_padroes_de_credencial(entrada: str, esperado: str) -> None:
    assert segredos.mascarar(entrada) == esperado


def test_registrar_no_actions_pede_ao_runner_que_mascare(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr(sys, "__stdout__", sys.stdout)

    segredos.registrar("senha-do-admin-123")

    assert capsys.readouterr().out == "\n::add-mask::senha-do-admin-123\n"


def test_registrar_fora_do_actions_nao_imprime_o_segredo(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr(sys, "__stdout__", sys.stdout)

    segredos.registrar("senha-do-admin-123")

    assert capsys.readouterr().out == ""
    assert segredos.mascarar("senha-do-admin-123") == "***"


@pytest.mark.parametrize(
    "token",
    [
        pytest.param(CHAVE_DO_MP, id="prefixo-test"),
        pytest.param(CHAVE_APP_USR, id="prefixo-app-usr"),
        pytest.param("APP_USR-12345678", id="app-usr-curto"),
    ],
)
def test_mascarar_pega_o_access_token_do_mercado_pago_mesmo_sem_registro(
    token: str,
) -> None:
    assert segredos.mascarar(f"token {token} fim") == "token *** fim"
    assert segredos.mascarar(f"Authorization: Bearer {token}") == (
        "Authorization: Bearer ***"
    )


@pytest.mark.parametrize(
    "texto",
    [
        pytest.param("SRV-TEST-12345678", id="no-meio-de-um-codigo"),
        pytest.param("PEC-E2E-3FA9C1-4", id="codigo-do-e2e"),
        pytest.param("TEST-curto", id="curto-demais"),
        pytest.param("o TEST de integracao", id="palavra-solta"),
    ],
)
def test_mascarar_nao_toca_em_texto_que_so_parece_token(texto: str) -> None:
    assert segredos.mascarar(texto) == texto


def test_registrados_lista_o_que_foi_registrado_e_esquecer_todos_zera() -> None:
    segredos.registrar("segredo-um-123\nsegredo-dois-456\nab")

    assert segredos.registrados() == frozenset({"segredo-um-123", "segredo-dois-456"})

    segredos.esquecer_todos()
    assert segredos.registrados() == frozenset()


def test_registrados_devolve_copia_que_nao_mexe_na_mascara() -> None:
    segredos.registrar("segredo-um-123")

    copia = segredos.registrados()

    assert isinstance(copia, frozenset)
    segredos.esquecer_todos()
    assert copia == frozenset({"segredo-um-123"})
