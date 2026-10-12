"""scripts/ci/smoke-servicos.sh com kubectl, curl, sleep e date falsos.

O cluster falso sai de um JSON por namespace: Jobs, Deployments e
StatefulSets, pods anotados, o up de cada pod no Prometheus e a metrica com
que o exporter diz se entrou no banco (pg_up ou mongodb_up), ambos podendo
chegar so depois de algumas consultas, o que o psql do pod do banco responde
sem senha, a conexao do pod da API ao banco (o controle) e a do rabbitmq-0; o
curl responde pelo caminho. O relogio e falso: o sleep o adianta, e o date o
le. O teste confere a tabela servico | etapa | resultado (saida e summary), que
cada etapa reprova o que deve reprovar (cada codigo HTTP errado, cada pod e
replica fora do lugar) e nomeia o servico, que erro do cluster numa consulta
vira FAILED sem parar o smoke, as esperas (intervalo e tempo total), o prazo de
cada chamada e o certificado sem verificacao so no localhost.
"""

from __future__ import annotations

import json
import os
import re
import shutil

# subprocess so roda o script do repositorio, sem shell.
import subprocess  # nosec B404
import sys
import urllib.parse
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
# A metrica com que o exporter de cada banco diz se entrou nele.
CONEXAO = {
    "os-service": "pg_up",
    "billing-service": "mongodb_up",
    "execution-service": "pg_up",
}
MENSAGEM_SEM_SENHA = (
    'psql: error: connection to server at "127.0.0.1", port 5432 failed: '
    "fe_sendauth: no password supplied"
)


def etapas(servico: str) -> int:
    """Linhas da tabela de um servico: 11, e uma a mais se o banco e PostgreSQL."""
    return 11 + (CONEXAO[servico] == "pg_up")


def total_de_linhas(*servicos: str) -> int:
    return sum(etapas(servico) for servico in servicos or SERVICOS)


def host_do_banco(servico: str) -> str:
    ns, _, banco, _ = SERVICOS[servico]
    return f"{banco}.{ns}.svc.cluster.local"


