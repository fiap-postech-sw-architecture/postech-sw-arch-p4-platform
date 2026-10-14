"""O que o Mercado Pago tem de dizer em cada cenario do sandbox.

Cada funcao compara o que o Mercado Pago respondeu com o que o Billing diz que
fez, e reprova com uma frase que aponta a divergencia. Nenhuma repete dado do
pagador: a resposta ja chega aqui so com os campos da lista.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from e2e.apoio.mercadopago import PagamentoMp, PreferenciaMp

APROVADO: Final = "approved"


class DivergenciaComOMercadoPagoError(AssertionError):
    """O Mercado Pago e o Billing nao contam a mesma historia."""


def _mesmo_valor(mp: Decimal | None, billing: str) -> bool:
    try:
        return mp is not None and mp == Decimal(billing)
    except InvalidOperation:
        return False


def conferir_aprovado(
    mp: PagamentoMp, *, pagamento_id: str, valor: str, moeda: str
) -> str | None:
    """Aprovado, desta cobranca, no valor e na moeda do orcamento, e de teste.

    Reprova a divergencia. ``None`` se tudo confere; senao, o motivo pelo qual a
    consulta nao prova que o pagamento e de teste: sem ``live_mode`` na resposta
    (ou nao booleano) nao ha o que afirmar, e e a unica barreira contra um token
    de producao (o prefixo do token nao distingue).
    """
    problemas = []
    if mp.status != APROVADO:
        problemas.append(
            f"o status no Mercado Pago é {mp.status!r} ({mp.status_detail}), "
            f"e o esperado era {APROVADO!r}"
        )
    if mp.external_reference != pagamento_id:
        problemas.append(
            "o external_reference do pagamento no Mercado Pago "
            f"({mp.external_reference}) não é o pagamento_id do Billing "
            f"({pagamento_id})"
        )
    if not _mesmo_valor(mp.valor, valor):
        problemas.append(
            f"o valor no Mercado Pago é {mp.valor} e o do orçamento é {valor}"
        )
    if mp.moeda != moeda:
        problemas.append(f"a moeda no Mercado Pago é {mp.moeda} e a esperada, {moeda}")
    if mp.live_mode is True:
        problemas.append(
            "o pagamento é de PRODUÇÃO (live_mode=true): o token não é de teste e "
            "o valor foi cobrado de verdade. Estorne pelo painel do Mercado Pago e "
            "troque as credenciais"
        )
    if problemas:
        raise DivergenciaComOMercadoPagoError("; ".join(problemas))
    if mp.live_mode is None:
        return (
            "a resposta do Mercado Pago não trouxe `live_mode` (ou não é verdadeiro "
            "ou falso): a natureza de teste do pagamento NÃO foi provada pela "
            "consulta. Confira no painel do vendedor de teste que o pagamento é de "
            "teste."
        )
    return None


def conferir_estornado(mp: PagamentoMp) -> None:
    """Estornado: ``refunded``, ou o valor estornado cobre o valor pago."""
    if not mp.estornado:
        msg = (
            f"o pagamento {mp.id} não aparece estornado no Mercado Pago: status "
            f"{mp.status!r} ({mp.status_detail}), estornado {mp.valor_estornado} "
            f"de {mp.valor}"
        )
        raise DivergenciaComOMercadoPagoError(msg)


def conferir_preferencia_expirada(
    preferencia: PreferenciaMp, *, agora: datetime | None = None
) -> str | None:
    """``None`` se a preferencia esta expirada; senao, por que a consulta nao prova.

    Reprova quando a resposta diz que a preferencia NAO expirou (o ``PUT`` do
    Billing nao valeu). Quando a resposta nao traz a expiracao no formato
    esperado, nao ha o que afirmar: devolve o motivo, e a evidencia registra que
    esta prova ficou so no log e na metrica do Billing.
    """
    expirada = preferencia.expirada(agora or datetime.now(UTC))
    if expirada is None:
        return (
            "a consulta da preferência não trouxe `expires` e `expiration_date_to` "
            "no formato esperado: a expiração NÃO foi provada por ela (veja o log do "
            "consumidor e a métrica "
            '`pytstop_mercadopago_requisicoes_total{operacao="cancelar_cobranca"}`)'
        )
    if not expirada:
        msg = (
            f"a preferência {preferencia.id} não está expirada no Mercado Pago "
            f"(expires={preferencia.expires}, "
            f"expiration_date_to={preferencia.expira_em}): "
            "o `PUT /checkout/preferences/{id}` do Billing não valeu"
        )
        raise DivergenciaComOMercadoPagoError(msg)
    return None
