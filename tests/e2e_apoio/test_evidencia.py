"""Evidencia do sandbox: campos permitidos, varredura de segredo e arquivos."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest

from e2e.apoio import segredos
from e2e.apoio.evidencia import (
    FRASE_DA_SANDBOX,
    FRASE_DO_ENSAIO,
    EvidenciaComSegredoError,
    RegistroDoCenario,
    gerar_resumo,
    gravar,
    gravar_evidencia,
    pagamento_do_billing,
    permitidos,
    principal_da_varredura,
    saga_resumida,
    transicoes_da_os,
    varrer,
    varrer_pasta,
)

if TYPE_CHECKING:
    from pathlib import Path

CHAVE_DO_MP = (
    "APP_USR-1234567890123456-101420-0a1b2c3d4e5f60718293a4b5c6d7e8f9-123456789"
)
ASSINATURA = "assinatura-do-webhook-0123456789abcdef"
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
    registro.transicoes = [
        (datetime(2026, 10, 20, 12, 0, 5, tzinfo=UTC), "depois"),
        (datetime(2026, 10, 20, 12, 0, 1, tzinfo=UTC), "antes"),
    ]
    registro.mercadopago = {"status": "approved"}

    dados = registro.para_json()

    assert [t["evento"] for t in dados["transicoes"]] == ["antes", "depois"]
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


# --- varredura -----------------------------------------------------------------------


def test_varrer_acha_cada_tipo_de_segredo_com_a_linha_e_nunca_o_valor() -> None:
    segredos.registrar("senha-registrada-do-admin")
    texto = "\n".join(
        [
            "linha limpa",
            "a senha senha-registrada-do-admin vazou",
            f"token {CHAVE_DO_MP}",
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
    tipos = {a.tipo for a in varrer(f"Bearer {CHAVE_DO_MP} de x@y.com")}

    assert tipos == {"Bearer", "token do Mercado Pago", "e-mail"}


def test_varrer_texto_limpo_nao_acha_nada() -> None:
    assert (
        varrer("## Evidência\n\n- `ordem_id`: `abc`\n| 12:30:00 | OS: recebida |\n")
        == []
    )


# --- gravar --------------------------------------------------------------------------


def test_gravar_escreve_o_texto_limpo(tmp_path: Path) -> None:
    gravar(tmp_path / "a.md", "tudo limpo\n")

    assert (tmp_path / "a.md").read_text() == "tudo limpo\n"


def test_gravar_recusa_se_achar_o_token_diz_onde_e_nao_grava(tmp_path: Path) -> None:
    segredos.registrar(CHAVE_DO_MP)

    with pytest.raises(EvidenciaComSegredoError) as erro:
        gravar(tmp_path / "resumo.md", f"linha 1\nlinha 2 com {CHAVE_DO_MP}\n")

    texto = str(erro.value)
    assert "resumo.md" in texto
    assert "linha 2" in texto
    assert CHAVE_DO_MP not in texto
    assert "Nada foi gravado" in texto
    assert not (tmp_path / "resumo.md").exists()


def test_gravar_recusa_a_assinatura_secreta_passada_como_extra(tmp_path: Path) -> None:
    with pytest.raises(EvidenciaComSegredoError, match="linha 1"):
        gravar(tmp_path / "x.json", f'{{"a": "{ASSINATURA}"}}', extras=[ASSINATURA])

    assert not (tmp_path / "x.json").exists()


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


def test_gravar_evidencia_sem_quando_usa_agora(tmp_path: Path) -> None:
    gravar_evidencia(tmp_path, [], modo="ensaio", contexto="kind-x", prints=[])

    assert f"Data: {datetime.now(UTC):%Y-%m-%d}" in (tmp_path / "resumo.md").read_text()


@pytest.mark.parametrize("onde", ["resumo", "json"])
def test_gravar_evidencia_com_segredo_nao_grava_nem_o_outro_arquivo(
    onde: str, tmp_path: Path
) -> None:
    segredos.registrar(CHAVE_DO_MP)
    registro = _registro_completo()
    if onde == "resumo":
        registro.nome = f"cenario com {CHAVE_DO_MP}"
    else:
        # So o JSON tem este campo: a varredura do resumo nao o veria.
        registro.billing = {"referencia": CHAVE_DO_MP}

    with pytest.raises(EvidenciaComSegredoError) as erro:
        gravar_evidencia(
            tmp_path,
            [registro],
            modo="real",
            contexto="kind-x",
            prints=[],
            quando=QUANDO,
        )

    assert CHAVE_DO_MP not in str(erro.value)
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
    (tmp_path / "sub" / "junit.xml").write_text(f"ok\nBearer {CHAVE_DO_MP}\n")

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


def test_varredura_apaga_o_arquivo_com_o_token_do_ambiente_e_nao_o_repete(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Um processo novo: so conhece o token e a assinatura pelo ambiente do shell.
    segredos.esquecer_todos()
    (tmp_path / "junit.xml").write_text(
        f"a\nb {CHAVE_DO_MP}\nc {CHAVE_DO_MP} outra vez\n"
    )
    (tmp_path / "cucumber.json").write_text(
        json.dumps({"x": base64.b64encode(ASSINATURA.encode()).decode()})
    )
    (tmp_path / "resumo.md").write_text("limpo\n")
    ambiente = {
        "MP_ACCESS_TOKEN": CHAVE_DO_MP,
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
    assert CHAVE_DO_MP not in erro
    assert ASSINATURA not in erro
    assert sorted(p.name for p in tmp_path.iterdir()) == ["resumo.md"]


def test_varredura_sem_as_credenciais_no_ambiente_ainda_acha_os_padroes(
    tmp_path: Path,
) -> None:
    segredos.esquecer_todos()
    (tmp_path / "x.md").write_text("comprador@testuser.com\n")

    assert principal_da_varredura([str(tmp_path)], {}) == 1
    assert not (tmp_path / "x.md").exists()


@pytest.mark.parametrize("argumentos", [[], ["a", "b"]])
def test_varredura_exige_exatamente_uma_pasta(
    argumentos: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert principal_da_varredura(argumentos, {}) == 2
    assert "uso:" in capsys.readouterr().err


def test_o_json_da_varredura_aceita_dados_de_qualquer_tipo_na_saga() -> None:
    saga: dict[str, Any] = {"etapa": "x", "passos": [{"seq": 1, "extra": {"a": 1}}]}

    assert saga_resumida(saga)["passos"] == [{"seq": 1}]
