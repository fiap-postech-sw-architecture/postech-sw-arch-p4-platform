"""Espera por polling com prazo e a prova de que uma condicao segue valendo."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from e2e.apoio import segredos
from e2e.apoio.espera import TempoEsgotadoError, esperar, manter

if TYPE_CHECKING:
    from collections.abc import Iterator

    from e2e_apoio.falsos import Relogio


def test_esperar_condicao_pronta_devolve_sem_dormir(relogio: Relogio) -> None:
    resultado = esperar(
        lambda: "pronto",
        prazo=10,
        descricao="x",
        relogio=relogio,
        dormir=relogio.dormir,
    )

    assert resultado == "pronto"
    assert relogio.dormidas == []


def test_esperar_devolve_o_primeiro_valor_verdadeiro(relogio: Relogio) -> None:
    respostas = iter([None, 0, "", {"ok": 1}, "nunca"])

    resultado = esperar(
        lambda: next(respostas),
        prazo=10,
        intervalo=2,
        descricao="x",
        relogio=relogio,
        dormir=relogio.dormir,
    )

    assert resultado == {"ok": 1}
    assert relogio.dormidas == [2, 2, 2]


def test_esperar_prazo_esgotado_reprova_com_descricao_e_ultimo_valor(
    relogio: Relogio,
) -> None:
    with pytest.raises(TempoEsgotadoError) as erro:
        esperar(
            lambda: [],
            prazo=5,
            intervalo=2,
            descricao="OS em aguardando_pagamento",
            relogio=relogio,
            dormir=relogio.dormir,
        )

    assert "OS em aguardando_pagamento" in str(erro.value)
    assert "5 s" in str(erro.value)
    assert "ultimo valor: []" in str(erro.value)


def test_esperar_nunca_dorme_alem_do_prazo(relogio: Relogio) -> None:
    with pytest.raises(TempoEsgotadoError):
        esperar(
            lambda: False,
            prazo=5,
            intervalo=2,
            descricao="x",
            relogio=relogio,
            dormir=relogio.dormir,
        )

    # 2 + 2 + 1: a ultima soneca e cortada no que resta do prazo.
    assert relogio.dormidas == [2, 2, 1]
    assert relogio.agora == 105.0


def test_esperar_avalia_uma_ultima_vez_no_fim_do_prazo(relogio: Relogio) -> None:
    chamadas: list[float] = []

    def condicao() -> bool:
        chamadas.append(relogio.agora)
        return relogio.agora >= 105.0

    assert esperar(
        condicao,
        prazo=5,
        intervalo=2,
        descricao="x",
        relogio=relogio,
        dormir=relogio.dormir,
    )
    assert chamadas[-1] == 105.0


def test_esperar_prazo_zero_ainda_avalia_uma_vez(relogio: Relogio) -> None:
    chamadas = []

    def condicao() -> bool:
        chamadas.append(1)
        return False

    with pytest.raises(TempoEsgotadoError):
        esperar(
            condicao, prazo=0, descricao="x", relogio=relogio, dormir=relogio.dormir
        )

    assert len(chamadas) == 1
    assert relogio.dormidas == []


def test_esperar_ignora_so_as_excecoes_listadas(relogio: Relogio) -> None:
    tentativas: Iterator[Exception | str] = iter(
        [ConnectionError("reset"), ConnectionError("reset"), "ok"]
    )

    def condicao() -> str:
        item = next(tentativas)
        if isinstance(item, Exception):
            raise item
        return item

    resultado = esperar(
        condicao,
        prazo=10,
        ignorar=(ConnectionError,),
        descricao="x",
        relogio=relogio,
        dormir=relogio.dormir,
    )

    assert resultado == "ok"


def test_esperar_excecao_nao_listada_propaga(relogio: Relogio) -> None:
    def condicao() -> bool:
        raise KeyError("bug")

    with pytest.raises(KeyError):
        esperar(
            condicao,
            prazo=10,
            ignorar=(ConnectionError,),
            descricao="x",
            relogio=relogio,
            dormir=relogio.dormir,
        )


def test_esperar_excecao_ignorada_aparece_na_mensagem_do_prazo(
    relogio: Relogio,
) -> None:
    def condicao() -> bool:
        raise ConnectionError("conexao recusada")

    with pytest.raises(TempoEsgotadoError, match="ConnectionError: conexao recusada"):
        esperar(
            condicao,
            prazo=2,
            ignorar=(ConnectionError,),
            descricao="x",
            relogio=relogio,
            dormir=relogio.dormir,
        )


def test_esperar_mensagem_de_prazo_sai_mascarada(relogio: Relogio) -> None:
    segredos.registrar("senha-super-secreta")

    def condicao() -> bool:
        raise ConnectionError("recusou a senha-super-secreta")

    with pytest.raises(TempoEsgotadoError) as erro:
        esperar(
            condicao,
            prazo=1,
            ignorar=(ConnectionError,),
            descricao="x",
            relogio=relogio,
            dormir=relogio.dormir,
        )

    assert "senha-super-secreta" not in str(erro.value)
    assert "recusou a ***" in str(erro.value)


def test_manter_condicao_sempre_verdadeira_dura_a_janela_inteira(
    relogio: Relogio,
) -> None:
    amostras = []

    def condicao() -> bool:
        amostras.append(relogio.agora)
        return True

    manter(
        condicao,
        duracao=20,
        intervalo=5,
        descricao="x",
        relogio=relogio,
        dormir=relogio.dormir,
    )

    assert amostras == [100.0, 105.0, 110.0, 115.0, 120.0]
    assert relogio.agora == 120.0


def test_manter_corta_a_ultima_soneca_no_fim_da_janela(relogio: Relogio) -> None:
    manter(
        lambda: True,
        duracao=7,
        intervalo=5,
        descricao="x",
        relogio=relogio,
        dormir=relogio.dormir,
    )

    assert relogio.dormidas == [5, 2]


def test_manter_mensagem_de_falha_sai_mascarada(relogio: Relogio) -> None:
    segredos.registrar("senha-do-admin-123")

    with pytest.raises(TempoEsgotadoError) as erro:
        manter(
            lambda: False,
            duracao=20,
            descricao="login com senha-do-admin-123",
            relogio=relogio,
            dormir=relogio.dormir,
        )

    assert "senha-do-admin-123" not in str(erro.value)
    assert "login com ***" in str(erro.value)


def test_manter_reprova_assim_que_a_condicao_deixa_de_valer(relogio: Relogio) -> None:
    estados = iter([True, True, False])

    with pytest.raises(TempoEsgotadoError, match="deixou de valer antes de 20 s"):
        manter(
            lambda: next(estados),
            duracao=20,
            intervalo=5,
            descricao="OS parada",
            relogio=relogio,
            dormir=relogio.dormir,
        )

    assert relogio.agora == 110.0


def test_esperar_avisa_o_progresso_antes_de_cada_pausa(relogio: Relogio) -> None:
    visto: list[tuple[float, object]] = []
    respostas = iter([None, "", 0, "pronto"])

    resultado = esperar(
        lambda: next(respostas),
        prazo=10,
        intervalo=2,
        descricao="x",
        progresso=lambda restante, ultimo: visto.append((restante, ultimo)),
        relogio=relogio,
        dormir=relogio.dormir,
    )

    assert resultado == "pronto"
    assert visto == [(10.0, None), (8.0, ""), (6.0, 0)]
    assert relogio.dormidas == [2, 2, 2]


def test_esperar_sem_progresso_nem_ve_o_gancho(relogio: Relogio) -> None:
    resultado = esperar(
        lambda: "pronto",
        prazo=10,
        descricao="x",
        progresso=lambda *_: pytest.fail("nao devia avisar"),  # pragma: no cover
        relogio=relogio,
        dormir=relogio.dormir,
    )

    assert resultado == "pronto"


def test_esperar_nao_avisa_progresso_quando_o_prazo_acabou(relogio: Relogio) -> None:
    visto: list[float] = []

    with pytest.raises(TempoEsgotadoError):
        esperar(
            lambda: None,
            prazo=4,
            intervalo=2,
            descricao="x",
            progresso=lambda restante, _: visto.append(restante),
            relogio=relogio,
            dormir=relogio.dormir,
        )

    assert visto == [4.0, 2.0]
