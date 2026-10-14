"""Processos de verdade: executar_processo e o port-forward."""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess  # nosec B404
import sys
import time
from pathlib import Path

import pytest

from e2e.apoio import segredos
from e2e.apoio.espera import TempoEsgotadoError
from e2e.apoio.kube import (
    ErroDeComandoError,
    Kubectl,
    PortForward,
    executar_processo,
)
from e2e_apoio.falsos import pids_do_kubectl_falso, processo_vivo

RAIZ = Path(__file__).resolve().parents[2]


def test_executar_processo_devolve_a_saida() -> None:
    assert (
        executar_processo([sys.executable, "-c", "print('ola')"], 10).strip() == "ola"
    )


def test_executar_processo_entrada_vai_so_pelo_stdin_e_nao_pelo_argv() -> None:
    programa = "import sys; sys.stdout.write(sys.stdin.read().upper())"

    saida = executar_processo([sys.executable, "-c", programa], 10, "token-secreto")

    assert saida == "TOKEN-SECRETO"
    assert "token-secreto" not in programa


def test_executar_processo_sem_entrada_o_stdin_e_vazio() -> None:
    programa = "import sys; print(repr(sys.stdin.read()))"

    assert executar_processo([sys.executable, "-c", programa], 10).strip() == "''"


def test_executar_processo_codigo_de_saida_diferente_de_zero_reprova_sem_segredo() -> (
    None
):
    segredos.registrar("senha-do-admin-123")
    codigo = (
        "import sys; sys.stderr.write('falhou com senha-do-admin-123'); sys.exit(3)"
    )

    with pytest.raises(ErroDeComandoError) as erro:
        executar_processo([sys.executable, "-c", codigo], 10)

    assert "saiu com 3" in str(erro.value)
    assert "senha-do-admin-123" not in str(erro.value)


def test_executar_processo_passou_do_prazo_mata_e_reprova() -> None:
    with pytest.raises(ErroDeComandoError, match=r"passou de 0\.5 s"):
        executar_processo([sys.executable, "-c", "import time; time.sleep(30)"], 0.5)


def test_port_forward_abre_a_porta_e_fecha_no_fim(kubectl_falso: Path) -> None:
    import socket

    kubectl = Kubectl("kind-x", binario=str(kubectl_falso))

    with PortForward(kubectl, "ns", "svc/mailpit", 8025) as ponte:
        assert ponte.url == f"http://127.0.0.1:{ponte.porta}"
        with socket.create_connection(("127.0.0.1", ponte.porta), timeout=2):
            pass

    with pytest.raises(OSError, match=r"refused|Connection"):
        socket.create_connection(("127.0.0.1", ponte.porta), timeout=2)


def test_port_forward_garantir_religa_o_kubectl_que_morreu(kubectl_falso: Path) -> None:
    kubectl = Kubectl("kind-x", binario=str(kubectl_falso))
    ponte = PortForward(kubectl, "ns", "svc/mailpit", 8025).iniciar()
    try:
        primeiro = ponte._processo
        assert primeiro is not None
        primeiro.kill()
        primeiro.wait()

        ponte.garantir()

        segundo = ponte._processo
        assert segundo is not primeiro
        assert segundo is not None
        assert segundo.poll() is None
        ponte.garantir()
        # Vivo, o kubectl nao e reiniciado a cada chamada.
        assert ponte._processo is segundo
    finally:
        ponte.encerrar()


def test_port_forward_kubectl_que_sai_na_hora_reprova_com_codigo_e_stderr(
    kubectl_falso: Path,
) -> None:
    ponte = PortForward(
        Kubectl("kind-x", binario=str(kubectl_falso)), "ns", "sai", 8025
    )
    try:
        with pytest.raises(
            ErroDeComandoError, match=r"codigo 3.*address already in use"
        ):
            ponte.iniciar(prazo=5)
    finally:
        ponte.encerrar()


def test_port_forward_que_nao_escuta_nao_deixa_o_kubectl_orfao(
    kubectl_falso: Path,
) -> None:
    ponte = PortForward(
        Kubectl("kind-x", binario=str(kubectl_falso)), "ns", "nao-escuta", 8025
    )

    with pytest.raises(TempoEsgotadoError, match="aceitando conexoes"):
        ponte.iniciar(prazo=1)

    assert not any(processo_vivo(pid) for pid in pids_do_kubectl_falso(kubectl_falso))
    assert ponte._processo is None


def test_port_forward_erro_do_kubectl_sai_mascarado(kubectl_falso: Path) -> None:
    segredos.registrar("address")
    ponte = PortForward(
        Kubectl("kind-x", binario=str(kubectl_falso)), "ns", "sai", 8025
    )
    try:
        with pytest.raises(ErroDeComandoError) as erro:
            ponte.iniciar(prazo=5)
    finally:
        ponte.encerrar()

    assert "address" not in str(erro.value)
    assert "***" in str(erro.value)


