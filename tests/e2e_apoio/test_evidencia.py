"""Evidencia do sandbox: campos permitidos, varredura de segredo e arquivos."""

from __future__ import annotations

import base64
import errno
import json
import os

# subprocess roda o pytest do proprio repositorio, sem shell.
import subprocess  # nosec B404
import sys
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from e2e.apoio import segredos
from e2e.apoio.evidencia import (
    FRASE_DA_SANDBOX,
    FRASE_DO_ENSAIO,
    FRASE_DO_ENSAIO_SEM_CONFIRMACAO,
    FRASE_SEM_CONFIRMACAO,
    EvidenciaComSegredoError,
    RegistroDoCenario,
    gerar_resumo,
    gravar_evidencia,
    pagamento_do_billing,
    permitidos,
    principal_da_varredura,
    saga_resumida,
    transicoes_da_os,
    varrer,
    varrer_pasta,
)
from e2e_apoio.falsos import ASSINATURA, CHAVE_APP_USR

RAIZ = Path(__file__).resolve().parents[2]
QUANDO = datetime(2026, 10, 20, 12, 30, tzinfo=UTC)

PAGAMENTO_DO_BILLING = {
    "id": "p-1",
    "ordem_id": "o-1",
    "status": "CONFIRMADO",
    "orcamento_id": "orc-1",
    "valor": "210.00",
    "moeda": "BRL",
    "provedor": "mercadopago",
    "referencia_preferencia": "123-abc",
    "checkout_url": "https://www.mercadopago.com.br/checkout/v1/redirect?pref_id=123-abc",
    "expira_em": "2026-10-20T13:00:00Z",
    "criado_em": "2026-10-20T12:00:00Z",
    "recusas": 0,
    "referencia_pagamento": "999",
    "confirmado_em": "2026-10-20T12:05:00Z",
    "encerrado_em": None,
    "motivo": None,
    "estornado_em": None,
    "motivo_estorno": None,
    "notificacoes": [
        {
            "recebida_em": "2026-10-20T12:05:00Z",
            "referencia_pagamento": "999",
            "status_provedor": "approved",
            "payer_email": "comprador@testuser.com",
        }
    ],
    "estornos_automaticos": [
        {
            "referencia_pagamento": "1",
            "registrado_em": "x",
            "falha": "texto livre do provedor",
        }
    ],
}


# --- lista de campos permitidos ------------------------------------------------------


def test_permitidos_mantem_so_a_lista_na_ordem_da_lista() -> None:
    dados = {"b": 2, "a": 1, "perigoso": "x"}

    assert list(permitidos(dados, ["a", "b", "ausente"]).items()) == [
        ("a", 1),
        ("b", 2),
    ]


def test_pagamento_do_billing_nao_leva_o_link_do_checkout_nem_o_texto_do_provedor() -> (
    None
):
    limpo = pagamento_do_billing(PAGAMENTO_DO_BILLING)

    assert "checkout_url" not in limpo
    assert "estornos_automaticos" not in limpo
    assert limpo["notificacoes"] == [
        {
            "recebida_em": "2026-10-20T12:05:00Z",
            "referencia_pagamento": "999",
            "status_provedor": "approved",
        }
    ]
    texto = json.dumps(limpo)
    for fora in ("pref_id", "comprador@", "texto livre"):
        assert fora not in texto
    assert limpo["referencia_pagamento"] == "999"


def test_pagamento_do_billing_vazio_ou_sem_notificacoes() -> None:
    assert pagamento_do_billing({}) == {"notificacoes": []}


def test_saga_resumida_guarda_etapa_motivo_e_o_rastro_de_cada_passo() -> None:
    saga = {
        "etapa": "compensada",
        "motivo": "cancelamento",
        "falha": "texto livre de falha",
        "plano_compensacao": ["x"],
        "passos": [
            {
                "seq": 1,
                "em": "2026-10-20T12:00:00Z",
                "de": None,
                "para": "aguardando_diagnostico",
                "gatilho": "abertura",
                "comando": "SolicitarDiagnostico",
                "mensagem_id": "m-1",
                "ator": "uuid-do-atendente",
            }
        ],
    }

    limpa = saga_resumida(saga)

    assert limpa == {
        "etapa": "compensada",
        "motivo": "cancelamento",
        "passos": [
            {
                "seq": 1,
                "em": "2026-10-20T12:00:00Z",
                "de": None,
                "para": "aguardando_diagnostico",
                "gatilho": "abertura",
                "comando": "SolicitarDiagnostico",
            }
        ],
    }
    assert saga_resumida({}) == {"passos": []}


