"""Consistencia entre dashboards, alertas e a documentacao de observabilidade/.

O ADR-043 pede cada painel com descricao e documentado, no formato da fase 3;
este teste e a trava:

- o JSON de cada dashboard tem o esqueleto do ADR (uid igual ao nome do arquivo,
  ids unicos, grade de 24 colunas, datasource Prometheus, uma das tags `negocio`
  ou `tecnico`) e esta na doc da sua tag (negocio.md ou README.md);
- o `description` de cada painel e o texto da coluna "Como ler" da doc, e as
  consultas do painel estao na coluna "Consulta";
- toda consulta de painel e de alerta usa so metrica e label do catalogo de
  metricas do README (um nome que o servico nao emite deixaria o painel vazio);
- regra de alerta com UID, titulo, consulta, severidade, janela, "sem dado" ou
  "onde" diferentes dos da tabela de alertas, regra sem caso que dispara e sem
  caso que nao dispara no arquivo do promtool, e o valor curto do "Outbox
  parada" fora do overlay kind reprovam;
- arquivo de alerta que o Grafana do cluster nao monta ou que o compose monta
  sem poder usar (as regras que dependem do cluster) e filtro por fila que nao
  seleciona o grupo certo de filas do definitions.json do RabbitMQ;
- a retencao do Prometheus: 15 dias num PVC no kind e no k3s, efemero no kind-ci.
"""

from __future__ import annotations

import copy
import functools
import json
import re

# subprocess so roda o kubectl kustomize dos overlays do repositorio, sem shell.
import subprocess  # nosec B404
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml

from e2e.apoio.paineis import carregar
from e2e.apoio.saga import STATUS_DA_OS

RAIZ = Path(__file__).resolve().parents[1]
OBSERVABILIDADE = RAIZ / "observabilidade"
# Prazo total do coletor da API do OS e da Execucao, em segundos.
PRAZO_DO_COLETOR_S = 5
DOC_CRU = (OBSERVABILIDADE / "README.md").read_text(encoding="utf-8")
NEGOCIO_CRU = (OBSERVABILIDADE / "negocio.md").read_text(encoding="utf-8")
# Tabela Markdown escapa o | das consultas.
DOC = DOC_CRU.replace("\\|", "|")
# A doc de cada area: os de negocio no negocio.md e os tecnicos no README.
DOC_DA_AREA = {"negocio": NEGOCIO_CRU, "tecnico": DOC_CRU}
ARQUIVO_DA_DOC = {
    "negocio": "observabilidade/negocio.md",
    "tecnico": "observabilidade/README.md",
}
DASHBOARDS = sorted((OBSERVABILIDADE / "dashboards").glob("*.json"))
DASHBOARD_POR_UID: dict[str, dict[str, Any]] = {
    arquivo.stem: json.loads(arquivo.read_text(encoding="utf-8"))
    for arquivo in DASHBOARDS
}
ALERTAS = sorted((OBSERVABILIDADE / "grafana").glob("alertas*.yaml"))
# Onde cada arquivo de alertas e provisionado: alertas.yaml no cluster e no
# compose; os outros so no cluster (dependem do Kong, do relay e do consumidor,
# que o compose nao tem; o "Outbox parada" mora a parte para o overlay kind
# trocar so ele).
ONDE = {
    "alertas.yaml": "cluster e compose",
    "alertas-cluster.yaml": "só cluster",
    "alertas-outbox-parada.yaml": "só cluster",
}
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
PROMTOOL = yaml.safe_load(
    (RAIZ / "tests" / "alertas.promtool.yml").read_text(encoding="utf-8")
)["tests"]
# Casos do promtool: (nome do teste, alertname, tem alerta esperado) de cada avaliacao.
CASOS_DO_PROMTOOL = [
    (teste["name"], caso["alertname"], bool(caso["exp_alerts"]))
    for teste in PROMTOOL
    for caso in teste.get("alert_rule_test", [])
]
# Consultas de painel que o promtool avalia direto (promql_expr_test).
EXPRESSOES_DO_PROMTOOL = [
    (teste["name"], caso["expr"])
    for teste in PROMTOOL
    for caso in teste.get("promql_expr_test", [])
]
PROMETHEUS = {"type": "prometheus", "uid": "prometheus"}
AREAS = ("negocio", "tecnico")


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
    "Retry por nível (msg/s)": RETRY,
    "pytstop-dlq-com-mensagens": DLQ,
    "pytstop-fila-sem-consumidor": TRABALHO,
}


def celulas(linha: str) -> list[str]:
    """As celulas de uma linha de tabela Markdown; a consulta pode levar \\|."""
    return [c.strip() for c in re.split(r"(?<!\\)\|", linha)[1:-1]]


def linhas_de_alerta() -> dict[str, dict[str, str]]:
    """uid -> {coluna: celula} da tabela "Regras de alerta" do README."""
    secao = DOC_CRU.split("\n## Regras de alerta", 1)[1].split("\n## ", 1)[0]
    tabela = [linha for linha in secao.splitlines() if linha.startswith("|")]
    colunas = celulas(tabela[0])
    return {
        c[0].strip("`"): dict(zip(colunas, c, strict=True))
        for c in (celulas(linha) for linha in tabela[2:])
    }


def area(dashboard: dict[str, Any]) -> str:
    tags: list[str] = dashboard["tags"]
    (a,) = [tag for tag in tags if tag in AREAS]
    return a


def cabecalho(dashboard: dict[str, Any]) -> str:
    return f"## Dashboard {dashboard['title']} (`{dashboard['uid']}`)"


def tabela_do_dashboard(dashboard: dict[str, Any]) -> dict[int, list[str]]:
    """id do painel -> celulas da linha dele na secao do dashboard, na doc da area."""
    doc = DOC_DA_AREA[area(dashboard)]
    secao = doc.split(f"\n{cabecalho(dashboard)}\n", 1)[1].split("\n## ", 1)[0]
    linhas = [linha for linha in secao.splitlines() if linha.startswith("|")]
    return {int(c[0]): c for c in (celulas(linha) for linha in linhas[2:])}


def paineis() -> list[Any]:
    return [
        pytest.param(dashboard, painel, id=f"{uid}-{painel['id']}")
        for uid, dashboard in DASHBOARD_POR_UID.items()
        for painel in dashboard["panels"]
    ]


