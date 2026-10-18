"""Links relativos e ancoras dos documentos que o alinhamento ao construido tocou.

O titulo de uma secao muda (o do overlay `k3s` no README mudou e levou o link da
nuvem opcional junto) e o link que apontava para ele fica morto sem ninguem ver.
Aqui cada link relativo desses documentos cai em arquivo e secao que existem; os
links para fora do repositorio (``https:``) nao entram.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote

import pytest

RAIZ = Path(__file__).resolve().parents[1]
DOCUMENTOS = (
    "README.md",
    "docs/arquitetura/adr/fase4/037-banco-por-servico.md",
    "docs/arquitetura/adr/fase4/040-integracao-mercado-pago.md",
    "docs/arquitetura/adr/fase4/041-estrategia-de-testes-e-qualidade.md",
    "docs/arquitetura/rfc/fase4/rfc-004-microsservicos-saga.md",
    "docs/operacao/nuvem-opcional.md",
    "docs/operacao/runbook-saga.md",
)
# Bloco de codigo: um # dentro dele nao e titulo, e um [x](y) nao e link.
_CERCA = re.compile(r"^[ \t]*```.*?^[ \t]*```[ \t]*$", re.DOTALL | re.MULTILINE)


def _ancoras(texto: str) -> set[str]:
    """As ancoras que o GitHub gera para os titulos do Markdown.

    Minusculas, sem pontuacao, espaco vira hifen, e o titulo repetido ganha
    ``-1``, ``-2``...
    """
    ancoras: set[str] = set()
    vistas: dict[str, int] = {}
    for titulo in re.findall(r"^#{1,6} (.+)$", _CERCA.sub("", texto), re.MULTILINE):
        base = re.sub(r"[^\w\- ]", "", titulo.strip().lower()).replace(" ", "-")
        repeticao = vistas.get(base, 0)
        vistas[base] = repeticao + 1
        ancoras.add(f"{base}-{repeticao}" if repeticao else base)
    return ancoras


def _links_relativos(origem: Path) -> list[tuple[str, Path, str]]:
    """(link, arquivo de destino, ancora) dos links de ``origem`` ao repositorio."""
    links = []
    for link in re.findall(
        r"\]\(([^)\s]+)\)", _CERCA.sub("", origem.read_text(encoding="utf-8"))
    ):
        caminho, _, ancora = unquote(link).partition("#")
        # https:, mailto: e afins saem do repositorio.
        if re.match(r"[a-z]+:", caminho) is None:
            links.append((link, origem.parent / caminho if caminho else origem, ancora))
    return links


def _quebrados(links: list[tuple[str, Path, str]]) -> list[str]:
    return [
        link
        for link, destino, ancora in links
        if not destino.exists()
        or (
            ancora != ""
            and destino.suffix == ".md"
            and ancora not in _ancoras(destino.read_text(encoding="utf-8"))
        )
    ]


@pytest.mark.parametrize("documento", DOCUMENTOS)
def test_links_relativos_do_documento_caem_em_arquivo_e_secao_reais(
    documento: str,
) -> None:
    links = _links_relativos(RAIZ / documento)

    assert links, "o documento nao tem nenhum link relativo: o teste nao conferiu nada"
    assert _quebrados(links) == []


def test_ancora_gerada_como_a_do_github() -> None:
    texto = (
        "# Ação (LGPD)\n"
        "```bash\n# nao e titulo\n```\n"
        "## Testes\n### Testes\n"
        "### Cluster persistente (overlay `k3s`)\n"
    )

    assert _ancoras(texto) == {
        "ação-lgpd",
        "testes",
        "testes-1",
        "cluster-persistente-overlay-k3s",
    }


def test_link_para_arquivo_ou_secao_que_nao_existe_reprova(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "a.md").write_text("# Seção A\n", encoding="utf-8")
    (tmp_path / "docs" / "dados.json").write_text("{}", encoding="utf-8")
    origem = tmp_path / "README.md"
    origem.write_text(
        "# Topo\n"
        "[a](docs/a.md#seção-a) [a2](docs/a.md#se%C3%A7%C3%A3o-a) [b](#topo)\n"
        "[c](docs/) [d](https://x.dev/#y) [e](docs/b.md) [f](docs/a.md#outra)\n"
        "[g](#fim) [h](docs/a.md) [i](docs/dados.json#qualquer)\n"
        "```bash\n[nao e link](nada.md)\n```\n",
        encoding="utf-8",
    )

    assert _quebrados(_links_relativos(origem)) == [
        "docs/b.md",
        "docs/a.md#outra",
        "#fim",
    ]
