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
RFC = RAIZ / "docs" / "arquitetura" / "rfc" / "fase4" / "rfc-004-microsservicos-saga.md"

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
FILA_DO_USUARIO = {
    "os": "os.eventos",
    "billing": "billing.comandos",
    "execucao": "execucao.comandos",
}
# Atraso, em segundos, de cada nova tentativa: a copia com x-tentativa n vai
# para <fila>.retry.<ATRASOS[n - 1]>s; a falha seguinte a quinta vai para a DLQ.
ATRASOS = (1, 5, 15, 60, 300)
# Dead letter sem perda: at-least-once, que a fila quorum so aceita com
# overflow reject-publish.
SEM_PERDA = {"dead-letter-strategy": "at-least-once", "overflow": "reject-publish"}
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


def filas_de_retry(fila: str) -> list[str]:
    """Filas de retry da fila de trabalho, na ordem das tentativas."""
    return [f"{fila}.retry.{atraso}s" for atraso in ATRASOS]


def casa_topico(padrao: list[str], chave: list[str]) -> bool:
    """Casamento de binding key de exchange topic do AMQP (* = 1 palavra, # = 0+)."""
    if not padrao:
        return not chave
    cabeca, *resto = padrao
    if cabeca == "#":
        return any(casa_topico(resto, chave[i:]) for i in range(len(chave) + 1))
    return bool(chave) and cabeca in ("*", chave[0]) and casa_topico(resto, chave[1:])


def filas_alcancadas(
    definitions: dict[str, Any], exchange: str, chave: str
) -> set[str]:
    """Filas do vhost / que recebem a publicacao com esta routing key no topic."""
    return {
        b["destination"]
        for b in definitions["bindings"]
        if b["source"] == exchange
        and b["vhost"] == "/"
        and b["destination_type"] == "queue"
        and casa_topico(b["routing_key"].split("."), chave.split("."))
    }


# Objetos como o definitions.json os declara, para comparar inteiros: vhost,
# tipo de destino ou auto-delete errados derrubam a importacao no boot, e o
# broker nao sobe.
def fila_quorum(nome: str, ttl_ms: int | None = None) -> dict[str, Any]:
    """Fila quorum duravel do vhost /; o TTL so nas filas de retry."""
    argumentos: dict[str, Any] = {"x-queue-type": "quorum"}
    if ttl_ms is not None:
        argumentos["x-message-ttl"] = ttl_ms
    return {
        "name": nome,
        "vhost": "/",
        "durable": True,
        "auto_delete": False,
        "arguments": argumentos,
    }


def ligacao(origem: str, destino: str, chave: str) -> dict[str, Any]:
    """Binding de exchange para fila no vhost /, sem argumentos."""
    return {
        "source": origem,
        "vhost": "/",
        "destination": destino,
        "destination_type": "queue",
        "routing_key": chave,
        "arguments": {},
    }


def policy_de_fila(nome: str, padrao: str, definicao: dict[str, Any]) -> dict[str, Any]:
    """Policy do vhost / para filas, com a prioridade 0 de todas."""
    return {
        "vhost": "/",
        "name": nome,
        "pattern": padrao,
        "apply-to": "queues",
        "priority": 0,
        "definition": definicao,
    }


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


@pytest.mark.parametrize("tipo", CATALOGO)
def test_descricao_do_schema_e_o_summary_da_mensagem_no_asyncapi(
    asyncapi: dict[str, Any], tipo: str
) -> None:
    # O texto que o servico le no schema e o que le no AsyncAPI e o mesmo: a
    # frase de identificacao (tipo, emissor e consumidor) mais o summary, sem
    # sobra do texto anterior.
    kind, emissor, consumidor = CATALOGO[tipo]
    summary = asyncapi["components"]["messages"][tipo]["summary"]
    esperada = (
        f"Campo dados da mensagem {tipo} "
        f"({kind}, {ORIGEM[emissor]} -> {ORIGEM[consumidor]}). {summary}"
    )

    assert ler_json(SCHEMAS / f"{tipo}.schema.json")["description"] == esperada


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
    filas = filas_alcancadas(definitions, EXCHANGE[kind], routing_key_esperada(tipo))
    fila = fila_do_consumidor(tipo)
    consumo = [
        o
        for o in asyncapi["operations"].values()
        if o["action"] == "receive" and o["channel"]["$ref"] == f"#/channels/{fila}"
    ]

    assert filas == {fila}
    assert len(consumo) == 1
    assert {"$ref": f"#/channels/{fila}/messages/{tipo}"} in consumo[0]["messages"]


