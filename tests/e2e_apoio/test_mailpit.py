"""E-mails do Mailpit: o link de decisao do orcamento."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx

from e2e.apoio.http import (
    ClienteHttp,
)
from e2e.apoio.mailpit import (
    Mailpit,
    extrair_link_de_decisao,
)

if TYPE_CHECKING:
    from e2e_apoio.falsos import Relogio

_CORPO_ORCAMENTO = """\
Olá, Cliente E2E!

O orçamento da sua ordem de serviço 64db2c4d está pronto: R$ 210,00.

Para aprovar ou recusar, acesse:
https://localhost/billing/api/v1/publico/orcamentos/879d09ac-7cff.1791951593.hcfahihF-5Kb_ZyvD

Equipe PytStop
"""

_CORPO_PAGAMENTO = (
    "Pague R$ 210,00 pelo link abaixo:\n"
    "https://localhost/billing/simulador/checkout/84ea5cc1?token=abc.def\n"
)


def test_extrair_link_de_decisao_do_corpo_do_email() -> None:
    assert extrair_link_de_decisao(_CORPO_ORCAMENTO) == (
        "https://localhost/billing/api/v1/publico/orcamentos/"
        "879d09ac-7cff.1791951593.hcfahihF-5Kb_ZyvD"
    )


def test_extrair_link_de_decisao_sem_link_devolve_none() -> None:
    assert extrair_link_de_decisao("Sua OS foi atualizada.") is None
    assert extrair_link_de_decisao(_CORPO_PAGAMENTO) is None


def _mailpit(
    relogio: Relogio, mensagens: list[dict[str, Any]], textos: dict[str, str]
) -> Mailpit:
    consultas: list[str] = []

    def tratador(pedido: httpx.Request) -> httpx.Response:
        consultas.append(str(pedido.url))
        if pedido.url.path == "/api/v1/search":
            assert pedido.url.params["query"] == "to:cliente@x.dev"
            return httpx.Response(200, json={"messages": mensagens})
        id_da_mensagem = pedido.url.path.rsplit("/", 1)[1]
        return httpx.Response(200, json={"Text": textos[id_da_mensagem]})

    return Mailpit(
        ClienteHttp(
            "http://mailpit.local",
            transporte=httpx.MockTransport(tratador),
            relogio=relogio,
        )
    )


def test_mailpit_link_de_decisao_acha_o_email_de_orcamento(relogio: Relogio) -> None:
    mensagens = [
        {"ID": "m2", "Subject": "PytStop — Ordem de Serviço 64db2c4d: Em diagnóstico"},
        {
            "ID": "m1",
            "Subject": "Ordem de Serviço 64db2c4d: orçamento para a sua decisão",
        },
    ]
    textos = {"m1": _CORPO_ORCAMENTO, "m2": "Em diagnóstico."}

    link = _mailpit(relogio, mensagens, textos).link_de_decisao("cliente@x.dev")

    assert link is not None
    assert link.endswith("hcfahihF-5Kb_ZyvD")


def test_mailpit_link_de_decisao_so_olha_o_email_de_orcamento(relogio: Relogio) -> None:
    outro_link = "https://localhost/billing/api/v1/publico/orcamentos/OUTRO.tok"
    mensagens = [
        {"ID": "m2", "Subject": "Ordem de Serviço 64db2c4d: pagamento"},
        {
            "ID": "m1",
            "Subject": "Ordem de Serviço 64db2c4d: orçamento para a sua decisão",
        },
    ]
    textos = {"m1": _CORPO_ORCAMENTO, "m2": f"Pague. Veja tambem {outro_link}"}

    link = _mailpit(relogio, mensagens, textos).link_de_decisao("cliente@x.dev")

    assert link is not None
    assert "OUTRO" not in link


def test_mailpit_link_de_decisao_antes_do_email_chegar_devolve_none(
    relogio: Relogio,
) -> None:
    mensagens = [
        {"ID": "m2", "Subject": "PytStop — Ordem de Serviço 64db2c4d: Em diagnóstico"}
    ]

    assert (
        _mailpit(relogio, mensagens, {"m2": "texto"}).link_de_decisao("cliente@x.dev")
        is None
    )


def test_mailpit_email_de_orcamento_sem_link_e_ignorado(relogio: Relogio) -> None:
    mensagens = [{"ID": "m1", "Subject": "Ordem de Serviço: Orçamento"}]

    assert (
        _mailpit(relogio, mensagens, {"m1": "sem link"}).link_de_decisao(
            "cliente@x.dev"
        )
        is None
    )


def test_mailpit_sem_mensagens_devolve_listas_vazias(relogio: Relogio) -> None:
    mailpit = _mailpit(relogio, [], {})

    assert mailpit.mensagens_para("cliente@x.dev") == []
    assert mailpit.assuntos("cliente@x.dev") == []


def test_mailpit_assuntos_lista_o_assunto_de_cada_mensagem(relogio: Relogio) -> None:
    mensagens = [{"ID": "m1", "Subject": "A"}, {"ID": "m2", "Subject": "B"}]

    assert _mailpit(relogio, mensagens, {}).assuntos("cliente@x.dev") == ["A", "B"]
