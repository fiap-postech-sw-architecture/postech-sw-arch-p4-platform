"""Mascara de segredos: o que o runner registra e os padroes de credencial."""

from __future__ import annotations

import sys

import pytest

from e2e.apoio import segredos


def test_mascarar_troca_segredo_registrado() -> None:
    segredos.registrar("abcdef123456")

    assert segredos.mascarar("senha=abcdef123456 fim") == "senha=*** fim"


def test_mascarar_valor_curto_nao_e_registrado() -> None:
    segredos.registrar("abc")

    assert segredos.mascarar("abc abc") == "abc abc"


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
        (
            "https://localhost/billing/api/v1/publico/orcamentos/abc.123.XYZ-_/decisao",
            "https://localhost/billing/api/v1/publico/orcamentos/***/decisao",
        ),
        (
            "POST /billing/api/v1/publico/orcamentos/tok.en-1_2",
            "POST /billing/api/v1/publico/orcamentos/***",
        ),
        (
            "https://localhost/billing/simulador/checkout/84ea5cc1?token=abc123&x=1",
            "https://localhost/billing/simulador/checkout/84ea5cc1?token=***&x=1",
        ),
        ("/aprovar?token=segredo", "/aprovar?token=***"),
        ("Authorization: Bearer abc.def-ghi", "Authorization: Bearer ***"),
        (
            "token eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiIxIn0.c2ln fim",
            "token *** fim",
        ),
        ("sem credencial nenhuma", "sem credencial nenhuma"),
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
