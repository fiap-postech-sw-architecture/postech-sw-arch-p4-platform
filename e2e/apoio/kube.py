"""kubectl do E2E: sempre com contexto explicito e prazo, e falhas desfeitas no fim.

Tudo o que o E2E faz no cluster fora da borda passa por aqui: ler Secret e
ConfigMap, escalar Deployment (as falhas dos cenarios de resiliencia), listar
as DLQs no RabbitMQ, ler logs e abrir port-forward. Nada pendura: todo comando
tem prazo, e o que o cenario derruba volta no teardown.
"""

from __future__ import annotations

import base64
import json
import os
import socket
import subprocess  # nosec B404
import tempfile
import time
from typing import TYPE_CHECKING, Any, Final

from e2e.apoio.espera import esperar
from e2e.apoio.segredos import CREDENCIAIS_DO_AMBIENTE, mascarar

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from types import TracebackType
    from typing import IO

    type Executor = Callable[[Sequence[str], float], str]
    # O mesmo executor com o texto que vai pelo stdin do processo.
    type ExecutorComEntrada = Callable[[Sequence[str], float, str], str]

NAMESPACE_DA_PLATAFORMA: Final = "pytstop-plataforma"
# As DLQs do broker (k8s/base/rabbitmq): uma ausente na leitura e nome que mudou, e
# "nenhuma mensagem nova" nao vale se a fila nem aparece.
FILA_MORTA_DO_BILLING: Final = "billing.comandos.dlq"
FILAS_MORTAS: Final = (
    FILA_MORTA_DO_BILLING,
    "execucao.comandos.dlq",
    "os.eventos.dlq",
)
_TAMANHO_DO_ERRO: Final = 400
PRAZO_DAS_DLQS: Final = 40.0


class ErroDeComandoError(AssertionError):
    """O comando saiu com erro ou passou do prazo."""


def _ambiente_dos_filhos() -> dict[str, str]:
    """O ambiente deste processo sem as credenciais do Mercado Pago.

    O ``kubectl``, o ``docker`` e o ``port-forward`` nao as usam. O pytest e o
    ``conferir_sandbox`` as tem no proprio ambiente ate o preflight tira-las, e os
    primeiros filhos (a conferencia previa e a fixture ``kubectl``) rodam antes disso.
    """
    return {
        chave: valor
        for chave, valor in os.environ.items()
        if chave not in CREDENCIAIS_DO_AMBIENTE
    }


def executar_processo(
    argumentos: Sequence[str], prazo: float, entrada: str | None = None
) -> str:
    """Roda o comando sem shell, com prazo (estourou, o processo e morto).

    ``entrada`` vai pelo stdin do processo e so por ele: e o caminho do que nao
    pode estar em argv (``ps``) nem em arquivo. Sem ``entrada``, o stdin e vazio.
    """
    comando = " ".join(argumentos[:8])
    try:
        processo = subprocess.run(  # noqa: S603  # nosec B603
            list(argumentos),
            capture_output=True,
            text=True,
            timeout=prazo,
            check=False,
            env=_ambiente_dos_filhos(),
            input=entrada,
            # input e stdin nao convivem: sem entrada, o stdin e vazio.
            stdin=subprocess.DEVNULL if entrada is None else None,
            # Sessao propria: o Ctrl-C do terminal vai ao grupo de processos inteiro e
            # mataria o kubectl em voo do desfazer, que ignora o sinal so no Python.
            start_new_session=True,
        )
    except subprocess.TimeoutExpired as erro:
        raise ErroDeComandoError(
            mascarar(f"{comando}: passou de {prazo:g} s")
        ) from erro
    if processo.returncode != 0:
        # Mascara o texto inteiro e so entao corta: um JWT cortado ao meio nao casa
        # com o padrao nem com o valor registrado.
        detalhe = mascarar(processo.stderr.strip())[:_TAMANHO_DO_ERRO]
        raise ErroDeComandoError(
            mascarar(f"{comando}: saiu com {processo.returncode}: {detalhe}")
        )
    return processo.stdout


