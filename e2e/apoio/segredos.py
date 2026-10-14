"""Mascara de segredos: nada que seja credencial chega ao log, ao junit ou ao resumo.

Dois niveis. Os valores que o runner conhece (a senha do admin, as senhas e os
tokens que ele gera) sao registrados e trocados por ``***`` onde aparecerem. Os
que ele nao conhece de antemao (token do link de decisao, ``token=`` do
checkout, JWT, cabecalho ``Authorization``) saem por padrao de texto.
"""

from __future__ import annotations

import os
import re
import sys
from typing import Final

MASCARA: Final = "***"
# Abaixo disto o valor casaria com texto comum e estragaria a leitura do log.
_TAMANHO_MINIMO: Final = 6

_PADROES: Final = (
    # Token do link de decisao e do checkout do simulador (credenciais de cliente).
    (re.compile(r"(/publico/orcamentos/)[^/?#\s\"']+"), r"\1***"),
    (re.compile(r"(/simulador/checkout/[^?\s\"']+\?token=)[^&\s\"']+"), r"\1***"),
    (re.compile(r"([?&]token=)[^&\s\"']+"), r"\1***"),
    (re.compile(r"(Bearer\s+)[A-Za-z0-9._~+/=-]+", re.IGNORECASE), r"\1***"),
    # JWT: tres segmentos base64url, o primeiro sempre comeca por eyJ ({"...).
    (re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*"), MASCARA),
)

_registrados: set[str] = set()


def registrar(valor: str) -> None:
    """Passa a mascarar ``valor`` e, no GitHub Actions, pede ao runner que o mascare.

    Fora do Actions o ``::add-mask::`` imprimiria o segredo no terminal, o
    contrario do que se quer: la so o ``mascarar`` protege.
    """
    if len(valor) < _TAMANHO_MINIMO:
        return
    for linha in valor.splitlines():
        if len(linha) >= _TAMANHO_MINIMO:
            _registrados.add(linha)
            if os.environ.get("GITHUB_ACTIONS") == "true":
                # Na linha propria: o runner so reconhece o comando no inicio da linha,
                # e o pytest deixa o nome do arquivo e os pontos de progresso abertos.
                print(f"\n::add-mask::{linha}", file=sys.__stdout__, flush=True)


def mascarar(texto: str) -> str:
    """``texto`` sem os segredos registrados nem os padroes de credencial."""
    # Os maiores primeiro: um valor que contem outro nao pode sobrar pela metade.
    for segredo in sorted(_registrados, key=len, reverse=True):
        texto = texto.replace(segredo, MASCARA)
    for padrao, troca in _PADROES:
        texto = padrao.sub(troca, texto)
    return texto


def esquecer_todos() -> None:
    """Zera os registrados (so os testes precisam)."""
    _registrados.clear()
