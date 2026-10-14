"""O sandbox do Mercado Pago fica fora do make e2e, do make demo e do CI.

O CI nao tem token e o sandbox mexe no modo do Billing, entao nada que o CI roda pode
selecionar um cenario ``@mp_sandbox``. Aqui isso e provado de tres lados: o que o
Makefile executa, o que o pytest seleciona de verdade e o que os workflows citam.
Tambem se prova que o pytest cru, sem ``E2E_MP_MODO``, pula o sandbox sem tocar no
cluster, e que o preflight do sandbox para antes de qualquer mudanca no cluster e
sem repetir a credencial.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess  # nosec B404
import sys
from pathlib import Path

import pytest

from e2e_apoio.falsos import ASSINATURA, CHAVE_DO_MP, criar_cluster_falso

RAIZ = Path(__file__).resolve().parents[2]
INI = RAIZ / "e2e" / "pytest.ini"
FEATURE = RAIZ / "e2e" / "features" / "mercadopago_sandbox.feature"
# O rootdir do pytest e a pasta do pytest.ini (e2e/): os ids vem sem o prefixo.
SANDBOX = "test_mp_sandbox.py"
ARQUIVO_DO_SANDBOX = "e2e/test_mp_sandbox.py"
CENARIOS_DO_SANDBOX = 3


def _ambiente(**extra: str) -> dict[str, str]:
    base = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("E2E_", "KUBE_", "MP_")) and k != "GITHUB_ACTIONS"
    }
    return {**base, "PYTHONPATH": str(RAIZ), **extra}


def _pytest(
    *argumentos: str, ambiente: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603  # nosec B603
        [sys.executable, "-m", "pytest", "-c", str(INI), *argumentos],
        cwd=RAIZ,
        env=ambiente or _ambiente(),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        stdin=subprocess.DEVNULL,
    )


def _selecionados(*filtro: str) -> list[str]:
    resultado = _pytest("e2e", "--collect-only", "-q", "-p", "no:randomly", *filtro)
    assert resultado.returncode == 0, resultado.stdout + resultado.stderr
    return [linha for linha in resultado.stdout.splitlines() if "::" in linha]


def _make(alvo: str, *variaveis: str) -> str:
    resultado = subprocess.run(  # noqa: S603  # nosec B603
        [shutil.which("make") or "make", "-n", "-C", str(RAIZ), alvo, *variaveis],
        env=_ambiente(),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        stdin=subprocess.DEVNULL,
    )
    assert resultado.returncode == 0, resultado.stdout + resultado.stderr
    return resultado.stdout


# --- o que o Makefile executa --------------------------------------------------------


def test_make_e2e_pede_tudo_menos_o_sandbox() -> None:
    comandos = _make("e2e")

    assert '-m "not mp_sandbox"' in comandos
    assert "E2E_MP_MODO" not in comandos
    assert "mp-sandbox" not in comandos


def test_make_demo_roda_so_o_que_tem_a_tag_demo() -> None:
    comandos = _make("demo")

    assert "-m demo" in comandos
    assert "mp_sandbox" not in comandos
    assert "E2E_MP_MODO" not in comandos


@pytest.mark.parametrize(
    ("alvo", "modo", "pasta"),
    [
        pytest.param("mp-sandbox", "real", "reports/mp-sandbox", id="real"),
        pytest.param(
            "mp-sandbox-ensaio", "ensaio", "reports/mp-sandbox-ensaio", id="ensaio"
        ),
    ],
)
def test_make_do_sandbox_roda_so_o_sandbox_no_modo_e_na_pasta_dele(
    alvo: str, modo: str, pasta: str
) -> None:
    comandos = _make(alvo)

    assert f"E2E_MP_MODO={modo}" in comandos
    assert "-m mp_sandbox -s -q -x " in comandos, "para no primeiro cenario que reprova"
    assert f"E2E_RELATORIOS={pasta} " in comandos
    assert f"--junitxml={pasta}/junit.xml" in comandos
    assert f"python -m e2e.varredura {pasta}" in comandos
    assert f"python -m e2e.resumo {pasta} relatorio-e2e.md" in comandos


def test_make_do_sandbox_recusa_contexto_que_nao_e_kind_e_nao_tem_escape() -> None:
    for alvo in ("mp-sandbox", "mp-sandbox-ensaio"):
        resultado = subprocess.run(  # noqa: S603  # nosec B603
            [
                shutil.which("make") or "make",
                "-C",
                str(RAIZ),
                alvo,
                "KUBE_CONTEXT=k3s-da-vm",
            ],
            env=_ambiente(E2E_CONTEXTO_NAO_DESCARTAVEL="k3s-da-vm"),
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
            stdin=subprocess.DEVNULL,
        )

        assert resultado.returncode == 2, resultado.stdout
        assert "nao e um kind" in resultado.stderr
        assert "o escape do E2E nao vale aqui" in resultado.stderr
        assert "uv run" not in resultado.stdout.replace("echo", "")


def test_o_real_gira_so_a_pasta_com_resumo_e_o_ensaio_nao_toca_nela() -> None:
    real = _make("mp-sandbox")
    ensaio = _make("mp-sandbox-ensaio")

    assert "if [ -f reports/mp-sandbox/resumo.md ]; then" in real
    assert 'mv reports/mp-sandbox "reports/mp-sandbox.$(date +%Y%m%d-%H%M%S)"' in real
    assert "reports/mp-sandbox.anterior" not in real, "nada anterior e apagado"
    assert "rm -rf reports/mp-sandbox-ensaio" in ensaio
    assert "rm -rf reports/mp-sandbox " not in ensaio
    assert "mv reports/mp-sandbox" not in ensaio


@pytest.mark.parametrize(
    ("alvo", "modo", "mexe_nos_relatorios"),
    [
        pytest.param(
            "mp-sandbox", "real", "if [ -f reports/mp-sandbox/resumo.md ]", id="real"
        ),
        pytest.param(
            "mp-sandbox-ensaio",
            "ensaio",
            "rm -rf reports/mp-sandbox-ensaio",
            id="ensaio",
        ),
    ],
)
def test_a_conferencia_vem_antes_de_tocar_nos_relatorios_e_do_pytest(
    alvo: str, modo: str, mexe_nos_relatorios: str
) -> None:
    comandos = _make(alvo)

    conferencia = comandos.index(f"python -m e2e.conferir_sandbox {modo}")
    assert conferencia < comandos.index(mexe_nos_relatorios)
    assert conferencia < comandos.index("pytest -c e2e/pytest.ini")


def _make_com(*argumentos: str, **ambiente: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603  # nosec B603
        [shutil.which("make") or "make", "-C", str(RAIZ), *argumentos],
        env=_ambiente(**ambiente),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        stdin=subprocess.DEVNULL,
    )


@pytest.mark.parametrize(
    "variavel",
    [
        pytest.param("MP_ACCESS_TOKEN", id="token"),
        pytest.param("MP_WEBHOOK_SECRET", id="assinatura"),
    ],
)
@pytest.mark.parametrize(
    "alvo",
    [
        pytest.param("mp-sandbox", id="real"),
        pytest.param("mp-sandbox-ensaio", id="ensaio"),
    ],
)
def test_credencial_na_linha_do_make_e_recusada_sem_repetir_o_valor(
    alvo: str, variavel: str
) -> None:
    # Na linha do make o valor ficaria no argv (ps) e no historico do shell.
    resultado = _make_com("-n", alvo, f"{variavel}={CHAVE_DO_MP}")

    saida = resultado.stdout + resultado.stderr
    assert resultado.returncode == 2, saida
    assert "nao vao na linha do make" in saida
    assert 'MP_ACCESS_TOKEN="$MP_ACCESS_TOKEN"' in saida, (
        "a forma certa vem na mensagem"
    )
    assert CHAVE_DO_MP not in saida
    assert CHAVE_DO_MP[:12] not in saida
    assert "uv run" not in saida, "nada foi executado"


def test_credencial_so_no_ambiente_o_make_aceita_e_nao_a_repete() -> None:
    for alvo in ("mp-sandbox", "mp-sandbox-ensaio"):
        resultado = _make_com(
            "-n",
            alvo,
            MP_ACCESS_TOKEN=CHAVE_DO_MP,
            MP_WEBHOOK_SECRET=ASSINATURA,
        )

        assert resultado.returncode == 0, resultado.stdout + resultado.stderr
        assert CHAVE_DO_MP not in resultado.stdout
        assert ASSINATURA not in resultado.stdout


def test_a_recusa_da_credencial_vale_so_para_os_alvos_do_sandbox() -> None:
    resultado = _make_com("-n", "e2e", f"MP_ACCESS_TOKEN={CHAVE_DO_MP}")

    assert resultado.returncode == 0, resultado.stdout + resultado.stderr


def test_nenhum_workflow_cita_o_sandbox() -> None:
    for workflow in sorted((RAIZ / ".github" / "workflows").glob("*.yml")):
        texto = workflow.read_text()
        assert not re.search(r"mp[-_]sandbox|E2E_MP_|MP_ACCESS_TOKEN", texto), (
            workflow.name
        )


# --- o que o pytest seleciona de verdade ---------------------------------------------


def test_sem_o_sandbox_o_pytest_seleciona_so_os_cenarios_da_saga() -> None:
    todos = _selecionados()
    sem_sandbox = _selecionados("-m", "not mp_sandbox")

    assert len([t for t in todos if SANDBOX in t]) == CENARIOS_DO_SANDBOX
    assert not [t for t in sem_sandbox if SANDBOX in t]
    assert len(sem_sandbox) == len(todos) - CENARIOS_DO_SANDBOX
    assert len(sem_sandbox) == 13, "os 13 cenarios do E2E da saga"


def test_so_com_o_marker_o_pytest_seleciona_so_o_sandbox() -> None:
    so_sandbox = _selecionados("-m", "mp_sandbox")

    assert len(so_sandbox) == CENARIOS_DO_SANDBOX
    assert all(SANDBOX in t for t in so_sandbox)


def test_o_make_demo_nao_seleciona_cenario_do_sandbox() -> None:
    demo = _selecionados("-m", "demo")

    assert demo
    assert not [t for t in demo if SANDBOX in t]


def test_todo_passo_do_feature_do_sandbox_tem_definicao() -> None:
    resultado = _pytest("--generate-missing", "--feature", str(FEATURE), "e2e")

    assert "is not defined" not in resultado.stdout, resultado.stdout
    assert "is not bound" not in resultado.stdout, resultado.stdout


# --- o pytest cru nao toca no cluster ------------------------------------------------


def _kubectl_que_nao_pode_ser_chamado(pasta: Path) -> Path:
    registro = pasta / "chamadas"
    script = pasta / "bin" / "kubectl"
    script.parent.mkdir()
    script.write_text(f'#!/bin/sh\necho "$@" >> "{registro}"\nexit 1\n')
    script.chmod(0o755)
    return registro


def test_pytest_cru_sem_modo_pula_o_sandbox_sem_chamar_o_kubectl(
    tmp_path: Path,
) -> None:
    registro = _kubectl_que_nao_pode_ser_chamado(tmp_path)

    resultado = _pytest(
        "e2e",
        "-m",
        "mp_sandbox",
        "-rs",
        "-p",
        "no:randomly",
        ambiente=_ambiente(PATH=f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}"),
    )

    assert resultado.returncode == 0, resultado.stdout
    assert f"{CENARIOS_DO_SANDBOX} skipped" in resultado.stdout
    assert "sandbox do Mercado Pago: use make mp-sandbox" in resultado.stdout
    assert not registro.exists(), "o kubectl foi chamado por um cenario pulado"


def test_modo_esquecido_no_shell_faz_a_saga_falhar_em_vez_de_pular_tudo(
    tmp_path: Path,
) -> None:
    # make e2e e make demo com E2E_MP_MODO exportado por engano: sem isto, 13 skipped e
    # saida 0, um verde falso.
    registro = _kubectl_que_nao_pode_ser_chamado(tmp_path)

    resultado = _pytest(
        "e2e",
        "-m",
        "not mp_sandbox",
        "-rs",
        "-p",
        "no:randomly",
        ambiente=_ambiente(
            E2E_MP_MODO="ensaio",
            PATH=f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}",
        ),
    )

    saida = resultado.stdout + resultado.stderr
    assert resultado.returncode == 2, saida
    assert "E2E_MP_MODO=ensaio esta no seu shell" in saida
    assert "unset E2E_MP_MODO" in saida
    assert " passed" not in saida
    assert " skipped" not in saida
    assert not registro.exists()


# --- o preflight do sandbox, com o pytest de verdade ---------------------------------


def _sessao_do_sandbox(
    tmp_path: Path, **ambiente: str
) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    estado = criar_cluster_falso(tmp_path)
    junit = tmp_path / "junit.xml"
    resultado = _pytest(
        ARQUIVO_DO_SANDBOX,
        "-m",
        "mp_sandbox",
        "-p",
        "no:randomly",
        f"--junitxml={junit}",
        ambiente=_ambiente(
            KUBE_CONTEXT="kind-pytstop-p4",
            FALSO_ESTADO=str(estado),
            PATH=f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}",
            **ambiente,
        ),
    )
    return resultado, estado / "chamadas", junit


def test_modo_invalido_reprova_antes_de_qualquer_mudanca_no_cluster(
    tmp_path: Path,
) -> None:
    resultado, chamadas, _ = _sessao_do_sandbox(tmp_path, E2E_MP_MODO="tanto-faz")

    assert resultado.returncode != 0
    assert (
        "use real (make mp-sandbox) ou ensaio (make mp-sandbox-ensaio)"
        in resultado.stdout
    )
    texto = chamadas.read_text()
    assert " scale " not in texto
    assert "set env" not in texto
    assert "apply" not in texto


def test_token_com_quebra_de_linha_reprova_antes_do_cluster_e_nao_vaza(
    tmp_path: Path,
) -> None:
    resultado, chamadas, junit = _sessao_do_sandbox(
        tmp_path,
        E2E_MP_MODO="real",
        MP_ACCESS_TOKEN=CHAVE_DO_MP + "\n",
        CREDENCIAL_DE_OUTRA_COISA="valor-secreto-do-ambiente-9999",
        MP_WEBHOOK_SECRET=ASSINATURA,
    )

    assert resultado.returncode == 2
    saida = resultado.stdout + resultado.stderr
    assert "MP_ACCESS_TOKEN tem espaço ou quebra de linha" in saida
    assert "Traceback" not in saida, "o preflight do sandbox nao mostra traceback"
    escrito = saida + junit.read_text()
    assert CHAVE_DO_MP not in escrito
    assert CHAVE_DO_MP[:12] not in escrito
    assert "assinatura-do-webhook" not in escrito
    # O ambiente inteiro nunca e argumento de quem pode falhar: o pytest o mostraria.
    assert "valor-secreto-do-ambiente-9999" not in escrito
    assert "CREDENCIAL_DE_OUTRA_COISA" not in escrito
    texto = chamadas.read_text()
    for mudanca in (" scale ", "set env", "apply", "rollout", "create secret"):
        assert mudanca not in texto


def test_sem_credencial_o_modo_real_diz_como_ler_sem_colar_no_comando(
    tmp_path: Path,
) -> None:
    resultado, _, _ = _sessao_do_sandbox(tmp_path, E2E_MP_MODO="real")

    saida = resultado.stdout + resultado.stderr
    assert resultado.returncode == 2
    assert "MP_ACCESS_TOKEN não está no ambiente" in saida
    assert "read -rs MP_ACCESS_TOKEN" in saida
    assert "Traceback" not in saida


def test_contexto_que_nao_e_kind_nao_vale_nem_com_o_escape_do_e2e(
    tmp_path: Path,
) -> None:
    estado = criar_cluster_falso(tmp_path)

    resultado = _pytest(
        ARQUIVO_DO_SANDBOX,
        "-m",
        "mp_sandbox",
        "-p",
        "no:randomly",
        ambiente=_ambiente(
            KUBE_CONTEXT="k3s-da-vm",
            E2E_CONTEXTO_NAO_DESCARTAVEL="k3s-da-vm",
            E2E_MP_MODO="ensaio",
            FALSO_ESTADO=str(estado),
            PATH=f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}",
        ),
    )

    saida = resultado.stdout + resultado.stderr
    assert resultado.returncode == 2
    assert "não é um kind" in saida
    assert "E2E_CONTEXTO_NAO_DESCARTAVEL não vale aqui" in saida
    assert "Traceback" not in saida
    texto = (estado / "chamadas").read_text()
    for mudanca in (" scale ", "set env", "apply", "rollout"):
        assert mudanca not in texto


def test_contexto_que_nao_e_kind_sem_escape_tambem_sai_sem_traceback(
    tmp_path: Path,
) -> None:
    estado = criar_cluster_falso(tmp_path)

    resultado = _pytest(
        ARQUIVO_DO_SANDBOX,
        "-m",
        "mp_sandbox",
        "-p",
        "no:randomly",
        ambiente=_ambiente(
            KUBE_CONTEXT="k3s-da-vm",
            E2E_MP_MODO="ensaio",
            FALSO_ESTADO=str(estado),
            PATH=f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}",
        ),
    )

    saida = resultado.stdout + resultado.stderr
    assert resultado.returncode == 2
    assert "sandbox do Mercado Pago:" in saida
    assert "nao e um kind descartavel" in saida
    assert "Traceback" not in saida
    assert (estado / "chamadas").read_text() == ""


def test_a_saga_continua_com_traceback_no_guarda_de_contexto(tmp_path: Path) -> None:
    # Fora do sandbox o guarda do E2E da saga e o de sempre: erro com traceback.
    estado = criar_cluster_falso(tmp_path)

    resultado = _pytest(
        "e2e",
        "-m",
        "borda",
        "-p",
        "no:randomly",
        ambiente=_ambiente(
            KUBE_CONTEXT="k3s-da-vm",
            FALSO_ESTADO=str(estado),
            PATH=f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}",
        ),
    )

    assert resultado.returncode != 0
    assert "ContextoNaoDescartavelError" in resultado.stdout


def test_kubectl_que_falha_no_preflight_sai_sem_traceback_e_sem_o_ambiente(
    tmp_path: Path,
) -> None:
    # O kubectl falso do E2E nao sabe responder "get deployment ... envFrom": quebra.
    estado = criar_cluster_falso(tmp_path)

    resultado = _pytest(
        ARQUIVO_DO_SANDBOX,
        "-m",
        "mp_sandbox",
        "-p",
        "no:randomly",
        ambiente=_ambiente(
            KUBE_CONTEXT="kind-pytstop-p4",
            E2E_MP_MODO="ensaio",
            CREDENCIAL_DE_OUTRA_COISA="valor-secreto-do-ambiente-9999",
            FALSO_ESTADO=str(estado),
            PATH=f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}",
        ),
    )

    saida = resultado.stdout + resultado.stderr
    assert resultado.returncode == 2
    assert "o kubectl falhou ao ler a configuração do Billing" in saida
    # O traceback do pytest (o do script falso que quebrou vem no texto do erro).
    assert "ERROR at setup" not in saida
    assert "def preparar_sandbox" not in saida
    assert "valor-secreto-do-ambiente-9999" not in saida
    chamadas = (estado / "chamadas").read_text()
    for mudanca in (" scale ", "set env", "apply", "rollout"):
        assert mudanca not in chamadas