# --- transicoes -----------------------------------------------------------------------


def test_transicoes_juntam_historico_saga_e_pagamento_na_ordem_do_servidor() -> None:
    historico = {
        "mudancas": [
            {
                "de": None,
                "para": "recebida",
                "origem": "atendimento",
                "ocorrido_em": "2026-10-20T12:00:00Z",
            },
            {
                "de": "recebida",
                "para": "em_diagnostico",
                "origem": "execucao",
                "ocorrido_em": "2026-10-20T12:00:05Z",
            },
            {"de": "x", "para": "y", "origem": "z", "ocorrido_em": "nao e data"},
        ]
    }
    saga = {
        "passos": [
            {
                "em": "2026-10-20T12:00:01Z",
                "gatilho": "DiagnosticoIniciado",
                "comando": None,
            },
            {
                "em": "2026-10-20T12:00:03Z",
                "gatilho": "DiagnosticoConcluido",
                "comando": "GerarOrcamento",
            },
            {"gatilho": "sem-hora"},
        ]
    }
    pagamento = {
        "criado_em": "2026-10-20T12:00:04Z",
        "confirmado_em": "2026-10-20T12:00:06Z",
        "encerrado_em": None,
        "estornado_em": "2026-10-20T12:00:07Z",
    }

    achados = transicoes_da_os(historico, saga, pagamento)

    assert [texto for _, texto in achados] == [
        "OS: (abertura) -> recebida (atendimento)",
        "saga: DiagnosticoIniciado",
        "saga: DiagnosticoConcluido, envia GerarOrcamento",
        "Billing: cobrança criada (SOLICITADO)",
        "OS: recebida -> em_diagnostico (execucao)",
        "Billing: pagamento CONFIRMADO",
        "Billing: pagamento ESTORNADO",
    ]
    assert [hora for hora, _ in achados] == sorted(hora for hora, _ in achados)


def test_transicoes_sem_nada_devolve_lista_vazia() -> None:
    assert transicoes_da_os({}, {}, {}) == []


def test_transicoes_da_cobranca_encerrada() -> None:
    achados = transicoes_da_os({}, {}, {"encerrado_em": "2026-10-20T12:00:00Z"})

    assert [texto for _, texto in achados] == ["Billing: cobrança encerrada"]


# --- o registro do cenario -----------------------------------------------------------


def test_anotar_poe_a_hora_dada_ou_a_de_agora() -> None:
    registro = RegistroDoCenario(nome="C")

    registro.anotar("link impresso", agora=QUANDO)
    registro.anotar("outra coisa")

    assert registro.transicoes[0] == (QUANDO, "script: link impresso")
    assert registro.transicoes[1][1] == "script: outra coisa"
    assert registro.transicoes[1][0].tzinfo is not None


def test_registro_para_json_ordena_as_transicoes_e_nao_perde_campo() -> None:
    registro = RegistroDoCenario(
        nome="Pagamento",
        resultado="passou",
        duracao=12.34,
        ordem_id="o-1",
        pagamento_id="p-1",
        pagamento_mp_id="999",
    )
    # O texto que vem primeiro na hora e o ultimo em ordem alfabetica: a ordem e a da
    # hora, e nao a do texto.
    registro.transicoes = [
        (datetime(2026, 10, 20, 12, 0, 5, tzinfo=UTC), "alfa: depois"),
        (datetime(2026, 10, 20, 12, 0, 1, tzinfo=UTC), "zeta: antes"),
    ]
    registro.mercadopago = {"status": "approved"}

    dados = registro.para_json()

    assert [t["evento"] for t in dados["transicoes"]] == ["zeta: antes", "alfa: depois"]
    assert dados["duracao_s"] == 12.3
    assert dados["pagamento_mercadopago_id"] == "999"
    assert dados["mercadopago"] == {"status": "approved"}
    assert set(dados) == {
        "cenario",
        "resultado",
        "duracao_s",
        "ordem_id",
        "pagamento_id",
        "pagamento_mercadopago_id",
        "transicoes",
        "billing",
        "mercadopago",
        "preferencia",
        "saga",
        "observacoes",
    }


# --- o resumo.md ---------------------------------------------------------------------


