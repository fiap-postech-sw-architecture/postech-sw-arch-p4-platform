"""Dados unicos de cada cenario: CPF, placa, codigos e e-mails."""

from __future__ import annotations

import random
import re

from e2e.apoio import dados


def _rng(semente: int) -> random.Random:
    return random.Random(semente)  # noqa: S311  # nosec B311


def _cpf_confere(cpf: str) -> bool:
    """Verificador independente do CPF (modulo 11), escrito a parte do gerador."""
    digitos = [int(c) for c in cpf]
    for n in (9, 10):
        soma = sum(d * p for d, p in zip(digitos[:n], range(n + 1, 1, -1), strict=True))
        if digitos[n] != (soma * 10 % 11) % 10:
            return False
    return len(cpf) == 11 and len(set(cpf)) > 1


def test_cpf_valido_passa_no_modulo_11_em_muitas_sementes() -> None:
    for semente in range(300):
        cpf = dados.cpf_valido(_rng(semente))
        assert _cpf_confere(cpf), cpf


def test_cpf_invalido_reprova_no_modulo_11_em_muitas_sementes() -> None:
    for semente in range(300):
        cpf = dados.cpf_invalido(_rng(semente))
        assert len(cpf) == 11
        assert not _cpf_confere(cpf), cpf


def test_cpf_valido_sorteia_de_novo_quando_a_base_tem_digitos_iguais() -> None:
    sorteios = iter([7] * 9 + [5, 2, 9, 9, 8, 2, 2, 4, 7])

    class Falso:
        def randrange(self, _: int) -> int:
            return next(sorteios)

    assert dados.cpf_valido(Falso()) == "52998224725"  # type: ignore[arg-type]


def test_cpf_conhecido_confere_com_o_verificador() -> None:
    assert _cpf_confere("52998224725")
    assert not _cpf_confere("52998224724")
    assert not _cpf_confere("11111111111")


def test_placa_mercosul_segue_o_padrao_e_nao_e_a_sentinela() -> None:
    for semente in range(200):
        placa = dados.placa_mercosul(_rng(semente))
        assert re.fullmatch(r"[A-Z]{3}\d[A-Z]\d{2}", placa)
        assert placa != "AAA0A00"


def test_placa_mercosul_descarta_a_sentinela() -> None:
    sorteios = iter(
        [
            *"AAA",  # letras
            0,
            *"A",
            0,  # 0A00 -> a sentinela
            *"BRA",
            2,
            *"E",
            19,
        ]
    )

    class Falso:
        def choice(self, _: str) -> str:
            return str(next(sorteios))

        def randrange(self, _: int) -> int:
            return int(next(sorteios))

    placa = dados.placa_mercosul(Falso())  # type: ignore[arg-type]  # falso de duas chamadas

    assert placa == "BRA2E19"


def test_codigo_segue_o_padrao_do_billing_e_do_estoque() -> None:
    padrao = r"^[A-Z0-9]+(?:-[A-Z0-9]+)*$"
    ident = dados.id_da_execucao()

    servico = dados.codigo("SRV", ident, 4)
    peca = dados.codigo("PEC", ident, 4)

    assert re.fullmatch(padrao, servico)
    assert re.fullmatch(padrao, peca)
    assert servico == f"SRV-E2E-{ident}-4"
    assert peca == f"PEC-E2E-{ident}-4"
    assert len(servico) <= 50


def test_id_da_execucao_tem_seis_hexadecimais_maiusculos() -> None:
    assert re.fullmatch(r"[0-9A-F]{6}", dados.id_da_execucao())


def test_emails_levam_a_execucao_e_o_numero() -> None:
    assert (
        dados.email_de_usuario("3FA9C1", "atendente")
        == "e2e-3fa9c1-atendente@e2e.pytstop.dev"
    )
    assert (
        dados.email_de_cliente("3FA9C1", 7) == "cliente-3fa9c1-7@clientes.pytstop.dev"
    )


def test_senha_aleatoria_tem_32_hexadecimais_e_muda() -> None:
    primeira, segunda = dados.senha_aleatoria(), dados.senha_aleatoria()

    assert re.fullmatch(r"[0-9a-f]{32}", primeira)
    assert primeira != segunda
