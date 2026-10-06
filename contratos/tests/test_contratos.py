"""Contratos de mensageria: catalogo, AsyncAPI, JSON Schemas, exemplos e topologia.

O catalogo e os campos abaixo sao os da RFC-004, secao 5.3
(docs/arquitetura/rfc/fase4/rfc-004-microsservicos-saga.md). Os testes amarram
as quatro fontes que os servicos copiam (asyncapi.yaml, schemas/, exemplos/ e o
definitions.json do RabbitMQ) para que nenhuma divirja das outras nem da RFC.

O criterio de qualidade do contrato e a bateria de negativos gerados dos
exemplos (test_todo_defeito_gerado_do_exemplo_e_rejeitado), nao a cobertura de
linha: o pytest-cov mede so este arquivo, nunca os schemas.
"""

from __future__ import annotations

import copy
import json
import re
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
import yaml
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError
from referencing import Registry, Resource

if TYPE_CHECKING:
    from collections.abc import Iterator

RAIZ = Path(__file__).resolve().parents[2]
CONTRATOS = RAIZ / "contratos"
SCHEMAS = CONTRATOS / "schemas"
EXEMPLOS = CONTRATOS / "exemplos"
DEFINITIONS = RAIZ / "k8s" / "base" / "rabbitmq" / "definitions.json"
PERMISSOES = RAIZ / "k8s" / "base" / "rabbitmq" / "permissoes.json"

