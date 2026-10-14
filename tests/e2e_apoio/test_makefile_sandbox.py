"""O Makefile do sandbox com um ``uv`` falso: a ordem e a pasta de relatorios.

A conferencia roda antes do pytest e antes de qualquer mudanca em ``reports/``: uma
execucao que reprova nela (credencial esquecida, cluster fora do ar) nao pode apagar
nem girar a evidencia de uma execucao boa. Cada caso roda o ``make`` do repositorio
numa pasta temporaria, e o ``uv`` falso registra o que o Makefile pediu.
"""

from __future__ import annotations

import os
import re
import shutil

# subprocess roda o make do proprio repositorio, sem shell.
import subprocess  # nosec B404
import time
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
MAKEFILE = RAIZ / "Makefile"

UV_FALSO = """\
#!/bin/sh
echo "KUBE_CONTEXT=${KUBE_CONTEXT:-} $*" >> "$FALSO_PASTA/chamadas"
case "$*" in
  *e2e.conferir_sandbox*) exit "${FALSO_CONFERIR:-0}" ;;
  *"pytest "*)
    if [ -n "${FALSO_ESCREVE_RESUMO:-}" ]; then : > "$E2E_RELATORIOS/resumo.md"; fi
    exit "${FALSO_PYTEST:-0}" ;;
esac
exit 0
"""
GIRADA = re.compile(r"reports/mp-sandbox\.\d{8}-\d{6}")


@pytest.fixture
def pasta(tmp_path: Path) -> Path:
    uv = tmp_path / "bin" / "uv"
    uv.parent.mkdir()
    uv.write_text(UV_FALSO)
    uv.chmod(0o755)
    return tmp_path


def _make(pasta: Path, alvo: str, **ambiente: str) -> subprocess.CompletedProcess[str]:
    base = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("E2E_", "KUBE_", "MP_", "FALSO_"))
    }
    return subprocess.run(  # noqa: S603  # nosec B603
        [shutil.which("make") or "make", "-C", str(pasta), "-f", str(MAKEFILE), alvo],
        env={
            **base,
            "PATH": f"{pasta / 'bin'}{os.pathsep}{base['PATH']}",
            "FALSO_PASTA": str(pasta),
            **ambiente,
        },
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        stdin=subprocess.DEVNULL,
    )


def _chamadas(pasta: Path) -> list[str]:
    arquivo = pasta / "chamadas"
    return arquivo.read_text().splitlines() if arquivo.exists() else []


def _giradas(pasta: Path) -> list[str]:
    return sorted(
        p.name for p in (pasta / "reports").glob("mp-sandbox.*") if p.is_dir()
    )


def test_conferencia_que_reprova_para_antes_de_pytest_relatorios_e_resumo(
    pasta: Path,
) -> None:
    resultado = _make(pasta, "mp-sandbox", FALSO_CONFERIR="2")

    assert resultado.returncode == 2, resultado.stdout + resultado.stderr
    assert _chamadas(pasta) == [
        (
            "KUBE_CONTEXT=kind-pytstop-p4 run --group e2e python -m "
            "e2e.conferir_sandbox real"
        )
    ]
    assert not (pasta / "reports").exists(), "nem a pasta de relatorios foi criada"
    saida = resultado.stdout + resultado.stderr
    assert "resumo escrito" not in saida
    assert "varredura" not in saida


def test_execucao_boa_confere_roda_o_pytest_resume_e_varre_nessa_ordem(
    pasta: Path,
) -> None:
    resultado = _make(pasta, "mp-sandbox", FALSO_ESCREVE_RESUMO="1")

    assert resultado.returncode == 0, resultado.stdout + resultado.stderr
    chamadas = _chamadas(pasta)
    assert [
        c.split("python -m ")[-1].split()[0] for c in chamadas if "python" in c
    ] == [
        "e2e.conferir_sandbox",
        "e2e.resumo",
        "e2e.varredura",
    ]
    assert "pytest -c e2e/pytest.ini e2e -m mp_sandbox" in chamadas[1]
    assert (pasta / "reports" / "mp-sandbox" / "resumo.md").exists()


