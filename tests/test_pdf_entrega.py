"""Garante links navegáveis, índice no PDF e fonte única da arquitetura."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

import pytest

from scripts.evidencias import pdf


def test_links_relativos_respeitam_origem_e_diretorios(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "docs").mkdir()
    texto = (
        "[pasta](../docs) [arquivo](../README.md#inicio) [fora](https://fiap.com.br)"
    )
    assert pdf.reescrever_links(
        texto, "grupo/repo", "main", tmp_path / "docs", tmp_path
    ) == (
        "[pasta](https://github.com/grupo/repo/tree/main/docs) "
        "[arquivo](https://github.com/grupo/repo/blob/main/README.md#inicio) "
        "[fora](https://fiap.com.br)"
    )


def test_diagrama_divergente_reprova_em_vez_de_gerar_pdf(tmp_path: Path) -> None:
    rfc = tmp_path / "docs/arquitetura/rfc/fase4/rfc-004-microsservicos-saga.md"
    rfc.parent.mkdir(parents=True)
    rfc.write_text("```mermaid\nflowchart TB\n A --> B\n```")
    (tmp_path / "README.md").write_text(rfc.read_text())
    doc = tmp_path / "docs/entrega/fase4/entrega-fase-4.md"
    doc.parent.mkdir(parents=True)
    doc.write_text("```mermaid\nflowchart TB\n A --> C\n```")
    with pytest.raises(ValueError, match="Mermaid divergente"):
        pdf.preparar(tmp_path, "grupo/repo", "main")


def test_pdf_inclui_indice_com_links_reescritos_por_arquivo(tmp_path: Path) -> None:
    rfc = tmp_path / "docs/arquitetura/rfc/fase4/rfc-004-microsservicos-saga.md"
    rfc.parent.mkdir(parents=True)
    rfc.write_text("```mermaid\nflowchart TB\n A --> B\n```")
    (tmp_path / "README.md").write_text(rfc.read_text())
    doc = tmp_path / "docs/entrega/fase4/entrega-fase-4.md"
    doc.parent.mkdir(parents=True)
    doc.write_text(
        rfc.read_text() + "\nPendências visíveis\n[leia](../../../README.md)"
    )
    (tmp_path / "INDICE-DA-ENTREGA.md").write_text(
        "# Índice\n[matriz](docs/entrega/matriz.md)"
    )
    texto = pdf.preparar(tmp_path, "grupo/repo", "main")
    assert "Pendências visíveis" in texto
    assert "# Índice" in texto
    assert "(https://github.com/grupo/repo/blob/main/docs/entrega/matriz.md)" in texto
    assert "(https://github.com/grupo/repo/blob/main/README.md)" in texto
