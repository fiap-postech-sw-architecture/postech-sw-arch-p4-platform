"""PDF da entrega: capa ABNT, sumário, diagramas e anexos, como nas fases 1 a 3.

Adapta o scripts/build-entrega-pdf.sh da fase 3 e o gerar_pdf_entrega.py da
skill entrega-tech-challenge: capa sem número de página, sumário logo depois
dela, rodapé numerado, marcadores por título e links relativos trocados pelos
do GitHub. Todo diagrama do documento é cópia literal de um da RFC-004 (o geral
também está no README) e fica no fluxo do texto, na largura da página; o largo
e denso ganha página paisagem própria. O índice dos artefatos do documento dá a
página de cada um. Pendências continuam visíveis no ensaio.
"""

from __future__ import annotations

import argparse
import html
import itertools
import json
import re
import shutil
import struct

# Executáveis resolvidos no PATH; argumentos separados, sem shell.
import subprocess  # nosec B404
import tempfile
from pathlib import Path
from urllib.parse import quote, urlsplit

from scripts.evidencias.verificar import verificar

DOCUMENTO = Path("docs/entrega/fase4/entrega-fase-4.md")
RFC = Path("docs/arquitetura/rfc/fase4/rfc-004-microsservicos-saga.md")
LOGO = Path("docs/entrega/fase4/logo-pytstop.png")
MERMAID = re.compile(r"```mermaid\n(.*?)```", re.S)
REPO = "fiap-postech-sw-architecture/postech-sw-arch-p4-platform"
MERMAID_CLI = "@mermaid-js/mermaid-cli@11.17.0"
# Página do mermaid-cli (px de CSS) e pixels por px: o diagrama mais largo que
# a página sai reduzido a ela, com 1.980 px, cerca de 300 ppi na largura do
# texto. A escala 2 (3.168 px, como os PNG da fase 3) dava 2,5 MB só de
# diagramas: o weasyprint regrava o PNG em RGB, e o peso no PDF acompanha os
# pixels (reduzir a paleta quase não muda o arquivo).
LARGURA_MERMAID = 1600
ESCALA = 1.25
# Linha da tabela de participantes do documento: | Nome | RM123456 | Discord |
PARTICIPANTE = re.compile(r"^\| ([^|\n]+?) \| (RM\d+) \|", re.M)
# Pontos de quebra dentro de código: camelCase e depois de "_", "/" e ".".
QUEBRA = re.compile(r"(?<=[a-z])(?=[A-Z])|(?<=[_/.])(?=[^\W_])")


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


def conferir_diagramas(documento: str, rfc: str, readme: str) -> None:
    """Todo diagrama do documento vem da RFC; o geral, o primeiro, também do README."""
    blocos = MERMAID.findall(documento)
    da_rfc = MERMAID.findall(rfc)
    if (
        not blocos
        or blocos[0] not in MERMAID.findall(readme)
        or any(bloco not in da_rfc for bloco in blocos)
    ):
        raise ValueError("Mermaid divergente entre documento, RFC e README")


def secao_da_rfc(rfc: str, bloco: str) -> str:
    """Título da seção da RFC que traz o diagrama, usado na legenda."""
    posicao = rfc.find(f"```mermaid\n{bloco}```")
    if posicao < 0:
        raise ValueError("Mermaid divergente entre documento, RFC e README")
    titulos = re.findall(r"^#{2,4} (.+)$", rfc[:posicao], re.M)
    return titulos[-1].replace("`", "") if titulos else "RFC-004"


def largo(largura: int, altura: int) -> bool:
    """Diagrama que vai para a página paisagem: reduzido pelo Mermaid e deitado.

    No retrato, o que o Mermaid reduziu à página dele sai com a letra menor. Na
    paisagem, a letra cresce na proporção da largura sobre a altura, até 1,5
    vez; abaixo de 1,4 o ganho não paga a página a mais.
    """
    reduzido = largura >= 0.9 * LARGURA_MERMAID * ESCALA
    return reduzido and largura >= 1.4 * altura


def capa(documento: str, logo: Path) -> str:
    """Capa ABNT, um participante por linha, com a tabela da seção 1."""
    autores = "\n".join(
        f"<p>{html.escape(nome)} — {rm}</p>"
        for nome, rm in PARTICIPANTE.findall(documento)
    )
    return f"""<div class="capa">
<div>
<p><strong>FIAP — Faculdade de Informática e Administração Paulista</strong></p>
<p>15SOAT — Pós-Graduação em Arquitetura de Software</p>
</div>
<div>
<img class="logo" src="{html.escape(str(logo))}" alt="Logo PytStop"/>
<p class="titulo">Tech Challenge — Fase 4</p>
<p class="subtitulo">PytStop — Microsserviços com Saga Orquestrada</p>
<p><em>Documento de Entrega</em></p>
</div>
<div class="autores">
{autores}
</div>
<div>
<p>São Paulo — 2026</p>
</div>
</div>

<div id="pos-capa"></div>

"""