def _registro_completo() -> RegistroDoCenario:
    registro = RegistroDoCenario(
        nome="Pagamento aprovado",
        resultado="passou",
        duracao=61.4,
        ordem_id="o-1",
        pagamento_id="p-1",
        pagamento_mp_id="999",
    )
    registro.transicoes = [(QUANDO, "Billing: pagamento CONFIRMADO")]
    registro.mercadopago = {"id": "999", "status": "approved", "live_mode": False}
    registro.preferencia = {"id": "123-abc", "expires": True}
    registro.observacoes = ["a expiração não foi provada pela consulta"]
    registro.billing = {"status": "CONFIRMADO"}
    return registro


def test_resumo_real_tem_a_frase_honesta_e_o_que_veio_do_mercado_pago() -> None:
    texto = gerar_resumo(
        [_registro_completo()],
        modo="real",
        contexto="kind-pytstop-p4",
        quando=QUANDO,
        prints=["Primeiro print.", "Segundo print."],
    )

    assert "Modo: **real (credenciais de teste do Mercado Pago)**" in texto
    assert "Data: 2026-10-20 12:30 UTC" in texto
    assert "Cluster: `kind-pytstop-p4`" in texto
    assert f"> {FRASE_DA_SANDBOX}" in texto
    assert "não envia webhook" in FRASE_DA_SANDBOX
    assert "conciliação" in FRASE_DA_SANDBOX
    assert "| Pagamento aprovado | passou | 61 | `o-1` | `p-1` | `999` |" in texto
    assert "Id do pagamento no Mercado Pago: `999`" in texto
    assert "| 12:30:00 | Billing: pagamento CONFIRMADO |" in texto
    assert "Do Mercado Pago (só estes campos):" in texto
    assert "- `status`: `approved`" in texto
    assert "- `live_mode`: `False`" in texto
    assert "Preferência do checkout no Mercado Pago:" in texto
    assert "- a expiração não foi provada pela consulta" in texto
    assert "1. Primeiro print." in texto
    assert "2. Segundo print." in texto
    assert "Sem consulta ao Mercado Pago" not in texto
    assert texto.endswith("\n")


def test_resumo_do_ensaio_diz_que_nada_foi_ao_mercado_pago() -> None:
    registro = RegistroDoCenario(nome="Cenário", resultado="passou")
    registro.billing = {"status": "ESTORNADO"}

    texto = gerar_resumo(
        [registro], modo="ensaio", contexto="kind-x", quando=QUANDO, prints=[]
    )

    assert "Modo: **ensaio (simulador do Billing)**" in texto
    assert f"> {FRASE_DO_ENSAIO}" in texto
    assert "nada foi enviado ao Mercado Pago" in FRASE_DO_ENSAIO
    assert "Sem consulta ao Mercado Pago (ensaio)." in texto
    assert "FRASE_DA_SANDBOX" not in texto
    assert FRASE_DA_SANDBOX not in texto
    assert "| Cenário | passou | 0 | `-` | `-` | `-` |" in texto


@pytest.mark.parametrize(
    ("modo", "frase", "outra"),
    [
        pytest.param("real", FRASE_SEM_CONFIRMACAO, FRASE_DA_SANDBOX, id="real"),
        pytest.param(
            "ensaio",
            FRASE_DO_ENSAIO_SEM_CONFIRMACAO,
            FRASE_DO_ENSAIO,
            id="ensaio",
        ),
    ],
)
@pytest.mark.parametrize(
    "billing",
    [
        pytest.param({}, id="sem-dados-do-billing"),
        pytest.param({"status": "SOLICITADO"}, id="solicitado"),
        pytest.param({"status": "CANCELADO"}, id="cancelado"),
    ],
)
def test_resumo_sem_pagamento_confirmado_nao_afirma_confirmacao(
    modo: str, frase: str, outra: str, billing: dict[str, str]
) -> None:
    registro = RegistroDoCenario(nome="Cenário", resultado="falhou")
    registro.billing = billing

    texto = gerar_resumo(
        [registro], modo=modo, contexto="kind-x", quando=QUANDO, prints=[]
    )

    assert f"> {frase}" in texto
    assert outra not in texto
    assert "nenhum pagamento foi confirmado nesta execução" in frase.lower()


def test_resumo_basta_um_pagamento_confirmado_entre_os_cenarios() -> None:
    sem = RegistroDoCenario(nome="A", resultado="falhou")
    com = RegistroDoCenario(nome="B", resultado="passou")
    com.billing = {"status": "ESTORNADO"}

    texto = gerar_resumo(
        [sem, com], modo="real", contexto="kind-x", quando=QUANDO, prints=[]
    )

    assert f"> {FRASE_DA_SANDBOX}" in texto


