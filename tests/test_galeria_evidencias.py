"""Galeria de evidências visuais: nenhuma imagem solta e PDF dentro do teto.

Cada PNG de docs/entrega/fase4/evidencias aparece no documento de entrega, embutido
ou, nos poucos casos de SO_COM_LINK, só com link (fica no repositório e no
registro, fora do PDF), e no registro de evidências. O documento não aponta para
imagem que não esteja na pasta (a conferência de links já reprova o arquivo
ausente).
"""

from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
PASTA = RAIZ / "docs/entrega/fase4/evidencias"
DOCUMENTO = RAIZ / "docs/entrega/fase4/entrega-fase-4.md"
# O PDF de ensaio precisa ficar abaixo de cerca de 6 MB; o resto é texto e diagrama.
TETO_DOS_PNG = 5_000_000
# Decisão de volume do PDF: os quatro dashboards que o Anexo B, B7, só lista, as
# três telas do Swagger (B4), o ruleset do Billing (o B8 mostra o do OS Service) e
# o print de 20/10 do trace e a busca do mesmo dia (o B3 mostra o de 23/10, com as
# compensações, e o caminho feliz). Imagem que sair desta lista passa a ser
# embutida, e o teste reprova a troca silenciosa de uma imagem por um link.
SO_COM_LINK = {
    "jaeger-busca-saga-2026-10-20.png",
    "swagger-os-service-2026-10-20.png",
    "swagger-billing-service-2026-10-20.png",
    "swagger-execution-service-2026-10-20.png",
    "grafana-saga-2026-10-22.png",
    "grafana-mensageria-2026-10-22.png",
    "grafana-bancos-2026-10-22.png",
    "grafana-plataforma-2026-10-22.png",
    "protecao-ruleset-billing-service-2026-10-23.png",
    "jaeger-trace-saga-2026-10-20.png",
}


def _imagens_do_documento() -> set[str]:
    texto = DOCUMENTO.read_text(encoding="utf-8")
    return {
        Path(destino).name
        for destino in re.findall(r"!\[[^\]\n]+\]\(([^)\s]+)\)", texto)
    }


def _png_ligados_no_documento() -> set[str]:
    texto = DOCUMENTO.read_text(encoding="utf-8")
    return {
        Path(destino).name
        for destino in re.findall(r"(?<!!)\[[^\]\n]+\]\(([^)\s#]+\.png)\)", texto)
    }


def test_toda_imagem_da_pasta_entra_no_documento_e_no_registro() -> None:
    na_pasta = {png.name for png in PASTA.glob("*.png")}
    registro = (PASTA / "README.md").read_text(encoding="utf-8")

    assert na_pasta
    assert na_pasta == _imagens_do_documento() | _png_ligados_no_documento()
    assert [nome for nome in sorted(na_pasta) if nome not in registro] == []


def test_so_as_imagens_da_lista_ficam_fora_do_pdf() -> None:
    embutidas = _imagens_do_documento()

    assert _png_ligados_no_documento() - embutidas == SO_COM_LINK
    assert embutidas & SO_COM_LINK == set()


def test_imagens_juntas_cabem_no_teto_do_pdf() -> None:
    assert sum(png.stat().st_size for png in PASTA.glob("*.png")) < TETO_DOS_PNG
