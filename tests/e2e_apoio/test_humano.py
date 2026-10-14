"""O que depende de uma pessoa: o quadro de instrucoes e a espera pelo pagamento."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx
import pytest

from e2e.apoio.espera import TempoEsgotadoError
from e2e.apoio.http import RespostaInesperadaError
from e2e.apoio.humano import (
    AVISO_A_CADA,
    CARTAO_DE_TESTE,
    PRAZO_DO_PAGAMENTO,
    CobrancaEncerradaError,
    esperar_pagamento,
    formatar_restante,
    instrucoes_de_pagamento,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from e2e_apoio.falsos import Relogio

LINK = "https://www.mercadopago.com.br/checkout/v1/redirect?pref_id=123-abc"


@pytest.mark.parametrize(
    ("segundos", "texto"),
    [
        (900, "15 min 00 s"),
        (845.4, "14 min 05 s"),
        (60, "1 min 00 s"),
        (59.9, "59 s"),
        (45, "45 s"),
        (0, "0 s"),
        (-3, "0 s"),
    ],
)
def test_formatar_restante(segundos: float, texto: str) -> None:
    assert formatar_restante(segundos) == texto


def test_instrucoes_dizem_janela_anonima_comprador_link_cartao_e_prazo() -> None:
    quadro = instrucoes_de_pagamento(
        link=LINK, valor="210.00", moeda="BRL", numero=1, total=2
    )

    assert "PAGAMENTO 1 de 2" in quadro
    assert "sem dinheiro de verdade" in quadro
    assert "Valor: BRL 210.00" in quadro
    assert "JANELA ANÔNIMA" in quadro
    assert "COMPRADOR de teste" in quadro
    assert "código de verificação" in quadro
    assert "6 últimos dígitos do User ID" in quadro
    assert f"     {LINK}" in quadro
    assert CARTAO_DE_TESTE in quadro
    assert "5480 8328 0103 3311" in quadro
    assert "nome do titular APRO" in quadro
    assert "até 30 s" in quadro
    assert f"Você tem {int(PRAZO_DO_PAGAMENTO // 60)} min" in quadro
    assert "Ctrl-C" in quadro
    assert quadro.splitlines()[0] == quadro.splitlines()[-1]


def _leitor(*estados: Mapping[str, Any] | Exception) -> Callable[[], Mapping[str, Any]]:
    fila = iter(estados)

    def ler() -> Mapping[str, Any]:
        estado = next(fila)
        if isinstance(estado, Exception):
            raise estado
        return estado

    return ler


def _esperar(
    ler: Callable[[], Mapping[str, Any]],
    relogio: Relogio,
    avisos: list[str],
    **opcoes: Any,
) -> Mapping[str, Any]:
    return esperar_pagamento(
        ler,
        prazo=opcoes.pop("prazo", 900.0),
        intervalo=opcoes.pop("intervalo", 5.0),
        max_recusas=3,
        avisar=avisos.append,
        relogio=relogio,
        dormir=relogio.dormir,
        **opcoes,
    )


def test_pagamento_ja_confirmado_volta_na_primeira_leitura(relogio: Relogio) -> None:
    avisos: list[str] = []

    pagamento = _esperar(
        _leitor({"status": "CONFIRMADO", "referencia_pagamento": "999"}),
        relogio,
        avisos,
    )

    assert pagamento["referencia_pagamento"] == "999"
    assert relogio.dormidas == []
    assert avisos == []


def test_espera_o_pagamento_com_contagem_regressiva_a_cada_30_segundos(
    relogio: Relogio,
) -> None:
    avisos: list[str] = []
    ainda = {"status": "SOLICITADO", "recusas": 0}
    estados = [ainda] * 13 + [{"status": "CONFIRMADO", "referencia_pagamento": "999"}]

    pagamento = _esperar(_leitor(*estados), relogio, avisos)

    assert pagamento["status"] == "CONFIRMADO"
    assert relogio.dormidas == [5.0] * 13
    # Um aviso na primeira pausa e outro a cada 30 s (a cada 6 leituras de 5 s).
    assert len(avisos) == 3
    assert avisos[0].startswith("aguardando o pagamento: restam 15 min 00 s")
    assert "(Billing: SOLICITADO, recusas 0 de 3)" in avisos[0]
    assert avisos[1].startswith("aguardando o pagamento: restam 14 min 30 s")
    assert avisos[2].startswith("aguardando o pagamento: restam 14 min 00 s")
    assert AVISO_A_CADA == 30.0


def test_recusa_ja_presente_na_primeira_leitura_e_avisada(relogio: Relogio) -> None:
    # Voltando de uma espera anterior, a primeira leitura ja pode ter uma recusa.
    avisos: list[str] = []
    estados = [
        {"status": "SOLICITADO", "recusas": 1},
        {"status": "CONFIRMADO", "recusas": 1, "referencia_pagamento": "999"},
    ]

    _esperar(_leitor(*estados), relogio, avisos)

    recusas = [aviso for aviso in avisos if "recusou a tentativa de pagamento" in aviso]
    assert len(recusas) == 1
    assert "(1 de 3)" in recusas[0]


def test_cada_tentativa_recusada_e_avisada_quando_aparece(relogio: Relogio) -> None:
    avisos: list[str] = []
    estados = [
        {"status": "SOLICITADO", "recusas": 0},
        {"status": "SOLICITADO", "recusas": 1},
        {"status": "SOLICITADO", "recusas": 1},
        {"status": "SOLICITADO", "recusas": 2},
        {"status": "CONFIRMADO", "recusas": 2, "referencia_pagamento": "999"},
    ]

    _esperar(_leitor(*estados), relogio, avisos)

    recusas = [a for a in avisos if "recusou a tentativa" in a]
    assert len(recusas) == 2
    assert "(1 de 3)" in recusas[0]
    assert "(2 de 3)" in recusas[1]
    assert "APRO aprova" in recusas[0]


@pytest.mark.parametrize("status", ["RECUSADO", "EXPIRADO", "CANCELADO", "ESTORNADO"])
def test_cobranca_encerrada_sem_pagamento_reprova_na_hora(
    status: str, relogio: Relogio
) -> None:
    avisos: list[str] = []
    ler = _leitor({"status": status, "recusas": 3, "motivo": "recusas_esgotadas"})

    with pytest.raises(CobrancaEncerradaError) as erro:
        _esperar(ler, relogio, avisos)

    texto = str(erro.value)
    assert f"terminou {status} sem ser paga" in texto
    assert "motivo: recusas_esgotadas" in texto
    assert "recusas: 3 de 3" in texto
    assert relogio.dormidas == []


def test_prazo_esgotado_diz_a_espera_e_o_ultimo_valor(relogio: Relogio) -> None:
    avisos: list[str] = []
    ler = _leitor(*[{"status": "SOLICITADO", "recusas": 0}] * 10)

    with pytest.raises(
        TempoEsgotadoError,
        match=r"pagamento CONFIRMADO no Billing: nao ocorreu em 20 s",
    ):
        _esperar(ler, relogio, avisos, prazo=20.0, intervalo=5.0)

    assert avisos[0].startswith("aguardando o pagamento: restam 20 s")


def test_falha_de_rede_ou_resposta_inesperada_contam_como_ainda_nao(
    relogio: Relogio,
) -> None:
    avisos: list[str] = []
    ler = _leitor(
        httpx.ConnectError("api reiniciando"),
        RespostaInesperadaError("HTTP 503"),
        {"status": "CONFIRMADO", "recusas": 0},
    )

    assert _esperar(ler, relogio, avisos)["status"] == "CONFIRMADO"
    assert relogio.dormidas == [5.0, 5.0]


def test_pagamento_sem_o_campo_recusas_conta_zero(relogio: Relogio) -> None:
    avisos: list[str] = []

    _esperar(_leitor({"status": "CONFIRMADO"}), relogio, avisos)

    assert avisos == []
