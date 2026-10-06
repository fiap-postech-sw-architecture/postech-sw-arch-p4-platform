"""Contratos de mensageria: catalogo, AsyncAPI, JSON Schemas, exemplos e topologia.

O catalogo abaixo e a secao 4 do design brief da fase 4, mais AnonimizarVeiculo
e PagamentoCancelado, decididos na revisao de arquitetura. Os testes amarram as
quatro fontes que os servicos copiam (asyncapi.yaml, schemas/, exemplos/ e o
definitions.json do RabbitMQ) para que nenhuma divirja das outras.
"""

from __future__ import annotations

import copy
import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError
from referencing import Registry, Resource

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
def test_exemplo_valido_contra_payload_da_mensagem_no_asyncapi(
    asyncapi: dict[str, Any], tipo: str
) -> None:
    payload = asyncapi["components"]["messages"][tipo]["payload"]

    assert payload["schemaFormat"] == "application/schema+json;version=draft-2020-12"
    validador(payload["schema"]).validate(ler_json(EXEMPLOS / f"{tipo}.json"))


def test_referencias_do_asyncapi_resolvem(asyncapi: dict[str, Any]) -> None:
    assert refs(asyncapi), "o documento deveria ter referencias"
    assert refs_quebradas(asyncapi) == []


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
    resolver_ponteiro(mudado, "/".join(pais))[ultimo] = valor
    return mudado


@pytest.mark.parametrize(
    ("tipo", "caminho", "valor"),
    [
        ("PagamentoConfirmado", "dados/valor", 820.0),
        ("PagamentoConfirmado", "dados/valor", "820"),
        ("OrcamentoGerado", "dados/moeda", "USD"),
        ("SolicitarDiagnostico", "dados/veiculo/placa", "ABC-1234"),
        ("OrcamentoAprovado", "dados/canal", "email"),
        ("DiagnosticoConcluido", "dados/itens", []),
        ("GerarOrcamento", "dados/itens/0/codigo", "X" * 51),
        ("DiagnosticoConcluido", "dados/campo_novo", "x"),
        ("GerarOrcamento", "correlation_id", "123"),
        ("GerarOrcamento", "ocorrido_em", "2026-10-06T12:00:00"),
        ("GerarOrcamento", "ocorrido_em", "2026-10-06T09:00:00-03:00"),
        ("GerarOrcamento", "ocorrido_em", "2026-13-45T12:00:00Z"),
        ("PagamentoSolicitado", "dados/checkout_url", "nao e uma url"),
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

    assert {"uuid", "data_hora", "dinheiro", "codigo", "motivo"} <= set(vistos)
    assert sem_descricao(envelope["ocorrido_em"]) == sem_descricao(vistos["data_hora"])


def test_exemplo_de_orcamento_fecha_a_conta_em_decimal() -> None:
    dados = ler_json(EXEMPLOS / "OrcamentoGerado.json")["dados"]
    subtotais = [Decimal(linha["subtotal"]) for linha in dados["linhas"]]

    for linha, subtotal in zip(dados["linhas"], subtotais, strict=True):
        assert subtotal == linha["quantidade"] * Decimal(linha["preco_unitario"])
    assert Decimal(dados["total"]) == sum(subtotais, Decimal(0))
