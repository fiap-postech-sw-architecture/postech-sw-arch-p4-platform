"""Cliente do Mercado Pago: formatos das respostas, erros e o que ele nunca faz."""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import httpx
import pytest

from e2e.apoio import segredos
from e2e.apoio.evidencia import varrer
from e2e.apoio.mercadopago import (
    MARGEM_DO_RELOGIO,
    PRAZO,
    URL_DA_API,
    USER_AGENT,
    ClienteMercadoPago,
    ErroDoMercadoPagoError,
    PagamentoMp,
    PreferenciaMp,
    TokenRecusadoError,
    registrar_conta,
    sem_id_da_conta,
)
from e2e.apoio.segredos import mascarar
from e2e_apoio.falsos import CHAVE_APP_USR

if TYPE_CHECKING:
    from collections.abc import Callable

AGORA = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)

# Um pagamento do Mercado Pago como a documentacao o mostra, com os dados do pagador
# e do cartao que o cliente nunca pode guardar.
PAGAMENTO = {
    "id": 1325012345,
    "status": "approved",
    "status_detail": "accredited",
    "transaction_amount": 210.0,
    "transaction_amount_refunded": 0,
    "currency_id": "BRL",
    "date_approved": "2026-10-20T08:01:02.000-04:00",
    "external_reference": "dc9357e8-1534-4d0f-b5a7-cb029074c044",
    "live_mode": False,
    "payer": {
        "email": "comprador@testuser.com",
        "first_name": "Test",
        "identification": {"type": "CPF", "number": "12345678909"},
    },
    "card": {"last_four_digits": "3311", "cardholder": {"name": "APRO"}},
}


def _cliente(
    responder: Callable[[httpx.Request], httpx.Response],
    visto: list[httpx.Request] | None = None,
) -> ClienteMercadoPago:
    def tratador(requisicao: httpx.Request) -> httpx.Response:
        if visto is not None:
            visto.append(requisicao)
        return responder(requisicao)

    return ClienteMercadoPago(CHAVE_APP_USR, transporte=httpx.MockTransport(tratador))


def _json(corpo: object, status: int = 200) -> httpx.Response:
    # O servidor manda numero com ponto decimal; json.dumps de float faz o mesmo.
    return httpx.Response(status, content=json.dumps(corpo).encode())


def test_pagamento_guarda_so_os_campos_da_evidencia_e_nada_do_pagador() -> None:
    visto: list[httpx.Request] = []
    cliente = _cliente(lambda _: _json(PAGAMENTO), visto)

    mp = cliente.pagamento("1325012345")

    assert mp == PagamentoMp(
        id="1325012345",
        status="approved",
        status_detail="accredited",
        valor=Decimal("210.0"),
        valor_estornado=Decimal(0),
        moeda="BRL",
        date_approved="2026-10-20T08:01:02.000-04:00",
        external_reference="dc9357e8-1534-4d0f-b5a7-cb029074c044",
        live_mode=False,
    )
    evidencia = mp.para_evidencia()
    assert set(evidencia) == {
        "id",
        "status",
        "transaction_amount",
        "currency_id",
        "date_approved",
        "external_reference",
        "live_mode",
    }
    texto = json.dumps(evidencia) + repr(mp)
    for dado_do_pagador in ("comprador@testuser", "12345678909", "3311", "APRO"):
        assert dado_do_pagador not in texto
    assert visto[0].method == "GET"
    assert visto[0].url.path == "/v1/payments/1325012345"


def test_cada_chamada_leva_o_token_no_cabecalho_e_um_user_agent_proprio() -> None:
    visto: list[httpx.Request] = []

    _cliente(lambda _: _json(PAGAMENTO), visto).pagamento("1")

    assert visto[0].headers["authorization"] == f"Bearer {CHAVE_APP_USR}"
    assert visto[0].headers["user-agent"] == USER_AGENT
    assert "pytstop" in USER_AGENT
    assert visto[0].headers["accept"] == "application/json"