def _resumo_real(registro: RegistroDoCenario, **opcoes: Any) -> str:
    return gerar_resumo(
        [registro], modo="real", contexto="kind-x", quando=QUANDO, prints=[], **opcoes
    )


def test_resumo_real_diz_a_notification_url_usada_e_que_nao_foi_exercitada() -> None:
    texto = _resumo_real(
        RegistroDoCenario(nome="C"),
        url_de_notificacao="https://example.com/api/v1/webhooks/mercadopago",
    )

    assert (
        "- `notification_url`: `https://example.com/api/v1/webhooks/mercadopago` "
        "(a notificação não foi exercitada: a sandbox não envia webhook)"
    ) in texto


def test_resumo_sem_url_de_notificacao_nao_tem_a_linha() -> None:
    assert "notification_url" not in _resumo_real(RegistroDoCenario(nome="C"))


def test_resumo_do_ensaio_nao_tem_a_linha_da_notification_url() -> None:
    texto = gerar_resumo(
        [RegistroDoCenario(nome="C")],
        modo="ensaio",
        contexto="kind-x",
        quando=QUANDO,
        prints=[],
        url_de_notificacao="https://example.com/hook",
    )

    assert "notification_url" not in texto


def test_resumo_traz_ordem_e_pagamento_de_cada_cenario() -> None:
    registro = RegistroDoCenario(
        nome="C", ordem_id="o-9", pagamento_id="p-9", pagamento_mp_id="1234"
    )

    texto = _resumo_real(registro)

    assert "- `ordem_id`: `o-9`" in texto
    assert "- `pagamento_id` (Billing): `p-9`" in texto
    assert "- Id do pagamento no Mercado Pago: `1234`" in texto


def test_resumo_sem_ordem_nem_pagamento_poe_traco() -> None:
    texto = _resumo_real(RegistroDoCenario(nome="C"))

    assert "- `ordem_id`: `-`" in texto
    assert "- `pagamento_id` (Billing): `-`" in texto
    assert "- Id do pagamento no Mercado Pago: -" in texto


def test_resumo_ordena_as_transicoes_pela_hora_e_nao_pela_ordem_em_que_entraram() -> (
    None
):
    registro = RegistroDoCenario(nome="C")
    # A nota do script entra antes, mas o evento do servico aconteceu antes dela.
    registro.transicoes = [
        (QUANDO + timedelta(seconds=5), "script: link impresso"),
        (QUANDO, "OS: (abertura) -> recebida (atendimento)"),
        (QUANDO + timedelta(seconds=2), "Billing: cobrança criada (SOLICITADO)"),
    ]

    texto = _resumo_real(registro)

    horas = [linha for linha in texto.splitlines() if linha.startswith("| 12:")]
    assert horas == [
        "| 12:30:00 | OS: (abertura) -> recebida (atendimento) |",
        "| 12:30:02 | Billing: cobrança criada (SOLICITADO) |",
        "| 12:30:05 | script: link impresso |",
    ]


def test_gravar_evidencia_recusa_segredo_que_so_esta_no_resumo(tmp_path: Path) -> None:
    # Os prints e o cabecalho so existem no resumo.md: o evidencia.json esta limpo.
    registro = RegistroDoCenario(nome="Cenário limpo", resultado="passou")

    with pytest.raises(EvidenciaComSegredoError, match=r"recusei gravar resumo\.md"):
        gravar_evidencia(
            tmp_path,
            [registro],
            modo="real",
            contexto="kind-x",
            prints=[f"print com {CHAVE_APP_USR}"],
        )

    assert list(tmp_path.iterdir()) == []


def test_gravar_evidencia_recusa_a_assinatura_passada_como_extra(
    tmp_path: Path,
) -> None:
    registro = RegistroDoCenario(nome="Cenário", resultado="passou")
    registro.observacoes = [f"a assinatura {ASSINATURA} apareceu"]

    with pytest.raises(EvidenciaComSegredoError) as erro:
        gravar_evidencia(
            tmp_path,
            [registro],
            modo="real",
            contexto="kind-x",
            prints=[],
            extras=[ASSINATURA],
        )

    assert "segredo registrado" in str(erro.value)
    assert ASSINATURA not in str(erro.value)
    assert list(tmp_path.iterdir()) == []