def ler_filas_mortas(saida: str) -> dict[str, int]:
    """DLQs da saida de ``rabbitmqctl -q list_queues name messages``."""
    filas: dict[str, int] = {}
    for linha in saida.splitlines():
        partes = linha.split()
        if len(partes) == 2 and partes[0].endswith(".dlq") and partes[1].isdigit():
            filas[partes[0]] = int(partes[1])
    return filas


class Kubectl:
    """kubectl num contexto fixo (``KUBE_CONTEXT``), com o executor injetavel."""

    def __init__(
        self,
        contexto: str,
        *,
        executor: Executor = executar_processo,
        executor_com_entrada: ExecutorComEntrada = executar_processo,
        binario: str = "kubectl",
    ) -> None:
        self.contexto = contexto
        self.binario = binario
        self._executor = executor
        self._executor_com_entrada = executor_com_entrada

    def executar(
        self, *argumentos: str, prazo: float = 60.0, entrada: str | None = None
    ) -> str:
        comando = [self.binario, "--context", self.contexto, *argumentos]
        if entrada is None:
            return self._executor(comando, prazo)
        return self._executor_com_entrada(comando, prazo, entrada)

    def aplicar_json(
        self,
        manifesto: Mapping[str, Any],  # Any: JSON livre do Kubernetes
        *,
        prazo: float = 60.0,
    ) -> None:
        """``kubectl apply`` de um manifesto montado em memoria.

        O JSON viaja pelo stdin: nunca em argv, nem em arquivo. Server-side, para
        o Secret nao ganhar a anotacao ``last-applied`` com o valor dentro, e com
        ``--force-conflicts`` para assumir um Secret criado a mao antes.
        """
        self.executar(
            "apply",
            "--server-side",
            "--force-conflicts",
            "-f",
            "-",
            prazo=prazo,
            entrada=json.dumps(manifesto),
        )

    def segredo(self, namespace: str, nome: str, chave: str) -> str:
        """Valor decodificado de uma chave de Secret (quem chama o registra)."""
        bruto = self.executar(
            "-n", namespace, "get", "secret", nome, "-o", f"jsonpath={{.data.{chave}}}"
        )
        if not bruto.strip():
            msg = f"a chave {chave} nao existe no Secret {nome} de {namespace}"
            raise ErroDeComandoError(msg)
        return base64.b64decode(bruto.strip()).decode()

    def valor_de_configmap(self, namespace: str, chave: str) -> str | None:
        """Valor de ``chave`` no ConfigMap do namespace que a tem (o nome leva hash)."""
        saida = self.executar(
            "-n",
            namespace,
            "get",
            "configmap",
            "-o",
            f"jsonpath={{.items[*].data.{chave}}}",
        )
        valores = saida.split()
        return valores[0] if valores else None

    def replicas(self, namespace: str, deployment: str) -> int:
        saida = self.executar(
            "-n",
            namespace,
            "get",
            "deployment",
            deployment,
            "-o",
            "jsonpath={.spec.replicas}",
        )
        return int(saida.strip() or 0)

    def escalar(self, namespace: str, deployment: str, replicas: int) -> None:
        self.executar(
            "-n",
            namespace,
            "scale",
            f"deployment/{deployment}",
            f"--replicas={replicas}",
        )

    def pods(self, namespace: str, app: str) -> list[str]:
        saida = self.executar(
            "-n", namespace, "get", "pods", "-l", f"app={app}", "-o", "name"
        )
        return saida.split()

    def aguardar_pronto(
        self, namespace: str, deployment: str, prazo: float = 120.0
    ) -> None:
        """Espera o Deployment ficar pronto (``kubectl rollout status``)."""
        self.executar(
            "-n",
            namespace,
            "rollout",
            "status",
            f"deployment/{deployment}",
            f"--timeout={int(prazo)}s",
            prazo=prazo + 30,
        )

    def filas_mortas(self) -> dict[str, int]:
        """Mensagens em cada ``*.dlq``, por ``rabbitmqctl`` no pod do broker."""
        saida = self.executar(
            "-n",
            NAMESPACE_DA_PLATAFORMA,
            "exec",
            "rabbitmq-0",
            "-c",
            "rabbitmq",
            "--",
            "rabbitmqctl",
            "-q",
            "list_queues",
            "name",
            "messages",
            prazo=PRAZO_DAS_DLQS,
        )
        filas = ler_filas_mortas(saida)
        ausentes = [fila for fila in FILAS_MORTAS if fila not in filas]
        if ausentes:
            msg = f"o rabbitmqctl nao listou as DLQs {ausentes}: {sorted(filas)}"
            raise ErroDeComandoError(msg)
        return filas

    def ultimas_linhas(
        self, namespace: str, app: str, *, container: str, quantidade: int = 40
    ) -> str:
        """As ultimas ``quantidade`` linhas de log de cada pod do ``app``."""
        return self.executar(
            "-n", namespace, "logs", "-l", f"app={app}", "-c", container,
            f"--tail={quantidade}",
            prazo=30,
        )  # fmt: skip

    def logs(
        self, namespace: str, app: str, *, container: str, desde: str = "10m"
    ) -> str:
        """Logs dos pods do ``app`` desde ``desde``, sem corte (``--tail=-1``)."""
        return self.executar(
            "-n", namespace, "logs", "-l", f"app={app}", "-c", container,
            f"--since={desde}", "--tail=-1",
            prazo=60,
        )  # fmt: skip


