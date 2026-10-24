#!/usr/bin/env python3
"""Confere requisitos e links do pacote.

--final também exige identificação, vídeo e texto sem marcas preliminares.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit


def _ids(texto: str) -> set[str]:
    ids = set(re.findall(r"\b(?:RF|RNF|RN)-\d{3}\b", texto))
    for prefixo, inicio, fim in re.findall(
        r"\b(RNF|RF|RN)-(\d{3})\s+a\s+(?:\1-)?(\d{3})\b", texto
    ):
        ids.update(f"{prefixo}-{n:03d}" for n in range(int(inicio), int(fim) + 1))
    return ids


# Marcas do texto preliminar do pacote; a versão final não pode levar nenhuma.
# O \b inicial evita falso positivo dentro de palavra ("independente").
RASCUNHO = re.compile(
    r"\b(?:vers[aã]o (?:de ensaio|preliminar)|documento de ensaio|durante o ensaio"
    r"|inserir o link|ainda ser[aá] gravado|n[aã]o serve para submiss[aã]o"
    r"|antes da submiss[aã]o|em coleta|a coletar|aguarda|pendente"
    r"|dependem do grupo)",
    re.IGNORECASE,
)
# Documentos que vão para o PDF e a matriz que eles citam.
PRELIMINARES = (
    "docs/entrega/fase4/entrega-fase-4.md",
    "INDICE-DA-ENTREGA.md",
    "docs/entrega/matriz-de-rastreabilidade.md",
)


# Exceções auditadas em docs/entrega/fase4/evidencias/README.md.
BOOTSTRAPS = {
    "fiap-postech-sw-architecture/postech-sw-arch-p4-os-service": (
        "4ad6f3d4787fc959563c08a978f6c7d055f00937"
    ),
    "fiap-postech-sw-architecture/postech-sw-arch-p4-billing-service": (
        "68f326dfab12200f06e2b5b4765cc09428cfd349"
    ),
    "fiap-postech-sw-architecture/postech-sw-arch-p4-execution-service": (
        "b77d56467fdefb32fbc315b109ad6697c0546d14"
    ),
    "fiap-postech-sw-architecture/postech-sw-arch-p4-platform": (
        "16f93ce23094627e16ff5a387b86bc5251722e12"
    ),
}


def verificar_github(github: dict[str, Any], *, final: bool = False) -> list[str]:
    """Confere o snapshot; lacunas remotas bloqueiam somente o fechamento final."""
    erros: list[str] = []
    if not final:
        return erros
    for repo in github.get("repositorios", []):
        nome = repo["repo"]
        if not repo.get("publico"):
            erros.append(f"{nome}: repositório não público")
        regras = {
            regra["type"]: regra.get("parameters") for regra in repo.get("regras", [])
        }
        checks = (regras.get("required_status_checks") or {}).get(
            "required_status_checks"
        )
        if "pull_request" not in regras or not checks:
            erros.append(f"{nome}: proteção sem PR ou checks obrigatórios")
        cd = repo.get("cd") or {}
        if (
            cd.get("head_sha") != repo.get("head")
            or cd.get("status") != "completed"
            or cd.get("conclusion") != "success"
        ):
            erros.append(f"{nome}: CD não aprovado no HEAD da main")
        jobs_verdes = {
            job["name"].split(" / ")[-1]
            for job in repo.get("jobs", [])
            if job["status"] == "completed" and job["conclusion"] == "success"
        }
        obrigatorios = {"deploy-kind", *(check["context"] for check in checks or [])}
        for job in sorted(obrigatorios - jobs_verdes):
            erros.append(f"{nome}: job obrigatório sem sucesso no CD: {job}")
        commits = repo.get("primeiro_pai", [])
        if not commits or commits[0]["sha"] != repo.get("head"):
            erros.append(f"{nome}: primeiro-pai ausente ou divergente do HEAD")
        for commit in commits:
            bootstrap = (
                commit["sha"] == BOOTSTRAPS.get(nome) and commit.get("pais") == []
            )
            if not commit["prs"] and not bootstrap:
                erros.append(f"{nome}: commit sem PR de origem: {commit['sha']}")
        if repo.get("tag") != repo.get("head"):
            erros.append(f"{nome}: tag entrega-fase-4 ausente ou divergente do HEAD")
    return erros


def verificar(
    raiz: Path, *, final: bool = False, github: dict[str, Any] | None = None
) -> list[str]:
    raiz = raiz.resolve()
    erros: list[str] = []
    fonte = raiz / "docs/requisitos/fase4/gap-analysis-fase-4.md"
    requisitos = {
        match[1]
        for linha in fonte.read_text().splitlines()
        if (match := re.match(r"\| ((?:RF|RNF|RN)-\d{3}) \|", linha))
    }
    if not requisitos:
        erros.append("gap analysis: nenhum requisito encontrado")
    documento = raiz / "docs/entrega/fase4/entrega-fase-4.md"
    if not documento.is_file():
        erros.append("arquivo ausente: docs/entrega/fase4/entrega-fase-4.md")
    for nome, relativo in (
        ("matriz", "docs/entrega/matriz-de-rastreabilidade.md"),
        ("índice", "INDICE-DA-ENTREGA.md"),
    ):
        arquivo = raiz / relativo
        if not arquivo.is_file():
            erros.append(f"arquivo ausente: {relativo}")
            continue
        for ausente in sorted(requisitos - _ids(arquivo.read_text())):
            erros.append(f"{nome}: requisito ausente {ausente}")

    arquivos = [
        raiz / "INDICE-DA-ENTREGA.md",
        *sorted((raiz / "docs/entrega").rglob("*.md")),
    ]
    for arquivo in arquivos:
        if not arquivo.is_file():
            continue
        for destino in re.findall(r"\[[^\]\n]+\]\(([^)\n]+)\)", arquivo.read_text()):
            url = urlsplit(destino)
            if url.scheme or url.netloc:
                match = re.fullmatch(
                    r"/([^/]+/[^/]+)/(blob|tree)/([^/]+)/(.+)", unquote(url.path)
                )
                if github is not None and url.netloc == "github.com" and match:
                    repo, _, ref, caminho = match.groups()
                    citados = (*github["repositorios"], *github.get("referencias", []))
                    prova = next((r for r in citados if r["repo"] == repo), None)
                    if prova is None:
                        erros.append(f"metadados GitHub ausentes: {repo}")
                    elif (
                        ref not in ("main", prova.get("head"))
                        and not (
                            ref == "entrega-fase-4"
                            and prova.get("tag") == prova.get("head")
                        )
                    ) or caminho not in prova["arvore"]:
                        erros.append(f"link GitHub ausente: {destino}")
                evento = re.fullmatch(
                    r"/([^/]+/[^/]+)/(pull|actions/runs)/(\d+)", url.path
                )
                if github is not None and url.netloc == "github.com" and evento:
                    repo, tipo, numero = evento.groups()
                    prova = next(
                        (r for r in github["repositorios"] if r["repo"] == repo), None
                    )
                    campo = "prs_citados" if tipo == "pull" else "runs_citados"
                    if prova is None or int(numero) not in prova.get(campo, []):
                        erros.append(f"link GitHub ausente: {destino}")
                continue
            alvo = (
                (arquivo.parent / unquote(url.path)).resolve() if url.path else arquivo
            )
            if not alvo.is_relative_to(raiz):
                erros.append(
                    f"{arquivo.relative_to(raiz)}: link fora do repositório: {destino}"
                )
            elif not alvo.exists():
                erros.append(f"{arquivo.relative_to(raiz)}: link ausente: {destino}")
            elif url.fragment and alvo.suffix == ".md":
                titulos = re.findall(r"^#+\s+(.+)$", alvo.read_text(), re.MULTILINE)
                ancoras = {
                    re.sub(r"[^\w -]", "", titulo.lower()).replace(" ", "-")
                    for titulo in titulos
                }
                if unquote(url.fragment) not in ancoras:
                    erros.append(
                        f"{arquivo.relative_to(raiz)}: âncora ausente: {destino}"
                    )

    if github is not None:
        erros.extend(verificar_github(github, final=final))
    if final:
        from scripts.evidencias.coletar import REFERENCIAS, REPOS

        presentes = {r["repo"] for r in (github or {}).get("repositorios", [])}
        for repo in sorted(set(REPOS) - presentes):
            erros.append(f"final: metadados GitHub ausentes: {repo}")
        for nome in (
            "bdd-resumo.md",
            "coverage.md",
            "observabilidade.md",
            "mp-sandbox.md",
            "newman-resumo.md",
        ):
            prova = documento.parent / "evidencias" / nome
            if not prova.is_file() or not prova.read_text().strip():
                erros.append(f"final: evidência ausente: {nome}")
        for relativo in PRELIMINARES:
            arquivo = raiz / relativo
            texto = arquivo.read_text() if arquivo.is_file() else ""
            # Código não é marca: `AGUARDANDO_DECISAO` é etapa da saga, e o
            # Mermaid copiado da RFC traz etapas e a situação "pendente".
            sem_blocos = re.sub(r"```.*?```", "", texto, flags=re.S)
            marcas = RASCUNHO.findall(re.sub(r"`[^`\n]*`", "", sem_blocos))
            for marca in sorted({m.lower() for m in marcas}):
                erros.append(f"final: texto preliminar em {relativo}: {marca}")
        texto = documento.read_text() if documento.is_file() else ""
        if not re.search(r"\|[^|\n]+\|\s*RM\d+\s*\|", texto):
            erros.append("final: identificação dos participantes ausente")
        if not re.search(
            r"https://(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/|vimeo\.com/)\S+",
            texto,
        ):
            erros.append("final: link do vídeo ausente")
        # A tag é da fase 4; o repositório da fase 3 continua citado pela main.
        fora = "|".join(map(re.escape, REFERENCIAS))
        if any(
            re.search(
                rf"https://github\.com/(?!(?:{fora})/)[^/]+/[^/]+/(?:blob|tree)/main"
                r"(?:[/)#?\s]|$)",
                p.read_text(),
            )
            for p in arquivos
            if p.is_file()
        ):
            erros.append("final: link de código ainda aponta para main")
    return erros


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--final", action="store_true")
    parser.add_argument(
        "--github", type=Path, help="snapshot de scripts.evidencias.coletar"
    )
    args = parser.parse_args()
    github = json.loads(args.github.read_text()) if args.github else None
    erros = verificar(
        Path(__file__).resolve().parents[2], final=args.final, github=github
    )
    for erro in erros:
        print(erro)
    if not erros:
        print("Pacote conferido: requisitos e links locais presentes.")
    return int(bool(erros))


if __name__ == "__main__":
    raise SystemExit(main())
