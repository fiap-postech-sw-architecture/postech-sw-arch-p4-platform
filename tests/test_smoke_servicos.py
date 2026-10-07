"""scripts/ci/smoke-servicos.sh com kubectl, curl e sleep falsos.

O cluster falso sai de um JSON por namespace: Jobs, Deployments e
StatefulSets, pods anotados, o up de cada pod no Prometheus (que pode chegar
so depois de algumas consultas) e o codigo da conexao do rabbitmq-0 ao banco;
o curl responde pelo caminho. O teste confere a tabela servico | etapa |
resultado (saida e summary), que cada etapa reprova o que deve reprovar e
nomeia o servico, que erro do cluster numa consulta vira FAILED sem parar o
smoke, a espera do Prometheus, a conexao ao banco de cada servico pelo
rabbitmq-0, o prazo de cada chamada e o certificado sem verificacao so no
localhost.
"""

from __future__ import annotations

import json
import os
import re

# subprocess so roda o script do repositorio, sem shell.
import subprocess  # nosec B404
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ci" / "smoke-servicos.sh"
SERVICOS = {
    "os-service": ("pytstop-os", "/os", "os-postgres", "5432"),
    "billing-service": ("pytstop-billing", "/billing", "billing-mongo", "27017"),
    "execution-service": ("pytstop-execucao", "/execucao", "execucao-postgres", "5432"),
}
ETAPAS = 6


def namespace_saudavel(servico: str) -> dict[str, Any]:
    ns, _, banco, _ = SERVICOS[servico]
    curto = ns.removeprefix("pytstop-")
    pods = [f"{servico}-api-1", f"{servico}-relay-1", f"{banco}-0"]
    return {
        "jobs": [{"nome": f"{curto}-inicializacao", "completo": True}],
        "objetos": [
            {"kind": "Deployment", "nome": f"{servico}-api", "pronto": True},
            {"kind": "Deployment", "nome": f"{servico}-relay", "pronto": True},
            {"kind": "StatefulSet", "nome": banco, "pronto": True},
        ],
        # O pod do Job ja terminou e nao e raspado.
        "pods": [
            *({"nome": pod, "anotado": True, "fase": "Running"} for pod in pods),
            {"nome": f"{curto}-inicializacao-x", "anotado": False, "fase": "Succeeded"},
        ],
        "up": dict.fromkeys(pods, "1"),
        # Consultas ao Prometheus antes de os pods aparecerem.
        "up_depois_de": 0,
        "codigo": "124",
    }


def cluster_saudavel() -> dict[str, Any]:
    estado: dict[str, Any] = {
        ns: namespace_saudavel(servico) for servico, (ns, *_) in SERVICOS.items()
    }
    estado["curl"] = {}
    for _, prefixo, _, _ in SERVICOS.values():
        estado["curl"][f"{prefixo}/api/v1/saude"] = "200"
        estado["curl"][f"{prefixo}/metrics"] = "404"
    return estado


