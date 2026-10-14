"""Preflight do sandbox do Mercado Pago: falha rapida e em portugues, antes do cluster.

Cada recusa diz o que mudar. Nenhuma mensagem leva o token, a assinatura ou o
tamanho deles: so o nome da variavel e o que ha de errado com ela.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final

import httpx

from e2e.apoio.contexto import PREFIXO_DO_KIND
from e2e.apoio.espera import TempoEsgotadoError, esperar
from e2e.apoio.kube import ErroDeComandoError
from e2e.apoio.mercadopago import (
    ClienteMercadoPago,
    ErroDoMercadoPagoError,
    TokenRecusadoError,
)
from e2e.apoio.modo_billing import (
    MODO_REAL,
    MODO_SIMULADO,
    NAMESPACE_BILLING,
    URL_DE_NOTIFICACAO_PADRAO,
    UrlDeNotificacaoInvalidaError,
    sem_consulta,
    url_de_notificacao_valida,
)
from e2e.apoio.preflight import numero
from e2e.apoio.segredos import registrar

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, MutableMapping

    from e2e.apoio.http import ClienteHttp
    from e2e.apoio.kube import Kubectl

# Um pagamento SOLICITADO que um ensaio interrompido ou reprovado deixou no cluster
# seria conciliado no Mercado Pago de verdade (o Billing escolhe o gateway pelo modo,
# e nao pelo pagamento). Nao ha como conferir daqui; fica o aviso.
AVISO_DO_PAGAMENTO_ANTIGO: Final = (
    "[mp-sandbox] atenção: se o último ensaio foi interrompido ou reprovado, suba um "
    "cluster novo (make kind-down kind-up) antes de seguir: um pagamento SOLICITADO "
    "dele seria conciliado no Mercado Pago de verdade"
)
MODO_REAL_DO_E2E: Final = "real"
MODO_ENSAIO: Final = "ensaio"
PREFIXOS_DOS_SERVICOS: Final = ("/os", "/billing", "/execucao")
# O humano abre o link e paga: o orcamento e a cobranca precisam durar mais que
# isso. O kind-ci (orcamento de 72 s, uma recusa encerra a cobranca) nao serve.
VALIDADE_MINIMA_DO_ORCAMENTO_HORAS: Final = 1.0
VALIDADE_MINIMA_DO_PAGAMENTO_MINUTOS: Final = 15.0
RECUSAS_MINIMAS: Final = 2.0
PRAZO_DA_SAUDE: Final = 20.0
HTTP_ERRO_DE_CLIENTE: Final = 400
HTTP_ERRO_DO_SERVIDOR: Final = 500


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
CHAVES_SECRETAS: Final = ("MP_ACCESS_TOKEN", "MP_WEBHOOK_SECRET")
CHAVES_DO_SANDBOX: Final = (
    "E2E_MP_MODO",
    "E2E_MP_MANTER",
    "E2E_MP_NOTIFICATION_URL",
    *CHAVES_SECRETAS,
)


def ambiente_do_sandbox(ambiente: Mapping[str, str]) -> dict[str, str]:
    """So as chaves do sandbox, com as credenciais ja na mascara.

    As credenciais entram na mascara antes de qualquer conferencia que possa
    reprovar: um traceback com o valor, mesmo de uma variavel mal lida, sai ``***``.
    """
    recorte = {c: ambiente[c] for c in CHAVES_DO_SANDBOX if c in ambiente}
    for chave in CHAVES_SECRETAS:
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
    for nome in CHAVES_SECRETAS:
        valor = ambiente.get(nome, "")
        if not valor:
            problemas.append(
                f"{nome} não está no ambiente (leia com `read -rs {nome}` e passe "
                f'só ao make: {nome}="${nome}" make mp-sandbox; nunca na linha do make)'
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


def retirar_credenciais(ambiente: MutableMapping[str, str]) -> None:
    """Tira as credenciais do ambiente deste processo.

    Os filhos (``kubectl``, ``port-forward``) herdariam as duas variaveis sem
    precisar delas. Quem as le do shell depois e outro processo (``e2e.varredura``,
    que o ``make`` roda a parte).
    """
    for chave in CHAVES_SECRETAS:
        ambiente.pop(chave, None)


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
    saida = kubectl.executar(
        "-n", NAMESPACE_BILLING, "get", "configmap", nome, "-o", "jsonpath={.data}"
    )
    try:
        valores: Mapping[str, str] = json.loads(saida)
    except ValueError:
        msg = f"não consegui ler o ConfigMap {nome} do Billing (a saída não é JSON)"
        raise PreflightDoSandboxError(msg) from None
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
    avisar: Callable[[str], None] = print,
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
    url, origem = _url_de_notificacao(ambiente) if real else ("", "")
    try:
        max_recusas = conferir_overlay_kind(kubectl)
    except ErroDeComandoError as erro:
        msg = f"o kubectl falhou ao ler a configuração do Billing: {erro}"
        raise PreflightDoSandboxError(msg) from None
    conferir_servicos(borda, relogio=relogio, dormir=dormir)
    mercadopago = _validar_token(cliente, credenciais[0], avisar) if real else None
    if real:
        avisar(
            f"[mp-sandbox] notification_url: {sem_consulta(url)} ({origem}); "
            "a sandbox não envia notificação, então o webhook não é exercitado"
        )
        avisar(AVISO_DO_PAGAMENTO_ANTIGO)
    return Sandbox(
        modo=modo,
        token=credenciais[0],
        assinatura=credenciais[1],
        manter=real and ambiente.get("E2E_MP_MANTER") == "1",
        url_de_notificacao=url,
        max_recusas=max_recusas,
        mercadopago=mercadopago,
    )


def preflight_do_sandbox(
    kubectl: Kubectl,
    borda: ClienteHttp,
    ambiente: MutableMapping[str, str],
    **opcoes: Any,  # cliente, avisar, relogio e dormir: as injecoes dos testes
) -> Sandbox:
    """O preflight a partir do ambiente do processo, que fica sem as credenciais.

    So as chaves do sandbox seguem adiante (o ambiente inteiro nunca e argumento de
    quem pode falhar), ja na mascara; depois delas lidas, o processo as esquece.
    """
    recorte = ambiente_do_sandbox(ambiente)
    retirar_credenciais(ambiente)
    return preparar_sandbox(kubectl, borda, recorte, **opcoes)


def _url_de_notificacao(ambiente: Mapping[str, str]) -> tuple[str, str]:
    """A ``notification_url`` do modo real e de onde ela veio.

    ``E2E_MP_NOTIFICATION_URL`` conferida, ou a padrao: a do kind
    (``https://localhost/...``) e local, e o Mercado Pago manda nao usar.
    """
    url = ambiente.get("E2E_MP_NOTIFICATION_URL", "")
    if not url:
        return URL_DE_NOTIFICACAO_PADRAO, "padrão do modo real"
    try:
        return url_de_notificacao_valida(url), "E2E_MP_NOTIFICATION_URL"
    except UrlDeNotificacaoInvalidaError as erro:
        raise PreflightDoSandboxError(str(erro)) from None


def _validar_token(
    cliente: Callable[[str], ClienteMercadoPago],
    token: str,
    avisar: Callable[[str], None],
) -> ClienteMercadoPago:
    """Falha cedo se o Mercado Pago recusa o token ou nao responde.

    Um 4xx que nao seja 401 nem 403 diz que a conferencia, e nao o token, tem
    algo errado (o formato da busca): avisa e segue, para uma conferencia
    previa nao barrar uma credencial boa. A primeira chamada real diz o resto.
    """
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
        if erro.status is not None and (
            HTTP_ERRO_DE_CLIENTE <= erro.status < HTTP_ERRO_DO_SERVIDOR
        ):
            avisar(
                f"[mp-sandbox] atenção: a conferência do token respondeu {erro} "
                "e o roteiro segue sem ela; a primeira chamada real diz se o "
                "token serve"
            )
            return mercadopago
        mercadopago.fechar()
        msg = f"não consegui falar com o Mercado Pago (api.mercadopago.com): {erro}"
        raise PreflightDoSandboxError(msg) from None
    return mercadopago