def politica(definitions: dict[str, Any], fila: str) -> dict[str, Any]:
    """A policy que o RabbitMQ aplica na fila (re.search do padrao no nome)."""
    casadas = [p for p in definitions["policies"] if re.search(p["pattern"], fila)]
    assert len(casadas) == 1, (fila, [p["name"] for p in casadas])
    policy: dict[str, Any] = casadas[0]
    return policy


@pytest.mark.parametrize("fila", FILAS_DE_TRABALHO)
def test_fila_de_trabalho_e_dlq_tem_as_policies_da_plataforma(
    definitions: dict[str, Any], fila: str
) -> None:
    filas = {q["name"]: q for q in definitions["queues"]}
    dlq = f"{fila}.dlq"

    # Argumento de fila e imutavel e a importacao no boot ignora a mudanca:
    # na fila de trabalho e na DLQ so o tipo e argumento; o resto vem das
    # policies, que convergem. Limite de 5 entregas (o padrao da fila quorum
    # e 20): a mensagem que derruba o consumidor a cada entrega, como um
    # header que o pika nao decodifica, vai para a DLQ na sexta, em vez de
    # prender o consumidor em reconexoes. A copia de retry entra na fila como
    # mensagem nova, com a contagem zerada, e nao gasta o limite.
    assert filas[fila] == fila_quorum(fila)
    assert filas[dlq] == fila_quorum(dlq)
    assert politica(definitions, fila) == policy_de_fila(
        f"trabalho-{fila}",
        f"^{re.escape(fila)}$",
        {
            "dead-letter-exchange": "pytstop.dlx",
            "dead-letter-routing-key": fila,
            "max-length": 10000,
            "delivery-limit": 5,
            **SEM_PERDA,
        },
    )
    # DLQ guarda no maximo 7 dias: as mensagens carregam dado pessoal (placa).
    assert politica(definitions, dlq) == policy_de_fila(
        "dlq", r"\.dlq$", {"message-ttl": 7 * 24 * 60 * 60 * 1000}
    )


@pytest.mark.parametrize("fila", FILAS_DE_TRABALHO)
def test_fila_de_trabalho_tem_uma_fila_de_retry_por_atraso(
    definitions: dict[str, Any], fila: str
) -> None:
    filas = {q["name"]: q for q in definitions["queues"]}
    # Sem message-ttl na policy: com policy e argumento, a fila quorum usa o
    # menor, e um valor na policy encurtaria os atrasos maiores.
    retry = policy_de_fila(
        f"retry-{fila}",
        f"^{re.escape(fila)}\\.retry\\.",
        {"dead-letter-exchange": "", "dead-letter-routing-key": fila, **SEM_PERDA},
    )

    # Uma fila de retry por atraso, com o TTL fixo no argumento: TTL por
    # mensagem so vence na cabeca da fila, e numa fila unica uma copia de
    # 300 s seguraria as de 1 s chegadas depois. Com TTL igual para todas, a
    # ordem de chegada e a de expiracao. O atraso esta no nome, entao mudar um
    # atraso e criar outra fila, nunca mudar o argumento de uma que ja existe.
    assert {n for n in filas if n.startswith(f"{fila}.retry")} == set(
        filas_de_retry(fila)
    )
    assert {n for n in filas if re.search(retry["pattern"], n)} == set(
        filas_de_retry(fila)
    )
    for nome, atraso in zip(filas_de_retry(fila), ATRASOS, strict=True):
        assert filas[nome] == fila_quorum(nome, ttl_ms=atraso * 1000)
        assert politica(definitions, nome) == retry
        # A routing key da copia e o nome da fila de retry e so chega nela.
        assert filas_alcancadas(definitions, "pytstop.retry", nome) == {nome}