# kubectl falso: so as formas que o script usa. Um namespace com "erro" no
# estado responde como um cluster fora do ar.
KUBECTL_FALSO = r"""
import json
import os
import sys
import urllib.parse
from pathlib import Path

dir_ = Path(os.environ["FALSOS"])
estado = json.loads((dir_ / "estado.json").read_text())
args = sys.argv[1:]
with (dir_ / "kubectl.jsonl").open("a") as log:
    log.write(json.dumps(args) + "\n")
resto = args[3:]  # depois do --context e do --request-timeout
ns = ""
if resto[:1] == ["-n"]:
    ns, resto = resto[1], resto[2:]
if estado.get(ns, {}).get("erro"):
    sys.exit("The connection to the server localhost:8080 was refused")


def items(lista):
    print(json.dumps({"items": lista}))


def anotacoes(pod):
    return {"prometheus.io/scrape": "true"} if pod["anotado"] else {}


if resto[:2] == ["get", "job"]:
    items([
        {"metadata": {"name": job["nome"]},
         "status": {"conditions": [{"type": "Complete", "status": "True"}]}
         if job["completo"] else {}}
        for job in estado[ns]["jobs"]
    ])
elif resto == ["get", "deployment,statefulset", "-o", "json"]:
    items([
        {"kind": o["kind"], "metadata": {"name": o["nome"], "generation": 2},
         "spec": {"replicas": 1},
         "status": {"observedGeneration": 2, "replicas": 1,
                    "updatedReplicas": 1, "readyReplicas": 1 if o["pronto"] else 0}}
        for o in estado[ns]["objetos"]
    ])
elif resto == ["get", "deployment,statefulset", "-o", "name"]:
    for o in estado[ns]["objetos"]:
        print(f"{o['kind'].lower()}.apps/{o['nome']}")
elif resto == ["get", "pods", "-o", "json"]:
    items([
        {"metadata": {"name": p["nome"], "annotations": anotacoes(p),
                      **({"deletionTimestamp": "2026-10-07T10:00:00Z"}
                         if p.get("saindo") else {})},
         "status": {"phase": p["fase"]}}
        for p in estado[ns]["pods"]
    ])
elif resto[:2] == ["get", "--raw"]:
    caminho, consulta = resto[2].split("?query=")
    prometheus = "/api/v1/namespaces/pytstop-plataforma/services/prometheus:9090"
    assert caminho == f"{prometheus}/proxy/api/v1/query", caminho
    alvo = urllib.parse.unquote(consulta)
    alvo = alvo.removeprefix('up{namespace="').removesuffix('"}')
    contador = dir_ / f"prometheus-{alvo}"
    n = int(contador.read_text()) + 1 if contador.exists() else 1
    contador.write_text(str(n))
    ups = estado[alvo]["up"] if n > estado[alvo]["up_depois_de"] else {}
    print(json.dumps({"data": {"result": [
        {"metric": {"pod": pod, "namespace": alvo}, "value": [0, valor]}
        for pod, valor in ups.items()
    ]}}))
elif ns == "pytstop-plataforma" and resto[:2] == ["exec", "rabbitmq-0"]:
    host, porta = resto[-2:]
    alvo = host.split(".")[1]
    codigo = estado[alvo]["codigo"]
    if codigo != "sem-resposta":
        print(f"code={codigo}")
else:
    sys.exit(f"chamada inesperada: {args}")
"""

CURL_FALSO = r"""
import json
import os
import sys
from pathlib import Path

dir_ = Path(os.environ["FALSOS"])
estado = json.loads((dir_ / "estado.json").read_text())
args = sys.argv[1:]
with (dir_ / "curl.jsonl").open("a") as log:
    log.write(json.dumps(args) + "\n")
url = args[-1]
caminho = "/" + url.split("://", 1)[1].split("/", 1)[1]
# Uma lista e a resposta de cada chamada, em ordem; a ultima se repete.
resposta = estado["curl"].get(caminho, "000")
if isinstance(resposta, list):
    contador = dir_ / ("curl-" + caminho.replace("/", "_"))
    n = int(contador.read_text()) if contador.exists() else 0
    contador.write_text(str(n + 1))
    resposta = resposta[min(n, len(resposta) - 1)]
print(resposta, end="")
"""

SLEEP_FALSO = r"""
import json
import os
import sys
from pathlib import Path

with (Path(os.environ["FALSOS"]) / "sleep.jsonl").open("a") as log:
    log.write(json.dumps(sys.argv[1:]) + "\n")
"""