# tipo -> (comando | evento, servico emissor, servico consumidor)
CATALOGO: dict[str, tuple[str, str, str]] = {
    "SolicitarDiagnostico": ("comando", "os", "execucao"),
    "DiagnosticoIniciado": ("evento", "execucao", "os"),
    "DiagnosticoConcluido": ("evento", "execucao", "os"),
    "DescartarDiagnostico": ("comando", "os", "execucao"),
    "DiagnosticoDescartado": ("evento", "execucao", "os"),
    "GerarOrcamento": ("comando", "os", "billing"),
    "OrcamentoGerado": ("evento", "billing", "os"),
    "GeracaoDeOrcamentoFalhou": ("evento", "billing", "os"),
    "OrcamentoAprovado": ("evento", "billing", "os"),
    "OrcamentoRecusado": ("evento", "billing", "os"),
    "OrcamentoExpirado": ("evento", "billing", "os"),
    "CancelarOrcamento": ("comando", "os", "billing"),
    "OrcamentoCancelado": ("evento", "billing", "os"),
    "ReservarPecas": ("comando", "os", "execucao"),
    "PecasReservadas": ("evento", "execucao", "os"),
    "ReservaDePecasFalhou": ("evento", "execucao", "os"),
    "LiberarReserva": ("comando", "os", "execucao"),
    "ReservaLiberada": ("evento", "execucao", "os"),
    "SolicitarPagamento": ("comando", "os", "billing"),
    "PagamentoSolicitado": ("evento", "billing", "os"),
    "PagamentoConfirmado": ("evento", "billing", "os"),
    "PagamentoRecusado": ("evento", "billing", "os"),
    "PagamentoExpirado": ("evento", "billing", "os"),
    "EstornarPagamento": ("comando", "os", "billing"),
    "PagamentoEstornado": ("evento", "billing", "os"),
    "EstornoDePagamentoFalhou": ("evento", "billing", "os"),
    "PagamentoCancelado": ("evento", "billing", "os"),
    "AgendarExecucao": ("comando", "os", "execucao"),
    "ExecucaoAgendada": ("evento", "execucao", "os"),
    "CancelarExecucao": ("comando", "os", "execucao"),
    "ExecucaoCancelada": ("evento", "execucao", "os"),
    "ExecucaoIniciada": ("evento", "execucao", "os"),
    "ExecucaoFinalizada": ("evento", "execucao", "os"),
    "AnonimizarVeiculo": ("comando", "os", "execucao"),
}
# Campos de `dados` na RFC-004 5.3: obrigatorios e opcionais. Sem
# additionalProperties: false (leitor tolerante, RFC 5.5), quem pega campo com
# nome errado ou esquecido e este teste.
CAMPOS: dict[str, str] = {
    "SolicitarDiagnostico": "ordem_id veiculo_id veiculo descricao_problema",
    "DiagnosticoIniciado": "ordem_id mecanico_id iniciado_em",
    "DiagnosticoConcluido": "ordem_id itens observacoes concluido_em",
    "DescartarDiagnostico": "ordem_id motivo",
    "DiagnosticoDescartado": "ordem_id",
    "GerarOrcamento": "ordem_id itens",
    "OrcamentoGerado": (
        "ordem_id orcamento_id linhas total moeda valido_ate link_decisao"
    ),
    "GeracaoDeOrcamentoFalhou": "ordem_id motivo codigos_invalidos",
    "OrcamentoAprovado": "ordem_id orcamento_id decidido_em canal",
    "OrcamentoRecusado": "ordem_id orcamento_id decidido_em canal",
    "OrcamentoExpirado": "ordem_id orcamento_id",
    "CancelarOrcamento": "ordem_id motivo",
    "OrcamentoCancelado": "ordem_id orcamento_id",
    "ReservarPecas": "ordem_id pecas",
    "PecasReservadas": "ordem_id reserva_id",
    "ReservaDePecasFalhou": "ordem_id faltantes",
    "LiberarReserva": "ordem_id motivo",
    "ReservaLiberada": "ordem_id",
    "SolicitarPagamento": "ordem_id orcamento_id",
    "PagamentoSolicitado": "ordem_id pagamento_id valor moeda checkout_url expira_em",
    "PagamentoConfirmado": (
        "ordem_id pagamento_id valor moeda confirmado_em referencia_provedor"
    ),
    "PagamentoRecusado": "ordem_id pagamento_id motivo",
    "PagamentoExpirado": "ordem_id pagamento_id motivo",
    "EstornarPagamento": "ordem_id motivo",
    "PagamentoEstornado": "ordem_id pagamento_id estornado_em motivo",
    "EstornoDePagamentoFalhou": "ordem_id pagamento_id motivo",
    "PagamentoCancelado": "ordem_id pagamento_id cancelado_em",
    "AgendarExecucao": "ordem_id prioridade",
    "ExecucaoAgendada": "ordem_id posicao_na_fila",
    "CancelarExecucao": "ordem_id motivo",
    "ExecucaoCancelada": "ordem_id",
    "ExecucaoIniciada": "ordem_id mecanico_id iniciada_em",
    "ExecucaoFinalizada": "ordem_id finalizada_em pecas_consumidas",
    "AnonimizarVeiculo": "veiculo_id",
}
# Ids do passo em voo (o participante localiza pelo ordem_id) e o autor da
# decisao, que so existe com canal=atendente.
OPCIONAIS: dict[str, set[str]] = {
    "CancelarOrcamento": {"orcamento_id"},
    "EstornarPagamento": {"pagamento_id"},
    "OrcamentoAprovado": {"decidido_por"},
    "OrcamentoRecusado": {"decidido_por"},
}
# Objetos aninhados (propriedade objeto ou itens de lista), todos obrigatorios.
ANINHADOS: dict[str, str] = {
    "veiculo": "placa marca modelo ano",
    "itens": "tipo codigo quantidade",
    "linhas": "codigo descricao quantidade preco_unitario subtotal",
    "pecas": "sku quantidade",
    "faltantes": "sku solicitado disponivel",
    "pecas_consumidas": "sku quantidade",
}
# Texto livre (aceita qualquer string curta); motivo so e livre nos eventos de
# falha: nos comandos de compensacao e codigo e em PagamentoEstornado, enum.
LIVRES = {
    "descricao_problema",
    "observacoes",
    "descricao",
    "marca",
    "modelo",
    "referencia_provedor",
}
FALHAS = {
    "GeracaoDeOrcamentoFalhou",
    "PagamentoRecusado",
    "PagamentoExpirado",
    "EstornoDePagamentoFalhou",
}
# Listas que a RFC deixa vazias: orcamento so de servicos e nenhum codigo invalido.
VAZIAS_OK = {"pecas", "pecas_consumidas", "codigos_invalidos"}
# LGPD (RFC 5.3): mensagem nao leva nome, documento nem contato; placa so no
# retrato do veiculo que a Execucao guarda.
PII = re.compile(r"nome|cpf|cnpj|documento|e_?mail|telefone|celular|contato")
ORIGEM = {
    "os": "os-service",
    "billing": "billing-service",
    "execucao": "execution-service",
}
EXCHANGE = {"comando": "pytstop.comandos", "evento": "pytstop.eventos"}
FILAS_DE_TRABALHO = ["billing.comandos", "execucao.comandos", "os.eventos"]
SCHEMA_2020_12 = "https://json-schema.org/draft/2020-12/schema"


def ler_json(caminho: Path) -> Any:
    return json.loads(caminho.read_text(encoding="utf-8"))


