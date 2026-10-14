"""E-mails do Mailpit: o cliente do E2E le o link de decisao do orcamento aqui.

O Billing nao devolve o link na API; quem o entrega ao cliente e o e-mail do
``notificador`` do OS. O E2E faz o que o cliente faz: abre o e-mail e segue o
link.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from e2e.apoio.http import Cliente

_LINK_DE_DECISAO: Final = re.compile(
    r"https?://[^\s\"'<>]+/api/v1/publico/orcamentos/[A-Za-z0-9_.~-]+"
)
_CHECKOUT: Final = re.compile(r"https?://[^\s\"'<>]+/simulador/checkout/[^\s\"'<>]+")


def extrair_link_de_decisao(corpo: str) -> str | None:
    achado = _LINK_DE_DECISAO.search(corpo)
    return achado.group() if achado else None


def extrair_checkout(corpo: str) -> str | None:
    achado = _CHECKOUT.search(corpo)
    return achado.group() if achado else None


class Mailpit:
    """API v1 do Mailpit, por um port-forward do Service ``mailpit`` (8025)."""

    def __init__(self, http: Cliente) -> None:
        self._http = http

    def mensagens_para(self, destinatario: str) -> list[dict[str, Any]]:
        """Resumos das mensagens a ``destinatario``, da mais nova a mais antiga."""
        resposta = self._http.pedir(
            "GET",
            "/api/v1/search",
            params={"query": f"to:{destinatario}"},
            esperado=(200,),
        )
        mensagens: list[dict[str, Any]] = resposta.json().get("messages") or []
        return mensagens

    def texto(self, id_da_mensagem: str) -> str:
        resposta = self._http.pedir(
            "GET", f"/api/v1/message/{id_da_mensagem}", esperado=(200,)
        )
        return str(resposta.json().get("Text") or "")

    def link_de_decisao(self, destinatario: str) -> str | None:
        """Link do e-mail de orcamento mais novo para ``destinatario``, se ja chegou."""
        for mensagem in self.mensagens_para(destinatario):
            if "orçamento" in str(mensagem.get("Subject", "")).lower():
                link = extrair_link_de_decisao(self.texto(str(mensagem["ID"])))
                if link:
                    return link
        return None

    def assuntos(self, destinatario: str) -> list[str]:
        return [str(m.get("Subject", "")) for m in self.mensagens_para(destinatario)]
