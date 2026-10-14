"""O que o Mercado Pago tem de dizer: aprovado, estornado e a preferencia expirada."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from e2e.apoio.conferencias import (
    DivergenciaComOMercadoPagoError,
    conferir_aprovado,
    conferir_estornado,
    conferir_preferencia_expirada,
)
from e2e.apoio.evidencia import varrer
from e2e.apoio.mercadopago import MARGEM_DO_RELOGIO, PagamentoMp, PreferenciaMp

AGORA = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)


def _mp(**campos: Any) -> PagamentoMp:
    base: dict[str, Any] = {
        "id": "999",
        "status": "approved",
        "status_detail": "accredited",
        "valor": Decimal("210.0"),
        "valor_estornado": Decimal(0),
        "moeda": "BRL",
        "date_approved": "2026-10-20T08:00:00.000-04:00",
        "external_reference": "p-1",
        "live_mode": False,
    }
    return PagamentoMp(**{**base, **campos})


def _confere(mp: PagamentoMp) -> str | None:
    return conferir_aprovado(mp, pagamento_id="p-1", valor="210.00", moeda="BRL")


def test_aprovado_desta_cobranca_no_valor_e_de_teste_passa_sem_ressalva() -> None:
    assert _confere(_mp()) is None


def test_live_mode_ausente_nao_prova_que_o_pagamento_e_de_teste() -> None:
    # A unica barreira contra um token de producao e o live_mode da resposta: sem ele
    # a consulta nao prova nada, e a evidencia tem de dizer isso.
    motivo = _confere(_mp(live_mode=None))

    assert motivo is not None
    assert "não trouxe `live_mode`" in motivo
    assert "NÃO foi provada pela consulta" in motivo


def test_divergencia_vale_mais_que_a_ressalva_do_live_mode() -> None:
    with pytest.raises(DivergenciaComOMercadoPagoError, match="rejected"):
        _confere(_mp(status="rejected", live_mode=None))


@pytest.mark.parametrize(
    ("troca", "trecho"),
    [
        pytest.param(
            {"status": "rejected", "status_detail": "cc_rejected_other_reason"},
            r"status no Mercado Pago é 'rejected' \(cc_rejected_other_reason\)",
            id="status",
        ),
        pytest.param(
            {"external_reference": "outro"},
            "external_reference .* não é o pagamento_id",
            id="referencia",
        ),
        pytest.param(
            {"external_reference": None},
            "external_reference .*None",
            id="sem-referencia",
        ),
        pytest.param(
            {"valor": Decimal("100.00")},
            "valor no Mercado Pago é 100.00 e o do orçamento é 210.00",
            id="valor",
        ),
        pytest.param({"valor": None}, "valor no Mercado Pago é None", id="sem-valor"),
        pytest.param(
            {"moeda": "USD"},
            "moeda no Mercado Pago é USD e a esperada, BRL",
            id="moeda",
        ),
        pytest.param({"live_mode": True}, "PRODUÇÃO .live_mode=true.", id="producao"),
    ],
)
def test_cada_divergencia_reprova_dizendo_qual(
    troca: dict[str, Any], trecho: str
) -> None:
    with pytest.raises(DivergenciaComOMercadoPagoError, match=trecho):
        _confere(_mp(**troca))


def test_valor_do_orcamento_ilegivel_e_divergencia_e_nao_excecao_estranha() -> None:
    with pytest.raises(
        DivergenciaComOMercadoPagoError, match="o do orçamento é muitos"
    ):
        conferir_aprovado(_mp(), pagamento_id="p-1", valor="muitos", moeda="BRL")


def test_varias_divergencias_aparecem_na_mesma_mensagem() -> None:
    with pytest.raises(DivergenciaComOMercadoPagoError) as erro:
        _confere(_mp(status="pending", moeda="USD"))

    assert "status no Mercado Pago" in str(erro.value)
    assert "moeda no Mercado Pago" in str(erro.value)


def test_pagamento_de_producao_manda_estornar_e_trocar_as_credenciais() -> None:
    with pytest.raises(DivergenciaComOMercadoPagoError) as erro:
        _confere(_mp(live_mode=True))

    assert "valor foi cobrado de verdade" in str(erro.value)
    assert "troque as credenciais" in str(erro.value)


def test_estornado_pelo_status_ou_pelo_valor_passa() -> None:
    conferir_estornado(_mp(status="refunded", status_detail="refunded"))
    conferir_estornado(_mp(valor_estornado=Decimal("210.00")))


def test_nao_estornado_diz_o_que_o_mercado_pago_mostra() -> None:
    with pytest.raises(DivergenciaComOMercadoPagoError) as erro:
        conferir_estornado(_mp(valor_estornado=Decimal("10.00")))

    texto = str(erro.value)
    assert "pagamento 999 não aparece estornado" in texto
    assert "status 'approved' (accredited)" in texto
    assert "estornado 10.00 de 210.0" in texto


def _preferencia(expires: bool | None, expira_em: datetime | None) -> PreferenciaMp:
    return PreferenciaMp(id="123-abc", expires=expires, expira_em=expira_em)


def test_preferencia_expirada_passa_sem_ressalva() -> None:
    passada = AGORA - timedelta(minutes=2)

    assert (
        conferir_preferencia_expirada(_preferencia(True, passada), agora=AGORA) is None
    )


def test_preferencia_ainda_valida_reprova_dizendo_que_o_put_nao_valeu() -> None:
    futura = AGORA + MARGEM_DO_RELOGIO + timedelta(minutes=50)

    with pytest.raises(DivergenciaComOMercadoPagoError) as erro:
        conferir_preferencia_expirada(_preferencia(True, futura), agora=AGORA)

    assert "preferência 123-abc não está expirada" in str(erro.value)
    assert "PUT /checkout/preferences" in str(erro.value)


def test_a_mensagem_da_preferencia_nao_expirada_nao_leva_o_user_id_da_conta() -> None:
    # O id que o Billing guarda e <User ID da vendedora>-<uuid>; a mensagem vai para o
    # junit.xml, e a varredura apagaria o arquivo ao achar o prefixo.
    uuid = "c5ca3674-5b81-4eef-bfb1-b4bfdccfa6b6"
    preferencia = PreferenciaMp(
        id=f"1462278261-{uuid}", expires=True, expira_em=AGORA + timedelta(days=30)
    )

    with pytest.raises(DivergenciaComOMercadoPagoError) as erro:
        conferir_preferencia_expirada(preferencia, agora=AGORA)

    assert uuid in str(erro.value)
    assert "1462278261" not in str(erro.value)
    assert varrer(str(erro.value)) == []


def test_preferencia_que_diz_expires_falso_reprova() -> None:
    with pytest.raises(DivergenciaComOMercadoPagoError, match="expires=False"):
        conferir_preferencia_expirada(_preferencia(False, AGORA), agora=AGORA)


@pytest.mark.parametrize(
    ("expires", "expira_em"),
    [
        pytest.param(None, None, id="sem-nenhum-dos-campos"),
        pytest.param(True, None, id="sem-a-data"),
        pytest.param(None, AGORA, id="sem-a-flag"),
    ],
)
def test_resposta_sem_os_campos_nao_prova_e_diz_onde_ver(
    expires: bool | None, expira_em: datetime | None
) -> None:
    motivo = conferir_preferencia_expirada(
        _preferencia(expires, expira_em), agora=AGORA
    )

    assert motivo is not None
    assert "NÃO foi provada" in motivo
    assert 'operacao="cancelar_cobranca"' in motivo


def test_sem_agora_usa_o_relogio_de_verdade() -> None:
    passada = datetime.now(UTC) - timedelta(hours=1)

    assert conferir_preferencia_expirada(_preferencia(True, passada)) is None
