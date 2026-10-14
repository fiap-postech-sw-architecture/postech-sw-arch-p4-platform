"""Falsos dos testes do codigo auxiliar do E2E: relogio e executor do kubectl."""

from __future__ import annotations

import os
import stat
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


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
# processo anota o proprio pid em pids, ao lado do script.
_KUBECTL_FALSO = """\
#!{python}
import os, socket, sys, time
from pathlib import Path
args = sys.argv[1:]
with Path(__file__).with_name("pids").open("a") as pids:
    pids.write(f"{{os.getpid()}}\\n")
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
    caminho.write_text(_KUBECTL_FALSO.format(python=sys.executable))
    caminho.chmod(caminho.stat().st_mode | stat.S_IXUSR)
    return caminho


def pids_do_kubectl_falso(kubectl_falso: Path) -> list[int]:
    return [int(p) for p in kubectl_falso.with_name("pids").read_text().split()]


def processo_vivo(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True
