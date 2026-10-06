"""Consistencia entre dashboards, alertas e a documentacao de observabilidade/.

O ADR-043 pede cada painel com descricao e documentado, no formato da fase 3;
este teste e a trava: painel sem descricao, painel ou consulta fora do
observabilidade/README.md, ou regra de alerta sem UID, titulo e consulta na
tabela de alertas, ou com severidade, janela ou "sem dado" diferentes dos da
tabela, reprovam.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

OBSERVABILIDADE = Path(__file__).resolve().parents[1] / "observabilidade"
DOC_CRU = (OBSERVABILIDADE / "README.md").read_text(encoding="utf-8")
# Tabela Markdown escapa o | das consultas.
DOC = DOC_CRU.replace("\\|", "|")
DASHBOARDS = sorted((OBSERVABILIDADE / "dashboards").glob("*.json"))
REGRAS: list[dict[str, Any]] = [
    regra
    for grupo in yaml.safe_load(
        (OBSERVABILIDADE / "grafana" / "alertas.yaml").read_text(encoding="utf-8")
    )["groups"]
    for regra in grupo["rules"]
]


def linhas_de_alerta() -> dict[str, dict[str, str]]:
    """uid -> {coluna: celula} da tabela "Regras de alerta" do README."""
    secao = DOC_CRU.split("\n## Regras de alerta", 1)[1].split("\n## ", 1)[0]
    tabela = [linha for linha in secao.splitlines() if linha.startswith("|")]
    # Divide so nas barras sem escape: a consulta pode levar \|.
    celulas = [
        [c.strip() for c in re.split(r"(?<!\\)\|", linha)[1:-1]] for linha in tabela
    ]
    colunas = celulas[0]
    return {c[0].strip("`"): dict(zip(colunas, c, strict=True)) for c in celulas[2:]}


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


@pytest.mark.parametrize("regra", REGRAS, ids=lambda r: r["uid"])
def test_tabela_de_alertas_diz_o_que_a_regra_faz(regra: dict[str, Any]) -> None:
    linha = linhas_de_alerta()[regra["uid"]]

    assert linha["Sem dado"] == regra["noDataState"]
    assert linha["Severidade"] == regra["labels"]["severity"]
    assert linha["Janela"] == f"{int(regra['for'].removesuffix('m'))} min"
