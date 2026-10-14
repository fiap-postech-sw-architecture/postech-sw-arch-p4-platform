"""O pytest do E2E de verdade, num subprocesso: o que um teste unitario nao enxerga.

A captura de saida, o ``::add-mask::``, a mascara do relatorio, o SIGTERM e a
guarda do contexto dependem do pytest rodando com o ``e2e/pytest.ini``: aqui
cada um roda como no ``make e2e``, com um ``kubectl`` falso no PATH.
"""

from __future__ import annotations

import json
import os
import signal

# subprocess roda o pytest do proprio repositorio, sem shell.
import subprocess  # nosec B404
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
INI = RAIZ / "e2e" / "pytest.ini"
SENHA = "senha-do-admin-123456"
ID_DO_LINK = "TOK.en-do-link-7"
CHECKOUT = "https://localhost/billing/simulador/checkout/abc?token=tok-do-checkout"

FEATURE = """\
# language: pt
Funcionalidade: Relatorio sem credencial
  Cenário: Um passo que reprova mostrando credenciais
    Quando o passo reprova
"""

TESTE_QUE_REPROVA = f'''\
from pytest_bdd import scenarios, when

from e2e.apoio.segredos import registrar

scenarios("relatorio.feature")


@when("o passo reprova")
def _reprova() -> None:
    registrar("{SENHA}")
    print("stdout com {SENHA} e {CHECKOUT}")
    link = "https://localhost/billing/api/v1/publico/orcamentos/{ID_DO_LINK}"
    assert link.startswith("https://outro-host/"), "falhou com {SENHA}"
'''


def _ambiente(**extra: str) -> dict[str, str]:
    # Sem as variaveis do E2E e sem GITHUB_ACTIONS: no CI ele vale "true" e o
    # ::add-mask:: (que e para o runner ler) entraria na saida que os testes de
    # vazamento examinam. Os testes que querem o comando passam GITHUB_ACTIONS.
    base = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("E2E_", "KUBE_")) and k != "GITHUB_ACTIONS"
    }
    return {**base, "PYTHONPATH": str(RAIZ), **extra}


def _pytest(
    pasta: Path, *argumentos: str, ambiente: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603  # nosec B603
        [
            sys.executable,
            "-m",
            "pytest",
            "-c",
            str(INI),
            "--rootdir",
            str(pasta),
            *argumentos,
        ],
        cwd=pasta,
        env=ambiente or _ambiente(),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        stdin=subprocess.DEVNULL,
    )


def _preparar_cenario_que_reprova(pasta: Path) -> None:
    (pasta / "relatorio.feature").write_text(FEATURE)
    (pasta / "test_relatorio.py").write_text(TESTE_QUE_REPROVA)


def _tudo_que_o_pytest_escreveu(pasta: Path, saida: str) -> str:
    return (
        saida
        + (pasta / "junit.xml").read_text()
        + (pasta / "cucumber.json").read_text()
    )


def test_add_mask_chega_ao_stdout_real_do_processo(tmp_path: Path) -> None:
    (tmp_path / "test_x.py").write_text(
        "from e2e.apoio.segredos import registrar\n\n"
        f'def test_registra():\n    registrar("{SENHA}")\n'
    )

    resultado = _pytest(
        tmp_path, "test_x.py", ambiente=_ambiente(GITHUB_ACTIONS="true")
    )

    assert resultado.returncode == 0, resultado.stdout
    assert f"::add-mask::{SENHA}" in resultado.stdout.splitlines()


def test_add_mask_com_a_captura_por_fd_nao_chega_ao_runner(tmp_path: Path) -> None:
    # Controle: o padrao do pytest esconde a linha, o que prova que o teste acima
    # enxerga o defeito que o --capture=sys do e2e/pytest.ini corrige.
    (tmp_path / "test_x.py").write_text(
        "from e2e.apoio.segredos import registrar\n\n"
        f'def test_registra():\n    registrar("{SENHA}")\n'
    )

    resultado = _pytest(
        tmp_path, "test_x.py", "--capture=fd", ambiente=_ambiente(GITHUB_ACTIONS="true")
    )

    assert f"::add-mask::{SENHA}" not in resultado.stdout


def test_relatorio_da_falha_sai_sem_credencial_no_terminal_no_junit_e_no_cucumber(
    tmp_path: Path,
) -> None:
    _preparar_cenario_que_reprova(tmp_path)

    resultado = _pytest(
        tmp_path,
        "test_relatorio.py",
        "-p",
        "e2e.apoio.plugin",
        "--junitxml=junit.xml",
        "--cucumberjson=cucumber.json",
    )

    escrito = _tudo_que_o_pytest_escreveu(tmp_path, resultado.stdout)
    assert resultado.returncode == 1, resultado.stdout
    assert "falhou com" in escrito
    for segredo in (SENHA, ID_DO_LINK, "tok-do-checkout"):
        assert segredo not in escrito, segredo
    assert json.loads((tmp_path / "cucumber.json").read_text())


def test_controle_sem_o_plugin_a_credencial_vaza_no_relatorio(tmp_path: Path) -> None:
    # Controle do teste acima: sem o hook, o pytest escreve a senha e o link.
    _preparar_cenario_que_reprova(tmp_path)

    resultado = _pytest(
        tmp_path,
        "test_relatorio.py",
        "--junitxml=junit.xml",
        "--cucumberjson=cucumber.json",
    )

    escrito = _tudo_que_o_pytest_escreveu(tmp_path, resultado.stdout)
    assert SENHA in escrito
    assert ID_DO_LINK in escrito


