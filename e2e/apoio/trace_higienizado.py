"""O trace da saga na evidencia do sandbox: so o que uma lista de permissao deixa.

O Jaeger guarda tudo o que os servicos poem num span (URL com query, ids de negocio,
comando do banco, IP e pod). Aqui o trace vira um JSON NOVO, montado so com o que a
lista deixa: campo que ela nao cita nao existe na saida, e valor de tag permitida
que nao tem a forma esperada tambem nao (``TAGS_PERMITIDAS``). Nenhum texto livre
passa, nem como valor de tag, nem como nome de operacao, nem como segmento de URL.

A saida mantem as chaves que o "JSON File" da tela de busca do Jaeger le
(``data[].traceID``, ``spans[]``, ``processes{}``); ``logs`` e ``warnings`` nao
existem nela (a interface do Jaeger 1.76 trata a falta deles).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import urlsplit

from e2e.apoio.jaeger import (
    TraceIdInvalidoError,
    melhor_trace,
    servicos_do_trace,
    validar_trace_id,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from e2e.apoio.jaeger import Trace

HOST_DO_MERCADO_PAGO: Final = "api.mercadopago.com"
SERVICO_DO_BILLING: Final = "billing-service"
SEM_ID: Final = "{id}"
OPERACAO_OMITIDA: Final = "(operacao omitida)"
_PALAVRAS_POR_OPERACAO: Final = 4
_TIPOS_DE_REFERENCIA: Final = ("CHILD_OF", "FOLLOWS_FROM")

# Segmento de caminho que fica como esta: palavra fixa da rota (``ordens-de-servico``),
# a versao (``v1``) e o modelo da rota (``{pagamento_id}``). Tudo o mais (numero,
# uuid, token, placa, CPF, e-mail, qualquer coisa com maiuscula ou digito) parece id
# e vira ``{id}``: o erro vai sempre para o lado de esconder.
_PALAVRA_DE_ROTA: Final = re.compile(r"[a-z][a-z_-]{0,39}")
_VERSAO: Final = re.compile(r"v[0-9]{1,2}")
_MODELO_DE_ROTA: Final = re.compile(r"\{[a-z_]{1,30}\}")
_HOST: Final = re.compile(r"[a-z0-9.-]{1,253}")
# Nome de operacao: palavras (``publish``, ``billing.find``) e caminhos, nunca digito.
_PALAVRA_DE_OPERACAO: Final = re.compile(r"[A-Za-z][A-Za-z_.:-]{0,63}")
_SPAN_ID: Final = re.compile(r"[0-9a-f]{16}")
_ID_DO_PROCESSO: Final = re.compile(r"[A-Za-z0-9_-]{1,32}")
_NOME_DO_SERVICO: Final = re.compile(r"[A-Za-z0-9_.:-]{1,64}")
# Vira parte do nome do arquivo: so letras minusculas, digitos e hifen.
_CHAVE_DO_ARQUIVO: Final = re.compile(r"[a-z0-9-]{1,32}")

_METODO_HTTP: Final = r"GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS|CONNECT|TRACE|_OTHER"
# Exchange ou fila: palavras separadas por ponto, e o atraso do retry (``retry.15s``).
_DESTINO: Final = r"[a-z]{1,30}(?:\.(?:[a-z]{1,30}|[0-9]{1,3}s)){0,5}"


class ChaveDeArquivoInvalidaError(ValueError):
    """A chave do cenario, que entra no nome do arquivo do trace, e invalida."""


def _segmento(texto: str) -> str:
    """``texto`` se for palavra fixa, versao, modelo ou vazio; senao ``{id}``."""
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

    Cada segmento do caminho que pareca id vira ``{id}``. Caminho relativo
    (``/api/v1/ordens``) fica so como caminho. ``None`` se a URL nao e http(s) com um
    host de letras, digitos, ponto e hifen, ou se nao se le.
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
    "messaging.system": ("string", _texto(r"[a-z]{1,30}")),
    "messaging.operation": ("string", _texto(r"[a-z]{1,16}")),
    "messaging.operation.type": ("string", _texto(r"[a-z]{1,16}")),
    "messaging.destination.name": ("string", _texto(_DESTINO)),
    "db.system": ("string", _texto(r"[a-z]{1,30}")),
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
    um texto) vira ``OPERACAO_OMITIDA``.
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
    """Cada processo so com ``serviceName`` (sem host, IP, pod nem versao)."""
    limpos: dict[str, dict[str, str]] = {}
    for chave, processo in processos.items() if isinstance(processos, dict) else []:
        nome = processo.get("serviceName") if isinstance(processo, dict) else None
        if (
            _id_valido(chave, _ID_DO_PROCESSO)
            and isinstance(nome, str)
            and _NOME_DO_SERVICO.fullmatch(nome)
        ):
            limpos[chave] = {"serviceName": nome}
    return limpos


def higienizar_trace(trace: object) -> Trace | None:
    """O trace do Jaeger so com o que a lista deixa, ou ``None`` se nao presta.

    Nao presta o que nao e um trace, tem ``traceID`` fora do formato ou fica sem
    nenhum span. Nunca levanta por causa do conteudo: o que o Jaeger devolve e
    desconhecido, e a evidencia do H1 nao se repete.
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
    tambem, ``None``. O trace com a chamada vem primeiro porque e ele que o video
    precisa mostrar, mesmo que lhe falte uma das pecas.
    """
    lista = list(traces)
    com_chamada = [trace for trace in lista if chamada_ao_mercado_pago(trace)]
    return melhor_trace(com_chamada, obrigatorios=()) or melhor_trace(lista)


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
    def chamou_o_mercado_pago(self) -> bool:
        return self.trace is not None and chamada_ao_mercado_pago(self.trace)
