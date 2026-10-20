"""Falsos dos testes do codigo auxiliar do E2E: relogio e executor do kubectl."""

from __future__ import annotations

import json
import os
import stat
import sys
from typing import TYPE_CHECKING, Any

from e2e.apoio.segredos import CREDENCIAIS_DO_AMBIENTE

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

# Credenciais de mentira: o formato imita o do Mercado Pago so para a mascara e a
# varredura as reconhecerem. Nenhuma vale em lugar nenhum.
CHAVE_DO_MP = "TEST-1234567890123456-101420-0a1b2c3d4e5f60718293a4b5c6d7e8f9-123456789"
CHAVE_APP_USR = (
    "APP_USR-1234567890123456-101420-0a1b2c3d4e5f60718293a4b5c6d7e8f9-123456789"
)
ASSINATURA = "assinatura-do-webhook-0123456789abcdef"
# Sem prefixo de token conhecido: a mascara central so a pega se foi registrada.
CHAVE_OPACA = "opaco-0123456789-abcdef"
# O que o trace falso leva de sensivel (na query da URL e no comando do banco): nada
# disto pode chegar a um arquivo da evidencia.
DADO_DO_TRACE = "123.456.789-09"
TRACE_ID_FALSO = "36c945dd0cb1589e33ecc81badd2bd71"
SERVICOS_DA_SAGA = ("os-service", "billing-service", "execution-service")


class Relogio:
    """Relogio e ``dormir`` falsos: dormir avanca o tempo sem esperar de verdade.

    ``limite`` corta a suite se uma regressao deixar um laco dormindo para sempre:
    sem ele, esse bug penduraria o job inteiro.
    """

    def __init__(self, limite: int = 10_000) -> None:
        self.agora = 100.0
        self.dormidas: list[float] = []
        self._limite = limite

    def __call__(self) -> float:
        return self.agora

    def dormir(self, segundos: float) -> None:
        self.dormidas.append(segundos)
        if len(self.dormidas) > self._limite:
            msg = "o laco dormiu mais vezes que o limite: regressao no prazo"
            raise AssertionError(msg)
        self.agora += segundos


def trace_do_jaeger(
    *,
    trace_id: str = TRACE_ID_FALSO,
    spans: int = 4,
    chamada_ao_mp: bool = False,
    servicos: Sequence[str] = SERVICOS_DA_SAGA,
) -> dict[str, Any]:
    """Um trace como o ``/api/traces`` do Jaeger o devolve, com dado que nao deve sair.

    ``spans`` conta tambem o da chamada ao Mercado Pago, que o Billing faz com
    ``chamada_ao_mp``; os spans se repartem entre os ``servicos``.
    """
    processos = {
        f"p{numero}": {
            "serviceName": servico,
            "tags": [{"key": "hostname", "type": "string", "value": f"pod-{numero}"}],
        }
        for numero, servico in enumerate(servicos, start=1)
    }
    do_billing = next(
        (
            p
            for p, dados in processos.items()
            if dados["serviceName"] == "billing-service"
        ),
        "p1",
    )
    lista: list[dict[str, Any]] = []
    for numero in range(1, spans + 1):
        chamada = chamada_ao_mp and numero == 1
        url = (
            "https://api.mercadopago.com/v1/payments/search?external_reference=abc"
            if chamada
            else f"https://x.test/a/{DADO_DO_TRACE}?cpf={DADO_DO_TRACE}"
        )
        lista.append(
            {
                "traceID": trace_id,
                "spanID": f"{numero:016x}",
                "operationName": "GET" if chamada else f"find {DADO_DO_TRACE}",
                "references": [],
                "startTime": 1_790_000_000_000_000 + numero,
                "duration": 10,
                "tags": [
                    {"key": "span.kind", "type": "string", "value": "client"},
                    {"key": "http.url", "type": "string", "value": url},
                    {"key": "db.statement", "type": "string", "value": DADO_DO_TRACE},
                ],
                "logs": [{"timestamp": 1, "fields": []}],
                "processID": do_billing
                if chamada
                else f"p{numero % len(processos) + 1}",
                "warnings": None,
            }
        )
    return {
        "traceID": trace_id,
        "spans": lista,
        "processes": processos,
        "warnings": None,
    }


class ExecutorFalso:
    """Registra os comandos e responde por um trecho do comando."""

    def __init__(self, respostas: dict[str, str] | None = None) -> None:
        self.comandos: list[list[str]] = []
        self.respostas = respostas or {}

    def __call__(self, argumentos: Sequence[str], prazo: float) -> str:
        del prazo
        comando = list(argumentos)
        self.comandos.append(comando)
        for trecho, resposta in self.respostas.items():
            if trecho in " ".join(comando):
                return resposta
        return ""