def geradores_da_kustomization() -> dict[str, list[str]]:
    kustomization = yaml.safe_load(
        (OBSERVABILIDADE / "kustomization.yaml").read_text(encoding="utf-8")
    )
    return {
        gerador["name"]: gerador["files"]
        for gerador in kustomization["configMapGenerator"]
    }


@pytest.mark.parametrize("uid", DASHBOARD_POR_UID)
def test_dashboard_tem_o_esqueleto_do_adr(uid: str) -> None:
    dashboard = DASHBOARD_POR_UID[uid]
    ids = [painel["id"] for painel in dashboard["panels"]]

    assert dashboard["uid"] == uid
    assert dashboard["schemaVersion"] == 39
    assert dashboard["editable"] is False
    assert ARQUIVO_DA_DOC[area(dashboard)] in dashboard["description"]
    assert "pytstop" in dashboard["tags"]
    # Um menu com os demais dashboards, por tag.
    assert [(link["type"], link["tags"]) for link in dashboard["links"]] == [
        ("dashboards", ["pytstop"])
    ]
    assert len(ids) == len(set(ids))
    for painel in dashboard["panels"]:
        assert painel["gridPos"]["x"] + painel["gridPos"]["w"] <= 24
        assert painel["datasource"] == PROMETHEUS
        assert [alvo["datasource"] for alvo in painel["targets"]] == [PROMETHEUS] * len(
            painel["targets"]
        )


@pytest.mark.parametrize("uid", DASHBOARD_POR_UID)
def test_dashboard_tem_exatamente_uma_das_tags_negocio_ou_tecnico(uid: str) -> None:
    tags = DASHBOARD_POR_UID[uid]["tags"]

    assert len([tag for tag in tags if tag in AREAS]) == 1
    # O nome do arquivo segue a tag: os de negocio levam pytstop-negocio-.
    assert uid.startswith("pytstop-negocio-") == ("negocio" in tags)


@pytest.mark.parametrize("uid", DASHBOARD_POR_UID)
def test_janela_e_atualizacao_de_cada_dashboard(uid: str) -> None:
    dashboard = DASHBOARD_POR_UID[uid]
    # Negocio: 7 dias e 1 min (os paineis por dia e o funil olham dias). Tecnicos:
    # 1 hora e 30 s, e a Saga olha 24 horas.
    janelas = {"negocio": ("now-7d", "1m"), "tecnico": ("now-1h", "30s")}
    janela, atualizacao = janelas[area(dashboard)]
    if uid == "pytstop-saga":
        janela = "now-24h"

    assert dashboard["time"]["from"] == janela
    assert dashboard["refresh"] == atualizacao


@pytest.mark.parametrize("uid", DASHBOARD_POR_UID)
def test_dashboard_esta_na_doc_da_sua_area_e_so_nela(uid: str) -> None:
    dashboard = DASHBOARD_POR_UID[uid]
    outra = next(a for a in AREAS if a != area(dashboard))

    assert cabecalho(dashboard) in DOC_DA_AREA[area(dashboard)]
    assert cabecalho(dashboard) not in DOC_DA_AREA[outra]
    # A tabela lista os paineis do JSON, nem a mais nem a menos.
    assert set(tabela_do_dashboard(dashboard)) == {
        painel["id"] for painel in dashboard["panels"]
    }


@pytest.mark.parametrize(("dashboard", "painel"), paineis())
def test_description_do_painel_e_o_como_ler_da_doc_e_as_consultas_estao_nela(
    dashboard: dict[str, Any], painel: dict[str, Any]
) -> None:
    linha = tabela_do_dashboard(dashboard)[painel["id"]]
    como_ler = linha[-1].replace("\\|", "|")
    consultas = linha[-2].replace("\\|", "|")

    assert painel["description"].strip()
    assert linha[1] == painel["title"]
    assert como_ler == painel["description"]
    for alvo in painel["targets"]:
        assert f"`{alvo['expr']}`" in consultas, alvo["expr"]


def test_dashboard_de_atendimento_tem_os_paineis_que_a_banca_pediu() -> None:
    titulos = {
        painel["title"]
        for painel in DASHBOARD_POR_UID["pytstop-negocio-atendimento"]["panels"]
    }

    assert {"Volume diário de OS", "Tempo médio por status"} <= titulos


@pytest.mark.parametrize(
    ("uid", "titulo"),
    [
        ("pytstop-negocio-atendimento", "Volume diário de OS"),
        ("pytstop-negocio-pagamentos", "Faturamento por dia"),
    ],
)
def test_painel_por_dia_arredonda_o_increase_e_usa_passo_de_um_dia(
    uid: str, titulo: str
) -> None:
    # increase() extrapola as bordas da janela e devolve fracao: o painel por dia
    # arredonda, com o passo minimo de 1d (dias em UTC).
    (painel,) = [p for p in DASHBOARD_POR_UID[uid]["panels"] if p["title"] == titulo]
    (alvo,) = painel["targets"]

    assert alvo["expr"].startswith("round(sum(increase(")
    assert "[1d]" in alvo["expr"]
    assert alvo["interval"] == "1d"
    assert DASHBOARD_POR_UID[uid]["timezone"] == "utc"
    # A barra do ponto conta o dia anterior; -1 a poe no dia que ela conta (com 0 ela
    # sairia meio dia deslocada).
    custom = painel["fieldConfig"]["defaults"]["custom"]
    assert (custom["drawStyle"], custom["barAlignment"]) == ("bars", -1)


# A coluna "Tipo" da doc ("bargauge; s; amarelo a partir de 86400, ...") diz o tipo, a
# unidade e os limiares do painel; o JSON tem de fazer o mesmo.
TIPO_DO_PAINEL = {
    "séries": "timeseries",
    "stat": "stat",
    "bargauge": "bargauge",
    "pizza": "piechart",
    "tabela": "table",
}
NUMERO_DA_DOC = re.compile(r"\d+(?:,\d+)?")


def partes_do_tipo(celula: str) -> tuple[str, str | None, str]:
    """(tipo, unidade, limiares) da coluna "Tipo"; o painel de mapa nao tem unidade."""
    tipo, unidade, *resto = [parte.strip() for parte in celula.split(";")]
    if unidade.startswith("mapa"):
        return tipo, None, "; ".join([unidade, *resto])
    return tipo, unidade, "; ".join(resto)


