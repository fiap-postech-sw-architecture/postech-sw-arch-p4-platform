"""scripts/esperar-pod.sh com kubectl e sleep falsos.

O kubectl falso e o apiserver diante de um pod que o StatefulSet recria depois
do delete: nas primeiras chamadas que citam o pod (get ou wait) ele responde
NotFound, e depois o pod existe e esta Ready. O teste confere o que o fim do
make smoke precisa: o pod ausente e esperado ate existir e ficar Ready (o wait
logo depois do delete saia com NotFound e o deploy-kind reprovava), as duas
esperas dividem os mesmos segundos, a consulta tem pausa, o erro do cluster
nao e esperado como se fosse pod ausente, e o pod que nao volta ou nao fica
Ready no prazo para o script com status 1 e o erro do kubectl.
"""

from __future__ import annotations

import json
import os
import re
import shutil

# subprocess so roda o script do repositorio, sem shell.
import subprocess  # nosec B404
import sys
import time
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
SCRIPT = RAIZ / "scripts" / "esperar-pod.sh"
SMOKE = RAIZ / "scripts" / "smoke.sh"
SLEEP = shutil.which("sleep") or "/bin/sleep"
BASE = ["--context", "kind-pytstop-p4", "-n", "pytstop-plataforma"]
CONSULTA = ["get", "pod", "rabbitmq-0", "--ignore-not-found", "-o", "name"]

# kubectl falso: o pod esta ausente nas primeiras KUBECTL_FALSO_AUSENTE chamadas
# que o citam e depois existe e esta Ready. KUBECTL_FALSO_NAO_PRONTO=1 deixa o
# pod existindo sem ficar Ready, KUBECTL_FALSO_DEMORA=<s> atrasa a resposta do
# get e KUBECTL_FALSO_FALHA=1 faz o get falhar como o cluster fora do ar. Como
# o de verdade, o get de pod ausente sai com NotFound sem o --ignore-not-found
# e sai 0, sem nome, com ele.
KUBECTL_FALSO = r"""
import json
import os
import sys
import time
from pathlib import Path

args = sys.argv[1:]
falsos = Path(os.environ["FALSOS"])
with (falsos / "kubectl.jsonl").open("a") as log:
    log.write(json.dumps(args) + "\n")
verbo = args[4:]
if verbo[:3] == ["get", "pod", "rabbitmq-0"] and verbo[3:] in (
    ["--ignore-not-found", "-o", "name"],
    ["-o", "name"],
):
    if os.environ.get("KUBECTL_FALSO_FALHA"):
        sys.exit("The connection to the server 127.0.0.1:6443 was refused")
    time.sleep(float(os.environ.get("KUBECTL_FALSO_DEMORA", "0")))
elif len(verbo) == 4 and verbo[:3] == [
    "wait",
    "--for=condition=Ready",
    "pod/rabbitmq-0",
] and verbo[3].startswith("--timeout="):
    pass
else:
    sys.exit(f"chamada inesperada: {args}")
contador = falsos / "chamadas-ao-pod"
n = int(contador.read_text()) + 1 if contador.exists() else 1
contador.write_text(str(n))
ausente = n <= int(os.environ.get("KUBECTL_FALSO_AUSENTE", "0"))
if verbo[0] == "get":
    if not ausente:
        print("pod/rabbitmq-0")
    elif "--ignore-not-found" not in verbo:
        sys.exit('Error from server (NotFound): pods "rabbitmq-0" not found')
elif ausente:
    sys.exit('Error from server (NotFound): pods "rabbitmq-0" not found')
elif os.environ.get("KUBECTL_FALSO_NAO_PRONTO"):
    sys.exit("error: timed out waiting for the condition on pods/rabbitmq-0")
else:
    print("pod/rabbitmq-0 condition met")
"""

# sleep falso: registra o argumento e dorme de verdade (SLEEP_REAL).
SLEEP_FALSO = r"""
import json
import os
import sys
from pathlib import Path

with (Path(os.environ["FALSOS"]) / "sleep.jsonl").open("a") as log:
    log.write(json.dumps(sys.argv[1:]) + "\n")
os.execv(os.environ["SLEEP_REAL"], ["sleep", *sys.argv[1:]])
"""


class Espera:
    """Falsos no PATH e os registros de cada chamada no tmp_path."""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp = tmp_path
        binarios = tmp_path / "bin"
        binarios.mkdir()
        for nome, codigo in (("kubectl", KUBECTL_FALSO), ("sleep", SLEEP_FALSO)):
            binario = binarios / nome
            binario.write_text(f"#!{sys.executable}\n{codigo}", encoding="utf-8")
            binario.chmod(0o755)
        self.env = {
            chave: valor
            for chave, valor in os.environ.items()
            if chave not in {"KUBE_CONTEXT", "NAMESPACE"}
        } | {
            "PATH": f"{binarios}{os.pathsep}{os.environ['PATH']}",
            "FALSOS": str(tmp_path),
            "SLEEP_REAL": SLEEP,
        }

    def roda(self, *args: str, **ambiente: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603  # nosec B603
            [str(SCRIPT), *args],
            env=self.env | ambiente,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )

    def chamadas(self, falso: str) -> list[list[str]]:
        arquivo = self.tmp / f"{falso}.jsonl"
        if not arquivo.exists():
            return []
        return [json.loads(linha) for linha in arquivo.read_text().splitlines()]


