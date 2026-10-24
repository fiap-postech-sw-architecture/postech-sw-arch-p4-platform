"""Prova o percurso primeiro-pai e a conferência do CD no commit coletado."""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from scripts.evidencias import coletar
from scripts.evidencias.verificar import verificar_github


def test_primeiro_pai_nao_visita_branch_lateral(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chamadas: list[str] = []
    dados: dict[str, Any] = {
        "repos/grupo/repo/git/commits/a": {
            "sha": "a",
            "parents": [{"sha": "b"}, {"sha": "lateral"}],
        },
        "repos/grupo/repo/git/commits/b": {"sha": "b", "parents": []},
        "repos/grupo/repo/commits/a/pulls": [
            {
                "number": 1,
                "merged_at": "2026-10-01",
                "merge_commit_sha": "a",
                "base": {"ref": "main"},
                "html_url": "https://github.com/grupo/repo/pull/1",
            }
        ],
        "repos/grupo/repo/commits/b/pulls": [],
    }

    def api(caminho: str, filtro: str = ".") -> Any:
        chamadas.append(caminho)
        return dados[caminho]

    monkeypatch.setattr(coletar, "api", api)
    assert coletar.primeiro_pai("grupo/repo", "a") == [
        {"sha": "a", "prs": [1], "pais": ["b", "lateral"]},
        {"sha": "b", "prs": [], "pais": []},
    ]
    assert not any("lateral" in chamada for chamada in chamadas)


def test_pr_associado_sem_ser_merge_da_main_nao_prova_origem(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def api(caminho: str, filtro: str = ".") -> Any:
        if caminho.endswith("/pulls"):
            return [
                {
                    "number": 9,
                    "merged_at": "2026-10-01",
                    "merge_commit_sha": "outro",
                    "base": {"ref": "main"},
                }
            ]
        return {"sha": "a", "parents": []}

    monkeypatch.setattr(coletar, "api", api)
    assert coletar.primeiro_pai("grupo/repo", "a") == [
        {"sha": "a", "prs": [], "pais": []}
    ]


@pytest.mark.parametrize(
    ("alteracao", "esperado"),
    [
        ({"publico": False}, "público"),
        ({"regras": []}, "proteção"),
        (
            {
                "cd": {
                    "head_sha": "velho",
                    "status": "completed",
                    "conclusion": "success",
                }
            },
            "CD",
        ),
        ({"primeiro_pai": [{"sha": "a", "prs": [], "pais": []}]}, "PR"),
        ({"tag": None}, "tag"),
    ],
)
def test_fechamento_reprova_metadados_incompletos(
    alteracao: dict[str, Any], esperado: str
) -> None:
    repo: dict[str, Any] = {
        "repo": "grupo/repo",
        "publico": True,
        "head": "a",
        "tag": "a",
        "regras": [
            {"type": "pull_request"},
            {
                "type": "required_status_checks",
                "parameters": {"required_status_checks": [{"context": "ci"}]},
            },
        ],
        "cd": {"head_sha": "a", "status": "completed", "conclusion": "success"},
        "primeiro_pai": [{"sha": "a", "prs": [1], "pais": ["b", "lateral"]}],
    }
    repo.update(alteracao)
    assert any(
        esperado in erro
        for erro in verificar_github({"repositorios": [repo]}, final=True)
    )


def test_so_bootstrap_conhecido_sem_pais_dispensa_pr() -> None:
    snapshot: dict[str, Any] = {
        "repositorios": [
            {
                "repo": "fiap-postech-sw-architecture/postech-sw-arch-p4-platform",
                "head": "16f93ce23094627e16ff5a387b86bc5251722e12",
                "primeiro_pai": [
                    {
                        "sha": "16f93ce23094627e16ff5a387b86bc5251722e12",
                        "prs": [],
                        "pais": [],
                    }
                ],
            }
        ]
    }
    assert not any("commit sem PR" in e for e in verificar_github(snapshot, final=True))
    snapshot["repositorios"][0]["primeiro_pai"][0]["pais"] = ["outro"]
    assert any("commit sem PR" in e for e in verificar_github(snapshot, final=True))


def test_cd_verde_com_deploy_pulado_nao_comprova_kubernetes() -> None:
    snapshot = {
        "repositorios": [
            {
                "repo": "grupo/repo",
                "publico": True,
                "head": "a",
                "tag": "a",
                "regras": [
                    {"type": "pull_request"},
                    {
                        "type": "required_status_checks",
                        "parameters": {"required_status_checks": [{"context": "ci"}]},
                    },
                ],
                "primeiro_pai": [{"sha": "a", "prs": [1]}],
                "cd": {"head_sha": "a", "status": "completed", "conclusion": "success"},
                "jobs": [
                    {
                        "name": "deploy-kind",
                        "status": "completed",
                        "conclusion": "skipped",
                    }
                ],
            }
        ]
    }
    assert any("deploy-kind" in e for e in verificar_github(snapshot, final=True))


def test_arvore_truncada_interrompe_coleta(monkeypatch: pytest.MonkeyPatch) -> None:
    def api(caminho: str, filtro: str = ".") -> Any:
        if "/git/trees/" in caminho:
            return {"truncated": True, "tree": []}
        return {"visibility": "public", "sha": "a"}

    monkeypatch.setattr(coletar, "api", api)
    with pytest.raises(RuntimeError, match="truncada"):
        coletar.coletar("grupo/repo")


def test_fase_3_entra_so_com_a_arvore_e_sem_exigencias_de_fechamento(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(coletar, "coletar", lambda repo: {"repo": repo})
    monkeypatch.setattr(coletar, "arvore_da_main", lambda repo: ("h", ["docs/x.md"]))
    saida = tmp_path / "github.json"
    monkeypatch.setattr(sys, "argv", ["coletar", "--output", str(saida)])
    assert coletar.main() == 0
    snapshot = json.loads(saida.read_text())
    assert [r["repo"] for r in snapshot["repositorios"]] == list(coletar.REPOS)
    assert snapshot["referencias"] == [
        {"repo": coletar.REFERENCIAS[0], "head": "h", "arvore": ["docs/x.md"]}
    ]
    erros = verificar_github(snapshot, final=True)
    assert erros
    assert not any(erro.startswith(f"{coletar.REFERENCIAS[0]}:") for erro in erros)
