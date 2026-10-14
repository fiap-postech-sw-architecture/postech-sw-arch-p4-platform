"""Chamadas de negocio aos tres servicos, sempre pela borda (Kong).

Cada metodo e um endpoint da API publica de um servico, com o papel de quem o
chama: o admin cadastra preco e estoque, o atendente cuida da OS e do cliente, o
mecanico trabalha na fila da Execucao. ``Api`` reune as tres APIs (``api.os``,
``api.billing`` e ``api.execucao``). So roda contra o cluster (``make e2e``); a
logica que da para testar sem ele fica em ``e2e/apoio``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final, Literal

from e2e.apoio.http import RespostaInesperadaError, descrever

if TYPE_CHECKING:
    from collections.abc import Iterable

    import httpx

    from e2e.apoio.credenciais import Credenciais, Papel
    from e2e.apoio.http import ClienteHttp

# Corpo JSON de uma resposta: o formato varia por endpoint e o servico o valida.
type Json = dict[str, Any]

OS: Final = "/os/api/v1"
BILLING: Final = "/billing/api/v1"
EXECUCAO: Final = "/execucao/api/v1"
CRIADO: Final = 201
PAGINA: Final = 100


@dataclass
class Cenario:
    """Os dados de um cenario: tudo nasce nele e nenhum outro cenario o enxerga."""

    numero: int
    execucao: str
    nome: str = ""
    tags: frozenset[str] = frozenset()
    servico: str = ""
    peca: str = ""
    cliente_id: str = ""
    # Fora do repr: o pytest imprime o fixture quando um passo falha, e o link
    # de decisao e uma credencial.
    documento: str = field(default="", repr=False)
    contato: str = field(default="", repr=False)
    placa: str = field(default="", repr=False)
    veiculo_id: str = ""
    ordem_id: str = ""
    request_id_da_abertura: str = ""
    link_de_decisao: str = field(default="", repr=False)
    orcamento_id: str = ""
    pagamento_id: str = ""
    trace_id: str = ""
    ultima_resposta: httpx.Response | None = field(default=None, repr=False)
    respostas: list[httpx.Response] = field(default_factory=list, repr=False)
    filas_mortas_antes: dict[str, int] = field(default_factory=dict)
    inicio: float = 0.0

    @property
    def resumo(self) -> str:
        return f"OS {self.ordem_id[:8]}" if self.ordem_id else "sem OS ainda"


class _Servico:
    """Base das APIs: o pedido com o papel certo e o corpo JSON."""

    def __init__(self, http: ClienteHttp, credenciais: Credenciais) -> None:
        self._http = http
        self._credenciais = credenciais

    def _pedir(
        self,
        papel: Papel | None,
        metodo: str,
        caminho: str,
        *,
        esperado: Iterable[int] | None = (200,),
        **opcoes: Any,
    ) -> httpx.Response:
        """O pedido; ``**opcoes`` vai para ``ClienteHttp.pedir`` (json, params)."""
        token = self._credenciais.token(papel) if papel else None
        return self._http.pedir(
            metodo, caminho, token=token, esperado=esperado, **opcoes
        )

    def _json(
        self,
        papel: Papel | None,
        metodo: str,
        caminho: str,
        *,
        esperado: Iterable[int] = (200,),
        **opcoes: Any,
    ) -> Json:
        corpo: Json = self._pedir(
            papel, metodo, caminho, esperado=esperado, **opcoes
        ).json()
        return corpo

    def _paginas(self, papel: Papel, caminho: str, **params: Any) -> list[Json]:
        itens: list[Json] = []
        while True:
            corpo = self._json(
                papel,
                "GET",
                caminho,
                params={**params, "offset": len(itens), "limit": PAGINA},
            )
            itens.extend(corpo["items"])
            if not corpo["items"] or len(itens) >= corpo["total"]:
                return itens


class ApiOs(_Servico):
    """OS Service: cliente, veiculo, ordem, historico e saga."""

    def cadastrar_cliente_bruto(
        self, nome: str, documento: str, contato: str
    ) -> httpx.Response:
        """O cadastro sem conferir o status (o CPF invalido quer o 422)."""
        return self._pedir(
            "atendente",
            "POST",
            f"{OS}/clientes",
            esperado=None,
            json={
                "nome": nome,
                "documento": documento,
                "tipo_documento": "cpf",
                "contato": contato,
            },
        )

    def cadastrar_cliente(self, nome: str, documento: str, contato: str) -> Json:
        resposta = self.cadastrar_cliente_bruto(nome, documento, contato)
        if resposta.status_code != CRIADO:
            raise RespostaInesperadaError(
                descrever("POST", f"{OS}/clientes", resposta, [CRIADO])
            )
        corpo: Json = resposta.json()
        return corpo

    def cadastrar_veiculo(self, cliente_id: str, placa: str) -> Json:
        return self._json(
            "atendente",
            "POST",
            f"{OS}/clientes/{cliente_id}/veiculos",
            esperado=[CRIADO],
            json={"placa": placa, "marca": "Fiat", "modelo": "Uno", "ano": 2020},
        )

    def abrir_ordem(
        self, cliente_id: str, veiculo_id: str, problema: str
    ) -> httpx.Response:
        return self._pedir(
            "atendente",
            "POST",
            f"{OS}/ordens-de-servico",
            esperado=[CRIADO],
            json={
                "cliente_id": cliente_id,
                "veiculo_id": veiculo_id,
                "descricao_problema": problema,
            },
        )

    def listar_ordens(self) -> Json:
        """A fila de ordens do atendente (``GET /api/v1/ordens-de-servico``)."""
        return self._json("atendente", "GET", f"{OS}/ordens-de-servico")

    def ordem(self, ordem_id: str) -> Json:
        return self._json("atendente", "GET", f"{OS}/ordens-de-servico/{ordem_id}")

    def historico(self, ordem_id: str) -> Json:
        return self._json(
            "atendente", "GET", f"{OS}/ordens-de-servico/{ordem_id}/historico"
        )

    def saga(self, ordem_id: str) -> Json:
        """Estado e passos da saga: so o admin le (``GET /api/v1/sagas/{id}``)."""
        return self._json("admin", "GET", f"{OS}/sagas/{ordem_id}")

    def cancelar(self, ordem_id: str, motivo: str) -> httpx.Response:
        return self._pedir(
            "atendente",
            "POST",
            f"{OS}/ordens-de-servico/{ordem_id}/cancelamento",
            esperado=None,
            json={"motivo": motivo},
        )

    def entregar(self, ordem_id: str) -> Json:
        return self._json(
            "atendente", "POST", f"{OS}/ordens-de-servico/{ordem_id}/entrega"
        )

    def acompanhar(self, placa: str, documento: str) -> httpx.Response:
        """Consulta publica por placa e documento: sem JWT."""
        return self._pedir(
            None,
            "POST",
            f"{OS}/publico/acompanhamento",
            esperado=None,
            json={"placa": placa, "documento": documento},
        )


class ApiBilling(_Servico):
    """Billing Service: precos, orcamento, link de decisao e pagamento."""

    def cadastrar_preco_do_servico(self, codigo: str, preco: str) -> None:
        self._pedir(
            "admin",
            "POST",
            f"{BILLING}/precos/servicos",
            esperado=[CRIADO],
            json={
                "codigo": codigo,
                "nome": "Servico de teste E2E",
                "descricao": "Servico cadastrado pelo teste ponta a ponta",
                "preco": preco,
            },
        )

    def cadastrar_preco_da_peca(self, sku: str, preco: str) -> None:
        self._pedir(
            "admin",
            "POST",
            f"{BILLING}/precos/pecas",
            esperado=[CRIADO],
            json={"sku": sku, "nome": "Peca de teste E2E", "preco": preco},
        )

    def orcamento(self, orcamento_id: str) -> Json:
        return self._json("atendente", "GET", f"{BILLING}/orcamentos/{orcamento_id}")

    def pagamento(self, pagamento_id: str) -> Json:
        return self._json("atendente", "GET", f"{BILLING}/pagamentos/{pagamento_id}")

    def decidir_pelo_link(
        self, link: str, decisao: Literal["aprovar", "recusar"]
    ) -> Json:
        """O cliente decide pelo link do e-mail: sem JWT, so o token do link."""
        return self._json(None, "POST", f"{link}/decisao", json={"decisao": decisao})

    def simular_pagamento(
        self, pagamento_id: str, token: str, acao: Literal["aprovar", "recusar"]
    ) -> Json:
        """O botao do checkout simulado (o mesmo caso de uso do webhook do provedor)."""
        return self._json(
            None,
            "POST",
            f"{BILLING}/simulador/pagamentos/{pagamento_id}/{acao}",
            params={"token": token},
        )


class ApiExecucao(_Servico):
    """Execution Service: estoque, diagnostico, fila e execucao."""

    def cadastrar_estoque(self, sku: str, quantidade: int) -> None:
        self._pedir(
            "admin",
            "POST",
            f"{EXECUCAO}/estoque",
            esperado=[CRIADO],
            json={
                "sku": sku,
                "nome": "Peca de teste E2E",
                "quantidade_disponivel": quantidade,
            },
        )

    def ajustar_estoque(self, sku: str, quantidade: int) -> None:
        self._pedir(
            "admin",
            "PATCH",
            f"{EXECUCAO}/estoque/{sku}/quantidade",
            json={"quantidade_disponivel": quantidade},
        )

    def estoque(self, sku: str) -> Json:
        return self._json("mecanico", "GET", f"{EXECUCAO}/estoque/{sku}")

    def diagnosticos(self, status: str) -> list[Json]:
        return self._paginas("mecanico", f"{EXECUCAO}/diagnosticos", status=status)

    def iniciar_diagnostico(self, ordem_id: str) -> Json:
        return self._json(
            "mecanico", "POST", f"{EXECUCAO}/diagnosticos/{ordem_id}/inicio"
        )

    def concluir_diagnostico(self, ordem_id: str, itens: list[Json]) -> httpx.Response:
        """A conclusao sem conferir o status (a resiliencia quer o 503)."""
        return self._pedir(
            "mecanico",
            "POST",
            f"{EXECUCAO}/diagnosticos/{ordem_id}/conclusao",
            esperado=None,
            json={"itens": itens, "observacoes": "Diagnostico do teste E2E"},
        )

    def fila(self) -> list[Json]:
        return self._paginas("mecanico", f"{EXECUCAO}/fila")

    def iniciar_execucao(self, ordem_id: str) -> Json:
        return self._json("mecanico", "POST", f"{EXECUCAO}/execucoes/{ordem_id}/inicio")

    def finalizar_execucao(self, ordem_id: str) -> Json:
        return self._json(
            "mecanico", "POST", f"{EXECUCAO}/execucoes/{ordem_id}/finalizacao"
        )


class Api:
    """As tres APIs, cada uma com o papel certo em cada chamada."""

    def __init__(self, http: ClienteHttp, credenciais: Credenciais) -> None:
        self.http = http
        self.os = ApiOs(http, credenciais)
        self.billing = ApiBilling(http, credenciais)
        self.execucao = ApiExecucao(http, credenciais)