def test_bindings_ligam_cada_fila_so_as_proprias_chaves(
    definitions: dict[str, Any],
) -> None:
    # Comando pelo servico de destino, evento pelo de origem (todos para o
    # OS), dead letter pelo nome da fila. No pytstop.retry, chave exata, sem
    # curinga e sem binding a mais: a permissao de topico do usuario (abaixo)
    # decide sozinha em quais filas de retry ele publica.
    esperadas = [
        *(
            ligacao("pytstop.comandos", f"{servico}.comandos", f"comando.{servico}.#")
            for servico in ("billing", "execucao")
        ),
        *(
            ligacao("pytstop.eventos", "os.eventos", f"evento.{servico}.#")
            for servico in ("billing", "execucao")
        ),
        *(
            ligacao("pytstop.retry", nome, nome)
            for fila in FILAS_DE_TRABALHO
            for nome in filas_de_retry(fila)
        ),
        *(ligacao("pytstop.dlx", f"{fila}.dlq", fila) for fila in FILAS_DE_TRABALHO),
    ]

    def ordem(binding: dict[str, Any]) -> str:
        return json.dumps(binding, sort_keys=True)

    assert sorted(definitions["bindings"], key=ordem) == sorted(esperadas, key=ordem)


def test_vhost_e_exchanges_da_plataforma(definitions: dict[str, Any]) -> None:
    # pytstop.retry e topic (com bindings de chave exata) so para aceitar
    # permissao por routing key: em direct, qualquer servico com escrita no
    # exchange poria mensagem na fila de outro. Objeto inteiro: num exchange
    # interno o broker recusa toda publicacao (403).
    tipos = {
        "pytstop.comandos": "topic",
        "pytstop.eventos": "topic",
        "pytstop.retry": "topic",
        "pytstop.dlx": "direct",
    }

    assert definitions["vhosts"] == [{"name": "/"}]
    assert {e["name"]: e for e in definitions["exchanges"]} == {
        nome: {
            "name": nome,
            "vhost": "/",
            "type": tipo,
            "durable": True,
            "auto_delete": False,
            "internal": False,
            "arguments": {},
        }
        for nome, tipo in tipos.items()
    }


# O RabbitMQ acha o padrao de permissao em qualquer posicao do nome
# (re.search): sem ^ ou \z, o padrao casaria tambem as filas de retry, a .dlq
# ou um nome com sobra. O fim e \z porque o $ casa tambem antes de um \n final.
def casam(padrao: str, nomes: set[str]) -> set[str]:
    return {n for n in nomes if re.search(padrao, n)}


def com_sobras(nomes: set[str]) -> set[str]:
    """Os nomes e cada um com uma sobra antes ou depois, o \\n final incluso."""
    return nomes | {s for n in nomes for s in (f"x{n}", f"{n}x", f"{n}\n")}


@pytest.mark.parametrize("usuario", FILA_DO_USUARIO)
def test_permissao_do_usuario_no_vhost_cobre_so_a_propria_fila_e_onde_publica(
    definitions: dict[str, Any], usuario: str
) -> None:
    (geral,) = [p for p in ler_json(PERMISSOES)["permissions"] if p["user"] == usuario]
    exchange = EXCHANGE["comando" if usuario == "os" else "evento"]
    exchanges = {e["name"] for e in definitions["exchanges"]}
    filas = {q["name"] for q in definitions["queues"]}

    # Objeto inteiro: vhost e configure fixos; write e read pelo que casam.
    assert geral | {"write": "", "read": ""} == {
        "user": usuario,
        "vhost": "/",
        "configure": "^\\z",
        "write": "",
        "read": "",
    }
    assert casam(geral["write"], com_sobras(exchanges)) == {exchange, "pytstop.retry"}
    assert casam(geral["read"], com_sobras(filas)) == {FILA_DO_USUARIO[usuario]}