class ClusterFalso:
    """Deployments com replicas; escalar a 0 esvazia os pods nas consultas."""

    def __init__(self, replicas: dict[str, int], pods_demoram: int = 0) -> None:
        self.replicas = replicas
        self.comandos: list[list[str]] = []
        self._pods_demoram = pods_demoram
        self._consultas = 0

    def __call__(self, argumentos: Sequence[str], prazo: float) -> str:
        comando = list(argumentos)
        self.comandos.append(comando)
        if "scale" in comando:
            nome = comando[comando.index("scale") + 1].split("/")[1]
            self.replicas[nome] = int(comando[-1].split("=")[1])
            self._consultas = 0
        elif "pods" in comando:
            self._consultas += 1
            nome = comando[comando.index("-l") + 1].split("=")[1]
            if self.replicas[nome] == 0 and self._consultas > self._pods_demoram:
                return ""
            return "pod/x\n"
        elif "deployment" in comando and "jsonpath={.spec.replicas}" in comando:
            return str(self.replicas[comando[comando.index("deployment") + 1]])
        return ""

    def escalas(self) -> list[str]:
        return [
            " ".join(c[c.index("scale") + 1 :]) for c in self.comandos if "scale" in c
        ]

    def prontos(self) -> list[str]:
        return [c[c.index("rollout") + 2] for c in self.comandos if "rollout" in c]


# kubectl falso: "sai" morre com erro; "nao-escuta" fica vivo sem abrir a porta;
# "jaeger" (um dos Services da sessao) morre com erro; o resto escuta. Todo
# processo anota o proprio pid em pids, ao lado do script, e quais credenciais do
# Mercado Pago (nunca o valor) havia no ambiente que recebeu, em ambiente.
_KUBECTL_FALSO = """\
#!{python}
import os, socket, sys, time
from pathlib import Path
args = sys.argv[1:]
with Path(__file__).with_name("pids").open("a") as pids:
    pids.write(f"{{os.getpid()}}\\n")
with Path(__file__).with_name("ambiente").open("a") as ambiente:
    ambiente.write(",".join(c for c in {credenciais!r} if c in os.environ) + "\\n")
if "sai" in args or "svc/jaeger" in args:
    sys.stderr.write("error: unable to listen on port: address already in use\\n")
    sys.exit(3)
if "nao-escuta" in args:
    time.sleep(60)
porta = int(args[-1].split(":")[0])
servidor = socket.socket()
servidor.bind(("127.0.0.1", porta))
servidor.listen()
time.sleep(60)
"""


def criar_kubectl_falso(tmp_path: Path) -> Path:
    """Escreve o kubectl falso (um script Python executavel) em ``tmp_path``."""
    caminho = tmp_path / "kubectl"
    caminho.write_text(
        _KUBECTL_FALSO.format(
            python=sys.executable, credenciais=CREDENCIAIS_DO_AMBIENTE
        )
    )
    caminho.chmod(caminho.stat().st_mode | stat.S_IXUSR)
    return caminho


def pids_do_kubectl_falso(kubectl_falso: Path) -> list[int]:
    return [int(p) for p in kubectl_falso.with_name("pids").read_text().split()]


def credenciais_vistas_pelo_kubectl_falso(kubectl_falso: Path) -> list[str]:
    """Por processo que o kubectl falso viu, as credenciais que havia no ambiente."""
    return kubectl_falso.with_name("ambiente").read_text().splitlines()


