"""Garante links navegáveis, capa ABNT, sumário depois dela e diagramas da RFC."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

import pytest

from scripts.evidencias import pdf

GERAL = "```mermaid\nflowchart TB\n A --> B\n```"
SAGA = "```mermaid\nsequenceDiagram\n A->>B: oi\n```"


def _pacote(tmp_path: Path, documento: str) -> Path:
    rfc = tmp_path / "docs/arquitetura/rfc/fase4/rfc-004-microsservicos-saga.md"
    rfc.parent.mkdir(parents=True)
    rfc.write_text(f"## 2. Geral\n\n{GERAL}\n\n#### (a) Caminho feliz\n\n{SAGA}\n")
    (tmp_path / "README.md").write_text(GERAL)
    doc = tmp_path / "docs/entrega/fase4/entrega-fase-4.md"
    doc.parent.mkdir(parents=True)
    doc.write_text(documento)
    (tmp_path / "INDICE-DA-ENTREGA.md").write_text(
        "# Índice\n[matriz](docs/entrega/matriz.md)"
    )
    return tmp_path


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
    raiz = _pacote(tmp_path, "```mermaid\nflowchart TB\n A --> C\n```")
    with pytest.raises(ValueError, match="Mermaid divergente"):
        pdf.preparar(raiz, "grupo/repo", "main")


@pytest.mark.parametrize(
    "documento",
    [
        pytest.param(f"{SAGA}\n{GERAL}", id="geral-fora-do-primeiro-lugar"),
        pytest.param(
            f"{GERAL}\n```mermaid\nflowchart LR\n X --> Y\n```", id="so-no-doc"
        ),
        pytest.param("sem diagrama", id="sem-diagrama"),
    ],
)
def test_todo_diagrama_vem_da_rfc_e_o_geral_tambem_do_readme(
    tmp_path: Path, documento: str
) -> None:
    raiz = _pacote(tmp_path, documento)
    with pytest.raises(ValueError, match="Mermaid divergente"):
        pdf.preparar(raiz, "grupo/repo", "main")


def test_legenda_traz_a_secao_da_rfc_que_contem_o_diagrama() -> None:
    rfc = f"## 2. Geral\n\n{GERAL}\n\n#### (a) `Caminho` feliz\n\n{SAGA}\n"
    assert pdf.secao_da_rfc(rfc, "sequenceDiagram\n A->>B: oi\n") == (
        "(a) Caminho feliz"
    )
    with pytest.raises(ValueError, match="Mermaid divergente"):
        pdf.secao_da_rfc(rfc, "flowchart LR\n X --> Y\n")


def test_pdf_inclui_indice_com_links_reescritos_por_arquivo(tmp_path: Path) -> None:
    raiz = _pacote(
        tmp_path, f"{GERAL}\n{SAGA}\nPendências visíveis\n[leia](../../../README.md)"
    )
    texto = pdf.preparar(raiz, "grupo/repo", "main")
    assert "Pendências visíveis" in texto
    assert "\n# Anexo C — Índice\n" in texto
    assert "(https://github.com/grupo/repo/blob/main/docs/entrega/matriz.md)" in texto
    assert "(https://github.com/grupo/repo/blob/main/README.md)" in texto


def test_capa_abnt_abre_o_pdf_com_os_participantes_do_documento(
    tmp_path: Path,
) -> None:
    documento = (
        f"{GERAL}\n# Documento\n\n| Nome | RM | Discord |\n|---|---|---|\n"
        "| Ana Lima | RM111111 | ana |\n| Bruno Reis | RM222222 | bruno |\n"
        "| Caio Dias | RM333333 | caio |\n| Davi Melo | RM444444 | davi |\n"
    )
    texto = pdf.preparar(_pacote(tmp_path, documento), "grupo/repo", "main")
    capa, _, corpo = texto.partition('<div id="pos-capa"></div>')

    assert "FIAP — Faculdade de Informática e Administração Paulista" in capa
    assert "15SOAT — Pós-Graduação em Arquitetura de Software" in capa
    assert "Tech Challenge — Fase 4" in capa
    assert "Documento de Entrega" in capa
    assert "São Paulo — 2026" in capa
    assert f'src="{tmp_path / "docs/entrega/fase4/logo-pytstop.png"}"' in capa
    # Um participante por linha, sem partir nome e RM entre linhas.
    assert "<p>Ana Lima — RM111111</p>\n<p>Bruno Reis — RM222222</p>" in capa
    assert "<p>Davi Melo — RM444444</p>" in capa
    assert "# Documento" in corpo
    assert "# Documento" not in capa


HTML = (
    '<nav id="TOC" role="doc-toc"><h2 id="toc-title">Sumário</h2><ul></ul></nav>'
    '<div class="capa">capa</div>\n<div id="pos-capa">\n</div>\n<h1>Documento</h1>'
    "<table><colgroup><col/></colgroup><tr><td><code>GeracaoDeOrcamentoFalhou</code>"
    " <code>AGUARDANDO_AGENDAMENTO</code> <code>docs/api/x.json</code></td></tr>"
    "</table><pre><code>RAIZ_DO/ProjetoX</code></pre>"
)


def test_sumario_vai_para_depois_da_capa_e_codigo_quebra_entre_palavras() -> None:
    pagina = pdf.ajustar_html(HTML)

    assert pagina.index('class="capa"') < pagina.index('id="TOC"')
    assert pagina.index('id="TOC"') < pagina.index("<h1>Documento</h1>")
    assert pagina.count('id="TOC"') == 1
    assert "<colgroup>" not in pagina
    assert "<code>Geracao<wbr>De<wbr>Orcamento<wbr>Falhou</code>" in pagina
    assert "<code>AGUARDANDO_<wbr>AGENDAMENTO</code>" in pagina
    assert "<code>docs/<wbr>api/<wbr>x.<wbr>json</code>" in pagina
    # Bloco de código mantém o texto como está.
    assert "<pre><code>RAIZ_DO/ProjetoX</code></pre>" in pagina


@pytest.mark.parametrize(
    "html",
    [
        pytest.param(
            HTML.replace('<div id="pos-capa">\n</div>', ""), id="sem-marcador"
        ),
        pytest.param(HTML.replace('<nav id="TOC"', "<nav"), id="sem-sumario"),
    ],
)
def test_sem_marcador_ou_sem_sumario_o_build_para(html: str) -> None:
    with pytest.raises(ValueError, match="sumário"):
        pdf.ajustar_html(html)
