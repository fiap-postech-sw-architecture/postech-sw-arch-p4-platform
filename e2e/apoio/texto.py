"""Comparacao de texto de mensagem de erro sem depender de acento nem de caixa."""

from __future__ import annotations

import unicodedata


def sem_acentos(texto: str) -> str:
    """``texto`` em minusculas e sem diacriticos (``execução`` vira ``execucao``)."""
    decomposto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in decomposto if not unicodedata.combining(c)).casefold()