def unidades_da_doc(unidade: str) -> set[str]:
    sem_casas = re.sub(r",?\s*`decimals: \d+`", "", unidade)
    return {parte.strip() for parte in sem_casas.split(" e ")}


def limiares_da_doc(texto: str) -> list[float]:
    texto = re.sub(r"mapa[^;]*", "", texto)
    if "sem limiar" in texto:
        return []
    # O Grafana compara com >=: "acima de 0" e o degrau em 0,001.
    texto = re.sub(r"acima de 0(?!,)", "acima de 0,001", texto)
    return sorted(float(n.replace(",", ".")) for n in NUMERO_DA_DOC.findall(texto))


def unidades_do_json(painel: dict[str, Any]) -> set[str]:
    campos = painel["fieldConfig"]
    unidades = {campos["defaults"].get("unit")} - {None}
    return unidades | {
        propriedade["value"]
        for sobreposicao in campos["overrides"]
        for propriedade in sobreposicao["properties"]
        if propriedade["id"] == "unit"
    }


def limiares_do_json(painel: dict[str, Any]) -> list[float]:
    campos = painel["fieldConfig"]
    degraus = list(campos["defaults"].get("thresholds", {}).get("steps", []))
    for sobreposicao in campos["overrides"]:
        for propriedade in sobreposicao["properties"]:
            if propriedade["id"] == "thresholds":
                degraus += propriedade["value"]["steps"]
    return sorted(d["value"] for d in degraus if d["value"] is not None)


@pytest.mark.parametrize(("dashboard", "painel"), paineis())
def test_tipo_unidade_e_limiares_da_doc_sao_os_do_json(
    dashboard: dict[str, Any], painel: dict[str, Any]
) -> None:
    celula = tabela_do_dashboard(dashboard)[painel["id"]][2]
    tipo, unidade, limiares = partes_do_tipo(celula)
    padrao = painel["fieldConfig"]["defaults"]

    assert painel["type"] == TIPO_DO_PAINEL[tipo.split()[0]], celula
    em_barras = padrao.get("custom", {}).get("drawStyle") == "bars"
    assert ("em barras" in tipo) == em_barras, celula
    if unidade is not None:
        assert unidades_da_doc(unidade) == unidades_do_json(painel), celula
        casas = re.search(r"`decimals: (\d+)`", unidade)
        if casas:
            assert padrao["decimals"] == int(casas.group(1)), celula
    assert limiares_da_doc(limiares) == limiares_do_json(painel), celula


@pytest.mark.parametrize(("dashboard", "painel"), paineis())
def test_so_o_painel_de_serie_consulta_um_intervalo(
    dashboard: dict[str, Any], painel: dict[str, Any]
) -> None:
    # stat, bargauge, pizza e tabela mostram o valor de agora: a consulta tem de ser
    # instantanea. Sem isso o painel reduz o intervalo inteiro (ultimo, soma...) e
    # mostra outro numero que o "Como ler".
    instantaneo = painel["type"] in {"stat", "bargauge", "piechart", "table"}

    assert [alvo.get("instant", False) for alvo in painel["targets"]] == [
        instantaneo
    ] * len(painel["targets"])


@pytest.mark.parametrize(("dashboard", "painel"), paineis())
def test_painel_que_diz_sem_dado_mostra_sem_dado(
    dashboard: dict[str, Any], painel: dict[str, Any]
) -> None:
    # O Grafana mostra "No data" quando a consulta nao devolve serie (idioma padrao
    # em ingles); o texto do painel promete "sem dado", entao o painel mostra isso.
    if "sem dado" in painel["description"].lower():
        assert painel["fieldConfig"]["defaults"]["noValue"] == "sem dado"


@pytest.mark.parametrize(("dashboard", "painel"), paineis())
def test_painel_que_diz_sem_leitura_mapeia_o_nan_para_sem_leitura(
    dashboard: dict[str, Any], painel: dict[str, Any]
) -> None:
    # Com o banco fora o relay exporta NaN, que o stat mostraria como "NaN": o mapa
    # especial o troca pelo texto que o painel promete.
    if "sem leitura" in painel["description"].lower():
        assert painel["fieldConfig"]["defaults"]["mappings"] == [
            {
                "type": "special",
                "options": {
                    "match": "nan",
                    "result": {"text": "sem leitura", "color": "text"},
                },
            }
        ]


def motivos_de_compensacao() -> set[str]:
    """Os codigos de `motivo` que o README da raiz lista para a saga."""
    texto = (RAIZ / "README.md").read_text(encoding="utf-8")
    (linha,) = re.findall(r"^- `motivo` dos cinco comandos.*$", texto, re.MULTILINE)
    (lista,) = re.findall(r"\(((?:`\w+`(?:, )?)+)\)", linha)
    return set(re.findall(r"\w+", lista))


@pytest.mark.parametrize(
    ("id_do_painel", "codigos"),
    [
        pytest.param(2, set(STATUS_DA_OS), id="os-por-status"),
        pytest.param(3, set(STATUS_DA_OS), id="tempo-por-status"),
        pytest.param(5, {"concluida", "compensada"}, id="desfecho-das-sagas"),
        pytest.param(6, motivos_de_compensacao(), id="motivos-de-cancelamento"),
    ],
)
def test_painel_de_atendimento_da_nome_legivel_a_todo_codigo_da_legenda(
    id_do_painel: int, codigos: set[str]
) -> None:
    # A legenda e o codigo cru da API ("aguardando_aprovacao"); o nome de exibicao
    # cobre todos eles, senao o que ficar sem nome aparece cru entre os legiveis.
    (painel,) = [
        p
        for p in DASHBOARD_POR_UID["pytstop-negocio-atendimento"]["panels"]
        if p["id"] == id_do_painel
    ]
    nomes = {
        o["matcher"]["options"]: o["properties"][0]["value"]
        for o in painel["fieldConfig"]["overrides"]
        if (o["matcher"]["id"], o["properties"][0]["id"]) == ("byName", "displayName")
    }

    assert set(nomes) == codigos
    assert len(set(nomes.values())) == len(nomes)
    assert all(nome[0].isupper() for nome in nomes.values())


