"""Preflight do sandbox do Mercado Pago: falha rapida e em portugues, antes do cluster.

Cada recusa diz o que mudar. Nenhuma mensagem leva o token, a assinatura ou o
tamanho deles: so o nome da variavel e o que ha de errado com ela.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

import httpx

from e2e.apoio.contexto import PREFIXO_DO_KIND
from e2e.apoio.espera import TempoEsgotadoError, esperar
from e2e.apoio.mercadopago import (
    ClienteMercadoPago,
    ErroDoMercadoPagoError,
    TokenRecusadoError,
)
from e2e.apoio.modo_billing import (
    MODO_REAL,
    MODO_SIMULADO,
    NAMESPACE_BILLING,
    UrlDeNotificacaoInvalidaError,
    url_de_notificacao_valida,
)
from e2e.apoio.preflight import numero
from e2e.apoio.segredos import registrar

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from e2e.apoio.http import ClienteHttp
    from e2e.apoio.kube import Kubectl

MODO_REAL_DO_E2E: Final = "real"
MODO_ENSAIO: Final = "ensaio"
PREFIXOS_DOS_SERVICOS: Final = ("/os", "/billing", "/execucao")
# O humano abre o link e paga: o orcamento e a cobranca precisam durar mais que
# isso. O kind-ci (orcamento de 72 s, uma recusa encerra a cobranca) nao serve.
VALIDADE_MINIMA_DO_ORCAMENTO_HORAS: Final = 1.0
VALIDADE_MINIMA_DO_PAGAMENTO_MINUTOS: Final = 15.0
RECUSAS_MINIMAS: Final = 2.0
PRAZO_DA_SAUDE: Final = 20.0


class PreflightDoSandboxError(AssertionError):
    """O ambiente nao esta pronto para o sandbox do Mercado Pago."""


@dataclass(frozen=True)
class Sandbox:
    """O que a sessao do sandbox decidiu no preflight. O token nao aparece no repr."""

    modo: str
    token: str = field(default="", repr=False)
    assinatura: str = field(default="", repr=False)
    manter: bool = False
    url_de_notificacao: str = ""
    max_recusas: int = 3
    mercadopago: ClienteMercadoPago | None = field(default=None, repr=False)

    @property
    def real(self) -> bool:
        return self.modo == MODO_REAL_DO_E2E


# O que o sandbox le do ambiente. O pytest mostra os argumentos de cada frame no
# traceback, entao o ambiente inteiro (que tem credenciais de outras coisas) nunca
# pode ser argumento de quem pode falhar: o corte vem antes, como no guarda do contexto.
CHAVES_DO_SANDBOX: Final = (
    "E2E_MP_MODO",
    "E2E_MP_MANTER",
    "E2E_MP_NOTIFICATION_URL",
    "MP_ACCESS_TOKEN",
    "MP_WEBHOOK_SECRET",
)


def ambiente_do_sandbox(ambiente: Mapping[str, str]) -> dict[str, str]:
    """So as chaves do sandbox, com as credenciais ja na mascara.

    As credenciais entram na mascara antes de qualquer conferencia que possa
    reprovar: um traceback com o valor, mesmo de uma variavel mal lida, sai ``***``.
    """
    recorte = {c: ambiente[c] for c in CHAVES_DO_SANDBOX if c in ambiente}
    for chave in ("MP_ACCESS_TOKEN", "MP_WEBHOOK_SECRET"):
        valor = recorte.get(chave, "")
        # Tambem sem o espaco que sobra de uma leitura ruim: e o valor que o
        # Mercado Pago reconheceria, e o que outro trecho do log repetiria.
        registrar(valor)
        registrar(valor.strip())
    return recorte


def credenciais_do_ambiente(ambiente: Mapping[str, str]) -> tuple[str, str]:
    """Access Token e assinatura do webhook, registrados na mascara.

    Recusa variavel ausente, vazia ou com espaco ou quebra de linha (o ``read``
    sem ``-r`` e a colagem deixam um ``\\n`` que o Mercado Pago le como token errado).
    """
    problemas = []
    for nome in ("MP_ACCESS_TOKEN", "MP_WEBHOOK_SECRET"):
        valor = ambiente.get(nome, "")
        if not valor:
            problemas.append(
                f"{nome} não está no ambiente (leia com `read -rs {nome} && "
                f"export {nome}`, sem colar o valor no comando)"
            )
        elif any(caractere.isspace() for caractere in valor):
            problemas.append(
                f"{nome} tem espaço ou quebra de linha (leia de novo com `read -rs`)"
            )
    if problemas:
        raise PreflightDoSandboxError("; ".join(problemas))
    token, assinatura = ambiente["MP_ACCESS_TOKEN"], ambiente["MP_WEBHOOK_SECRET"]
    registrar(token)
    registrar(assinatura)
    return token, assinatura


def conferir_kind(contexto: str) -> None:
    """So kind, e sem o escape do E2E: o token vai para um Secret do cluster."""
    if not contexto.startswith(PREFIXO_DO_KIND):
        msg = (
            f"o contexto {contexto!r} não é um kind (kind-<cluster>): o sandbox grava "
            "o Access Token num Secret do cluster, e o escape "
            "E2E_CONTEXTO_NAO_DESCARTAVEL não vale aqui"
        )
        raise PreflightDoSandboxError(msg)


def configmap_do_billing(kubectl: Kubectl) -> Mapping[str, str]:
    """O ConfigMap que a API do Billing usa de verdade (o nome leva o hash).

    Ler pelo Deployment evita o ConfigMap velho que um deploy anterior deixou no
    namespace e que um ``get configmap`` generico misturaria com o atual.
    """
    nome = kubectl.executar(
        "-n",
        NAMESPACE_BILLING,
        "get",
        "deployment",
        "billing-service-api",
        "-o",
        "jsonpath={.spec.template.spec.containers[0].envFrom[0].configMapRef.name}",
    ).strip()
    if not nome:
        msg = "o Deployment billing-service-api não referencia um ConfigMap (envFrom)"
        raise PreflightDoSandboxError(msg)
    valores: Mapping[str, str] = json.loads(
        kubectl.executar(
            "-n", NAMESPACE_BILLING, "get", "configmap", nome, "-o", "jsonpath={.data}"
        )
    )
    return valores


def conferir_overlay_kind(kubectl: Kubectl) -> int:
    """O Billing esta no overlay ``kind`` (orcamento de 72 h), nao no ``kind-ci``.

    Devolve as recusas que encerram a cobranca (``PAGAMENTO_MAX_RECUSAS``).
    """
    valores = configmap_do_billing(kubectl)
    validade = numero(valores.get("ORCAMENTO_VALIDADE_HORAS"))
    pagamento = numero(valores.get("PAGAMENTO_VALIDADE_MINUTOS"))
    recusas = numero(valores.get("PAGAMENTO_MAX_RECUSAS"))
    problemas = []
    if validade is None or validade < VALIDADE_MINIMA_DO_ORCAMENTO_HORAS:
        problemas.append(
            f"o orçamento vence em {validade} h (ORCAMENTO_VALIDADE_HORAS), e você "
            "precisa de pelo menos 1 h para abrir o link e pagar"
        )
    if pagamento is None or pagamento < VALIDADE_MINIMA_DO_PAGAMENTO_MINUTOS:
        problemas.append(
            f"a cobrança vale {pagamento} min (PAGAMENTO_VALIDADE_MINUTOS), menos "
            "que os 15 min da espera"
        )
    if recusas is None or recusas < RECUSAS_MINIMAS:
        problemas.append(
            f"a primeira recusa encerra a cobrança (PAGAMENTO_MAX_RECUSAS={recusas})"
        )
    if problemas:
        msg = (
            "o Billing está com os prazos do E2E (kind-ci): "
            + "; ".join(problemas)
            + ". Use o overlay kind: make kind-up deploy e make kind-deploy em "
            "cada serviço, num cluster novo (trocar de overlay no mesmo cluster "
            "não desfaz o anterior)."
        )
        raise PreflightDoSandboxError(msg)
    return int(recusas or 0)


def conferir_servicos(
    borda: ClienteHttp,
    *,
    prazo: float = PRAZO_DA_SAUDE,
    relogio: Callable[[], float] = time.monotonic,
    dormir: Callable[[float], None] = time.sleep,
) -> str:
    """Os tres servicos respondem a saude pela borda; devolve o modo do Billing."""
    problemas: list[str] = []

    def verificar() -> str | None:
        problemas.clear()
        modo = ""
        for prefixo in PREFIXOS_DOS_SERVICOS:
            try:
                resposta = borda.pedir("GET", f"{prefixo}/api/v1/saude")
            except httpx.TransportError as erro:
                problemas.append(f"{prefixo} não respondeu ({type(erro).__name__})")
                continue
            if resposta.status_code != httpx.codes.OK:
                problemas.append(f"{prefixo} respondeu HTTP {resposta.status_code}")
            elif prefixo == "/billing":
                modo = _modo_do_billing(resposta)
                if modo not in {MODO_SIMULADO, MODO_REAL}:
                    problemas.append(f"/billing diz o modo {modo!r}")
        return None if problemas else modo

    try:
        return esperar(
            verificar,
            prazo=prazo,
            intervalo=2.0,
            descricao="servicos pela borda",
            relogio=relogio,
            dormir=dormir,
        )
    except TempoEsgotadoError:
        msg = (
            "serviços fora do ar pela borda: "
            + "; ".join(problemas)
            + '. Suba o cluster e os três serviços (README, "Subir a plataforma").'
        )
        raise PreflightDoSandboxError(msg) from None


def _modo_do_billing(resposta: httpx.Response) -> str:
    try:
        corpo = resposta.json()
    except ValueError:
        return "(sem JSON)"
    return str(corpo.get("modo", "")) if isinstance(corpo, dict) else "(sem JSON)"


def preparar_sandbox(
    kubectl: Kubectl,
    borda: ClienteHttp,
    ambiente: Mapping[str, str],
    *,
    cliente: Callable[[str], ClienteMercadoPago] = ClienteMercadoPago,
    relogio: Callable[[], float] = time.monotonic,
    dormir: Callable[[float], None] = time.sleep,
) -> Sandbox:
    """Todas as conferencias, na ordem do mais barato ao mais lento."""
    modo = ambiente.get("E2E_MP_MODO", "")
    if modo not in {MODO_REAL_DO_E2E, MODO_ENSAIO}:
        msg = (
            f"E2E_MP_MODO={modo!r}: use real (make mp-sandbox) ou ensaio "
            "(make mp-sandbox-ensaio)"
        )
        raise PreflightDoSandboxError(msg)
    conferir_kind(kubectl.contexto)
    real = modo == MODO_REAL_DO_E2E
    credenciais = credenciais_do_ambiente(ambiente) if real else ("", "")
    url = _url_de_notificacao(ambiente) if real else ""
    max_recusas = conferir_overlay_kind(kubectl)
    conferir_servicos(borda, relogio=relogio, dormir=dormir)
    mercadopago = _validar_token(cliente, credenciais[0]) if real else None
    return Sandbox(
        modo=modo,
        token=credenciais[0],
        assinatura=credenciais[1],
        manter=real and ambiente.get("E2E_MP_MANTER") == "1",
        url_de_notificacao=url,
        max_recusas=max_recusas,
        mercadopago=mercadopago,
    )


def _url_de_notificacao(ambiente: Mapping[str, str]) -> str:
    """``E2E_MP_NOTIFICATION_URL`` conferida, ou vazio se nao foi pedida."""
    url = ambiente.get("E2E_MP_NOTIFICATION_URL", "")
    if not url:
        return ""
    try:
        return url_de_notificacao_valida(url)
    except UrlDeNotificacaoInvalidaError as erro:
        raise PreflightDoSandboxError(str(erro)) from None


def _validar_token(
    cliente: Callable[[str], ClienteMercadoPago], token: str
) -> ClienteMercadoPago:
    mercadopago = cliente(token)
    try:
        mercadopago.validar_token()
    except TokenRecusadoError as erro:
        mercadopago.fechar()
        msg = (
            f"o Mercado Pago não aceita o MP_ACCESS_TOKEN (HTTP {erro.status}): use o "
            "Access Token de teste da aplicação, lido de novo com `read -rs`, e "
            "não um de produção, de outra aplicação ou com espaço no fim"
        )
        raise PreflightDoSandboxError(msg) from None
    except ErroDoMercadoPagoError as erro:
        mercadopago.fechar()
        msg = f"não consegui falar com o Mercado Pago (api.mercadopago.com): {erro}"
        raise PreflightDoSandboxError(msg) from None
    return mercadopago
