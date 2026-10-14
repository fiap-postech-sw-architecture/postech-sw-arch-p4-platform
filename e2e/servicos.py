"""Chamadas de negocio aos tres servicos, sempre pela borda (Kong).

Cada metodo e um endpoint da API publica de um servico, com o papel de quem o
chama: o admin cadastra preco e estoque, o atendente cuida da OS e do cliente, o
mecanico trabalha na fila da Execucao. So roda contra o cluster (``make e2e``);
a logica que da para testar sem ele fica em ``e2e/apoio``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final, Literal

from e2e.apoio import dados
from e2e.apoio.segredos import registrar

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    import httpx

    from e2e.apoio.http import Cliente

type Json = dict[str, Any]
type Papel = Literal["admin", "atendente", "mecanico"]

OS: Final = "/os/api/v1"
BILLING: Final = "/billing/api/v1"
EXECUCAO: Final = "/execucao/api/v1"
# O access token vale 15 min (JWT_EXPIRATION_MINUTES); renova antes.
_VIDA_DO_TOKEN: Final = 12 * 60
_PAGINA: Final = 100


class Credenciais:
    """Admin do Secret ``os-admin`` e o atendente e o mecanico que o admin registra.

    Faz o login uma vez por sessao (o OS limita login e registro a 5 por minuto
    por processo, e atras do Kong todo cliente do kind tem o mesmo IP) e renova
    o token pouco antes de vencer.
    """

    def __init__(
        self,
        http: Cliente,
        *,
        admin_email: str,
        admin_senha: str,
        execucao: str,
        relogio: Callable[[], float] = time.monotonic,
    ) -> None:
        self._http = http
        self._relogio = relogio
        self._usuarios: dict[Papel, tuple[str, str]] = {
            "admin": (admin_email, admin_senha)
        }
        self._tokens: dict[Papel, tuple[str, float]] = {}
        registrar(admin_senha)
        self._execucao = execucao

    def preparar(self) -> None:
        """Registra o atendente e o mecanico pelo admin, cada um com senha propria."""
        for papel in ("atendente", "mecanico"):
            email, senha = (
                dados.email_de_usuario(self._execucao, papel),
                dados.senha_aleatoria(),
            )
            registrar(senha)
            self._http.pedir(
                "POST",
                f"{OS}/autenticacao/registrar",
                token=self.token("admin"),
                json={"email": email, "senha": senha, "papel": papel},
                esperado=[201],
            )
            self._usuarios[papel] = (email, senha)

    def token(self, papel: Papel) -> str:
        emitido = self._tokens.get(papel)
        if emitido is None or self._relogio() - emitido[1] > _VIDA_DO_TOKEN:
            email, senha = self._usuarios[papel]
            resposta = self._http.pedir(
                "POST",
                f"{OS}/autenticacao/login",
                json={"email": email, "senha": senha},
                esperado=[200],
            )
            token = str(resposta.json()["access_token"])
            registrar(token)
            emitido = (token, self._relogio())
            self._tokens[papel] = emitido
        return emitido[0]


@dataclass
class Cenario:
    """Os dados de um cenario: tudo nasce nele e nenhum outro cenario o enxerga."""

    numero: int
    execucao: str
    nome: str = ""
    tags: frozenset[str] = frozenset()
    servico: str = ""
    peca: str = ""
    preco_servico: str = ""
    preco_peca: str = ""
    estoque_inicial: int = 0
    cliente_id: str = ""
    documento: str = ""
    contato: str = ""
    placa: str = ""
    veiculo_id: str = ""
    ordem_id: str = ""
    request_id_da_abertura: str = ""
    link_de_decisao: str = ""
    orcamento_id: str = ""
    pagamento_id: str = ""
    trace_id: str = ""
    ultima_resposta: httpx.Response | None = None
    respostas: list[httpx.Response] = field(default_factory=list)
    filas_mortas_antes: dict[str, int] = field(default_factory=dict)
    inicio: float = 0.0

    @property
    def resumo(self) -> str:
        return f"OS {self.ordem_id[:8]}" if self.ordem_id else "sem OS ainda"


class Api:
    """Os endpoints que os cenarios usam, com o papel certo em cada um."""

    def __init__(self, http: Cliente, credenciais: Credenciais) -> None:
        self.http = http
        self._credenciais = credenciais

    def _pedir(
        self,
        papel: Papel | None,
        metodo: str,
        caminho: str,
        *,
        esperado: Iterable[int] | None,
        **opcoes: Any,
    ) -> httpx.Response:
        token = self._credenciais.token(papel) if papel else None
        return self.http.pedir(
            metodo, caminho, token=token, esperado=esperado, **opcoes
        )

    def _paginas(self, papel: Papel, caminho: str, **params: Any) -> list[Json]:
        itens: list[Json] = []
        while True:
            corpo = self._pedir(
                papel,
                "GET",
                caminho,
                params={**params, "offset": len(itens), "limit": _PAGINA},
                esperado=[200],
            ).json()
            itens.extend(corpo["items"])
            if not corpo["items"] or len(itens) >= corpo["total"]:
                return itens

    # --- OS: cliente, veiculo e ordem -------------------------------------

    def cadastrar_cliente_bruto(
        self, nome: str, documento: str, contato: str
    ) -> httpx.Response:
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
        if resposta.status_code != 201:
            msg = f"cadastro do cliente: HTTP {resposta.status_code}"
            raise AssertionError(msg)
        corpo: Json = resposta.json()
        return corpo

    def cadastrar_veiculo(self, cliente_id: str, placa: str) -> Json:
        corpo: Json = self._pedir(
            "atendente",
            "POST",
            f"{OS}/clientes/{cliente_id}/veiculos",
            esperado=[201],
            json={"placa": placa, "marca": "Fiat", "modelo": "Uno", "ano": 2020},
        ).json()
        return corpo

    def abrir_ordem(
        self, cliente_id: str, veiculo_id: str, problema: str
    ) -> httpx.Response:
        return self._pedir(
            "atendente",
            "POST",
            f"{OS}/ordens-de-servico",
            esperado=[201],
            json={
                "cliente_id": cliente_id,
                "veiculo_id": veiculo_id,
                "descricao_problema": problema,
            },
        )

    def ordem(self, ordem_id: str) -> Json:
        corpo: Json = self._pedir(
            "atendente", "GET", f"{OS}/ordens-de-servico/{ordem_id}", esperado=[200]
        ).json()
        return corpo

    def historico(self, ordem_id: str) -> Json:
        corpo: Json = self._pedir(
            "atendente",
            "GET",
            f"{OS}/ordens-de-servico/{ordem_id}/historico",
            esperado=[200],
        ).json()
        return corpo

    def saga(self, ordem_id: str) -> Json:
        corpo: Json = self._pedir(
            "admin", "GET", f"{OS}/sagas/{ordem_id}", esperado=[200]
        ).json()
        return corpo

    def cancelar(self, ordem_id: str, motivo: str) -> httpx.Response:
        return self._pedir(
            "atendente",
            "POST",
            f"{OS}/ordens-de-servico/{ordem_id}/cancelamento",
            esperado=None,
            json={"motivo": motivo},
        )

    def entregar(self, ordem_id: str) -> Json:
        corpo: Json = self._pedir(
            "atendente",
            "POST",
            f"{OS}/ordens-de-servico/{ordem_id}/entrega",
            esperado=[200],
        ).json()
        return corpo

    def acompanhar(self, placa: str, documento: str) -> httpx.Response:
        return self._pedir(
            None,
            "POST",
            f"{OS}/publico/acompanhamento",
            esperado=None,
            json={"placa": placa, "documento": documento},
        )

    # --- Billing: precos, orcamento e pagamento ---------------------------

    def cadastrar_preco_do_servico(self, codigo: str, preco: str) -> None:
        self._pedir(
            "admin",
            "POST",
            f"{BILLING}/precos/servicos",
            esperado=[201],
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
            esperado=[201],
            json={"sku": sku, "nome": "Peca de teste E2E", "preco": preco},
        )

    def orcamento(self, orcamento_id: str) -> Json:
        corpo: Json = self._pedir(
            "atendente", "GET", f"{BILLING}/orcamentos/{orcamento_id}", esperado=[200]
        ).json()
        return corpo

    def pagamento(self, pagamento_id: str) -> Json:
        corpo: Json = self._pedir(
            "atendente", "GET", f"{BILLING}/pagamentos/{pagamento_id}", esperado=[200]
        ).json()
        return corpo

    def decidir_pelo_link(
        self, link: str, decisao: Literal["aprovar", "recusar"]
    ) -> Json:
        """O cliente decide pelo link do e-mail: sem JWT, so o token do link."""
        corpo: Json = self._pedir(
            None, "POST", f"{link}/decisao", esperado=[200], json={"decisao": decisao}
        ).json()
        return corpo

    def simular_pagamento(
        self, pagamento_id: str, token: str, acao: Literal["aprovar", "recusar"]
    ) -> Json:
        """O botao do checkout simulado (o mesmo caso de uso do webhook do provedor)."""
        corpo: Json = self._pedir(
            None,
            "POST",
            f"{BILLING}/simulador/pagamentos/{pagamento_id}/{acao}",
            esperado=[200],
            params={"token": token},
        ).json()
        return corpo

    # --- Execucao: estoque, diagnostico, fila e execucao ------------------

    def cadastrar_estoque(self, sku: str, quantidade: int) -> None:
        self._pedir(
            "admin",
            "POST",
            f"{EXECUCAO}/estoque",
            esperado=[201],
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
            esperado=[200],
            json={"quantidade_disponivel": quantidade},
        )

    def estoque(self, sku: str) -> Json:
        corpo: Json = self._pedir(
            "mecanico", "GET", f"{EXECUCAO}/estoque/{sku}", esperado=[200]
        ).json()
        return corpo

    def diagnosticos(self, status: str) -> list[Json]:
        return self._paginas("mecanico", f"{EXECUCAO}/diagnosticos", status=status)

    def iniciar_diagnostico(self, ordem_id: str) -> Json:
        corpo: Json = self._pedir(
            "mecanico",
            "POST",
            f"{EXECUCAO}/diagnosticos/{ordem_id}/inicio",
            esperado=[200],
        ).json()
        return corpo

    def concluir_diagnostico(self, ordem_id: str, itens: list[Json]) -> httpx.Response:
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
        corpo: Json = self._pedir(
            "mecanico",
            "POST",
            f"{EXECUCAO}/execucoes/{ordem_id}/inicio",
            esperado=[200],
        ).json()
        return corpo

    def finalizar_execucao(self, ordem_id: str) -> Json:
        corpo: Json = self._pedir(
            "mecanico",
            "POST",
            f"{EXECUCAO}/execucoes/{ordem_id}/finalizacao",
            esperado=[200],
        ).json()
        return corpo
