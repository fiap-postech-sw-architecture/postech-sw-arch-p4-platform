"""Ctrl-C, SIGTERM e SIGHUP de verdade: o desfazer do modo real nao pode ser pulado.

O terminal manda o Ctrl-C ao grupo de processos inteiro, e o pytest desmonta as
fixtures em ordem inversa: um segundo sinal no meio do desmonte pularia as fixtures
que faltam. Aqui cada caso roda como no ``make mp-sandbox``, num subprocesso.
"""

from __future__ import annotations

import os
import signal

# subprocess roda o pytest e o Python do proprio repositorio, sem shell.
import subprocess  # nosec B404
import sys
import time
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
INI = RAIZ / "e2e" / "pytest.ini"


def _ambiente(**extra: str) -> dict[str, str]:
    base = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("E2E_", "KUBE_", "MP_")) and k != "GITHUB_ACTIONS"
    }
    return {**base, "PYTHONPATH": str(RAIZ), **extra}


def _esperar_arquivo(arquivo: Path, motivo: str) -> None:
    limite = time.monotonic() + 30
    while not arquivo.exists():
        assert time.monotonic() < limite, motivo
        time.sleep(0.05)


def _pytest(
    pasta: Path, *, plugin: bool = True, **ambiente: str
) -> subprocess.CompletedProcess[str]:
    carregar = ["-p", "e2e.apoio.plugin_sandbox"] if plugin else []
    return subprocess.run(  # noqa: S603  # nosec B603
        [sys.executable, "-m", "pytest", "-c", str(INI), "--rootdir", str(pasta),
         str(pasta / "test_x.py"), *carregar, "-p", "no:randomly",
         "-p", "no:cacheprovider"],
        cwd=pasta,
        env=_ambiente(**ambiente),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        stdin=subprocess.DEVNULL,
    )  # fmt: skip


# --- o segundo Ctrl-C no desmonte -----------------------------------------------


def _suite_com_segundo_ctrl_c(pasta: Path) -> Path:
    registro = pasta / "registro"
    (pasta / "test_x.py").write_text(
        "import os\nimport signal\nfrom pathlib import Path\n\nimport pytest\n\n"
        # Um job em segundo plano herda o SIGINT ignorado, e entao o os.kill abaixo
        # nao levanta nada: o teste mede o pytest, e nao o shell que o lancou.
        "signal.signal(signal.SIGINT, signal.default_int_handler)\n"
        f"REGISTRO = Path({str(registro)!r})\n\n\n"
        "def anotar(texto):\n"
        "    with REGISTRO.open('a') as arquivo:\n"
        "        arquivo.write(texto + '\\n')\n\n\n"
        # O desfazer nasce primeiro, entao morre depois das outras fixtures.
        '@pytest.fixture(scope="session")\ndef desfazer():\n    yield\n'
        "    anotar('desfazer rodou')\n\n\n"
        '@pytest.fixture(scope="session")\ndef outra(desfazer):\n    yield\n'
        # O segundo Ctrl-C chega no teardown de outra fixture.
        "    os.kill(os.getpid(), signal.SIGINT)\n"
        "    anotar('o segundo sinal foi ignorado')\n\n\n"
        "@pytest.mark.mp_sandbox\n"
        "def test_primeiro_ctrl_c(outra):\n    raise KeyboardInterrupt\n"
    )
    return registro


def test_segundo_ctrl_c_no_desmonte_nao_pula_o_desfazer(tmp_path: Path) -> None:
    registro = _suite_com_segundo_ctrl_c(tmp_path)

    resultado = _pytest(tmp_path, E2E_MP_MODO="real")

    assert resultado.returncode == 2, resultado.stdout
    assert registro.read_text().splitlines() == [
        "o segundo sinal foi ignorado",
        "desfazer rodou",
    ]


def test_controle_sem_o_plugin_o_segundo_ctrl_c_pula_o_desfazer(
    tmp_path: Path,
) -> None:
    # Prova que o teste acima mede o que diz: sem o gancho o desfazer nao roda.
    registro = _suite_com_segundo_ctrl_c(tmp_path)

    _pytest(tmp_path, plugin=False)

    assert not registro.exists()


# --- o kubectl do desfazer, com o sinal que o terminal manda ---------------------

KUBECTL_FALSO = """\
#!{python}
import os
import signal
import sys
import time
from pathlib import Path

pasta = Path(os.environ["FALSO_PASTA"])
signal.signal(signal.SIGINT, lambda *_: (pasta / "sigint").write_text("1"))
comando = " ".join(sys.argv[1:])
with (pasta / "chamadas").open("a") as arquivo:
    arquivo.write(comando + "\\n")
if "get deployment -o name" in comando:
    print("deployment.apps/billing-service-api")
elif "rollout status" in comando:
    (pasta / "no-rollout").write_text("1")
    time.sleep(1.5)
"""

DESFAZER = """\
import sys
from e2e.apoio.kube import Kubectl
from e2e.apoio.modo_billing import ModoDoBilling

modo = ModoDoBilling(
    Kubectl("kind-x", binario=sys.argv[1]), lambda: "simulado", avisar=lambda _: None
)
modo.desfazer()
"""


@pytest.mark.parametrize(
    "sinal",
    [
        pytest.param(signal.SIGINT, id="ctrl-c"),
        pytest.param(signal.SIGTERM, id="kill"),
        pytest.param(signal.SIGHUP, id="terminal-fechado"),
    ],
)
def test_sinal_ao_grupo_durante_o_rollout_do_desfazer_nao_o_interrompe(
    sinal: signal.Signals, tmp_path: Path
) -> None:
    falso = tmp_path / "kubectl"
    falso.write_text(KUBECTL_FALSO.format(python=sys.executable))
    falso.chmod(0o755)
    (tmp_path / "desfazer.py").write_text(DESFAZER)
    # start_new_session: o killpg do teste so alcanca o desfazer e os filhos dele.
    processo = subprocess.Popen(  # noqa: S603  # nosec B603
        [sys.executable, str(tmp_path / "desfazer.py"), str(falso)],
        env=_ambiente(FALSO_PASTA=str(tmp_path)),
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _esperar_arquivo(tmp_path / "no-rollout", "o desfazer nao chegou ao rollout")
        os.killpg(processo.pid, sinal)
        _, erros = processo.communicate(timeout=60)
    finally:
        if processo.poll() is None:  # pragma: no cover - so se o teste falhar
            os.killpg(processo.pid, signal.SIGKILL)
            processo.wait()

    assert processo.returncode == 0, erros
    assert not (tmp_path / "sigint").exists(), "o kubectl recebeu o sinal do grupo"
    chamadas = (tmp_path / "chamadas").read_text()
    for passo in ("delete secret", "set env", "rollout restart", "rollout status"):
        assert passo in chamadas, passo
