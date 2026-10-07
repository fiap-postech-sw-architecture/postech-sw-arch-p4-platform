"""Consistencia entre dashboards, alertas e a documentacao de observabilidade/.

O ADR-043 pede cada painel com descricao e documentado, no formato da fase 3;
este teste e a trava: painel sem descricao, painel ou consulta fora do
observabilidade/README.md, ou regra de alerta com UID, titulo, consulta,
severidade, janela, "sem dado" ou "onde" diferentes dos da tabela de alertas
reprovam. Tambem reprova arquivo de alerta que o Grafana do cluster nao monta
ou que o compose monta sem poder usar (as regras do Kong), e filtro por fila
que nao seleciona o grupo certo de filas do definitions.json do RabbitMQ.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

RAIZ = Path(__file__).resolve().parents[1]
OBSERVABILIDADE = RAIZ / "observabilidade"
DOC_CRU = (OBSERVABILIDADE / "README.md").read_text(encoding="utf-8")
# Tabela Markdown escapa o | das consultas.
DOC = DOC_CRU.replace("\\|", "|")
DASHBOARDS = sorted((OBSERVABILIDADE / "dashboards").glob("*.json"))
ALERTAS = sorted((OBSERVABILIDADE / "grafana").glob("alertas*.yaml"))
# Onde cada arquivo de alertas e provisionado: alertas.yaml no cluster e no
# compose; alertas-cluster.yaml so no cluster (depende do Kong).
ONDE = {"alertas.yaml": "cluster e compose", "alertas-cluster.yaml": "só cluster"}
# (arquivo, regra) de todas as regras de alerta.
REGRAS: list[tuple[str, dict[str, Any]]] = [
    (arquivo.name, regra)
    for arquivo in ALERTAS
    for grupo in yaml.safe_load(arquivo.read_text(encoding="utf-8"))["groups"]
    for regra in grupo["rules"]
]
IDS_DAS_REGRAS = [regra["uid"] for _, regra in REGRAS]
DEFINITIONS = json.loads(
    (RAIZ / "k8s" / "base" / "rabbitmq" / "definitions.json").read_text(
        encoding="utf-8"
    )
)
FILAS = {fila["name"] for fila in DEFINITIONS["queues"]}


def ligadas_a(*exchanges: str) -> set[str]:
    return {
        b["destination"] for b in DEFINITIONS["bindings"] if b["source"] in exchanges
    }


# Grupos de filas pela topologia, nao pelo nome: e o oraculo dos filtros.
TRABALHO = ligadas_a("pytstop.comandos", "pytstop.eventos")
RETRY = ligadas_a("pytstop.retry")
DLQ = ligadas_a("pytstop.dlx")
# Painel ou regra com filtro no label queue -> filas que ele deve mostrar.
FILTRO_DE_FILA = {
    "Mensagens nas DLQs": DLQ,
    "Consumidores por fila": TRABALHO,
    "Mensagens prontas por fila": TRABALHO,
    "Mensagens em processamento (sem ack)": TRABALHO,
    "Aguardando retry e DLQ": RETRY | DLQ,
    "pytstop-dlq-com-mensagens": DLQ,
}


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


@pytest.mark.parametrize("regra", [regra for _, regra in REGRAS], ids=IDS_DAS_REGRAS)
def test_regra_de_alerta_esta_na_tabela_com_a_consulta(regra: dict[str, Any]) -> None:
    (consulta,) = [d["model"]["expr"] for d in regra["data"] if "expr" in d["model"]]

    assert f"| `{regra['uid']}` | {regra['title']} |" in DOC
    assert f"`{consulta}`" in DOC


@pytest.mark.parametrize(("arquivo", "regra"), REGRAS, ids=IDS_DAS_REGRAS)
def test_tabela_de_alertas_diz_o_que_a_regra_faz(
    arquivo: str, regra: dict[str, Any]
) -> None:
    linha = linhas_de_alerta()[regra["uid"]]

    assert linha["Sem dado"] == regra["noDataState"]
    assert linha["Severidade"] == regra["labels"]["severity"]
    assert linha["Janela"] == f"{int(regra['for'].removesuffix('m'))} min"
    assert linha["Onde"] == ONDE[arquivo]


def test_tabela_de_alertas_nao_tem_regra_que_nenhum_arquivo_define() -> None:
    assert set(linhas_de_alerta()) == set(IDS_DAS_REGRAS)


def test_grafana_do_cluster_monta_todos_os_alertas_e_o_compose_so_os_comuns() -> None:
    kustomization = yaml.safe_load(
        (OBSERVABILIDADE / "kustomization.yaml").read_text(encoding="utf-8")
    )
    arquivos = {
        gerador["name"]: gerador["files"]
        for gerador in kustomization["configMapGenerator"]
    }
    compose = yaml.safe_load(
        (RAIZ / "compose" / "docker-compose.yml").read_text(encoding="utf-8")
    )
    montados = " ".join(compose["services"]["grafana"]["volumes"])

    assert sorted(arquivos["grafana-alerting"]) == [
        f"grafana/{a.name}" for a in ALERTAS
    ]
    assert "grafana/alertas.yaml:" in montados
    assert "alertas-cluster" not in montados


def consultas_com_filtro_de_fila() -> list[Any]:
    consultas = [
        (painel["title"], alvo["expr"])
        for arquivo in DASHBOARDS
        for painel in json.loads(arquivo.read_text(encoding="utf-8"))["panels"]
        for alvo in painel["targets"]
    ] + [
        (regra["uid"], dado["model"]["expr"])
        for _, regra in REGRAS
        for dado in regra["data"]
        if "expr" in dado["model"]
    ]
    return [
        pytest.param(nome, expr, id=nome)
        for nome, expr in consultas
        if re.search(r"queue[=!]~", expr)
    ]


@pytest.mark.parametrize(("nome", "expr"), consultas_com_filtro_de_fila())
def test_filtro_de_fila_seleciona_o_grupo_certo_da_topologia(
    nome: str, expr: str
) -> None:
    # Matcher do PromQL e RE2 ancorado nas duas pontas (re.fullmatch). Uma fila
    # nova no definitions.json com nome fora do padrao, ou um padrao que ficou
    # para tras quando a topologia mudou, reprova aqui.
    (operador, padrao), *outros = re.findall(r'queue(=~|!~)"([^"]*)"', expr)
    casam = {fila for fila in FILAS if re.fullmatch(padrao, fila)}

    assert outros == []
    assert FILAS == TRABALHO | RETRY | DLQ
    assert (casam if operador == "=~" else FILAS - casam) == FILTRO_DE_FILA[nome]