class Escalas:
    """Deployments que o cenario derrubou, para o teardown devolver ao que eram."""

    def __init__(
        self,
        kubectl: Kubectl,
        *,
        relogio: Callable[[], float] = time.monotonic,
        dormir: Callable[[float], None] = time.sleep,
    ) -> None:
        self._kubectl = kubectl
        self._relogio = relogio
        self._dormir = dormir
        self._originais: dict[tuple[str, str], int] = {}

    def recuperar_do_inicio(
        self, alvos: Sequence[tuple[str, str]]
    ) -> list[tuple[str, str]]:
        """Religa os ``alvos`` que uma execucao anterior deixou em 0 replicas.

        Uma queda no meio de um cenario (maquina dormiu, processo morto) nao
        roda o teardown; sem isto a execucao seguinte falharia por causa da
        anterior. Devolve o que religou, para o log dizer.
        """
        religados = []
        for namespace, deployment in alvos:
            if self._kubectl.replicas(namespace, deployment) == 0:
                self._kubectl.escalar(namespace, deployment, 1)
                self._kubectl.aguardar_pronto(namespace, deployment)
                religados.append((namespace, deployment))
        return religados

    def zerar(self, namespace: str, deployment: str, *, prazo: float = 90.0) -> None:
        """Escala a 0 e espera o ultimo pod sair (parado de verdade, nao so pedido)."""
        chave = (namespace, deployment)
        if chave not in self._originais:
            self._originais[chave] = self._kubectl.replicas(namespace, deployment) or 1
        self._kubectl.escalar(namespace, deployment, 0)
        esperar(
            lambda: not self._kubectl.pods(namespace, deployment),
            prazo=prazo,
            intervalo=1.0,
            descricao=f"pods de {deployment} encerrados",
            relogio=self._relogio,
            dormir=self._dormir,
        )

    def restaurar(self, namespace: str, deployment: str) -> None:
        """Volta ao numero original de replicas e espera ficarem prontas."""
        original = self._originais.get((namespace, deployment))
        if original is None:
            return
        self._kubectl.escalar(namespace, deployment, original)
        # So esquece depois de escalar: uma falha do kubectl deixa o registro
        # para o teardown da sessao tentar de novo.
        del self._originais[(namespace, deployment)]
        self._kubectl.aguardar_pronto(namespace, deployment)

    def restaurar_todas(self) -> list[str]:
        """Restaura tudo o que ficou derrubado e devolve os nomes restaurados.

        Tenta todos mesmo que um falhe, e so no fim levanta um erro com as falhas
        juntas: o teardown nao deixa um Deployment em 0 por causa de outro.
        """
        nomes: list[str] = []
        falhas: list[str] = []
        for namespace, deployment in list(self._originais):
            try:
                self.restaurar(namespace, deployment)
            except ErroDeComandoError as erro:
                falhas.append(f"{deployment}: {erro}")
            else:
                nomes.append(deployment)
        if falhas:
            raise ErroDeComandoError("nao restaurei: " + "; ".join(falhas))
        return nomes


