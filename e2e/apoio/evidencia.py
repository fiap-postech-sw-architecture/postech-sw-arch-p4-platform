"""Evidencia do sandbox do Mercado Pago: o que se guarda, sem nenhum segredo.

Tres regras, nesta ordem. Primeiro, lista de campos PERMITIDOS: de cada resposta
entra so o que esta numa tupla daqui (``permitidos``), nunca "tudo menos o
perigoso". Depois, os textos que vao para o disco sao varridos atras de qualquer
segredo registrado, de ``Bearer``, de ``TEST-``/``APP_USR-`` e de e-mail
(``varrer``). Por fim, achado recusa a gravacao e diz onde esta (arquivo e
linha), sem repetir o valor (``gravar``).

A sanitizacao e a varredura sao duas barreiras diferentes de proposito: a
primeira impede o campo de entrar, a segunda pega o que passou por engano.
"""

from __future__ import annotations

import base64
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from e2e.apoio.mercadopago import sem_id_da_conta
from e2e.apoio.segredos import registrados

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

# Do GET /billing/api/v1/pagamentos/{id}. Fora de proposito: checkout_url (o link
# que paga a cobranca e uma credencial) e o texto livre de estornos_automaticos.
CAMPOS_DO_PAGAMENTO: Final = (
    "id",
    "ordem_id",
    "status",
    "orcamento_id",
    "valor",
    "moeda",
    "provedor",
    "referencia_preferencia",
    "expira_em",
    "criado_em",
    "recusas",
    "referencia_pagamento",
    "confirmado_em",
    "encerrado_em",
    "motivo",
    "estornado_em",
    "motivo_estorno",
)
CAMPOS_DA_NOTIFICACAO: Final = (
    "recebida_em",
    "referencia_pagamento",
    "status_provedor",
)
# Do GET /os/api/v1/sagas/{id}: o texto livre da falha nao entra.
CAMPOS_DA_SAGA: Final = ("etapa", "motivo")
CAMPOS_DO_PASSO: Final = ("seq", "em", "de", "para", "gatilho", "comando")

FRASE_DA_SANDBOX: Final = (
    "A sandbox do Mercado Pago não envia webhook (notificação) para pagamento de "
    "teste. A confirmação do pagamento veio da conciliação do processo `prazos` "
    "do Billing, que consulta `GET /v1/payments/search?external_reference=` a "
    "cada 30 s, e não de um webhook."
)
FRASE_DO_ENSAIO: Final = (
    "ENSAIO: o pagamento foi aprovado pelo simulador do Billing e nada foi enviado "
    "ao Mercado Pago. Este arquivo prova o fluxo, o formato da evidência e o "
    "desfazer; a integração real só é provada por `make mp-sandbox`."
)
# Execucao em que nenhum pagamento chegou a ser confirmado: o resumo nao afirma
# uma confirmacao que nao houve.
FRASE_SEM_CONFIRMACAO: Final = (
    "Nenhum pagamento foi confirmado nesta execução. A sandbox do Mercado Pago "
    "não envia webhook (notificação) para pagamento de teste: quando o pagamento "
    "é confirmado, a confirmação vem da conciliação do processo `prazos` do "
    "Billing, que consulta `GET /v1/payments/search?external_reference=` a cada "
    "30 s, e não de um webhook."
)
FRASE_DO_ENSAIO_SEM_CONFIRMACAO: Final = (
    "ENSAIO: nenhum pagamento foi confirmado nesta execução, e nada foi enviado "
    "ao Mercado Pago. A integração real só é provada por `make mp-sandbox`."
)
# Estados do pagamento no Billing que so existem depois de uma confirmacao.
CONFIRMADOS: Final = frozenset({"CONFIRMADO", "ESTORNADO"})
_PADROES_DA_VARREDURA: Final = {
    "Bearer": re.compile(r"Bearer\s+\S+", re.IGNORECASE),
    "token do Mercado Pago": re.compile(r"(?:TEST|APP_USR)-[A-Za-z0-9_-]{8,}"),
    "e-mail": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+"),
    "User ID da conta vendedora (prefixo do id da preferencia)": re.compile(
        r"\b\d{6,}-[0-9a-f]{8}-[0-9a-f]{4}"
    ),
}


class EvidenciaComSegredoError(AssertionError):
    """A varredura achou algo que nao pode ir para o disco. Nada foi gravado."""


def permitidos(dados: Mapping[str, Any], campos: Iterable[str]) -> dict[str, Any]:
    """So os ``campos`` de ``dados``, na ordem da lista (campo ausente nao entra)."""
    return {campo: dados[campo] for campo in campos if campo in dados}


