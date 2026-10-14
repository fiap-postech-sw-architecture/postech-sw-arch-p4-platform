"""Modo de pagamento do Billing no kind: liga o Mercado Pago real e desfaz no fim.

Ligar o modo real e criar o Secret ``billing-mercadopago`` com o Access Token e a
assinatura do webhook, trocar ``MP_MODE`` e ``SIMULADOR_PERMITIDO`` nos Deployments
e reiniciar. O token so passa pelo stdin do ``kubectl apply`` (o manifesto em JSON
nasce em memoria): nunca em argv, nunca em arquivo, nunca no log.

Desfazer e a metade que importa. Ele apaga o Secret, tira as variaveis dos
Deployments (valem de novo ``MP_MODE=simulado`` e ``SIMULADOR_PERMITIDO=true`` do
ConfigMap do overlay), reinicia e espera. Roda sempre que algo foi mexido, com
falha, Ctrl-C, SIGTERM ou SIGHUP no meio, e nenhum passo falho impede os seguintes.
Nao cobre ``kill -9``, queda de energia nem terminal sem sinal: ai o ensaio
(``make mp-sandbox-ensaio``) acha o que sobrou e devolve o Billing ao simulador.
"""

from __future__ import annotations

import base64
import contextlib
import ipaddress
import re
import signal
import time
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import urlsplit

import httpx

from e2e.apoio.espera import esperar
from e2e.apoio.http import RespostaInesperadaError
from e2e.apoio.segredos import mascarar, registrar

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping

    from e2e.apoio.kube import Kubectl

NAMESPACE_BILLING: Final = "pytstop-billing"
SEGREDO: Final = "billing-mercadopago"
CHAVE_DO_TOKEN: Final = "MP_ACCESS_TOKEN"  # noqa: S105 - nome da chave, nao o valor
CHAVE_DA_ASSINATURA: Final = "MP_WEBHOOK_SECRET"
MODO_REAL: Final = "mercadopago"
MODO_SIMULADO: Final = "simulado"
VARIAVEIS_DO_MODO_REAL: Final = {"MP_MODE": MODO_REAL, "SIMULADOR_PERMITIDO": "false"}
# O que o desfazer tira dos Deployments: com elas fora, valem o ConfigMap do
# overlay (MP_MODE=simulado, SIMULADOR_PERMITIDO=true) e o endereco padrao do webhook.
VARIAVEIS_A_REMOVER: Final = ("MP_MODE", "SIMULADOR_PERMITIDO", "MP_NOTIFICATION_URL")
# Os nomes das variaveis de ambiente de cada container de cada Deployment, um por linha.
NOMES_DAS_VARIAVEIS: Final = (
    "jsonpath={range .items[*]}{range .spec.template.spec.containers[*]}"
    '{range .env[*]}{.name}{"\\n"}{end}{end}{end}'
)
PRAZO_DO_ROLLOUT: Final = 300.0
PRAZO_DA_CONFERENCIA: Final = 90.0
INTERVALO_DA_CONFERENCIA: Final = 2.0
HOSTS_LOCAIS: Final = frozenset({"localhost", "127.0.0.1", "::1"})
SUFIXOS_LOCAIS: Final = (".localhost", ".local", ".internal", ".test", ".lan")
# A sandbox nao envia notificacao, entao qualquer https publico serve; a documentacao
# do Mercado Pago manda nao usar dominio local (o padrao do kind, https://localhost).
URL_DE_NOTIFICACAO_PADRAO: Final = "https://example.com/api/v1/webhooks/mercadopago"
# Cada pedaco de um IP em forma legada que o ``ipaddress`` nao le: 127.1, 0x7f.0.0.1.
_NUMERO_LEGADO: Final = re.compile(r"0x[0-9a-f]+|[0-9]+")
# Os sinais que o terminal, o kill e o fechamento da janela mandam ao script.
SINAIS_DE_INTERRUPCAO: Final = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
NAO_FECHE: Final = "Não feche o terminal e não use kill -9."


class DesfazerFalhouError(AssertionError):
    """O Billing nao voltou ao simulador sozinho: o texto traz o que rodar a mao."""


class RolloutDoBillingError(AssertionError):
    """Um Deployment do Billing nao ficou pronto, ou a API nao disse o modo esperado."""


