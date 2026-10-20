"""Galeria de evidências visuais: nenhuma imagem solta e PDF dentro do teto.

Cada PNG de docs/entrega/fase4/evidencias aparece no documento de entrega e no
registro de evidências, e o documento não aponta para imagem que não esteja na
pasta (a conferência de links já reprova o arquivo ausente).
"""

from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
PASTA = RAIZ / "docs/entrega/fase4/evidencias"
DOCUMENTO = RAIZ / "docs/entrega/fase4/entrega-fase-4.md"
# O PDF de ensaio precisa ficar abaixo de cerca de 6 MB; o resto é texto e diagrama.
TETO_DOS_PNG = 5_000_000


def _imagens_do_documento() -> set[str]:
    texto = DOCUMENTO.read_text(encoding="utf-8")
    return {
        Path(destino).name
        for destino in re.findall(r"!\[[^\]\n]+\]\(([^)\s]+)\)", texto)
    }


def test_toda_imagem_da_pasta_entra_no_documento_e_no_registro() -> None:
    na_pasta = {png.name for png in PASTA.glob("*.png")}
    registro = (PASTA / "README.md").read_text(encoding="utf-8")

    assert na_pasta
    assert na_pasta == _imagens_do_documento()
    assert [nome for nome in sorted(na_pasta) if nome not in registro] == []


def test_imagens_juntas_cabem_no_teto_do_pdf() -> None:
    assert sum(png.stat().st_size for png in PASTA.glob("*.png")) < TETO_DOS_PNG
