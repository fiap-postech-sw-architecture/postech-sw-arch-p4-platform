"""Comparacao de texto sem acento nem caixa."""

from __future__ import annotations

import pytest

from e2e.apoio.texto import sem_acentos


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        (
            "Cancelamento recusado: execução já iniciada",
            "cancelamento recusado: execucao ja iniciada",
        ),
        ("Orçamento", "orcamento"),
        ("sem acento", "sem acento"),
    ],
)
def test_sem_acentos_tira_diacriticos_e_caixa(entrada: str, esperado: str) -> None:
    assert sem_acentos(entrada) == esperado


def test_sem_acentos_compara_mensagem_acentuada_com_a_da_spec() -> None:
    assert sem_acentos("Execução JÁ iniciada") == sem_acentos("execucao ja iniciada")
