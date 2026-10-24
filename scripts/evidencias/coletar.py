"""Coleta metadados públicos de fechamento, sem alterar o GitHub.

Uso: uv run python -m scripts.evidencias.coletar --output /tmp/github-fase4.json
Requer gh autenticado. A saída não contém autores, mensagens, eventos ou segredos.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil

# Executáveis resolvidos no PATH; argumentos separados, sem shell.
import subprocess  # nosec B404
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPOS = tuple(
    f"fiap-postech-sw-architecture/postech-sw-arch-p4-{nome}"
    for nome in ("os-service", "billing-service", "execution-service", "platform")
)
# Só citados no pacote: a árvore da main confere os links, sem as exigências de
# fechamento dos quatro repositórios da fase 4.
REFERENCIAS = ("fiap-postech-sw-architecture/postech-sw-arch-p3",)


def api(caminho: str, filtro: str = ".") -> Any:
    """Consulta somente GET; erros de acesso interrompem a coleta."""
    gh = shutil.which("gh")
    if not gh:
        raise RuntimeError("gh não encontrado no PATH")
    processo = subprocess.run(  # noqa: S603  # nosec B603
        [gh, "api", "--method", "GET", caminho, "--jq", filtro],
        capture_output=True,
        text=True,
        check=False,
    )
    if processo.returncode:
        raise RuntimeError(f"consulta GitHub falhou: {caminho}")
    return json.loads(processo.stdout)


def primeiro_pai(repo: str, head: str) -> list[dict[str, Any]]:
    """Percorre toda a main pelo primeiro pai e identifica o PR de cada merge."""
    commits = []
    sha = head
    while sha:
        commit = api(
            f"repos/{repo}/git/commits/{sha}", "{sha, parents: [.parents[] | {sha}]}"
        )
        prs = api(
            f"repos/{repo}/commits/{sha}/pulls",
            "[.[] | {number, merged_at, merge_commit_sha, base: {ref: .base.ref}}]",
        )
        commits.append(
            {
                "sha": sha,
                "pais": [pai["sha"] for pai in commit["parents"]],
                "prs": [
                    pr["number"]
                    for pr in prs
                    if pr["merged_at"]
                    and pr["merge_commit_sha"] == sha
                    and pr["base"]["ref"] == "main"
                ],
            }
        )
        sha = commit["parents"][0]["sha"] if commit["parents"] else ""
    return commits


def arvore_da_main(repo: str) -> tuple[str, list[str]]:
    """HEAD da main e todos os caminhos da árvore dele."""
    base = f"repos/{repo}"
    head = api(f"{base}/commits/main", "{sha}")["sha"]
    arvore = api(
        f"{base}/git/trees/{head}?recursive=1", "{truncated, tree: [.tree[] | {path}]}"
    )
    if arvore["truncated"]:
        raise RuntimeError(f"árvore GitHub truncada: {repo}")
    return head, [item["path"] for item in arvore["tree"]]


def coletar(repo: str) -> dict[str, Any]:
    """Preserva apenas campos necessários à conferência de fechamento."""
    base = f"repos/{repo}"
    metadados = api(base, "{visibility}")
    head, caminhos = arvore_da_main(repo)
    # Ausência de workflow/tag é uma lacuna, não erro de transporte.
    workflows = api(
        f"{base}/actions/workflows?per_page=100",
        "{workflows: [.workflows[] | {id,path}]}",
    )["workflows"]
    cd = next((w for w in workflows if w["path"] == ".github/workflows/cd.yml"), None)
    runs = (
        api(
            f"{base}/actions/workflows/{cd['id']}/runs?branch=main&per_page=1",
            "{workflow_runs: [.workflow_runs[] | "
            "{id,head_sha,status,conclusion,html_url,event}]}",
        )["workflow_runs"]
        if cd
        else []
    )
    run = runs[0] if runs else None
    jobs = (
        api(
            f"{base}/actions/runs/{run['id']}/jobs?per_page=100",
            "{jobs: [.jobs[] | {name,status,conclusion,html_url}]}",
        )["jobs"]
        if run
        else []
    )
    tags = api(f"{base}/tags?per_page=100", "[.[] | {name,commit: {sha: .commit.sha}}]")
    tag = next(
        (t["commit"]["sha"] for t in tags if t["name"] == "entrega-fase-4"), None
    )
    raiz = Path(__file__).resolve().parents[2]
    arquivos = [
        raiz / "INDICE-DA-ENTREGA.md",
        *sorted((raiz / "docs/entrega").rglob("*.md")),
    ]
    texto = "\n".join(p.read_text() for p in arquivos if p.is_file())
    prs_citados = sorted(
        {
            int(n)
            for n in re.findall(
                re.escape(f"https://github.com/{repo}/pull/") + r"(\d+)", texto
            )
        }
    )
    runs_citados = sorted(
        {
            int(n)
            for n in re.findall(
                re.escape(f"https://github.com/{repo}/actions/runs/") + r"(\d+)", texto
            )
        }
    )
    for numero in prs_citados:
        api(f"{base}/pulls/{numero}", "{number}")
    for numero in runs_citados:
        api(f"{base}/actions/runs/{numero}", "{id}")
    return {
        "repo": repo,
        "prs_citados": prs_citados,
        "runs_citados": runs_citados,
        "publico": metadados["visibility"] == "public",
        "head": head,
        "regras": [
            {"type": r["type"], "parameters": r.get("parameters")}
            for r in api(f"{base}/rules/branches/main", "[.[] | {type,parameters}]")
        ],
        "primeiro_pai": primeiro_pai(repo, head),
        "cd": {
            k: run[k]
            for k in ("id", "head_sha", "status", "conclusion", "html_url", "event")
        }
        if run
        else None,
        "jobs": [
            {k: job[k] for k in ("name", "status", "conclusion", "html_url")}
            for job in jobs
        ],
        "tag": tag,
        "arvore": caminhos,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    resultado: dict[str, Any] = {
        "coletado_em": datetime.now(UTC).isoformat(),
        "repositorios": [],
        "referencias": [],
    }
    for repo in REPOS:
        print(f"Coletando {repo}", flush=True)
        resultado["repositorios"].append(coletar(repo))
    for repo in REFERENCIAS:
        print(f"Coletando a árvore de {repo}", flush=True)
        head, caminhos = arvore_da_main(repo)
        resultado["referencias"].append(
            {"repo": repo, "head": head, "arvore": caminhos}
        )
    args.output.write_text(json.dumps(resultado, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