class UrlDeNotificacaoInvalidaError(ValueError):
    """``E2E_MP_NOTIFICATION_URL`` nao serve de ``notification_url``."""


def _host_publico(host: str) -> bool:
    """Nome com ponto fora dos dominios locais, ou IP global.

    Recusa loopback, rede privada, link-local, ``0.0.0.0``, o IPv4 dentro de IPv6
    (``::ffff:127.0.0.1``), nome sem ponto e as formas legadas de IP.
    """
    host = host.rstrip(".")
    if not host or host in HOSTS_LOCAIS or host.endswith(SUFIXOS_LOCAIS):
        return False
    try:
        endereco = ipaddress.ip_address(host)
    except ValueError:
        rotulos = host.split(".")
        return len(rotulos) > 1 and not all(
            _NUMERO_LEGADO.fullmatch(rotulo) for rotulo in rotulos
        )
    if isinstance(endereco, ipaddress.IPv6Address) and endereco.ipv4_mapped:
        endereco = endereco.ipv4_mapped
    return endereco.is_global


def url_de_notificacao_valida(url: str) -> str:
    """``url`` se for https, sem usuario e de um host publico.

    A documentacao do Mercado Pago manda nao usar dominios locais na
    ``notification_url``: a variavel existe para trocar a padrao por outra
    publica, e uma local nao resolveria nada (o Mercado Pago a recusa depois, e a
    primeira tentativa real seria gasta para descobrir).
    """
    partes = urlsplit(url)
    host = (partes.hostname or "").lower()
    if partes.scheme != "https" or partes.username or not _host_publico(host):
        msg = (
            "E2E_MP_NOTIFICATION_URL precisa ser uma URL https pública, sem usuário "
            "e fora de localhost (exemplo: "
            "https://example.com/api/v1/webhooks/mercadopago)"
        )
        raise UrlDeNotificacaoInvalidaError(msg)
    return url


def sem_consulta(url: str) -> str:
    """Esquema, host e caminho: a consulta (e o que mais vier depois) nao se imprime."""
    partes = urlsplit(url)
    return f"{partes.scheme}://{partes.hostname}{partes.path}"


def _base64(valor: str) -> str:
    return base64.b64encode(valor.encode()).decode()


# Any: o manifesto e JSON do Kubernetes; so o kubectl o le.
def manifesto_do_segredo(token: str, assinatura: str) -> dict[str, Any]:
    """O Secret ``billing-mercadopago``, em JSON, so em memoria.

    Os dois valores e as formas em base64 entram na mascara antes de qualquer uso:
    um erro do ``kubectl`` que repetisse o manifesto sairia mascarado.
    """
    for valor in (token, assinatura):
        registrar(valor)
        registrar(_base64(valor))
    return {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {"name": SEGREDO, "namespace": NAMESPACE_BILLING},
        "type": "Opaque",
        "data": {
            CHAVE_DO_TOKEN: _base64(token),
            CHAVE_DA_ASSINATURA: _base64(assinatura),
        },
    }


@contextlib.contextmanager
def sem_interrupcao() -> Iterator[None]:
    """Ctrl-C, SIGTERM e SIGHUP nao interrompem o que roda aqui dentro.

    O desfazer leva um minuto ou dois (reinicia e espera os Deployments), e quem
    aperta Ctrl-C duas vezes ou fecha a janela nao pode deixar o Billing em modo
    real. Isto protege so este processo: o ``kubectl`` filho roda em sessao propria
    (``kube.executar_processo``), e por isso o Ctrl-C do terminal, que vai ao grupo
    de processos, tambem nao o alcanca. Cada comando tem prazo, entao o pior caso e
    esperar esse prazo, e nao ficar preso.
    """
    anteriores = {
        sinal: signal.signal(sinal, signal.SIG_IGN) for sinal in SINAIS_DE_INTERRUPCAO
    }
    try:
        yield
    finally:
        for sinal, tratador in anteriores.items():
            signal.signal(sinal, tratador)


def comandos_a_mao(contexto: str) -> str:
    """O mesmo desfazer em tres comandos, para quem o script nao conseguiu terminar."""
    base = f"kubectl --context {contexto} -n {NAMESPACE_BILLING}"
    variaveis = " ".join(f"{nome}-" for nome in VARIAVEIS_A_REMOVER)
    return "; ".join(
        (
            f"{base} delete secret {SEGREDO} --ignore-not-found",
            f"{base} set env deployment --all {variaveis}",
            f"{base} rollout restart deployment",
        )
    )