def segundos_do_wait(chamada: list[str]) -> int:
    """Os segundos do --timeout=<n>s com que o script chamou o kubectl wait."""
    achado = re.fullmatch(r"--timeout=(-?\d+)s", chamada[-1])
    assert achado, chamada
    return int(achado[1])


@pytest.fixture
def espera(tmp_path: Path) -> Espera:
    return Espera(tmp_path)


def test_pod_ausente_e_esperado_ate_existir_e_ficar_pronto(espera: Espera) -> None:
    # O flake do deploy-kind: o wait logo depois do delete achava o pod ainda nao
    # recriado e saia com NotFound.
    processo = espera.roda("rabbitmq-0", "30", KUBECTL_FALSO_AUSENTE="2")

    assert processo.returncode == 0, processo.stderr
    assert processo.stdout == ""
    *consultas, pronto = espera.chamadas("kubectl")
    assert consultas == [[*BASE, *CONSULTA]] * 3
    assert pronto[:-1] == [*BASE, "wait", "--for=condition=Ready", "pod/rabbitmq-0"]
    # O wait leva o que sobrou dos 30 s (passaram 2 s e pouco), nao os 30 inteiros.
    assert 20 <= segundos_do_wait(pronto) <= 28
    # Pausa entre as consultas: sem ela o laco consultaria o apiserver sem parar.
    assert espera.chamadas("sleep") == [["1"], ["1"]]


def test_pod_que_ja_existe_vai_direto_ao_wait(espera: Espera) -> None:
    processo = espera.roda("rabbitmq-0", "30")

    assert processo.returncode == 0, processo.stderr
    verbos = [chamada[4] for chamada in espera.chamadas("kubectl")]
    assert verbos == ["get", "wait"]
    assert espera.chamadas("sleep") == []


def test_pod_que_nao_volta_no_prazo_falha_sem_chamar_o_wait(espera: Espera) -> None:
    inicio = time.monotonic()

    processo = espera.roda("rabbitmq-0", "3", KUBECTL_FALSO_AUSENTE="999")

    # O SECONDS do bash conta segundos inteiros: 3 s de espera podem ser 2 s e pouco.
    assert time.monotonic() - inicio >= 2
    assert processo.returncode == 1
    assert processo.stderr == "pod rabbitmq-0 not recreated after 3s\n"
    verbos = [chamada[4] for chamada in espera.chamadas("kubectl")]
    assert len(verbos) >= 2
    assert set(verbos) == {"get"}
    pausas = espera.chamadas("sleep")
    assert pausas
    assert all(pausa == ["1"] for pausa in pausas)


def test_pod_que_nao_fica_pronto_falha_com_status_1_e_o_erro_do_kubectl(
    espera: Espera,
) -> None:
    processo = espera.roda("rabbitmq-0", "30", KUBECTL_FALSO_NAO_PRONTO="1")

    assert processo.returncode == 1
    assert processo.stderr == (
        "error: timed out waiting for the condition on pods/rabbitmq-0\n"
    )
    assert [chamada[4] for chamada in espera.chamadas("kubectl")] == ["get", "wait"]


def test_erro_do_cluster_na_consulta_para_na_hora_sem_esperar_o_prazo(
    espera: Espera,
) -> None:
    processo = espera.roda("rabbitmq-0", "30", KUBECTL_FALSO_FALHA="1")

    assert processo.returncode == 1
    assert (
        processo.stderr == "The connection to the server 127.0.0.1:6443 was refused\n"
    )
    assert espera.chamadas("kubectl") == [[*BASE, *CONSULTA]]
    assert espera.chamadas("sleep") == []


def test_prazo_gasto_na_consulta_nao_vira_timeout_negativo(espera: Espera) -> None:
    # Com 1 s de prazo e a consulta levando 3 s, nao sobra nada: o kubectl wait
    # entende zero como "confere uma vez" e negativo como "espera uma semana".
    processo = espera.roda("rabbitmq-0", "1", KUBECTL_FALSO_DEMORA="3")

    assert processo.returncode == 0, processo.stderr
    *_, pronto = espera.chamadas("kubectl")
    assert pronto[-1] == "--timeout=0s"


def test_contexto_e_namespace_do_ambiente_chegam_a_toda_chamada(
    espera: Espera,
) -> None:
    processo = espera.roda(
        "rabbitmq-0",
        "30",
        KUBECTL_FALSO_AUSENTE="1",
        KUBE_CONTEXT="k3s",
        NAMESPACE="outro",
    )

    assert processo.returncode == 0, processo.stderr
    chamadas = espera.chamadas("kubectl")
    assert len(chamadas) == 3
    assert all(
        chamada[:4] == ["--context", "k3s", "-n", "outro"] for chamada in chamadas
    )


@pytest.mark.parametrize("args", [[], ["rabbitmq-0"]])
def test_sem_o_pod_ou_sem_o_prazo_diz_o_uso_e_nao_chama_o_kubectl(
    espera: Espera, args: list[str]
) -> None:
    processo = espera.roda(*args)

    assert processo.returncode == 1
    assert "usage: esperar-pod.sh <pod> <seconds>" in processo.stderr
    assert espera.chamadas("kubectl") == []


def test_o_fim_do_smoke_espera_o_broker_por_esperar_pod_sh() -> None:
    # O wait direto no pod recem apagado e o que reprovou o deploy-kind.
    smoke = SMOKE.read_text(encoding="utf-8")

    assert "scripts/esperar-pod.sh rabbitmq-0 300\n" in smoke
    assert "wait --for=condition=Ready pod/rabbitmq-0" not in smoke
