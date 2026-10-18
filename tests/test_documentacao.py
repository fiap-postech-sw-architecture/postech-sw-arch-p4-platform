"""Links, ancoras e blocos de comando de todo .md versionado.

- Cada link relativo cai em arquivo e secao que existem; as ancoras sao as que o
  GitHub gera dos titulos. Os links para fora do repositorio (``https:``) e o que
  esta entre crases (uma consulta PromQL com ``](``) nao entram.
- Toda cerca de codigo fecha: uma cerca sem par troca, no resto do arquivo, o que
  e bloco de codigo pelo que nao e.
- Os comandos dos blocos ``bash``, ``sh``, ``zsh``, ``shell`` e ``console`` rodam
  colados no terminal: no zsh interativo (o padrao do macOS) o ``#`` nao abre
  comentario, e o texto depois dele vira argumento do comando (no make, vira
  alvo). O que o comando faz fica na frase acima do bloco.
"""

from __future__ import annotations

import re
import subprocess  # nosec B404
from pathlib import Path
from urllib.parse import unquote

import pytest

RAIZ = Path(__file__).resolve().parents[1]


def _documentos() -> list[str]:
    """Todo .md que o git versiona: um documento novo entra sem mexer aqui."""
    saida = subprocess.run(  # nosec B603 B607
        ["git", "ls-files", "-z", "*.md"],  # noqa: S607
        cwd=RAIZ,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    ).stdout
    return list(filter(None, saida.split("\0")))


DOCUMENTOS = _documentos()
# Bloco de codigo: um # dentro dele nao e titulo, e um [x](y) nao e link.
_CERCA = re.compile(r"^[ \t]*```.*?^[ \t]*```[ \t]*$", re.DOTALL | re.MULTILINE)
# Linha de cerca, de abertura ou de fechamento: o total por documento e par.
_LINHA_DE_CERCA = re.compile(r"^[ \t]*```", re.MULTILINE)
# Trecho em linha: o que esta entre crases nao e link, mesmo com ](.
_EM_LINHA = re.compile(r"`[^`\n]*`")
# Bloco de comando: a cerca pode vir indentada, no passo numerado de uma lista.
_BLOCO = re.compile(
    r"^[ \t]*```(?:bash|sh|zsh|shell|console)\n(.*?)^[ \t]*```[ \t]*$",
    re.DOTALL | re.MULTILINE,
)
# Um # no comeco da linha ou depois de espaco: `make e2e #texto` tambem passa o
# texto como argumento. O # no meio de uma palavra (https://x.dev/#y) nao conta.
_COMENTARIO = re.compile(r"(^|\s)#")


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
    texto = _EM_LINHA.sub("", _CERCA.sub("", origem.read_text(encoding="utf-8")))
    links = []
    for link in re.findall(r"\]\(([^)\s]+)\)", texto):
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


def _cercas_pares(texto: str) -> bool:
    return len(_LINHA_DE_CERCA.findall(texto)) % 2 == 0


def test_a_conferencia_cobre_o_readme_e_os_documentos_de_docs() -> None:
    em_docs = {p.relative_to(RAIZ).as_posix() for p in (RAIZ / "docs").rglob("*.md")}

    assert "README.md" in DOCUMENTOS
    assert em_docs <= set(DOCUMENTOS)


@pytest.mark.parametrize("documento", DOCUMENTOS)
def test_links_relativos_do_documento_caem_em_arquivo_e_secao_reais(
    documento: str,
) -> None:
    assert _quebrados(_links_relativos(RAIZ / documento)) == []


@pytest.mark.parametrize("documento", DOCUMENTOS)
def test_cercas_do_documento_fecham(documento: str) -> None:
    assert _cercas_pares((RAIZ / documento).read_text(encoding="utf-8"))


def test_cerca_sem_par_reprova() -> None:
    assert _cercas_pares("```bash\nmake test\n```\n   ```text\nx\n   ```\n")
    assert not _cercas_pares("```bash\nmake test\n```\n   ```text\nsem fechar\n")


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
        '`sum(x{q!~".+[.](dlq|retry[.].+)"})` [j](docs/c.md) `y`\n'
        "```bash\n[nao e link](nada.md)\n```\n",
        encoding="utf-8",
    )

    assert _quebrados(_links_relativos(origem)) == [
        "docs/b.md",
        "docs/a.md#outra",
        "#fim",
        "docs/c.md",
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
        "```bash\nmake e2e      # os 14 cenarios\nmake e2e #os 14 cenarios\n```\n"
        "1. Passo:\n\n"
        "   ```sh\n   kubectl get pods  # espera\n   ```\n\n"
        "```zsh\n# so comentario\nmake test\n```\n"
        "```shell\nmake lint  # confere\n```\n"
        "```console\n$ make lint  # confere\n```\n"
        "```text\nsaida # nao e comando\n```\n"
        "```bash\ncurl https://x.dev/#y\nmake kind-up\n```\n"
    )

    assert _linhas_com_comentario(texto) == [
        "make e2e      # os 14 cenarios",
        "make e2e #os 14 cenarios",
        "   kubectl get pods  # espera",
        "# so comentario",
        "make lint  # confere",
        "$ make lint  # confere",
    ]
