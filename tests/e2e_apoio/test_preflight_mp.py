"""Preflight do sandbox do Mercado Pago: cada recusa diz o que mudar, sem o token."""

from __future__ import annotations

import json
import os
import sys
from typing import TYPE_CHECKING, Any, cast

import httpx
import pytest

from e2e.apoio import preflight_mp, segredos
from e2e.apoio.http import ClienteHttp
from e2e.apoio.kube import ErroDeComandoError, Kubectl, executar_processo
from e2e.apoio.mercadopago import ErroDoMercadoPagoError, TokenRecusadoError
from e2e.apoio.modo_billing import URL_DE_NOTIFICACAO_PADRAO
from e2e.apoio.preflight_mp import (
    AVISO_DO_PAGAMENTO_ANTIGO,
    CHAVES_DO_SANDBOX,
    PreflightDoSandboxError,
    Sandbox,
    ambiente_do_sandbox,
    conferir_kind,
    conferir_overlay_kind,
    conferir_servicos,
    configmap_do_billing,
    credenciais_do_ambiente,
    preflight_do_sandbox,
    preparar_sandbox,
    retirar_credenciais,
)
from e2e_apoio.falsos import ExecutorFalso, Relogio

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

CHAVE_DO_MP = "TEST-1234567890123456-101420-0a1b2c3d4e5f60718293a4b5c6d7e8f9-123456789"
ASSINATURA = "assinatura-do-webhook-0123456789abcdef"
KIND = {
    "ORCAMENTO_VALIDADE_HORAS": "72",
    "PAGAMENTO_VALIDADE_MINUTOS": "60",
    "PAGAMENTO_MAX_RECUSAS": "3",
    "PRAZOS_INTERVALO_SEGUNDOS": "30",
    "MP_MODE": "simulado",
}
KIND_CI = {
    **KIND,
    "ORCAMENTO_VALIDADE_HORAS": "0.02",
    "PAGAMENTO_MAX_RECUSAS": "1",
    "PRAZOS_INTERVALO_SEGUNDOS": "5",
}
AMBIENTE = {
    "E2E_MP_MODO": "real",
    "MP_ACCESS_TOKEN": CHAVE_DO_MP,
    "MP_WEBHOOK_SECRET": ASSINATURA,
}


def _kubectl(
    configmap: dict[str, str] | None = None, contexto: str = "kind-x"
) -> Kubectl:
    executor = ExecutorFalso(
        {
            "get deployment": "billing-service-t5bghkfd67\n",
            "get configmap": json.dumps(configmap if configmap is not None else KIND),
        }
    )
    return Kubectl(contexto, executor=executor)


def _preparar(
    kubectl: Kubectl,
    borda: ClienteHttp,
    ambiente: Mapping[str, str],
    **opcoes: Any,
) -> Sandbox:
    """``preparar_sandbox`` com o relogio falso: o prazo dos servicos nao espera."""
    relogio = Relogio()
    return preparar_sandbox(
        kubectl, borda, ambiente, relogio=relogio, dormir=relogio.dormir, **opcoes
    )


def _borda(
    relogio: Relogio,
    *,
    modo: str = "simulado",
    status: dict[str, int] | None = None,
    corpo_do_billing: bytes | None = None,
) -> ClienteHttp:
    codigos = {"/os": 200, "/billing": 200, "/execucao": 200, **(status or {})}

    def responder(requisicao: httpx.Request) -> httpx.Response:
        prefixo = "/" + requisicao.url.path.split("/")[1]
        if codigos[prefixo] == 0:
            msg = "sem rota"
            raise httpx.ConnectError(msg)
        if prefixo == "/billing" and codigos[prefixo] == 200:
            corpo = (
                corpo_do_billing or json.dumps({"status": "ok", "modo": modo}).encode()
            )
            return httpx.Response(200, content=corpo)
        return httpx.Response(codigos[prefixo], json={"status": "ok"})

    return ClienteHttp(
        "https://localhost",
        transporte=httpx.MockTransport(responder),
        relogio=relogio,
        dormir=relogio.dormir,
    )


