"""As ligacoes do conftest do E2E, com o pytest de verdade e um cluster falso.

O conftest decide a ordem da sessao: guarda do contexto, preflight do overlay e
das DLQs, e so depois qualquer ``kubectl scale``; e devolve ao cluster, no fim de
cada cenario e da sessao, o que o cenario derrubou. Nada disso aparece num
``make e2e`` verde, entao cada ligacao e provada aqui: uma suite minima carrega o
``e2e.conftest`` como plugin e roda contra um ``kubectl`` falso.
"""

from __future__ import annotations

import json
import os

# subprocess roda o pytest do proprio repositorio, sem shell.
import subprocess  # nosec B404
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import unquote

import pytest

from e2e import ambiente
from e2e import conftest as conftest_do_e2e
from e2e_apoio.falsos import criar_cluster_falso

RAIZ = Path(__file__).resolve().parents[2]
INI = RAIZ / "e2e" / "pytest.ini"
CONSUMIDOR = "billing-service-consumidor"
API = "billing-service-api"

CONFTEST = """\
pytest_plugins = ["e2e.conftest"]
{extra}
"""


def _rodar(
    pasta: Path, estado: Path, testes: str, extra_do_conftest: str = ""
) -> subprocess.CompletedProcess[str]:
    suite = pasta / "suite"
    suite.mkdir()
    (suite / "conftest.py").write_text(CONFTEST.format(extra=extra_do_conftest))
    (suite / "test_suite.py").write_text(testes)
    ambiente = {
        **{k: v for k, v in os.environ.items() if not k.startswith(("E2E_", "KUBE_"))},
        "PYTHONPATH": str(RAIZ),
        "KUBE_CONTEXT": "kind-pytstop-p4",
        "FALSO_ESTADO": str(estado),
        "OBSERVADO": str(pasta / "observado"),
        "PATH": f"{pasta / 'bin'}{os.pathsep}{os.environ['PATH']}",
    }
    ambiente.pop("GITHUB_ACTIONS", None)
    return subprocess.run(  # noqa: S603  # nosec B603
        [
            sys.executable,
            "-m",
            "pytest",
            "-c",
            str(INI),
            "--rootdir",
            str(suite),
            str(suite),
        ],
        cwd=suite,
        env=ambiente,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        stdin=subprocess.DEVNULL,
    )


@pytest.fixture
def estado(tmp_path: Path) -> Path:
    return criar_cluster_falso(tmp_path)


def _chamadas(estado: Path) -> list[str]:
    return (estado / "chamadas").read_text().splitlines()


def _escalas(estado: Path) -> list[str]:
    return [c for c in _chamadas(estado) if " scale " in c]


def test_cenario_que_reprova_depois_de_zerar_devolve_o_que_derrubou_antes_do_seguinte(
    tmp_path: Path, estado: Path
) -> None:
    testes = f"""\
import os
from pathlib import Path


def test_a_zera_e_reprova(escalas):
    escalas.zerar("pytstop-billing", "{CONSUMIDOR}")
    assert False, "reprova depois de derrubar o consumidor"


def test_b_ve_o_consumidor_de_pe():
    replicas = Path(os.environ["FALSO_ESTADO"]) / "replicas-{CONSUMIDOR}"
    Path(os.environ["OBSERVADO"]).write_text(replicas.read_text())
"""

    resultado = _rodar(tmp_path, estado, testes)

    assert resultado.returncode == 1, resultado.stdout
    assert (tmp_path / "observado").read_text() == "1"
    escalas = _escalas(estado)
    assert any("--replicas=0" in c for c in escalas)
    assert any("--replicas=1" in c for c in escalas)


def test_sessao_restaura_no_fim_o_que_uma_fixture_de_sessao_derrubou(
    tmp_path: Path, estado: Path
) -> None:
    conftest = f"""\
import pytest


@pytest.fixture(scope="session", autouse=True)
def derruba_no_fim(escalas):
    yield
    escalas.zerar("pytstop-billing", "{API}")
"""

    resultado = _rodar(tmp_path, estado, "def test_x():\n    pass\n", conftest)

    assert resultado.returncode == 0, resultado.stdout
    assert (estado / f"replicas-{API}").read_text() == "1"


def test_o_passo_do_consumidor_parado_so_derruba_o_pod_depois_de_o_prometheus_raspa_lo(
    tmp_path: Path, estado: Path
) -> None:
    # O passo de verdade, com as fixtures de verdade e um cluster falso: o pod do
    # consumidor so cai depois de o Prometheus ter raspado o consumidor. Sem a espera
    # o que o pod contou desde a ultima raspagem some do contador do Billing (no make
    # demo, o estorno de dois cenarios antes: a causa provavel dos 6 contra 8 do OS).
    testes = """\
from e2e.test_saga import _consumidor_parado


def test_passo(escalas, kubectl, cenario):
    _consumidor_parado(escalas, kubectl, cenario)
"""

    resultado = _rodar(tmp_path, estado, testes)

    assert resultado.returncode == 0, resultado.stdout
    chamadas = _chamadas(estado)
    ao_prometheus = [i for i, c in enumerate(chamadas) if "prometheus:9090" in c]
    derrubada = next(
        i for i, c in enumerate(chamadas) if " scale " in c and "--replicas=0" in c
    )
    assert ao_prometheus, "o passo derrubou o consumidor sem perguntar ao Prometheus"
    assert max(ao_prometheus) < derrubada
    ultima = unquote(chamadas[ao_prometheus[-1]].split("query=")[1])
    assert 'job="billing-service-consumidor"' in ultima
    assert 'namespace="pytstop-billing"' in ultima