def preparar(raiz: Path, repo: str, branch: str) -> str:
    """Capa e documento num markdown só, sem editar os originais."""
    documento = (raiz / DOCUMENTO).read_text()
    conferir_diagramas(
        documento, (raiz / RFC).read_text(), (raiz / "README.md").read_text()
    )
    corpo = reescrever_links(documento, repo, branch, (raiz / DOCUMENTO).parent, raiz)
    return capa(documento, raiz / LOGO) + corpo


def ajustar_html(pagina: str) -> str:
    """Sumário depois da capa e código inline que quebra entre palavras."""
    # Fatias iguais do pandoc espremeriam as colunas de texto.
    pagina = re.sub(r"<colgroup>.*?</colgroup>", "", pagina, flags=re.S)
    nav = re.search(r'<nav id="TOC".*?</nav>', pagina, flags=re.S)
    if nav is None:
        raise ValueError("sumário ausente no HTML do pandoc")
    pagina = pagina.replace(nav.group(0), "", 1)
    pagina, trocas = re.subn(
        r'<div id="pos-capa">\s*</div>',
        lambda m: m.group(0) + nav.group(0),
        pagina,
        count=1,
    )
    if trocas != 1:
        raise ValueError("marcador pos-capa ausente: o sumário ficaria antes da capa")
    # Sem <wbr>, o identificador longo alarga a coluna ou parte em qualquer letra.
    return re.sub(
        r"(?<!<pre>)<code>(.*?)</code>",
        lambda m: f"<code>{QUEBRA.sub('<wbr>', m.group(1))}</code>",
        pagina,
        flags=re.S,
    )


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
    rfc = (raiz / RFC).read_text()
    with tempfile.TemporaryDirectory(prefix="pytstop-entrega-") as pasta:
        tmp = Path(pasta)
        numeros = itertools.count(1)

        def renderizar(match: re.Match[str]) -> str:
            # Weasyprint não pagina imagem: o max-height do CSS evita o corte
            # no rodapé. A escala 1,25 dá de 190 a 335 ppi na página (a menor,
            # na paisagem), nítido no zoom; a letra impressa depende da largura
            # que o diagrama ocupa.
            numero = next(numeros)
            fonte, imagem = (
                tmp / f"diagrama-{numero}.mmd",
                tmp / f"diagrama-{numero}.png",
            )
            fonte.write_text(match.group(1))
            executar(
                [
                    "npx",
                    "--yes",
                    MERMAID_CLI,
                    "-i",
                    str(fonte),
                    "-o",
                    str(imagem),
                    "-w",
                    str(LARGURA_MERMAID),
                    "-s",
                    str(ESCALA),
                    "-b",
                    "white",
                ]
            )
            largura, altura = struct.unpack(">II", imagem.read_bytes()[16:24])
            classe = "diagrama paisagem" if largo(largura, altura) else "diagrama"
            titulo = html.escape(secao_da_rfc(rfc, match.group(1)))
            legenda = f"Diagrama {numero} — RFC-004, {titulo}."
            return (
                f'<div class="{classe}">\n\n'
                f'<img src="{html.escape(str(imagem))}" alt="Diagrama {numero}"/>\n\n'
                f'<p class="legenda">{legenda}</p>\n\n</div>\n'
            )

        (tmp / "entrega.md").write_text(MERMAID.sub(renderizar, texto))
        executar(
            [
                "pandoc",
                str(tmp / "entrega.md"),
                # Âncoras como as do GitHub: os links internos do documento
                # (#7-estratégia-da-saga) valem no repositório e no PDF.
                "--from",
                "markdown+gfm_auto_identifiers",
                "-o",
                str(tmp / "entrega.html"),
                "--standalone",
                "--toc",
                "--toc-depth=2",
                "-V",
                "lang=pt-BR",
                "-V",
                "toc-title=Sumário",
                # Mantém o CSS padrão do pandoc, a tipografia das fases 1 a 3.
                "-V",
                "document-css=true",
                "--metadata",
                "pagetitle=PytStop — Entrega Fase 4",
                "--css",
                str(Path(__file__).with_name("pdf.css")),
            ]
        )
        pagina = ajustar_html((tmp / "entrega.html").read_text())
        (tmp / "entrega.html").write_text(pagina)
        executar(["weasyprint", str(tmp / "entrega.html"), str(destino)])
    print(f"PDF {'final' if args.final else 'de ensaio'} gerado: {destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