class Smoke:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp = tmp_path
        binarios = tmp_path / "bin"
        binarios.mkdir()
        for nome, codigo in (
            ("kubectl", KUBECTL_FALSO),
            ("curl", CURL_FALSO),
            ("sleep", SLEEP_FALSO),
        ):
            binario = binarios / nome
            binario.write_text(f"#!{sys.executable}\n{codigo}", encoding="utf-8")
            binario.chmod(0o755)
        self.summary = tmp_path / "summary.md"
        self.env = {
            chave: valor
            for chave, valor in os.environ.items()
            if chave not in {"KUBE_CONTEXT", "BORDA", "GITHUB_STEP_SUMMARY"}
        } | {
            "PATH": f"{binarios}{os.pathsep}{os.environ['PATH']}",
            "FALSOS": str(tmp_path),
            "GITHUB_STEP_SUMMARY": str(self.summary),
        }

    def roda(
        self, estado: dict[str, Any], *servicos: str, **ambiente: str
    ) -> subprocess.CompletedProcess[str]:
        (self.tmp / "estado.json").write_text(json.dumps(estado), encoding="utf-8")
        return subprocess.run(  # noqa: S603  # nosec B603
            [str(SCRIPT), *servicos],
            env=self.env | ambiente,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )

    def chamadas(self, falso: str) -> list[Any]:
        arquivo = self.tmp / f"{falso}.jsonl"
        if not arquivo.exists():
            return []
        return [json.loads(linha) for linha in arquivo.read_text().splitlines()]

    def linhas(self) -> list[tuple[str, str, str]]:
        """As linhas da tabela do summary: servico, etapa, resultado."""
        return [
            (servico, etapa, resultado)
            for servico, etapa, resultado in re.findall(
                r"^\| (\S+) \| ([^|]+) \| ([^|]+) \|$",
                self.summary.read_text(),
                flags=re.MULTILINE,
            )
            if servico != "Service"
        ]


@pytest.fixture
def smoke(tmp_path: Path) -> Smoke:
    return Smoke(tmp_path)


def test_servicos_saudaveis_passam_em_todas_as_etapas(smoke: Smoke) -> None:
    processo = smoke.roda(cluster_saudavel())

    assert processo.returncode == 0, processo.stderr
    assert smoke.linhas() == [
        linha
        for servico, (ns, prefixo, banco, porta) in SERVICOS.items()
        for linha in (
            (
                servico,
                "initialization Job",
                f"ok: {ns.removeprefix('pytstop-')}-inicializacao=true",
            ),
            (servico, "rollouts", "ok: 3 ready"),
            (servico, f"GET {prefixo}/api/v1/saude", "ok: 200"),
            (servico, f"GET {prefixo}/metrics", "ok: 404"),
            (servico, "up = 1 in Prometheus", "ok: 3 pods"),
            (
                servico,
                f"rabbitmq-0 -> {banco}.{ns}.svc.cluster.local:{porta}",
                "ok: blocked (connection timed out)",
            ),
        )
    ]
    assert smoke.summary.read_text().startswith(
        "### Services smoke\n\n| Service | Stage | Result |\n|---|---|---|\n"
    )
    assert processo.stdout.endswith(
        "services smoke OK: os-service billing-service execution-service\n"
    )
    assert smoke.chamadas("sleep") == []


def test_conexao_ao_banco_sai_do_rabbitmq_0_com_prazo_no_pod(smoke: Smoke) -> None:
    processo = smoke.roda(cluster_saudavel())

    assert processo.returncode == 0, processo.stderr
    conexoes = [chamada for chamada in smoke.chamadas("kubectl") if "exec" in chamada]
    assert [chamada[-2:] for chamada in conexoes] == [
        [f"{banco}.{ns}.svc.cluster.local", porta]
        for ns, _, banco, porta in SERVICOS.values()
    ]
    for chamada in conexoes:
        assert chamada[:7] == [
            "--context",
            "kind-pytstop-p4",
            "--request-timeout=20s",
            "-n",
            "pytstop-plataforma",
            "exec",
            "rabbitmq-0",
        ]
        assert chamada[9:12] == ["--", "bash", "-c"]
        assert chamada[12].startswith('timeout 3 bash -c "</dev/tcp/$0/$1"')