def porta_livre() -> int:
    """Porta TCP livre do loopback (o kernel escolhe)."""
    with socket.socket() as soquete:
        soquete.bind(("127.0.0.1", 0))
        return int(soquete.getsockname()[1])


class PortForward:
    """``kubectl port-forward`` de sessao para um Service, numa porta local livre."""

    def __init__(
        self, kubectl: Kubectl, namespace: str, alvo: str, porta_remota: int
    ) -> None:
        self._kubectl = kubectl
        self._namespace = namespace
        self._alvo = alvo
        self._porta_remota = porta_remota
        self.porta = porta_livre()
        self._processo: subprocess.Popen[str] | None = None
        # O stderr do kubectl vai para um arquivo: e dele a causa de um port-forward
        # que morre ("address already in use", "pods not found", "forbidden").
        self._erros: IO[str] | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.porta}"

    def iniciar(self, prazo: float = 30.0) -> PortForward:
        """Sobe o kubectl e espera a porta; se nao abre, nao deixa processo orfao."""
        self._erros = tempfile.TemporaryFile("w+")  # noqa: SIM115 - fecha em encerrar()
        self._processo = subprocess.Popen(  # noqa: S603  # nosec B603
            [
                self._kubectl.binario,
                "--context",
                self._kubectl.contexto,
                "-n",
                self._namespace,
                "port-forward",
                "--address",
                "127.0.0.1",
                self._alvo,
                f"{self.porta}:{self._porta_remota}",
            ],
            env=_ambiente_dos_filhos(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=self._erros,
            text=True,
        )
        try:
            esperar(
                self._aceita_conexao,
                prazo=prazo,
                intervalo=0.2,
                descricao=f"port-forward de {self._alvo} aceitando conexoes",
            )
        except BaseException:
            # Sem isto o kubectl que nao chegou a escutar sobrevive ao pytest.
            self.encerrar()
            raise
        return self

    def _ultimas_linhas_do_erro(self) -> str:
        if self._erros is None:
            return ""
        self._erros.seek(0)
        return mascarar(self._erros.read().strip())[-_TAMANHO_DO_ERRO:]

    def _aceita_conexao(self) -> bool:
        if self._processo is None or self._processo.poll() is not None:
            codigo = None if self._processo is None else self._processo.returncode
            msg = (
                f"o kubectl port-forward de {self._alvo} terminou (codigo {codigo}): "
                f"{self._ultimas_linhas_do_erro()}"
            )
            raise ErroDeComandoError(msg)
        try:
            with socket.create_connection(("127.0.0.1", self.porta), timeout=1):
                return True
        except OSError:
            return False

    def garantir(self) -> None:
        """Religa o port-forward se o kubectl morreu (pod reiniciado, conexao caida)."""
        if self._processo is not None and self._processo.poll() is None:
            return
        self.iniciar()

    def encerrar(self) -> None:
        """Mata o kubectl, se vivo, e fecha o arquivo do stderr."""
        processo, self._processo = self._processo, None
        erros, self._erros = self._erros, None
        try:
            if processo is None:
                return
            processo.terminate()
            try:
                processo.wait(timeout=5)
            except subprocess.TimeoutExpired:
                processo.kill()
                processo.wait(timeout=5)
        finally:
            if erros is not None:
                erros.close()

    def __enter__(self) -> PortForward:
        return self.iniciar()

    def __exit__(
        self,
        tipo: type[BaseException] | None,
        erro: BaseException | None,
        pilha: TracebackType | None,
    ) -> None:
        self.encerrar()