def test_a_conferencia_leva_o_contexto_do_make(pasta: Path) -> None:
    resultado = _make(pasta, "mp-sandbox-ensaio")
    assert resultado.returncode == 0, resultado.stdout + resultado.stderr
    assert _chamadas(pasta)[0].startswith("KUBE_CONTEXT=kind-pytstop-p4 run")
    assert _chamadas(pasta)[0].endswith("e2e.conferir_sandbox ensaio")


def test_segunda_execucao_boa_guarda_a_primeira_em_pasta_com_data_e_hora(
    pasta: Path,
) -> None:
    _make(pasta, "mp-sandbox", FALSO_ESCREVE_RESUMO="1")
    primeiro = pasta / "reports" / "mp-sandbox" / "resumo.md"
    primeiro.write_text("a primeira evidencia boa")
    time.sleep(1.1)  # o nome da pasta tem a hora ate o segundo

    resultado = _make(pasta, "mp-sandbox", FALSO_ESCREVE_RESUMO="1")

    assert resultado.returncode == 0, resultado.stdout + resultado.stderr
    giradas = _giradas(pasta)
    assert len(giradas) == 1
    assert GIRADA.fullmatch(f"reports/{giradas[0]}")
    assert (pasta / "reports" / giradas[0] / "resumo.md").read_text() == (
        "a primeira evidencia boa"
    )
    assert (pasta / "reports" / "mp-sandbox" / "resumo.md").read_text() == ""


def test_duas_falhas_de_conferencia_seguidas_nao_apagam_a_evidencia_boa(
    pasta: Path,
) -> None:
    # O caso do token esquecido num shell novo: depois de uma execucao boa, duas que
    # reprovam na conferencia. A evidencia boa continua onde estava.
    _make(pasta, "mp-sandbox", FALSO_ESCREVE_RESUMO="1")
    boa = pasta / "reports" / "mp-sandbox" / "resumo.md"
    boa.write_text("a evidencia boa")

    for _ in range(2):
        resultado = _make(pasta, "mp-sandbox", FALSO_CONFERIR="2")
        assert resultado.returncode == 2

    assert boa.read_text() == "a evidencia boa"
    assert _giradas(pasta) == []


def test_pasta_que_ficou_sem_resumo_e_limpa_e_nao_vira_pasta_com_data(
    pasta: Path,
) -> None:
    sobra = pasta / "reports" / "mp-sandbox"
    sobra.mkdir(parents=True)
    (sobra / "junit.xml").write_text("de uma execucao que morreu antes do resumo")

    resultado = _make(pasta, "mp-sandbox")

    assert resultado.returncode == 0, resultado.stdout + resultado.stderr
    assert not (sobra / "junit.xml").exists()
    assert _giradas(pasta) == []


def test_pytest_que_reprova_ainda_resume_varre_e_falha(pasta: Path) -> None:
    resultado = _make(pasta, "mp-sandbox", FALSO_PYTEST="1", FALSO_ESCREVE_RESUMO="1")

    assert resultado.returncode != 0
    chamadas = " ".join(_chamadas(pasta))
    assert "e2e.resumo" in chamadas
    assert "e2e.varredura" in chamadas


def test_o_ensaio_confere_antes_e_nunca_toca_na_evidencia_do_real(pasta: Path) -> None:
    _make(pasta, "mp-sandbox", FALSO_ESCREVE_RESUMO="1")
    real = pasta / "reports" / "mp-sandbox" / "resumo.md"
    real.write_text("a evidencia do real")

    reprovado = _make(pasta, "mp-sandbox-ensaio", FALSO_CONFERIR="2")
    aprovado = _make(pasta, "mp-sandbox-ensaio", FALSO_ESCREVE_RESUMO="1")

    assert reprovado.returncode == 2
    assert not (pasta / "reports" / "mp-sandbox-ensaio" / "junit.xml").exists()
    assert aprovado.returncode == 0, aprovado.stdout + aprovado.stderr
    assert real.read_text() == "a evidencia do real"
    assert _giradas(pasta) == []
