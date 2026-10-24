"""As ligacoes do conftest do E2E, com o pytest de verdade e um cluster falso.

O conftest decide a ordem da sessao: guarda do contexto, preflight do overlay e
das DLQs, e so depois qualquer ``kubectl scale``; e devolve ao cluster, no fim de
cada cenario e da sessao, o que o cenario derrubou. Nada disso aparece num
``make e2e`` verde, entao cada ligacao e provada aqui: uma suite minima carrega o
``e2e.conftest`` como plugin e roda contra um ``kubectl`` falso.
"""

from __future__ import annotations

import ast
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
from e2e_apoio.falsos import INTERVALO_DA_RASPAGEM, criar_cluster_falso

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
    # O Prometheus falso responde duas vezes com a raspagem de antes do pedido e so na
    # terceira com uma posterior; o passo espera por ela (10 ms entre as perguntas, no
    # lugar do 1 s de verdade).
    (estado / "raspagens-antigas").write_text("2")
    testes = """\
from e2e import test_saga
from e2e.apoio import prometheus


def test_passo(monkeypatch, escalas, kubectl, cenario):
    monkeypatch.setattr(prometheus, "INTERVALO_DA_ESPERA", 0.01)
    test_saga._consumidor_parado(escalas, kubectl, cenario)
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
    perguntas = [unquote(chamadas[i].split("query=")[1]) for i in ao_prometheus]
    # O time(), as duas raspagens antigas e a posterior: espera ate a que vale, e para.
    assert perguntas[0] == "time()"
    assert len(perguntas) == 1 + 3, perguntas
    for pergunta in perguntas[1:]:
        assert 'job="billing-service-consumidor"' in pergunta
        assert 'namespace="pytstop-billing"' in pergunta


def test_passo_do_consumidor_parado_reprova_e_nao_derruba_se_o_prometheus_nao_raspa(
    tmp_path: Path, estado: Path
) -> None:
    # O Prometheus falso nunca traz uma raspagem posterior ao pedido: o passo reprova no
    # prazo e o pod do consumidor continua de pe. Quem engole o estouro derruba o pod
    # sem a raspagem. O prazo aqui e de 0,5 s; o de verdade e o PRAZO_DA_RASPAGEM, e a
    # mensagem diz o prazo que o passo passou a espera.
    (estado / "raspagens-antigas").write_text("1000000")
    testes = """\
from e2e import test_saga
from e2e.apoio import prometheus


def test_passo(monkeypatch, escalas, kubectl, cenario):
    monkeypatch.setattr(prometheus, "INTERVALO_DA_ESPERA", 0.01)
    monkeypatch.setattr(test_saga, "PRAZO_DA_RASPAGEM", 0.5)
    test_saga._consumidor_parado(escalas, kubectl, cenario)
"""

    resultado = _rodar(tmp_path, estado, testes)

    assert resultado.returncode == 1, resultado.stdout
    assert "nao ocorreu em 0.5 s" in resultado.stdout
    derrubadas = [c for c in _escalas(estado) if "--replicas=0" in c]
    assert not derrubadas, "o passo derrubou o consumidor sem a raspagem"


def _prazo_da_raspagem_do_passo() -> float:
    """O ``PRAZO_DA_RASPAGEM`` de ``e2e/test_saga.py``, lido do codigo.

    O modulo so importa com os markers do E2E (``-c e2e/pytest.ini``): aqui, com os do
    repositorio, o ``--strict-markers`` recusa as tags do Gherkin.
    """
    fonte = (RAIZ / "e2e" / "test_saga.py").read_text(encoding="utf-8")
    (valor,) = (
        no.value
        for no in ast.parse(fonte).body
        if isinstance(no, ast.AnnAssign)
        and isinstance(no.target, ast.Name)
        and no.target.id == "PRAZO_DA_RASPAGEM"
        and no.value is not None
    )
    return float(ast.literal_eval(valor))


def test_o_prazo_do_passo_cobre_duas_raspagens_do_prometheus() -> None:
    # Com a raspagem a cada 15 s, um prazo menor que dois intervalos reprovaria o CI de
    # verdade num runner que atrasa a raspagem seguinte.
    assert _prazo_da_raspagem_do_passo() >= 2 * INTERVALO_DA_RASPAGEM


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