def test_inicio_da_sessao_religa_o_que_a_execucao_anterior_deixou_em_zero(
    tmp_path: Path, estado: Path
) -> None:
    (estado / f"replicas-{CONSUMIDOR}").write_text("0")

    resultado = _rodar(tmp_path, estado, "def test_x():\n    pass\n")

    assert resultado.returncode == 0, resultado.stdout
    assert (estado / f"replicas-{CONSUMIDOR}").read_text() == "1"
    assert f"scale deployment/{CONSUMIDOR} --replicas=1" in _escalas(estado)[0]


def test_overlay_diferente_do_kind_ci_reprova_antes_do_primeiro_scale(
    tmp_path: Path, estado: Path
) -> None:
    (estado / "configmap.json").write_text(
        json.dumps({"ORCAMENTO_VALIDADE_HORAS": "24", "PAGAMENTO_MAX_RECUSAS": "3"})
    )

    resultado = _rodar(tmp_path, estado, "def test_x():\n    pass\n")

    assert resultado.returncode != 0
    assert "nao esta no overlay kind-ci" in resultado.stdout
    assert _escalas(estado) == []


def test_dlq_com_mensagem_reprova_antes_do_primeiro_scale(
    tmp_path: Path, estado: Path
) -> None:
    (estado / "dlq.json").write_text(
        json.dumps(
            {
                "billing.comandos.dlq": 0,
                "execucao.comandos.dlq": 0,
                "os.eventos.dlq": 4,
            }
        )
    )

    resultado = _rodar(tmp_path, estado, "def test_x():\n    pass\n")

    assert resultado.returncode != 0
    assert "DLQs com mensagem antes do primeiro cenario" in resultado.stdout
    assert _escalas(estado) == []


def test_o_conftest_guarda_o_desfecho_da_chamada_de_cada_cenario(
    tmp_path: Path, estado: Path
) -> None:
    # O resultado de cada cenario do sandbox no resumo.md vem daqui: passed, failed
    # e, no Ctrl-C, ausente. O terceiro teste interrompe a sessao.
    saida = tmp_path / "desfechos"
    conftest = f"""\
from pathlib import Path

import pytest

from e2e.apoio.plugin_sandbox import desfecho_da_chamada


@pytest.fixture(autouse=True)
def registrar(request):
    yield
    desfecho = desfecho_da_chamada(request.node)
    with Path({str(saida)!r}).open("a") as arquivo:
        arquivo.write(f"{{request.node.name}}={{desfecho}}\\n")
"""
    testes = (
        "def test_a():\n    pass\n\n\n"
        "def test_b():\n    assert False\n\n\n"
        "def test_c():\n    raise KeyboardInterrupt\n"
    )

    resultado = _rodar(tmp_path, estado, testes, conftest)

    assert resultado.returncode == 2, resultado.stdout
    assert saida.read_text().splitlines() == [
        "test_a=passed",
        "test_b=failed",
        "test_c=None",
    ]


@pytest.mark.parametrize(
    ("tipo", "imprime"), [("given", False), ("when", False), ("then", True)]
)
def test_narracao_mostra_o_status_da_os_so_depois_de_um_entao(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tipo: str,
    imprime: bool,
) -> None:
    ordens = SimpleNamespace(
        ordem=lambda ordem_id: {"status": "recebida", "etapa": "aguardando_diagnostico"}
    )
    fixtures: dict[str, Any] = {
        "cenario": SimpleNamespace(ordem_id="abc", resumo="OS abc"),
        "api": SimpleNamespace(os=ordens),
    }
    request = SimpleNamespace(getfixturevalue=fixtures.__getitem__)
    passo = SimpleNamespace(type=tipo, line_number=30)
    monkeypatch.setattr(ambiente, "NARRAR", True)
    monkeypatch.setattr(conftest_do_e2e, "NARRAR", True)

    conftest_do_e2e.pytest_bdd_after_step(
        request,  # type: ignore[arg-type]  # fake com so o getfixturevalue
        SimpleNamespace(background=None),  # type: ignore[arg-type]  # fake sem Contexto
        SimpleNamespace(),  # type: ignore[arg-type]  # o hook nao le o cenario
        passo,  # type: ignore[arg-type]  # fake com so o tipo e a linha
        None,
        {},
    )

    saida = capsys.readouterr().out
    assert (
        "-> OS abc: status=recebida etapa=aguardando_diagnostico" in saida
    ) is imprime
