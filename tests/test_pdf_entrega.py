"""Garante links navegáveis, capa ABNT, sumário depois dela e diagramas da RFC,
com página paisagem só para o diagrama largo."""

from __future__ import annotations

import math
import re
import sys
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


def test_os_diagramas_do_documento_sao_os_da_rfc_e_o_geral_o_do_readme() -> None:
    # O build do PDF faz a mesma conferência; aqui ela roda no CI, sem pandoc.
    raiz = Path(pdf.__file__).resolve().parents[2]
    pdf.conferir_diagramas(
        (raiz / pdf.DOCUMENTO).read_text(),
        (raiz / pdf.RFC).read_text(),
        (raiz / "README.md").read_text(),
    )


def _pixels(css: float) -> int:
    """Lado do PNG de um diagrama de `css` px de CSS, na escala do gerador."""
    return round(css * pdf.ESCALA)


# As fronteiras usam as contas do largo(): `ceil` dá a menor largura que passa
# em cada teste, sem depender de como o ponto flutuante arredonda 1,1 x altura.
REDUZIDO = math.ceil(0.9 * pdf.LARGURA_MERMAID * pdf.ESCALA)
ALTURA_NO_LIMITE = _pixels(1350)
LARGURA_NO_LIMITE = math.ceil(1.1 * ALTURA_NO_LIMITE)


# Os oito primeiros são os tamanhos em px de CSS de diagramas da RFC-004; 1584 é
# a largura a que o Mermaid reduz o diagrama que não cabe na página. O de
# componentes e o ER do OS levam espaçamento menor na RFC, que os deixa mais
# largos que altos; as duas últimas partes do caminho feliz, que o Mermaid não
# reduz, ficam no retrato.
@pytest.mark.parametrize(
    ("largura", "altura", "deitado"),
    [
        pytest.param(
            _pixels(1584), _pixels(1086.4), True, id="sequencia-larga-reduzida"
        ),
        pytest.param(_pixels(1584), _pixels(526.4), True, id="er-largo-e-baixo"),
        pytest.param(
            _pixels(1584), _pixels(1020), True, id="componentes-com-espacamento-menor"
        ),
        pytest.param(
            _pixels(1584), _pixels(1034.4), True, id="er-do-os-com-espacamento-menor"
        ),
        pytest.param(
            _pixels(1582.4), _pixels(1147.2), True, id="caminho-feliz-t1-a-t4"
        ),
        pytest.param(_pixels(1340), _pixels(979), False, id="caminho-feliz-t5-a-t6"),
        pytest.param(_pixels(1123), _pixels(828), False, id="caminho-feliz-t7-a-t10"),
        pytest.param(
            _pixels(1584), _pixels(1500), False, id="quase-quadrado-fica-no-retrato"
        ),
        pytest.param(
            _pixels(1366.4), _pixels(794.4), False, id="largo-que-cabe-no-retrato"
        ),
        pytest.param(REDUZIDO, _pixels(480), True, id="no-limite-do-reduzido"),
        pytest.param(
            REDUZIDO - 1, _pixels(480), False, id="um-pixel-abaixo-do-reduzido"
        ),
        pytest.param(
            LARGURA_NO_LIMITE, ALTURA_NO_LIMITE, True, id="no-limite-da-proporcao"
        ),
        pytest.param(
            LARGURA_NO_LIMITE,
            ALTURA_NO_LIMITE + 1,
            False,
            id="um-pixel-acima-da-proporcao",
        ),
    ],
)
def test_so_o_diagrama_reduzido_e_bem_mais_largo_que_alto_vai_deitado(
    largura: int, altura: int, deitado: bool
) -> None:
    assert pdf.largo(largura, altura) is deitado


def test_so_a_versao_compacta_limita_a_resolucao_das_imagens() -> None:
    html, destino = Path("entrega.html"), Path("entrega.pdf")

    assert pdf.comando_weasyprint(html, destino, None) == [
        "weasyprint",
        "entrega.html",
        "entrega.pdf",
    ]
    assert pdf.comando_weasyprint(html, destino, 150) == [
        "weasyprint",
        "-D",
        "150",
        "entrega.html",
        "entrega.pdf",
    ]


