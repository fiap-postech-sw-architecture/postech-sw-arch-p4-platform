"""Consistencia entre dashboards, alertas e a documentacao de observabilidade/.

O ADR-043 pede cada painel com descricao e documentado, no formato da fase 3;
este teste e a trava: painel sem descricao, painel ou consulta fora do
observabilidade/README.md, ou regra de alerta sem UID, titulo e consulta na
tabela de alertas reprovam.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

OBSERVABILIDADE = Path(__file__).resolve().parents[1] / "observabilidade"
# Tabela Markdown escapa o | das consultas.
DOC = (OBSERVABILIDADE / "README.md").read_text(encoding="utf-8").replace("\\|", "|")
DASHBOARDS = sorted((OBSERVABILIDADE / "dashboards").glob("*.json"))
REGRAS: list[dict[str, Any]] = [
    regra
    for grupo in yaml.safe_load(
        (OBSERVABILIDADE / "grafana" / "alertas.yaml").read_text(encoding="utf-8")
    )["groups"]
    for regra in grupo["rules"]
]


def paineis() -> list[Any]:
    return [
        pytest.param(painel, id=f"{arquivo.stem}-{painel['id']}")
        for arquivo in DASHBOARDS
        for painel in json.loads(arquivo.read_text(encoding="utf-8"))["panels"]
    ]


@pytest.mark.parametrize("arquivo", DASHBOARDS, ids=lambda p: p.stem)
def test_dashboard_documentado_com_uid_e_titulo(arquivo: Path) -> None:
    dashboard = json.loads(arquivo.read_text(encoding="utf-8"))

    assert f"## Dashboard {dashboard['title']} (`{dashboard['uid']}`)" in DOC


@pytest.mark.parametrize("painel", paineis())
def test_painel_tem_descricao_e_esta_na_tabela_com_as_consultas(
    painel: dict[str, Any],
) -> None:
    assert painel["description"].strip()
    assert f"| {painel['id']} | {painel['title']} |" in DOC
    for alvo in painel["targets"]:
        assert f"`{alvo['expr']}`" in DOC, alvo["expr"]


@pytest.mark.parametrize("regra", REGRAS, ids=lambda r: r["uid"])
def test_regra_de_alerta_esta_na_tabela_com_a_consulta(regra: dict[str, Any]) -> None:
    (consulta,) = [d["model"]["expr"] for d in regra["data"] if "expr" in d["model"]]

    assert f"| `{regra['uid']}` | {regra['title']} |" in DOC
    assert f"`{consulta}`" in DOC
