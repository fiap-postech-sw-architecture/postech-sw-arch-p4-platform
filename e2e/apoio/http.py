"""Cliente HTTP do E2E: TLS so para localhost, 429 com espera e erro sem segredo.

Atras do Kong todo cliente do kind tem o mesmo IP, e o OS limita login e
registro a 5 por minuto por processo: duas sessoes seguidas podem receber 429.
O cliente espera a janela passar (``espera_429``) em vez de reprovar um cenario
que nada tem a ver com o limite.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import urlsplit

import httpx

from e2e.apoio.segredos import mascarar

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

HOSTS_SEM_VERIFICACAO: Final = frozenset({"localhost", "127.0.0.1", "::1"})
_TAMANHO_DO_CORPO_NO_ERRO: Final = 400
# Retry-After 0 (ou negativo) nao pode virar um laco sem pausa contra o Kong.
PISO_DA_ESPERA_429: Final = 1.0


class RespostaInesperadaError(AssertionError):
    """A API respondeu com um status que o cenario nao esperava."""


def verificar_tls(url_base: str) -> bool:
    """``False`` (aceita o certificado autoassinado do Kong) so para localhost."""
    return urlsplit(url_base).hostname not in HOSTS_SEM_VERIFICACAO


class Cliente:
    """``httpx.Client`` com prazo, espera de 429 e erros que nao vazam credencial."""

    def __init__(
        self,
        url_base: str,
        *,
        transporte: httpx.BaseTransport | None = None,
        prazo: float = 15.0,
        espera_429: float = 70.0,
        intervalo_429: float = 5.0,
        relogio: Callable[[], float] = time.monotonic,
        dormir: Callable[[float], None] = time.sleep,
    ) -> None:
        self._http = httpx.Client(
            base_url=url_base,
            verify=verificar_tls(url_base),
            timeout=prazo,
            transport=transporte,
        )
        self._espera_429 = espera_429
        self._intervalo_429 = intervalo_429
        self._relogio = relogio
        self._dormir = dormir

    def fechar(self) -> None:
        self._http.close()

    def pedir(
        self,
        metodo: str,
        caminho: str,
        *,
        token: str | None = None,
        json: Any = None,
        params: dict[str, Any] | None = None,
        esperado: Iterable[int] | None = None,
    ) -> httpx.Response:
        """Faz o pedido; ``esperado`` lista os status aceitos (outro reprova)."""
        cabecalhos = {"Authorization": f"Bearer {token}"} if token else {}
        limite = self._relogio() + self._espera_429
        while True:
            resposta = self._http.request(
                metodo, caminho, headers=cabecalhos, json=json, params=params
            )
            if resposta.status_code != httpx.codes.TOO_MANY_REQUESTS:
                break
            restante = limite - self._relogio()
            if restante <= 0:
                break
            self._dormir(min(_espera_pedida(resposta, self._intervalo_429), restante))
        if esperado is not None and resposta.status_code not in set(esperado):
            raise RespostaInesperadaError(
                descrever(metodo, caminho, resposta, esperado)
            )
        return resposta


def _espera_pedida(resposta: httpx.Response, padrao: float) -> float:
    """Segundos do ``Retry-After``, ou ``padrao`` se nao ha (ou nao e numero)."""
    try:
        return max(float(resposta.headers["retry-after"]), PISO_DA_ESPERA_429)
    except (KeyError, ValueError):
        return padrao


def descrever(
    metodo: str, caminho: str, resposta: httpx.Response, esperado: Iterable[int]
) -> str:
    """Erro com status, ``X-Request-ID`` e o inicio do corpo, tudo mascarado."""
    # Mascara o corpo inteiro e so entao corta: um JWT cortado ao meio escaparia.
    corpo = mascarar(resposta.text)[:_TAMANHO_DO_CORPO_NO_ERRO]
    pedido = resposta.headers.get("x-request-id", "-")
    texto = (
        f"{metodo} {caminho}: HTTP {resposta.status_code} (esperado "
        f"{sorted(set(esperado))}; X-Request-ID {pedido}): {corpo}"
    )
    return mascarar(texto)