class MercadoPagoFalso:
    def __init__(self, erro: Exception | None = None) -> None:
        self.erro = erro
        self.fechado = False
        self.chave: str | None = None

    def validar_token(self) -> None:
        if self.erro:
            raise self.erro

    def fechar(self) -> None:
        self.fechado = True


def _fabrica(falso: MercadoPagoFalso) -> Callable[[str], Any]:
    def criar(token: str) -> MercadoPagoFalso:
        falso.chave = token
        return falso

    return criar


# --- o corte do ambiente -------------------------------------------------------------


def test_ambiente_do_sandbox_leva_so_as_chaves_do_sandbox() -> None:
    ambiente = {
        **AMBIENTE,
        "E2E_MP_MANTER": "1",
        "E2E_MP_NOTIFICATION_URL": "https://example.com/hook",
        "CREDENCIAL_DE_OUTRA_COISA": "outra-credencial-qualquer",
        "PATH": "/usr/bin",
    }

    recorte = ambiente_do_sandbox(ambiente)

    assert set(recorte) == set(CHAVES_DO_SANDBOX)
    assert recorte["MP_ACCESS_TOKEN"] == CHAVE_DO_MP
    assert "outra-credencial-qualquer" not in json.dumps(recorte)


def test_ambiente_do_sandbox_registra_as_credenciais_antes_de_conferir() -> None:
    # Mesmo mal lidas (com quebra de linha), ja saem mascaradas de um traceback.
    ambiente_do_sandbox(
        {"MP_ACCESS_TOKEN": CHAVE_DO_MP + "\n", "MP_WEBHOOK_SECRET": ASSINATURA + " "}
    )

    assert segredos.mascarar(f"{CHAVE_DO_MP} {ASSINATURA}") == "*** ***"


def test_ambiente_do_sandbox_sem_as_chaves_devolve_vazio_sem_quebrar() -> None:
    assert ambiente_do_sandbox({"PATH": "/usr/bin"}) == {}


# --- credenciais -----------------------------------------------------------------


def test_credenciais_do_ambiente_devolve_e_registra_na_mascara() -> None:
    token, assinatura = credenciais_do_ambiente(AMBIENTE)

    assert (token, assinatura) == (CHAVE_DO_MP, ASSINATURA)
    assert segredos.mascarar(f"{CHAVE_DO_MP} {ASSINATURA}") == "*** ***"


def test_credenciais_ausentes_ou_vazias_dizem_o_nome_e_como_ler_sem_expor_valor() -> (
    None
):
    vazias = dict.fromkeys(["MP_ACCESS_TOKEN"], "")

    with pytest.raises(PreflightDoSandboxError) as erro:
        credenciais_do_ambiente({**vazias, "OUTRA": "valor-qualquer"})

    texto = str(erro.value)
    assert "MP_ACCESS_TOKEN não está no ambiente" in texto
    assert "MP_WEBHOOK_SECRET não está no ambiente" in texto
    assert "valor-qualquer" not in texto
    # Sem export: a atribuicao no prefixo do comando leva o valor so ao make.
    assert "leia com `read -rs MP_ACCESS_TOKEN` e passe só ao make" in texto
    assert 'MP_ACCESS_TOKEN="$MP_ACCESS_TOKEN" make mp-sandbox' in texto
    assert 'MP_WEBHOOK_SECRET="$MP_WEBHOOK_SECRET" make mp-sandbox' in texto
    assert "nunca na linha do make" in texto
    assert "export" not in texto