def pagamento_do_billing(dados: Mapping[str, Any]) -> dict[str, Any]:
    """O pagamento do Billing sem o ``checkout_url`` e com as notificacoes enxutas."""
    limpo = permitidos(dados, CAMPOS_DO_PAGAMENTO)
    if isinstance(limpo.get("referencia_preferencia"), str):
        limpo["referencia_preferencia"] = sem_id_da_conta(
            limpo["referencia_preferencia"]
        )
    limpo["notificacoes"] = [
        permitidos(notificacao, CAMPOS_DA_NOTIFICACAO)
        for notificacao in dados.get("notificacoes", [])
    ]
    return limpo


def saga_resumida(dados: Mapping[str, Any]) -> dict[str, Any]:
    """Etapa, motivo e os passos da saga, cada um so com seus campos de rastro."""
    limpa = permitidos(dados, CAMPOS_DA_SAGA)
    limpa["passos"] = [
        permitidos(passo, CAMPOS_DO_PASSO) for passo in dados.get("passos", [])
    ]
    return limpa


def _hora(texto: str) -> datetime | None:
    try:
        return datetime.fromisoformat(texto)
    except ValueError:
        return None


def transicoes_da_os(
    historico: Mapping[str, Any],
    saga: Mapping[str, Any],
    pagamento: Mapping[str, Any],
) -> list[tuple[datetime, str]]:
    """O que o servidor registrou, com a hora que ele registrou, em ordem.

    Historico da OS (mudancas de status), passos da saga (o que cada comando e
    evento fez) e as datas do pagamento no Billing. Sao as horas dos servicos, e
    nao as de quem observou: provam a ordem mesmo se o script demorou a olhar.
    """
    achados: list[tuple[datetime, str]] = []
    for mudanca in historico.get("mudancas", []):
        hora = _hora(str(mudanca.get("ocorrido_em", "")))
        if hora is not None:
            de = mudanca.get("de") or "(abertura)"
            achados.append(
                (hora, f"OS: {de} -> {mudanca.get('para')} ({mudanca.get('origem')})")
            )
    for passo in saga.get("passos", []):
        hora = _hora(str(passo.get("em", "")))
        if hora is not None:
            comando = f", envia {passo['comando']}" if passo.get("comando") else ""
            achados.append((hora, f"saga: {passo.get('gatilho')}{comando}"))
    for campo, rotulo in (
        ("criado_em", "Billing: cobrança criada (SOLICITADO)"),
        ("confirmado_em", "Billing: pagamento CONFIRMADO"),
        ("encerrado_em", "Billing: cobrança encerrada"),
        ("estornado_em", "Billing: pagamento ESTORNADO"),
    ):
        hora = _hora(str(pagamento.get(campo) or ""))
        if hora is not None:
            achados.append((hora, rotulo))
    return sorted(achados, key=lambda achado: achado[0])


@dataclass
class RegistroDoCenario:
    """O que um cenario descobriu e vai para o ``resumo.md`` e o JSON."""

    nome: str
    resultado: str = "nao executado"
    duracao: float = 0.0
    ordem_id: str = ""
    pagamento_id: str = ""
    pagamento_mp_id: str = ""
    transicoes: list[tuple[datetime, str]] = field(default_factory=list)
    billing: dict[str, Any] = field(default_factory=dict)
    mercadopago: dict[str, Any] = field(default_factory=dict)
    preferencia: dict[str, Any] = field(default_factory=dict)
    saga: dict[str, Any] = field(default_factory=dict)
    observacoes: list[str] = field(default_factory=list)

    def anotar(self, texto: str, *, agora: datetime | None = None) -> None:
        """Uma observacao do script, com a hora em que ele a fez."""
        self.transicoes.append((agora or datetime.now(UTC), f"script: {texto}"))

    def para_json(self) -> dict[str, Any]:
        return {
            "cenario": self.nome,
            "resultado": self.resultado,
            "duracao_s": round(self.duracao, 1),
            "ordem_id": self.ordem_id,
            "pagamento_id": self.pagamento_id,
            "pagamento_mercadopago_id": self.pagamento_mp_id,
            "transicoes": [
                {"hora": hora.astimezone(UTC).isoformat(), "evento": texto}
                for hora, texto in sorted(self.transicoes, key=lambda t: t[0])
            ],
            "billing": self.billing,
            "mercadopago": self.mercadopago,
            "preferencia": self.preferencia,
            "saga": self.saga,
            "observacoes": self.observacoes,
        }


def _horario(hora: datetime) -> str:
    return hora.astimezone(UTC).strftime("%H:%M:%S")