def test_configmap_dos_dashboards_lista_todos_os_json() -> None:
    arquivos = geradores_da_kustomization()["grafana-dashboards"]

    assert sorted(arquivos) == sorted(f"dashboards/{a.name}" for a in DASHBOARDS)


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


def consulta_e_limiar(regra: dict[str, Any]) -> tuple[str, str, float]:
    """(consulta A, tipo do avaliador, limiar) de uma regra, como o Grafana os le."""
    (consulta,) = [d["model"]["expr"] for d in regra["data"] if d["refId"] == "A"]
    (avaliador,) = [
        d["model"]["conditions"][0]["evaluator"]
        for d in regra["data"]
        if d["refId"] == "C"
    ]
    return consulta, avaliador["type"], avaliador["params"][0]


@pytest.mark.parametrize("regra", [regra for _, regra in REGRAS], ids=IDS_DAS_REGRAS)
def test_regra_tem_o_modelo_que_o_grafana_avalia(regra: dict[str, Any]) -> None:
    # O promtool le so a consulta, o for e o limiar; o resto do modelo e do Grafana,
    # e o kind-ci nao o tem. Um campo trocado (a condicao que avalia a consulta e nao
    # o limiar, o datasource, a consulta por intervalo) so aparece no smoke local.
    dados = {d["refId"]: d for d in regra["data"]}
    consulta, limiar = dados["A"], dados["C"]

    assert set(dados) == {"A", "C"}
    assert regra["condition"] == "C"
    assert regra["execErrState"] == "Error"
    assert regra["noDataState"] in {"OK", "Alerting"}
    assert regra["labels"]["severity"] in {"warning", "critical"}
    assert regra["annotations"]["summary"].strip()
    assert regra["for"].endswith("m")
    assert consulta["datasourceUid"] == "prometheus"
    assert consulta["relativeTimeRange"]["from"] > 0
    # Um `to` acima de 0 avaliaria a consulta no passado.
    assert consulta["relativeTimeRange"]["to"] == 0
    assert consulta["model"]["refId"] == "A"
    assert consulta["model"]["instant"] is True
    assert limiar["datasourceUid"] == "__expr__"
    assert limiar["model"]["type"] == "threshold"
    assert limiar["model"]["expression"] == "A"
    assert len(limiar["model"]["conditions"]) == 1


def test_p95_cita_no_titulo_e_no_resumo_o_limiar_da_regra() -> None:
    # O limiar mudou de 300 para 500 ms; um texto que ficou com o numero velho mente
    # sobre quando o alerta dispara.
    (regra,) = [r for _, r in REGRAS if r["uid"] == "pytstop-latencia-p95"]
    (limiar,) = [d for d in regra["data"] if d["refId"] == "C"]
    ms = round(limiar["model"]["conditions"][0]["evaluator"]["params"][0] * 1000)

    assert f"{ms} ms" in regra["title"]
    assert f"{ms} ms" in regra["annotations"]["summary"]


def numero_da_doc(valor: float) -> str:
    return f"{valor:g}".replace(".", ",")


@pytest.mark.parametrize(("arquivo", "regra"), REGRAS, ids=IDS_DAS_REGRAS)
def test_tabela_de_alertas_traz_a_consulta_e_o_limiar_da_regra(
    arquivo: str, regra: dict[str, Any]
) -> None:
    # A consulta tambem e de painel, entao procurar no README inteiro nao basta: a
    # celula da regra tem de trazer a consulta dela e o limiar com o operador
    # (acima no gt, abaixo no lt; no "Outbox parada", o valor de producao).
    celula = linhas_de_alerta()[regra["uid"]]["Condição (PromQL)"].replace("\\|", "|")
    consulta, tipo, limiar = consulta_e_limiar(regra)
    operador = {"gt": "acima de", "lt": "abaixo de"}[tipo]

    assert f"`{consulta}`" in celula
    assert re.search(
        rf"{operador} {re.escape(numero_da_doc(limiar))}(?![\d]|,\d)", celula
    ), celula


def test_saga_parada_dispara_acima_de_zero_depois_de_5_min() -> None:
    # O scripts/alertas-promtool.sh le o limiar, o tipo e a janela do proprio
    # arquivo e so modela gt e lt; este teste prende a forma da regra e o valor
    # que a tabela do README e o runbook dizem (acima de 0, 5 min).
    regra = next(r for _, r in REGRAS if r["uid"] == "pytstop-saga-parada")
    (limiar,) = [d["model"] for d in regra["data"] if d["refId"] == "C"]

    assert regra["condition"] == "C"
    assert regra["for"] == "5m"
    assert limiar["type"] == "threshold"
    assert limiar["expression"] == "A"
    assert limiar["conditions"] == [{"evaluator": {"type": "gt", "params": [0]}}]


def test_regra_que_le_o_coletor_das_sagas_espera_mais_que_duas_raspagens() -> None:
    # O coletor le uma vez por vez: duas raspagens ao mesmo tempo fazem a segunda
    # sair com pytstop_saga_coletor_disponivel em 0, por desenho. O `for` cobre
    # mais que duas raspagens de 15 s, ou esse 0 isolado alertaria.
    regras = [
        regra
        for _, regra in REGRAS
        if any(
            "pytstop_saga_coletor_disponivel" in dado["model"].get("expr", "")
            for dado in regra["data"]
        )
    ]

    assert [regra["uid"] for regra in regras] == ["pytstop-saga-parada"]
    assert int(regras[0]["for"].removesuffix("m")) * 60 > 2 * 15


def test_tabela_de_alertas_nao_tem_regra_que_nenhum_arquivo_define() -> None:
    assert set(linhas_de_alerta()) == set(IDS_DAS_REGRAS)


def test_grafana_do_cluster_monta_todos_os_alertas_e_o_compose_so_os_comuns() -> None:
    arquivos = geradores_da_kustomization()
    compose = yaml.safe_load(
        (RAIZ / "compose" / "docker-compose.yml").read_text(encoding="utf-8")
    )
    montados = " ".join(compose["services"]["grafana"]["volumes"])

    assert sorted(arquivos["grafana-alerting"]) == [
        f"grafana/{a.name}" for a in ALERTAS
    ]
    assert "grafana/alertas.yaml:" in montados
    assert "alertas-cluster" not in montados
    assert "alertas-outbox-parada" not in montados
    # O compose monta a pasta inteira dos dashboards.
    assert "../observabilidade/dashboards:/var/lib/grafana/dashboards" in montados


