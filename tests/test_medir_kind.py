"""scripts/medir-kind.sh com docker, kubectl e date falsos.

Os falsos devolvem amostras conhecidas: o teste confere as contas do resumo
(duracao de cada etapa e do total, memory.peak, maior working set amostrado,
memoria do host e maior uso de cada pod, sem pod de Job terminado e sem os
pods do eco do smoke), o resumo sem etapa, a falta de diretorio para a
medicao e quando o amostrador para: no resumo e, fora do GitHub Actions,
quando termina o shell que marcou a primeira etapa.
"""

from __future__ import annotations

import contextlib
import os
import re
import signal

# subprocess so roda o script do repositorio (e um bash para fazer de pai),
# sem shell.
import subprocess  # nosec B404
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "medir-kind.sh"
MIB = 1024 * 1024

# docker falso: memory.current e inactive_file do no a cada amostra (working
# set de 2048, 3072 e, dali em diante, 1536 MiB), o memory.peak e o host.
DOCKER_FALSO = r"""
import os
import sys
from pathlib import Path

MIB = 1024 * 1024
AMOSTRAS = [(3072, 1024), (4096, 1024), (2048, 512)]
args = sys.argv[1:]
no = ["exec", "pytstop-p4-control-plane"]
if args == ["info", "--format", "{{.MemTotal}}"]:
    print(15989 * MIB)
elif args == [*no, "cat", "/sys/fs/cgroup/memory.peak"]:
    print(3559 * MIB)
elif args[:3] == [*no, "sh"]:
    contador = Path(os.environ["FALSOS"]) / "docker"
    n = int(contador.read_text()) + 1 if contador.exists() else 1
    contador.write_text(str(n))
    atual, inativo = AMOSTRAS[min(n, len(AMOSTRAS)) - 1]
    print(atual * MIB)
    print(f"inactive_file {inativo * MIB}")
else:
    sys.exit(f"chamada inesperada: {args}")
"""

# kubectl falso: o kubectl top de cada amostra. Sem o seletor que tira o eco
# do smoke, devolve tambem o pod do eco, como o kubectl de verdade.
KUBECTL_FALSO = r"""
import os
import sys
from pathlib import Path

AMOSTRAS = [
    ["kong-abc 5m 100Mi", "rabbitmq-usuarios-xyz 0m 0Mi"],
    ["kong-abc 7m 293Mi", "rabbitmq-0 9m 213Mi"],
    ["kong-abc 6m 150Mi", "rabbitmq-0 8m 100Mi"],
]
args = sys.argv[1:]
topo = ["--context", "kind-pytstop-p4", "top", "pod", "-A", "--no-headers"]
if args[: len(topo)] != topo:
    sys.exit(f"chamada inesperada: {args}")
contador = Path(os.environ["FALSOS"]) / "kubectl"
n = int(contador.read_text()) + 1 if contador.exists() else 1
contador.write_text(str(n))
linhas = AMOSTRAS[min(n, len(AMOSTRAS)) - 1]
if args[len(topo) :] != ["-l", "app.kubernetes.io/part-of!=pytstop-smoke"]:
    linhas = [*linhas, "os-service-api-123 1m 28Mi"]
for linha in linhas:
    print(f"pytstop-plataforma {linha}")
"""

DATE_FALSO = r"""
import os
import sys

if sys.argv[1:] != ["+%s"]:
    sys.exit(f"chamada inesperada: {sys.argv[1:]}")
print(os.environ["AGORA"])
"""

RESUMO = """### Deploy on kind: minutes and memory

| Stage | Duration |
|---|---|
| kind-up | 0 min 39 s |
| deploy | 0 min 51 s |
| smoke | 1 min 40 s |
| total | 3 min 10 s |

| Memory of the kind node (pytstop-p4-control-plane) | MiB |
|---|---|
| cgroup peak (memory.peak, file cache included) | 3559 |
| highest sampled working set (N samples, every 0.05 s) | 3072 |
| memory of the Docker host | 15989 |

| Pod (without the smoke echo servers) | Highest sampled memory (MiB, kubectl top) |
|---|---|
| pytstop-plataforma/kong-abc | 293 |
| pytstop-plataforma/rabbitmq-0 | 213 |
"""


def espera(condicao: Callable[[], bool], segundos: float = 10) -> None:
    limite = time.monotonic() + segundos
    while not condicao():
        assert time.monotonic() < limite, "condicao nao chegou a tempo"
        time.sleep(0.02)