def _secao(registro: RegistroDoCenario, *, real: bool) -> list[str]:
    linhas = [
        f"## {registro.nome}",
        "",
        f"- Resultado: **{registro.resultado}**, em {registro.duracao:.0f} s",
        f"- `ordem_id`: `{registro.ordem_id or '-'}`",
        f"- `pagamento_id` (Billing): `{registro.pagamento_id or '-'}`",
        "- Id do pagamento no Mercado Pago: "
        + (f"`{registro.pagamento_mp_id}`" if registro.pagamento_mp_id else "-"),
        "",
        "Transições observadas (hora UTC, do serviço que registrou):",
        "",
        "| Hora | O que aconteceu |",
        "|---|---|",
    ]
    linhas.extend(
        f"| {_horario(hora)} | {texto} |"
        for hora, texto in sorted(registro.transicoes, key=lambda t: t[0])
    )
    if registro.mercadopago:
        linhas += ["", "Do Mercado Pago (só estes campos):", ""]
        linhas += [
            f"- `{chave}`: `{valor}`" for chave, valor in registro.mercadopago.items()
        ]
    if registro.preferencia:
        linhas += ["", "Preferência do checkout no Mercado Pago:", ""]
        linhas += [
            f"- `{chave}`: `{valor}`" for chave, valor in registro.preferencia.items()
        ]
    if not real:
        linhas += ["", "Sem consulta ao Mercado Pago (ensaio)."]
    if registro.observacoes:
        linhas += ["", "Observações:", ""]
        linhas += [f"- {texto}" for texto in registro.observacoes]
    return [*linhas, ""]


def _frase(*, real: bool, confirmou: bool) -> str:
    """A frase honesta do cabeçalho: diz como o pagamento foi confirmado, se foi."""
    if real:
        return FRASE_DA_SANDBOX if confirmou else FRASE_SEM_CONFIRMACAO
    return FRASE_DO_ENSAIO if confirmou else FRASE_DO_ENSAIO_SEM_CONFIRMACAO


def _linha_da_notificacao(url: str) -> str:
    return (
        f"- `notification_url`: `{url}` (a notificação não foi exercitada: "
        "a sandbox não envia webhook)"
    )


def gerar_resumo(
    registros: Iterable[RegistroDoCenario],
    *,
    modo: str,
    contexto: str,
    quando: datetime,
    prints: Iterable[str],
    url_de_notificacao: str = "",
) -> str:
    """O ``resumo.md``: modo, a frase honesta, os cenarios e os prints a tirar.

    ``url_de_notificacao`` (so no modo real, sem a consulta) entra no cabecalho: a
    notificacao nao foi exercitada, e o leitor tem de saber qual URL o Mercado Pago
    recebeu.
    """
    real = modo == "real"
    lista = list(registros)
    confirmou = any(r.billing.get("status") in CONFIRMADOS for r in lista)
    descricao_do_modo = (
        "real (credenciais de teste do Mercado Pago)"
        if real
        else "ensaio (simulador do Billing)"
    )
    cabecalho = [
        "# Evidência do Mercado Pago na sandbox",
        "",
        f"- Modo: **{descricao_do_modo}**",
        f"- Data: {quando.astimezone(UTC):%Y-%m-%d %H:%M} UTC",
        f"- Cluster: `{contexto}`",
        *(
            [_linha_da_notificacao(url_de_notificacao)]
            if real and url_de_notificacao
            else []
        ),
        "",
        f"> {_frase(real=real, confirmou=confirmou)}",
        "",
        (
            "| Cenário | Resultado | Duração (s) | `ordem_id` | `pagamento_id` "
            "| Pagamento no Mercado Pago |"
        ),
        "|---|---|---|---|---|---|",
    ]
    cabecalho += [
        f"| {r.nome} | {r.resultado} | {r.duracao:.0f} | `{r.ordem_id or '-'}` | "
        f"`{r.pagamento_id or '-'}` | `{r.pagamento_mp_id or '-'}` |"
        for r in lista
    ]
    corpo = [linha for r in lista for linha in ["", *_secao(r, real=real)]]
    rodape = ["", "## Prints que você tira (o script não tira)", ""]
    rodape += [f"{n}. {texto}" for n, texto in enumerate(prints, 1)]
    return "\n".join([*cabecalho, *corpo, *rodape, ""])


@dataclass(frozen=True)
class Achado:
    tipo: str
    linha: int


