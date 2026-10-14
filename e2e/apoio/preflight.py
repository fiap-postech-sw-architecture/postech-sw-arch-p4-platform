"""Conferencia previa do overlay: o E2E so vale no ``kind-ci``.

Os cenarios ``@expiracao`` e de pagamento recusado dependem de valores do overlay
``kind-ci`` do Billing (orcamento de 72 s, primeira recusa encerra a cobranca,
``prazos`` a cada 5 s) e todos de um rate limit da borda multiplicado por 10. Num
overlay ``kind`` padrao eles reprovariam minutos depois com um "nao ocorreu";
aqui reprovam na hora, dizendo o que mudar.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from e2e.apoio.kube import Kubectl

NAMESPACE_BILLING: Final = "pytstop-billing"
# Horas do orcamento no kind-ci: 0,02 h = 72 s.
VALIDADE_DO_ORCAMENTO_HORAS: Final = 0.02
EXIGIDOS_NO_BILLING: Final = {
    "ORCAMENTO_VALIDADE_HORAS": "0.02",
    "PAGAMENTO_MAX_RECUSAS": "1",
    "PRAZOS_INTERVALO_SEGUNDOS": "5",
}
# Limite global por minuto da borda com o x10 do overlay kind (o base e 60).
LIMITE_DA_BORDA_POR_MINUTO: Final = 600


class OverlayErradoError(AssertionError):
    """O cluster nao esta no overlay ``kind-ci``."""


def _numero(texto: str | None) -> float | None:
    try:
        return None if texto is None else float(texto)
    except ValueError:
        return None


def conferir_overlay_kind_ci(kubectl: Kubectl) -> None:
    """Falha na hora, listando cada divergencia, se o overlay nao e o ``kind-ci``."""
    problemas: list[str] = []
    for chave, esperado in EXIGIDOS_NO_BILLING.items():
        lido = kubectl.valor_de_configmap(NAMESPACE_BILLING, chave)
        if _numero(lido) != _numero(esperado):
            problemas.append(
                f"{chave} no Billing e {lido!r}, o kind-ci pede {esperado}"
            )
    limite = _numero(
        kubectl.executar(
            "get",
            "kongclusterplugin",
            "rate-limiting-global",
            "-o",
            "jsonpath={.config.minute}",
        ).strip()
        or None
    )
    if limite is None or limite < LIMITE_DA_BORDA_POR_MINUTO:
        problemas.append(
            f"o rate limit global da borda e {limite}/min, o kind pede "
            f"{LIMITE_DA_BORDA_POR_MINUTO}"
        )
    if problemas:
        msg = (
            "o cluster nao esta no overlay kind-ci: "
            + "; ".join(problemas)
            + ". Suba com `make kind-up deploy OVERLAY=kind-ci` num cluster novo "
            "(trocar de overlay no mesmo cluster nao desfaz o anterior)."
        )
        raise OverlayErradoError(msg)