def test_sigterm_roda_o_teardown_da_sessao(tmp_path: Path) -> None:
    pronto, desfeito = tmp_path / "pronto", tmp_path / "desfeito"
    (tmp_path / "test_x.py").write_text(
        "import time\nfrom pathlib import Path\n\nimport pytest\n\n\n"
        '@pytest.fixture(scope="session")\ndef recurso():\n    yield\n'
        f'    Path("{desfeito}").write_text("teardown")\n\n\n'
        "def test_espera(recurso):\n"
        f'    Path("{pronto}").write_text("pronto")\n'
        "    time.sleep(60)\n"
    )
    processo = subprocess.Popen(  # noqa: S603  # nosec B603
        [sys.executable, "-m", "pytest", "-c", str(INI), "--rootdir", str(tmp_path),
         "test_x.py", "-p", "e2e.apoio.plugin"],
        cwd=tmp_path,
        env=_ambiente(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
    )  # fmt: skip
    try:
        limite = time.monotonic() + 30
        while not pronto.exists():
            assert time.monotonic() < limite, "o teste nao chegou a esperar"
            time.sleep(0.1)
        processo.send_signal(signal.SIGTERM)
        processo.wait(timeout=30)
    finally:
        if processo.poll() is None:  # pragma: no cover - so se o SIGTERM falhar
            processo.kill()
            processo.wait()

    assert desfeito.exists(), "o SIGTERM matou o pytest sem rodar o teardown"


def _kubectl_falso(pasta: Path, saida_dos_nos: str) -> Path:
    registro = pasta / "chamadas-do-kubectl"
    script = pasta / "bin" / "kubectl"
    script.parent.mkdir()
    script.write_text(
        "#!/bin/sh\n"
        f'echo "$@" >> "{registro}"\n'
        f'case "$*" in *"get nodes"*) echo "{saida_dos_nos}"; exit 0;; esac\n'
        "exit 1\n"
    )
    script.chmod(0o755)
    return registro


def _sessao_do_e2e(
    pasta: Path, contexto: str, *argumentos: str, **extra: str
) -> subprocess.CompletedProcess[str]:
    ambiente = _ambiente(KUBE_CONTEXT=contexto, **extra)
    ambiente["PATH"] = f"{pasta / 'bin'}{os.pathsep}{ambiente['PATH']}"
    return subprocess.run(  # noqa: S603  # nosec B603
        [sys.executable, "-m", "pytest", "-c", str(INI), str(RAIZ / "e2e"),
         "-m", "borda", "-p", "no:randomly", *argumentos],
        cwd=RAIZ,
        env=ambiente,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        stdin=subprocess.DEVNULL,
    )  # fmt: skip


def test_sessao_com_contexto_que_nao_e_kind_nao_chega_a_chamar_o_kubectl(
    tmp_path: Path,
) -> None:
    registro = _kubectl_falso(tmp_path, "node/ip-10-0-0-5")

    resultado = _sessao_do_e2e(
        tmp_path, "arn:aws:eks:us-east-1:111122223333:cluster/producao"
    )

    assert resultado.returncode != 0
    assert "nao e um kind descartavel" in resultado.stdout
    assert not registro.exists(), "o kubectl foi chamado antes do guarda"


def test_sessao_de_kind_que_nao_e_o_da_borda_para_antes_do_scale(
    tmp_path: Path,
) -> None:
    registro = _kubectl_falso(tmp_path, "node/outro-control-plane")

    resultado = _sessao_do_e2e(tmp_path, "kind-pytstop-p4")

    assert resultado.returncode != 0
    assert "node/pytstop-p4-control-plane" in resultado.stdout
    chamadas = registro.read_text().splitlines()
    assert len(chamadas) == 1
    assert "get nodes" in chamadas[0]
    assert "scale" not in registro.read_text()


def test_guarda_que_recusa_nao_imprime_o_ambiente_no_traceback(tmp_path: Path) -> None:
    _kubectl_falso(tmp_path, "node/ip-10-0-0-5")
    junit = tmp_path / "junit.xml"

    resultado = _sessao_do_e2e(
        tmp_path,
        "arn:aws:eks:us-east-1:111122223333:cluster/producao",
        f"--junitxml={junit}",
        **{"CREDENCIAL_DO_AMBIENTE": "valor-secreto-do-ambiente-9999"},
    )

    assert "nao e um kind descartavel" in resultado.stdout
    escrito = resultado.stdout + junit.read_text()
    assert "valor-secreto-do-ambiente-9999" not in escrito
    assert "CREDENCIAL_DO_AMBIENTE" not in escrito


def test_sessao_com_borda_em_outro_host_nao_chega_a_chamar_o_kubectl(
    tmp_path: Path,
) -> None:
    registro = _kubectl_falso(tmp_path, "node/pytstop-p4-control-plane")

    resultado = _sessao_do_e2e(
        tmp_path, "kind-pytstop-p4", E2E_URL="https://outro-host"
    )

    assert resultado.returncode != 0
    assert "outro-host" in resultado.stdout
    assert "senha do admin" in resultado.stdout
    assert not registro.exists(), "o kubectl foi chamado com a borda em outro host"