def varrer(texto: str, extras: Iterable[str] = ()) -> list[Achado]:
    """Onde o ``texto`` tem segredo: registrado, ``Bearer``, token do MP ou e-mail."""
    segredos = [*registrados(), *extras]
    achados: list[Achado] = []
    for numero, linha in enumerate(texto.splitlines(), 1):
        if any(segredo and segredo in linha for segredo in segredos):
            achados.append(Achado("segredo registrado", numero))
        achados.extend(
            Achado(tipo, numero)
            for tipo, padrao in _PADROES_DA_VARREDURA.items()
            if padrao.search(linha)
        )
    return achados


def _conferir(nome: str, texto: str, extras: Iterable[str]) -> None:
    # O pytest mostra os argumentos de cada frame do traceback: o texto inteiro (com o
    # que a varredura acabou de achar) nao pode aparecer.
    __tracebackhide__ = True
    achados = varrer(texto, extras)
    if achados:
        onde = ", ".join(f"linha {a.linha} ({a.tipo})" for a in achados[:10])
        msg = f"recusei gravar {nome}: achei segredo na {onde}. Nada foi gravado."
        raise EvidenciaComSegredoError(msg)


def gravar(caminho: Path, texto: str, extras: Iterable[str] = ()) -> None:
    """Grava ``texto`` em ``caminho`` se a varredura nao achar nada."""
    __tracebackhide__ = True
    _conferir(caminho.name, texto, extras)
    caminho.write_text(texto, encoding="utf-8")


def varrer_pasta(pasta: Path, extras: Iterable[str] = ()) -> dict[str, list[Achado]]:
    """Os achados de cada arquivo da ``pasta`` (so os que tem algum)."""
    return {
        str(arquivo.relative_to(pasta)): achados
        for arquivo in sorted(pasta.rglob("*"))
        if arquivo.is_file()
        and (
            achados := varrer(
                arquivo.read_text(encoding="utf-8", errors="replace"), extras
            )
        )
    }


def gravar_evidencia(
    pasta: Path,
    registros: Iterable[RegistroDoCenario],
    *,
    modo: str,
    contexto: str,
    prints: Iterable[str],
    url_de_notificacao: str = "",
    quando: datetime | None = None,
    extras: Iterable[str] = (),
) -> None:
    """``resumo.md`` e ``evidencia.json`` em ``pasta``, os dois varridos antes."""
    __tracebackhide__ = (
        True  # ``registros`` leva as observacoes, que podem ter o achado
    )
    lista = list(registros)
    resumo = gerar_resumo(
        lista,
        modo=modo,
        contexto=contexto,
        quando=quando or datetime.now(UTC),
        prints=prints,
        url_de_notificacao=url_de_notificacao,
    )
    dados = json.dumps(
        {
            "modo": modo,
            "contexto": contexto,
            "cenarios": [r.para_json() for r in lista],
        },
        indent=2,
        ensure_ascii=False,
    )
    # As duas varreduras antes de gravar qualquer um: nao fica um sem o outro.
    _conferir("resumo.md", resumo, extras)
    _conferir("evidencia.json", dados, extras)
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "resumo.md").write_text(resumo, encoding="utf-8")
    (pasta / "evidencia.json").write_text(dados + "\n", encoding="utf-8")


def principal_da_varredura(argumentos: list[str], ambiente: Mapping[str, str]) -> int:
    """``python -m e2e.varredura <pasta>``: apaga o arquivo que tem segredo.

    Roda depois do pytest, que grava o ``junit.xml`` e o ``cucumber.json`` por conta
    propria e por isso nao passa pelo ``gravar``. O processo novo nao conhece as
    senhas que o E2E gerou; conhece o token e a assinatura, que vem do ambiente do
    shell, e os padroes de credencial e de e-mail.
    """
    if len(argumentos) != 1:
        print("uso: python -m e2e.varredura <pasta dos relatorios>", file=sys.stderr)
        return 2
    pasta = Path(argumentos[0])
    extras = [
        formato
        for nome in ("MP_ACCESS_TOKEN", "MP_WEBHOOK_SECRET")
        if (valor := ambiente.get(nome))
        for formato in (valor, base64.b64encode(valor.encode()).decode())
    ]
    problemas = varrer_pasta(pasta, extras)
    for nome, achados in problemas.items():
        onde = ", ".join(f"linha {a.linha} ({a.tipo})" for a in achados[:10])
        print(f"segredo em {nome}: {onde}", file=sys.stderr)
        (pasta / nome).unlink()
    if problemas:
        print(
            "arquivos com segredo APAGADOS; nao compartilhe a pasta antes de rodar "
            "de novo.",
            file=sys.stderr,
        )
        return 1
    print(f"varredura de {pasta}: nenhum segredo")
    return 0