def snake_case(nome: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", nome).lower()


def routing_key_esperada(tipo: str) -> str:
    kind, emissor, consumidor = CATALOGO[tipo]
    servico = consumidor if kind == "comando" else emissor
    return f"{kind}.{servico}.{snake_case(tipo)}"


def fila_do_consumidor(tipo: str) -> str:
    kind, _, consumidor = CATALOGO[tipo]
    return f"{consumidor}.comandos" if kind == "comando" else "os.eventos"


def casa_topico(padrao: list[str], chave: list[str]) -> bool:
    """Casamento de binding key de exchange topic do AMQP (* = 1 palavra, # = 0+)."""
    if not padrao:
        return not chave
    cabeca, *resto = padrao
    if cabeca == "#":
        return any(casa_topico(resto, chave[i:]) for i in range(len(chave) + 1))
    return bool(chave) and cabeca in ("*", chave[0]) and casa_topico(resto, chave[1:])


def objeto_aninhado(schema: dict[str, Any], no: dict[str, Any]) -> Any:
    """Schema do objeto de uma propriedade objeto ou lista de objetos, ou None."""
    no = no.get("items", no)
    if "$ref" in no:
        no = schema["$defs"][no["$ref"].rsplit("/", 1)[-1]]
    return no if no.get("type") == "object" else None


def nomes_de_campo(no: Any) -> set[str]:
    """Todas as chaves de objeto de um exemplo, em qualquer nivel."""
    if isinstance(no, dict):
        return set(no) | {c for v in no.values() for c in nomes_de_campo(v)}
    if isinstance(no, list):
        return {c for item in no for c in nomes_de_campo(item)}
    return set()


def propriedades(no: Any) -> set[str]:
    """Nomes declarados em qualquer `properties` de um schema."""
    if isinstance(no, dict):
        proprios = set(no.get("properties", {}))
        return proprios | {c for v in no.values() for c in propriedades(v)}
    if isinstance(no, list):
        return {c for item in no for c in propriedades(item)}
    return set()


def resolver_ponteiro(documento: Any, ponteiro: str) -> Any:
    no = documento
    for parte in filter(None, ponteiro.split("/")):
        chave = parte.replace("~1", "/").replace("~0", "~")
        no = no[int(chave)] if isinstance(no, list) else no[chave]
    return no


def refs(no: Any) -> list[str]:
    if isinstance(no, dict):
        return [v for k, v in no.items() if k == "$ref"] + [
            r for k, v in no.items() if k != "$ref" for r in refs(v)
        ]
    if isinstance(no, list):
        return [r for item in no for r in refs(item)]
    return []


def refs_quebradas(documento: dict[str, Any]) -> list[str]:
    quebradas = []
    for ref in refs(documento):
        arquivo, _, ponteiro = ref.partition("#")
        try:
            alvo = ler_json(CONTRATOS / arquivo) if arquivo else documento
            resolver_ponteiro(alvo, ponteiro)
        except (OSError, KeyError, IndexError, TypeError, ValueError):
            quebradas.append(ref)
    return quebradas


# Schemas indexados pela URI do arquivo: com o $id abaixo, os $ref relativos
# do asyncapi.yaml (./schemas/...) caem nos arquivos de verdade.
REGISTRO: Registry[Any] = Registry().with_resources(
    (p.as_uri(), Resource.from_contents(ler_json(p))) for p in SCHEMAS.glob("*.json")
)


def validador(schema: dict[str, Any]) -> Draft202012Validator:
    com_base = {"$id": (CONTRATOS / "asyncapi.yaml").as_uri(), **schema}
    return Draft202012Validator(
        com_base, registry=REGISTRO, format_checker=FormatChecker()
    )


@pytest.fixture(scope="session")
def asyncapi() -> dict[str, Any]:
    documento: dict[str, Any] = yaml.safe_load(
        (CONTRATOS / "asyncapi.yaml").read_text(encoding="utf-8")
    )
    return documento


@pytest.fixture(scope="session")
def definitions() -> dict[str, Any]:
    conteudo: dict[str, Any] = ler_json(DEFINITIONS)
    return conteudo


def test_todo_tipo_do_catalogo_tem_schema_exemplo_e_mensagem_no_asyncapi(
    asyncapi: dict[str, Any],
) -> None:
    schemas = {p.name.removesuffix(".schema.json") for p in SCHEMAS.glob("*.json")}
    exemplos = {p.stem for p in EXEMPLOS.glob("*.json")}

    assert schemas - {"envelope"} == set(CATALOGO)
    assert exemplos == set(CATALOGO)
    assert set(asyncapi["components"]["messages"]) == set(CATALOGO)


@pytest.mark.parametrize(
    "arquivo", sorted(SCHEMAS.glob("*.json")), ids=lambda p: p.name
)
def test_schema_e_json_schema_2020_12_valido(arquivo: Path) -> None:
    schema = ler_json(arquivo)

    assert schema["$schema"] == SCHEMA_2020_12
    Draft202012Validator.check_schema(schema)


@pytest.mark.parametrize("tipo", CATALOGO)
def test_exemplo_valido_contra_envelope_e_schema_do_tipo(tipo: str) -> None:
    exemplo = ler_json(EXEMPLOS / f"{tipo}.json")
    _, emissor, _ = CATALOGO[tipo]

    validador(ler_json(SCHEMAS / "envelope.schema.json")).validate(exemplo)
    validador(ler_json(SCHEMAS / f"{tipo}.schema.json")).validate(exemplo["dados"])
    assert exemplo["tipo"] == tipo
    assert exemplo["origem"] == ORIGEM[emissor]
    # Fora da saga (AnonimizarVeiculo) a correlacao e o agregado tratado.
    dados = exemplo["dados"]
    assert exemplo["correlation_id"] == dados.get("ordem_id", dados.get("veiculo_id"))


@pytest.mark.parametrize("tipo", CATALOGO)
def test_campos_do_schema_sao_os_da_rfc(tipo: str) -> None:
    schema = ler_json(SCHEMAS / f"{tipo}.schema.json")
    obrigatorios = set(CAMPOS[tipo].split())

    assert set(schema["required"]) == obrigatorios
    assert set(schema["properties"]) == obrigatorios | OPCIONAIS.get(tipo, set())
    for nome, propriedade in schema["properties"].items():
        aninhado = objeto_aninhado(schema, propriedade)
        if aninhado is not None:
            campos = set(ANINHADOS[nome].split())
            assert set(aninhado["required"]) == set(aninhado["properties"]) == campos


def com_campo_novo(no: Any) -> Any:
    if isinstance(no, dict):
        return {**{k: com_campo_novo(v) for k, v in no.items()}, "campo_novo": "x"}
    if isinstance(no, list):
        return [com_campo_novo(item) for item in no]
    return no


@pytest.mark.parametrize("tipo", CATALOGO)
def test_campo_opcional_novo_e_tolerado_em_qualquer_nivel(
    asyncapi: dict[str, Any], tipo: str
) -> None:
    # RFC 5.5: mudanca aditiva mantem a versao, e o consumidor ignora o campo
    # que nao conhece; um schema estrito mandaria a mensagem para a DLQ durante
    # o Rolling Update.
    exemplo = com_campo_novo(ler_json(EXEMPLOS / f"{tipo}.json"))

    validador(asyncapi["components"]["messages"][tipo]["payload"]["schema"]).validate(
        exemplo
    )


def test_mensagens_nao_levam_dado_pessoal_alem_da_placa() -> None:
    for arquivo in sorted(SCHEMAS.glob("*.json")):
        tipo = arquivo.name.removesuffix(".schema.json")
        campos = propriedades(ler_json(arquivo))
        exemplo = EXEMPLOS / f"{tipo}.json"
        if exemplo.exists():
            campos |= nomes_de_campo(ler_json(exemplo))

        assert not {c for c in campos if PII.search(c)}, tipo
        assert "placa" not in campos or tipo == "SolicitarDiagnostico", tipo


@pytest.mark.parametrize("tipo", CATALOGO)
def test_exemplo_valido_contra_payload_da_mensagem_no_asyncapi(
    asyncapi: dict[str, Any], tipo: str
) -> None:
    payload = asyncapi["components"]["messages"][tipo]["payload"]

    assert payload["schemaFormat"] == "application/schema+json;version=draft-2020-12"
    validador(payload["schema"]).validate(ler_json(EXEMPLOS / f"{tipo}.json"))


def test_referencias_do_asyncapi_resolvem(asyncapi: dict[str, Any]) -> None:
    assert refs(asyncapi), "o documento deveria ter referencias"
    assert refs_quebradas(asyncapi) == []


@pytest.mark.parametrize("tipo", CATALOGO)
def test_mensagem_do_asyncapi_amarra_o_proprio_tipo(
    asyncapi: dict[str, Any], tipo: str
) -> None:
    kind, emissor, _ = CATALOGO[tipo]
    mensagem = asyncapi["components"]["messages"][tipo]
    envelope, especifico = mensagem["payload"]["schema"]["allOf"]
    chave = routing_key_esperada(tipo)
    operacao = asyncapi["operations"][f"publicar{tipo}"]
    componente = {"$ref": f"#/components/messages/{tipo}"}
    topico = {
        (p["user"], p["exchange"]): p["write"]
        for p in ler_json(PERMISSOES)["topic_permissions"]
    }

    assert envelope == {"$ref": "./schemas/envelope.schema.json"}
    assert especifico["properties"] == {
        "tipo": {"const": tipo},
        "versao": {"const": 1},
        "origem": {"const": ORIGEM[emissor]},
        "dados": {"$ref": f"./schemas/{tipo}.schema.json"},
    }
    assert mensagem["bindings"]["amqp"]["messageType"] == tipo
    assert asyncapi["channels"][chave]["messages"] == {tipo: componente}
    assert asyncapi["channels"][fila_do_consumidor(tipo)]["messages"][tipo] == (
        componente
    )
    assert operacao["channel"] == {"$ref": f"#/channels/{chave}"}
    assert operacao["messages"] == [{"$ref": f"#/channels/{chave}/messages/{tipo}"}]
    # user_id do produtor: o broker confere contra a conexao, e a permissao de
    # topico do usuario tem de aceitar a routing key do tipo.
    assert operacao["bindings"]["amqp"]["deliveryMode"] == 2
    assert operacao["bindings"]["amqp"]["userId"] == emissor
    assert re.search(topico[emissor, EXCHANGE[kind]], chave)


def test_referencia_quebrada_e_apontada(asyncapi: dict[str, Any]) -> None:
    documento = copy.deepcopy(asyncapi)
    documento["channels"]["os.eventos"]["messages"]["Fantasma"] = {
        "$ref": "#/components/messages/Fantasma"
    }
    payload = documento["components"]["messages"]["GerarOrcamento"]["payload"]
    payload["schema"]["allOf"][0] = {"$ref": "./schemas/Fantasma.schema.json"}

    assert set(refs_quebradas(documento)) == {
        "#/components/messages/Fantasma",
        "./schemas/Fantasma.schema.json",
    }


def test_operacao_so_referencia_mensagens_do_proprio_canal(
    asyncapi: dict[str, Any],
) -> None:
    for nome, operacao in asyncapi["operations"].items():
        canal = operacao["channel"]["$ref"]
        for mensagem in operacao["messages"]:
            assert mensagem["$ref"].startswith(f"{canal}/messages/"), nome


@pytest.mark.parametrize("tipo", CATALOGO)
def test_canal_do_tipo_segue_convencao_de_routing_key_e_exchange(
    asyncapi: dict[str, Any], tipo: str
) -> None:
    kind, emissor, _ = CATALOGO[tipo]
    operacao = asyncapi["operations"][f"publicar{tipo}"]
    canal = resolver_ponteiro(asyncapi, operacao["channel"]["$ref"].removeprefix("#"))
    amqp = canal["bindings"]["amqp"]

    assert operacao["action"] == "send"
    assert operacao["tags"] == [{"name": ORIGEM[emissor]}]
    assert canal["address"] == routing_key_esperada(tipo)
    assert amqp["is"] == "routingKey"
    assert amqp["exchange"]["name"] == EXCHANGE[kind]


@pytest.mark.parametrize("tipo", CATALOGO)
def test_routing_key_chega_so_na_fila_do_consumidor(
    asyncapi: dict[str, Any], definitions: dict[str, Any], tipo: str
) -> None:
    kind, _, _ = CATALOGO[tipo]
    chave = routing_key_esperada(tipo).split(".")
    filas = {
        b["destination"]
        for b in definitions["bindings"]
        if b["source"] == EXCHANGE[kind]
        and casa_topico(b["routing_key"].split("."), chave)
    }
    fila = fila_do_consumidor(tipo)
    consumo = [
        o
        for o in asyncapi["operations"].values()
        if o["action"] == "receive" and o["channel"]["$ref"] == f"#/channels/{fila}"
    ]

    assert filas == {fila}
    assert len(consumo) == 1
    assert {"$ref": f"#/channels/{fila}/messages/{tipo}"} in consumo[0]["messages"]


@pytest.mark.parametrize("fila", FILAS_DE_TRABALHO)
def test_fila_de_trabalho_tem_retry_e_dlq_com_os_argumentos_da_plataforma(
    definitions: dict[str, Any], fila: str
) -> None:
    filas = {q["name"]: q for q in definitions["queues"]}
    seguro = {"x-dead-letter-strategy": "at-least-once", "x-overflow": "reject-publish"}

    def ligada(origem: str, destino: str) -> bool:
        return {
            "source": origem,
            "vhost": "/",
            "destination": destino,
            "destination_type": "queue",
            "routing_key": fila,
            "arguments": {},
        } in definitions["bindings"]

    assert filas[fila]["durable"] is True
    assert filas[fila]["arguments"] == {
        "x-queue-type": "quorum",
        "x-dead-letter-exchange": "pytstop.dlx",
        "x-dead-letter-routing-key": fila,
        **seguro,
    }
    # O consumidor publica a copia no pytstop.retry; sem consumidor na .retry,
    # a mensagem expira pelo TTL dela e o broker a devolve para a fila
    # original pelo default exchange.
    assert ligada("pytstop.retry", f"{fila}.retry")
    assert filas[f"{fila}.retry"]["arguments"] == {
        "x-queue-type": "quorum",
        "x-dead-letter-exchange": "",
        "x-dead-letter-routing-key": fila,
        **seguro,
    }
    # DLQ guarda no maximo 7 dias: as mensagens carregam dado pessoal (placa).
    assert ligada("pytstop.dlx", f"{fila}.dlq")
    assert filas[f"{fila}.dlq"]["arguments"] == {
        "x-queue-type": "quorum",
        "x-message-ttl": 7 * 24 * 60 * 60 * 1000,
    }


def test_exchanges_da_plataforma(definitions: dict[str, Any]) -> None:
    tipos = {e["name"]: e["type"] for e in definitions["exchanges"] if e["durable"]}

    # pytstop.retry e topic (com bindings de chave exata) so para aceitar
    # permissao por routing key: em direct, qualquer servico com escrita no
    # exchange poria mensagem na fila de outro.
    assert tipos == {
        "pytstop.comandos": "topic",
        "pytstop.eventos": "topic",
        "pytstop.retry": "topic",
        "pytstop.dlx": "direct",
    }


@pytest.mark.parametrize("usuario", ["os", "billing", "execucao"])
def test_permissoes_do_usuario_cobrem_so_o_que_o_catalogo_manda(
    definitions: dict[str, Any], usuario: str
) -> None:
    permissoes = ler_json(PERMISSOES)
    (geral,) = [p for p in permissoes["permissions"] if p["user"] == usuario]
    topico = {
        p["exchange"]: p["write"]
        for p in permissoes["topic_permissions"]
        if p["user"] == usuario
    }
    publica = {
        routing_key_esperada(t)
        for t, (_, emissor, _) in CATALOGO.items()
        if emissor == usuario
    }
    exchange = EXCHANGE["comando" if usuario == "os" else "evento"]
    fila = "os.eventos" if usuario == "os" else f"{usuario}.comandos"

    # O RabbitMQ procura o padrao em qualquer posicao do nome (re.search):
    # padrao sem ^ ou $ casaria tambem a .retry e a .dlq e reprovaria aqui.
    def casam(padrao: str, nomes: set[str]) -> set[str]:
        return {n for n in nomes if re.search(padrao, n)}

    exchanges = {e["name"] for e in definitions["exchanges"]}
    filas = {q["name"] for q in definitions["queues"]}
    chaves = {routing_key_esperada(t) for t in CATALOGO}
    assert geral["configure"] == "^$"
    assert casam(geral["write"], exchanges) == {exchange, "pytstop.retry"}
    assert casam(geral["read"], filas) == {fila}
    assert set(topico) == {exchange, "pytstop.retry"}
    assert casam(topico[exchange], chaves) == publica
    assert casam(topico["pytstop.retry"], filas) == {fila}


@pytest.mark.parametrize(
    ("padrao", "chave", "esperado"),
    [
        ("comando.billing.#", "comando.billing.gerar_orcamento", True),
        ("comando.billing.#", "comando.billing", True),
        ("comando.billing.#", "comando.execucao.reservar_pecas", False),
        ("evento.*.pecas_reservadas", "evento.execucao.pecas_reservadas", True),
        ("evento.*.pecas_reservadas", "evento.pecas_reservadas", False),
        ("billing.comandos", "billing.comandos", True),
    ],
)
def test_casa_topico(padrao: str, chave: str, esperado: bool) -> None:
    assert casa_topico(padrao.split("."), chave.split(".")) is esperado


def _mudar(exemplo: dict[str, Any], caminho: str, valor: Any) -> dict[str, Any]:
    mudado = copy.deepcopy(exemplo)
    *pais, ultimo = caminho.split("/")
    pai = resolver_ponteiro(mudado, "/".join(pais))
    pai[int(ultimo) if isinstance(pai, list) else ultimo] = valor
    return mudado


ITEM = {"tipo": "servico", "codigo": "SRV-X", "quantidade": 1}
ATENDENTE = "2f4e8c1a-7b3d-4e5f-9a6b-1c2d3e4f5a6b"


@pytest.mark.parametrize(
    ("tipo", "caminho", "valor"),
    [
        pytest.param("PagamentoConfirmado", "dados/valor", 820.0, id="dinheiro-float"),
        pytest.param(
            "PagamentoConfirmado", "dados/valor", "820", id="dinheiro-sem-casas"
        ),
        pytest.param(
            "PagamentoConfirmado",
            "dados/valor",
            "10000000000.00",
            id="dinheiro-11-digitos",
        ),
        pytest.param("OrcamentoGerado", "dados/moeda", "USD", id="moeda-usd"),
        pytest.param(
            "SolicitarDiagnostico",
            "dados/veiculo/placa",
            "ABC-1234",
            id="placa-com-hifen",
        ),
        pytest.param("OrcamentoAprovado", "dados/canal", "email", id="canal-email"),
        pytest.param(
            "OrcamentoAprovado", "dados/decidido_por", ATENDENTE, id="link-com-autor"
        ),
        pytest.param("DiagnosticoConcluido", "dados/itens", [], id="itens-vazio"),
        pytest.param("GerarOrcamento", "dados/itens", [ITEM] * 51, id="itens-51"),
        pytest.param(
            "GerarOrcamento", "dados/itens/0/quantidade", 1001, id="quantidade-1001"
        ),
        pytest.param(
            "GerarOrcamento", "dados/itens/0/codigo", "X" * 51, id="codigo-51-chars"
        ),
        pytest.param(
            "CancelarOrcamento", "dados/motivo", "Cliente desistiu", id="motivo-livre"
        ),
        pytest.param(
            "PagamentoEstornado", "dados/motivo", "outro", id="motivo-estorno-fora"
        ),
        pytest.param("GerarOrcamento", "correlation_id", "123", id="correlation-123"),
        pytest.param(
            "GerarOrcamento", "ocorrido_em", "2026-10-06T12:00:00", id="data-sem-fuso"
        ),
        pytest.param(
            "GerarOrcamento",
            "ocorrido_em",
            "2026-10-06T09:00:00-03:00",
            id="data-fora-de-utc",
        ),
        pytest.param(
            "GerarOrcamento", "ocorrido_em", "2026-13-45T12:00:00Z", id="data-invalida"
        ),
        pytest.param(
            "PagamentoSolicitado", "dados/checkout_url", "nao e uma url", id="url-texto"
        ),
        pytest.param(
            "PagamentoSolicitado",
            "dados/checkout_url",
            "javascript:alert(1)",
            id="url-javascript",
        ),
        pytest.param(
            "PagamentoSolicitado", "dados/checkout_url", "ftp://x/y", id="url-ftp"
        ),
        pytest.param(
            "OrcamentoGerado",
            "dados/link_decisao",
            "https://billing.local@evil.example/",
            id="url-com-userinfo",
        ),
    ],
)
def test_contrato_rejeita_dado_invalido(
    asyncapi: dict[str, Any], tipo: str, caminho: str, valor: Any
) -> None:
    invalido = _mudar(ler_json(EXEMPLOS / f"{tipo}.json"), caminho, valor)

    with pytest.raises(ValidationError):
        validador(
            asyncapi["components"]["messages"][tipo]["payload"]["schema"]
        ).validate(invalido)


def test_decisao_do_atendente_exige_o_autor(asyncapi: dict[str, Any]) -> None:
    exemplo = ler_json(EXEMPLOS / "OrcamentoRecusado.json")
    schema = validador(
        asyncapi["components"]["messages"]["OrcamentoRecusado"]["payload"]["schema"]
    )
    del exemplo["dados"]["decidido_por"]

    assert schema.is_valid(_mudar(exemplo, "dados/canal", "link"))
    assert not schema.is_valid(exemplo)


@pytest.mark.parametrize(
    ("tipo", "campo"),
    [("CancelarOrcamento", "orcamento_id"), ("EstornarPagamento", "pagamento_id")],
)
def test_compensacao_do_passo_em_voo_vai_sem_o_id(
    asyncapi: dict[str, Any], tipo: str, campo: str
) -> None:
    exemplo = ler_json(EXEMPLOS / f"{tipo}.json")
    del exemplo["dados"][campo]

    validador(asyncapi["components"]["messages"][tipo]["payload"]["schema"]).validate(
        exemplo
    )


def test_envelope_limita_o_tipo() -> None:
    envelope = validador(ler_json(SCHEMAS / "envelope.schema.json"))
    exemplo = ler_json(EXEMPLOS / "GerarOrcamento.json")

    assert envelope.is_valid(_mudar(exemplo, "tipo", "A" * 64))
    assert not envelope.is_valid(_mudar(exemplo, "tipo", "A" * 65))


def caminhos(no: Any, prefixo: str = "") -> Iterator[str]:
    """Ponteiro de cada chave e de cada item de lista do exemplo."""
    filhos = no.items() if isinstance(no, dict) else enumerate(no)
    for chave, valor in filhos:
        caminho = f"{prefixo}{chave}"
        yield caminho
        if isinstance(valor, dict | list):
            yield from caminhos(valor, f"{caminho}/")


def defeitos(tipo: str) -> Iterator[tuple[str, dict[str, Any]]]:
    """Variacoes invalidas de cada campo do exemplo, com a descricao do defeito."""
    exemplo = ler_json(EXEMPLOS / f"{tipo}.json")
    for onde in caminhos(exemplo):
        pais, _, nome = onde.rpartition("/")
        pai = resolver_ponteiro(exemplo, pais)
        valor = pai[int(nome)] if isinstance(pai, list) else pai[nome]
        livre = nome in LIVRES or (nome == "motivo" and tipo in FALHAS)
        if isinstance(pai, dict) and nome not in OPCIONAIS.get(tipo, set()):
            sem = copy.deepcopy(exemplo)
            del resolver_ponteiro(sem, pais)[nome]
            yield f"sem {onde}", sem
        if isinstance(valor, str) and not livre:
            yield f"{onde} fora do dominio", _mudar(exemplo, onde, "§")
        if isinstance(valor, str):
            yield f"{onde} gigante", _mudar(exemplo, onde, "x" * 100_000)
        if isinstance(valor, int):
            yield f"{onde} abaixo do minimo", _mudar(exemplo, onde, -1)
        yield f"{onde} com tipo errado", _mudar(exemplo, onde, 3.5)
        if isinstance(valor, list) and nome not in VAZIAS_OK:
            yield f"{onde} vazia", _mudar(exemplo, onde, [])


@pytest.mark.parametrize("tipo", CATALOGO)
def test_todo_defeito_gerado_do_exemplo_e_rejeitado(
    asyncapi: dict[str, Any], tipo: str
) -> None:
    schema = validador(asyncapi["components"]["messages"][tipo]["payload"]["schema"])

    aceitos = [
        defeito for defeito, envelope in defeitos(tipo) if schema.is_valid(envelope)
    ]

    assert aceitos == []


# Enumeracoes fechadas da RFC-004 (5.3 e secao 9): mudar um valor e mudanca de
# contrato, nao ajuste de schema.
ENUMERACOES: dict[str, list[str]] = {
    "canal": ["link", "atendente"],
    "prioridade": ["normal", "alta"],
    "tipo_item": ["servico", "peca"],
    "motivo_estorno": ["compensacao", "pagamento_apos_encerramento"],
    "motivo_compensacao": [
        "orcamento_recusado",
        "orcamento_expirado",
        "geracao_falhou",
        "reserva_falhou",
        "pagamento_recusado",
        "pagamento_expirado",
        "cancelamento",
        "prazo_tecnico",
    ],
}


def test_enumeracoes_sao_as_da_rfc() -> None:
    for arquivo in sorted(SCHEMAS.glob("*.json")):
        definicoes = ler_json(arquivo).get("$defs", {})
        for nome, valores in ENUMERACOES.items():
            if nome in definicoes:
                assert definicoes[nome]["enum"] == valores, (arquivo.name, nome)
        if "moeda" in definicoes:
            assert definicoes["moeda"]["const"] == "BRL", arquivo.name


def test_toda_mensagem_declara_os_headers_do_envelope(
    asyncapi: dict[str, Any],
) -> None:
    trait = asyncapi["components"]["messageTraits"]["envelope"]
    headers = trait["headers"]["properties"]

    assert set(headers) == {"traceparent", "tracestate", "x-tentativa"}
    assert headers["x-tentativa"] | {"description": ""} == {
        "type": "integer",
        "minimum": 1,
        "maximum": 5,
        "description": "",
    }
    for tipo, mensagem in asyncapi["components"]["messages"].items():
        assert mensagem["traits"] == [
            {"$ref": "#/components/messageTraits/envelope"}
        ], tipo


def test_definicoes_compartilhadas_sao_iguais_em_todos_os_schemas() -> None:
    # Cada schema e autocontido (o servico copia so os que usa), entao uuid,
    # data_hora, dinheiro etc. se repetem; aqui nenhuma copia diverge.
    vistos: dict[str, Any] = {}
    for arquivo in sorted(SCHEMAS.glob("*.json")):
        for nome, definicao in ler_json(arquivo).get("$defs", {}).items():
            assert vistos.setdefault(nome, definicao) == definicao, (arquivo, nome)
    envelope = ler_json(SCHEMAS / "envelope.schema.json")["properties"]

    def sem_descricao(definicao: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in definicao.items() if k != "description"}

    assert {
        "uuid",
        "data_hora",
        "dinheiro",
        "moeda",
        "codigo",
        "quantidade",
        "tipo_item",
        "uri",
        "canal",
        "prioridade",
        "motivo",
        "motivo_compensacao",
        "motivo_estorno",
    } <= set(vistos)
    assert sem_descricao(envelope["ocorrido_em"]) == sem_descricao(vistos["data_hora"])


def test_exemplo_de_orcamento_fecha_a_conta_em_decimal() -> None:
    dados = ler_json(EXEMPLOS / "OrcamentoGerado.json")["dados"]
    subtotais = [Decimal(linha["subtotal"]) for linha in dados["linhas"]]

    for linha, subtotal in zip(dados["linhas"], subtotais, strict=True):
        assert subtotal == linha["quantidade"] * Decimal(linha["preco_unitario"])
    assert Decimal(dados["total"]) == sum(subtotais, Decimal(0))
