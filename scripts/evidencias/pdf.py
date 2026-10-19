"""PDF da entrega: receita pandoc/weasyprint/Mermaid das fases anteriores.

Adapta scripts/build-entrega-pdf.sh da fase 3 e gerar_pdf_entrega.py da skill
entrega-tech-challenge. Mantém pendências e anexa o índice, com links por origem.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil

# Executáveis resolvidos no PATH; argumentos separados, sem shell.
import subprocess  # nosec B404
import tempfile
from pathlib import Path
from urllib.parse import quote, urlsplit

from scripts.evidencias.verificar import verificar

DOCUMENTO = Path("docs/entrega/fase4/entrega-fase-4.md")
RFC = Path("docs/arquitetura/rfc/fase4/rfc-004-microsservicos-saga.md")
MERMAID = re.compile(r"```mermaid\n(.*?)```", re.S)
REPO = "fiap-postech-sw-architecture/postech-sw-arch-p4-platform"


def reescrever_links(
    texto: str, repo: str, branch: str, origem: Path, raiz: Path
) -> str:
    """Converte cada destino local em link GitHub, preservando âncoras e imagens."""

    def trocar(match: re.Match[str]) -> str:
        rotulo, destino = match.groups()
        url = urlsplit(destino)
        if url.scheme or url.netloc or not url.path:
            return match.group(0)
        alvo = (origem / url.path).resolve()
        relativo = alvo.relative_to(raiz).as_posix()
        fragmento = f"#{url.fragment}" if url.fragment else ""
        if match.start() and texto[match.start() - 1] == "!":
            return f"[{rotulo}]({alvo})"
        tipo = "tree" if alvo.is_dir() else "blob"
        return f"[{rotulo}](https://github.com/{repo}/{tipo}/{branch}/{quote(relativo)}{fragmento})"

    return re.sub(r"\[([^\]]+)\]\(([^)]+)\)", trocar, texto)


def preparar(raiz: Path, repo: str, branch: str) -> str:
    """Confere a fonte Mermaid e combina documento e índice sem editar originais."""
    documento = (raiz / DOCUMENTO).read_text()
    blocos = MERMAID.findall(documento)
    if len(blocos) != 1 or any(
        blocos[0] not in MERMAID.findall((raiz / fonte).read_text())
        for fonte in (RFC, Path("README.md"))
    ):
        raise ValueError("Mermaid divergente entre documento, RFC e README")
    documento = reescrever_links(
        documento, repo, branch, (raiz / DOCUMENTO).parent, raiz
    )
    # A arquitetura ocupa página própria; a receita da fase 3 limita a imagem
    # à área imprimível, pois weasyprint não pagina imagens.
    documento = documento.replace(
        "## 4. Arquitetura final",
        '<div class="arquitetura">\n\n## 4. Arquitetura final',
    )
    documento = documento.replace("## 5. Divisão", "</div>\n\n## 5. Divisão")
    indice = reescrever_links(
        (raiz / "INDICE-DA-ENTREGA.md").read_text(), repo, branch, raiz, raiz
    )
    return documento + '\n\n<div class="indice">\n\n' + indice + "\n\n</div>\n"


def executar(argumentos: list[str]) -> None:
    """Executa ferramentas do PATH, sem shell, e preserva falhas de build."""
    ferramenta = shutil.which(argumentos[0])
    if ferramenta is None:
        raise RuntimeError(f"ferramenta necessária ausente: {argumentos[0]}")
    subprocess.run([ferramenta, *argumentos[1:]], check=True)  # noqa: S603  # nosec B603


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--final", action="store_true")
    parser.add_argument("--github", type=Path)
    args = parser.parse_args()
    raiz = Path(__file__).resolve().parents[2]
    destino = args.output.expanduser().resolve()
    if destino.is_relative_to(raiz):
        parser.error("o PDF deve ficar fora do repositório")
    github = json.loads(args.github.read_text()) if args.github else None
    erros = verificar(raiz, final=args.final, github=github)
    if erros:
        parser.error("\n".join(erros))
    texto = preparar(raiz, REPO, "entrega-fase-4" if args.final else "main")
    with tempfile.TemporaryDirectory(prefix="pytstop-entrega-") as pasta:
        tmp = Path(pasta)

        def renderizar(match: re.Match[str]) -> str:
            fonte, imagem = tmp / "arquitetura.mmd", tmp / "arquitetura.png"
            fonte.write_text(match.group(1))
            executar(
                [
                    "npx",
                    "--yes",
                    "@mermaid-js/mermaid-cli@11.17.0",
                    "-i",
                    str(fonte),
                    "-o",
                    str(imagem),
                    "-w",
                    "1600",
                    "-s",
                    "2",
                    "-b",
                    "white",
                ]
            )
            return (
                f'<img class="diagrama" src="{html.escape(str(imagem))}" '
                'alt="Arquitetura: serviços, bancos, mensageria e observabilidade"/>\n'
            )

        (tmp / "entrega.md").write_text(MERMAID.sub(renderizar, texto))
        executar(
            [
                "pandoc",
                str(tmp / "entrega.md"),
                "-o",
                str(tmp / "entrega.html"),
                "--standalone",
                "--toc",
                "--toc-depth=2",
                "-V",
                "lang=pt-BR",
                "-V",
                "toc-title=Sumário",
                "--metadata",
                "pagetitle=PytStop - Tech Challenge Fase 4",
                "--css",
                str(Path(__file__).with_name("pdf.css")),
            ]
        )
        pagina = (tmp / "entrega.html").read_text()
        pagina = re.sub(r"<colgroup>.*?</colgroup>", "", pagina, flags=re.S)
        larguras = {"JSON": "8em", "Como ler": "10em"}
        pagina = re.sub(
            r"<th[^>]*>(JSON|Como ler)</th>",
            lambda m: f'<th style="width:{larguras[m.group(1)]}">{m.group(1)}</th>',
            pagina,
        )
        (tmp / "entrega.html").write_text(pagina)
        executar(["weasyprint", str(tmp / "entrega.html"), str(destino)])
    print(f"PDF {'final' if args.final else 'de ensaio'} gerado: {destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
