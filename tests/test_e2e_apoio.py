"""Codigo auxiliar do E2E (e2e/apoio) sem cluster: espera, mascara, dados, parsers.

O que o E2E faz de critico fora do cluster e testado aqui: a espera por
polling com prazo, a mascara de segredos, o parser do Mailpit e do Jaeger, a
leitura de metricas e das DLQs, o desfazer do ``kubectl scale`` e o resumo.
Os falsos sao injetados (relogio, executor do kubectl, transporte HTTP); o
unico processo real e o do ``executar_processo`` e o do port-forward falso.
"""

from __future__ import annotations

import json
import random
import re
import stat
import subprocess  # nosec B404
import sys
from typing import TYPE_CHECKING, Any

import httpx
import pytest

from e2e.apoio import dados, segredos
from e2e.apoio.espera import TempoEsgotadoError, esperar, manter
from e2e.apoio.http import (
    Cliente,
    RespostaInesperadaError,
    verificar_tls,
)
from e2e.apoio.jaeger import Jaeger, melhor_trace, servicos_do_trace
from e2e.apoio.kube import (
    ErroDeComandoError,
    Escalas,
    Kubectl,
    PortForward,
    executar_processo,
    ler_filas_mortas,
)
from e2e.apoio.mailpit import (
    Mailpit,
    extrair_checkout,
    extrair_link_de_decisao,
)
from e2e.apoio.metricas import valor_da_serie
from e2e.apoio.relatorio import (
    Registro,
    escrever_resumo,
    gerar_resumo,
    principal,
)
from e2e.apoio.texto import sem_acentos

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence
    from pathlib import Path


class Relogio:
    """Relogio e ``dormir`` falsos: dormir avanca o tempo sem esperar de verdade."""

    def __init__(self) -> None:
        self.agora = 100.0
        self.dormidas: list[float] = []

    def __call__(self) -> float:
        return self.agora

    def dormir(self, segundos: float) -> None:
        self.dormidas.append(segundos)
        self.agora += segundos


@pytest.fixture
def relogio() -> Relogio:
    return Relogio()


@pytest.fixture(autouse=True)
def _sem_segredos_registrados() -> Iterator[None]:
    segredos.esquecer_todos()
    yield
    segredos.esquecer_todos()


# --- espera -----------------------------------------------------------------


def test_esperar_condicao_pronta_devolve_sem_dormir(relogio: Relogio) -> None:
    resultado = esperar(
        lambda: "pronto",
        prazo=10,
        descricao="x",
        relogio=relogio,
        dormir=relogio.dormir,
    )

    assert resultado == "pronto"
    assert relogio.dormidas == []


def test_esperar_devolve_o_primeiro_valor_verdadeiro(relogio: Relogio) -> None:
    respostas = iter([None, 0, "", {"ok": 1}, "nunca"])

    resultado = esperar(
        lambda: next(respostas),
        prazo=10,
        intervalo=2,
        descricao="x",
        relogio=relogio,
        dormir=relogio.dormir,
    )

    assert resultado == {"ok": 1}
    assert relogio.dormidas == [2, 2, 2]


def test_esperar_prazo_esgotado_reprova_com_descricao_e_ultimo_valor(
    relogio: Relogio,
) -> None:
    with pytest.raises(TempoEsgotadoError) as erro:
        esperar(
            lambda: [],
            prazo=5,
            intervalo=2,
            descricao="OS em aguardando_pagamento",
            relogio=relogio,
            dormir=relogio.dormir,
        )

    assert "OS em aguardando_pagamento" in str(erro.value)
    assert "5 s" in str(erro.value)
    assert "ultimo valor: []" in str(erro.value)


def test_esperar_nunca_dorme_alem_do_prazo(relogio: Relogio) -> None:
    with pytest.raises(TempoEsgotadoError):
        esperar(
            lambda: False,
            prazo=5,
            intervalo=2,
            descricao="x",
            relogio=relogio,
            dormir=relogio.dormir,
        )

    # 2 + 2 + 1: a ultima soneca e cortada no que resta do prazo.
    assert relogio.dormidas == [2, 2, 1]
    assert relogio.agora == 105.0


def test_esperar_avalia_uma_ultima_vez_no_fim_do_prazo(relogio: Relogio) -> None:
    chamadas: list[float] = []

    def condicao() -> bool:
        chamadas.append(relogio.agora)
        return relogio.agora >= 105.0

    assert esperar(
        condicao,
        prazo=5,
        intervalo=2,
        descricao="x",
        relogio=relogio,
        dormir=relogio.dormir,
    )
    assert chamadas[-1] == 105.0


def test_esperar_prazo_zero_ainda_avalia_uma_vez(relogio: Relogio) -> None:
    chamadas = []

    def condicao() -> bool:
        chamadas.append(1)
        return False

    with pytest.raises(TempoEsgotadoError):
        esperar(
            condicao, prazo=0, descricao="x", relogio=relogio, dormir=relogio.dormir
        )

    assert len(chamadas) == 1
    assert relogio.dormidas == []


def test_esperar_ignora_so_as_excecoes_listadas(relogio: Relogio) -> None:
    tentativas: Iterator[Exception | str] = iter(
        [ConnectionError("reset"), ConnectionError("reset"), "ok"]
    )

    def condicao() -> str:
        item = next(tentativas)
        if isinstance(item, Exception):
            raise item
        return item

    resultado = esperar(
        condicao,
        prazo=10,
        ignorar=(ConnectionError,),
        descricao="x",
        relogio=relogio,
        dormir=relogio.dormir,
    )

    assert resultado == "ok"