# O Kong e o RabbitMQ existem no cluster so com a plataforma (o do smoke); o OS, o
# Billing, a Execucao e os exporters dos bancos nao.
ALVOS_DA_PLATAFORMA = {"pytstop-kong-fora", "pytstop-rabbitmq-fora"}


def test_smoke_espera_disparando_as_regras_que_disparam_sem_os_servicos() -> None:
    # Sem alvo, a regra com `noDataState: Alerting` dispara; a fila de trabalho dispara
    # porque nenhum consumidor existe. Regra nova que dispara por desenho e nao esta na
    # lista do smoke o faria esperar 3 min e reprovar so no cluster.
    smoke = (RAIZ / "scripts" / "smoke.sh").read_text(encoding="utf-8")
    (lista,) = re.findall(r"for uid in ([a-z0-9 -]+); do", smoke)
    sem_alvo = {
        regra["uid"] for _, regra in REGRAS if regra["noDataState"] == "Alerting"
    } - ALVOS_DA_PLATAFORMA

    assert set(lista.split()) == sem_alvo | {"pytstop-fila-sem-consumidor"}


@pytest.mark.parametrize("uid", IDS_DAS_REGRAS)
def test_regra_tem_caso_que_dispara_e_caso_que_nao_dispara_no_promtool(
    uid: str,
) -> None:
    esperados = {
        dispara for _, alertname, dispara in CASOS_DO_PROMTOOL if alertname == uid
    }

    assert esperados == {True, False}


def test_promtool_so_testa_regra_que_existe() -> None:
    # Um alertname que nenhuma regra tem passaria calado no promtool: o teste
    # esperaria uma lista vazia de alertas de uma regra que nao existe.
    assert {alertname for _, alertname, _ in CASOS_DO_PROMTOOL} <= set(IDS_DAS_REGRAS)


@pytest.mark.parametrize(
    ("nome", "expr"),
    EXPRESSOES_DO_PROMTOOL,
    ids=[f"{i}-{nome}" for i, (nome, _) in enumerate(EXPRESSOES_DO_PROMTOOL)],
)
def test_promtool_so_avalia_consulta_que_um_painel_ou_um_alerta_tem(
    nome: str, expr: str
) -> None:
    # O script troca $__rate_interval por 5m e $__range por 1h; o caso escreve a
    # consulta ja trocada, e uma consulta que ninguem mais usa passaria calada.
    resolvidas = {
        e.replace("$__rate_interval", "5m").replace("$__range", "1h")
        for _, e in consultas()
    }

    assert expr in resolvidas, nome


# ---------------------------------------------------------------------------
# Catalogo de metricas: toda consulta usa so metrica e label que a doc lista.

# Funcoes, agregacoes, operadores e palavras-chave do PromQL.
FUNCOES_E_OPERADORES = frozenset(
    """
    abs absent absent_over_time and avg avg_over_time bool bottomk ceil changes
    clamp clamp_max clamp_min count count_over_time count_values day_of_month
    day_of_week day_of_year days_in_month delta deriv exp floor group
    histogram_quantile hour idelta increase inf irate label_join label_replace
    last_over_time ln log10 log2 max max_over_time min min_over_time minute month
    nan offset or predict_linear present_over_time quantile quantile_over_time
    rate resets round scalar sgn sort sort_desc sqrt stddev stddev_over_time
    stdvar sum sum_over_time time timestamp topk unless vector year
    """.split()  # noqa: SIM905  # lista longa: um nome por linha nao ajuda a ler
)
SUFIXOS_DE_HISTOGRAMA = ("_bucket", "_sum", "_count")
# Labels que o Prometheus poe em todo alvo (relabel_configs) e o le do bucket.
LABELS_COMUNS = frozenset({"job", "app", "processo", "namespace", "pod", "instance"})
LITERAIS = re.compile(r"\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|`[^`]*`")
AGRUPAMENTO = re.compile(
    r"\b(?:by|without|on|ignoring|group_left|group_right)\s*\(([^)]*)\)"
)
SELETOR = re.compile(r"([A-Za-z_:][\w:]*)\s*\{([^{}]*)\}")
# Os quatro ultimos argumentos do label_replace: "destino", "troca", "origem", "regex".
LABEL_REPLACE = re.compile(r',\s*"(\w+)"\s*,\s*"[^"]*"\s*,\s*"\w+"\s*,\s*"[^"]*"\s*\)')


@dataclass(frozen=True)
class Analise:
    metricas: frozenset[str]
    # (nome antes da chave, labels dos matchers)
    seletores: tuple[tuple[str, frozenset[str]], ...]
    agrupamentos: frozenset[str]
    criados: frozenset[str]


def analisar(expr: str) -> Analise:
    """Os identificadores de uma consulta PromQL, sem strings, funcoes e numeros."""
    criados = frozenset(LABEL_REPLACE.findall(expr))
    resto = LITERAIS.sub('""', expr)
    seletores = tuple(
        (nome, frozenset(re.findall(r"(\w+)\s*(?:=~|!~|!=|=)", corpo)))
        for nome, corpo in SELETOR.findall(resto)
    )
    agrupamentos = frozenset(
        rotulo.strip()
        for corpo in AGRUPAMENTO.findall(resto)
        for rotulo in corpo.split(",")
        if rotulo.strip()
    )
    for removivel in (
        r"\{[^{}]*\}",
        r"\[[^\]]*\]",
        AGRUPAMENTO.pattern,
        r"\b\d\w*(?:\.\d+)?",
    ):
        resto = re.sub(removivel, "", resto)
    identificadores = frozenset(re.findall(r"[A-Za-z_:][A-Za-z0-9_:]*", resto))
    return Analise(
        identificadores - FUNCOES_E_OPERADORES, seletores, agrupamentos, criados
    )