def namespace_saudavel(servico: str) -> dict[str, Any]:
    ns, _, banco, _ = SERVICOS[servico]
    curto = ns.removeprefix("pytstop-")
    # A API por ultimo: o controle tem de achar o pod pelo rotulo, nao pegar o
    # primeiro que roda.
    pods = [f"{servico}-relay-1", f"{banco}-0", f"{servico}-api-1"]
    return {
        "jobs": [{"nome": f"{curto}-inicializacao", "condicao": "True"}],
        "objetos": [
            {"kind": "Deployment", "nome": f"{servico}-api", "pronto": True},
            {"kind": "Deployment", "nome": f"{servico}-relay", "pronto": True},
            {"kind": "StatefulSet", "nome": banco, "pronto": True},
        ],
        # O pod do Job ja terminou e nao e raspado. So o da API leva o rotulo
        # app que o Ingress e o smoke usam.
        "pods": [
            {
                "nome": pod,
                "anotado": True,
                "fase": "Running",
                "app": f"{servico}-api" if pod.endswith("-api-1") else None,
            }
            for pod in pods
        ]
        + [{"nome": f"{curto}-inicializacao-x", "anotado": False, "fase": "Succeeded"}],
        "up": dict.fromkeys(pods, "1"),
        # So o exporter do banco tem a metrica de conexao. O valor de um pod
        # pode ser uma lista, um valor por consulta (a ultima se repete).
        "metrica": CONEXAO[servico],
        "conexao": {f"{banco}-0": "1"},
        # Consultas ao Prometheus antes de os pods aparecerem.
        "up_depois_de": 0,
        # O psql como postgres, sem senha, no pod do banco: "pede-senha",
        # "trust", "banco-fora" ou "sem-resposta".
        "loopback": "pede-senha",
        # O codigo da conexao do pod da API ao banco (o controle) e o da
        # conexao do rabbitmq-0.
        "controle": "0",
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
        estado["curl"][f"{prefixo}/api/v1/admin/outbox"] = "404"
        estado["curl"][f"{prefixo}/docs"] = "200"
        estado["curl"][f"{prefixo}/openapi.json"] = "200"
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


def condicoes(job):
    if job["condicao"] is None:
        return {}
    return {"conditions": [{"type": "Complete", "status": job["condicao"]}]}


if resto[:2] == ["get", "job"]:
    items([
        {"metadata": {"name": job["nome"]}, "status": condicoes(job)}
        for job in estado[ns]["jobs"]
    ])
elif resto == ["get", "deployment,statefulset", "-o", "json"]:
    items([
        {"kind": o["kind"],
         "metadata": {"name": o["nome"], "generation": 2},
         "spec": {"replicas": 1},
         "status": {"observedGeneration": o.get("geracao_vista", 2),
                    "replicas": 1,
                    "updatedReplicas": o.get("atualizados", 1),
                    "readyReplicas": 1 if o["pronto"] else 0}}
        for o in estado[ns]["objetos"]
    ])
elif resto == ["get", "deployment,statefulset", "-o", "name"]:
    for o in estado[ns]["objetos"]:
        print(f"{o['kind'].lower()}.apps/{o['nome']}")
elif resto == ["get", "pods", "-o", "json"]:
    items([
        {"metadata": {"name": p["nome"], "annotations": anotacoes(p),
                      "labels": {"app": p["app"]} if p.get("app") else {},
                      **({"deletionTimestamp": "2026-10-07T10:00:00Z"}
                         if p.get("saindo") else {})},
         "status": {"phase": p["fase"]}}
        for p in estado[ns]["pods"]
    ])
elif resto[:2] == ["get", "--raw"]:
    caminho, consulta = resto[2].split("?query=")
    prometheus = "/api/v1/namespaces/pytstop-plataforma/services/prometheus:9090"
    assert caminho == f"{prometheus}/proxy/api/v1/query", caminho
    consulta = urllib.parse.unquote(consulta).removesuffix('"}')
    metrica, alvo = consulta.split('{namespace="')
    if estado[alvo].get("erro"):
        sys.exit("The connection to the server localhost:8080 was refused")
    contador = dir_ / f"prometheus-{alvo}-{metrica}"
    n = int(contador.read_text()) + 1 if contador.exists() else 1
    contador.write_text(str(n))
    # Uma metrica que o namespace nao expoe volta sem serie, como no Prometheus.
    if metrica == "up":
        series = estado[alvo]["up"]
    elif metrica == estado[alvo]["metrica"]:
        series = estado[alvo]["conexao"]
    else:
        series = {}
    if n <= estado[alvo]["up_depois_de"]:
        series = {}
    resultado = []
    for pod, valor in series.items():
        if isinstance(valor, list):
            valor = valor[min(n - 1, len(valor) - 1)]
        rotulos = {"pod": pod, "namespace": alvo}
        resultado.append({"metric": rotulos, "value": [0, valor]})
    print(json.dumps({"data": {"result": resultado}}))
elif ns == "pytstop-plataforma" and resto[:2] == ["exec", "rabbitmq-0"]:
    host, porta = resto[-2:]
    alvo = host.split(".")[1]
    codigo = estado[alvo]["codigo"]
    if codigo != "sem-resposta":
        print(f"code={codigo}")
elif resto[:1] == ["exec"] and resto[2:4] == ["-c", "postgres"]:
    # O psql como postgres, sem senha, dentro do pod do banco.
    assert resto[1].endswith("-0"), resto
    assert resto[-1].startswith("psql -h 127.0.0.1 -U postgres -w "), resto
    modo = estado[ns]["loopback"]
    if modo == "pede-senha":
        print(os.environ["MENSAGEM_SEM_SENHA"] + "\ncode=2")
    elif modo == "trust":
        print(" ?column? \n----------\n        1\n(1 row)\n\ncode=0")
    elif modo == "banco-fora":
        print('psql: error: connection to server at "127.0.0.1", port 5432 '
              "failed: Connection refused\ncode=2")
elif resto[:1] == ["exec"]:
    # O controle: a sonda do pod da API ao banco, do proprio namespace.
    host, porta = resto[-2:]
    assert host.split(".")[1] == ns, resto
    assert "python" in resto[-3], resto
    if estado[ns]["controle"] != "sem-resposta":
        print(f"code={estado[ns]['controle']}")
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

# O relogio falso: o sleep registra o argumento e adianta o relogio (sem
# dormir), e o date +%s o le. Assim uma espera "de 1 min" se prova pelo tempo
# que o script quis esperar, nao pela contagem de voltas.
SLEEP_FALSO = r"""
import json
import os
import sys
from pathlib import Path

dir_ = Path(os.environ["FALSOS"])
with (dir_ / "sleep.jsonl").open("a") as log:
    log.write(json.dumps(sys.argv[1:]) + "\n")
relogio = dir_ / "relogio"
atual = float(relogio.read_text()) if relogio.exists() else 0.0
relogio.write_text(str(atual + float(sys.argv[1])))
"""

DATE_FALSO = r"""
import os
import sys
from pathlib import Path

if sys.argv[1:] != ["+%s"]:
    os.execv("/bin/date", ["date", *sys.argv[1:]])
relogio = Path(os.environ["FALSOS"]) / "relogio"
print(int(1_800_000_000 + (float(relogio.read_text()) if relogio.exists() else 0.0)))
"""

# So o Linux tem timeout; o falso o poe no PATH tambem no macOS, onde o script
# cai no alarm do perl.
TIMEOUT_FALSO = r"""
import json
import os
import sys
from pathlib import Path

with (Path(os.environ["FALSOS"]) / "timeout.jsonl").open("a") as log:
    log.write(json.dumps(sys.argv[1:]) + "\n")
os.execvp(sys.argv[2], sys.argv[2:])
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
            ("date", DATE_FALSO),
        ):
            binario = binarios / nome
            binario.write_text(f"#!{sys.executable}\n{codigo}", encoding="utf-8")
            binario.chmod(0o755)
        self.summary = tmp_path / "summary.md"
        self.env = {
            chave: valor
            for chave, valor in os.environ.items()
            if chave not in {"KUBE_CONTEXT", "CLUSTER", "BORDA", "GITHUB_STEP_SUMMARY"}
        } | {
            "PATH": f"{binarios}{os.pathsep}{os.environ['PATH']}",
            "FALSOS": str(tmp_path),
            "GITHUB_STEP_SUMMARY": str(self.summary),
            "MENSAGEM_SEM_SENHA": MENSAGEM_SEM_SENHA,
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

    def sleeps(self) -> list[float]:
        """Os segundos de cada sleep, em ordem."""
        return [float(chamada[0]) for chamada in self.chamadas("sleep")]

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

    def reprovadas(self) -> list[tuple[str, str, str]]:
        return [linha for linha in self.linhas() if "FAILED" in linha[2]]


@pytest.fixture
def smoke(tmp_path: Path) -> Smoke:
    return Smoke(tmp_path)


def linhas_saudaveis(servico: str) -> list[tuple[str, str, str]]:
    ns, prefixo, banco, porta = SERVICOS[servico]
    host = host_do_banco(servico)
    linhas = [
        (
            servico,
            "initialization Job",
            f"ok: {ns.removeprefix('pytstop-')}-inicializacao=true",
        ),
        (servico, "rollouts", "ok: 3 ready"),
        (servico, f"GET {prefixo}/api/v1/saude", "ok: 200"),
        (servico, f"GET {prefixo}/metrics", "ok: 404"),
        (servico, f"GET {prefixo}/api/v1/admin/outbox", "ok: 404"),
        (servico, f"GET {prefixo}/docs", "ok: 200"),
        (servico, f"GET {prefixo}/openapi.json", "ok: 200"),
        (servico, "up = 1 in Prometheus", "ok: 3 pods"),
        (servico, f"{CONEXAO[servico]} = 1 in Prometheus", f"ok: {banco}-0"),
    ]
    if CONEXAO[servico] == "pg_up":
        linhas.append(
            (
                servico,
                f"{banco}-0 127.0.0.1 asks for a password",
                "ok: postgres on 127.0.0.1 without a password was refused",
            )
        )
    return [
        *linhas,
        (
            servico,
            f"{servico}-api pod -> {host}:{porta}",
            "ok: connected (the namespace itself reaches the database)",
        ),
        (
            servico,
            f"rabbitmq-0 -> {host}:{porta}",
            "ok: blocked (connection timed out)",
        ),
    ]


def test_servicos_saudaveis_passam_em_todas_as_etapas(smoke: Smoke) -> None:
    processo = smoke.roda(cluster_saudavel())

    assert processo.returncode == 0, processo.stderr
    assert smoke.linhas() == [
        linha for servico in SERVICOS for linha in linhas_saudaveis(servico)
    ]
    assert len(smoke.linhas()) == total_de_linhas()
    assert smoke.summary.read_text().startswith(
        "### Services smoke\n\n| Service | Stage | Result |\n|---|---|---|\n"
    )
    assert processo.stdout.endswith(
        "services smoke OK: os-service billing-service execution-service\n"
    )
    assert smoke.chamadas("sleep") == []


def execs(smoke: Smoke) -> list[list[str]]:
    return [chamada for chamada in smoke.chamadas("kubectl") if "exec" in chamada]


def test_conexao_ao_banco_sai_do_rabbitmq_0_com_prazo_no_pod(smoke: Smoke) -> None:
    processo = smoke.roda(cluster_saudavel())

    assert processo.returncode == 0, processo.stderr
    conexoes = [chamada for chamada in execs(smoke) if "rabbitmq-0" in chamada]
    assert [chamada[-2:] for chamada in conexoes] == [
        [host_do_banco(servico), SERVICOS[servico][3]] for servico in SERVICOS
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


def test_controle_sai_do_pod_da_api_e_a_prova_do_d88_do_pod_do_banco(
    smoke: Smoke,
) -> None:
    processo = smoke.roda(cluster_saudavel())

    assert processo.returncode == 0, processo.stderr
    chamadas = execs(smoke)
    controles = [c for c in chamadas if "python" in c[10]]
    assert [(c[4], c[6]) for c in controles] == [
        (ns, f"{servico}-api-1") for servico, (ns, *_) in SERVICOS.items()
    ]
    for chamada in controles:
        assert chamada[7:10] == ["--", "sh", "-c"]
        # A conexao do controle tem prazo de 3 s, como a sonda do rabbitmq-0.
        assert (
            "socket.create_connection((sys.argv[1], int(sys.argv[2])), 3)"
            in (chamada[10])
        )
    loopbacks = [c for c in chamadas if c[7:9] == ["-c", "postgres"]]
    # So os dois bancos PostgreSQL: o MongoDB nao tem essa prova.
    assert [(c[4], c[6]) for c in loopbacks] == [
        ("pytstop-os", "os-postgres-0"),
        ("pytstop-execucao", "execucao-postgres-0"),
    ]
    for chamada in loopbacks:
        assert chamada[7:11] == ["-c", "postgres", "--", "sh"]
        assert chamada[12] == (
            'psql -h 127.0.0.1 -U postgres -w -c "select 1" 2>&1; echo "code=$?"'
        )


def test_kubectl_exec_vai_com_prazo_em_volta(smoke: Smoke) -> None:
    # Sem o prazo, um pod que nao responde pendura o smoke.
    timeout = smoke.tmp / "bin" / "timeout"
    timeout.write_text(f"#!{sys.executable}\n{TIMEOUT_FALSO}", encoding="utf-8")
    timeout.chmod(0o755)

    processo = smoke.roda(cluster_saudavel())

    assert processo.returncode == 0, processo.stderr
    prazos = smoke.chamadas("timeout")
    # A prova do D88 (so os PostgreSQL), o controle e a conexao do rabbitmq-0.
    assert len(prazos) == 2 + len(SERVICOS) * 2
    for chamada in prazos:
        assert chamada[:2] == ["20", "kubectl"]
        assert "exec" in chamada


# Uma falha por etapa: o que muda no cluster, o servico e as linhas reprovadas.
# Quase todas no Billing; as do PostgreSQL, no OS.
BILLING = "billing-service"
OS = "os-service"
HOST_BILLING = "billing-mongo.pytstop-billing.svc.cluster.local:27017"
CONEXAO_BILLING = f"rabbitmq-0 -> {HOST_BILLING}"
CONTROLE_BILLING = f"billing-service-api pod -> {HOST_BILLING}"
SEM_PROVA = (
    "FAILED: timed out, but the control from billing-service-api did not connect: "
    "the probe proves nothing"
)
LOOPBACK_OS = "os-postgres-0 127.0.0.1 asks for a password"
FALHAS: dict[
    str,
    tuple[
        Callable[[dict[str, Any]], object],
        str,
        list[tuple[str, str]],
    ],
] = {
    "job-sem-condicao": (
        lambda e: e["pytstop-billing"]["jobs"][0].update(condicao=None),
        BILLING,
        [("initialization Job", "FAILED: billing-inicializacao=false")],
    ),
    "job-com-complete-false": (
        lambda e: e["pytstop-billing"]["jobs"][0].update(condicao="False"),
        BILLING,
        [("initialization Job", "FAILED: billing-inicializacao=false")],
    ),
    "sem-job": (
        lambda e: e["pytstop-billing"].update(jobs=[]),
        BILLING,
        [
            (
                "initialization Job",
                "FAILED: no Job labeled app.kubernetes.io/component=inicializacao",
            )
        ],
    ),
    "deployment-pendente": (
        lambda e: e["pytstop-billing"]["objetos"][1].update(pronto=False),
        BILLING,
        [("rollouts", "FAILED: Deployment/billing-service-relay")],
    ),
    "banco-pendente": (
        lambda e: e["pytstop-billing"]["objetos"][2].update(pronto=False),
        BILLING,
        [("rollouts", "FAILED: StatefulSet/billing-mongo")],
    ),
    # Pronto, mas ainda com a revisao antiga de parte das replicas.
    "replicas-nao-atualizadas": (
        lambda e: e["pytstop-billing"]["objetos"][0].update(atualizados=0),
        BILLING,
        [("rollouts", "FAILED: Deployment/billing-service-api")],
    ),
    # Pronto e atualizado, mas na geracao anterior do objeto.
    "geracao-atrasada": (
        lambda e: e["pytstop-billing"]["objetos"][0].update(geracao_vista=1),
        BILLING,
        [("rollouts", "FAILED: Deployment/billing-service-api")],
    ),
    "sem-objetos": (
        lambda e: e["pytstop-billing"].update(objetos=[]),
        BILLING,
        [("rollouts", "FAILED: 0 ready")],
    ),
    "pod-sem-up": (
        lambda e: e["pytstop-billing"]["up"].pop("billing-service-relay-1"),
        BILLING,
        [("up = 1 in Prometheus", "FAILED: missing billing-service-relay-1")],
    ),
    "pod-com-up-0": (
        lambda e: e["pytstop-billing"]["up"].update({"billing-mongo-0": "0"}),
        BILLING,
        [("up = 1 in Prometheus", "FAILED: missing billing-mongo-0")],
    ),
    "sem-pod-anotado": (
        lambda e: e["pytstop-billing"].update(pods=[]),
        BILLING,
        [
            ("up = 1 in Prometheus", "FAILED: no annotated pod running"),
            (
                CONTROLE_BILLING,
                "FAILED: no running pod labeled app=billing-service-api",
            ),
            (CONEXAO_BILLING, SEM_PROVA),
        ],
    ),
    "exporter-sem-a-metrica-do-banco": (
        lambda e: e["pytstop-billing"].update(conexao={}),
        BILLING,
        [("mongodb_up = 1 in Prometheus", "FAILED: no mongodb_up series")],
    ),
    "loopback-em-trust": (
        lambda e: e["pytstop-os"].update(loopback="trust"),
        OS,
        [
            (
                LOOPBACK_OS,
                "FAILED: postgres connected from 127.0.0.1 without a password: trust",
            )
        ],
    ),
    "loopback-recusado-por-outro-motivo": (
        lambda e: e["pytstop-os"].update(loopback="banco-fora"),
        OS,
        [
            (
                LOOPBACK_OS,
                (
                    "FAILED: refused for another reason: psql: error: connection "
                    'to server at "127.0.0.1", port 5432 failed: Connection refused'
                ),
            )
        ],
    ),
    "loopback-sem-resposta": (
        lambda e: e["pytstop-os"].update(loopback="sem-resposta"),
        OS,
        [
            (
                LOOPBACK_OS,
                "FAILED: no answer from os-postgres-0",
            )
        ],
    ),
    "banco-alcancavel": (
        lambda e: e["pytstop-billing"].update(codigo="0"),
        BILLING,
        [(CONEXAO_BILLING, "FAILED: connected: no NetworkPolicy denies it")],
    ),
    "conexao-recusada": (
        lambda e: e["pytstop-billing"].update(codigo="1"),
        BILLING,
        [
            (
                CONEXAO_BILLING,
                (
                    "FAILED: refused or unknown host (code 1), "
                    "which does not prove the rule"
                ),
            )
        ],
    ),
    "rabbitmq-sem-resposta": (
        lambda e: e["pytstop-billing"].update(codigo="sem-resposta"),
        BILLING,
        [(CONEXAO_BILLING, "FAILED: no answer from rabbitmq-0")],
    ),
    # O 124 so vale com o controle: sem ele, a sonda pode estar quebrada.
    "controle-recusado": (
        lambda e: e["pytstop-billing"].update(controle="1"),
        BILLING,
        [
            (
                CONTROLE_BILLING,
                "FAILED: could not connect (code 1)",
            ),
            (CONEXAO_BILLING, SEM_PROVA),
        ],
    ),
    "controle-sem-resposta": (
        lambda e: e["pytstop-billing"].update(controle="sem-resposta"),
        BILLING,
        [
            (
                CONTROLE_BILLING,
                "FAILED: no answer from billing-service-api-1",
            ),
            (CONEXAO_BILLING, SEM_PROVA),
        ],
    ),
}


@pytest.mark.parametrize("falha", FALHAS)
def test_etapa_que_falha_reprova_so_ela_e_nomeia_o_servico(
    smoke: Smoke, falha: str
) -> None:
    estado = cluster_saudavel()
    muda, servico, esperadas = FALHAS[falha]
    muda(estado)

    processo = smoke.roda(estado)

    assert processo.returncode == 1
    assert processo.stderr.endswith(f"services smoke FAILED: {servico}\n")
    assert smoke.reprovadas() == [(servico, *linha) for linha in esperadas]
    assert len(smoke.linhas()) == total_de_linhas()


# Cada codigo diferente do esperado reprova, nao so o que o servico real daria.
ROTAS_DA_BORDA = {
    "/billing/metrics": "404",
    "/billing/api/v1/admin/outbox": "404",
    "/billing/api/v1/saude": "200",
    "/billing/docs": "200",
    "/billing/openapi.json": "200",
}


@pytest.mark.parametrize(
    ("caminho", "obtido"),
    [
        (caminho, obtido)
        for caminho, esperado in ROTAS_DA_BORDA.items()
        for obtido in ("000", "200", "401", "404", "500", "503")
        if obtido != esperado
    ],
)
def test_borda_com_status_diferente_do_esperado_reprova_so_aquele_get(
    smoke: Smoke, caminho: str, obtido: str
) -> None:
    estado = cluster_saudavel()
    estado["curl"][caminho] = obtido

    processo = smoke.roda(estado)

    assert processo.returncode == 1
    assert smoke.reprovadas() == [
        ("billing-service", f"GET {caminho}", f"FAILED: {obtido}")
    ]


def test_erro_do_cluster_vira_failed_e_o_smoke_segue(smoke: Smoke) -> None:
    estado = cluster_saudavel()
    estado["pytstop-os"]["erro"] = True

    processo = smoke.roda(estado)

    assert processo.returncode == 1
    assert processo.stderr.endswith("services smoke FAILED: os-service\n")
    falharam = {(servico, etapa) for servico, etapa, _ in smoke.reprovadas()}
    assert falharam == {
        ("os-service", "initialization Job"),
        ("os-service", "rollouts"),
        ("os-service", "up = 1 in Prometheus"),
        ("os-service", "pg_up = 1 in Prometheus"),
        ("os-service", "os-postgres-0 127.0.0.1 asks for a password"),
        (
            "os-service",
            "os-service-api pod -> os-postgres.pytstop-os.svc.cluster.local:5432",
        ),
        ("os-service", "rabbitmq-0 -> os-postgres.pytstop-os.svc.cluster.local:5432"),
    }
    assert len(smoke.linhas()) == total_de_linhas()


def test_saude_ganha_tempo_ate_o_kong_ter_o_alvo(smoke: Smoke) -> None:
    estado = cluster_saudavel()
    estado["curl"]["/billing/api/v1/saude"] = ["503", "404", "503", "200"]

    processo = smoke.roda(estado)

    assert processo.returncode == 0, processo.stderr
    assert smoke.sleeps() == [2, 2, 2]


def test_saude_que_nunca_responde_esgota_a_espera_de_1_min(smoke: Smoke) -> None:
    estado = cluster_saudavel()
    estado["curl"]["/os/api/v1/saude"] = "503"

    processo = smoke.roda(estado, "os-service")

    assert processo.returncode == 1
    # De 2 em 2 s ate completar o minuto, e nao uma volta a mais.
    assert smoke.sleeps() == [2] * 30
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


def test_pod_anotado_que_ainda_nao_roda_nao_conta_no_prometheus(smoke: Smoke) -> None:
    # Pending: ainda sem container, sem metrica para o Prometheus raspar.
    estado = cluster_saudavel()
    estado["pytstop-billing"]["pods"].append(
        {"nome": "billing-service-api-2", "anotado": True, "fase": "Pending"}
    )

    processo = smoke.roda(estado)

    assert processo.returncode == 0, processo.stderr
    assert ("billing-service", "up = 1 in Prometheus", "ok: 3 pods") in smoke.linhas()


def test_controle_pula_o_pod_da_api_que_esta_saindo(smoke: Smoke) -> None:
    estado = cluster_saudavel()
    estado["pytstop-billing"]["pods"].insert(
        0,
        {
            "nome": "billing-service-api-0",
            "anotado": True,
            "fase": "Running",
            "saindo": True,
            "app": "billing-service-api",
        },
    )

    processo = smoke.roda(estado, "billing-service")

    assert processo.returncode == 0, processo.stderr
    controles = [c for c in execs(smoke) if "python" in c[10]]
    assert [c[6] for c in controles] == ["billing-service-api-1"]


def test_summary_acrescenta_ao_que_os_passos_anteriores_escreveram(
    smoke: Smoke,
) -> None:
    smoke.summary.write_text("### Passo anterior\n\n")

    processo = smoke.roda(cluster_saudavel(), "billing-service")

    assert processo.returncode == 0, processo.stderr
    assert smoke.summary.read_text().startswith(
        "### Passo anterior\n\n### Services smoke\n"
    )


def test_prometheus_ganha_tempo_ate_os_pods_aparecerem(smoke: Smoke) -> None:
    estado = cluster_saudavel()
    estado["pytstop-execucao"]["up_depois_de"] = 2

    processo = smoke.roda(estado)

    assert processo.returncode == 0, processo.stderr
    assert smoke.sleeps() == [5, 5]


def test_pod_que_nunca_aparece_esgota_a_espera_de_45_s(smoke: Smoke) -> None:
    estado = cluster_saudavel()
    estado["pytstop-os"]["up_depois_de"] = 100

    processo = smoke.roda(estado, "os-service")

    assert processo.returncode == 1
    # O up e a metrica do banco esperam juntos: o prazo e um so.
    assert smoke.sleeps() == [5] * 9


@pytest.mark.parametrize("servico", SERVICOS)
def test_exporter_com_up_1_e_banco_desligado_reprova_so_a_conexao(
    smoke: Smoke, servico: str
) -> None:
    # O alvo responde ao Prometheus (up = 1), mas o exporter nao entrou no banco.
    ns, _, banco, _ = SERVICOS[servico]
    metrica = CONEXAO[servico]
    estado = cluster_saudavel()
    estado[ns]["conexao"] = {f"{banco}-0": "0"}

    processo = smoke.roda(estado)

    assert processo.returncode == 1
    assert processo.stderr.endswith(f"services smoke FAILED: {servico}\n")
    assert smoke.reprovadas() == [
        (
            servico,
            f"{metrica} = 1 in Prometheus",
            f"FAILED: {metrica} is not 1 on {banco}-0",
        )
    ]
    assert (servico, "up = 1 in Prometheus", "ok: 3 pods") in smoke.linhas()
    assert smoke.sleeps() == [5] * 9


def test_exporter_ganha_tempo_ate_entrar_no_banco(smoke: Smoke) -> None:
    # O exporter subiu antes do banco: duas raspagens com pg_up 0, e a terceira
    # ja conectada.
    estado = cluster_saudavel()
    estado["pytstop-execucao"]["conexao"] = {"execucao-postgres-0": ["0", "0", "1"]}

    processo = smoke.roda(estado)

    assert processo.returncode == 0, processo.stderr
    assert smoke.sleeps() == [5, 5]
    assert (
        "execution-service",
        "pg_up = 1 in Prometheus",
        "ok: execucao-postgres-0",
    ) in smoke.linhas()


def test_so_um_exporter_desligado_reprova_o_servico_e_nomeia_o_pod(
    smoke: Smoke,
) -> None:
    # Com dois pods de banco, o conectado nao esconde o desligado.
    estado = cluster_saudavel()
    estado["pytstop-os"]["conexao"] = {"os-postgres-0": "1", "os-postgres-1": "0"}

    processo = smoke.roda(estado, "os-service")

    assert processo.returncode == 1
    assert (
        "os-service",
        "pg_up = 1 in Prometheus",
        "FAILED: pg_up is not 1 on os-postgres-1",
    ) in smoke.linhas()


def test_consulta_a_metrica_do_banco_de_cada_servico_no_namespace_dele(
    smoke: Smoke,
) -> None:
    processo = smoke.roda(cluster_saudavel())

    assert processo.returncode == 0, processo.stderr
    consultas = {
        urllib.parse.unquote(chamada[-1].split("?query=")[1])
        for chamada in smoke.chamadas("kubectl")
        if chamada[3:5] == ["get", "--raw"]
    }
    assert consultas == {
        *(f'up{{namespace="{ns}"}}' for ns, *_ in SERVICOS.values()),
        'pg_up{namespace="pytstop-os"}',
        'mongodb_up{namespace="pytstop-billing"}',
        'pg_up{namespace="pytstop-execucao"}',
    }


@pytest.mark.parametrize(
    ("borda", "verifica"),
    [
        ("https://localhost", False),
        ("https://localhost:8443", False),
        ("https://pytstop.exemplo.dev", True),
        # O glob https://localhost:* casava estes, e o -k valeria para outro host.
        ("https://localhost:443@outro.host", True),
        ("https://localhost:8443/outro", True),
        ("https://localhost.exemplo.dev", True),
        ("http://localhost", True),
    ],
)
def test_curl_so_ignora_o_certificado_do_localhost_com_ou_sem_porta(
    smoke: Smoke, borda: str, verifica: bool
) -> None:
    smoke.roda(cluster_saudavel(), "os-service", BORDA=borda)

    chamadas = smoke.chamadas("curl")
    assert len(chamadas) >= 5
    assert all(("-k" in chamada) is (not verifica) for chamada in chamadas)
    assert all(chamada[-1].startswith(borda) for chamada in chamadas)


def test_curl_com_prazo_proprio_na_saude_e_nas_outras_rotas(smoke: Smoke) -> None:
    smoke.roda(cluster_saudavel(), "os-service")

    assert [
        (
            chamada[-1].removeprefix("https://localhost"),
            chamada[chamada.index("--max-time") + 1],
        )
        for chamada in smoke.chamadas("curl")
    ] == [
        ("/os/api/v1/saude", "3"),
        ("/os/metrics", "10"),
        ("/os/api/v1/admin/outbox", "10"),
        ("/os/docs", "10"),
        ("/os/openapi.json", "10"),
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


def test_contexto_segue_o_cluster_do_ambiente_como_nos_outros_scripts(
    smoke: Smoke,
) -> None:
    processo = smoke.roda(cluster_saudavel(), "execution-service", CLUSTER="outro")

    assert processo.returncode == 0, processo.stderr
    assert {chamada[1] for chamada in smoke.chamadas("kubectl")} == {"kind-outro"}


def test_servico_desconhecido_para_antes_de_consultar(smoke: Smoke) -> None:
    processo = smoke.roda(cluster_saudavel(), "os-service", "web-service")

    assert processo.returncode == 2
    assert "unknown service web-service" in processo.stderr
    assert smoke.chamadas("kubectl") == []


@pytest.mark.parametrize(
    ("falta", "mensagem"),
    [
        ("jq", "jq is required"),
        ("curl", "curl is required"),
        ("timeout-e-perl", "timeout or perl is required"),
    ],
)
def test_ferramenta_que_falta_para_com_status_2_antes_de_consultar(
    smoke: Smoke, tmp_path: Path, falta: str, mensagem: str
) -> None:
    # PATH so com o que o script precisa para chegar a checagem (env e bash) e
    # as ferramentas que nao faltam.
    minimo = tmp_path / "minimo"
    minimo.mkdir()
    ferramentas = ["env", "bash", "jq", "curl", "timeout", "perl"]
    if falta == "timeout-e-perl":
        ferramentas = ["env", "bash", "jq", "curl"]
    else:
        ferramentas.remove(falta)
    for nome in ferramentas:
        caminho = shutil.which(nome)
        if caminho:
            (minimo / nome).symlink_to(caminho)

    processo = smoke.roda(cluster_saudavel(), PATH=str(minimo))

    assert processo.returncode == 2
    assert mensagem in processo.stderr
    assert smoke.chamadas("kubectl") == []
