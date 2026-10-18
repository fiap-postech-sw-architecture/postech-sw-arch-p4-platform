"""Links, ancoras e blocos de comando dos documentos que o alinhamento tocou.

- O titulo de uma secao muda (o do overlay `k3s` no README mudou e levou o link
  da nuvem opcional junto) e o link que apontava para ele fica morto sem ninguem
  ver. Cada link relativo desses documentos cai em arquivo e secao que existem;
  os links para fora do repositorio (``https:``) nao entram.
- Os comandos dos blocos ``bash`` rodam colados no terminal: no zsh interativo (o
  padrao do macOS) o ``#`` nao abre comentario, e o texto depois dele vira
  argumento do comando (no make, vira alvo). O que o comando faz fica na frase
  acima do bloco.
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
# Bloco de comando: a cerca pode vir indentada, no passo numerado de uma lista.
_BLOCO = re.compile(
    r"^[ \t]*```(?:bash|sh|zsh)\n(.*?)^[ \t]*```[ \t]*$", re.DOTALL | re.MULTILINE
)
_COMENTARIO = re.compile(r"(^|\s)#(\s|$)")


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


def _linhas_com_comentario(texto: str) -> list[str]:
    return [
        linha
        for bloco in _BLOCO.findall(texto)
        for linha in bloco.splitlines()
        if _COMENTARIO.search(linha)
    ]


def test_blocos_de_comando_dos_documentos_nao_levam_comentario() -> None:
    textos = [
        (RAIZ / documento).read_text(encoding="utf-8") for documento in DOCUMENTOS
    ]

    assert sum(len(_BLOCO.findall(texto)) for texto in textos) > 10
    assert [linha for texto in textos for linha in _linhas_com_comentario(texto)] == []


def test_comentario_em_bloco_de_comando_reprova() -> None:
    texto = (
        "```bash\nmake e2e      # os 14 cenarios\n```\n"
        "1. Passo:\n\n"
        "   ```sh\n   kubectl get pods  # espera\n   ```\n\n"
        "```zsh\n# so comentario\nmake test\n```\n"
        "```text\nsaida # nao e comando\n```\n"
        "```bash\ncurl https://x.dev/#y\nmake kind-up\n```\n"
    )

    assert _linhas_com_comentario(texto) == [
        "make e2e      # os 14 cenarios",
        "   kubectl get pods  # espera",
        "# so comentario",
    ]