def catalogo() -> dict[str, tuple[str, frozenset[str]]]:
    """nome da metrica -> (tipo, labels) da tabela "Catalogo de metricas" do README."""
    secao = DOC_CRU.split("\n## Catálogo de métricas", 1)[1].split("\n## ", 1)[0]
    linhas = [celulas(c) for c in secao.splitlines() if c.startswith("|")]
    resultado: dict[str, tuple[str, frozenset[str]]] = {}
    for coluna in linhas[2:]:
        # Nome entre crases; o que vem entre parenteses nos labels sao valores.
        labels = frozenset(re.findall(r"`(\w+)`", re.sub(r"\([^)]*\)", "", coluna[2])))
        for nome in re.findall(r"`(\w+)`", coluna[0]):
            resultado[nome] = (coluna[1], labels)
    return resultado


CATALOGO = catalogo()


def metrica_do_catalogo(identificador: str) -> str | None:
    """O nome no catalogo: o proprio, ou o do histograma de uma serie _bucket/_sum."""
    if identificador in CATALOGO:
        return identificador
    base = identificador.rsplit("_", 1)[0]
    if identificador.endswith(SUFIXOS_DE_HISTOGRAMA) and base in CATALOGO:
        return base if CATALOGO[base][0].startswith("histograma") else None
    return None


def violacoes_do_catalogo(expr: str) -> list[str]:
    analise = analisar(expr)
    achados = []
    nomes = {i: metrica_do_catalogo(i) for i in analise.metricas}
    achados += [f"metrica fora do catalogo: {i}" for i, n in nomes.items() if n is None]
    labels_das_metricas = frozenset().union(
        *(CATALOGO[n][1] for n in nomes.values() if n is not None)
    )
    for nome, rotulos in analise.seletores:
        base = metrica_do_catalogo(nome)
        permitidos = (CATALOGO[base][1] if base else frozenset()) | LABELS_COMUNS
        achados += [
            f"label {r} nao existe em {nome}" for r in sorted(rotulos - permitidos)
        ]
    conhecidos = labels_das_metricas | LABELS_COMUNS | analise.criados | {"le"}
    achados += [
        f"agrupa por {r}, que nenhuma metrica da consulta tem"
        for r in sorted(analise.agrupamentos - conhecidos)
    ]
    return achados


def consultas() -> list[tuple[str, str]]:
    """(titulo do painel ou uid da regra, consulta) de todo painel e todo alerta."""
    return [
        (painel["title"], alvo["expr"])
        for dashboard in DASHBOARD_POR_UID.values()
        for painel in dashboard["panels"]
        for alvo in painel["targets"]
    ] + [
        (regra["uid"], dado["model"]["expr"])
        for _, regra in REGRAS
        for dado in regra["data"]
        if "expr" in dado["model"]
    ]


CONSULTAS = consultas()


@pytest.mark.parametrize(
    ("nome", "expr"), CONSULTAS, ids=[f"{i}-{n}" for i, (n, _) in enumerate(CONSULTAS)]
)
def test_consulta_so_usa_metrica_e_label_do_catalogo(nome: str, expr: str) -> None:
    assert violacoes_do_catalogo(expr) == [], nome


def test_analise_ignora_literais_funcoes_agrupamentos_e_numeros() -> None:
    analise = analisar(
        "topk(10, sum by (le, nivel) (label_replace("
        'rate(a_bucket{queue=~"b_total", c!="d"}[5m]), '
        '"nivel", "$1", "queue", "e_total")) / 100 > bool 0.5) or vector(0)'
    )

    assert analise.metricas == {"a_bucket"}
    assert analise.seletores == (("a_bucket", frozenset({"queue", "c"})),)
    assert analise.agrupamentos == {"le", "nivel"}
    assert analise.criados == {"nivel"}


@pytest.mark.parametrize(
    ("expr", "achado"),
    [
        pytest.param(
            "sum(pytstop_inventada_total)",
            "metrica fora do catalogo: pytstop_inventada_total",
            id="metrica-inventada",
        ),
        # Sufixo de histograma so vale em histograma.
        pytest.param(
            "rate(outbox_dead_count[5m])",
            "metrica fora do catalogo: outbox_dead_count",
            id="sufixo-de-histograma-em-contador",
        ),
        pytest.param(
            'up{rota="x"}', "label rota nao existe em up", id="label-inventado"
        ),
        pytest.param(
            "sum by (tipo) (pytstop_os_criadas_total)",
            "agrupa por tipo, que nenhuma metrica da consulta tem",
            id="agrupamento-inventado",
        ),
    ],
)
def test_analise_do_catalogo_reprova_nome_label_e_agrupamento_inventados(
    expr: str, achado: str
) -> None:
    assert achado in violacoes_do_catalogo(expr)


def test_catalogo_conhece_o_tipo_e_os_labels_de_um_histograma() -> None:
    tipo, labels = CATALOGO["http_request_duration_seconds"]

    assert tipo.startswith("histograma")
    assert labels == {"method", "rota", "status"}
    assert metrica_do_catalogo("http_request_duration_seconds_bucket") == (
        "http_request_duration_seconds"
    )


# ---------------------------------------------------------------------------
# Ferramentas: o filtro do jq do promtool e os extratores de "toda consulta".

FILTRO_DO_PROMTOOL = RAIZ / "scripts" / "alertas-promtool.jq"


def executar(*comando: str) -> str:
    """A saida de um comando do PATH (jq, sed), sem shell."""
    return subprocess.run(  # noqa: S603  # nosec B603
        comando, capture_output=True, text=True, timeout=30, check=True
    ).stdout