def test_gravar_evidencia_lista_no_maximo_dez_achados_na_mensagem(
    tmp_path: Path,
) -> None:
    registro = RegistroDoCenario(nome="Cenário", resultado="passou")
    registro.observacoes = [f"contato{n}" + chr(64) + "example.com" for n in range(12)]

    with pytest.raises(EvidenciaComSegredoError) as erro:
        gravar_evidencia(
            tmp_path, [registro], modo="real", contexto="kind-x", prints=[]
        )

    assert str(erro.value).count("(e-mail)") == 10


# --- varredura -----------------------------------------------------------------------


def test_varrer_acha_cada_tipo_de_segredo_com_a_linha_e_nunca_o_valor() -> None:
    segredos.registrar("senha-registrada-do-admin")
    texto = "\n".join(
        [
            "linha limpa",
            "a senha senha-registrada-do-admin vazou",
            f"token {CHAVE_APP_USR}",
            "Authorization: Bearer abc.def.ghi",
            "comprador@testuser.com comprou",
            "TEST-1234567890-abcdef tambem",
        ]
    )

    achados = varrer(texto)

    assert [(a.linha, a.tipo) for a in achados] == [
        (2, "segredo registrado"),
        (3, "token do Mercado Pago"),
        (4, "Bearer"),
        (5, "e-mail"),
        (6, "token do Mercado Pago"),
    ]


def test_varrer_acha_o_que_o_chamador_passa_como_extra_e_ignora_extra_vazio() -> None:
    assert [
        a.linha for a in varrer("x\ncontem-o-extra\n", extras=["contem-o-extra"])
    ] == [2]
    assert varrer("qualquer texto", extras=[""]) == []


def test_varrer_uma_linha_com_dois_tipos_conta_os_dois() -> None:
    tipos = {a.tipo for a in varrer(f"Bearer {CHAVE_APP_USR} de x@y.com")}

    assert tipos == {"Bearer", "token do Mercado Pago", "e-mail"}


@pytest.mark.parametrize(
    "texto",
    [
        pytest.param('{"Authorization": f"Bearer {token}"}', id="codigo-da-requisicao"),
        pytest.param("Authorization: Bearer ***", id="valor-ja-mascarado"),
        pytest.param("o Bearer chegou", id="palavra-solta"),
    ],
)
def test_varrer_nao_confunde_a_palavra_bearer_com_um_token(texto: str) -> None:
    # O traceback de uma falha mostra o codigo do cliente HTTP, e o relatorio inteiro
    # nao pode ser apagado por causa de uma linha que so cita o cabecalho.
    assert varrer(texto) == []


def test_o_achado_da_varredura_nao_muda_depois_de_achado() -> None:
    achado = varrer("comprador" + chr(64) + "testuser.com")[0]

    with pytest.raises(FrozenInstanceError):
        achado.linha = 9  # type: ignore[misc]  # a classe e congelada de proposito


@pytest.mark.parametrize(
    "texto",
    [
        pytest.param(
            "e2e-9afc16-atendente" + chr(64) + "e2e.pytstop.dev", id="staff-do-e2e"
        ),
        pytest.param(
            "cliente-9afc16-1" + chr(64) + "clientes.pytstop.dev", id="cliente"
        ),
        pytest.param("admin" + chr(64) + "pytstop.dev", id="admin"),
        pytest.param("falhou para x" + chr(64) + "e2e.pytstop.dev.", id="ponto-final"),
    ],
)
def test_varrer_nao_trata_como_dado_o_usuario_que_o_proprio_e2e_cria(
    texto: str,
) -> None:
    assert varrer(texto) == []


@pytest.mark.parametrize(
    "texto",
    [
        pytest.param("comprador" + chr(64) + "testuser.com", id="comprador-de-teste"),
        pytest.param(
            "joao" + chr(64) + "pytstop.dev.evil.com", id="dominio-que-comeca-igual"
        ),
        pytest.param("joao" + chr(64) + "meupytstop.dev", id="sufixo-colado"),
        pytest.param("joao" + chr(64) + "pytstop.dev9.com", id="outro-dominio"),
    ],
)
def test_varrer_acha_o_e_mail_que_nao_e_do_dominio_do_e2e(texto: str) -> None:
    assert [a.tipo for a in varrer(texto)] == ["e-mail"]


def test_varrer_texto_limpo_nao_acha_nada() -> None:
    assert (
        varrer("## Evidência\n\n- `ordem_id`: `abc`\n| 12:30:00 | OS: recebida |\n")
        == []
    )


# --- a evidencia inteira -------------------------------------------------------------