@pytest.mark.parametrize("usuario", FILA_DO_USUARIO)
def test_permissao_de_topico_cobre_so_as_chaves_que_o_catalogo_manda(
    definitions: dict[str, Any], usuario: str
) -> None:
    topico = {
        p["exchange"]: p
        for p in ler_json(PERMISSOES)["topic_permissions"]
        if p["user"] == usuario
    }
    exchange = EXCHANGE["comando" if usuario == "os" else "evento"]
    chaves = {routing_key_esperada(t) for t in CATALOGO}
    publica = {
        routing_key_esperada(t)
        for t, (_, emissor, _) in CATALOGO.items()
        if emissor == usuario
    }
    filas = {q["name"] for q in definitions["queues"]}

    # Objeto inteiro: uma por exchange em que publica, so de escrita.
    so_escrita = {"user": usuario, "vhost": "/", "write": "", "read": "^\\z"}
    assert {nome: p | {"write": ""} for nome, p in topico.items()} == {
        nome: so_escrita | {"exchange": nome} for nome in (exchange, "pytstop.retry")
    }
    # Chave de comando ou evento: o padrao e prefixo, so a sobra antes conta.
    prefixadas = chaves | {f"x{c}" for c in chaves}
    assert casam(topico[exchange]["write"], prefixadas) == publica
    # No pytstop.retry a routing key e o nome da fila de retry (a varredura
    # esta no teste seguinte).
    assert casam(topico["pytstop.retry"]["write"], filas) == set(
        filas_de_retry(FILA_DO_USUARIO[usuario])
    )


@pytest.mark.parametrize("usuario", FILA_DO_USUARIO)
def test_permissao_no_retry_aceita_so_as_cinco_chaves_da_propria_fila(
    usuario: str,
) -> None:
    (padrao,) = [
        p["write"]
        for p in ler_json(PERMISSOES)["topic_permissions"]
        if p["user"] == usuario and p["exchange"] == "pytstop.retry"
    ]
    fila = FILA_DO_USUARIO[usuario]
    propria = filas_de_retry(fila)[0]
    outras = [f for f in FILAS_DE_TRABALHO if f != fila]
    pontos = [i for i, c in enumerate(propria) if c == "."]

    def aceita(chave: str) -> bool:
        return re.search(padrao, chave) is not None

    # Varredura, nao amostra: de 0 a 1000 s, com ou sem zero a esquerda, so
    # os cinco atrasos passam; depois do numero, so o s; e nenhuma sobra de um
    # ou dois caracteres ASCII (o \n incluso) antes ou depois de uma chave.
    sobras = [chr(c) + resto for c in range(128) for resto in ("", "x")]
    assert [n for n in range(1001) if aceita(f"{fila}.retry.{n}s")] == list(ATRASOS)
    assert [n for n in range(1001) if aceita(f"{fila}.retry.0{n}s")] == []
    for atraso in ATRASOS:
        assert [s for s in sobras if aceita(f"{fila}.retry.{atraso}{s}")] == ["s"]
    for chave in filas_de_retry(fila):
        assert [s for s in sobras if aceita(chave + s) or aceita(s + chave)] == []
    # As chaves das outras filas, a antiga (o nome da fila de trabalho), o
    # prefixo sem atraso, cada atraso sem o s (a varredura acima nunca deixa
    # o s de fora), a DLQ e cada ponto trocado por outro caractere (pega o
    # ponto sem escape na regex).
    recusadas = [
        *(chave for outra in outras for chave in filas_de_retry(outra)),
        *(f"{propria[:i]}-{propria[i + 1 :]}" for i in pontos),
        *(f"{fila}.retry.{atraso}" for atraso in ATRASOS),
        fila,
        f"{fila}.retry",
        f"{fila}.retry.",
        f"{fila}.dlq",
    ]
    assert [c for c in recusadas if aceita(c)] == []


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
        pytest.param("DiagnosticoConcluido", "dados/itens", [], id="itens-vazio"),
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


