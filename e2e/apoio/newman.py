"""Newman no kind: runtime privado, prazo e evidencia sem corpos nem credenciais."""

from __future__ import annotations

import contextlib
import json
import math
import os
import re
import signal
import subprocess  # nosec B404
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlsplit

from e2e.apoio.evidencia import permitidos, varrer, varrer_pasta
from e2e.apoio.saga import STATUS_EM_ORDEM, divergencias_das_metricas
from e2e.apoio.segredos import CREDENCIAIS_DO_AMBIENTE, mascarar, registrar

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from typing import IO

COLLECTION = (
    Path(__file__).resolve().parents[2]
    / "docs/api/fluxo-completo.postman_collection.json"
)
PACOTE = "newman@6.2.3"
_PRAZO_DA_VERSAO = 30.0


def conferir_ambiente(ambiente: Mapping[str, str]) -> None:
    """Recusa sandbox, escape e origem remota antes de executar fixtures."""
    __tracebackhide__ = True
    base = urlsplit(ambiente.get("E2E_URL", "https://localhost"))
    contexto = ambiente.get("KUBE_CONTEXT", "kind-pytstop-p4")
    if (
        ambiente.get("E2E_MP_MODO")
        or ambiente.get("E2E_CONTEXTO_NAO_DESCARTAVEL")
        or not contexto.startswith("kind-")
        or base.hostname not in {"localhost", "127.0.0.1"}
        or base.scheme not in {"http", "https"}
        or base.username
        or base.password
        or base.path not in {"", "/"}
        or base.query
        or base.fragment
    ):
        raise AssertionError("Newman exige kind local, sem sandbox nem escape")


def _rodar(
    argumentos: Sequence[str],
    prazo: float,
    *,
    env: Mapping[str, str],
    stdout: int | IO[bytes] = subprocess.DEVNULL,
) -> int:
    """Descarta stdout/stderr e encerra o grupo inteiro em timeout ou interrupcao."""
    __tracebackhide__ = True
    with subprocess.Popen(  # noqa: S603  # nosec B603
        list(argumentos),
        stdin=subprocess.DEVNULL,
        stdout=stdout,
        stderr=subprocess.DEVNULL,
        env=env,
        start_new_session=True,
        umask=0o077,
    ) as processo:
        try:
            return processo.wait(timeout=prazo)
        except subprocess.TimeoutExpired:
            raise AssertionError("Newman passou do prazo") from None
        finally:
            # O npm tambem cria filhos: matar so o PID do npx deixa o runtime vivo.
            with contextlib.suppress(ProcessLookupError):
                os.killpg(processo.pid, signal.SIGKILL)
            processo.wait()


def _conferir_versao(pacote: str, pasta: Path, env: Mapping[str, str]) -> None:
    """Valida so a versao; stdout fica privado e filhos nao sobrevivem ao prazo."""
    __tracebackhide__ = True
    arquivo = pasta / "versao.txt"
    try:
        with arquivo.open("wb") as saida:
            arquivo.chmod(0o600)
            codigo = _rodar(
                ["npx", "--yes", pacote, "--version"],
                _PRAZO_DA_VERSAO,
                env=env,
                stdout=saida,
            )
    except AssertionError:
        raise AssertionError("Newman: consulta de versao passou do prazo") from None
    except OSError:
        raise AssertionError("Newman: nao foi possivel conferir a versao") from None
    if codigo != 0 or arquivo.read_bytes().strip() != b"6.2.3":
        raise AssertionError("Newman: versao diferente da fixada")


def _numero(valor: Any) -> bool:
    return type(valor) in {int, float} and math.isfinite(valor) and valor >= 0


_PROVAS = frozenset(
    {
        "Historico",
        "Estoque reservado",
        "Estoque baixado",
        "Pagamento confirmado",
        "Saga concluida",
        "Entregar",
        "Metricas admin",
    }
)


def _prova(nome: str, resposta: dict[str, Any]) -> Any:
    """Valores de negocio fechados; o resto do corpo nunca entra na evidencia."""
    __tracebackhide__ = True
    try:
        dados = json.loads(bytes(resposta["stream"]["data"]))
        if nome == "Historico":
            historico = [m["para"] for m in dados["mudancas"]]
            return historico if historico == list(STATUS_EM_ORDEM) else None
        if nome.startswith("Estoque "):
            campos = (
                "quantidade_disponivel",
                "quantidade_reservada",
                "quantidade_livre",
            )
            if all(type(dados[k]) is int and dados[k] >= 0 for k in campos):
                return permitidos(dados, campos)
        if nome == "Pagamento confirmado" and (
            dados["status"] == "CONFIRMADO"
            and dados["valor"] == "210.00"
            and dados["moeda"] == "BRL"
        ):
            return permitidos(dados, ("status", "valor", "moeda"))
        if nome == "Saga concluida" and dados["etapa"] == "concluida":
            return "concluida"
        if nome == "Entregar" and dados["status"] == "entregue":
            return "entregue"
        if (
            nome == "Metricas admin"
            and not divergencias_das_metricas(dados)
            and all(
                _numero(x) for x in dados["tempo_medio_por_status_segundos"].values()
            )
        ):
            return permitidos(
                dados, ("total", "por_status", "tempo_medio_por_status_segundos")
            )
    except (KeyError, TypeError, ValueError):
        pass
    return None