def test_port_forward_encerrar_mata_o_kubectl_que_ignora_o_terminate() -> None:
    chamadas: list[str] = []

    class Teimoso:
        def terminate(self) -> None:
            chamadas.append("terminate")

        def kill(self) -> None:
            chamadas.append("kill")

        def wait(self, timeout: float) -> int:
            chamadas.append(f"wait {timeout:g}")
            if chamadas.count("terminate") == 1 and "kill" not in chamadas:
                raise subprocess.TimeoutExpired("kubectl", timeout)
            return 0

    ponte = PortForward(Kubectl("kind-x"), "ns", "svc/x", 1)
    ponte._processo = Teimoso()  # type: ignore[assignment]  # falso do Popen

    ponte.encerrar()

    assert chamadas == ["terminate", "wait 5", "kill", "wait 5"]
    assert ponte._processo is None


def test_port_forward_encerrar_sem_iniciar_nao_faz_nada() -> None:
    PortForward(Kubectl("kind-x"), "ns", "svc/x", 1).encerrar()


def test_executar_processo_mascara_o_erro_inteiro_antes_de_cortar() -> None:
    # Um valor registrado que cruza o limite de 400 caracteres nao pode sobrar pela
    # metade: o corte vem depois da mascara.
    segredos.registrar("segredo-que-cruza-o-corte")
    codigo = (
        "import sys; sys.stderr.write('x' * 390 + ' segredo-que-cruza-o-corte');"
        "sys.exit(2)"
    )

    with pytest.raises(ErroDeComandoError) as erro:
        executar_processo([sys.executable, "-c", codigo], 10)

    assert "segredo" not in str(erro.value)
    assert "***" in str(erro.value)


def test_port_forward_encerrar_fecha_o_arquivo_do_stderr(kubectl_falso: Path) -> None:
    ponte = PortForward(
        Kubectl("kind-x", binario=str(kubectl_falso)), "ns", "svc/mailpit", 8025
    ).iniciar()
    erros = ponte._erros
    assert erros is not None
    assert not erros.closed

    ponte.encerrar()

    assert erros.closed
    assert ponte._erros is None


def test_port_forward_sem_iniciar_nao_tem_stderr_para_mostrar() -> None:
    ponte = PortForward(Kubectl("kind-x"), "ns", "svc/x", 1)

    assert ponte._ultimas_linhas_do_erro() == ""


def test_executar_processo_roda_em_sessao_propria_e_o_ctrl_c_do_terminal_nao_o_alcanca(
    tmp_path: Path,
) -> None:
    # O Ctrl-C do terminal vai ao grupo de processos inteiro (os.killpg). O Python do
    # desfazer o ignora, mas o kubectl em voo morreria junto sem a sessao propria.
    filho = tmp_path / "filho.py"
    filho.write_text(
        "import signal, time\n"
        "from pathlib import Path\n"
        f"pasta = Path({str(tmp_path)!r})\n"
        "signal.signal(signal.SIGINT, lambda *_: (pasta / 'sigint').write_text('1'))\n"
        "(pasta / 'inicio').write_text('1')\n"
        "time.sleep(1.5)\n"
        "(pasta / 'fim').write_text('1')\n"
    )
    lider = tmp_path / "lider.py"
    lider.write_text(
        "import signal, sys\n"
        "from e2e.apoio.kube import executar_processo\n"
        "signal.signal(signal.SIGINT, signal.SIG_IGN)\n"
        f"executar_processo([sys.executable, {str(filho)!r}], 30)\n"
    )
    # start_new_session: o killpg do teste so alcanca o lider e o filho dele.
    processo = subprocess.Popen(  # noqa: S603  # nosec B603
        [sys.executable, str(lider)],
        env={**os.environ, "PYTHONPATH": str(RAIZ)},
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        limite = time.monotonic() + 30
        while not (tmp_path / "inicio").exists():
            assert time.monotonic() < limite, "o filho nao chegou a rodar"
            time.sleep(0.05)
        os.killpg(processo.pid, signal.SIGINT)
        processo.wait(timeout=30)
    finally:
        # Sobra de grupo so se o teste falhar; com o grupo ja vazio, nao ha o que matar.
        with contextlib.suppress(ProcessLookupError):
            os.killpg(processo.pid, signal.SIGKILL)
        processo.wait()

    assert processo.returncode == 0
    assert (tmp_path / "fim").exists()
    assert not (tmp_path / "sigint").exists(), "o kubectl recebeu o Ctrl-C do terminal"