# Os defeitos gerados acima mudam um campo por vez e nao chegam na fronteira
# exata de um limite, nem provam o lado aceito. Daqui ate o fim da secao, cada
# limite e cada regra condicional tem o valor na fronteira aceito e o seguinte
# rejeitado, para que mexer em um limite, tirar uma regra ou apertar uma lista
# reprove o teste. O oraculo e a RFC-004 5.3 e o README, nao o schema.
def listas_dos_exemplos() -> list[Any]:
    achadas = []
    for tipo in CATALOGO:
        exemplo = ler_json(EXEMPLOS / f"{tipo}.json")
        for onde in caminhos(exemplo):
            if isinstance(resolver_ponteiro(exemplo, onde), list):
                nome = onde.rsplit("/", 1)[-1]
                achadas.append(pytest.param(tipo, onde, id=f"{tipo}-{nome}"))
    return achadas


def n_itens(item: Any, n: int) -> list[Any]:
    """n itens como o do exemplo; texto muda por indice (codigos nao repetem)."""
    return [f"{item}-{i}" if isinstance(item, str) else item for i in range(n)]


@pytest.mark.parametrize(("tipo", "onde"), listas_dos_exemplos())
def test_lista_vai_de_um_a_50_itens_e_so_aceita_vazia_onde_a_rfc_deixa(
    asyncapi: dict[str, Any], tipo: str, onde: str
) -> None:
    exemplo = ler_json(EXEMPLOS / f"{tipo}.json")
    item = resolver_ponteiro(exemplo, onde)[0]
    schema = validador(asyncapi["components"]["messages"][tipo]["payload"]["schema"])

    def aceita(n: int) -> bool:
        return schema.is_valid(_mudar(exemplo, onde, n_itens(item, n)))

    assert aceita(1)
    assert aceita(50)
    assert not aceita(51)
    assert aceita(0) is (onde.rsplit("/", 1)[-1] in VAZIAS_OK)


def test_codigos_invalidos_nao_repete_codigo(asyncapi: dict[str, Any]) -> None:
    exemplo = ler_json(EXEMPLOS / "GeracaoDeOrcamentoFalhou.json")
    caminho = "dados/codigos_invalidos"
    schema = validador(
        asyncapi["components"]["messages"]["GeracaoDeOrcamentoFalhou"]["payload"][
            "schema"
        ]
    )

    assert schema.is_valid(_mudar(exemplo, caminho, ["PEC-A", "PEC-B"]))
    assert not schema.is_valid(_mudar(exemplo, caminho, ["PEC-A", "PEC-A"]))


@pytest.mark.parametrize("tipo", ["OrcamentoAprovado", "OrcamentoRecusado"])
@pytest.mark.parametrize(
    ("canal", "decidido_por", "valido"),
    [
        pytest.param("atendente", ATENDENTE, True, id="atendente-com-autor"),
        pytest.param("atendente", None, False, id="atendente-sem-autor"),
        pytest.param("atendente", "nao-e-uuid", False, id="atendente-autor-invalido"),
        pytest.param("link", None, True, id="link-sem-autor"),
        pytest.param("link", ATENDENTE, False, id="link-com-autor"),
        pytest.param("email", None, False, id="canal-fora-da-enumeracao"),
    ],
)
def test_decisao_so_leva_decidido_por_com_canal_atendente(
    asyncapi: dict[str, Any],
    tipo: str,
    canal: str,
    decidido_por: str | None,
    valido: bool,
) -> None:
    exemplo = ler_json(EXEMPLOS / f"{tipo}.json")
    dados = exemplo["dados"]
    dados["canal"] = canal
    dados.pop("decidido_por", None)
    if decidido_por is not None:
        dados["decidido_por"] = decidido_por
    schema = validador(asyncapi["components"]["messages"][tipo]["payload"]["schema"])

    assert schema.is_valid(exemplo) is valido