@pytest.mark.parametrize("valor", ["0", "-5"])
def test_dpi_zero_ou_negativo_e_recusado_antes_do_build(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, valor: str
) -> None:
    saida = tmp_path / "entrega.pdf"
    monkeypatch.setattr(sys, "argv", ["pdf", "--output", str(saida), "--dpi", valor])

    with pytest.raises(SystemExit):
        pdf.main()
    assert not saida.exists()


def test_a_classe_paisagem_do_gerador_tem_pagina_deitada_no_css() -> None:
    css = Path(pdf.__file__).with_name("pdf.css").read_text()

    assert re.search(r"@page\s+paisagem\s*\{[^}]*size:\s*A4 landscape", css)
    assert re.search(r"\.paisagem\s*\{[^}]*page:\s*paisagem", css)


def test_legenda_traz_a_secao_da_rfc_que_contem_o_diagrama() -> None:
    rfc = f"## 2. Geral\n\n{GERAL}\n\n#### (a) `Caminho` feliz\n\n{SAGA}\n"
    assert pdf.secao_da_rfc(rfc, "sequenceDiagram\n A->>B: oi\n") == (
        "(a) Caminho feliz"
    )
    with pytest.raises(ValueError, match="Mermaid divergente"):
        pdf.secao_da_rfc(rfc, "flowchart LR\n X --> Y\n")


def test_pdf_reescreve_os_links_e_nao_anexa_o_indice_do_repositorio(
    tmp_path: Path,
) -> None:
    raiz = _pacote(
        tmp_path, f"{GERAL}\n{SAGA}\nPendências visíveis\n[leia](../../../README.md)"
    )
    texto = pdf.preparar(raiz, "grupo/repo", "main")
    assert "Pendências visíveis" in texto
    assert "(https://github.com/grupo/repo/blob/main/README.md)" in texto
    # O índice dos artefatos abre o documento; o do repositório fica no link.
    assert "Índice" not in texto
    assert "matriz.md" not in texto


def test_capa_abnt_abre_o_pdf_com_os_participantes_do_documento(
    tmp_path: Path,
) -> None:
    documento = (
        f"{GERAL}\n# Documento\n\nGrupo 158 (PytStop), turma 15SOAT.\n\n"
        "| Nome | RM | Discord |\n|---|---|---|\n"
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
    # O grupo abre a lista; um participante por linha, sem partir nome e RM.
    assert "<p><strong>Grupo 158</strong></p>\n<p>Ana Lima — RM111111</p>" in capa
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


def test_capa_sem_a_linha_do_grupo_nao_inventa_um(tmp_path: Path) -> None:
    documento = (
        f"{GERAL}\n| Nome | RM | Discord |\n|---|---|---|\n"
        "| Ana Lima | RM111111 | ana |\n"
    )
    capa = pdf.preparar(_pacote(tmp_path, documento), "grupo/repo", "main").partition(
        '<div id="pos-capa"></div>'
    )[0]

    assert "Grupo" not in capa
    assert "<p>Ana Lima — RM111111</p>" in capa


@pytest.mark.parametrize(
    ("largura", "altura", "esperado"),
    [
        pytest.param(_pixels(1217), _pixels(811), True, id="orcamento-recusado"),
        pytest.param(_pixels(1366), _pixels(794), True, id="falta-de-peca"),
        pytest.param(_pixels(1169), _pixels(936), False, id="geral-quase-quadrado"),
        pytest.param(1450, 1000, True, id="no-limite-da-proporcao"),
        pytest.param(1449, 1000, False, id="um-pixel-abaixo-da-proporcao"),
    ],
)
def test_so_o_diagrama_largo_que_cabe_no_retrato_ganha_altura_limitada(
    largura: int, altura: int, esperado: bool
) -> None:
    assert pdf.compacto(largura, altura) is esperado


@pytest.mark.parametrize(
    ("largura", "altura", "esperado"),
    [
        pytest.param(_pixels(1340), _pixels(979), True, id="caminho-feliz-t5-a-t6"),
        pytest.param(_pixels(1123), _pixels(828), True, id="caminho-feliz-t7-a-t10"),
        pytest.param(_pixels(1169), _pixels(936), False, id="geral-quase-quadrado"),
        pytest.param(1340, 1000, True, id="no-limite-da-proporcao"),
        pytest.param(1339, 1000, False, id="um-pixel-abaixo-da-proporcao"),
    ],
)
def test_so_o_diagrama_medio_ganha_meia_pagina(
    largura: int, altura: int, esperado: bool
) -> None:
    assert pdf.meia(largura, altura) is esperado
