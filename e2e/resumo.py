"""Escreve ``resumo.md``: ``python -m e2e.resumo reports/e2e``."""

from __future__ import annotations

import sys

from e2e.apoio.relatorio import principal

if __name__ == "__main__":
    sys.exit(principal(sys.argv[1:]))