@pytest.mark.parametrize(
    "valor",
    [
        pytest.param(CHAVE_DO_MP + "\n", id="quebra-de-linha-no-fim"),
        pytest.param(CHAVE_DO_MP + " ", id="espaco-no-fim"),
        pytest.param(" " + CHAVE_DO_MP, id="espaco-no-comeco"),
        pytest.param(CHAVE_DO_MP[:10] + " " + CHAVE_DO_MP[10:], id="espaco-no-meio"),
        pytest.param(CHAVE_DO_MP + "\t", id="tab"),
    ],
)
def test_token_com_espaco_ou_quebra_de_linha_e_recusado_sem_mostrar_o_valor(
    valor: str,
) -> None:
    with pytest.raises(PreflightDoSandboxError) as erro:
        credenciais_do_ambiente({**AMBIENTE, "MP_ACCESS_TOKEN": valor})

    texto = str(erro.value)
    assert "MP_ACCESS_TOKEN tem espaço ou quebra de linha" in texto
    assert CHAVE_DO_MP not in texto
    assert CHAVE_DO_MP[:10] not in texto
    assert str(len(valor)) not in texto
    assert "MP_WEBHOOK_SECRET" not in texto


def test_assinatura_com_quebra_de_linha_tambem_e_recusada() -> None:
    with pytest.raises(PreflightDoSandboxError, match="MP_WEBHOOK_SECRET tem espaço"):
        credenciais_do_ambiente({**AMBIENTE, "MP_WEBHOOK_SECRET": ASSINATURA + "\n"})


def test_credenciais_recusadas_nao_entram_na_mascara() -> None:
    with pytest.raises(PreflightDoSandboxError):
        credenciais_do_ambiente({**AMBIENTE, "MP_ACCESS_TOKEN": CHAVE_DO_MP + "\n"})

    assert segredos.mascarar(ASSINATURA) == ASSINATURA


# --- as credenciais saem do ambiente do processo ----------------------------


def test_retirar_credenciais_tira_so_as_duas_chaves() -> None:
    ambiente = {**AMBIENTE, "PATH": "/usr/bin"}

    retirar_credenciais(ambiente)

    assert ambiente == {"E2E_MP_MODO": "real", "PATH": "/usr/bin"}
    retirar_credenciais(ambiente)  # sem as chaves, nao quebra