def texto(n: int) -> str:
    return "x" * n


# (tipo, campo do exemplo, valores aceitos, valores rejeitados). quantidade,
# codigo, dinheiro e uri vem de $defs iguais em varios schemas (outro teste
# garante que as copias nao divergem): um tipo de cada basta.
FRONTEIRAS: list[tuple[str, str, list[Any], list[Any]]] = [
    ("GerarOrcamento", "dados/itens/0/quantidade", [1, 1000], [0, 1001, 1.5, "1"]),
    (
        "GerarOrcamento",
        "dados/itens/0/codigo",
        ["A", "A.b_c-9", texto(50)],
        ["", texto(51), "-A", "A B", "ÁB", "A/B"],
    ),
    (
        "PagamentoConfirmado",
        "dados/valor",
        ["0.50", "9999999999.99"],
        ["10000000000.00", "01.00", "1.5", "1.234", "-1.00", 1.5],
    ),
    (
        "PagamentoConfirmado",
        "dados/referencia_provedor",
        ["x", texto(100)],
        ["", texto(101)],
    ),
    ("PagamentoRecusado", "dados/motivo", ["x", texto(500)], ["", texto(501)]),
    (
        "OrcamentoGerado",
        "dados/link_decisao",
        ["http://billing.local/p", "https://x/" + "a" * 2038],
        ["https://x/" + "a" * 2039, "https://x/a b"],
    ),
    (
        "OrcamentoGerado",
        "dados/linhas/0/descricao",
        ["x", texto(255)],
        ["", texto(256)],
    ),
    ("DiagnosticoConcluido", "dados/observacoes", ["", texto(2000)], [texto(2001)]),
    ("ExecucaoAgendada", "dados/posicao_na_fila", [1, 2], [0, -1, 1.5, "1"]),
    ("ReservaDePecasFalhou", "dados/faltantes/0/disponivel", [0, 5], [-1, 0.5, "0"]),
    (
        "SolicitarDiagnostico",
        "dados/descricao_problema",
        ["x", texto(2000)],
        ["", texto(2001)],
    ),
    (
        "SolicitarDiagnostico",
        "dados/veiculo/marca",
        ["x", texto(100)],
        ["", texto(101)],
    ),
    (
        "SolicitarDiagnostico",
        "dados/veiculo/modelo",
        ["x", texto(100)],
        ["", texto(101)],
    ),
    ("SolicitarDiagnostico", "dados/veiculo/ano", [1887, 2026], [1886, 2026.5, "2026"]),
    (
        "SolicitarDiagnostico",
        "dados/veiculo/placa",
        ["ABC1234", "ABC1D23"],
        ["abc1234", "ABC123", "ABC12345", " ABC1234", "ABC1234 ", "AB1C234"],
    ),
]


@pytest.mark.parametrize(
    ("tipo", "caminho", "aceitos", "rejeitados"),
    FRONTEIRAS,
    ids=[f"{t}-{c.removeprefix('dados/')}" for t, c, *_ in FRONTEIRAS],
)
def test_limite_aceita_o_valor_na_fronteira_e_rejeita_o_seguinte(
    asyncapi: dict[str, Any],
    tipo: str,
    caminho: str,
    aceitos: list[Any],
    rejeitados: list[Any],
) -> None:
    exemplo = ler_json(EXEMPLOS / f"{tipo}.json")
    schema = validador(asyncapi["components"]["messages"][tipo]["payload"]["schema"])

    def valido(valor: Any) -> bool:
        return schema.is_valid(_mudar(exemplo, caminho, valor))

    assert [v for v in aceitos if not valido(v)] == []
    assert [v for v in rejeitados if valido(v)] == []


NAO_OBJETOS: tuple[Any, ...] = (None, True, 3, "x", [])


