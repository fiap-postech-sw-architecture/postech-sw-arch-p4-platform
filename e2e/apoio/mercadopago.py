"""Cliente do Mercado Pago da evidencia da sandbox: so leitura, com o token do ambiente.

Quem cria a preferencia, concilia e estorna e o Billing. Este cliente confere, do
lado do Mercado Pago, o que o Billing diz que fez: o pagamento aprovado, o estorno
e a preferencia expirada. Como o Access Token e uma credencial, tres regras valem
aqui: ele so existe no cabecalho do ``httpx.Client`` (nunca em atributo, em ``repr``
ou em mensagem de erro), o cliente nunca segue redirecionamento (um 3xx para outro
host levaria o cabecalho junto) e a verificacao do TLS fica ligada.

De cada resposta so entra o que o roteiro precisa; ``payer`` e cartao nem sao lidos.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any, Final

import httpx

from e2e.apoio.segredos import mascarar, registrar

if TYPE_CHECKING:
    from collections.abc import Mapping

URL_DA_API: Final = "https://api.mercadopago.com"
USER_AGENT: Final = "pytstop-e2e-sandbox/1.0 (fase 4 do PytStop; leitura)"
PRAZO: Final = 10.0
# O formato que o Billing aceita para id de pagamento e de preferencia: impede que
# um valor mude o caminho da URL (``../``, ``?``).
_ID_VALIDO: Final = re.compile(r"[A-Za-z0-9_-]{1,64}")
_TAMANHO_DO_DETALHE: Final = 300
# O id da preferencia vem como ``<collector_id>-<uuid>``: o numero e o User ID da conta
# vendedora, que nao vai para a evidencia (ela pode ir para um repositorio publico).
_PREFIXO_DA_CONTA: Final = re.compile(r"^\d{6,}-(?=[0-9a-fA-F]{8}-)")
# O Mercado Pago responde a data de expiracao com fuso (``-04:00``); a margem cobre
# a diferenca de relogio entre esta maquina e a dele.
MARGEM_DO_RELOGIO: Final = timedelta(minutes=5)


class ErroDoMercadoPagoError(AssertionError):
    """O Mercado Pago nao respondeu como o roteiro precisa (rede, status ou formato)."""

    def __init__(self, mensagem: str, *, status: int | None = None) -> None:
        super().__init__(mensagem)
        self.status = status


class TokenRecusadoError(ErroDoMercadoPagoError):
    """401 ou 403: o Mercado Pago nao aceita o Access Token."""


def _fora_do_formato(campo: str) -> ErroDoMercadoPagoError:
    return ErroDoMercadoPagoError(
        f"resposta do Mercado Pago fora do formato esperado: campo {campo}"
    )


def _texto(dados: Mapping[str, Any], campo: str) -> str:
    """Campo obrigatorio como texto (o id numerico do pagamento vira texto)."""
    valor = dados.get(campo)
    if isinstance(valor, bool) or not isinstance(valor, str | int) or valor == "":
        raise _fora_do_formato(campo)
    return str(valor)


def _texto_opcional(dados: Mapping[str, Any], campo: str) -> str | None:
    valor = dados.get(campo)
    return None if valor is None else str(valor)


def _dinheiro(dados: Mapping[str, Any], campo: str) -> Decimal | None:
    valor = dados.get(campo)
    if valor is None:
        return None
    if isinstance(valor, bool) or not isinstance(valor, int | Decimal):
        raise _fora_do_formato(campo)
    return Decimal(valor)


def _data(texto: str | None) -> datetime | None:
    """Data ISO 8601 com ou sem fuso (sem fuso vale UTC); ``None`` se nao le."""
    if texto is None:
        return None
    try:
        data = datetime.fromisoformat(texto)
    except ValueError:
        return None
    return data if data.tzinfo else data.replace(tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class PagamentoMp:
    """Um pagamento no Mercado Pago, so com o que a evidencia guarda."""

    id: str
    status: str
    status_detail: str | None
    valor: Decimal | None
    valor_estornado: Decimal
    moeda: str | None
    date_approved: str | None
    external_reference: str | None
    live_mode: bool | None

    @property
    def estornado(self) -> bool:
        """``refunded``, ou o valor estornado cobre o valor pago."""
        if self.status == "refunded":
            return True
        return (
            self.valor is not None
            and self.valor_estornado > 0
            and self.valor_estornado >= self.valor
        )

    def para_evidencia(self) -> dict[str, str | bool | None]:
        """Id, status, valor, moeda, ``date_approved`` e ``external_reference``.

        Mais ``live_mode``, que diz se o pagamento foi de verdade (``true``) ou
        de teste (``false``). Nenhum dado do pagador ou do cartao.
        """
        return {
            "id": self.id,
            "status": self.status,
            "transaction_amount": None if self.valor is None else str(self.valor),
            "currency_id": self.moeda,
            "date_approved": self.date_approved,
            "external_reference": self.external_reference,
            "live_mode": self.live_mode,
        }


def _pagamento(dados: object) -> PagamentoMp:
    if not isinstance(dados, dict):
        raise _fora_do_formato("(objeto)")
    live_mode = dados.get("live_mode")
    return PagamentoMp(
        id=_texto(dados, "id"),
        status=_texto(dados, "status"),
        status_detail=_texto_opcional(dados, "status_detail"),
        valor=_dinheiro(dados, "transaction_amount"),
        valor_estornado=_dinheiro(dados, "transaction_amount_refunded") or Decimal(0),
        moeda=_texto_opcional(dados, "currency_id"),
        date_approved=_texto_opcional(dados, "date_approved"),
        external_reference=_texto_opcional(dados, "external_reference"),
        live_mode=live_mode if isinstance(live_mode, bool) else None,
    )


@dataclass(frozen=True, slots=True)
class PreferenciaMp:
    """A preferencia do checkout: o id e a expiracao que o Billing pediu."""

    id: str
    expires: bool | None
    expira_em: datetime | None

    def expirada(self, agora: datetime) -> bool | None:
        """``True``/``False`` quando a resposta traz a expiracao; senao ``None``.

        ``None`` nao prova nada: o formato da resposta nao e o esperado, e a
        evidencia diz que a expiracao nao foi provada por esta consulta.
        """
        if self.expires is None or self.expira_em is None:
            return None
        return self.expires and self.expira_em <= agora + MARGEM_DO_RELOGIO

    def para_evidencia(self) -> dict[str, str | bool | None]:
        """O uuid da preferencia (sem o User ID da conta), ``expires`` e a expiracao."""
        return {
            "id": sem_id_da_conta(self.id),
            "expires": self.expires,
            "expiration_date_to": (
                None if self.expira_em is None else self.expira_em.isoformat()
            ),
        }


def _preferencia(dados: object) -> PreferenciaMp:
    if not isinstance(dados, dict):
        raise _fora_do_formato("(objeto)")
    expires = dados.get("expires")
    return PreferenciaMp(
        id=_texto(dados, "id"),
        expires=expires if isinstance(expires, bool) else None,
        expira_em=_data(_texto_opcional(dados, "expiration_date_to")),
    )


def _detalhe_do_erro(resposta: httpx.Response) -> str:
    """``message``, ``error`` e ``cause`` do JSON de erro do Mercado Pago.

    E o JSON de erro da API, sem dado do pagador. Corpo que nao e JSON nao e
    repetido: o que sobra e o tamanho do problema, nunca o texto.
    """
    try:
        corpo = json.loads(resposta.text)
    except ValueError:
        return "corpo sem JSON"
    if not isinstance(corpo, dict):
        return "corpo sem JSON"
    partes = [str(corpo[chave]) for chave in ("error", "message") if corpo.get(chave)]
    causas = corpo.get("cause")
    if isinstance(causas, list):
        partes.extend(
            f"{causa.get('code')}: {causa.get('description')}"
            for causa in causas[:3]
            if isinstance(causa, dict)
        )
    return mascarar("; ".join(partes) or "sem detalhe")[:_TAMANHO_DO_DETALHE]


def sem_id_da_conta(preferencia_id: str) -> str:
    """O uuid da preferencia, sem o ``<collector_id>-`` que vem na frente."""
    return _PREFIXO_DA_CONTA.sub("", preferencia_id, count=1)


def _caminho_sem_conta(caminho: str) -> str:
    """O caminho da URL com o id da preferencia sem o User ID da conta vendedora.

    E o que as mensagens de erro dizem: elas vao para o ``junit.xml`` e o
    ``cucumber.json``, que a varredura apaga se acha o prefixo.
    """
    inicio, barra, ultimo = caminho.rpartition("/")
    return f"{inicio}{barra}{sem_id_da_conta(ultimo)}"


def _id_valido(valor: str, rotulo: str) -> str:
    if not _ID_VALIDO.fullmatch(valor):
        msg = f"{rotulo} fora do formato aceito: {sem_id_da_conta(valor)[:20]!r}"
        raise ErroDoMercadoPagoError(msg)
    return valor


class ClienteMercadoPago:
    """Leituras no ``api.mercadopago.com``, com prazo e sem seguir redirecionamento."""

    def __init__(
        self, token: str, *, transporte: httpx.BaseTransport | None = None
    ) -> None:
        registrar(token)
        self._http = httpx.Client(
            base_url=URL_DA_API,
            timeout=PRAZO,
            follow_redirects=False,
            verify=True,
            transport=transporte,
            headers={
                "Authorization": f"Bearer {token}",
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
            },
        )

    def __repr__(self) -> str:
        return "ClienteMercadoPago()"

    def fechar(self) -> None:
        """Fecha as conexoes do cliente."""
        self._http.close()

    def _ler(self, caminho: str, **params: str) -> Any:  # JSON do provedor
        onde = _caminho_sem_conta(caminho)  # o que as mensagens dizem
        try:
            resposta = self._http.get(caminho, params=params or None)
        except httpx.HTTPError as erro:
            msg = f"sem resposta do Mercado Pago em {onde}: {type(erro).__name__}"
            raise ErroDoMercadoPagoError(msg) from None
        status = resposta.status_code
        if httpx.codes.is_redirect(status):
            msg = f"GET {onde}: redirecionamento {status} recusado (nunca se segue)"
            raise ErroDoMercadoPagoError(msg, status=status)
        if status in {httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN}:
            msg = (
                f"GET {onde}: HTTP {status}, o Mercado Pago não aceita o token "
                f"({_detalhe_do_erro(resposta)})"
            )
            raise TokenRecusadoError(msg, status=status)
        if not httpx.codes.is_success(status):
            msg = f"GET {onde}: HTTP {status} ({_detalhe_do_erro(resposta)})"
            raise ErroDoMercadoPagoError(msg, status=status)
        try:
            # parse_float=Decimal: o valor cobrado nunca passa por float.
            return json.loads(resposta.text, parse_float=Decimal)
        except (ValueError, InvalidOperation):
            msg = f"GET {onde}: o corpo da resposta não é JSON"
            raise ErroDoMercadoPagoError(msg, status=status) from None

    def pagamento(self, pagamento_id: str) -> PagamentoMp:
        """``GET /v1/payments/{id}``."""
        _id_valido(pagamento_id, "id do pagamento")
        return _pagamento(self._ler(f"/v1/payments/{pagamento_id}"))

    def buscar_por_referencia(self, referencia_externa: str) -> list[PagamentoMp]:
        """``GET /v1/payments/search?external_reference=``: as tentativas."""
        corpo = self._ler(
            "/v1/payments/search",
            external_reference=referencia_externa,
            sort="date_created",
            criteria="asc",
        )
        resultados = corpo.get("results") if isinstance(corpo, dict) else None
        if not isinstance(resultados, list):
            raise _fora_do_formato("results")
        return [_pagamento(item) for item in resultados]

    def preferencia(self, preferencia_id: str) -> PreferenciaMp:
        """``GET /checkout/preferences/{id}``."""
        _id_valido(preferencia_id, "id da preferencia")
        return _preferencia(self._ler(f"/checkout/preferences/{preferencia_id}"))

    def validar_token(self) -> None:
        """Falha com ``TokenRecusadoError`` se o Mercado Pago não aceita o token.

        Busca uma referencia que nao existe: a resposta e uma lista vazia, sem
        efeito e sem dado de ninguem.
        """
        self.buscar_por_referencia(str(uuid.uuid4()))