class ModoDoBilling:
    """Liga e desfaz o modo real. ``saude`` devolve o ``modo`` do ``/api/v1/saude``."""

    def __init__(
        self,
        kubectl: Kubectl,
        saude: Callable[[], str],
        *,
        url_de_notificacao: str = "",
        avisar: Callable[[str], None] = print,
        relogio: Callable[[], float] = time.monotonic,
        dormir: Callable[[float], None] = time.sleep,
    ) -> None:
        self._kubectl = kubectl
        self._saude = saude
        self._url_de_notificacao = url_de_notificacao
        self._avisar = avisar
        self._relogio = relogio
        self._dormir = dormir
        self._mexeu = False

    def _dizer(self, texto: str) -> None:
        """O aviso e cortesia: pipe quebrado ou terminal fechado nao aborta tudo."""
        with contextlib.suppress(OSError, ValueError):
            self._avisar(texto)

    def _executar(self, *argumentos: str) -> str:
        return self._kubectl.executar("-n", NAMESPACE_BILLING, *argumentos)

    def _deployments(self) -> list[str]:
        saida = self._executar("get", "deployment", "-o", "name")
        return [linha.split("/", 1)[-1] for linha in saida.split()]

    def _definir_variaveis(self, variaveis: Mapping[str, str]) -> None:
        self._executar(
            "set",
            "env",
            "deployment",
            "--all",
            *(f"{nome}={valor}" for nome, valor in variaveis.items()),
        )

    def _remover_variaveis(self) -> None:
        self._executar(
            "set",
            "env",
            "deployment",
            "--all",
            *(f"{nome}-" for nome in VARIAVEIS_A_REMOVER),
        )

    def _apagar_segredo(self) -> None:
        self._executar("delete", "secret", SEGREDO, "--ignore-not-found")

    def _sobras(self) -> list[str]:
        """O que o modo real deixa no cluster: o Secret e as variaveis."""
        sobras = []
        if self._executar("get", "secret", SEGREDO, "-o", "name", "--ignore-not-found"):
            sobras.append(f"o Secret {SEGREDO}")
        nomes = self._executar("get", "deployment", "-o", NOMES_DAS_VARIAVEIS).split()
        presentes = sorted(set(nomes) & set(VARIAVEIS_A_REMOVER))
        if presentes:
            sobras.append(f"as variáveis {', '.join(presentes)} nos Deployments")
        return sobras

    def _reiniciar_e_esperar(self, modo: str, *, etapa: str = "") -> None:
        """Reinicia e espera CADA Deployment e o modo da API, mesmo que um falhe.

        Junta as falhas e levanta no fim: abandonar na primeira deixaria o resto sem
        conferir, e o rollout segue no servidor de qualquer jeito.
        """
        self._executar("rollout", "restart", "deployment")
        falhas: list[str] = []
        for deployment in self._deployments():
            self._dizer(
                f"[mp-sandbox] {etapa}esperando o rollout de {deployment} "
                f"(até {PRAZO_DO_ROLLOUT / 60:g} min)"
            )
            try:
                self._kubectl.aguardar_pronto(
                    NAMESPACE_BILLING, deployment, prazo=PRAZO_DO_ROLLOUT
                )
            except AssertionError as erro:
                falhas.append(f"rollout de {deployment}: {mascarar(str(erro))}")
        try:
            self._conferir_modo(modo)
        except (AssertionError, httpx.HTTPError, LookupError, ValueError) as erro:
            falhas.append(f"/billing/api/v1/saude: {mascarar(str(erro))}")
        if falhas:
            raise RolloutDoBillingError("; ".join(falhas))

    def _conferir_modo(self, esperado: str) -> None:
        esperar(
            lambda: self._saude() == esperado,
            prazo=PRAZO_DA_CONFERENCIA,
            intervalo=INTERVALO_DA_CONFERENCIA,
            descricao=f"/billing/api/v1/saude com modo {esperado}",
            ignorar=(
                httpx.TransportError,
                RespostaInesperadaError,
                LookupError,
                ValueError,
            ),
            relogio=self._relogio,
            dormir=self._dormir,
        )

    def ligar_real(self, token: str, assinatura: str) -> None:
        """Secret, variaveis e reinicio; so volta com a API dizendo ``mercadopago``."""
        self._mexeu = True
        self._dizer("[mp-sandbox] Billing: criando o Secret e ligando o modo real")
        self._kubectl.aplicar_json(manifesto_do_segredo(token, assinatura))
        variaveis = dict(VARIAVEIS_DO_MODO_REAL)
        if self._url_de_notificacao:
            variaveis["MP_NOTIFICATION_URL"] = self._url_de_notificacao
        self._definir_variaveis(variaveis)
        self._reiniciar_e_esperar(MODO_REAL)

    def garantir_simulado(self) -> None:
        """No ensaio: o Billing tem de estar no simulador, sem Secret e sem variavel.

        Decide pelo cluster, e nao so pelo ``/saude``: um ``kill -9`` entre o
        ``apply`` do Secret e o fim do rollout deixa o Billing dizendo ``simulado``
        com o Secret e as variaveis la. Um ``E2E_MP_MANTER=1`` anterior tambem e
        desfeito. Sem sobra nenhuma, nao reinicia nada: o ensaio nao mexe na geracao
        dos Deployments a toa.
        """
        modo = self._saude()
        achados = self._sobras()
        if modo != MODO_SIMULADO:
            achados.insert(0, f"o Billing em modo {modo}")
        if not achados:
            return
        self._dizer(
            f"[mp-sandbox] o ensaio achou {'; '.join(achados)}: "
            "voltando o Billing ao simulador"
        )
        self.desfazer()

    def desfazer(self) -> None:
        """Apaga o Secret, tira as variaveis, reinicia e espera; junta as falhas."""
        falhas: list[str] = []
        with sem_interrupcao():
            self._dizer(
                "[mp-sandbox] Billing: desfazendo o modo real em 3 passos "
                f"(Secret, variáveis e reinício). {NAO_FECHE}"
            )
            passos: tuple[tuple[str, str, Callable[[], None]], ...] = (
                (
                    "1/3 apagando o Secret",
                    "apagar o Secret",
                    self._apagar_segredo,
                ),
                (
                    (
                        "2/3 tirando MP_MODE, SIMULADOR_PERMITIDO e "
                        "MP_NOTIFICATION_URL dos Deployments"
                    ),
                    "tirar as variáveis dos Deployments",
                    self._remover_variaveis,
                ),
                (
                    "3/3 reiniciando os Deployments",
                    "reiniciar e esperar o Billing",
                    lambda: self._reiniciar_e_esperar(MODO_SIMULADO, etapa="3/3 "),
                ),
            )
            for progresso, descricao, passo in passos:
                self._dizer(f"[mp-sandbox] {progresso}")
                try:
                    passo()
                except (
                    AssertionError,
                    httpx.HTTPError,
                    LookupError,
                    ValueError,
                ) as erro:
                    falhas.append(f"{descricao}: {mascarar(str(erro))}")
        if falhas:
            msg = (
                "o Billing pode ter ficado em modo real. Falhou: "
                + "; ".join(falhas)
                + f". Termine à mão: {comandos_a_mao(self._kubectl.contexto)}"
            )
            raise DesfazerFalhouError(msg)
        self._mexeu = False
        self._dizer("[mp-sandbox] Billing de volta ao simulador")

    @contextlib.contextmanager
    def sessao(
        self, *, real: bool, token: str = "", assinatura: str = "", manter: bool = False
    ) -> Iterator[None]:
        """O modo da sessao: real (e desfeito no fim) ou simulador (ensaio).

        ``manter`` so vale se o modo real foi ligado por inteiro: um ligar que
        falhou no meio e sempre desfeito.
        """
        ligado = False
        try:
            if real:
                self.ligar_real(token, assinatura)
            else:
                self.garantir_simulado()
            ligado = True
            yield
        finally:
            if self._mexeu and manter and ligado:
                self._dizer(
                    "[mp-sandbox] E2E_MP_MANTER=1: o Billing segue em modo real. "
                    "Para voltar ao simulador: make mp-sandbox-ensaio"
                )
            elif self._mexeu:
                self.desfazer()