def test_gravar_evidencia_escreve_o_resumo_e_o_json(tmp_path: Path) -> None:
    gravar_evidencia(
        tmp_path / "reports" / "mp-sandbox",
        [_registro_completo()],
        modo="real",
        contexto="kind-x",
        prints=["Print."],
        quando=QUANDO,
    )

    pasta = tmp_path / "reports" / "mp-sandbox"
    assert "# Evidência do Mercado Pago na sandbox" in (pasta / "resumo.md").read_text()
    dados = json.loads((pasta / "evidencia.json").read_text())
    assert dados["modo"] == "real"
    assert dados["contexto"] == "kind-x"
    assert dados["cenarios"][0]["pagamento_mercadopago_id"] == "999"
    assert "ç" in (pasta / "evidencia.json").read_text(encoding="utf-8"), (
        "acentos legiveis"
    )
    assert '\n  "modo": "real"' in (pasta / "evidencia.json").read_text(), (
        "JSON indentado, para a pessoa ler"
    )


def test_gravar_evidencia_sem_quando_usa_agora(tmp_path: Path) -> None:
    # A data de antes e a de depois da chamada: o teste nao quebra na virada do
    # dia UTC (meia-noite no meio da chamada).
    antes = datetime.now(UTC)
    gravar_evidencia(tmp_path, [], modo="ensaio", contexto="kind-x", prints=[])
    depois = datetime.now(UTC)

    texto = (tmp_path / "resumo.md").read_text()
    assert any(f"Data: {dia:%Y-%m-%d}" in texto for dia in (antes, depois))


@pytest.mark.parametrize(
    "onde",
    [
        pytest.param("resumo", id="no-resumo"),
        pytest.param("json", id="so-no-json"),
    ],
)
def test_gravar_evidencia_com_segredo_nao_grava_nem_o_outro_arquivo(
    onde: str, tmp_path: Path
) -> None:
    segredos.registrar(CHAVE_APP_USR)
    registro = _registro_completo()
    if onde == "resumo":
        registro.nome = f"cenario com {CHAVE_APP_USR}"
    else:
        # So o JSON tem este campo: a varredura do resumo nao o veria.
        registro.billing = {"referencia": CHAVE_APP_USR}

    with pytest.raises(EvidenciaComSegredoError) as erro:
        gravar_evidencia(
            tmp_path,
            [registro],
            modo="real",
            contexto="kind-x",
            prints=[],
            quando=QUANDO,
        )

    assert CHAVE_APP_USR not in str(erro.value)
    assert list(tmp_path.iterdir()) == []


def test_o_json_da_evidencia_nunca_tem_dado_do_pagador_nem_o_link(
    tmp_path: Path,
) -> None:
    registro = RegistroDoCenario(nome="C", resultado="passou")
    registro.billing = pagamento_do_billing(PAGAMENTO_DO_BILLING)
    registro.saga = saga_resumida({"etapa": "compensada", "passos": []})

    gravar_evidencia(
        tmp_path, [registro], modo="real", contexto="kind-x", prints=[], quando=QUANDO
    )

    escrito = (tmp_path / "evidencia.json").read_text() + (
        tmp_path / "resumo.md"
    ).read_text()
    for fora in ("pref_id", "comprador@", "payer", "texto livre", "checkout"):
        assert fora not in escrito, fora


# --- a varredura da pasta, depois do pytest ------------------------------------------


def test_varrer_pasta_so_lista_os_arquivos_com_achado(tmp_path: Path) -> None:
    (tmp_path / "limpo.md").write_text("tudo certo\n")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "junit.xml").write_text(f"ok\nBearer {CHAVE_APP_USR}\n")

    achados = varrer_pasta(tmp_path)

    assert list(achados) == ["sub/junit.xml"]
    assert [(a.linha, a.tipo) for a in achados["sub/junit.xml"]] == [
        (2, "Bearer"),
        (2, "token do Mercado Pago"),
    ]


def test_varrer_pasta_le_arquivo_que_nao_e_utf8_sem_quebrar(tmp_path: Path) -> None:
    (tmp_path / "binario.bin").write_bytes(b"\xff\xfe nada \x00")

    assert varrer_pasta(tmp_path) == {}


def test_varredura_da_pasta_limpa_sai_com_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "resumo.md").write_text("limpo\n")

    codigo = principal_da_varredura([str(tmp_path)], {})

    assert codigo == 0
    assert "nenhum segredo" in capsys.readouterr().out
    assert (tmp_path / "resumo.md").exists()


