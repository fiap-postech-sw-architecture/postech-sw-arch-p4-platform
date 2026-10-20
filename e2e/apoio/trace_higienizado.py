"""O trace da saga na evidencia do sandbox: so o que uma lista de permissao deixa.

O Jaeger guarda tudo o que os servicos poem num span (URL com query, ids de negocio,
comando do banco, IP e pod). Aqui o trace vira um JSON NOVO, montado so com o que a
lista deixa: campo que ela nao cita nao existe na saida, e valor de tag permitida
que nao tem a forma esperada tambem nao (``TAGS_PERMITIDAS``).

Onde o vocabulario e fechado o valor e uma enumeracao: ``span.kind``, ``db.system``,
``messaging.system``, ``messaging.operation`` e ``messaging.operation.type``, o
verbo HTTP, o nome do servico e o host da URL. Onde nao e (segmento de caminho,
modelo de rota, nome de fila e nome de span), so a FORMA e conferida: digito, simbolo,
``@``, query e fragmento nao passam, mas uma palavra em letras passa, mesmo que seja
um nome de pessoa. Esta etapa e a segunda barreira: os servicos ja redigem o dado na
origem (URL pelo template da rota, ``REDACTED`` no resto, sem o comando do banco).

A saida mantem as chaves que a aba "Upload" da tela de busca do Jaeger 1.76 le (a
"JSON File" das versoes antigas): ``data[].traceID``, ``spans[]`` e ``processes{}``.
``logs`` e ``warnings`` nao existem nela (a interface trata a falta deles).
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import urlsplit

from e2e.apoio.espera import TempoEsgotadoError, esperar
from e2e.apoio.jaeger import (
    SERVICOS,
    TraceIdInvalidoError,
    melhor_trace,
    servicos_do_trace,
    validar_trace_id,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from e2e.apoio.jaeger import Trace

# O trace da ordem no Jaeger e lido no fim do cenario: os spans chegam em lote, e o
# Jaeger os guarda so na memoria. O trace que nao aparece nao reprova o cenario (o
# pagamento e a prova principal): o resumo diz que nao o achou.
PRAZO_DO_TRACE: Final = 30.0
INTERVALO_DO_TRACE: Final = 3.0
# Motivo do cenario que o Ctrl-C parou no meio da espera pelo trace.
INTERROMPIDO: Final = "interrompido"
# Motivo do trace que a varredura de segredos achou algo e por isso nao foi gravado.
DESCARTADO: Final = "descartado pela varredura de segredos"
HOST_DO_MERCADO_PAGO: Final = "api.mercadopago.com"
SERVICO_DO_BILLING: Final = "billing-service"
SEM_ID: Final = "{id}"
HOST_OCULTO: Final = "REDACTED"
OPERACAO_OMITIDA: Final = "(operacao omitida)"
_PALAVRAS_POR_OPERACAO: Final = 4
_TIPOS_DE_REFERENCIA: Final = ("CHILD_OF", "FOLLOWS_FROM")
_NAMESPACE_DO_SERVICO: Final = {
    "os-service": "pytstop-os",
    "billing-service": "pytstop-billing",
    "execution-service": "pytstop-execucao",
}
# Os unicos hosts que ficam numa URL: o do Mercado Pago e os dos tres servicos, pelo
# nome curto ou pelo DNS do Service no cluster. Outro (IP de pod, nome de maquina, um
# CPF num rotulo) vira ``REDACTED``, como os servicos ja gravam na origem.
HOSTS_VISIVEIS: Final = frozenset(
    {
        HOST_DO_MERCADO_PAGO,
        *_NAMESPACE_DO_SERVICO,
        *(
            f"{servico}.{namespace}.svc.cluster.local"
            for servico, namespace in _NAMESPACE_DO_SERVICO.items()
        ),
    }
)

# Segmento de caminho que fica como esta: palavra da rota (``ordens-de-servico``), a
# versao (``v1``) e o modelo da rota (``{pagamento_id}``). Nao ha lista fechada de
# palavras: qualquer palavra em minusculas passa, inclusive um nome de pessoa. O que
# tem digito, maiuscula ou simbolo (numero, uuid, token, placa, CPF, e-mail) parece id
# e vira ``{id}``: o erro vai sempre para o lado de esconder.
_PALAVRA_DE_ROTA: Final = re.compile(r"[a-z][a-z_-]{0,39}")
_VERSAO: Final = re.compile(r"v[0-9]{1,2}")
_MODELO_DE_ROTA: Final = re.compile(r"\{[a-z_]{1,30}\}")
# So a forma de um host (letras, digitos, ponto e hifen); quem fica e o que a
# ``HOSTS_VISIVEIS`` cita.
_HOST: Final = re.compile(r"[a-z0-9.-]{1,253}")
# Nome de operacao: palavras (``publish``, ``billing.find``) e caminhos, nunca digito.
_PALAVRA_DE_OPERACAO: Final = re.compile(r"[A-Za-z][A-Za-z_.:-]{0,63}")
_SPAN_ID: Final = re.compile(r"[0-9a-f]{16}")
# A chave do processo no Jaeger e ``p<numero>``.
_ID_DO_PROCESSO: Final = re.compile(r"p[0-9]{1,4}")
# Vira parte do nome do arquivo: so letras minusculas, digitos e hifen.
_CHAVE_DO_ARQUIVO: Final = re.compile(r"[a-z0-9-]{1,32}")

_METODO_HTTP: Final = r"GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS|CONNECT|TRACE|_OTHER"
_OPERACAO_DE_MENSAGEM: Final = r"publish|send|receive|process|deliver|create|settle"
# Exchange ou fila: palavras separadas por ponto, e o atraso do retry (``retry.15s``).
# Sem lista fechada de nomes: passa qualquer sequencia de palavras em minusculas.
_DESTINO: Final = r"[a-z]{1,30}(?:\.(?:[a-z]{1,30}|[0-9]{1,3}s)){0,5}"


class ChaveDeArquivoInvalidaError(ValueError):
    """A chave do cenario, que entra no nome do arquivo do trace, e invalida."""


def _segmento(texto: str) -> str:
    """``texto`` se for palavra, versao, modelo ou vazio; senao ``{id}``."""
    fixo = texto == "" or any(
        padrao.fullmatch(texto)
        for padrao in (_PALAVRA_DE_ROTA, _VERSAO, _MODELO_DE_ROTA)
    )
    return texto if fixo else SEM_ID


def _caminho(texto: str) -> str | None:
    """O caminho sem query nem fragmento e com cada segmento que pareca id em ``{id}``.

    ``None`` se nao comeca por barra: nao e um caminho.
    """
    caminho = re.split(r"[?#]", texto, maxsplit=1)[0]
    if not caminho.startswith("/"):
        return None
    return "/" + "/".join(_segmento(segmento) for segmento in caminho[1:].split("/"))


def url_reduzida(url: str) -> str | None:
    """``esquema://host[:porta]/caminho``, sem usuario, query nem fragmento.

    O host so fica se for um de ``HOSTS_VISIVEIS``; senao vira ``REDACTED``, e a porta
    sai com ele. Cada segmento do caminho que pareca id vira ``{id}``. Caminho
    relativo (``/api/v1/ordens``) fica so como caminho. ``None`` se a URL nao e http(s)
    com um host de letras, digitos, ponto e hifen, ou se nao se le.
    """
    if url.startswith("/"):
        return _caminho(url)
    try:
        partes = urlsplit(url)
        host, porta = partes.hostname, partes.port
    except ValueError:
        return None
    if partes.scheme not in ("http", "https") or not host or not _HOST.fullmatch(host):
        return None
    # Depois de ``//host`` o caminho vazio ou comeca por barra; vazio fica sem caminho.
    caminho = _caminho(partes.path) or ""
    if host not in HOSTS_VISIVEIS:
        host, porta = HOST_OCULTO, None
    return f"{partes.scheme}://{host}{'' if porta is None else f':{porta}'}{caminho}"


def _texto(regex: str) -> Callable[[object], str | None]:
    """Validador de um valor de texto que tem de casar inteiro com ``regex``."""
    padrao = re.compile(regex)

    def validar(valor: object) -> str | None:
        return valor if isinstance(valor, str) and padrao.fullmatch(valor) else None

    return validar


def _codigo_http(valor: object) -> int | None:
    if isinstance(valor, int) and not isinstance(valor, bool) and 100 <= valor <= 599:
        return valor
    return None


def _verdadeiro(valor: object) -> bool | None:
    return True if valor is True else None


def _rota(valor: object) -> str | None:
    return _caminho(valor) if isinstance(valor, str) else None


def _url(valor: object) -> str | None:
    return url_reduzida(valor) if isinstance(valor, str) else None


def _host_do_mercado_pago(valor: object) -> str | None:
    """O host so se for o do Mercado Pago, por igualdade (nada de ``endswith``)."""
    if isinstance(valor, str) and valor.lower() == HOST_DO_MERCADO_PAGO:
        return HOST_DO_MERCADO_PAGO
    return None


# A LISTA DE PERMISSAO: chave da tag -> (tipo no JSON do Jaeger, validador do valor).
# O validador devolve o valor limpo, ou ``None`` e a tag sai. Tag fora daqui sai,
# qualquer que seja o valor.
TAGS_PERMITIDAS: Final[dict[str, tuple[str, Callable[[object], object]]]] = {
    "span.kind": ("string", _texto(r"client|server|producer|consumer|internal")),
    "http.method": ("string", _texto(_METODO_HTTP)),
    "http.request.method": ("string", _texto(_METODO_HTTP)),
    "http.status_code": ("int64", _codigo_http),
    "http.response.status_code": ("int64", _codigo_http),
    "http.route": ("string", _rota),
    "http.url": ("string", _url),
    "url.full": ("string", _url),
    "server.address": ("string", _host_do_mercado_pago),
    "otel.status_code": ("string", _texto(r"OK|ERROR|UNSET")),
    "error": ("bool", _verdadeiro),
    "messaging.system": ("string", _texto(r"rabbitmq")),
    "messaging.operation": ("string", _texto(_OPERACAO_DE_MENSAGEM)),
    "messaging.operation.type": ("string", _texto(_OPERACAO_DE_MENSAGEM)),
    "messaging.destination.name": ("string", _texto(_DESTINO)),
    "db.system": ("string", _texto(r"postgresql|mongodb")),
}


def _tags(tags: object) -> list[dict[str, Any]]:
    limpas: list[dict[str, Any]] = []
    for tag in tags if isinstance(tags, list) else []:
        chave = tag.get("key") if isinstance(tag, dict) else None
        regra = TAGS_PERMITIDAS.get(chave) if isinstance(chave, str) else None
        if regra is None:
            continue
        tipo, validar = regra
        valor = validar(tag.get("value"))
        if valor is not None and tag.get("type") == tipo:
            limpas.append({"key": chave, "type": tipo, "value": valor})
    return limpas


def _operacao(nome: object) -> str:
    """O nome do span (``POST /api/v1/{id}``, ``publish PagamentoConfirmado``).

    Passa so o que tem a forma de um nome de operacao: de 1 a 4 palavras separadas por
    espaco, cada uma uma palavra sem digito ou um caminho. O resto (uma consulta SQL,
    um texto com digito ou simbolo) vira ``OPERACAO_OMITIDA``. Nao ha lista de palavras:
    "Joao da Silva" passa.
    """
    palavras: list[str] = []
    for parte in nome.split(" ") if isinstance(nome, str) else []:
        if parte.startswith("/"):
            limpa = _caminho(parte)
        else:
            limpa = parte if _PALAVRA_DE_OPERACAO.fullmatch(parte) else None
        if limpa is None:
            return OPERACAO_OMITIDA
        palavras.append(limpa)
    return (
        " ".join(palavras)
        if 1 <= len(palavras) <= _PALAVRAS_POR_OPERACAO
        else OPERACAO_OMITIDA
    )


def _id_valido(valor: object, padrao: re.Pattern[str]) -> bool:
    return isinstance(valor, str) and bool(padrao.fullmatch(valor))


def _trace_id(valor: object) -> str | None:
    try:
        return validar_trace_id(valor) if isinstance(valor, str) else None
    except TraceIdInvalidoError:
        return None


def _referencias(referencias: object) -> list[dict[str, str]]:
    limpas: list[dict[str, str]] = []
    for ref in referencias if isinstance(referencias, list) else []:
        if (
            isinstance(ref, dict)
            and ref.get("refType") in _TIPOS_DE_REFERENCIA
            and _trace_id(ref.get("traceID")) is not None
            and _id_valido(ref.get("spanID"), _SPAN_ID)
        ):
            limpas.append(
                {
                    "refType": ref["refType"],
                    "traceID": ref["traceID"],
                    "spanID": ref["spanID"],
                }
            )
    return limpas


def _inteiro(valor: object) -> bool:
    return isinstance(valor, int) and not isinstance(valor, bool) and valor >= 0


def _span(
    span: object, trace_id: str, processos: dict[str, Any]
) -> dict[str, Any] | None:
    """O span so com o que a lista deixa; ``None`` se lhe falta o que o Jaeger exige."""
    if not isinstance(span, dict):
        return None
    processo = span.get("processID")
    if not (
        _id_valido(span.get("spanID"), _SPAN_ID)
        and span.get("traceID") == trace_id
        and isinstance(processo, str)
        and processo in processos
        and _inteiro(span.get("startTime"))
        and _inteiro(span.get("duration"))
    ):
        return None
    return {
        "traceID": trace_id,
        "spanID": span["spanID"],
        "operationName": _operacao(span.get("operationName")),
        "references": _referencias(span.get("references")),
        "startTime": span["startTime"],
        "duration": span["duration"],
        "tags": _tags(span.get("tags")),
        "processID": processo,
    }


def _processos(processos: object) -> dict[str, dict[str, str]]:
    """Cada processo so com ``serviceName`` (sem host, IP, pod nem versao).

    So fica o processo de chave ``p<numero>`` e de um dos servicos da saga. O span dos
    outros sai tambem: a interface do Jaeger recusa o arquivo inteiro se um span aponta
    para um processo que nao existe.
    """
    limpos: dict[str, dict[str, str]] = {}
    for chave, processo in processos.items() if isinstance(processos, dict) else []:
        nome = processo.get("serviceName") if isinstance(processo, dict) else None
        if (
            _id_valido(chave, _ID_DO_PROCESSO)
            and isinstance(nome, str)
            and nome in SERVICOS
        ):
            limpos[chave] = {"serviceName": nome}
    return limpos


def higienizar_trace(trace: object) -> Trace | None:
    """O trace do Jaeger so com o que a lista deixa, ou ``None`` se nao presta.

    Nao presta o que nao e um trace, tem ``traceID`` fora do formato ou fica sem
    nenhum span. Nunca levanta por causa do conteudo: o que o Jaeger devolve e
    desconhecido, e a evidencia do ``make mp-sandbox`` nao se repete (exige pagar de
    novo no navegador).
    """
    if not isinstance(trace, dict):
        return None
    trace_id = _trace_id(trace.get("traceID"))
    if trace_id is None:
        return None
    processos = _processos(trace.get("processes"))
    brutos = trace.get("spans")
    spans = [
        limpo
        for bruto in (brutos if isinstance(brutos, list) else [])
        if (limpo := _span(bruto, trace_id, processos)) is not None
    ]
    if not spans:
        return None
    return {"traceID": trace_id, "spans": spans, "processes": processos}


def _tags_do_span(span: dict[str, Any]) -> dict[str, Any]:
    return {tag["key"]: tag["value"] for tag in span["tags"]}


def _chamada_ao_host(span: dict[str, Any]) -> bool:
    tags = _tags_do_span(span)
    if tags.get("span.kind") != "client":
        return False
    return tags.get("server.address") == HOST_DO_MERCADO_PAGO or any(
        urlsplit(str(tags.get(chave, ""))).hostname == HOST_DO_MERCADO_PAGO
        for chave in ("http.url", "url.full")
    )


def chamada_ao_mercado_pago(trace: Trace) -> bool:
    """O Billing tem span CLIENT para ``api.mercadopago.com`` neste trace.

    Espera um trace que ja passou por ``higienizar_trace``: so olha o que a lista
    deixou na saida, e por isso o que o resumo afirma e o que o arquivo mostra.
    """
    do_billing = {
        processo
        for processo, dados in trace["processes"].items()
        if dados["serviceName"] == SERVICO_DO_BILLING
    }
    return any(
        span["processID"] in do_billing and _chamada_ao_host(span)
        for span in trace["spans"]
    )


def escolher_trace(traces: Iterable[Trace]) -> Trace | None:
    """O trace da evidencia: entre os com a chamada ao Mercado Pago, o de mais spans.

    Sem nenhum deles, o melhor trace das tres pecas (``melhor_trace``); sem este
    tambem, o de mais spans, mesmo que falte um servico (o Jaeger recebe os spans em
    lote, e um parcial ainda mostra a saga); sem trace nenhum, ``None``. O trace com a
    chamada vem primeiro porque e ele que o video precisa mostrar, mesmo parcial.
    """
    lista = list(traces)
    com_chamada = [trace for trace in lista if chamada_ao_mercado_pago(trace)]
    return (
        melhor_trace(com_chamada, obrigatorios=())
        or melhor_trace(lista)
        or melhor_trace(lista, obrigatorios=())
    )


def nome_do_arquivo(chave: str, trace_id: str) -> str:
    """``trace-<chave>-<traceID>.json``, so com minusculas, digitos, hifen e hexa.

    Nao muda de pasta nem de extensao, qualquer que seja o que o Jaeger devolveu.
    """
    if not _CHAVE_DO_ARQUIVO.fullmatch(chave):
        msg = f"chave do cenario fora do formato do nome do arquivo: {chave[:40]!r}"
        raise ChaveDeArquivoInvalidaError(msg)
    return f"trace-{chave}-{validar_trace_id(trace_id)}.json"


def arquivo_do_trace(chave: str, trace: Trace) -> tuple[str, str]:
    """``(nome, texto)`` do arquivo do trace, no formato do upload do Jaeger."""
    nome = nome_do_arquivo(chave, str(trace["traceID"]))
    texto = json.dumps({"data": [trace]}, indent=2, ensure_ascii=False)
    return nome, texto + "\n"


@dataclass(frozen=True)
class TraceDoCenario:
    """O trace de um cenario na evidencia: higienizado, ou ``None`` se nao apareceu."""

    chave: str
    trace: Trace | None = None
    # Por que nao apareceu, quando se sabe (o nome do erro, nunca a mensagem).
    motivo: str = ""

    @property
    def arquivo(self) -> str | None:
        """O nome do arquivo, ou ``None`` se nao ha trace para guardar."""
        if self.trace is None:
            return None
        return nome_do_arquivo(self.chave, str(self.trace["traceID"]))

    @property
    def servicos(self) -> list[str]:
        return sorted(servicos_do_trace(self.trace or {}))

    @property
    def servicos_ausentes(self) -> list[str]:
        """Os servicos da saga que faltam no trace (todos, se nao ha trace)."""
        return sorted(set(SERVICOS) - set(self.servicos))

    @property
    def chamou_o_mercado_pago(self) -> bool:
        return self.trace is not None and chamada_ao_mercado_pago(self.trace)


class _Leitura:
    """Uma leitura do Jaeger por chamada, e o que as anteriores mostraram."""

    def __init__(self, ler: Callable[[], Iterable[object]], *, real: bool) -> None:
        self._ler = ler
        self._real = real
        self._anterior: tuple[str, int] | None = None
        self.melhor: Trace | None = None
        self.erro = ""

    def __call__(self) -> Trace | None:
        """O trace, se duas leituras seguidas o trazem com o mesmo id e os mesmos spans.

        No modo real so conta o que tem a chamada do Billing ao Mercado Pago, e no
        ensaio, o que tem os tres servicos: o parcial fica como o melhor visto, se o
        prazo acabar. ``erro`` e o da ultima leitura: uma que respondeu o apaga.
        """
        try:
            traces = [t for bruto in self._ler() if (t := higienizar_trace(bruto))]
        except Exception as falha:  # o Jaeger fora do ar nao reprova o cenario
            self.erro = type(falha).__name__
            return None
        self.erro = ""
        trace = escolher_trace(traces)
        if trace is None:
            return None
        visto = (str(trace["traceID"]), len(trace["spans"]))
        pronto = visto == self._anterior and (
            chamada_ao_mercado_pago(trace)
            if self._real
            else set(SERVICOS) <= servicos_do_trace(trace)
        )
        self._anterior, self.melhor = visto, trace
        return trace if pronto else None


def esperar_trace(
    ler: Callable[[], Iterable[object]],
    *,
    chave: str,
    real: bool,
    relogio: Callable[[], float] = time.monotonic,
    dormir: Callable[[float], None] = time.sleep,
) -> TraceDoCenario:
    """O trace da ordem, higienizado, quando ele para de crescer.

    Vale o trace que duas leituras seguidas trazem com os mesmos spans; no modo real,
    so o que tem a chamada do Billing ao Mercado Pago (que o video precisa mostrar).
    Se ``PRAZO_DO_TRACE`` acaba antes, fica o melhor trace que se viu. Nao levanta por
    causa do Jaeger: fora do ar, ele nao reprova o cenario, e o nome do erro (nunca a
    mensagem) vai para o resumo. O ``KeyboardInterrupt`` passa direto, para quem
    chama registrar o ``INTERROMPIDO``.
    """
    leitura = _Leitura(ler, real=real)
    achado: Trace | None
    try:
        achado = esperar(
            leitura,
            prazo=PRAZO_DO_TRACE,
            intervalo=INTERVALO_DO_TRACE,
            descricao="trace da ordem no Jaeger",
            relogio=relogio,
            dormir=dormir,
        )
    except TempoEsgotadoError:
        achado = leitura.melhor
    if achado is not None:
        return TraceDoCenario(chave, achado)
    motivo = (
        f"erro ao consultar o Jaeger: {leitura.erro}"
        if leitura.erro
        else f"nenhum trace da ordem no Jaeger em {PRAZO_DO_TRACE:g} s"
    )
    return TraceDoCenario(chave, None, motivo)