def test_preflight_do_sandbox_devolve_as_credenciais_e_o_processo_as_esquece(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for chave, valor in AMBIENTE.items():
        monkeypatch.setenv(chave, valor)
    relogio = Relogio()

    sandbox = preflight_do_sandbox(
        _kubectl(),
        _borda(relogio),
        os.environ,
        cliente=_fabrica(MercadoPagoFalso()),
        avisar=lambda _: None,
        relogio=relogio,
        dormir=relogio.dormir,
    )

    assert (sandbox.token, sandbox.assinatura) == (CHAVE_DO_MP, ASSINATURA)
    assert "MP_ACCESS_TOKEN" not in os.environ
    assert "MP_WEBHOOK_SECRET" not in os.environ
    assert os.environ["E2E_MP_MODO"] == "real"


def test_o_kubectl_filho_nao_herda_as_credenciais_depois_do_preflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for chave, valor in AMBIENTE.items():
        monkeypatch.setenv(chave, valor)
    relogio = Relogio()
    preflight_do_sandbox(
        _kubectl(),
        _borda(relogio),
        os.environ,
        cliente=_fabrica(MercadoPagoFalso()),
        avisar=lambda _: None,
        relogio=relogio,
        dormir=relogio.dormir,
    )
    programa = (
        "import os; print(os.environ.get('MP_ACCESS_TOKEN'), "
        "os.environ.get('MP_WEBHOOK_SECRET'), os.environ.get('E2E_MP_MODO'))"
    )

    # O processo real, com o ambiente que o kubectl herdaria.
    saida = executar_processo([sys.executable, "-c", programa], 30)

    assert saida.strip() == "None None real"


def test_preflight_do_sandbox_so_passa_o_recorte_ao_preflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recebidos: list[Mapping[str, str]] = []
    preparado = Sandbox(modo="real")

    def espiar(
        kubectl: Kubectl, borda: ClienteHttp, ambiente: Mapping[str, str]
    ) -> Sandbox:
        del kubectl, borda
        recebidos.append(dict(ambiente))
        return preparado

    monkeypatch.setattr(preflight_mp, "preparar_sandbox", espiar)
    ambiente = {**AMBIENTE, "CREDENCIAL_DE_OUTRA_COISA": "valor-secreto-9999"}

    resultado = preflight_do_sandbox(
        _kubectl(),
        cast("ClienteHttp", None),  # a borda nao e usada pelo espiao
        ambiente,
    )

    assert resultado is preparado
    assert recebidos == [
        {
            "E2E_MP_MODO": "real",
            "MP_ACCESS_TOKEN": CHAVE_DO_MP,
            "MP_WEBHOOK_SECRET": ASSINATURA,
        }
    ]
    assert "CREDENCIAL_DE_OUTRA_COISA" in ambiente  # so as duas chaves saem dele


# --- kind e overlay -----------------------------------------------------------------


def test_conferir_kind_aceita_o_kind() -> None:
    conferir_kind("kind-pytstop-p4")


@pytest.mark.parametrize(
    "contexto", ["arn:aws:eks:us-east-1:1:cluster/producao", "k3s", "kind", "minikube"]
)
def test_conferir_kind_recusa_o_resto_e_diz_que_o_escape_nao_vale(
    contexto: str,
) -> None:
    with pytest.raises(PreflightDoSandboxError) as erro:
        conferir_kind(contexto)

    assert "Secret do cluster" in str(erro.value)
    assert "E2E_CONTEXTO_NAO_DESCARTAVEL não vale aqui" in str(erro.value)


def test_configmap_do_billing_le_o_que_a_api_usa_de_verdade() -> None:
    executor = ExecutorFalso(
        {
            "get deployment": "billing-service-abc123",
            "get configmap": json.dumps({"MP_MODE": "simulado"}),
        }
    )

    valores = configmap_do_billing(Kubectl("kind-x", executor=executor))

    assert valores == {"MP_MODE": "simulado"}
    assert "get deployment billing-service-api" in " ".join(executor.comandos[0])
    # Pelo nome do container e por todos os envFrom, e nao pela posicao nas listas.
    assert '[?(@.name=="api")].envFrom[*].configMapRef.name' in " ".join(
        executor.comandos[0]
    )
    assert "containers[0]" not in " ".join(executor.comandos[0])
    assert "envFrom[0]" not in " ".join(executor.comandos[0])
    assert "get configmap billing-service-abc123" in " ".join(executor.comandos[1])
    assert "-n pytstop-billing" in " ".join(executor.comandos[1])


def test_configmap_do_billing_junta_os_envfrom_e_o_ultimo_vence_a_chave_repetida() -> (
    None
):
    executor = ExecutorFalso(
        {
            "get deployment": "cm-base cm-overlay",
            "configmap cm-base": json.dumps({"MP_MODE": "simulado", "A": "1"}),
            "configmap cm-overlay": json.dumps({"MP_MODE": "mercadopago", "B": "2"}),
        }
    )

    valores = configmap_do_billing(Kubectl("kind-x", executor=executor))

    assert valores == {"MP_MODE": "mercadopago", "A": "1", "B": "2"}


def test_configmap_do_billing_sem_envfrom_diz_o_que_falta() -> None:
    kubectl = Kubectl("kind-x", executor=ExecutorFalso())

    with pytest.raises(PreflightDoSandboxError, match="não referencia um ConfigMap"):
        configmap_do_billing(kubectl)


def test_configmap_ilegivel_diz_qual_e_nao_estoura_com_json_decode_error() -> None:
    executor = ExecutorFalso(
        {"get deployment": "billing-service-abc", "get configmap": "nao e json"}
    )

    with pytest.raises(PreflightDoSandboxError, match="ConfigMap billing-service-abc"):
        configmap_do_billing(Kubectl("kind-x", executor=executor))


def test_overlay_kind_passa_e_devolve_as_recusas_que_encerram_a_cobranca() -> None:
    assert conferir_overlay_kind(_kubectl()) == 3


def test_overlay_kind_ci_e_recusado_dizendo_cada_prazo_curto_e_o_que_fazer() -> None:
    with pytest.raises(PreflightDoSandboxError) as erro:
        conferir_overlay_kind(_kubectl({**KIND_CI, "PAGAMENTO_VALIDADE_MINUTOS": "5"}))

    texto = str(erro.value)
    assert "orçamento vence em 0.02 h" in texto
    assert "cobrança vale 5.0 min" in texto
    assert "PAGAMENTO_MAX_RECUSAS=1.0" in texto
    assert "overlay kind" in texto
    assert "make kind-up deploy" in texto


@pytest.mark.parametrize(
    ("troca", "trecho"),
    [
        pytest.param(
            {"ORCAMENTO_VALIDADE_HORAS": "0.5"},
            "ORCAMENTO_VALIDADE_HORAS",
            id="validade",
        ),
        pytest.param(
            {"PAGAMENTO_VALIDADE_MINUTOS": "14"},
            "PAGAMENTO_VALIDADE_MINUTOS",
            id="cobranca",
        ),
        pytest.param(
            {"PAGAMENTO_MAX_RECUSAS": "1"}, "PAGAMENTO_MAX_RECUSAS", id="recusas"
        ),
    ],
)
def test_overlay_kind_recusa_cada_prazo_curto_sozinho(
    troca: dict[str, str], trecho: str
) -> None:
    with pytest.raises(PreflightDoSandboxError, match=trecho):
        conferir_overlay_kind(_kubectl({**KIND, **troca}))


def test_overlay_kind_aceita_o_limite_de_cada_prazo() -> None:
    limite = {
        **KIND,
        "ORCAMENTO_VALIDADE_HORAS": "1",
        "PAGAMENTO_VALIDADE_MINUTOS": "15",
        "PAGAMENTO_MAX_RECUSAS": "2",
    }

    assert conferir_overlay_kind(_kubectl(limite)) == 2


def test_overlay_kind_com_chaves_ausentes_ou_ilegiveis_e_recusado() -> None:
    with pytest.raises(PreflightDoSandboxError) as erro:
        conferir_overlay_kind(_kubectl({"ORCAMENTO_VALIDADE_HORAS": "muitas"}))

    assert "ORCAMENTO_VALIDADE_HORAS" in str(erro.value)
    assert "PAGAMENTO_VALIDADE_MINUTOS" in str(erro.value)
    assert "PAGAMENTO_MAX_RECUSAS=None" in str(erro.value)


# --- servicos ------------------------------------------------------------------------


def test_conferir_servicos_devolve_o_modo_do_billing(relogio: Relogio) -> None:
    assert (
        conferir_servicos(
            _borda(relogio, modo="mercadopago"), relogio=relogio, dormir=relogio.dormir
        )
        == "mercadopago"
    )
    assert (
        conferir_servicos(_borda(relogio), relogio=relogio, dormir=relogio.dormir)
        == "simulado"
    )


@pytest.mark.parametrize(
    ("status", "trecho"),
    [
        pytest.param({"/os": 503}, "/os respondeu HTTP 503", id="os-503"),
        pytest.param(
            {"/execucao": 404}, "/execucao respondeu HTTP 404", id="execucao-404"
        ),
        pytest.param(
            {"/billing": 502}, "/billing respondeu HTTP 502", id="billing-502"
        ),
        pytest.param({"/os": 0}, "/os não respondeu (ConnectError)", id="os-sem-rede"),
    ],
)
def test_servico_fora_do_ar_reprova_dizendo_qual(
    status: dict[str, int], trecho: str, relogio: Relogio
) -> None:
    with pytest.raises(PreflightDoSandboxError) as erro:
        conferir_servicos(
            _borda(relogio, status=status), relogio=relogio, dormir=relogio.dormir
        )

    assert trecho in str(erro.value)
    assert 'README, "Mercado Pago na sandbox", "Como rodar"' in str(erro.value)


def test_servico_que_demora_a_responder_e_esperado_ate_o_prazo(
    relogio: Relogio,
) -> None:
    respostas = iter([503, 503, 200, 200, 200])

    def responder(requisicao: httpx.Request) -> httpx.Response:
        if requisicao.url.path.startswith("/os"):
            return httpx.Response(next(respostas))
        return httpx.Response(200, json={"modo": "simulado"})

    borda = ClienteHttp(
        "https://localhost",
        transporte=httpx.MockTransport(responder),
        relogio=relogio,
        dormir=relogio.dormir,
    )

    assert (
        conferir_servicos(borda, relogio=relogio, dormir=relogio.dormir) == "simulado"
    )
    assert relogio.dormidas == [2.0, 2.0]


@pytest.mark.parametrize(
    "corpo",
    [
        pytest.param(b'{"status": "ok", "modo": "outro"}', id="modo-desconhecido"),
        pytest.param(b'{"status": "ok"}', id="sem-modo"),
        pytest.param(b"nao e json", id="sem-json"),
        pytest.param(b'["modo"]', id="json-nao-objeto"),
    ],
)
def test_billing_com_modo_que_nao_e_conhecido_reprova(
    corpo: bytes, relogio: Relogio
) -> None:
    with pytest.raises(PreflightDoSandboxError, match="/billing diz o modo"):
        conferir_servicos(
            _borda(relogio, corpo_do_billing=corpo),
            relogio=relogio,
            dormir=relogio.dormir,
        )


# --- tudo junto ----------------------------------------------------------------------


def test_preparar_sandbox_real_devolve_o_que_a_sessao_precisa(relogio: Relogio) -> None:
    mp = MercadoPagoFalso()

    sandbox = _preparar(
        _kubectl(),
        _borda(relogio),
        {
            **AMBIENTE,
            "E2E_MP_MANTER": "1",
            "E2E_MP_NOTIFICATION_URL": "https://example.com/hook",
        },
        cliente=_fabrica(mp),
    )

    assert sandbox.real
    assert sandbox.modo == "real"
    assert (sandbox.token, sandbox.assinatura) == (CHAVE_DO_MP, ASSINATURA)
    assert sandbox.manter is True
    assert sandbox.url_de_notificacao == "https://example.com/hook"
    assert sandbox.max_recusas == 3
    assert id(sandbox.mercadopago) == id(mp)
    assert mp.chave == CHAVE_DO_MP


def test_modo_real_sem_url_usa_a_padrao_publica_e_diz_qual(relogio: Relogio) -> None:
    avisos: list[str] = []

    sandbox = _preparar(
        _kubectl(),
        _borda(relogio),
        AMBIENTE,
        cliente=_fabrica(MercadoPagoFalso()),
        avisar=avisos.append,
    )

    assert sandbox.url_de_notificacao == URL_DE_NOTIFICACAO_PADRAO
    assert URL_DE_NOTIFICACAO_PADRAO == (
        "https://example.com/api/v1/webhooks/mercadopago"
    )
    assert (
        "[mp-sandbox] notification_url: "
        "https://example.com/api/v1/webhooks/mercadopago (padrão do modo real); "
        "a sandbox não envia notificação, então o webhook não é exercitado"
    ) in avisos


def test_modo_real_com_url_propria_usa_a_dela_e_nao_imprime_a_consulta(
    relogio: Relogio,
) -> None:
    avisos: list[str] = []
    url = "https://meu-tunel.ngrok.app/hook?token=segredo-na-consulta"

    sandbox = _preparar(
        _kubectl(),
        _borda(relogio),
        {**AMBIENTE, "E2E_MP_NOTIFICATION_URL": url},
        cliente=_fabrica(MercadoPagoFalso()),
        avisar=avisos.append,
    )

    assert sandbox.url_de_notificacao == url
    aviso = next(a for a in avisos if "notification_url:" in a)
    assert "https://meu-tunel.ngrok.app/hook (E2E_MP_NOTIFICATION_URL)" in aviso
    assert "segredo-na-consulta" not in " ".join(avisos)


def test_modo_real_lembra_do_pagamento_que_um_ensaio_antigo_deixa(
    relogio: Relogio,
) -> None:
    avisos: list[str] = []

    _preparar(
        _kubectl(),
        _borda(relogio),
        AMBIENTE,
        cliente=_fabrica(MercadoPagoFalso()),
        avisar=avisos.append,
    )

    assert AVISO_DO_PAGAMENTO_ANTIGO in avisos
    assert "make kind-down kind-up" in AVISO_DO_PAGAMENTO_ANTIGO
    assert "conciliado no Mercado Pago de verdade" in AVISO_DO_PAGAMENTO_ANTIGO


def test_ensaio_nao_imprime_url_nem_aviso_de_pagamento_antigo(
    relogio: Relogio,
) -> None:
    avisos: list[str] = []

    _preparar(
        _kubectl(), _borda(relogio), {"E2E_MP_MODO": "ensaio"}, avisar=avisos.append
    )

    assert avisos == []


def test_preparar_sandbox_nao_poe_o_token_no_repr() -> None:
    sandbox = Sandbox(modo="real", token=CHAVE_DO_MP, assinatura=ASSINATURA)

    assert CHAVE_DO_MP not in repr(sandbox)
    assert ASSINATURA not in repr(sandbox)


def test_preparar_sandbox_ensaio_nao_pede_credencial_nem_fala_com_o_mercado_pago(
    relogio: Relogio,
) -> None:
    sandbox = _preparar(
        _kubectl(),
        _borda(relogio),
        {
            "E2E_MP_MODO": "ensaio",
            "E2E_MP_MANTER": "1",
            "E2E_MP_NOTIFICATION_URL": "http://ignorada",
        },
        cliente=_fabrica(
            MercadoPagoFalso(erro=AssertionError("nao devia ser chamado"))
        ),
    )

    assert not sandbox.real
    assert not sandbox.token
    assert sandbox.mercadopago is None
    assert sandbox.manter is False
    assert sandbox.url_de_notificacao == ""


@pytest.mark.parametrize("modo", ["", "tanto-faz", "REAL"])
def test_preparar_sandbox_exige_real_ou_ensaio(modo: str, relogio: Relogio) -> None:
    kubectl = _kubectl()

    with pytest.raises(PreflightDoSandboxError, match=r"use real .* ou ensaio"):
        _preparar(kubectl, _borda(relogio), {"E2E_MP_MODO": modo})


def test_preparar_sandbox_fora_do_kind_nao_chega_a_chamar_o_kubectl(
    relogio: Relogio,
) -> None:
    executor = ExecutorFalso()

    with pytest.raises(PreflightDoSandboxError, match="não é um kind"):
        _preparar(
            Kubectl("arn:aws:eks:x:1:cluster/prod", executor=executor),
            _borda(relogio),
            {
                **AMBIENTE,
                "E2E_CONTEXTO_NAO_DESCARTAVEL": "arn:aws:eks:x:1:cluster/prod",
            },
        )

    assert executor.comandos == []


def test_preparar_sandbox_sem_credencial_falha_antes_de_tocar_no_cluster(
    relogio: Relogio,
) -> None:
    executor = ExecutorFalso()

    with pytest.raises(PreflightDoSandboxError, match="MP_ACCESS_TOKEN não está"):
        _preparar(
            Kubectl("kind-x", executor=executor),
            _borda(relogio),
            {"E2E_MP_MODO": "real"},
        )

    assert executor.comandos == []


def test_preparar_sandbox_com_url_local_reprova_antes_do_cluster(
    relogio: Relogio,
) -> None:
    executor = ExecutorFalso()

    with pytest.raises(PreflightDoSandboxError, match="https pública"):
        _preparar(
            Kubectl("kind-x", executor=executor),
            _borda(relogio),
            {**AMBIENTE, "E2E_MP_NOTIFICATION_URL": "https://localhost/webhook"},
        )

    assert executor.comandos == []


def test_preparar_sandbox_com_overlay_errado_reprova_antes_de_chamar_o_mercado_pago(
    relogio: Relogio,
) -> None:
    mp = MercadoPagoFalso()

    with pytest.raises(PreflightDoSandboxError, match="kind-ci"):
        _preparar(_kubectl(KIND_CI), _borda(relogio), AMBIENTE, cliente=_fabrica(mp))

    assert mp.chave is None


def test_preparar_sandbox_com_servico_fora_reprova_antes_de_chamar_o_mercado_pago(
    relogio: Relogio,
) -> None:
    mp = MercadoPagoFalso()

    with pytest.raises(PreflightDoSandboxError, match="serviços fora do ar"):
        _preparar(
            _kubectl(),
            _borda(relogio, status={"/os": 503}),
            AMBIENTE,
            cliente=_fabrica(mp),
        )

    assert mp.chave is None


def test_token_que_o_mercado_pago_recusa_diz_o_que_fazer_sem_o_valor(
    relogio: Relogio,
) -> None:
    mp = MercadoPagoFalso(
        erro=TokenRecusadoError("invalid token " + CHAVE_DO_MP, status=401)
    )

    with pytest.raises(PreflightDoSandboxError) as erro:
        _preparar(_kubectl(), _borda(relogio), AMBIENTE, cliente=_fabrica(mp))

    texto = str(erro.value)
    assert "HTTP 401" in texto
    assert "Access Token de teste" in texto
    assert "read -rs" in texto
    assert CHAVE_DO_MP not in texto
    assert mp.fechado


def test_mercado_pago_fora_do_ar_diz_que_nao_conseguiu_falar_com_ele(
    relogio: Relogio,
) -> None:
    mp = MercadoPagoFalso(
        erro=ErroDoMercadoPagoError("sem resposta do Mercado Pago em /x: ConnectError")
    )

    with pytest.raises(
        PreflightDoSandboxError,
        match=r"não consegui falar com o Mercado Pago.*ConnectError",
    ):
        _preparar(_kubectl(), _borda(relogio), AMBIENTE, cliente=_fabrica(mp))

    assert mp.fechado


def test_kubectl_que_falha_na_leitura_do_billing_vira_recusa_clara(
    relogio: Relogio,
) -> None:
    class KubectlFora(ExecutorFalso):
        def __call__(self, argumentos: Sequence[str], prazo: float) -> str:
            msg = "kubectl get deployment: saiu com 1: NotFound"
            raise ErroDeComandoError(msg)

    with pytest.raises(PreflightDoSandboxError) as erro:
        _preparar(
            Kubectl("kind-x", executor=KubectlFora()),
            _borda(relogio),
            {"E2E_MP_MODO": "ensaio"},
        )

    assert "o kubectl falhou ao ler a configuração do Billing" in str(erro.value)
    assert "NotFound" in str(erro.value)


@pytest.mark.parametrize("status", [400, 404, 422, 499])
def test_conferencia_do_token_com_4xx_que_nao_e_de_credencial_avisa_e_segue(
    status: int, relogio: Relogio
) -> None:
    avisos: list[str] = []
    mp = MercadoPagoFalso(
        erro=ErroDoMercadoPagoError("GET /v1/payments/search: HTTP 400", status=status)
    )

    sandbox = _preparar(
        _kubectl(),
        _borda(relogio),
        AMBIENTE,
        cliente=_fabrica(mp),
        avisar=avisos.append,
    )

    assert id(sandbox.mercadopago) == id(mp)
    assert not mp.fechado
    aviso = next(a for a in avisos if "a conferência do token respondeu" in a)
    assert aviso.startswith("[mp-sandbox] atenção:")
    assert "o roteiro segue sem ela" in aviso
    assert all(CHAVE_DO_MP not in a for a in avisos)


@pytest.mark.parametrize("status", [500, 502, 503, None])
def test_mercado_pago_que_nao_responde_ou_cai_barra_o_roteiro(
    status: int | None, relogio: Relogio
) -> None:
    avisos: list[str] = []
    mp = MercadoPagoFalso(erro=ErroDoMercadoPagoError("sem resposta", status=status))

    with pytest.raises(PreflightDoSandboxError, match="não consegui falar"):
        _preparar(
            _kubectl(),
            _borda(relogio),
            AMBIENTE,
            cliente=_fabrica(mp),
            avisar=avisos.append,
        )

    assert mp.fechado
    assert avisos == []
