"""Diagnostico de uma falha do sandbox: o estado, o log filtrado e a causa provavel.

Quando o prazo estoura ou uma afirmacao falha, quem roda o script precisa ver, sem
abrir o kubectl, onde a OS e o pagamento pararam, o que o Billing e o Mercado Pago
disseram e o que fazer. Tudo sai mascarado, e do log so passam os campos de uma
lista: o resto de uma linha (que pode ter id de cliente ou mensagem de fora) fica.

Nada aqui pode falhar: o diagnostico roda no meio de uma falha, e uma excecao dele
esconderia a causa verdadeira. Cada fonte que nao responde vira uma linha
"(sem ...)" no texto.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final

from e2e.apoio.segredos import mascarar

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from e2e.apoio.mercadopago import PagamentoMp

LINHAS_DE_LOG: Final = 40
# Os campos do log estruturado do Billing que o diagnostico mostra. O que sobra
# da linha (id de requisicao, git_sha, trace) nao ajuda a achar a causa.
CAMPOS_DO_LOG: Final = (
    "tipo",
    "comando",
    "resultado",
    "tentativa",
    "erro",
    "codigo",
    "motivo",
    "operacao",
    "status",
    "path",
    "pagamento_id",
    "referencia",
    "message",
    "cause",
)
_TAMANHO_DO_CAMPO: Final = 160
_NIVEIS_QUE_INTERESSAM: Final = frozenset({"warning", "error", "critical"})
# O httpx do Billing loga cada chamada ao Mercado Pago em INFO, com o status.
_CHAMADA_AO_MP: Final = re.compile(
    r"HTTP Request: (?P<metodo>[A-Z]+) https://api\.mercadopago\.com(?P<caminho>/[^\s?\"]*)"
    r'[^"]*"HTTP/[\d.]+ (?P<status>\d{3})'
)
NOTIFICATION_URL_PUBLICA: Final = "https://example.com/api/v1/webhooks/mercadopago"
HTTP_ERRO: Final = 400
HTTP_ERRO_DO_SERVIDOR: Final = 500
HTTP_MUITAS_REQUISICOES: Final = 429
HTTP_RECUSA_DO_TOKEN: Final = frozenset({401, 403})
PROCESSOS_DO_BILLING: Final = (
    ("api", "billing-service-api", "api"),
    ("consumidor", "billing-service-consumidor", "consumidor"),
    ("prazos", "billing-service-prazos", "prazos"),
)


@dataclass(frozen=True)
class LinhaDeLog:
    """Uma linha do log do Billing, so com os campos da lista."""

    quando: str
    nivel: str
    evento: str
    campos: dict[str, str] = field(default_factory=dict)
    # ``POST /checkout/preferences`` -> 400, quando a linha e uma chamada ao MP.
    chamada_ao_mp: tuple[str, str, int] | None = None

    def texto(self) -> str:
        if self.chamada_ao_mp:
            metodo, caminho, status = self.chamada_ao_mp
            detalhe = f"Mercado Pago: {metodo} {caminho} respondeu {status}"
        else:
            detalhe = self.evento + "".join(
                f" {chave}={valor}" for chave, valor in self.campos.items()
            )
        return mascarar(f"{self.quando} {self.nivel:<7} {detalhe}")


def _curto(valor: object) -> str:
    return str(valor).replace("\n", " ")[:_TAMANHO_DO_CAMPO]


def _linha(bruta: str) -> LinhaDeLog | None:
    """A linha de log que interessa, ou ``None`` (ruido, texto solto, rotina)."""
    try:
        registro = json.loads(bruta)
    except ValueError:
        return None
    if not isinstance(registro, dict):
        return None
    evento = str(registro.get("event", ""))
    nivel = str(registro.get("level", ""))
    quando = str(registro.get("timestamp", ""))[11:19]
    chamada = _CHAMADA_AO_MP.search(evento)
    if chamada:
        return LinhaDeLog(
            quando,
            nivel,
            evento,
            chamada_ao_mp=(
                chamada["metodo"],
                chamada["caminho"],
                int(chamada["status"]),
            ),
        )
    status = registro.get("status")
    requisicao_com_erro = isinstance(status, int) and status >= HTTP_ERRO
    rotina = registro.get("resultado") in {"processada", "sucesso"}
    interessa = (
        nivel in _NIVEIS_QUE_INTERESSAM
        or requisicao_com_erro
        or ("erro" in registro)
        or (registro.get("resultado") is not None and not rotina)
    )
    if not interessa:
        return None
    campos = {
        campo: _curto(registro[campo])
        for campo in CAMPOS_DO_LOG
        if registro.get(campo) is not None
    }
    excecao = registro.get("exception")
    if excecao:
        campos["excecao"] = _curto(str(excecao).strip().splitlines()[-1])
    return LinhaDeLog(quando, nivel, evento, campos)


def filtrar_log(saida: str, *, ultimas: int = LINHAS_DE_LOG) -> list[LinhaDeLog]:
    """As ``ultimas`` linhas do log, so as que ajudam a achar a causa."""
    achadas = (_linha(bruta) for bruta in saida.splitlines()[-ultimas:])
    return [linha for linha in achadas if linha is not None]


@dataclass
class Sinais:
    """O que a coleta trouxe; ``None`` e fonte que nao respondeu."""

    cenario: str
    passo: str
    erro: str
    esperado: str
    real: bool
    contexto: str  # o kubectl que a dica manda rodar leva o --context do script
    estado_da_os: str | None = None
    pagamento: Mapping[str, Any] | None = None
    mercadopago: list[PagamentoMp] | None = None
    filas_mortas: Mapping[str, int] | None = None
    filas_mortas_antes: Mapping[str, int] | None = None
    logs: dict[str, list[LinhaDeLog]] = field(default_factory=dict)


def _kubectl(sinais: Sinais) -> str:
    """O inicio de um ``kubectl`` no cluster certo, e nao no contexto corrente."""
    return f"kubectl --context {sinais.contexto} -n pytstop-billing"


def _linhas_do_mp(sinais: Sinais) -> list[tuple[str, str, int]]:
    return [
        linha.chamada_ao_mp
        for linhas in sinais.logs.values()
        for linha in linhas
        if linha.chamada_ao_mp
    ]


def _eventos(sinais: Sinais, processo: str) -> list[LinhaDeLog]:
    return sinais.logs.get(processo, [])


def _criacao_recusada(sinais: Sinais, chamadas: list[tuple[str, str, int]]) -> bool:
    """O Mercado Pago respondeu 4xx a criacao da preferencia (ou o comando morreu)."""
    return any(
        metodo == "POST"
        and caminho == "/checkout/preferences"
        and HTTP_ERRO <= status < HTTP_ERRO_DO_SERVIDOR
        for metodo, caminho, status in chamadas
    ) or any(
        linha.evento == "command_dead_lettered"
        and linha.campos.get("codigo") == "GATEWAY_PAGAMENTO_RECUSOU"
        for linha in _eventos(sinais, "consumidor")
    )


def _token_recusado(sinais: Sinais, chamadas: list[tuple[str, str, int]]) -> bool:
    return any(status in HTTP_RECUSA_DO_TOKEN for _, _, status in chamadas) or any(
        linha.evento == "payment_reconciliation_refused"
        for linha in _eventos(sinais, "prazos")
    )


def _provedor_indisponivel(
    sinais: Sinais, chamadas: list[tuple[str, str, int]]
) -> bool:
    return any(
        linha.evento in {"payment_reconciliation_paused", "command_retry_scheduled"}
        for linhas in sinais.logs.values()
        for linha in linhas
    ) or any(
        status >= HTTP_ERRO_DO_SERVIDOR or status == HTTP_MUITAS_REQUISICOES
        for _, _, status in chamadas
    )


def dicas(sinais: Sinais) -> list[str]:
    """As causas provaveis, da mais especifica a mais geral; sempre ao menos uma."""
    achadas: list[str] = []
    chamadas = _linhas_do_mp(sinais)
    if _token_recusado(sinais, chamadas):
        achadas.append(
            "O Mercado Pago não aceitou o token (HTTP 401 ou 403): é de produção, de "
            "outra aplicação, está revogado ou tem espaço no fim. Leia de novo com "
            "`read -rs MP_ACCESS_TOKEN` e use o Access Token de teste da mesma conta "
            "de teste da aplicação."
        )
    elif _criacao_recusada(sinais, chamadas):
        achadas.append(
            "O Mercado Pago recusou criar a cobrança (POST /checkout/preferences "
            "com resposta 4xx). Causa mais provável: a notification_url local "
            "(https://localhost/billing/...), que a documentação do Mercado Pago "
            "manda não usar. Aponte para uma URL pública: exporte "
            f"E2E_MP_NOTIFICATION_URL={NOTIFICATION_URL_PUBLICA} e rode de novo, ou "
            f"com o modo real mantido, `{_kubectl(sinais)} set env deployment "
            f"--all MP_NOTIFICATION_URL={NOTIFICATION_URL_PUBLICA}`."
        )
    if _provedor_indisponivel(sinais, chamadas):
        achadas.append(
            "O Mercado Pago estava indisponível ou limitou as chamadas (5xx ou 429): "
            "o Billing repete sozinho. Espere um pouco e rode de novo."
        )
    rejeitados = [p for p in sinais.mercadopago or [] if p.status == "rejected"]
    aprovados = [p for p in sinais.mercadopago or [] if p.status == "approved"]
    solicitado = (sinais.pagamento or {}).get("status") == "SOLICITADO"
    if rejeitados:
        detalhe = rejeitados[-1].status_detail or "sem detalhe"
        achadas.append(
            f"O Mercado Pago recusou o pagamento ({detalhe}). Confira o nome do "
            "titular (APRO aprova; OTHE, FUND e SECU recusam), o cartão de teste da "
            "documentação, o CVV e a validade, e que o checkout foi aberto numa janela "
            "anônima com só o usuário Comprador de teste (conta real logada recusa)."
        )
    if aprovados and solicitado:
        achadas.append(
            "O pagamento está aprovado no Mercado Pago, mas o Billing ainda o vê como "
            "SOLICITADO: a conciliação do `prazos` está parada. Veja "
            f"`{_kubectl(sinais)} logs deploy/billing-service-prazos` "
            "(`conciliacao` tem de ser true)."
        )
    if sinais.mercadopago == [] and solicitado:
        achadas.append(
            "O Mercado Pago não recebeu nenhum pagamento deste link. Você pagou? Abra "
            "o link numa janela anônima, entre só com o usuário Comprador de teste e "
            "pague com o cartão de teste (nome do titular APRO)."
        )
    mortas = (sinais.filas_mortas or {}).get("billing.comandos.dlq", 0)
    antes = (sinais.filas_mortas_antes or {}).get("billing.comandos.dlq", 0)
    if mortas > antes:
        # Mensagem de uma execucao anterior nao e causa desta falha.
        a_mais = (
            ""
            if sinais.filas_mortas_antes is None
            else f" ({mortas - antes} a mais que no início do cenário)"
        )
        achadas.append(
            f"A fila billing.comandos.dlq tem {mortas} mensagem(ns){a_mais}: um "
            "comando da saga foi recusado de vez. Veja o log do consumidor abaixo."
        )
    if not achadas:
        achadas.append(
            "Sem causa óbvia nos logs. Veja o do consumidor: "
            f"`{_kubectl(sinais)} logs deploy/billing-service-consumidor --tail=50`."
        )
    return achadas


def montar(sinais: Sinais) -> str:
    """O texto do diagnostico, mascarado."""
    linhas = [
        f'==== Diagnóstico: {sinais.cenario}, passo "{sinais.passo}" ====',
        f"Falhou: {sinais.erro}",
        f"Esperado: {sinais.esperado}",
        f"OS e saga: {sinais.estado_da_os or '(sem leitura)'}",
    ]
    if sinais.pagamento is None:
        linhas.append("Pagamento no Billing: (sem leitura ou ainda não criado)")
    else:
        resumo = " ".join(
            f"{chave}={sinais.pagamento.get(chave)}"
            for chave in ("status", "recusas", "expira_em", "referencia_pagamento")
        )
        linhas.append(f"Pagamento no Billing: {resumo}")
    if sinais.real:
        if sinais.mercadopago is None:
            linhas.append("Mercado Pago: (sem leitura)")
        elif not sinais.mercadopago:
            linhas.append("Mercado Pago: nenhum pagamento com esta referência")
        else:
            linhas += [
                f"Mercado Pago: pagamento {p.id} status={p.status} "
                f"detalhe={p.status_detail} valor={p.valor} {p.moeda}"
                for p in sinais.mercadopago
            ]
    if sinais.filas_mortas is not None:
        linhas.append(f"Filas mortas: {dict(sinais.filas_mortas)}")
        if sinais.filas_mortas_antes is not None:
            linhas.append(
                f"Filas mortas no início do cenário: {dict(sinais.filas_mortas_antes)}"
            )
    for processo, registros in sinais.logs.items():
        linhas.append(f"Log do {processo} (últimas {LINHAS_DE_LOG} linhas, filtradas):")
        linhas += [f"  {registro.texto()}" for registro in registros] or [
            "  (nada que interesse)"
        ]
    linhas.append("Dica provável:")
    linhas += [f"  - {dica}" for dica in dicas(sinais)]
    return mascarar("\n".join(linhas))


def coletar[T](leitura: Callable[[], T]) -> T | None:
    """Roda uma leitura do diagnostico; a que falha vira ``None`` e nao propaga."""
    try:
        return leitura()
    except Exception:  # o diagnostico nunca esconde a falha original
        return None
