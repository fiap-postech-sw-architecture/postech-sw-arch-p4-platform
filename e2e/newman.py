"""Collection do fluxo completo: pytest explicito por make newman, sem sandbox."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from e2e.ambiente import URL_DA_BORDA
from e2e.apoio import dados
from e2e.apoio.espera import esperar
from e2e.apoio.newman import conferir_ambiente, executar_newman
from e2e.apoio.segredos import registrar

if TYPE_CHECKING:
    from e2e.ambiente import Portas
    from e2e.apoio.http import ClienteHttp
    from e2e.apoio.kube import Kubectl

# A coleta acontece antes de fixtures autouse poderem ligar um modo da sandbox.
conferir_ambiente(os.environ)


def test_fluxo_completo_newman(
    kubectl: Kubectl, borda: ClienteHttp, portas: Portas, execucao: str
) -> None:
    __tracebackhide__ = True
    from pathlib import Path

    for servico in ("os", "billing", "execucao"):

        def saudavel(servico: str = servico) -> bool:
            return borda.pedir("GET", f"/{servico}/api/v1/saude").status_code == 200

        esperar(
            saudavel,
            prazo=60,
            intervalo=2,
            descricao="servicos saudaveis para Newman",
        )
    assert borda.pedir("GET", "/billing/api/v1/saude").json()["modo"] == "simulado", (
        "Newman exige o simulador"
    )
    senha = kubectl.segredo("pytstop-os", "os-admin", "ADMIN_PASSWORD")
    registrar(senha)
    variaveis = {
        "baseUrl": URL_DA_BORDA.rstrip("/"),
        "mailpitUrl": portas.url_do_mailpit,
        "admin_email": os.environ.get("E2E_ADMIN_EMAIL")
        or kubectl.valor_de_configmap("pytstop-os", "ADMIN_EMAIL")
        or "admin@pytstop.dev",
        "admin_senha": senha,
        "servico": dados.codigo("SRV", execucao, 1),
        "peca": dados.codigo("PEC", execucao, 1),
        "cpf": dados.cpf_valido(),
        "contato": dados.email_de_cliente(execucao, 1),
        "placa": dados.placa_mercosul(),
        "offset": "0",
    }
    for papel in ("atendente", "mecanico"):
        variaveis[papel + "_email"] = dados.email_de_usuario(execucao, papel)
        variaveis[papel + "_senha"] = dados.senha_aleatoria()
    executar_newman(
        variaveis, pacote=os.environ["NEWMAN"], relatorios=Path("reports/e2e/newman")
    )