# Uma falha no Billing, por etapa: o que muda no cluster e a linha esperada.
FALHAS: dict[str, tuple[Callable[[dict[str, Any]], object], tuple[str, str]]] = {
    "job-incompleto": (
        lambda e: e["pytstop-billing"]["jobs"][0].update(completo=False),
        ("initialization Job", "FAILED: billing-inicializacao=false"),
    ),
    "sem-job": (
        lambda e: e["pytstop-billing"].update(jobs=[]),
        (
            "initialization Job",
            "FAILED: no Job labeled app.kubernetes.io/component=inicializacao",
        ),
    ),
    "deployment-pendente": (
        lambda e: e["pytstop-billing"]["objetos"][1].update(pronto=False),
        ("rollouts", "FAILED: Deployment/billing-service-relay"),
    ),
    "banco-pendente": (
        lambda e: e["pytstop-billing"]["objetos"][2].update(pronto=False),
        ("rollouts", "FAILED: StatefulSet/billing-mongo"),
    ),
    "sem-objetos": (
        lambda e: e["pytstop-billing"].update(objetos=[]),
        ("rollouts", "FAILED: 0 ready"),
    ),
    "saude-503": (
        lambda e: e["curl"].update({"/billing/api/v1/saude": "503"}),
        ("GET /billing/api/v1/saude", "FAILED: 503"),
    ),
    "metrics-aberto": (
        lambda e: e["curl"].update({"/billing/metrics": "200"}),
        ("GET /billing/metrics", "FAILED: 200"),
    ),
    "pod-sem-up": (
        lambda e: e["pytstop-billing"]["up"].pop("billing-service-relay-1"),
        ("up = 1 in Prometheus", "FAILED: missing billing-service-relay-1"),
    ),
    "pod-com-up-0": (
        lambda e: e["pytstop-billing"]["up"].update({"billing-mongo-0": "0"}),
        ("up = 1 in Prometheus", "FAILED: missing billing-mongo-0"),
    ),
    "sem-pod-anotado": (
        lambda e: e["pytstop-billing"].update(pods=[]),
        ("up = 1 in Prometheus", "FAILED: no annotated pod running"),
    ),
    "banco-alcancavel": (
        lambda e: e["pytstop-billing"].update(codigo="0"),
        (
            "rabbitmq-0 -> billing-mongo.pytstop-billing.svc.cluster.local:27017",
            "FAILED: connected: no NetworkPolicy denies it",
        ),
    ),
    "conexao-recusada": (
        lambda e: e["pytstop-billing"].update(codigo="1"),
        (
            "rabbitmq-0 -> billing-mongo.pytstop-billing.svc.cluster.local:27017",
            "FAILED: refused or unknown host (code 1), which does not prove the rule",
        ),
    ),
    "rabbitmq-sem-resposta": (
        lambda e: e["pytstop-billing"].update(codigo="sem-resposta"),
        (
            "rabbitmq-0 -> billing-mongo.pytstop-billing.svc.cluster.local:27017",
            "FAILED: no answer from rabbitmq-0",
        ),
    ),
}


@pytest.mark.parametrize("falha", FALHAS)
def test_etapa_que_falha_reprova_so_ela_e_nomeia_o_servico(
    smoke: Smoke, falha: str
) -> None:
    estado = cluster_saudavel()
    muda, (etapa, resultado) = FALHAS[falha]
    muda(estado)

    processo = smoke.roda(estado)

    assert processo.returncode == 1
    assert processo.stderr.endswith("services smoke FAILED: billing-service\n")
    reprovadas = [linha for linha in smoke.linhas() if "FAILED" in linha[2]]
    assert reprovadas == [("billing-service", etapa, resultado)]
    assert len(smoke.linhas()) == ETAPAS * len(SERVICOS)


def test_erro_do_cluster_vira_failed_e_o_smoke_segue(smoke: Smoke) -> None:
    estado = cluster_saudavel()
    estado["pytstop-os"]["erro"] = True

    processo = smoke.roda(estado)

    assert processo.returncode == 1
    assert processo.stderr.endswith("services smoke FAILED: os-service\n")
    falharam = {
        (servico, etapa)
        for servico, etapa, resultado in smoke.linhas()
        if "FAILED" in resultado
    }
    assert falharam == {
        ("os-service", "initialization Job"),
        ("os-service", "rollouts"),
        ("os-service", "up = 1 in Prometheus"),
    }
    assert len(smoke.linhas()) == ETAPAS * len(SERVICOS)


