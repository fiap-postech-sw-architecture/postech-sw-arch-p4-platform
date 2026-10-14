"""Painel de negocio sem serie no Prometheus: ``python -m e2e.paineis <dir>``."""

from __future__ import annotations

import sys

from e2e.apoio.paineis import principal

if __name__ == "__main__":
    sys.exit(principal(sys.argv[1:]))
