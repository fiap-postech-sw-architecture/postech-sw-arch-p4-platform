"""O que depende de uma pessoa: as instrucoes de pagamento e a espera por ele.

No modo real, quem paga no checkout do Mercado Pago e o dono do projeto, num
navegador. O script imprime o link e o que fazer, e espera o Billing confirmar o
pagamento (a conciliacao do processo ``prazos``, ate 30 s depois), com a contagem
regressiva e o aviso de cada tentativa recusada. No ensaio, o simulador do Billing
paga no lugar dele e a espera e curta.
"""

from __future__ import annotations

import contextlib
import time
from typing import TYPE_CHECKING, Any, Final

import httpx

from e2e.apoio.espera import esperar
from e2e.apoio.http import RespostaInesperadaError

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

PRAZO_DO_PAGAMENTO: Final = 15 * 60.0
INTERVALO_DO_PAGAMENTO: Final = 5.0
PRAZO_NO_ENSAIO: Final = 60.0
INTERVALO_NO_ENSAIO: Final = 1.0
AVISO_A_CADA: Final = 30.0
# Encerrado sem pagamento: esperar mais nao muda nada.
ENCERRADOS: Final = frozenset({"RECUSADO", "EXPIRADO", "CANCELADO", "ESTORNADO"})
CARTAO_DE_TESTE: Final = (
    "Mastercard crédito 5480 8328 0103 3311, CVV 123, validade 11/30, "
    "nome do titular APRO, CPF 12345678909"
)


class CobrancaEncerradaError(AssertionError):
    """A cobranca terminou sem pagamento; esperar nao adianta."""


def falar(texto: str) -> None:
    """Diz ``texto`` a quem roda o script; sem terminal (a janela fechou), a ninguem.

    Um ``print`` para o terminal que sumiu levanta ``OSError``, e no desmonte de um
    cenario interrompido essa excecao tomaria o lugar da interrupcao: o cenario
    constaria como falho.
    """
    with contextlib.suppress(OSError):
        print(texto, flush=True)


def formatar_restante(segundos: float) -> str:
    """``14 min 05 s`` ou ``45 s``."""
    inteiro = max(int(segundos), 0)
    minutos, resto = divmod(inteiro, 60)
    return f"{minutos} min {resto:02d} s" if minutos else f"{resto} s"


def instrucoes_de_pagamento(
    *, link: str, valor: str, moeda: str, numero: int, total: int
) -> str:
    """O quadro que o dono do projeto segue para pagar a cobranca no navegador."""
    barra = "=" * 72
    return "\n".join(
        [
            barra,
            (
                f"PAGAMENTO {numero} de {total}: pague no Mercado Pago "
                "(sandbox, sem dinheiro de verdade)"
            ),
            f"  Valor: {moeda} {valor}",
            "  1. Abra uma JANELA ANÔNIMA do navegador.",
            (
                "  2. Entre no Mercado Pago só com o usuário COMPRADOR de teste "
                "(nunca a sua conta real)."
            ),
            "     Se pedir código de verificação, use o da tabela de contas de teste",
            (
                '     (coluna "Código de verificação") ou os 6 últimos dígitos do '
                "User ID da conta."
            ),
            "  3. Abra este link de pagamento:",
            f"     {link}",
            f"  4. Pague com o cartão de teste: {CARTAO_DE_TESTE}.",
            (
                "  5. Volte ao terminal. A conciliação do Billing confirma o "
                "pagamento em até 30 s."
            ),
            (
                f"  Você tem {int(PRAZO_DO_PAGAMENTO // 60)} min. Ctrl-C cancela e o "
                "script desfaz o modo real."
            ),
            barra,
        ]
    )


def _aviso_da_recusa(recusas: int, max_recusas: int) -> str:
    return (
        f"O Mercado Pago recusou a tentativa de pagamento ({recusas} de "
        f"{max_recusas}). Confira o nome do titular (APRO aprova), o cartão "
        "de teste e se está na janela anônima com o usuário Comprador de teste."
    )


def _confirmado_ou_encerrado(
    pagamento: Mapping[str, Any], recusas: int, max_recusas: int
) -> Mapping[str, Any] | None:
    """O pagamento se ``CONFIRMADO``; erro se a cobranca acabou sem ser paga."""
    if pagamento["status"] == "CONFIRMADO":
        return pagamento
    if pagamento["status"] in ENCERRADOS:
        msg = (
            f"a cobrança terminou {pagamento['status']} sem ser paga "
            f"(motivo: {pagamento.get('motivo')}, "
            f"recusas: {recusas} de {max_recusas})"
        )
        raise CobrancaEncerradaError(msg)
    return None


def esperar_pagamento(  # Any: o JSON do Billing; so status, recusas e motivo sao lidos
    ler: Callable[[], Mapping[str, Any]],
    *,
    prazo: float,
    intervalo: float,
    max_recusas: int,
    avisar: Callable[[str], None] = falar,
    relogio: Callable[[], float] = time.monotonic,
    dormir: Callable[[float], None] = time.sleep,
) -> Mapping[str, Any]:
    """Espera o pagamento do Billing ficar ``CONFIRMADO``; devolve o pagamento.

    ``ler`` e o ``GET /billing/api/v1/pagamentos/{id}``. Cobranca encerrada sem
    pagamento (recusada, expirada, cancelada) reprova na hora, e cada tentativa
    recusada pelo Mercado Pago e avisada quando aparece.
    """
    visto: dict[str, Any] = {"status": "?", "recusas": 0}
    ultimo_aviso: list[float] = []

    def confirmado() -> Mapping[str, Any] | None:
        pagamento = ler()
        recusas = int(pagamento.get("recusas") or 0)
        if recusas > visto["recusas"]:
            avisar(_aviso_da_recusa(recusas, max_recusas))
        visto.update(status=pagamento["status"], recusas=recusas)
        return _confirmado_ou_encerrado(pagamento, recusas, max_recusas)

    def contagem(restante: float, _visto: object) -> None:
        if not ultimo_aviso or ultimo_aviso[-1] - restante >= AVISO_A_CADA:
            ultimo_aviso.append(restante)
            avisar(
                f"aguardando o pagamento: restam {formatar_restante(restante)} "
                f"(Billing: {visto['status']}, "
                f"recusas {visto['recusas']} de {max_recusas})"
            )

    return esperar(
        confirmado,
        prazo=prazo,
        intervalo=intervalo,
        descricao="pagamento CONFIRMADO no Billing",
        ignorar=(httpx.TransportError, RespostaInesperadaError),
        progresso=contagem,
        relogio=relogio,
        dormir=dormir,
    )