def test_o_cliente_http_tem_prazo_tls_ligado_e_nao_segue_redirecionamento(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opcoes: dict[str, Any] = {}

    class ClienteFalso:
        def __init__(self, **kwargs: Any) -> None:
            opcoes.update(kwargs)

    monkeypatch.setattr(httpx, "Client", ClienteFalso)

    ClienteMercadoPago(CHAVE_APP_USR)

    assert opcoes["base_url"] == URL_DA_API == "https://api.mercadopago.com"
    assert opcoes["timeout"] == PRAZO == 10.0, "o README promete 10 s"
    assert opcoes["verify"] is True
    assert opcoes["follow_redirects"] is False


def test_o_token_nao_aparece_no_repr_nem_nos_atributos() -> None:
    cliente = _cliente(lambda _: _json(PAGAMENTO))

    assert CHAVE_APP_USR not in repr(cliente)
    assert all(
        CHAVE_APP_USR not in str(valor)
        for valor in vars(cliente).values()
        if not isinstance(valor, httpx.Client)
    )


def test_pagamento_estornado_pelo_status_ou_pelo_valor_estornado() -> None:
    def com(**campos: Any) -> PagamentoMp:
        return _cliente(lambda _: _json({**PAGAMENTO, **campos})).pagamento("1")

    assert com(status="refunded").estornado
    assert com(transaction_amount_refunded=210.0).estornado
    assert com(transaction_amount_refunded=300).estornado
    assert not com(transaction_amount_refunded=100.5).estornado
    assert not com().estornado
    assert not com(transaction_amount=None, transaction_amount_refunded=10).estornado
    assert com(transaction_amount=0.5, transaction_amount_refunded=0.5).estornado
    assert not com(transaction_amount=0, transaction_amount_refunded=0).estornado


def test_buscar_por_referencia_lista_as_tentativas_em_ordem() -> None:
    visto: list[httpx.Request] = []
    rejeitado = {
        **PAGAMENTO,
        "id": 1,
        "status": "rejected",
        "status_detail": "cc_rejected_other_reason",
    }
    cliente = _cliente(
        lambda _: _json({"paging": {"total": 2}, "results": [rejeitado, PAGAMENTO]}),
        visto,
    )

    tentativas = cliente.buscar_por_referencia("ref-1")

    assert [t.status for t in tentativas] == ["rejected", "approved"]
    assert tentativas[0].status_detail == "cc_rejected_other_reason"
    parametros = dict(visto[0].url.params)
    assert parametros == {
        "external_reference": "ref-1",
        "sort": "date_created",
        "criteria": "asc",
    }
    assert visto[0].url.path == "/v1/payments/search"


def test_buscar_por_referencia_sem_resultado_e_lista_vazia() -> None:
    assert _cliente(lambda _: _json({"results": []})).buscar_por_referencia("x") == []


@pytest.mark.parametrize(
    "corpo",
    [
        pytest.param({"paging": {}}, id="sem-results"),
        pytest.param({"results": {"id": 1}}, id="results-nao-e-lista"),
        pytest.param([1, 2], id="corpo-e-lista"),
    ],
)
def test_buscar_por_referencia_fora_do_formato_diz_o_campo(corpo: object) -> None:
    with pytest.raises(ErroDoMercadoPagoError, match=r"fora do formato.*results"):
        _cliente(lambda _: _json(corpo)).buscar_por_referencia("x")


def test_preferencia_expirada_quando_expires_e_a_data_ja_passou() -> None:
    passada = (AGORA - timedelta(minutes=1)).isoformat()
    visto: list[httpx.Request] = []
    cliente = _cliente(
        lambda _: _json(
            {"id": "123-abc", "expires": True, "expiration_date_to": passada}
        ),
        visto,
    )

    preferencia = cliente.preferencia("123-abc")

    assert preferencia.expirada(AGORA) is True
    assert preferencia.para_evidencia() == {
        "id": "123-abc",
        "expires": True,
        "expiration_date_to": datetime.fromisoformat(passada).isoformat(),
    }
    assert visto[0].url.path == "/checkout/preferences/123-abc"


def test_preferencia_com_data_longe_no_futuro_nao_esta_expirada() -> None:
    futura = (AGORA + MARGEM_DO_RELOGIO + timedelta(minutes=1)).isoformat()

    preferencia = _cliente(
        lambda _: _json({"id": "1", "expires": True, "expiration_date_to": futura})
    ).preferencia("1")

    assert preferencia.expirada(AGORA) is False


def test_preferencia_dentro_da_margem_do_relogio_conta_como_expirada() -> None:
    quase = (AGORA + MARGEM_DO_RELOGIO - timedelta(seconds=1)).isoformat()

    preferencia = _cliente(
        lambda _: _json({"id": "1", "expires": True, "expiration_date_to": quase})
    ).preferencia("1")

    assert preferencia.expirada(AGORA) is True


def test_preferencia_que_diz_nao_expirar_nao_esta_expirada() -> None:
    passada = (AGORA - timedelta(days=1)).isoformat()

    preferencia = _cliente(
        lambda _: _json({"id": "1", "expires": False, "expiration_date_to": passada})
    ).preferencia("1")

    assert preferencia.expirada(AGORA) is False


@pytest.mark.parametrize(
    "corpo",
    [
        pytest.param({"id": "1"}, id="sem-os-campos"),
        pytest.param(
            {"id": "1", "expires": "sim", "expiration_date_to": "2026-10-20T10:00:00Z"},
            id="expires-nao-booleano",
        ),
        pytest.param(
            {"id": "1", "expires": True, "expiration_date_to": "ontem"},
            id="data-ilegivel",
        ),
        pytest.param({"id": "1", "expires": True}, id="sem-data"),
    ],
)
def test_preferencia_sem_os_campos_no_formato_nao_prova_nada(corpo: object) -> None:
    preferencia = _cliente(lambda _: _json(corpo)).preferencia("1")

    assert preferencia.expirada(AGORA) is None


def test_data_sem_fuso_vale_utc_e_com_z_tambem() -> None:
    sem_fuso = _cliente(
        lambda _: _json(
            {"id": "1", "expires": True, "expiration_date_to": "2026-10-20T11:00:00"}
        )
    ).preferencia("1")
    com_z = _cliente(
        lambda _: _json(
            {"id": "1", "expires": True, "expiration_date_to": "2026-10-20T11:00:00Z"}
        )
    ).preferencia("1")

    assert (
        sem_fuso.expira_em
        == com_z.expira_em
        == datetime(2026, 10, 20, 11, 0, tzinfo=UTC)
    )


def test_preferencia_fora_do_formato_diz_o_campo() -> None:
    with pytest.raises(ErroDoMercadoPagoError, match="campo id"):
        _cliente(lambda _: _json({"expires": True})).preferencia("1")
    with pytest.raises(ErroDoMercadoPagoError, match="objeto"):
        _cliente(lambda _: _json(["x"])).preferencia("1")


@pytest.mark.parametrize(
    "status",
    [
        pytest.param(401, id="nao-autenticado"),
        pytest.param(403, id="proibido"),
    ],
)
def test_token_recusado_e_um_erro_proprio_com_a_mensagem_do_mercado_pago(
    status: int,
) -> None:
    cliente = _cliente(
        lambda _: _json(
            {"message": "invalid_token", "error": "unauthorized", "status": status},
            status,
        )
    )

    with pytest.raises(TokenRecusadoError) as erro:
        cliente.pagamento("1")

    assert erro.value.status == status
    assert "não aceita o token" in str(erro.value)
    assert "unauthorized; invalid_token" in str(erro.value)


def test_erro_4xx_traz_message_e_causas_sem_dado_do_pagador() -> None:
    corpo = {
        "message": "invalid parameters",
        "error": "bad_request",
        "cause": [
            {
                "code": 4020,
                "description": "notification_url attribute must be url valid",
            },
            {"code": 1, "description": "x"},
            {"code": 2, "description": "y"},
            {"code": 3, "description": "cortada: so as tres primeiras"},
            "texto solto",
        ],
    }

    with pytest.raises(ErroDoMercadoPagoError) as erro:
        _cliente(lambda _: _json(corpo, 400)).pagamento("1")

    assert erro.value.status == 400
    texto = str(erro.value)
    assert "HTTP 400" in texto
    assert "4020: notification_url attribute must be url valid" in texto
    assert "cortada" not in texto


def test_erro_so_com_texto_solto_na_lista_de_causas_ignora_o_que_nao_e_objeto() -> None:
    corpo = {"message": "m", "cause": ["texto solto"]}

    with pytest.raises(ErroDoMercadoPagoError, match=r"\(m\)"):
        _cliente(lambda _: _json(corpo, 400)).pagamento("1")


def test_erro_5xx_com_corpo_que_nao_e_json_nao_repete_o_texto() -> None:
    cliente = _cliente(
        lambda _: httpx.Response(
            502, content=b"<html>pagina de erro com cpf 12345678909</html>"
        )
    )

    with pytest.raises(ErroDoMercadoPagoError) as erro:
        cliente.pagamento("1")

    assert erro.value.status == 502
    assert "corpo sem JSON" in str(erro.value)
    assert "12345678909" not in str(erro.value)


def test_erro_cujo_json_nao_e_objeto_tambem_nao_repete_o_texto() -> None:
    with pytest.raises(ErroDoMercadoPagoError, match="corpo sem JSON"):
        _cliente(lambda _: _json(["a"], 500)).pagamento("1")


def test_erro_sem_nenhum_campo_conhecido_diz_sem_detalhe() -> None:
    with pytest.raises(ErroDoMercadoPagoError, match="sem detalhe"):
        _cliente(lambda _: _json({"outro": "x"}, 404)).pagamento("1")


def test_a_mensagem_de_erro_sai_mascarada_e_cortada() -> None:
    segredos.registrar("segredo-que-o-mp-repetiu")
    corpo = {"message": "x" * 290 + " segredo-que-o-mp-repetiu"}

    with pytest.raises(ErroDoMercadoPagoError) as erro:
        _cliente(lambda _: _json(corpo, 400)).pagamento("1")

    assert "segredo" not in str(erro.value)
    assert len(str(erro.value)) < 400


def test_erro_que_repete_o_proprio_token_sai_mascarado() -> None:
    with pytest.raises(ErroDoMercadoPagoError) as erro:
        _cliente(
            lambda _: _json({"message": f"token {CHAVE_APP_USR} invalido"}, 400)
        ).pagamento("1")

    assert CHAVE_APP_USR not in str(erro.value)
    assert "***" in str(erro.value)


def test_redirecionamento_nunca_e_seguido() -> None:
    visto: list[httpx.Request] = []
    cliente = _cliente(
        lambda _: httpx.Response(
            302, headers={"location": "https://outro-host.example/x"}
        ),
        visto,
    )

    with pytest.raises(
        ErroDoMercadoPagoError, match="redirecionamento 302 recusado"
    ) as erro:
        cliente.pagamento("1")

    assert erro.value.status == 302
    assert len(visto) == 1, "o cliente seguiu o redirecionamento"
    assert "outro-host" not in str(erro.value)


def test_falha_de_rede_vira_erro_sem_o_texto_da_excecao() -> None:
    def cai(_: httpx.Request) -> httpx.Response:
        msg = f"conexao com {CHAVE_APP_USR} caiu"
        raise httpx.ConnectError(msg)

    with pytest.raises(ErroDoMercadoPagoError) as erro:
        _cliente(cai).pagamento("1")

    assert "ConnectError" in str(erro.value)
    assert CHAVE_APP_USR not in str(erro.value)
    assert erro.value.status is None


def test_prazo_estourado_tambem_e_erro_do_mercado_pago() -> None:
    def demora(_: httpx.Request) -> httpx.Response:
        msg = "lento"
        raise httpx.ReadTimeout(msg)

    with pytest.raises(ErroDoMercadoPagoError, match="ReadTimeout"):
        _cliente(demora).pagamento("1")


def test_corpo_2xx_que_nao_e_json_reprova() -> None:
    with pytest.raises(ErroDoMercadoPagoError, match="não é JSON") as erro:
        _cliente(lambda _: httpx.Response(200, content=b"ok")).pagamento("1")

    assert erro.value.status == 200


@pytest.mark.parametrize(
    ("troca", "campo"),
    [
        pytest.param({"id": None}, "id", id="id-ausente"),
        pytest.param({"id": True}, "id", id="id-booleano"),
        pytest.param({"id": ""}, "id", id="id-vazio"),
        pytest.param({"id": [1]}, "id", id="id-lista"),
        pytest.param({"status": None}, "status", id="status-ausente"),
        pytest.param(
            {"transaction_amount": "210"}, "transaction_amount", id="valor-texto"
        ),
        pytest.param(
            {"transaction_amount": True}, "transaction_amount", id="valor-booleano"
        ),
        pytest.param(
            {"transaction_amount_refunded": "0"},
            "transaction_amount_refunded",
            id="estornado-texto",
        ),
    ],
)
def test_pagamento_fora_do_formato_diz_qual_campo(
    troca: dict[str, Any], campo: str
) -> None:
    with pytest.raises(ErroDoMercadoPagoError, match=f"fora do formato.*campo {campo}"):
        _cliente(lambda _: _json({**PAGAMENTO, **troca})).pagamento("1")


def test_pagamento_cujo_corpo_nao_e_objeto_reprova() -> None:
    with pytest.raises(ErroDoMercadoPagoError, match="objeto"):
        _cliente(lambda _: _json([1])).pagamento("1")


def test_campos_opcionais_ausentes_viram_none_e_live_mode_so_aceita_booleano() -> None:
    minimo = _cliente(lambda _: _json({"id": 7, "status": "pending"})).pagamento("7")
    estranho = _cliente(lambda _: _json({**PAGAMENTO, "live_mode": "false"})).pagamento(
        "1"
    )

    assert minimo.valor is None
    assert minimo.moeda is None
    assert minimo.external_reference is None
    assert minimo.date_approved is None
    assert minimo.status_detail is None
    assert minimo.live_mode is None
    assert minimo.valor_estornado == 0
    assert minimo.para_evidencia()["transaction_amount"] is None
    assert estranho.live_mode is None


def test_detalhe_longo_do_erro_sai_cortado_em_300_caracteres() -> None:
    corpo = {"message": "x" * 400}

    with pytest.raises(ErroDoMercadoPagoError) as erro:
        _cliente(lambda _: _json(corpo, 400)).pagamento("1")

    assert "x" * 300 in str(erro.value)
    assert "x" * 301 not in str(erro.value)


def test_id_invalido_aparece_cortado_na_mensagem() -> None:
    cliente = _cliente(lambda _: _json(PAGAMENTO))

    with pytest.raises(ErroDoMercadoPagoError) as erro:
        cliente.pagamento("1" * 20 + "9" * 50 + "/")

    assert "1" * 20 in str(erro.value)
    assert "9" not in str(erro.value)


@pytest.mark.parametrize(
    "lido",
    [
        pytest.param(lambda c: c.pagamento("1"), id="pagamento"),
        pytest.param(lambda c: c.preferencia("1"), id="preferencia"),
    ],
)
def test_o_que_se_le_do_mercado_pago_nao_muda_depois_de_lido(
    lido: Callable[[ClienteMercadoPago], Any],
) -> None:
    resposta = {
        **PAGAMENTO,
        "expires": True,
        "expiration_date_to": "2026-10-20T12:00:00.000-04:00",
    }
    objeto = lido(_cliente(lambda _: _json(resposta)))

    with pytest.raises(FrozenInstanceError):
        objeto.id = "outro"
    assert not hasattr(objeto, "__dict__"), "sem dicionario por instancia"


def test_id_com_caracteres_que_mudam_o_caminho_nem_sai_da_maquina() -> None:
    visto: list[httpx.Request] = []
    cliente = _cliente(lambda _: _json(PAGAMENTO), visto)

    for invalido in ("../v1/users", "1?x=y", "", "a" * 65, "1/2"):
        with pytest.raises(ErroDoMercadoPagoError, match="fora do formato aceito"):
            cliente.pagamento(invalido)
        with pytest.raises(ErroDoMercadoPagoError, match="fora do formato aceito"):
            cliente.preferencia(invalido)

    assert visto == []


def test_validar_token_busca_uma_referencia_que_nao_existe() -> None:
    visto: list[httpx.Request] = []
    cliente = _cliente(lambda _: _json({"results": []}), visto)

    cliente.validar_token()

    assert visto[0].url.path == "/v1/payments/search"
    referencia = visto[0].url.params["external_reference"]
    assert len(referencia) == 36


def test_validar_token_recusado_levanta_token_recusado() -> None:
    cliente = _cliente(lambda _: _json({"message": "invalid access token"}, 401))

    with pytest.raises(TokenRecusadoError):
        cliente.validar_token()


def test_fechar_fecha_o_cliente_http() -> None:
    cliente = _cliente(lambda _: _json(PAGAMENTO))

    cliente.fechar()

    with pytest.raises(RuntimeError, match="closed"):
        cliente.pagamento("1")


def test_token_sem_prefixo_conhecido_tambem_sai_mascarado() -> None:
    chave = "chave-sem-prefixo-do-mercado-pago-123456"
    cliente = ClienteMercadoPago(
        chave,
        transporte=httpx.MockTransport(
            lambda _: httpx.Response(400, json={"message": f"{chave} invalido"})
        ),
    )

    with pytest.raises(ErroDoMercadoPagoError) as erro:
        cliente.pagamento("1")

    assert chave not in str(erro.value)
    assert "***" in str(erro.value)


# --- o User ID da conta vendedora no id da preferencia ----------------------

UUID = "c5ca3674-5b81-4eef-bfb1-b4bfdccfa6b6"


@pytest.mark.parametrize(
    ("entrada", "saida"),
    [
        pytest.param(f"1462278261-{UUID}", UUID, id="com-user-id"),
        pytest.param(UUID, UUID, id="so-o-uuid"),
        pytest.param(f"1462278261-{UUID.upper()}", UUID.upper(), id="maiusculas"),
        pytest.param("123-abc", "123-abc", id="formato-desconhecido"),
        pytest.param(f"12345-{UUID}", f"12345-{UUID}", id="numero-curto-demais"),
    ],
)
def test_sem_id_da_conta_corta_so_o_prefixo_numerico_do_vendedor(
    entrada: str, saida: str
) -> None:
    assert sem_id_da_conta(entrada) == saida


def test_registrar_conta_mascara_o_user_id_onde_o_pytest_mostrar_o_id() -> None:
    # O pytest mostra o argumento de cada frame do traceback (``PreferenciaMp(id=...)``,
    # ``preferencia_id=...``): a mascara central tira o numero do terminal, do
    # junit.xml e do cucumber.json, e a varredura nao acha o prefixo.
    registrar_conta(f"1462278261-{UUID}")

    texto = mascarar(f"preferencia = PreferenciaMp(id='1462278261-{UUID}')")

    assert texto == f"preferencia = PreferenciaMp(id='***-{UUID}')"
    assert varrer(texto) == []


@pytest.mark.parametrize(
    "preferencia_id",
    [
        pytest.param(UUID, id="so-o-uuid"),
        pytest.param("123-abc", id="formato-desconhecido"),
        pytest.param(f"12345-{UUID}", id="numero-curto-demais"),
        pytest.param("", id="vazio"),
    ],
)
def test_registrar_conta_ignora_o_id_sem_user_id(preferencia_id: str) -> None:
    antes = set(segredos.registrados())

    registrar_conta(preferencia_id)

    assert set(segredos.registrados()) == antes


def test_ler_a_preferencia_registra_o_user_id_da_conta() -> None:
    _cliente(
        lambda _: httpx.Response(200, json={"id": "x", "expires": True})
    ).preferencia(f"1462278261-{UUID}")

    assert mascarar(f"1462278261-{UUID}") == f"***-{UUID}"


def test_id_de_preferencia_invalido_tambem_registra_a_conta_antes_de_falhar() -> None:
    with pytest.raises(ErroDoMercadoPagoError):
        _cliente(lambda _: _json(PAGAMENTO)).preferencia(f"1462278261-{UUID}?x=y")

    assert "1462278261" not in mascarar(f"preferencia_id='1462278261-{UUID}?x=y'")


def test_a_preferencia_na_evidencia_nao_leva_o_user_id_da_conta() -> None:
    preferencia_id = f"1462278261-{UUID}"
    cliente = _cliente(
        lambda _: httpx.Response(200, json={"id": preferencia_id, "expires": True})
    )

    preferencia = cliente.preferencia(preferencia_id)

    assert preferencia.id == preferencia_id, "a consulta usa o id inteiro"
    assert preferencia.para_evidencia()["id"] == UUID


def _sem_rede(_: httpx.Request) -> httpx.Response:
    msg = "sem rede"
    raise httpx.ConnectError(msg)


@pytest.mark.parametrize(
    "resposta",
    [
        pytest.param(_sem_rede, id="sem-rede"),
        pytest.param(lambda _: httpx.Response(404, json={"error": "nf"}), id="404"),
        pytest.param(lambda _: httpx.Response(500, json={"message": "x"}), id="500"),
        pytest.param(lambda _: httpx.Response(401, json={"message": "x"}), id="token"),
        pytest.param(
            lambda _: httpx.Response(302, headers={"location": "https://outro"}),
            id="redirecionamento",
        ),
        pytest.param(
            lambda _: httpx.Response(200, content=b"nao e json"), id="sem-json"
        ),
    ],
)
def test_erro_da_leitura_da_preferencia_nao_leva_o_user_id_da_conta(
    resposta: Callable[[httpx.Request], httpx.Response],
) -> None:
    # A mensagem vai para o junit.xml e o cucumber.json; a varredura apaga os dois se
    # achar o prefixo numerico do id da preferencia.
    with pytest.raises(ErroDoMercadoPagoError) as erro:
        _cliente(resposta).preferencia(f"1462278261-{UUID}")

    texto = str(erro.value)
    assert f"/checkout/preferences/{UUID}" in texto
    assert "1462278261" not in texto
    assert varrer(texto) == []


def test_id_de_preferencia_fora_do_formato_nao_leva_o_user_id_da_conta() -> None:
    with pytest.raises(ErroDoMercadoPagoError, match="fora do formato aceito") as erro:
        _cliente(lambda _: _json(PAGAMENTO)).preferencia(f"1462278261-{UUID}?x=y")

    assert "1462278261" not in str(erro.value)


# --- as fronteiras do estorno e da expiracao ----------------------------------


def _pagamento_mp(**campos: Any) -> PagamentoMp:
    base: dict[str, Any] = {
        "id": "1",
        "status": "approved",
        "status_detail": None,
        "valor": Decimal("100.00"),
        "valor_estornado": Decimal(0),
        "moeda": "BRL",
        "date_approved": None,
        "external_reference": None,
        "live_mode": False,
    }
    return PagamentoMp(**{**base, **campos})


@pytest.mark.parametrize(
    ("campos", "estornado"),
    [
        pytest.param({"status": "refunded"}, True, id="status-refunded"),
        pytest.param({"valor_estornado": Decimal("100.00")}, True, id="total"),
        pytest.param({"valor_estornado": Decimal("100.01")}, True, id="acima-do-total"),
        pytest.param(
            {"valor_estornado": Decimal("99.99")}, False, id="um-centavo-faltando"
        ),
        pytest.param({"valor_estornado": Decimal(0)}, False, id="nada-estornado"),
        pytest.param(
            {"valor": None, "valor_estornado": Decimal(5)}, False, id="sem-valor"
        ),
    ],
)
def test_estornado_so_com_refunded_ou_com_o_valor_inteiro_devolvido(
    campos: dict[str, Any], estornado: bool
) -> None:
    assert _pagamento_mp(**campos).estornado is estornado


@pytest.mark.parametrize(
    ("minutos_a_frente", "expirada"),
    [(-1, True), (0, True), (5, True), (5.01, False), (60, False)],
    ids=["passada", "agora", "na-margem", "um-instante-alem-da-margem", "uma-hora"],
)
def test_preferencia_expirada_tem_a_margem_de_cinco_minutos_de_relogio(
    minutos_a_frente: float, expirada: bool
) -> None:
    preferencia = PreferenciaMp(
        id="p",
        expires=True,
        expira_em=AGORA + timedelta(minutes=minutos_a_frente),
    )

    assert preferencia.expirada(AGORA) is expirada
