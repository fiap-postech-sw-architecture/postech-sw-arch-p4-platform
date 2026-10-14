"""Confere o sandbox antes do pytest: python -m e2e.conferir_sandbox <real|ensaio>."""

from __future__ import annotations

import os
import sys

from e2e.ambiente import CONTEXTO, URL_DA_BORDA
from e2e.apoio.conferencia_previa import conferir_antes_do_pytest

if __name__ == "__main__":
    sys.exit(
        conferir_antes_do_pytest(
            sys.argv[1:], os.environ, contexto=CONTEXTO, url_da_borda=URL_DA_BORDA
        )
    )
