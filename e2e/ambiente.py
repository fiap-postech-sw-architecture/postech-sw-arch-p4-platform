"""Ambiente do E2E: contexto, URL da borda, relatorios, narracao e port-forwards.

Fica fora do ``conftest.py`` porque os steps tambem usam (importar de um conftest
e fragil). So roda com cluster: ``make e2e`` e ``make demo`` o exercitam.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final

from e2e.apoio.http import ClienteHttp
from e2e.apoio.jaeger import Jaeger, validar_trace_id
from e2e.apoio.kube import NAMESPACE_DA_PLATAFORMA, Kubectl, PortForward
from e2e.apoio.mailpit import Mailpit

# O padrao do Makefile (CLUSTER ?= pytstop-p4); test_ambiente.py confere.
CONTEXTO_PADRAO: Final = "kind-pytstop-p4"
CONTEXTO: Final = os.environ.get("KUBE_CONTEXT", CONTEXTO_PADRAO)
URL_DA_BORDA: Final = os.environ.get("E2E_URL", "https://localhost")
RELATORIOS: Final = Path(os.environ.get("E2E_RELATORIOS", "reports/e2e"))
NARRAR: Final = os.environ.get("E2E_NARRAR") == "1"
# Sandbox do Mercado Pago (make mp-sandbox e make mp-sandbox-ensaio): "real" ou
# "ensaio". Vazio e o E2E da saga; com ele, so os cenarios @mp_sandbox rodam.
MP_MODO: Final = os.environ.get("E2E_MP_MODO", "")
# Cada bloco do video dura ate 4 min; o make demo imprime o tempo dos dois.
LIMITE_DO_BLOCO: Final = 240.0
DURACAO_DOS_BLOCOS: dict[str, float] = {}
NAMESPACE_BILLING: Final = "pytstop-billing"
NAMESPACE_EXECUCAO: Final = "pytstop-execucao"
NAMESPACE_OS: Final = "pytstop-os"
# Deployments que os cenarios de resiliencia derrubam; uma execucao que caiu no
# meio os deixa em 0, e o inicio da proxima os religa.
ALVOS_DE_FALHA: Final = (
    (NAMESPACE_BILLING, "billing-service-consumidor"),
    (NAMESPACE_BILLING, "billing-service-api"),
)


def narrar(texto: str) -> None:
    """Linha do roteiro do video (so com ``E2E_NARRAR=1``)."""
    if NARRAR:
        print(texto, flush=True)


class Portas:
    """Port-forwards de sessao do que nao sai pela borda (e-mail, trace, metricas)."""

    def __init__(self, kubectl: Kubectl) -> None:
        self._pontes = {
            "mailpit": PortForward(
                kubectl, NAMESPACE_DA_PLATAFORMA, "svc/mailpit", 8025
            ),
            "jaeger": PortForward(
                kubectl, NAMESPACE_DA_PLATAFORMA, "svc/jaeger", 16686
            ),
            # /metrics da api da Execucao: o Kong o barra, o Service nao.
            "execucao": PortForward(
                kubectl, NAMESPACE_EXECUCAO, "svc/execution-service", 8000
            ),
        }
        self._clientes: dict[str, ClienteHttp] = {}

    def iniciar(self) -> None:
        """Abre os tres; se um falha, fecha os que ja abriu (o pytest nao roda o
        teardown de uma fixture que levantou antes do ``yield``)."""
        try:
            for nome, ponte in self._pontes.items():
                ponte.iniciar()
                self._clientes[nome] = ClienteHttp(ponte.url)
        except BaseException:
            self.encerrar()
            raise

    def encerrar(self) -> None:
        for cliente in self._clientes.values():
            cliente.fechar()
        for ponte in self._pontes.values():
            ponte.encerrar()

    def _cliente(self, nome: str) -> ClienteHttp:
        self._pontes[nome].garantir()
        return self._clientes[nome]

    @property
    def mailpit(self) -> Mailpit:
        return Mailpit(self._cliente("mailpit"))

    @property
    def jaeger(self) -> Jaeger:
        return Jaeger(self._cliente("jaeger"))

    def baixar_trace(self, trace_id: str) -> str:
        """JSON do trace, como o Jaeger o serve em ``/api/traces/<id>``."""
        validado = validar_trace_id(trace_id)
        return (
            self._cliente("jaeger")
            .pedir("GET", f"/api/traces/{validado}", esperado=[200])
            .text
        )

    def metricas_da_execucao(self) -> str:
        return self._cliente("execucao").pedir("GET", "/metrics", esperado=[200]).text