def test_esperar_excecao_nao_listada_propaga(relogio: Relogio) -> None:
    def condicao() -> bool:
        raise KeyError("bug")

    with pytest.raises(KeyError):
        esperar(
            condicao,
            prazo=10,
            ignorar=(ConnectionError,),
            descricao="x",
            relogio=relogio,
            dormir=relogio.dormir,
        )


def test_esperar_excecao_ignorada_aparece_na_mensagem_do_prazo(
    relogio: Relogio,
) -> None:
    def condicao() -> bool:
        raise ConnectionError("conexao recusada")

    with pytest.raises(TempoEsgotadoError, match="ConnectionError: conexao recusada"):
        esperar(
            condicao,
            prazo=2,
            ignorar=(ConnectionError,),
            descricao="x",
            relogio=relogio,
            dormir=relogio.dormir,
        )


def test_esperar_mensagem_de_prazo_sai_mascarada(relogio: Relogio) -> None:
    segredos.registrar("senha-super-secreta")

    def condicao() -> bool:
        raise ConnectionError("recusou a senha-super-secreta")

    with pytest.raises(TempoEsgotadoError) as erro:
        esperar(
            condicao,
            prazo=1,
            ignorar=(ConnectionError,),
            descricao="x",
            relogio=relogio,
            dormir=relogio.dormir,
        )

    assert "senha-super-secreta" not in str(erro.value)
    assert "recusou a ***" in str(erro.value)


def test_manter_condicao_sempre_verdadeira_dura_a_janela_inteira(
    relogio: Relogio,
) -> None:
    amostras = []

    def condicao() -> bool:
        amostras.append(relogio.agora)
        return True

    manter(
        condicao,
        duracao=20,
        intervalo=5,
        descricao="x",
        relogio=relogio,
        dormir=relogio.dormir,
    )

    assert amostras == [100.0, 105.0, 110.0, 115.0, 120.0]
    assert relogio.agora == 120.0


def test_manter_corta_a_ultima_soneca_no_fim_da_janela(relogio: Relogio) -> None:
    manter(
        lambda: True,
        duracao=7,
        intervalo=5,
        descricao="x",
        relogio=relogio,
        dormir=relogio.dormir,
    )

    assert relogio.dormidas == [5, 2]


def test_manter_reprova_assim_que_a_condicao_deixa_de_valer(relogio: Relogio) -> None:
    estados = iter([True, True, False])

    with pytest.raises(TempoEsgotadoError, match="deixou de valer antes de 20 s"):
        manter(
            lambda: next(estados),
            duracao=20,
            intervalo=5,
            descricao="OS parada",
            relogio=relogio,
            dormir=relogio.dormir,
        )

    assert relogio.agora == 110.0


# --- segredos ---------------------------------------------------------------


def test_mascarar_troca_segredo_registrado() -> None:
    segredos.registrar("abcdef123456")

    assert segredos.mascarar("senha=abcdef123456 fim") == "senha=*** fim"


def test_mascarar_valor_curto_nao_e_registrado() -> None:
    segredos.registrar("abc")

    assert segredos.mascarar("abc abc") == "abc abc"


def test_mascarar_o_maior_segredo_primeiro() -> None:
    segredos.registrar("segredo-longo")
    segredos.registrar("segredo-longo-demais")

    assert segredos.mascarar("x segredo-longo-demais y") == "x *** y"


def test_mascarar_segredo_de_varias_linhas_mascara_cada_linha() -> None:
    segredos.registrar("linha-um-123\nlinha-dois-456\nab")

    assert (
        segredos.mascarar("a linha-um-123 b linha-dois-456 c ab") == "a *** b *** c ab"
    )


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        (
            "https://localhost/billing/api/v1/publico/orcamentos/abc.123.XYZ-_/decisao",
            "https://localhost/billing/api/v1/publico/orcamentos/***/decisao",
        ),
        (
            "POST /billing/api/v1/publico/orcamentos/tok.en-1_2",
            "POST /billing/api/v1/publico/orcamentos/***",
        ),
        (
            "https://localhost/billing/simulador/checkout/84ea5cc1?token=abc123&x=1",
            "https://localhost/billing/simulador/checkout/84ea5cc1?token=***&x=1",
        ),
        ("/aprovar?token=segredo", "/aprovar?token=***"),
        ("Authorization: Bearer abc.def-ghi", "Authorization: Bearer ***"),
        (
            "token eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiIxIn0.c2ln fim",
            "token *** fim",
        ),
        ("sem credencial nenhuma", "sem credencial nenhuma"),
    ],
)
def test_mascarar_padroes_de_credencial(entrada: str, esperado: str) -> None:
    assert segredos.mascarar(entrada) == esperado


