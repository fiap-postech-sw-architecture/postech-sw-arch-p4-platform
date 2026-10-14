"""Varre os relatorios atras de segredo: ``python -m e2e.varredura <pasta>``."""

from __future__ import annotations

import os
import sys

from e2e.apoio.evidencia import principal_da_varredura

if __name__ == "__main__":
    sys.exit(principal_da_varredura(sys.argv[1:], os.environ))