@pytest.mark.parametrize("tipo", CATALOGO)
def test_schema_de_dados_so_aceita_objeto(tipo: str) -> None:
    schema = validador(ler_json(SCHEMAS / f"{tipo}.schema.json"))

    assert [v for v in NAO_OBJETOS if schema.is_valid(v)] == []


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("origem", "outro-service"),
        ("versao", 0),
        ("versao", 1.5),
        ("versao", "1"),
        ("tipo", "gerarOrcamento"),
        ("tipo", " GerarOrcamento"),
        ("tipo", "GerarOrcamento!"),
        ("tipo", 5),
        ("dados", "x"),
        ("dados", []),
        ("dados", None),
    ],
)
def test_envelope_rejeita_o_que_a_rfc_nao_define(campo: str, valor: Any) -> None:
    envelope = validador(ler_json(SCHEMAS / "envelope.schema.json"))
    exemplo = ler_json(EXEMPLOS / "GerarOrcamento.json")

    assert not envelope.is_valid(_mudar(exemplo, campo, valor))


def test_envelope_so_aceita_objeto_e_so_os_tres_servicos_como_origem() -> None:
    schema = ler_json(SCHEMAS / "envelope.schema.json")
    envelope = validador(schema)

    assert [v for v in NAO_OBJETOS if envelope.is_valid(v)] == []
    assert schema["properties"]["origem"]["enum"] == list(ORIGEM.values())


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
    # Uma tentativa por fila de retry: x-tentativa n vem de <fila>.retry.<n-esimo
    # atraso>s.
    assert headers["x-tentativa"] | {"description": ""} == {
        "type": "integer",
        "minimum": 1,
        "maximum": len(ATRASOS),
        "description": "",
    }
    for tipo, mensagem in asyncapi["components"]["messages"].items():
        assert mensagem["traits"] == [
            {"$ref": "#/components/messageTraits/envelope"}
        ], tipo


def test_atrasos_do_retry_sao_os_da_rfc_e_os_do_asyncapi(
    asyncapi: dict[str, Any],
) -> None:
    # O consumidor escolhe a fila de retry pela tentativa: a tabela de
    # parametros da RFC (10.3) e o header x-tentativa do AsyncAPI dizem os
    # mesmos atrasos, na mesma ordem, que as filas do definitions.json.
    (linha,) = [
        linha
        for linha in RFC.read_text(encoding="utf-8").splitlines()
        if linha.startswith("| atrasos das filas de retry |")
    ]
    tentativa = asyncapi["components"]["messageTraits"]["envelope"]["headers"][
        "properties"
    ]["x-tentativa"]["description"]

    assert [int(n) for n in re.findall(r"\d+", linha.split("|")[2])] == list(ATRASOS)
    assert [int(n) for n in re.findall(r"\.retry\.(\d+)s", tentativa)] == list(ATRASOS)


def test_asyncapi_lista_as_filas_de_retry_e_a_dlq_de_cada_fila(
    asyncapi: dict[str, Any], definitions: dict[str, Any]
) -> None:
    # O consumidor le no contrato para onde vai a copia: o info.description
    # cita os atrasos das filas de retry, e a descricao de cada canal de fila,
    # as filas de retry e a DLQ dela que o definitions.json declara, nem mais
    # nem menos.
    filas = [q["name"] for q in definitions["queues"]]
    atrasos = {int(m[1]) for f in filas if (m := re.fullmatch(r".+\.retry\.(\d+)s", f))}
    info = asyncapi["info"]["description"]

    assert {int(n) for n in re.findall(r"\.retry\.(\d+)s", info)} == atrasos
    for fila in FILAS_DE_TRABALHO:
        descricao = asyncapi["channels"][fila]["description"]
        citadas = re.findall(rf"{re.escape(fila)}\.(?:retry\.\d+s|dlq)\b", descricao)
        assert sorted(citadas) == sorted(f for f in filas if f.startswith(f"{fila}."))


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