def test_registrar_no_actions_pede_ao_runner_que_mascare(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr(sys, "__stdout__", sys.stdout)

    segredos.registrar("senha-do-admin-123")

    assert capsys.readouterr().out == "::add-mask::senha-do-admin-123\n"


def test_registrar_fora_do_actions_nao_imprime_o_segredo(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr(sys, "__stdout__", sys.stdout)

    segredos.registrar("senha-do-admin-123")

    assert capsys.readouterr().out == ""
    assert segredos.mascarar("senha-do-admin-123") == "***"


# --- dados ------------------------------------------------------------------


def _rng(semente: int) -> random.Random:
    return random.Random(semente)  # noqa: S311  # nosec B311


def _cpf_confere(cpf: str) -> bool:
    """Verificador independente do CPF (modulo 11), escrito a parte do gerador."""
    digitos = [int(c) for c in cpf]
    for n in (9, 10):
        soma = sum(d * p for d, p in zip(digitos[:n], range(n + 1, 1, -1), strict=True))
        if digitos[n] != (soma * 10 % 11) % 10:
            return False
    return len(cpf) == 11 and len(set(cpf)) > 1


def test_cpf_valido_passa_no_modulo_11_em_muitas_sementes() -> None:
    for semente in range(300):
        cpf = dados.cpf_valido(_rng(semente))
        assert _cpf_confere(cpf), cpf


def test_cpf_invalido_reprova_no_modulo_11_em_muitas_sementes() -> None:
    for semente in range(300):
        cpf = dados.cpf_invalido(_rng(semente))
        assert len(cpf) == 11
        assert not _cpf_confere(cpf), cpf


def test_cpf_valido_sorteia_de_novo_quando_a_base_tem_digitos_iguais() -> None:
    sorteios = iter([7] * 9 + [5, 2, 9, 9, 8, 2, 2, 4, 7])

    class Falso:
        def randrange(self, _: int) -> int:
            return next(sorteios)

    assert dados.cpf_valido(Falso()) == "52998224725"  # type: ignore[arg-type]


def test_cpf_conhecido_confere_com_o_verificador() -> None:
    assert _cpf_confere("52998224725")
    assert not _cpf_confere("52998224724")
    assert not _cpf_confere("11111111111")


def test_placa_mercosul_segue_o_padrao_e_nao_e_a_sentinela() -> None:
    for semente in range(200):
        placa = dados.placa_mercosul(_rng(semente))
        assert re.fullmatch(r"[A-Z]{3}\d[A-Z]\d{2}", placa)
        assert placa != "AAA0A00"


def test_placa_mercosul_descarta_a_sentinela() -> None:
    sorteios = iter(
        [
            *"AAA",  # letras
            0,
            *"A",
            0,  # 0A00 -> a sentinela
            *"BRA",
            2,
            *"E",
            19,
        ]
    )

    class Falso:
        def choice(self, _: str) -> str:
            return str(next(sorteios))

        def randrange(self, _: int) -> int:
            return int(next(sorteios))

    placa = dados.placa_mercosul(Falso())  # type: ignore[arg-type]  # falso de duas chamadas

    assert placa == "BRA2E19"


def test_codigo_segue_o_padrao_do_billing_e_do_estoque() -> None:
    padrao = r"^[A-Z0-9]+(?:-[A-Z0-9]+)*$"
    ident = dados.id_da_execucao()

    servico = dados.codigo("SRV", ident, 4)
    peca = dados.codigo("PEC", ident, 4)

    assert re.fullmatch(padrao, servico)
    assert re.fullmatch(padrao, peca)
    assert servico == f"SRV-E2E-{ident}-4"
    assert peca == f"PEC-E2E-{ident}-4"
    assert len(servico) <= 50


def test_id_da_execucao_tem_seis_hexadecimais_maiusculos() -> None:
    assert re.fullmatch(r"[0-9A-F]{6}", dados.id_da_execucao())


def test_emails_levam_a_execucao_e_o_numero() -> None:
    assert (
        dados.email_de_usuario("3FA9C1", "atendente")
        == "e2e-3fa9c1-atendente@e2e.pytstop.dev"
    )
    assert (
        dados.email_de_cliente("3FA9C1", 7) == "cliente-3fa9c1-7@clientes.pytstop.dev"
    )


def test_senha_aleatoria_tem_32_hexadecimais_e_muda() -> None:
    primeira, segunda = dados.senha_aleatoria(), dados.senha_aleatoria()

    assert re.fullmatch(r"[0-9a-f]{32}", primeira)
    assert primeira != segunda


# --- http -------------------------------------------------------------------


def _cliente(
    tratador: Callable[[httpx.Request], httpx.Response],
    relogio: Relogio,
    **opcoes: Any,
) -> Cliente:
    return Cliente(
        "http://servico.local",
        transporte=httpx.MockTransport(tratador),
        relogio=relogio,
        dormir=relogio.dormir,
        **opcoes,
    )


def test_pedir_manda_o_token_como_bearer(relogio: Relogio) -> None:
    vistos: list[httpx.Request] = []

    def tratador(pedido: httpx.Request) -> httpx.Response:
        vistos.append(pedido)
        return httpx.Response(200, json={"ok": True})

    resposta = _cliente(tratador, relogio).pedir("GET", "/x", token="t0k3n")  # noqa: S106  # nosec B106

    assert resposta.json() == {"ok": True}
    assert vistos[0].headers["authorization"] == "Bearer t0k3n"


def test_fechar_encerra_o_cliente_http(relogio: Relogio) -> None:
    cliente = _cliente(lambda _: httpx.Response(200), relogio)

    cliente.fechar()

    with pytest.raises(RuntimeError, match="closed"):
        cliente.pedir("GET", "/x")


def test_pedir_sem_token_nao_manda_authorization(relogio: Relogio) -> None:
    vistos: list[httpx.Request] = []

    def tratador(pedido: httpx.Request) -> httpx.Response:
        vistos.append(pedido)
        return httpx.Response(200)

    _cliente(tratador, relogio).pedir("GET", "/x")

    assert "authorization" not in vistos[0].headers


def test_pedir_envia_json_e_parametros(relogio: Relogio) -> None:
    vistos: list[httpx.Request] = []

    def tratador(pedido: httpx.Request) -> httpx.Response:
        vistos.append(pedido)
        return httpx.Response(201)

    _cliente(tratador, relogio).pedir("POST", "/x", json={"a": 1}, params={"q": "v"})

    assert json.loads(vistos[0].content) == {"a": 1}
    assert vistos[0].url.params["q"] == "v"


def test_pedir_status_fora_do_esperado_reprova_sem_vazar_credencial(
    relogio: Relogio,
) -> None:
    def tratador(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            409,
            headers={"x-request-id": "req-1"},
            json={"link": "https://h/api/v1/publico/orcamentos/SEGREDO.tok"},
        )

    with pytest.raises(RespostaInesperadaError) as erro:
        _cliente(tratador, relogio).pedir("POST", "/x", esperado=[200, 201])

    mensagem = str(erro.value)
    assert "HTTP 409" in mensagem
    assert "[200, 201]" in mensagem
    assert "req-1" in mensagem
    assert "SEGREDO" not in mensagem


def test_pedir_status_esperado_nao_levanta(relogio: Relogio) -> None:
    resposta = _cliente(lambda _: httpx.Response(204), relogio).pedir(
        "DELETE", "/x", esperado=(204,)
    )

    assert resposta.status_code == 204


def test_pedir_sem_esperado_devolve_qualquer_status(relogio: Relogio) -> None:
    resposta = _cliente(lambda _: httpx.Response(503), relogio).pedir("GET", "/x")

    assert resposta.status_code == 503


def test_pedir_429_espera_a_janela_e_tenta_de_novo(relogio: Relogio) -> None:
    respostas = iter([429, 429, 200])

    def tratador(_: httpx.Request) -> httpx.Response:
        return httpx.Response(next(respostas))

    resposta = _cliente(tratador, relogio, intervalo_429=5).pedir(
        "GET", "/x", esperado=[200]
    )

    assert resposta.status_code == 200
    assert relogio.dormidas == [5, 5]


def test_pedir_429_respeita_o_retry_after(relogio: Relogio) -> None:
    respostas = iter(
        [httpx.Response(429, headers={"retry-after": "12"}), httpx.Response(200)]
    )

    _cliente(lambda _: next(respostas), relogio).pedir("GET", "/x", esperado=[200])

    assert relogio.dormidas == [12]


def test_pedir_429_retry_after_invalido_usa_o_intervalo(relogio: Relogio) -> None:
    respostas = iter(
        [httpx.Response(429, headers={"retry-after": "logo"}), httpx.Response(200)]
    )

    _cliente(lambda _: next(respostas), relogio, intervalo_429=3).pedir("GET", "/x")

    assert relogio.dormidas == [3]


def test_pedir_429_desiste_quando_a_janela_acaba(relogio: Relogio) -> None:
    chamadas = []

    def tratador(_: httpx.Request) -> httpx.Response:
        chamadas.append(1)
        return httpx.Response(429, json={"erro": {"codigo": "RATE_LIMIT_EXCEDIDO"}})

    with pytest.raises(RespostaInesperadaError, match="HTTP 429"):
        _cliente(tratador, relogio, espera_429=12, intervalo_429=5).pedir(
            "POST", "/x", esperado=[200]
        )

    # 5 + 5 + 2: a ultima espera e cortada no que resta da janela.
    assert relogio.dormidas == [5, 5, 2]
    assert len(chamadas) == 4


@pytest.mark.parametrize(
    ("url", "verifica"),
    [
        ("https://localhost", False),
        ("https://127.0.0.1:8443", False),
        ("https://[::1]", False),
        ("https://localhost.evil.example", True),
        ("https://exemplo.com.br", True),
        ("https://10.0.0.5", True),
    ],
)
def test_verificar_tls_so_dispensa_para_localhost(url: str, verifica: bool) -> None:
    assert verificar_tls(url) is verifica


# --- metricas ---------------------------------------------------------------

_METRICAS = """\
# HELP pytstop_circuit_breaker_aberto 1 com o circuito aberto
# TYPE pytstop_circuit_breaker_aberto gauge
pytstop_circuit_breaker_aberto{dependencia="jwks"} 0.0
pytstop_circuit_breaker_aberto{dependencia="billing"} 0.5
pytstop_http_requests_total{metodo="GET",status="200"} 12.0
pytstop_http_requests_total{status="200",metodo="POST"} 3.0
pytstop_sem_rotulo 7
"""


def test_valor_da_serie_acha_pelo_rotulo() -> None:
    assert (
        valor_da_serie(
            _METRICAS, "pytstop_circuit_breaker_aberto", dependencia="billing"
        )
        == 0.5
    )
    assert (
        valor_da_serie(_METRICAS, "pytstop_circuit_breaker_aberto", dependencia="jwks")
        == 0.0
    )


def test_valor_da_serie_ignora_a_ordem_dos_rotulos() -> None:
    assert (
        valor_da_serie(
            _METRICAS, "pytstop_http_requests_total", status="200", metodo="POST"
        )
        == 3.0
    )


def test_valor_da_serie_exige_o_conjunto_exato_de_rotulos() -> None:
    assert (
        valor_da_serie(_METRICAS, "pytstop_http_requests_total", metodo="GET") is None
    )


def test_valor_da_serie_sem_rotulo_e_inexistente() -> None:
    assert valor_da_serie(_METRICAS, "pytstop_sem_rotulo") == 7.0
    assert valor_da_serie(_METRICAS, "pytstop_nao_existe") is None
    assert (
        valor_da_serie(_METRICAS, "pytstop_circuit_breaker_aberto", dependencia="x")
        is None
    )


def test_valor_da_serie_nome_e_prefixo_de_outro_nao_casa() -> None:
    texto = 'pytstop_circuit_breaker_aberto_total{dependencia="billing"} 9.0\n'

    assert (
        valor_da_serie(texto, "pytstop_circuit_breaker_aberto", dependencia="billing")
        is None
    )


# --- mailpit ----------------------------------------------------------------

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


def test_extrair_checkout_do_corpo_do_email() -> None:
    assert extrair_checkout(_CORPO_PAGAMENTO) == (
        "https://localhost/billing/simulador/checkout/84ea5cc1?token=abc.def"
    )
    assert extrair_checkout(_CORPO_ORCAMENTO) is None


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
        Cliente(
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


# --- jaeger -----------------------------------------------------------------


def _trace(identificador: str, servicos: Sequence[str], spans: int) -> dict[str, Any]:
    return {
        "traceID": identificador,
        "spans": [{"spanID": str(i)} for i in range(spans)],
        "processes": {
            f"p{i}": {"serviceName": nome} for i, nome in enumerate(servicos)
        },
    }


def test_servicos_do_trace_une_os_processos() -> None:
    trace = _trace("t1", ["os-service", "billing-service", "os-service"], 3)

    assert servicos_do_trace(trace) == {"os-service", "billing-service"}
    assert servicos_do_trace({"traceID": "vazio"}) == set()


def test_melhor_trace_escolhe_o_completo_com_mais_spans() -> None:
    todos = ["os-service", "billing-service", "execution-service"]
    traces = [
        _trace("curto", ["os-service", "billing-service"], 50),
        _trace("completo-pequeno", todos, 5),
        _trace("completo-grande", todos, 45),
    ]

    escolhido = melhor_trace(traces)

    assert escolhido is not None
    assert escolhido["traceID"] == "completo-grande"


def test_melhor_trace_sem_trace_completo_devolve_none() -> None:
    assert melhor_trace([_trace("t", ["os-service"], 3)]) is None
    assert melhor_trace([]) is None


def test_jaeger_traces_da_ordem_consulta_cada_servico_e_junta_sem_repetir(
    relogio: Relogio,
) -> None:
    consultas: list[httpx.Request] = []

    def tratador(pedido: httpx.Request) -> httpx.Response:
        consultas.append(pedido)
        return httpx.Response(200, json={"data": [_trace("t1", ["os-service"], 1)]})

    jaeger = Jaeger(
        Cliente(
            "http://jaeger.local",
            transporte=httpx.MockTransport(tratador),
            relogio=relogio,
        )
    )

    traces = jaeger.traces_da_ordem("ordem-1")

    assert [t["traceID"] for t in traces] == ["t1"]
    assert [c.url.params["service"] for c in consultas] == [
        "os-service",
        "billing-service",
        "execution-service",
    ]
    assert json.loads(consultas[0].url.params["tags"]) == {
        "messaging.message.conversation_id": "ordem-1"
    }


def test_jaeger_resposta_sem_data_vira_lista_vazia(relogio: Relogio) -> None:
    jaeger = Jaeger(
        Cliente(
            "http://jaeger.local",
            transporte=httpx.MockTransport(
                lambda _: httpx.Response(200, json={"data": None})
            ),
            relogio=relogio,
        )
    )

    assert jaeger.traces_da_ordem("ordem-1") == []


# --- kubectl ----------------------------------------------------------------


class ExecutorFalso:
    """Registra os comandos e responde pelo ultimo argumento ou por uma tabela."""

    def __init__(self, respostas: dict[str, str] | None = None) -> None:
        self.comandos: list[list[str]] = []
        self.respostas = respostas or {}
        self.pods: list[list[str]] = []

    def __call__(self, argumentos: Sequence[str], prazo: float) -> str:
        comando = list(argumentos)
        self.comandos.append(comando)
        for trecho, resposta in self.respostas.items():
            if trecho in " ".join(comando):
                return resposta
        return ""


def test_kubectl_executar_sempre_leva_o_contexto() -> None:
    executor = ExecutorFalso()

    Kubectl("kind-teste", executor=executor).executar("get", "pods")

    assert executor.comandos == [["kubectl", "--context", "kind-teste", "get", "pods"]]


def test_kubectl_segredo_decodifica_o_base64() -> None:
    executor = ExecutorFalso({"get secret": "c2VuaGEtMTIz\n"})

    valor = Kubectl("c", executor=executor).segredo(
        "pytstop-os", "os-admin", "ADMIN_PASSWORD"
    )

    assert valor == "senha-123"
    assert "jsonpath={.data.ADMIN_PASSWORD}" in executor.comandos[0]
    assert executor.comandos[0][3:5] == ["-n", "pytstop-os"]


def test_kubectl_valor_de_configmap_pega_o_primeiro_valor_nao_vazio() -> None:
    executor = ExecutorFalso({"configmap": "admin@pytstop.dev"})

    assert Kubectl("c", executor=executor).valor_de_configmap(
        "pytstop-os", "ADMIN_EMAIL"
    ) == ("admin@pytstop.dev")
    assert (
        Kubectl("c", executor=ExecutorFalso()).valor_de_configmap("pytstop-os", "X")
        is None
    )


def test_kubectl_replicas_le_o_spec() -> None:
    assert (
        Kubectl(
            "c", executor=ExecutorFalso({"jsonpath={.spec.replicas}": "3"})
        ).replicas("n", "d")
        == 3
    )
    assert Kubectl("c", executor=ExecutorFalso()).replicas("n", "d") == 0


def test_kubectl_escalar_monta_o_comando() -> None:
    executor = ExecutorFalso()

    Kubectl("c", executor=executor).escalar("pytstop-billing", "billing-service-api", 0)

    assert executor.comandos[0][3:] == [
        "-n",
        "pytstop-billing",
        "scale",
        "deployment/billing-service-api",
        "--replicas=0",
    ]


def test_kubectl_pods_seleciona_pelo_label_app() -> None:
    executor = ExecutorFalso({"get pods": "pod/a pod/b\n"})

    assert Kubectl("c", executor=executor).pods("ns", "app-x") == ["pod/a", "pod/b"]
    assert "app=app-x" in executor.comandos[0]


def test_kubectl_aguardar_pronto_pede_o_rollout_com_prazo_maior_no_processo() -> None:
    prazos: list[float] = []

    def executor(argumentos: Sequence[str], prazo: float) -> str:
        prazos.append(prazo)
        assert "--timeout=120s" in argumentos
        return ""

    Kubectl("c", executor=executor).aguardar_pronto("ns", "dep")

    assert prazos == [150.0]


def test_kubectl_logs_pede_todos_os_pods_sem_corte() -> None:
    executor = ExecutorFalso({"logs": "linha"})

    assert (
        Kubectl("c", executor=executor).logs("ns", "app-x", container="api", desde="3m")
        == "linha"
    )
    comando = " ".join(executor.comandos[0])
    assert "-l app=app-x" in comando
    assert "-c api" in comando
    assert "--since=3m" in comando
    assert "--tail=-1" in comando


_SAIDA_FILAS = """\
os.eventos\t0
os.eventos.dlq\t0
billing.comandos.dlq\t2
execucao.comandos.dlq\t11
billing.comandos.retry.5s\t1
linha com mais colunas aqui
"""


def test_ler_filas_mortas_so_pega_as_dlq() -> None:
    assert ler_filas_mortas(_SAIDA_FILAS) == {
        "os.eventos.dlq": 0,
        "billing.comandos.dlq": 2,
        "execucao.comandos.dlq": 11,
    }
    assert ler_filas_mortas("") == {}
    assert ler_filas_mortas("x.dlq\tmuitas") == {}


def test_kubectl_filas_mortas_executa_no_pod_do_broker() -> None:
    executor = ExecutorFalso({"rabbitmqctl": _SAIDA_FILAS})

    filas = Kubectl("c", executor=executor).filas_mortas()

    assert filas["billing.comandos.dlq"] == 2
    comando = " ".join(executor.comandos[0])
    assert (
        "-n pytstop-plataforma exec rabbitmq-0 -c rabbitmq -- rabbitmqctl -q "
        "list_queues" in comando
    )


# --- escalas (o que o cenario derruba volta no teardown) ---------------------


class ClusterFalso:
    """Deployments com replicas; escalar a 0 esvazia os pods nas consultas."""

    def __init__(self, replicas: dict[str, int], pods_demoram: int = 0) -> None:
        self.replicas = replicas
        self.comandos: list[list[str]] = []
        self._pods_demoram = pods_demoram
        self._consultas = 0

    def __call__(self, argumentos: Sequence[str], prazo: float) -> str:
        comando = list(argumentos)
        self.comandos.append(comando)
        if "scale" in comando:
            nome = comando[comando.index("scale") + 1].split("/")[1]
            self.replicas[nome] = int(comando[-1].split("=")[1])
            self._consultas = 0
        elif "pods" in comando:
            self._consultas += 1
            nome = comando[comando.index("-l") + 1].split("=")[1]
            if self.replicas[nome] == 0 and self._consultas > self._pods_demoram:
                return ""
            return "pod/x\n"
        elif "deployment" in comando and "jsonpath={.spec.replicas}" in comando:
            return str(self.replicas[comando[comando.index("deployment") + 1]])
        return ""

    def escalas(self) -> list[str]:
        return [
            " ".join(c[c.index("scale") + 1 :]) for c in self.comandos if "scale" in c
        ]

    def prontos(self) -> list[str]:
        return [c[c.index("rollout") + 2] for c in self.comandos if "rollout" in c]


def _escalas(cluster: ClusterFalso, relogio: Relogio) -> Escalas:
    return Escalas(
        Kubectl("c", executor=cluster), relogio=relogio, dormir=relogio.dormir
    )


def test_escalas_zerar_derruba_e_restaurar_volta_ao_original(relogio: Relogio) -> None:
    cluster = ClusterFalso({"billing-api": 2})
    escalas = _escalas(cluster, relogio)

    escalas.zerar("ns", "billing-api")
    assert cluster.replicas["billing-api"] == 0

    escalas.restaurar("ns", "billing-api")
    assert cluster.replicas["billing-api"] == 2
    assert cluster.escalas() == [
        "deployment/billing-api --replicas=0",
        "deployment/billing-api --replicas=2",
    ]
    assert cluster.prontos() == ["deployment/billing-api"]


def test_escalas_zerar_espera_o_ultimo_pod_sair(relogio: Relogio) -> None:
    cluster = ClusterFalso({"dep": 1}, pods_demoram=3)

    _escalas(cluster, relogio).zerar("ns", "dep")

    assert sum(1 for c in cluster.comandos if "pods" in c) == 4


def test_escalas_zerar_pod_que_nao_sai_reprova_pelo_prazo(relogio: Relogio) -> None:
    cluster = ClusterFalso({"dep": 1}, pods_demoram=10_000)

    with pytest.raises(TempoEsgotadoError, match="pods de dep encerrados"):
        _escalas(cluster, relogio).zerar("ns", "dep", prazo=10)


def test_escalas_zerar_duas_vezes_guarda_o_original_da_primeira(
    relogio: Relogio,
) -> None:
    cluster = ClusterFalso({"dep": 3})
    escalas = _escalas(cluster, relogio)

    escalas.zerar("ns", "dep")
    escalas.zerar("ns", "dep")
    escalas.restaurar("ns", "dep")

    assert cluster.replicas["dep"] == 3


def test_escalas_restaurar_o_que_nao_foi_zerado_nao_faz_nada(relogio: Relogio) -> None:
    cluster = ClusterFalso({"dep": 1})

    _escalas(cluster, relogio).restaurar("ns", "dep")

    assert cluster.comandos == []


def test_escalas_restaurar_e_idempotente(relogio: Relogio) -> None:
    cluster = ClusterFalso({"dep": 1})
    escalas = _escalas(cluster, relogio)
    escalas.zerar("ns", "dep")

    escalas.restaurar("ns", "dep")
    escalas.restaurar("ns", "dep")

    assert len(cluster.escalas()) == 2


def test_escalas_restaurar_todas_devolve_tudo_que_ficou_derrubado(
    relogio: Relogio,
) -> None:
    cluster = ClusterFalso({"a": 1, "b": 2})
    escalas = _escalas(cluster, relogio)
    escalas.zerar("ns", "a")
    escalas.zerar("ns", "b")

    restauradas = escalas.restaurar_todas()

    assert sorted(restauradas) == ["a", "b"]
    assert cluster.replicas == {"a": 1, "b": 2}
    assert escalas.restaurar_todas() == []


def test_escalas_zerar_deployment_ja_em_zero_restaura_para_um(relogio: Relogio) -> None:
    cluster = ClusterFalso({"dep": 0})
    escalas = _escalas(cluster, relogio)

    escalas.zerar("ns", "dep")
    escalas.restaurar("ns", "dep")

    assert cluster.replicas["dep"] == 1


def test_escalas_recuperar_do_inicio_religa_so_o_que_ficou_em_zero(
    relogio: Relogio,
) -> None:
    cluster = ClusterFalso({"parado": 0, "de-pe": 1})

    religados = _escalas(cluster, relogio).recuperar_do_inicio(
        [("ns", "parado"), ("ns", "de-pe")]
    )

    assert religados == [("ns", "parado")]
    assert cluster.replicas == {"parado": 1, "de-pe": 1}
    assert cluster.prontos() == ["deployment/parado"]


# --- processos de verdade ------------------------------------------------------


def test_executar_processo_devolve_a_saida() -> None:
    assert (
        executar_processo([sys.executable, "-c", "print('ola')"], 10).strip() == "ola"
    )


def test_executar_processo_codigo_de_saida_diferente_de_zero_reprova_sem_segredo() -> (
    None
):
    segredos.registrar("senha-do-admin-123")
    codigo = (
        "import sys; sys.stderr.write('falhou com senha-do-admin-123'); sys.exit(3)"
    )

    with pytest.raises(ErroDeComandoError) as erro:
        executar_processo([sys.executable, "-c", codigo], 10)

    assert "saiu com 3" in str(erro.value)
    assert "senha-do-admin-123" not in str(erro.value)


def test_executar_processo_passou_do_prazo_mata_e_reprova() -> None:
    with pytest.raises(ErroDeComandoError, match=r"passou de 0\.5 s"):
        executar_processo([sys.executable, "-c", "import time; time.sleep(30)"], 0.5)


_KUBECTL_FALSO = """\
#!{python}
import socket, sys, time
args = sys.argv[1:]
if "--vive" not in args and "sai" in args:
    sys.exit(1)
porta = int(args[-1].split(":")[0])
servidor = socket.socket()
servidor.bind(("127.0.0.1", porta))
servidor.listen()
time.sleep(60)
"""


@pytest.fixture
def kubectl_falso(tmp_path: Path) -> Path:
    caminho = tmp_path / "kubectl"
    caminho.write_text(_KUBECTL_FALSO.format(python=sys.executable))
    caminho.chmod(caminho.stat().st_mode | stat.S_IXUSR)
    return caminho


def test_port_forward_abre_a_porta_e_fecha_no_fim(kubectl_falso: Path) -> None:
    import socket

    kubectl = Kubectl("kind-x", binario=str(kubectl_falso))

    with PortForward(kubectl, "ns", "svc/mailpit", 8025) as ponte:
        assert ponte.url == f"http://127.0.0.1:{ponte.porta}"
        with socket.create_connection(("127.0.0.1", ponte.porta), timeout=2):
            pass

    with pytest.raises(OSError, match=r"refused|Connection"):
        socket.create_connection(("127.0.0.1", ponte.porta), timeout=2)


def test_port_forward_garantir_religa_o_kubectl_que_morreu(kubectl_falso: Path) -> None:
    kubectl = Kubectl("kind-x", binario=str(kubectl_falso))
    ponte = PortForward(kubectl, "ns", "svc/mailpit", 8025).iniciar()
    try:
        primeiro = ponte._processo
        assert primeiro is not None
        primeiro.kill()
        primeiro.wait()

        ponte.garantir()

        assert ponte._processo is not primeiro
        assert ponte._processo is not None
        assert ponte._processo.poll() is None
        ponte.garantir()
    finally:
        ponte.encerrar()


def test_port_forward_kubectl_que_sai_na_hora_reprova(kubectl_falso: Path) -> None:
    ponte = PortForward(
        Kubectl("kind-x", binario=str(kubectl_falso)), "ns", "sai", 8025
    )
    try:
        with pytest.raises(ErroDeComandoError, match="terminou"):
            ponte.iniciar(prazo=5)
    finally:
        ponte.encerrar()


def test_port_forward_encerrar_mata_o_kubectl_que_ignora_o_terminate() -> None:
    chamadas: list[str] = []

    class Teimoso:
        def terminate(self) -> None:
            chamadas.append("terminate")

        def kill(self) -> None:
            chamadas.append("kill")

        def wait(self, timeout: float) -> int:
            chamadas.append(f"wait {timeout:g}")
            if chamadas.count("terminate") == 1 and "kill" not in chamadas:
                raise subprocess.TimeoutExpired("kubectl", timeout)
            return 0

    ponte = PortForward(Kubectl("kind-x"), "ns", "svc/x", 1)
    ponte._processo = Teimoso()  # type: ignore[assignment]  # falso do Popen

    ponte.encerrar()

    assert chamadas == ["terminate", "wait 5", "kill", "wait 5"]
    assert ponte._processo is None


def test_port_forward_encerrar_sem_iniciar_nao_faz_nada() -> None:
    PortForward(Kubectl("kind-x"), "ns", "svc/x", 1).encerrar()


# --- relatorio --------------------------------------------------------------


def _cucumber() -> list[dict[str, Any]]:
    def passo(status: str, ns: int) -> dict[str, Any]:
        return {"result": {"status": status, "duration": ns}}

    return [
        {
            "elements": [
                {
                    "name": "A OS percorre os tres servicos",
                    "tags": [{"name": "caminho-feliz"}, {"name": "demo"}],
                    "steps": [
                        passo("passed", 1_500_000_000),
                        passo("passed", 2_500_000_000),
                    ],
                },
                {
                    "name": "Orcamento vence",
                    "tags": [{"name": "expiracao"}],
                    "steps": [
                        passo("passed", 1_000_000_000),
                        passo("failed", 3_000_000_000),
                    ],
                },
                {
                    "name": "Pulado",
                    "tags": [],
                    "steps": [passo("passed", 0), passo("skipped", 0)],
                },
            ]
        }
    ]


def test_gerar_resumo_lista_cada_cenario_com_resultado_duracao_e_rastreio() -> None:
    registros = {
        "A OS percorre os tres servicos": {"ordem_id": "ord-1", "trace_id": "trace-1"}
    }

    texto = gerar_resumo(_cucumber(), registros, "Titulo")

    linhas = texto.splitlines()
    assert linhas[0] == "## Titulo"
    assert "3 cenarios, 2 com falha, 8 s no total." in texto
    assert (
        "| A OS percorre os tres servicos | `@caminho-feliz` `@demo` | passou | 4.0 | "
        "`ord-1` | `trace-1` |"
    ) in linhas
    assert "| Orcamento vence | `@expiracao` | falhou | 4.0 | `-` | `-` |" in linhas
    assert "| Pulado |  | nao executado | 0.0 | `-` | `-` |" in linhas


def test_gerar_resumo_cenario_de_esquema_leva_o_exemplo_no_nome() -> None:
    cucumber = [
        {
            "elements": [
                {
                    "id": "test_swagger[/os]",
                    "name": "Swagger de cada servico",
                    "tags": [{"name": "borda"}],
                    "steps": [{"result": {"status": "passed", "duration": 0}}],
                },
                {
                    "id": "test_swagger[/billing]",
                    "name": "Swagger de cada servico",
                    "tags": [{"name": "borda"}],
                    "steps": [{"result": {"status": "passed", "duration": 0}}],
                },
            ]
        }
    ]

    linhas = gerar_resumo(cucumber, {}, "T").splitlines()

    assert any(
        linha.startswith("| Swagger de cada servico [/os] |") for linha in linhas
    )
    assert any(
        linha.startswith("| Swagger de cada servico [/billing] |") for linha in linhas
    )


def test_gerar_resumo_sem_cenarios() -> None:
    texto = gerar_resumo([{"elements": []}], {}, "Vazio")

    assert "0 cenarios, 0 com falha, 0 s no total." in texto


def test_registro_anota_por_cenario_e_salva_json(tmp_path: Path) -> None:
    registro = Registro()
    registro.anotar("A", ordem_id="o1")
    registro.anotar("A", trace_id="t1")
    registro.anotar("B", ordem_id="o2")

    registro.salvar(tmp_path / "cenarios.json")

    assert json.loads((tmp_path / "cenarios.json").read_text()) == {
        "A": {"ordem_id": "o1", "trace_id": "t1"},
        "B": {"ordem_id": "o2"},
    }


def test_escrever_resumo_junta_cucumber_e_registro_e_anexa_ao_step_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "cucumber.json").write_text(json.dumps(_cucumber()))
    (tmp_path / "cenarios.json").write_text(
        json.dumps({"Orcamento vence": {"ordem_id": "ord-9"}})
    )
    sumario = tmp_path / "step-summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(sumario))

    destino = escrever_resumo(tmp_path, "Meu resumo")

    assert destino == tmp_path / "resumo.md"
    assert "`ord-9`" in destino.read_text()
    assert sumario.read_text().startswith("## Meu resumo")


def test_escrever_resumo_sem_registro_e_sem_step_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "cucumber.json").write_text(json.dumps(_cucumber()))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    destino = escrever_resumo(tmp_path)

    assert "| Pulado |" in destino.read_text()


def test_principal_exige_o_diretorio_dos_relatorios(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert principal([]) == 2
    assert "uso:" in capsys.readouterr().err


def test_principal_escreve_o_resumo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "cucumber.json").write_text(json.dumps(_cucumber()))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    assert principal([str(tmp_path)]) == 0
    assert "resumo escrito em" in capsys.readouterr().out


# --- texto ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        (
            "Cancelamento recusado: execução já iniciada",
            "cancelamento recusado: execucao ja iniciada",
        ),
        ("Orçamento", "orcamento"),
        ("sem acento", "sem acento"),
    ],
)
def test_sem_acentos_tira_diacriticos_e_caixa(entrada: str, esperado: str) -> None:
    assert sem_acentos(entrada) == esperado


def test_sem_acentos_compara_mensagem_acentuada_com_a_da_spec() -> None:
    assert sem_acentos("Execução JÁ iniciada") == sem_acentos("execucao ja iniciada")