def vivo(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def linhas(arquivo: Path) -> int:
    return len(arquivo.read_text().splitlines()) if arquivo.exists() else 0


class Medicao:
    """Ambiente com os falsos no PATH e o diretorio da medicao no tmp_path."""

    def __init__(self, tmp_path: Path) -> None:
        self.dir = tmp_path / "medicao"
        self.summary = tmp_path / "summary.md"
        binarios = tmp_path / "bin"
        binarios.mkdir()
        for nome, codigo in (
            ("docker", DOCKER_FALSO),
            ("kubectl", KUBECTL_FALSO),
            ("date", DATE_FALSO),
        ):
            binario = binarios / nome
            binario.write_text(f"#!{sys.executable}\n{codigo}", encoding="utf-8")
            binario.chmod(0o755)
        fora = {"GITHUB_ACTIONS", "GITHUB_STEP_SUMMARY", "RUNNER_TEMP", "TMPDIR"}
        self.env = {
            chave: valor for chave, valor in os.environ.items() if chave not in fora
        }
        for chave in ("MEDICAO", "KUBE_CONTEXT", "CLUSTER", "INTERVALO"):
            self.env.pop(chave, None)
        self.env |= {
            "PATH": f"{binarios}{os.pathsep}{self.env['PATH']}",
            "FALSOS": str(tmp_path),
            "MEDICAO": str(self.dir),
            "INTERVALO": "0.05",
            "GITHUB_STEP_SUMMARY": str(self.summary),
        }
        self.amostradores: list[int] = []

    def roda(
        self, *args: str, pai: bool = False, **ambiente: str
    ) -> subprocess.CompletedProcess[str]:
        """Roda o script; com ``pai``, por um bash que termina logo depois."""
        comando = [str(SCRIPT), *args]
        if pai:
            comando = ["bash", "-c", '"$0" "$@"; true', *comando]
        processo = subprocess.run(  # noqa: S603  # nosec B603
            comando,
            env=self.env | ambiente,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        pid = self.dir / "amostrador"
        if pid.exists():
            self.amostradores.append(int(pid.read_text()))
        return processo

    def amostras(self) -> int:
        return linhas(self.dir / "no")


@pytest.fixture
def medicao(tmp_path: Path) -> Iterator[Medicao]:
    medicao = Medicao(tmp_path)
    yield medicao
    # Teste que falhou no meio nao deixa amostrador rodando.
    for pid in medicao.amostradores:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGTERM)


def test_resumo_traz_duracoes_memoria_do_no_e_maior_uso_por_pod(
    medicao: Medicao,
) -> None:
    assert medicao.roda("etapa", "kind-up", AGORA="1000").returncode == 0
    (amostrador,) = medicao.amostradores
    espera(lambda: medicao.amostras() >= 3)
    assert medicao.roda("etapa", "deploy", AGORA="1039").returncode == 0
    assert medicao.roda("etapa", "smoke", AGORA="1090").returncode == 0

    resumo = medicao.roda("resumo", AGORA="1190")

    assert resumo.returncode == 0, resumo.stderr
    assert re.sub(r"\(\d+ samples", "(N samples", resumo.stdout) == RESUMO
    assert medicao.summary.read_text() == resumo.stdout
    espera(lambda: not vivo(amostrador))
    assert not (medicao.dir / "etapas").exists()


def test_resumo_sem_etapa_avisa_e_nao_escreve_summary(medicao: Medicao) -> None:
    resumo = medicao.roda("resumo")

    assert resumo.returncode == 0
    assert resumo.stdout == f"no stage recorded in {medicao.dir}\n"
    assert not medicao.summary.exists()


def test_fora_do_actions_o_amostrador_para_com_o_shell_que_o_ligou(
    medicao: Medicao,
) -> None:
    medicao.roda("etapa", "kind-up", pai=True, AGORA="1000")
    (amostrador,) = medicao.amostradores

    espera(lambda: not vivo(amostrador))
    # Parou pelo dono, nao pelo resumo: a marca da etapa continua la.
    assert (medicao.dir / "etapas").exists()


def test_no_actions_o_amostrador_segue_entre_os_passos_ate_o_resumo(
    medicao: Medicao,
) -> None:
    medicao.roda("etapa", "kind-up", pai=True, AGORA="1000", GITHUB_ACTIONS="true")
    (amostrador,) = medicao.amostradores
    espera(lambda: medicao.amostras() >= 3)
    depois_do_pai = medicao.amostras()

    espera(lambda: medicao.amostras() >= depois_do_pai + 3)
    assert vivo(amostrador)
    medicao.roda("resumo", AGORA="1060", GITHUB_ACTIONS="true")
    espera(lambda: not vivo(amostrador))


def test_sem_diretorio_para_a_medicao_pede_mktemp(medicao: Medicao) -> None:
    del medicao.env["MEDICAO"]

    processo = medicao.roda("etapa", "kind-up", AGORA="1000")

    assert processo.returncode == 2
    assert "export MEDICAO=$(mktemp -d)" in processo.stderr
    assert medicao.amostradores == []


def test_o_amostrador_para_quando_as_marcas_somem(medicao: Medicao) -> None:
    # No Actions, sem dono: so a marca segura o amostrador.
    medicao.roda("etapa", "kind-up", AGORA="1000", GITHUB_ACTIONS="true")
    (amostrador,) = medicao.amostradores
    espera(lambda: medicao.amostras() >= 1)

    (medicao.dir / "etapas").unlink()

    espera(lambda: not vivo(amostrador))
    assert not (medicao.dir / "amostrador").exists()
