"""Modo de pagamento do Billing no kind: liga o Mercado Pago real e desfaz no fim.

Ligar o modo real e criar o Secret ``billing-mercadopago`` com o Access Token e a
assinatura do webhook, trocar ``MP_MODE`` e ``SIMULADOR_PERMITIDO`` nos Deployments
e reiniciar. O token so passa pelo stdin do ``kubectl apply`` (o manifesto em JSON
nasce em memoria): nunca em argv, nunca em arquivo, nunca no log.

Desfazer e a metade que importa. Ele apaga o Secret, tira as duas variaveis dos
Deployments (o ``MP_MODE=simulado`` e o ``SIMULADOR_PERMITIDO=true`` do ConfigMap
voltam a valer; deixar ``simulado`` escrito no Deployment sobreviveria ao proximo
``make kind-deploy``), reinicia e espera. Roda sempre que algo foi mexido, com
falha, Ctrl-C ou SIGTERM no meio, e nenhum passo falho impede os seguintes.
"""

from __future__ import annotations

import base64
import contextlib
import signal
import time
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import urlsplit

import httpx

from e2e.apoio.espera import esperar
from e2e.apoio.http import RespostaInesperadaError
from e2e.apoio.segredos import mascarar, registrar

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

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
PRAZO_DO_ROLLOUT: Final = 300.0
PRAZO_DA_CONFERENCIA: Final = 90.0
HOSTS_LOCAIS: Final = frozenset({"localhost", "127.0.0.1", "::1"})
SUFIXOS_LOCAIS: Final = (".localhost", ".local", ".internal", ".test", ".lan")


class DesfazerFalhouError(AssertionError):
    """O Billing nao voltou ao simulador sozinho: o texto traz o que rodar a mao."""


class UrlDeNotificacaoInvalidaError(ValueError):
    """``E2E_MP_NOTIFICATION_URL`` nao serve de ``notification_url``."""


def url_de_notificacao_valida(url: str) -> str:
    """``url`` se for https, sem usuario e fora do loopback e dos dominios locais.

    A documentacao do Mercado Pago manda nao usar dominios locais na
    ``notification_url``: a variavel existe para trocar a local (``localhost``)
    por uma publica, e uma local de novo nao resolveria nada.
    """
    partes = urlsplit(url)
    host = (partes.hostname or "").lower()
    local = host in HOSTS_LOCAIS or host.endswith(SUFIXOS_LOCAIS)
    if partes.scheme != "https" or not host or partes.username or local:
        msg = (
            "E2E_MP_NOTIFICATION_URL precisa ser uma URL https pública, sem usuário "
            "e fora de localhost (exemplo: "
            "https://example.com/api/v1/webhooks/mercadopago)"
        )
        raise UrlDeNotificacaoInvalidaError(msg)
    return url


def _base64(valor: str) -> str:
    return base64.b64encode(valor.encode()).decode()


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
    """Ctrl-C e SIGTERM nao interrompem o que roda aqui dentro.

    O desfazer leva um minuto ou dois (reinicia e espera os Deployments), e quem
    aperta Ctrl-C duas vezes nao pode deixar o Billing em modo real. Cada comando
    tem prazo, entao o pior caso e esperar esse prazo, e nao ficar preso.
    """
    anteriores = {
        sinal: signal.signal(sinal, signal.SIG_IGN)
        for sinal in (signal.SIGINT, signal.SIGTERM)
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

    def _reiniciar_e_esperar(self, modo: str) -> None:
        self._kubectl.reiniciar(NAMESPACE_BILLING)
        for deployment in self._kubectl.deployments(NAMESPACE_BILLING):
            self._kubectl.aguardar_pronto(
                NAMESPACE_BILLING, deployment, prazo=PRAZO_DO_ROLLOUT
            )
        self._conferir_modo(modo)

    def _conferir_modo(self, esperado: str) -> None:
        esperar(
            lambda: self._saude() == esperado,
            prazo=PRAZO_DA_CONFERENCIA,
            intervalo=2.0,
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
        self._avisar("[mp-sandbox] Billing: criando o Secret e ligando o modo real")
        self._kubectl.aplicar_json(manifesto_do_segredo(token, assinatura))
        variaveis = dict(VARIAVEIS_DO_MODO_REAL)
        if self._url_de_notificacao:
            variaveis["MP_NOTIFICATION_URL"] = self._url_de_notificacao
        self._kubectl.definir_variaveis(NAMESPACE_BILLING, variaveis)
        self._reiniciar_e_esperar(MODO_REAL)

    def garantir_simulado(self) -> None:
        """No ensaio: o Billing tem de estar no simulador, e so isso.

        Um modo real que sobrou (``E2E_MP_MANTER=1`` numa execucao anterior) e
        desfeito; no simulador nao se mexe em nada.
        """
        if self._saude() != MODO_SIMULADO:
            self._avisar(
                "[mp-sandbox] o Billing estava em modo real: voltando ao simulador"
            )
            self.desfazer()

    def desfazer(self) -> None:
        """Apaga o Secret, tira as variaveis, reinicia e espera; junta as falhas."""
        self._avisar("[mp-sandbox] Billing: desfazendo (Secret, variáveis e reinício)")
        falhas: list[str] = []
        with sem_interrupcao():
            passos: tuple[tuple[str, Callable[[], None]], ...] = (
                (
                    "apagar o Secret",
                    lambda: self._kubectl.apagar_segredo(NAMESPACE_BILLING, SEGREDO),
                ),
                (
                    "tirar MP_MODE e SIMULADOR_PERMITIDO dos Deployments",
                    lambda: self._kubectl.remover_variaveis(
                        NAMESPACE_BILLING, VARIAVEIS_A_REMOVER
                    ),
                ),
                (
                    "reiniciar e esperar o Billing",
                    lambda: self._reiniciar_e_esperar(MODO_SIMULADO),
                ),
            )
            for descricao, passo in passos:
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
        self._avisar("[mp-sandbox] Billing de volta ao simulador")

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
                self._avisar(
                    "[mp-sandbox] E2E_MP_MANTER=1: o Billing segue em modo real. "
                    "Para voltar ao simulador: make mp-sandbox-ensaio"
                )
            elif self._mexeu:
                self.desfazer()
