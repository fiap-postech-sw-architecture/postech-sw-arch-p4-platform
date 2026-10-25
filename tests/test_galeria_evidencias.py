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

from scripts.evidencias.coletar import REPOS

RAIZ = Path(__file__).resolve().parents[1]
PASTA = RAIZ / "docs/entrega/fase4/evidencias"
DOCUMENTO = RAIZ / "docs/entrega/fase4/entrega-fase-4.md"
# O PDF de ensaio precisa ficar abaixo de cerca de 6 MB; o resto é texto e diagrama.
TETO_DOS_PNG = 5_000_000
# Decisão de volume do PDF: os quatro dashboards que o Anexo A, A7, só lista, os dois
# de 22/10 que ele liga pelas barras diárias (os do A7, de 24/10, saem sem barra), as
# três telas do Swagger (A4), o ruleset do Billing (o A8 mostra o do OS Service) e
# o print de 20/10 do trace e a busca do mesmo dia (o A3 mostra o de 23/10, com as
# compensações, e o caminho feliz), os grafos dos CDs de 20/10 e os passos do
# deploy-kind de 23/10 (o A1 mostra o grafo do CD de 24/10 e a tabela dos quatro
# runs). Imagem que sair desta lista passa a ser embutida, e o teste reprova a
# troca silenciosa de uma imagem por um link.
SO_COM_LINK = {
    "cd-os-service-main-2026-10-20.png",
    "cd-billing-service-main-2026-10-20.png",
    "cd-execution-service-main-2026-10-20.png",
    "cd-platform-main-2026-10-20.png",
    "cd-deploy-kind-os-service-2026-10-23.png",
    "jaeger-busca-saga-2026-10-20.png",
    "swagger-os-service-2026-10-20.png",
    "swagger-billing-service-2026-10-20.png",
    "swagger-execution-service-2026-10-20.png",
    "grafana-saga-2026-10-24.png",
    "grafana-mensageria-2026-10-24.png",
    "grafana-bancos-2026-10-24.png",
    "grafana-plataforma-2026-10-24.png",
    "grafana-atendimento-2026-10-22.png",
    "grafana-pagamentos-2026-10-22.png",
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


def test_a1_cada_linha_liga_o_run_e_o_commit_do_mesmo_repositorio() -> None:
    # A tabela se refaz à mão a cada troca de runs: run de um repositório com o commit
    # de outro, ou número e SHA curto que não são os do link, passam em todos os
    # outros testes.
    texto = DOCUMENTO.read_text(encoding="utf-8")
    a1 = texto.split("## A1 — CD da `main`\n", 1)[1].split("\n## A2", 1)[0]
    linhas = [
        linha
        for linha in a1.splitlines()
        if linha.startswith("| ") and "/runs/" in linha
    ]

    assert len(linhas) == len(REPOS)
    runs: dict[str, tuple[str, str]] = {}
    for linha in linhas:
        run = re.search(
            r"\[(\d+)\]\(https://github\.com/([^/]+/[^/]+)/actions/runs/(\d+)\)", linha
        )
        commit = re.search(
            r"\[`([0-9a-f]{7})`\]\(https://github\.com/([^/]+/[^/]+)/commit/([0-9a-f]{40})\)",
            linha,
        )
        assert run, linha
        assert commit, linha
        assert run[1] == run[3], linha
        assert run[2] == commit[2], linha
        assert commit[3].startswith(commit[1]), linha
        runs[run[2]] = (run[1], commit[1])
    assert set(runs) == set(REPOS)
    # O grafo e a Fonte dele são do run e do commit da linha do OS Service.
    repo_do_os = next(repo for repo in REPOS if repo.endswith("-os-service"))
    run_do_os, commit_do_os = runs[repo_do_os]
    fonte = next(linha for linha in a1.splitlines() if linha.startswith("Fonte: "))
    assert (
        f"[run {run_do_os}](https://github.com/{repo_do_os}/actions/runs/{run_do_os})"
        in fonte
    )
    assert f"`{commit_do_os}`" in fonte