def processo_vivo(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


# kubectl e docker falsos de um cluster kind-ci: respondem ao que a sessao do E2E
# pergunta antes e durante os cenarios e anotam cada chamada em ``chamadas``.
# O estado (replicas, ConfigMap do Billing, DLQs) vive em arquivos de ``estado``.
_CLUSTER_FALSO = """\
#!{python}
import json, os, sys
from pathlib import Path
estado = Path(os.environ["FALSO_ESTADO"])
args = sys.argv[1:]
nome = Path(sys.argv[0]).name
with (estado / "chamadas").open("a") as chamadas:
    chamadas.write(nome + " " + " ".join(args) + "\\n")
with (estado / "ambiente").open("a") as ambiente:
    ambiente.write(",".join(c for c in {credenciais!r} if c in os.environ) + "\\n")
juntos = " ".join(args)
if nome == "docker":
    print("127.0.0.1:443")
elif "get nodes" in juntos:
    print("node/pytstop-p4-control-plane")
elif "get configmap" in juntos:
    config = json.loads((estado / "configmap.json").read_text())
    chave = juntos.split(".data.")[1].rstrip("}")
    print(config.get(chave, ""))
elif "get kongclusterplugin" in juntos:
    print("600")
elif "rabbitmqctl" in juntos:
    for fila, total in json.loads((estado / "dlq.json").read_text()).items():
        print(fila + "\\t" + str(total))
elif "get deployment" in juntos:
    deployment = args[args.index("deployment") + 1]
    arquivo = estado / ("replicas-" + deployment)
    print(arquivo.read_text() if arquivo.exists() else "1")
elif "scale" in args:
    deployment = args[args.index("scale") + 1].split("/")[1]
    (estado / ("replicas-" + deployment)).write_text(args[-1].split("=")[1])
elif "get pods" in juntos:
    app = args[args.index("-l") + 1].split("=")[1]
    arquivo = estado / ("replicas-" + app)
    zero = arquivo.exists() and arquivo.read_text() == "0"
    print("" if zero else "pod/x")
sys.exit(0)
"""


def credenciais_vistas_pelo_cluster_falso(estado: Path) -> list[str]:
    """Por chamada ao kubectl ou ao docker falsos, as credenciais no ambiente dela."""
    return (estado / "ambiente").read_text().splitlines()


KIND_CI_NO_BILLING = {
    "ORCAMENTO_VALIDADE_HORAS": "0.02",
    "PAGAMENTO_MAX_RECUSAS": "1",
    "PRAZOS_INTERVALO_SEGUNDOS": "5",
}


def criar_cluster_falso(pasta: Path) -> Path:
    """Escreve ``bin/kubectl`` e ``bin/docker`` falsos e devolve a pasta do estado.

    Estado inicial: overlay ``kind-ci``, as tres DLQs vazias e todo Deployment com
    1 replica. Quem testa troca os arquivos de ``estado`` e le ``chamadas``.
    """
    import json

    estado = pasta / "estado"
    estado.mkdir()
    (estado / "configmap.json").write_text(json.dumps(KIND_CI_NO_BILLING))
    (estado / "dlq.json").write_text(
        json.dumps(
            {
                "billing.comandos.dlq": 0,
                "execucao.comandos.dlq": 0,
                "os.eventos.dlq": 0,
            }
        )
    )
    (estado / "chamadas").write_text("")
    (estado / "ambiente").write_text("")
    bin_ = pasta / "bin"
    bin_.mkdir()
    for nome in ("kubectl", "docker"):
        script = bin_ / nome
        script.write_text(
            _CLUSTER_FALSO.replace("{python}", sys.executable).replace(
                "{credenciais!r}", repr(CREDENCIAIS_DO_AMBIENTE)
            )
        )
        script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return estado


# kubectl falso que grava cada chamada (argv e o stdin, se o comando le `-f -`) em
# `chamadas.jsonl`, ao lado do script. Os Deployments do namespace respondem como
# os do Billing; o resto sai com 0. Serve a provar o que passa por argv e o que so
# passa pelo stdin.
_KUBECTL_GRAVADOR = """\
#!{python}
import json, sys
from pathlib import Path
args = sys.argv[1:]
entrada = ""
if "-f" in args and args[args.index("-f") + 1] == "-":
    entrada = sys.stdin.read()
with Path(__file__).with_name("chamadas.jsonl").open("a") as arquivo:
    arquivo.write(json.dumps({{"argv": args, "stdin": entrada}}) + "\\n")
if "get" in args and "deployment" in args and "name" in args:
    print("deployment.apps/billing-service-api")
    print("deployment.apps/billing-service-consumidor")
"""


def criar_kubectl_gravador(pasta: Path) -> Path:
    """Escreve o kubectl gravador em ``pasta`` e devolve o caminho dele."""
    caminho = pasta / "kubectl"
    caminho.write_text(_KUBECTL_GRAVADOR.format(python=sys.executable))
    caminho.chmod(caminho.stat().st_mode | stat.S_IXUSR)
    return caminho


def chamadas_do_gravador(kubectl: Path) -> list[dict[str, Any]]:
    """As chamadas que o kubectl gravador recebeu, na ordem."""
    arquivo = kubectl.with_name("chamadas.jsonl")
    return [json.loads(linha) for linha in arquivo.read_text().splitlines()]
