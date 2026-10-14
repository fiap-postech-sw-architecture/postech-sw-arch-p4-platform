"""A conferencia do sandbox antes do pytest: ``python -m e2e.conferir_sandbox``.

E a mesma conferencia que a sessao faz (contexto, borda, overlay, servicos, credencial
e token), so que com mensagem limpa, sem o prefixo nem o resumo do pytest, e antes de
o ``make`` mexer na pasta de relatorios. Quem esqueceu a credencial, ou esta sem
cluster, le o que mudar e o terminal nao mostra mais nada; a evidencia de uma
execucao boa fica onde estava.
"""

from __future__ import annotations

import re
import sys
from typing import TYPE_CHECKING, Final, TextIO

from e2e.apoio.contexto import (
    ContextoNaoDescartavelError,
    conferir_borda_local,
    conferir_contexto,
    escape_do_ambiente,
)
from e2e.apoio.http import ClienteHttp
from e2e.apoio.kube import ErroDeComandoError, Kubectl, executar_processo
from e2e.apoio.mercadopago import ClienteMercadoPago
from e2e.apoio.preflight_mp import (
    PreflightDoSandboxError,
    conferir_kind,
    credenciais_do_ambiente,
    preflight_do_sandbox,
)
from e2e.apoio.segredos import mascarar

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from e2e.apoio.kube import Executor

MODOS: Final = frozenset({"real", "ensaio"})
# A saida de um kubectl que falhou: "<comando>: saiu com 1: <o que o kubectl disse>".
_DO_KUBECTL: Final = re.compile(r": saiu com \d+: (?P<motivo>.*)$", re.DOTALL)
SUBIR_O_CLUSTER: Final = (
    'Suba o cluster e os três serviços (README, "Mercado Pago na sandbox", '
    '"Como rodar") e confira o KUBE_CONTEXT.'
)


def _motivo_do_kubectl(erro: ErroDeComandoError) -> str:
    """O que o kubectl disse, sem o comando na frente."""
    texto = str(erro)
    achado = _DO_KUBECTL.search(texto)
    return (achado["motivo"] if achado else texto).strip()


def _recusar(saida: TextIO, mensagem: str) -> int:
    print(f"[mp-sandbox] não posso seguir: {mascarar(mensagem)}", file=saida)
    return 2


def conferir_antes_do_pytest(  # cada parametro e um ponto de injecao dos testes
    argumentos: Sequence[str],
    ambiente: Mapping[str, str],
    *,
    contexto: str,
    url_da_borda: str,
    saida: TextIO = sys.stderr,
    criar_kubectl: Callable[[str], Kubectl] = Kubectl,
    criar_borda: Callable[[str], ClienteHttp] = ClienteHttp,
    criar_cliente: Callable[[str], ClienteMercadoPago] = ClienteMercadoPago,
    executor_docker: Executor = executar_processo,
) -> int:
    """``<real|ensaio>``: 0 se o sandbox pode rodar; 2, com a mensagem em ``saida``."""
    if len(argumentos) != 1 or argumentos[0] not in MODOS:
        print("uso: python -m e2e.conferir_sandbox <real|ensaio>", file=saida)
        return 2
    kubectl = criar_kubectl(contexto)
    borda = criar_borda(url_da_borda)
    try:
        # Sem o escape do E2E: o token vai para um Secret do cluster.
        conferir_kind(contexto)
        if argumentos[0] == "real":
            credenciais_do_ambiente(ambiente)  # o mais barato primeiro: sem cluster
        escape = escape_do_ambiente(ambiente)
        conferir_contexto(contexto, escape)
        conferir_borda_local(
            kubectl, escape, executor_docker, url_da_borda=url_da_borda
        )
        sandbox = preflight_do_sandbox(
            kubectl,
            borda,
            {**ambiente, "E2E_MP_MODO": argumentos[0]},
            cliente=criar_cliente,
            avisar=lambda _: None,
        )
    except (ContextoNaoDescartavelError, PreflightDoSandboxError) as erro:
        return _recusar(saida, str(erro))
    except ErroDeComandoError as erro:
        return _recusar(
            saida,
            f"o kubectl não conseguiu ler o cluster ({_motivo_do_kubectl(erro)}). "
            f"{SUBIR_O_CLUSTER}",
        )
    finally:
        borda.fechar()
    if sandbox.mercadopago is not None:
        sandbox.mercadopago.fechar()
    print(f"[mp-sandbox] conferência ok ({argumentos[0]}) em {contexto}")
    return 0