def _resumir(
    bruto: dict[str, Any], artefato: dict[str, Any], saida: int
) -> dict[str, Any]:
    """Projeta campos de tipos fechados; nunca copia erro, URL ou corpo do runtime."""
    __tracebackhide__ = True
    itens = {item["id"]: item for item in artefato["item"]}
    script = "\n".join(artefato["event"][0]["script"]["exec"])
    nomes = set(re.findall(r"check\('([^']+)'", script))
    run = bruto["run"]
    estatisticas = permitidos(run["stats"]["assertions"], ("total", "failed"))
    if not all(type(estatisticas.get(k)) is int for k in ("total", "failed")):
        raise ValueError("contagem invalida")
    requisicoes = []
    evidencias = {}
    vistos = set()
    falhou = False
    for execucao in run["executions"]:
        item = itens[execucao["item"]["id"]]
        vistos.add(item["id"])
        if item["name"] in _PROVAS:
            prova = _prova(item["name"], execucao.get("response") or {})
            if prova is not None:
                evidencias[item["name"]] = prova
        resposta = permitidos(execucao.get("response") or {}, ("code", "responseTime"))
        codigo = resposta.get("code")
        duracao = resposta.get("responseTime")
        assertions = []
        for assertion in execucao.get("assertions", []):
            nome = assertion.get("assertion")
            conhecido = nome in nomes
            passou = conhecido and not assertion.get("error")
            falhou |= not passou
            assertions.append(
                {
                    "nome": nome if conhecido else "Assertion desconhecida",
                    "aprovada": passou,
                }
            )
        requisicoes.append(
            {
                "etapa": item["name"],
                "metodo": item["request"]["method"],
                "rota": item["request"]["url"],
                "codigo": codigo if type(codigo) is int else None,
                "duracao_ms": duracao if _numero(duracao) else None,
                "assertions": assertions,
            }
        )
    passou = (
        saida == 0
        and not run["failures"]
        and not falhou
        and estatisticas["total"] > 0
        and estatisticas["failed"] == 0
        and vistos == set(itens)
        and set(evidencias) == {i["name"] for i in itens.values()} & _PROVAS
    )
    return {
        "ferramenta": "newman",
        "versao": "6.2.3",
        "modo": "simulado",
        "resultado": "aprovado" if passou else "reprovado",
        "assertions": estatisticas,
        "requisicoes": requisicoes,
        "evidencias": evidencias,
    }


def _salvar(relatorios: Path, resumo: dict[str, Any]) -> None:
    __tracebackhide__ = True
    dados = mascarar(json.dumps(resumo, indent=2, ensure_ascii=False) + "\n")
    texto = (
        "# Collection do fluxo completo\n\n"
        f"Resultado: {resumo['resultado']}. Ferramenta: Newman 6.2.3.\n\n"
        "Modo: simulador do Billing. Nenhuma chamada ao Mercado Pago.\n\n"
        f"Requisicoes registradas: {len(resumo['requisicoes'])}.\n"
    )
    texto += "\nProvas do fluxo (campos permitidos):\n\n```json\n"
    texto += json.dumps(resumo.get("evidencias", {}), indent=2, ensure_ascii=False)
    texto += "\n```\n"
    if varrer(dados) or varrer(texto) or varrer_pasta(relatorios):
        raise AssertionError("Newman: relatorio recusado pela varredura")
    relatorios.mkdir(parents=True, exist_ok=True)
    (relatorios / "resumo.json").write_text(dados)
    (relatorios / "resumo.md").write_text(texto)


def executar_newman(
    variaveis: Mapping[str, str], *, pacote: str, relatorios: Path
) -> None:
    """Executa a collection fixada e publica apenas a projecao permitida do run."""
    __tracebackhide__ = True
    conferir_ambiente({"E2E_URL": variaveis.get("baseUrl", "https://localhost")})
    for valor in variaveis.values():
        registrar(valor)
    if pacote != PACOTE:
        raise AssertionError("Newman: versao diferente da fixada")
    resumo: dict[str, Any] = {
        "ferramenta": "newman",
        "versao": "6.2.3",
        "modo": "simulado",
        "resultado": "reprovado",
        "assertions": {"total": 0, "failed": 0},
        "requisicoes": [],
    }
    artefato = cast("dict[str, Any]", json.loads(COLLECTION.read_text()))
    env = {k: v for k, v in os.environ.items() if k not in CREDENCIAIS_DO_AMBIENTE}
    with TemporaryDirectory(prefix="pytstop-newman-") as temporario:
        pasta = Path(temporario)
        _conferir_versao(pacote, pasta, env)
        collection = pasta / "collection.json"
        collection.write_text(json.dumps(artefato))
        runtime = pasta / "runtime.json"
        runtime.write_text(
            json.dumps(
                {
                    "values": [
                        {"key": k, "value": v, "enabled": True}
                        for k, v in variaveis.items()
                    ]
                }
            )
        )
        runtime.chmod(0o600)
        raw = pasta / "raw.json"
        argumentos = [
            "npx",
            "--yes",
            pacote,
            "run",
            str(collection),
            "--environment",
            str(runtime),
            "--working-dir",
            str(pasta),
            "--no-insecure-file-read",
            "--reporters",
            "json",
            "--reporter-json-export",
            str(raw),
            "--timeout",
            "600000",
            "--timeout-request",
            "15000",
            "--timeout-script",
            "75000",
            "--delay-request",
            "500",
            "--bail",
            "failure",
            "--ignore-redirects",
            "--color",
            "off",
            "--insecure",
        ]
        try:
            saida = _rodar(
                argumentos,
                630,
                env=env,
            )
            bruto = cast("dict[str, Any]", json.loads(raw.read_text()))
            resumo = _resumir(bruto, artefato, saida)
        except (
            OSError,
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            AssertionError,
        ):
            # Nem a mensagem nem o encadeamento do erro do driver entram na evidencia.
            pass
    _salvar(relatorios, resumo)
    if resumo["resultado"] != "aprovado":
        raise AssertionError("Newman reprovou; consulte o resumo sanitizado")