def test_varredura_lista_no_maximo_dez_achados_por_arquivo(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    linhas = [f"contato{n}" + chr(64) + "example.com" for n in range(12)]
    (tmp_path / "junit.xml").write_text("\n".join(linhas))

    assert principal_da_varredura([str(tmp_path)], {}) == 1

    assert capsys.readouterr().err.count("(e-mail)") == 10


def test_varredura_apaga_o_arquivo_com_o_token_do_ambiente_e_nao_o_repete(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Um processo novo: so conhece o token e a assinatura pelo ambiente do shell.
    segredos.esquecer_todos()
    (tmp_path / "junit.xml").write_text(
        f"a\nb {CHAVE_APP_USR}\nc {CHAVE_APP_USR} outra vez\n"
    )
    (tmp_path / "cucumber.json").write_text(
        json.dumps({"x": base64.b64encode(ASSINATURA.encode()).decode()})
    )
    (tmp_path / "resumo.md").write_text("limpo\n")
    ambiente = {
        "MP_ACCESS_TOKEN": CHAVE_APP_USR,
        "MP_WEBHOOK_SECRET": ASSINATURA,
        "OUTRA": "x",
    }

    codigo = principal_da_varredura([str(tmp_path)], ambiente)

    erro = capsys.readouterr().err
    assert codigo == 1
    assert (
        "segredo em junit.xml: linha 2 (segredo registrado)" in erro
        or "segredo em junit.xml" in erro
    )
    assert "segredo em cucumber.json" in erro
    assert "APAGADOS" in erro
    assert CHAVE_APP_USR not in erro
    assert ASSINATURA not in erro
    assert sorted(p.name for p in tmp_path.iterdir()) == ["resumo.md"]


class TerminalQueSumiu:
    """Um stdout ou stderr cuja janela fechou: escrever levanta ``OSError`` (EIO)."""

    def write(self, texto: str) -> int:
        raise OSError(errno.EIO, "Input/output error", texto)

    def flush(self) -> None:
        raise OSError(errno.EIO, "Input/output error")


def test_varredura_apaga_o_arquivo_com_segredo_mesmo_com_o_terminal_fechado(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # SIGHUP: o make segue e roda a varredura depois do pytest, sem terminal. O aviso
    # levanta OSError, e o arquivo com segredo nao pode ficar por causa dele.
    segredos.esquecer_todos()
    (tmp_path / "junit.xml").write_text(f"x {CHAVE_APP_USR}\n")
    (tmp_path / "resumo.md").write_text("limpo\n")
    monkeypatch.setattr(sys, "stderr", TerminalQueSumiu())

    codigo = principal_da_varredura([str(tmp_path)], {})

    assert codigo == 1
    assert sorted(p.name for p in tmp_path.iterdir()) == ["resumo.md"]


def test_varredura_limpa_com_o_terminal_fechado_sai_com_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "resumo.md").write_text("limpo\n")
    monkeypatch.setattr(sys, "stdout", TerminalQueSumiu())

    assert principal_da_varredura([str(tmp_path)], {}) == 0


def test_varredura_sem_a_pasta_e_sem_terminal_ainda_sai_com_dois(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "stderr", TerminalQueSumiu())

    assert principal_da_varredura([], {}) == 2


def test_varredura_sem_as_credenciais_no_ambiente_ainda_acha_os_padroes(
    tmp_path: Path,
) -> None:
    segredos.esquecer_todos()
    (tmp_path / "x.md").write_text("comprador@testuser.com\n")

    assert principal_da_varredura([str(tmp_path)], {}) == 1
    assert not (tmp_path / "x.md").exists()


@pytest.mark.parametrize(
    "argumentos",
    [
        pytest.param([], id="nenhuma-pasta"),
        pytest.param(["a", "b"], id="pastas-demais"),
    ],
)
def test_varredura_exige_exatamente_uma_pasta(
    argumentos: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert principal_da_varredura(argumentos, {}) == 2
    assert "uso:" in capsys.readouterr().err


def test_o_json_da_varredura_aceita_dados_de_qualquer_tipo_na_saga() -> None:
    saga: dict[str, Any] = {"etapa": "x", "passos": [{"seq": 1, "extra": {"a": 1}}]}

    assert saga_resumida(saga)["passos"] == [{"seq": 1}]


# --- o User ID da conta vendedora -----------------------------------------------------

ID_DA_PREFERENCIA = "1462278261-c5ca3674-5b81-4eef-bfb1-b4bfdccfa6b6"
UUID_DA_PREFERENCIA = "c5ca3674-5b81-4eef-bfb1-b4bfdccfa6b6"
TIPO_DO_USER_ID = "User ID da conta vendedora (prefixo do id da preferência)"


def test_pagamento_do_billing_guarda_so_o_uuid_da_preferencia() -> None:
    limpo = pagamento_do_billing(
        {**PAGAMENTO_DO_BILLING, "referencia_preferencia": ID_DA_PREFERENCIA}
    )

    assert limpo["referencia_preferencia"] == UUID_DA_PREFERENCIA


def test_pagamento_do_billing_sem_preferencia_nao_inventa_o_campo() -> None:
    assert "referencia_preferencia" not in pagamento_do_billing({"id": "p-1"})
    assert (
        pagamento_do_billing({"referencia_preferencia": None})["referencia_preferencia"]
        is None
    )


def test_varredura_acha_o_user_id_no_id_da_preferencia() -> None:
    achados = varrer(f"linha limpa\npreferencia {ID_DA_PREFERENCIA}")

    assert [(a.tipo, a.linha) for a in achados] == [(TIPO_DO_USER_ID, 2)]


@pytest.mark.parametrize(
    "texto",
    [
        pytest.param(UUID_DA_PREFERENCIA, id="so-o-uuid"),
        pytest.param("98c4cf1d-c9fc-4371-8cd0-f409ad2ff8e2", id="uuid-do-billing"),
        pytest.param(
            "12345678-1234-4371-8cd0-f409ad2ff8e2", id="uuid-que-comeca-numerico"
        ),
        pytest.param("2026-10-14T11:49:42.940000+00:00", id="data"),
        pytest.param("pagamento 1791978588021 aprovado", id="id-numerico-do-mp"),
    ],
)
def test_varredura_nao_confunde_uuid_data_nem_id_numerico_com_user_id(
    texto: str,
) -> None:
    assert varrer(texto) == []


# --- o e-mail nao vaza pelo traceback -----------------------------------------


@pytest.mark.parametrize(
    "gravacao",
    [
        pytest.param(
            "gravar_evidencia(Path({saida!r}), [registro], modo='real',\n"
            "                     contexto='kind-x', prints=[])\n",
            id="direto",
        ),
        pytest.param(
            "gravar_evidencia_da_sessao(Path({saida!r}), [registro],\n"
            "                               Sandbox(modo='ensaio'),\n"
            "                               contexto='kind-x')\n",
            id="pela-sessao-do-sandbox",
        ),
    ],
)
def test_email_achado_na_evidencia_nao_vaza_pelo_traceback_nem_pelo_junit(
    gravacao: str, tmp_path: Path
) -> None:
    usuario, dominio = "joao.silva", "example.com"
    email = f"{usuario}@{dominio}"
    saida = tmp_path / "saida"
    (tmp_path / "test_x.py").write_text(
        "from pathlib import Path\n\n"
        "from e2e.apoio.evidencia import RegistroDoCenario, gravar_evidencia\n"
        "from e2e.apoio.preflight_mp import Sandbox\n"
        "from e2e.apoio.prova import gravar_evidencia_da_sessao\n\n\n"
        "def test_grava_com_email():\n"
        "    registro = RegistroDoCenario(nome='Cenario', resultado='passou')\n"
        # O endereco nasce em tempo de execucao: o pytest mostra o codigo-fonte do
        # teste no traceback, e o literal apareceria ali sem nenhum vazamento.
        f"    email = {usuario!r} + chr(64) + {dominio!r}\n"
        "    registro.observacoes = ['contato ' + email + ' no pagamento']\n"
        "    " + gravacao.replace("{saida!r}", repr(str(saida)))
    )

    resultado = subprocess.run(  # noqa: S603  # nosec B603
        [sys.executable, "-m", "pytest", "test_x.py", "-q", "-p", "no:cacheprovider",
         "--rootdir", str(tmp_path), "--junitxml=junit.xml"],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(RAIZ)},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        stdin=subprocess.DEVNULL,
    )  # fmt: skip

    escrito = resultado.stdout + resultado.stderr + (tmp_path / "junit.xml").read_text()
    assert resultado.returncode == 1, escrito
    assert "recusei gravar resumo.md" in escrito, "a mensagem aparece sem o valor"
    assert email not in escrito
    assert not saida.exists(), "nada foi gravado"