def test_saude_ganha_tempo_ate_o_kong_ter_o_alvo(smoke: Smoke) -> None:
    estado = cluster_saudavel()
    estado["curl"]["/billing/api/v1/saude"] = ["503", "404", "503", "200"]

    processo = smoke.roda(estado)

    assert processo.returncode == 0, processo.stderr
    assert len(smoke.chamadas("sleep")) == 3


def test_saude_que_nunca_responde_esgota_a_espera_de_1_min(smoke: Smoke) -> None:
    estado = cluster_saudavel()
    estado["curl"]["/os/api/v1/saude"] = "503"

    processo = smoke.roda(estado, "os-service")

    assert processo.returncode == 1
    assert len(smoke.chamadas("sleep")) == 30
    assert ("os-service", "GET /os/api/v1/saude", "FAILED: 503") in smoke.linhas()


def test_pod_saindo_de_um_rollout_nao_conta_no_prometheus(smoke: Smoke) -> None:
    estado = cluster_saudavel()
    estado["pytstop-billing"]["pods"].append(
        {
            "nome": "billing-service-api-0",
            "anotado": True,
            "fase": "Running",
            "saindo": True,
        }
    )

    processo = smoke.roda(estado)

    assert processo.returncode == 0, processo.stderr
    assert ("billing-service", "up = 1 in Prometheus", "ok: 3 pods") in smoke.linhas()


def test_prometheus_ganha_tempo_ate_os_pods_aparecerem(smoke: Smoke) -> None:
    estado = cluster_saudavel()
    estado["pytstop-execucao"]["up_depois_de"] = 2

    processo = smoke.roda(estado)

    assert processo.returncode == 0, processo.stderr
    assert len(smoke.chamadas("sleep")) == 2


def test_pod_que_nunca_aparece_esgota_a_espera_de_45_s(smoke: Smoke) -> None:
    estado = cluster_saudavel()
    estado["pytstop-os"]["up_depois_de"] = 100

    processo = smoke.roda(estado, "os-service")

    assert processo.returncode == 1
    assert len(smoke.chamadas("sleep")) == 9


def test_curl_com_prazo_e_sem_verificar_certificado_so_no_localhost(
    smoke: Smoke,
) -> None:
    smoke.roda(cluster_saudavel(), "os-service")
    smoke.roda(cluster_saudavel(), "os-service", BORDA="https://pytstop.exemplo.dev")

    chamadas = smoke.chamadas("curl")
    assert len(chamadas) == 4
    assert all("--max-time" in chamada for chamada in chamadas)
    assert [("-k" in chamada, chamada[-1]) for chamada in chamadas] == [
        (True, "https://localhost/os/api/v1/saude"),
        (True, "https://localhost/os/metrics"),
        (False, "https://pytstop.exemplo.dev/os/api/v1/saude"),
        (False, "https://pytstop.exemplo.dev/os/metrics"),
    ]
    kubectl = smoke.chamadas("kubectl")
    assert {tuple(chamada[:3]) for chamada in kubectl} == {
        ("--context", "kind-pytstop-p4", "--request-timeout=20s")
    }


def test_so_os_servicos_pedidos_e_no_contexto_do_ambiente(smoke: Smoke) -> None:
    processo = smoke.roda(cluster_saudavel(), "execution-service", KUBE_CONTEXT="outro")

    assert processo.returncode == 0, processo.stderr
    assert {linha[0] for linha in smoke.linhas()} == {"execution-service"}
    assert {chamada[1] for chamada in smoke.chamadas("kubectl")} == {"outro"}


def test_servico_desconhecido_para_antes_de_consultar(smoke: Smoke) -> None:
    processo = smoke.roda(cluster_saudavel(), "os-service", "web-service")

    assert processo.returncode == 2
    assert "unknown service web-service" in processo.stderr
    assert smoke.chamadas("kubectl") == []
