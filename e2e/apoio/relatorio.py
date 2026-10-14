"""Relatorio do E2E: o resumo.md (cenario, duracao, ordem_id, trace_id) e o registro.

O pytest-bdd escreve o junit e o cucumber.json; o que eles nao sabem (a OS e o
trace de cada cenario) o runner anota em ``cenarios.json``. Este modulo junta os
dois no ``resumo.md``, que tambem vai para o ``$GITHUB_STEP_SUMMARY``.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Final

NS_POR_S: Final = 1_000_000_000
type Registros = dict[str, dict[str, str]]


class Registro:
    """O que cada cenario descobriu (``ordem_id``, ``trace_id``), para o resumo."""

    def __init__(self) -> None:
        self._cenarios: Registros = {}

    def anotar(self, cenario: str, **dados: str) -> None:
        self._cenarios.setdefault(cenario, {}).update(dados)

    def salvar(self, caminho: Path) -> None:
        caminho.write_text(json.dumps(self._cenarios, indent=2, sort_keys=True) + "\n")


def _duracao(cenario: dict[str, Any]) -> float:
    """Segundos do cenario: a soma da duracao (em ns) dos passos."""
    nanos: int = sum(
        passo.get("result", {}).get("duration", 0) for passo in cenario.get("steps", [])
    )
    return nanos / NS_POR_S


def _virgula(segundos: float) -> str:
    """``8,3``: a vírgula decimal do README e do corpo do PR."""
    return f"{segundos:.1f}".replace(".", ",")


def _exemplo(cenario: dict[str, Any]) -> str:
    """`` [/os]`` de um cenario de esquema: o id do pytest-bdd leva o exemplo."""
    identificador = str(cenario.get("id", ""))
    return (
        f" {identificador[identificador.index('[') :]}" if "[" in identificador else ""
    )


def _resultado(cenario: dict[str, Any]) -> str:
    estados = {
        passo.get("result", {}).get("status") for passo in cenario.get("steps", [])
    }
    if "failed" in estados:
        return "falhou"
    # "passou" so quando todo passo passou: cenario sem passo, ou com passo pendente,
    # pulado ou sem definicao, nao prova nada.
    return "passou" if estados == {"passed"} else "não executado"


def gerar_resumo(
    cucumber: list[dict[str, Any]], registros: Registros, titulo: str
) -> str:
    """Tabela em Markdown: um cenario por linha, com resultado, duracao e rastreio."""
    linhas = []
    total = 0.0
    falhas = 0
    for funcionalidade in cucumber:
        for cenario in funcionalidade.get("elements", []):
            nome = str(cenario.get("name", ""))
            exibido = nome + _exemplo(cenario)
            tags = " ".join(f"`@{t['name']}`" for t in cenario.get("tags", []))
            resultado = _resultado(cenario)
            duracao = _duracao(cenario)
            total += duracao
            falhas += resultado != "passou"
            achados = registros.get(nome, {})
            linhas.append(
                f"| {exibido} | {tags} | {resultado} | {_virgula(duracao)} | "
                f"`{achados.get('ordem_id', '-')}` | `{achados.get('trace_id', '-')}` |"
            )
    cabecalho = [
        f"## {titulo}",
        "",
        f"{len(linhas)} cenários, {falhas} sem passar, {total:.0f} s no total.",
        "",
        "| Cenário | Tags | Resultado | Duração (s) | ordem_id | trace_id |",
        "|---|---|---|---|---|---|",
    ]
    return "\n".join([*cabecalho, *linhas, ""])


def escrever_resumo(diretorio: Path, titulo: str = "Resumo do E2E da saga") -> Path:
    """Le cucumber.json e cenarios.json de ``diretorio`` e escreve o resumo.md."""
    cucumber = json.loads((diretorio / "cucumber.json").read_text())
    registros_arquivo = diretorio / "cenarios.json"
    registros = (
        json.loads(registros_arquivo.read_text()) if registros_arquivo.exists() else {}
    )
    texto = gerar_resumo(cucumber, registros, titulo)
    destino = diretorio / "resumo.md"
    destino.write_text(texto)
    resumo_do_actions = os.environ.get("GITHUB_STEP_SUMMARY")
    if resumo_do_actions:
        with Path(resumo_do_actions).open("a") as arquivo:
            arquivo.write(texto + "\n")
    return destino


def principal(argumentos: list[str]) -> int:
    if len(argumentos) != 1:
        print("uso: python -m e2e.resumo <diretorio dos relatorios>", file=sys.stderr)
        return 2
    diretorio = Path(argumentos[0])
    try:
        destino = escrever_resumo(diretorio)
    except FileNotFoundError:
        print(
            f"sem {diretorio / 'cucumber.json'}: o pytest terminou antes de escrever "
            "os relatorios (veja a saida acima)",
            file=sys.stderr,
        )
        return 1
    print(f"resumo escrito em {destino}")
    return 0
