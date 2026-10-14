"""Falsos dos testes do codigo auxiliar do E2E: relogio e executor do kubectl."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


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