def filtrar(*regras: dict[str, Any]) -> subprocess.CompletedProcess[str]:
    """O filtro do scripts/alertas-promtool.sh sobre regras ja lidas do YAML."""
    return subprocess.run(  # noqa: S603  # nosec B603 B607
        ["jq", "-c", "-s", "-f", str(FILTRO_DO_PROMTOOL)],  # noqa: S607
        input="\n".join(json.dumps(regra) for regra in regras),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


REGRA_VALIDA = {"uid": "r1", "for": "5m", "tipo": "gt", "limiar": 0.5, "expr": "x"}


def test_filtro_do_promtool_monta_a_regra_com_o_operador_do_avaliador() -> None:
    saida = filtrar(REGRA_VALIDA, {**REGRA_VALIDA, "uid": "r2", "tipo": "lt"})

    assert saida.returncode == 0
    assert json.loads(saida.stdout) == {
        "groups": [
            {
                "name": "alertas",
                "rules": [
                    {"alert": "r1", "expr": "(x) > 0.5", "for": "5m"},
                    {"alert": "r2", "expr": "(x) < 0.5", "for": "5m"},
                ],
            }
        ]
    }


@pytest.mark.parametrize(
    ("regra", "erro"),
    [
        pytest.param(
            {**REGRA_VALIDA, "for": "30s"},
            "rule r1: unexpected for: 30s",
            id="for-fora-de-minutos",
        ),
        pytest.param(
            {**REGRA_VALIDA, "limiar": "0.5"},
            "rule r1: unexpected threshold 0.5",
            id="limiar-que-nao-e-numero",
        ),
        pytest.param(
            {**REGRA_VALIDA, "tipo": "within_range"},
            "rule r1: threshold type within_range is neither gt nor lt",
            id="tipo-que-nao-e-gt-nem-lt",
        ),
    ],
)
def test_filtro_do_promtool_reprova_regra_que_o_modelo_de_teste_nao_cobre(
    regra: dict[str, Any], erro: str
) -> None:
    saida = filtrar(regra)

    assert saida.returncode != 0
    assert erro in saida.stderr


def test_os_extratores_de_consulta_de_painel_e_de_alerta_concordam() -> None:
    # Quatro lugares tiram "toda consulta de painel e de alerta", cada um com o seu
    # parser: o gate de paineis do E2E (Python), o teste de catalogo, e o script do
    # promtool e o smoke (jq nos JSON, sed nos YAML). Uma lista que diverge deixaria
    # uma consulta sem prova.
    paineis_jq = executar(
        "jq", "-r", ".panels[].targets[].expr", *map(str, DASHBOARDS)
    ).splitlines()
    alertas_sed = executar(
        "sed", "-n", "s/^ *expr: //p", *map(str, ALERTAS)
    ).splitlines()
    do_gate = carregar(OBSERVABILIDADE)
    paineis_do_gate = [c.expr for c in do_gate if not c.origem.startswith("alerta ")]
    alertas_do_gate = [c.expr for c in do_gate if c.origem.startswith("alerta ")]
    do_teste = consultas()
    paineis_do_teste = [expr for nome, expr in do_teste if nome not in IDS_DAS_REGRAS]
    alertas_do_teste = [expr for nome, expr in do_teste if nome in IDS_DAS_REGRAS]

    assert paineis_jq == paineis_do_gate == paineis_do_teste
    assert sorted(alertas_sed) == sorted(alertas_do_gate) == sorted(alertas_do_teste)
    assert len(paineis_jq) == sum(
        len(painel["targets"])
        for dashboard in DASHBOARD_POR_UID.values()
        for painel in dashboard["panels"]
    )


# ---------------------------------------------------------------------------
# Filtros por fila contra a topologia do RabbitMQ.

# Matcher de regex no label queue, com ou sem espaco e com qualquer aspa do
# PromQL.
FILTRO_REGEX_DE_FILA = re.compile(r"""queue\s*(=~|!~)\s*["'`]([^"'`]*)["'`]""")
COM_FILTRO_DE_FILA = [
    (nome, expr) for nome, expr in CONSULTAS if FILTRO_REGEX_DE_FILA.search(expr)
]


def test_painel_e_regra_com_filtro_de_fila_sao_os_mapeados() -> None:
    # Painel que perde o filtro sai do conjunto e reprova; um novo precisa de
    # grupo em FILTRO_DE_FILA.
    assert {nome for nome, _ in COM_FILTRO_DE_FILA} == set(FILTRO_DE_FILA)
    assert FILAS == TRABALHO | RETRY | DLQ


@pytest.mark.parametrize(
    ("nome", "expr"), COM_FILTRO_DE_FILA, ids=[nome for nome, _ in COM_FILTRO_DE_FILA]
)
def test_filtro_de_fila_seleciona_o_grupo_certo_da_topologia(
    nome: str, expr: str
) -> None:
    # Matcher do PromQL e RE2 ancorado nas duas pontas (re.fullmatch). Uma fila
    # nova no definitions.json com nome fora do padrao, ou um padrao que ficou
    # para tras quando a topologia mudou, reprova aqui.
    (operador, padrao), *outros = FILTRO_REGEX_DE_FILA.findall(expr)
    casam = {fila for fila in FILAS if re.fullmatch(padrao, fila)}

    assert outros == []
    assert (casam if operador == "=~" else FILAS - casam) == FILTRO_DE_FILA[nome]


# ---------------------------------------------------------------------------
# Kustomize: retencao do Prometheus.


@functools.cache
def renderizar(caminho: str) -> tuple[dict[str, Any], ...]:
    """Os objetos de `kubectl kustomize k8s/<caminho>` (base ou overlays/<nome>)."""
    saida = subprocess.run(  # noqa: S603  # nosec B603 B607
        ["kubectl", "kustomize", str(RAIZ / "k8s" / caminho)],  # noqa: S607
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    ).stdout
    return tuple(objeto for objeto in yaml.safe_load_all(saida) if objeto)


def do_prometheus(caminho: str) -> dict[str, Any]:
    return next(
        o
        for o in renderizar(caminho)
        if o["kind"] == "Deployment" and o["metadata"]["name"] == "prometheus"
    )


def volume_de_dados(deployment: dict[str, Any]) -> dict[str, Any]:
    volumes: list[dict[str, Any]] = deployment["spec"]["template"]["spec"]["volumes"]
    (volume,) = [v for v in volumes if v["name"] == "dados"]
    return volume


@pytest.mark.parametrize("overlay", ["kind", "k3s"])
def test_prometheus_retem_15_dias_num_pvc_no_kind_e_no_k3s(overlay: str) -> None:
    deployment = do_prometheus(f"overlays/{overlay}")
    (container,) = deployment["spec"]["template"]["spec"]["containers"]
    (pvc,) = [
        o
        for o in renderizar(f"overlays/{overlay}")
        if o["kind"] == "PersistentVolumeClaim"
        and o["metadata"]["name"] == "prometheus-dados"
    ]
    (tamanho,) = [
        a for a in container["args"] if a.startswith("--storage.tsdb.retention.size=")
    ]
    limite_mib = int(tamanho.split("=")[1].removesuffix("MB"))

    assert "--storage.tsdb.retention.time=15d" in container["args"]
    assert volume_de_dados(deployment)["persistentVolumeClaim"] == {
        "claimName": "prometheus-dados"
    }
    assert pvc["spec"]["resources"]["requests"]["storage"] == "2Gi"
    assert pvc["metadata"]["namespace"] == "pytstop-plataforma"
    # O WAL conta no retention.size: o resto do volume e folga da compactacao.
    assert limite_mib <= 0.75 * 2 * 1024
    # Com PVC ReadWriteOnce, RollingUpdate deixaria o pod novo preso no lock do TSDB.
    assert deployment["spec"]["strategy"] == {"type": "Recreate"}


def test_prometheus_do_kind_ci_segue_efemero_como_o_base() -> None:
    kind_ci = do_prometheus("overlays/kind-ci")

    assert kind_ci == do_prometheus("base")
    assert "emptyDir" in volume_de_dados(kind_ci)
    assert not [
        o
        for o in renderizar("overlays/kind-ci")
        if o["kind"] == "PersistentVolumeClaim"
    ]


@pytest.mark.parametrize(
    "arquivo",
    [
        RAIZ / "k8s" / "base" / "observabilidade" / "config" / "prometheus.yml",
        RAIZ / "compose" / "prometheus.yml",
    ],
    ids=["cluster", "compose"],
)
def test_prometheus_tem_scrape_timeout_explicito_que_o_readme_documenta(
    arquivo: Path,
) -> None:
    globais = yaml.safe_load(arquivo.read_text(encoding="utf-8"))["global"]

    assert globais["scrape_timeout"] == "10s"
    # O coletor do OS e da Execucao desiste da raspagem em 5 s: o prazo do Prometheus
    # fica acima disso, ou ele cortaria uma raspagem ainda dentro do prazo.
    assert int(globais["scrape_timeout"].removesuffix("s")) > PRAZO_DO_COLETOR_S
    assert globais["scrape_interval"] == "15s"
    assert "`scrape_timeout: 10s`" in DOC
    assert "acima de 5 s" in DOC


def teto_de_traces_do_cluster() -> str:
    objetos = yaml.safe_load_all(
        (RAIZ / "k8s" / "base" / "observabilidade" / "jaeger.yaml").read_text(
            encoding="utf-8"
        )
    )
    (deployment,) = [o for o in objetos if o and o["kind"] == "Deployment"]
    (conteiner,) = deployment["spec"]["template"]["spec"]["containers"]
    return str(
        next(e["value"] for e in conteiner["env"] if e["name"] == "MEMORY_MAX_TRACES")
    )


def test_jaeger_tem_o_mesmo_teto_de_traces_no_cluster_no_compose_e_na_doc() -> None:
    # O teto vem da conta do README (12 KB por span, limite de 512 Mi): cluster,
    # compose e os textos que o citam dizem o mesmo numero.
    compose = yaml.safe_load(
        (RAIZ / "compose" / "docker-compose.yml").read_text(encoding="utf-8")
    )
    runbook = (RAIZ / "docs" / "operacao" / "runbook-saga.md").read_text(
        encoding="utf-8"
    )
    adr = (
        RAIZ
        / "docs"
        / "arquitetura"
        / "adr"
        / "fase4"
        / "043-observabilidade-distribuida.md"
    ).read_text(encoding="utf-8")
    teto = teto_de_traces_do_cluster()

    assert compose["services"]["jaeger"]["environment"]["MEMORY_MAX_TRACES"] == teto
    assert f"`MEMORY_MAX_TRACES={teto}`" in DOC
    assert f"(até {teto}," in runbook
    assert f"(`MEMORY_MAX_TRACES` em {teto}," in adr


def alertas_renderizados(caminho: str) -> dict[str, str]:
    """arquivo -> texto do ConfigMap grafana-alerting que o kustomize renderiza."""
    (configmap,) = [
        o
        for o in renderizar(caminho)
        if o["kind"] == "ConfigMap"
        and o["metadata"]["name"].startswith("grafana-alerting-")
    ]
    data: dict[str, str] = configmap["data"]
    return data


def outbox_parada(texto: str) -> dict[str, Any]:
    regra: dict[str, Any] = yaml.safe_load(texto)["groups"][0]["rules"][0]
    return regra


def limiar_da_regra(regra: dict[str, Any]) -> float:
    (condicao,) = [d["model"] for d in regra["data"] if d["refId"] == "C"]
    limiar: float = condicao["conditions"][0]["evaluator"]["params"][0]
    return limiar


def test_so_o_overlay_kind_traz_o_outbox_parada_de_30_s_e_1_min() -> None:
    base = alertas_renderizados("base")
    kind = alertas_renderizados("overlays/kind")
    k3s = alertas_renderizados("overlays/k3s")
    regra_kind = outbox_parada(kind["alertas-outbox-parada.yaml"])
    regra_k3s = outbox_parada(k3s["alertas-outbox-parada.yaml"])
    igualada = copy.deepcopy(regra_kind)
    igualada["for"] = regra_k3s["for"]
    igualada["data"][1]["model"]["conditions"][0]["evaluator"]["params"] = [
        limiar_da_regra(regra_k3s)
    ]

    assert (regra_kind["for"], limiar_da_regra(regra_kind)) == ("1m", 30)
    assert (regra_k3s["for"], limiar_da_regra(regra_k3s)) == ("5m", 300)
    # O base e o k3s sao os de producao, e o kind difere deles so nessa regra,
    # e nela so no for e no limiar.
    assert base == k3s
    assert {nome for nome in kind if kind[nome] != k3s[nome]} == {
        "alertas-outbox-parada.yaml"
    }
    assert igualada == regra_k3s
    # Os valores de producao sao os do arquivo versionado em observabilidade/.
    versionada = outbox_parada(
        (OBSERVABILIDADE / "grafana" / "alertas-outbox-parada.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert (versionada["for"], limiar_da_regra(versionada)) == ("5m", 300)


def test_kind_ci_nao_tem_grafana_nem_regras_de_alerta() -> None:
    assert not [
        o
        for o in renderizar("overlays/kind-ci")
        if o["metadata"]["name"].startswith("grafana")
    ]
