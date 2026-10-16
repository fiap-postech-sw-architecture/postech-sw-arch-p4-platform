"""Prometheus do kind depois do E2E: cada consulta de painel de negocio tem serie?

Os dashboards de negocio (``observabilidade/dashboards/pytstop-negocio-*.json``)
sao o que a banca pediu. Um nome de metrica errado, um rotulo trocado ou um
servico que deixou de emitir deixa o painel vazio sem erro nenhum, e justo o
painel que a banca olha. Aqui o ``expr`` de cada alvo de cada painel de negocio
roda em ``/api/v1/query`` do Prometheus do kind (pelo proxy do apiserver, como o
``make smoke``), com ``$__range`` em 1h e ``$__rate_interval`` em 5m, e a que
voltar vazia ou com erro reprova. Os paineis tecnicos e os alertas entram no
resumo, mas nao reprovam: serie ausente ali pode ser normal (sem 5xx nao ha
serie de 5xx).

A prova vale depois do E2E, que deixa a saga passar pelos tres servicos e
alimenta o funil, os desfechos e as duas series esparsas da Execucao (tempo de
execucao por servico e pecas em falta).
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import quote

import yaml

from e2e.apoio.kube import NAMESPACE_DA_PLATAFORMA, ErroDeComandoError, Kubectl

if TYPE_CHECKING:
    from collections.abc import Sequence

RAIZ: Final = Path(__file__).resolve().parents[2]
OBSERVABILIDADE: Final = RAIZ / "observabilidade"
CONTEXTO_PADRAO: Final = "kind-pytstop-p4"
PRAZO_DA_CONSULTA: Final = 30.0
_TAMANHO_DO_ERRO: Final = 160


@dataclass(frozen=True)
class Consulta:
    origem: str
    expr: str
    # Painel de negocio: sem serie, a prova reprova.
    obrigatoria: bool


@dataclass(frozen=True)
class Resultado:
    consulta: Consulta
    series: int | None
    erro: str = ""

    @property
    def ok(self) -> bool:
        return self.series is not None and self.series > 0


def resolver(expr: str) -> str:
    """A consulta como o Grafana a manda: o periodo e a taxa viram valores fixos."""
    return expr.replace("$__range", "1h").replace("$__rate_interval", "5m")


def carregar(raiz: Path = OBSERVABILIDADE) -> list[Consulta]:
    """Todo ``expr`` de painel (os de negocio, obrigatorios) e de alerta."""
    consultas: list[Consulta] = []
    for arquivo in sorted((raiz / "dashboards").glob("*.json")):
        dashboard = json.loads(arquivo.read_text(encoding="utf-8"))
        negocio = "negocio" in dashboard["tags"]
        for painel in dashboard["panels"]:
            for alvo in painel["targets"]:
                origem = f"{dashboard['uid']} {painel['id']} {painel['title']}"
                consultas.append(Consulta(origem, alvo["expr"], negocio))
    for arquivo in sorted((raiz / "grafana").glob("alertas*.yaml")):
        for grupo in yaml.safe_load(arquivo.read_text(encoding="utf-8"))["groups"]:
            for regra in grupo["rules"]:
                for dado in regra["data"]:
                    if "expr" in dado["model"]:
                        consultas.append(
                            Consulta(
                                f"alerta {regra['uid']}", dado["model"]["expr"], False
                            )
                        )
    return consultas


def contar_series(kubectl: Kubectl, expr: str) -> int:
    """Quantas series a consulta devolve agora no Prometheus do kind."""
    caminho = (
        f"/api/v1/namespaces/{NAMESPACE_DA_PLATAFORMA}/services/prometheus:9090"
        f"/proxy/api/v1/query?query={quote(resolver(expr), safe='')}"
    )
    resposta: dict[str, Any] = json.loads(
        kubectl.executar("get", "--raw", caminho, prazo=PRAZO_DA_CONSULTA)
    )
    if resposta.get("status") != "success":
        msg = f"o Prometheus respondeu {str(resposta)[:_TAMANHO_DO_ERRO]}"
        raise ErroDeComandoError(msg)
    return len(resposta["data"]["result"])


def verificar(kubectl: Kubectl, consultas: Sequence[Consulta]) -> list[Resultado]:
    resultados = []
    for consulta in consultas:
        try:
            resultados.append(
                Resultado(consulta, contar_series(kubectl, consulta.expr))
            )
        except (ErroDeComandoError, ValueError, KeyError) as erro:
            resultados.append(Resultado(consulta, None, str(erro)[:_TAMANHO_DO_ERRO]))
    return resultados


def _celula(texto: str) -> str:
    return texto.replace("|", "\\|")


def _item_sem_serie(r: Resultado) -> str:
    erro = f" ({r.erro})" if r.erro else ""
    return f"- {r.consulta.origem}: `{_celula(r.consulta.expr)}`{erro}"


def gerar_resumo(resultados: Sequence[Resultado]) -> str:
    """Markdown: os paineis de negocio, um por linha, e os demais sem serie."""
    negocio = [r for r in resultados if r.consulta.obrigatoria]
    outros = [r for r in resultados if not r.consulta.obrigatoria]
    reprovados = [r for r in negocio if not r.ok]
    linhas = [
        "## Painéis de negócio com série depois do E2E",
        "",
        f"{len(negocio)} consultas de painel de negócio, {len(reprovados)} sem série.",
        "",
        "| Resultado | Séries | Painel | Consulta |",
        "|---|---|---|---|",
    ]
    for r in negocio:
        series = r.erro or str(r.series)
        resultado = "ok" if r.ok else "SEM SÉRIE"
        expr = _celula(r.consulta.expr)
        linhas.append(f"| {resultado} | {series} | {r.consulta.origem} | `{expr}` |")
    vazios = [r for r in outros if not r.ok]
    tecnicos = (
        f"Painéis técnicos e alertas: {len(outros)} consultas, {len(vazios)} sem série "
        "(informativo, não reprova)."
    )
    linhas += ["", tecnicos, ""]
    linhas += [_item_sem_serie(r) for r in vazios]
    return "\n".join(linhas) + "\n"


def principal(argumentos: list[str]) -> int:
    """``<dir>``: escreve o ``paineis.md``; 1 se um painel de negocio vier vazio."""
    if len(argumentos) != 1:
        print("uso: python -m e2e.paineis <diretorio dos relatorios>", file=sys.stderr)
        return 2
    kubectl = Kubectl(os.environ.get("KUBE_CONTEXT", CONTEXTO_PADRAO))
    resultados = verificar(kubectl, carregar())
    texto = gerar_resumo(resultados)
    diretorio = Path(argumentos[0])
    diretorio.mkdir(parents=True, exist_ok=True)
    (diretorio / "paineis.md").write_text(texto, encoding="utf-8")
    print(texto)
    resumo_do_actions = os.environ.get("GITHUB_STEP_SUMMARY")
    if resumo_do_actions:
        with Path(resumo_do_actions).open("a", encoding="utf-8") as saida:
            saida.write(texto + "\n")
    reprovados = [r for r in resultados if r.consulta.obrigatoria and not r.ok]
    return 1 if reprovados else 0
