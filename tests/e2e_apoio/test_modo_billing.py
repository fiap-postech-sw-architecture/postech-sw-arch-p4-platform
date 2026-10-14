"""Modo do Billing: liga o Mercado Pago real, desfaz sempre, token fora do argv."""

from __future__ import annotations

import base64
import json
import signal
from typing import TYPE_CHECKING

import httpx
import pytest

from e2e.apoio import segredos
from e2e.apoio.espera import TempoEsgotadoError
from e2e.apoio.kube import ErroDeComandoError, Kubectl
from e2e.apoio.modo_billing import (
    MODO_REAL,
    MODO_SIMULADO,
    NAMESPACE_BILLING,
    SEGREDO,
    DesfazerFalhouError,
    ModoDoBilling,
    UrlDeNotificacaoInvalidaError,
    comandos_a_mao,
    manifesto_do_segredo,
    sem_interrupcao,
    url_de_notificacao_valida,
)
from e2e_apoio.falsos import chamadas_do_gravador, criar_kubectl_gravador

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from pathlib import Path

    from e2e_apoio.falsos import Relogio

CHAVE_DO_MP = "TEST-1234567890123456-101420-0a1b2c3d4e5f60718293a4b5c6d7e8f9-123456789"
ASSINATURA = "assinatura-do-webhook-0123456789abcdef"
URL = "https://example.com/api/v1/webhooks/mercadopago"


def _b64(valor: str) -> str:
    return base64.b64encode(valor.encode()).decode()


class Cluster:
    """O kubectl do Billing: grava as chamadas e muda o modo como o rollout muda."""

    def __init__(
        self, *, falhas: Sequence[str] = (), modo_real_pega: bool = True
    ) -> None:
        self.chamadas: list[tuple[str, str | None]] = []
        self.sinais_durante: list[object] = []
        self.modo = MODO_SIMULADO
        self._falhas = falhas
        self._modo_real_pega = modo_real_pega

    def __call__(
        self, argumentos: Sequence[str], prazo: float, entrada: str | None = None
    ) -> str:
        del prazo
        juntos = " ".join(argumentos)
        self.chamadas.append((juntos, entrada))
        self.sinais_durante.append(signal.getsignal(signal.SIGINT))
        for trecho in self._falhas:
            if trecho in juntos:
                msg = f"{trecho}: saiu com 1: erro do kubectl com {CHAVE_DO_MP}"
                raise ErroDeComandoError(segredos.mascarar(msg))
        if (
            "set env" in juntos
            and "MP_MODE=mercadopago" in juntos
            and self._modo_real_pega
        ):
            self.modo = MODO_REAL
        if "set env" in juntos and "MP_MODE-" in juntos:
            self.modo = MODO_SIMULADO
        if "get deployment -o name" in juntos:
            return (
                "deployment.apps/billing-service-api\n"
                "deployment.apps/billing-service-relay\n"
            )
        return ""

    def comandos(self) -> list[str]:
        return [comando for comando, _ in self.chamadas]

    def kubectl(self) -> Kubectl:
        return Kubectl("kind-x", executor=self, executor_com_entrada=self)

    def saude(self) -> str:
        return self.modo


def _modo(
    cluster: Cluster, relogio: Relogio, **opcoes: str
) -> tuple[ModoDoBilling, list[str]]:
    avisos: list[str] = []
    modo = ModoDoBilling(
        cluster.kubectl(),
        cluster.saude,
        avisar=avisos.append,
        relogio=relogio,
        dormir=relogio.dormir,
        **opcoes,
    )
    return modo, avisos


# --- a URL do webhook ---------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        URL,
        "https://meu-tunel.ngrok.app/api/v1/webhooks/mercadopago",
        "https://203.0.113.10/webhook",
    ],
)
def test_url_de_notificacao_publica_passa(url: str) -> None:
    assert url_de_notificacao_valida(url) == url


@pytest.mark.parametrize(
    "url",
    [
        pytest.param("http://example.com/webhook", id="http"),
        pytest.param(
            "https://localhost/billing/api/v1/webhooks/mercadopago", id="localhost"
        ),
        pytest.param("https://127.0.0.1/webhook", id="loopback"),
        pytest.param("https://[::1]/webhook", id="ipv6-loopback"),
        pytest.param("https://billing.localhost/webhook", id="sufixo-localhost"),
        pytest.param("https://billing.local/webhook", id="sufixo-local"),
        pytest.param("https://billing.internal/webhook", id="sufixo-internal"),
        pytest.param("https://usuario:senha@example.com/webhook", id="com-usuario"),
        pytest.param("https:///sem-host", id="sem-host"),
        pytest.param("example.com/webhook", id="sem-esquema"),
    ],
)
def test_url_de_notificacao_local_ou_insegura_e_recusada(url: str) -> None:
    with pytest.raises(UrlDeNotificacaoInvalidaError, match="https pública"):
        url_de_notificacao_valida(url)


# --- o manifesto do Secret ------------------------------------------------------


def test_manifesto_do_segredo_leva_os_dois_valores_em_base64_e_nada_mais() -> None:
    manifesto = manifesto_do_segredo(CHAVE_DO_MP, ASSINATURA)

    assert manifesto["kind"] == "Secret"
    assert manifesto["metadata"] == {"name": SEGREDO, "namespace": NAMESPACE_BILLING}
    assert manifesto["data"] == {
        "MP_ACCESS_TOKEN": _b64(CHAVE_DO_MP),
        "MP_WEBHOOK_SECRET": _b64(ASSINATURA),
    }
    assert SEGREDO == "billing-mercadopago"


def test_manifesto_do_segredo_registra_os_valores_e_o_base64_na_mascara() -> None:
    manifesto_do_segredo(CHAVE_DO_MP, ASSINATURA)

    texto = (
        f"token {CHAVE_DO_MP}, assinatura {ASSINATURA}, "
        f"b64 {_b64(CHAVE_DO_MP)} e {_b64(ASSINATURA)}"
    )
    mascarado = segredos.mascarar(texto)
    for valor in (CHAVE_DO_MP, ASSINATURA, _b64(CHAVE_DO_MP), _b64(ASSINATURA)):
        assert valor not in mascarado


# --- Ctrl-C --------------------------------------------------------------------


def test_sem_interrupcao_ignora_ctrl_c_e_sigterm_e_restaura_no_fim() -> None:
    antes = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM)}

    with sem_interrupcao():
        assert signal.getsignal(signal.SIGINT) == signal.SIG_IGN
        assert signal.getsignal(signal.SIGTERM) == signal.SIG_IGN

    assert {s: signal.getsignal(s) for s in antes} == antes


def test_sem_interrupcao_restaura_mesmo_com_excecao() -> None:
    antes = signal.getsignal(signal.SIGINT)

    def falha_no_meio() -> None:
        with sem_interrupcao():
            msg = "falhou no meio"
            raise RuntimeError(msg)

    with pytest.raises(RuntimeError):
        falha_no_meio()

    assert signal.getsignal(signal.SIGINT) == antes


def test_comandos_a_mao_sao_os_tres_passos_do_desfazer() -> None:
    texto = comandos_a_mao("kind-pytstop-p4")

    assert texto.count("kubectl --context kind-pytstop-p4 -n pytstop-billing") == 3
    assert f"delete secret {SEGREDO} --ignore-not-found" in texto
    assert (
        "set env deployment --all MP_MODE- SIMULADOR_PERMITIDO- MP_NOTIFICATION_URL-"
        in texto
    )
    assert "rollout restart deployment" in texto


# --- ligar o modo real ------------------------------------------------------------


def test_ligar_real_cria_o_secret_pelo_stdin_troca_o_modo_reinicia_e_espera(
    relogio: Relogio,
) -> None:
    cluster = Cluster()
    modo, avisos = _modo(cluster, relogio)

    modo.ligar_real(CHAVE_DO_MP, ASSINATURA)

    comandos = cluster.comandos()
    assert comandos[0].endswith("apply --server-side --force-conflicts -f -")
    assert comandos[1].endswith(
        f"-n {NAMESPACE_BILLING} set env deployment --all "
        "MP_MODE=mercadopago SIMULADOR_PERMITIDO=false"
    )
    assert comandos[2].endswith(f"-n {NAMESPACE_BILLING} rollout restart deployment")
    esperas = [c for c in comandos if "rollout status" in c]
    assert [c.split("deployment/")[1].split()[0] for c in esperas] == [
        "billing-service-api",
        "billing-service-relay",
    ]
    assert cluster.modo == MODO_REAL
    assert any("modo real" in aviso for aviso in avisos)


def test_ligar_real_com_url_de_notificacao_tambem_a_aplica(relogio: Relogio) -> None:
    cluster = Cluster()
    modo, _ = _modo(cluster, relogio, url_de_notificacao=URL)

    modo.ligar_real(CHAVE_DO_MP, ASSINATURA)

    assert f"MP_NOTIFICATION_URL={URL}" in cluster.comandos()[1]


def test_ligar_real_so_volta_com_a_api_dizendo_mercadopago(relogio: Relogio) -> None:
    cluster = Cluster(modo_real_pega=False)
    modo, _ = _modo(cluster, relogio)

    with pytest.raises(TempoEsgotadoError, match="modo mercadopago"):
        modo.ligar_real(CHAVE_DO_MP, ASSINATURA)


def test_ligar_real_espera_a_api_voltar_depois_do_rollout(relogio: Relogio) -> None:
    cluster = Cluster()
    respostas: Iterator[Exception | str] = iter(
        [httpx.ConnectError("api reiniciando"), "simulado", "mercadopago"]
    )

    def saude() -> str:
        resposta = next(respostas)
        if isinstance(resposta, Exception):
            raise resposta
        return resposta

    modo = ModoDoBilling(
        cluster.kubectl(),
        saude,
        avisar=lambda _: None,
        relogio=relogio,
        dormir=relogio.dormir,
    )

    modo.ligar_real(CHAVE_DO_MP, ASSINATURA)

    assert relogio.dormidas == [2.0, 2.0]


def test_o_token_so_passa_pelo_stdin_e_nunca_pelo_argv_nem_por_arquivo(
    tmp_path: Path, relogio: Relogio
) -> None:
    kubectl_gravador = criar_kubectl_gravador(tmp_path)
    kubectl = Kubectl("kind-x", binario=str(kubectl_gravador))
    modo = ModoDoBilling(
        kubectl,
        lambda: MODO_REAL,
        avisar=lambda _: None,
        relogio=relogio,
        dormir=relogio.dormir,
    )

    modo.ligar_real(CHAVE_DO_MP, ASSINATURA)

    chamadas = chamadas_do_gravador(kubectl_gravador)
    argvs = [json.dumps(c["argv"]) for c in chamadas]
    for segredo in (CHAVE_DO_MP, ASSINATURA, _b64(CHAVE_DO_MP), _b64(ASSINATURA)):
        assert not any(segredo in argv for argv in argvs), "segredo no argv"
    assert not any("MP_ACCESS_TOKEN" in argv or "Secret" in argv for argv in argvs)
    com_stdin = [c for c in chamadas if c["stdin"]]
    assert len(com_stdin) == 1
    aplicar = com_stdin[0]
    assert aplicar["argv"][-5:] == [
        "apply",
        "--server-side",
        "--force-conflicts",
        "-f",
        "-",
    ]
    manifesto = json.loads(str(aplicar["stdin"]))
    assert manifesto["kind"] == "Secret"
    assert (
        base64.b64decode(manifesto["data"]["MP_ACCESS_TOKEN"]).decode() == CHAVE_DO_MP
    )
    assert (
        base64.b64decode(manifesto["data"]["MP_WEBHOOK_SECRET"]).decode() == ASSINATURA
    )
    # So o diretorio do kubectl falso: o codigo do E2E nao gravou arquivo nenhum.
    assert sorted(p.name for p in tmp_path.iterdir()) == ["chamadas.jsonl", "kubectl"]


def test_o_kubectl_que_falha_no_apply_nao_repete_o_token_na_mensagem(
    relogio: Relogio,
) -> None:
    cluster = Cluster(falhas=("apply",))
    modo, _ = _modo(cluster, relogio)

    with pytest.raises(ErroDeComandoError) as erro:
        modo.ligar_real(CHAVE_DO_MP, ASSINATURA)

    assert CHAVE_DO_MP not in str(erro.value)
    assert "***" in str(erro.value)


# --- desfazer -----------------------------------------------------------------------


def test_desfazer_apaga_o_secret_tira_as_variaveis_reinicia_e_espera(
    relogio: Relogio,
) -> None:
    cluster = Cluster()
    cluster.modo = MODO_REAL
    modo, avisos = _modo(cluster, relogio)

    modo.desfazer()

    comandos = cluster.comandos()
    assert comandos[0].endswith(f"delete secret {SEGREDO} --ignore-not-found")
    assert comandos[1].endswith(
        "set env deployment --all MP_MODE- SIMULADOR_PERMITIDO- MP_NOTIFICATION_URL-"
    )
    assert comandos[2].endswith("rollout restart deployment")
    assert sum("rollout status" in c for c in comandos) == 2
    assert cluster.modo == MODO_SIMULADO
    assert any("desfazendo" in aviso for aviso in avisos)


def test_desfazer_roda_sem_interrupcao_e_devolve_os_sinais(relogio: Relogio) -> None:
    cluster = Cluster()
    cluster.modo = MODO_REAL
    modo, _ = _modo(cluster, relogio)
    antes = signal.getsignal(signal.SIGINT)

    modo.desfazer()

    assert set(cluster.sinais_durante) == {signal.SIG_IGN}
    assert signal.getsignal(signal.SIGINT) == antes


@pytest.mark.parametrize(
    ("falha", "passo"),
    [
        pytest.param("delete secret", "apagar o Secret", id="apagar-o-secret"),
        pytest.param(
            "set env", "tirar MP_MODE e SIMULADOR_PERMITIDO", id="tirar-as-variaveis"
        ),
        pytest.param(
            "rollout restart", "reiniciar e esperar o Billing", id="reiniciar"
        ),
        pytest.param("rollout status", "reiniciar e esperar o Billing", id="esperar"),
    ],
)
def test_desfazer_com_um_passo_falho_faz_os_outros_e_diz_o_que_rodar_a_mao(
    falha: str, passo: str, relogio: Relogio
) -> None:
    cluster = Cluster(falhas=(falha,))
    cluster.modo = MODO_REAL
    modo, _ = _modo(cluster, relogio)

    with pytest.raises(DesfazerFalhouError) as erro:
        modo.desfazer()

    texto = str(erro.value)
    assert passo in texto
    assert (
        "Termine à mão: kubectl --context kind-x -n pytstop-billing delete secret"
        in texto
    )
    assert CHAVE_DO_MP not in texto
    comandos = cluster.comandos()
    for esperado in ("delete secret", "set env", "rollout restart"):
        assert any(esperado in c for c in comandos), f"{esperado} nao rodou"


def test_desfazer_que_nao_chega_ao_simulador_diz_que_o_modo_nao_voltou(
    relogio: Relogio,
) -> None:
    cluster = Cluster()
    # O Billing segue dizendo mercadopago depois de tudo.
    modo = ModoDoBilling(
        cluster.kubectl(),
        lambda: MODO_REAL,
        avisar=lambda _: None,
        relogio=relogio,
        dormir=relogio.dormir,
    )

    with pytest.raises(DesfazerFalhouError, match="modo simulado"):
        modo.desfazer()


# --- a sessao ------------------------------------------------------------------------


def test_sessao_real_liga_no_inicio_e_desfaz_no_fim(relogio: Relogio) -> None:
    cluster = Cluster()
    modo, _ = _modo(cluster, relogio)

    with modo.sessao(real=True, token=CHAVE_DO_MP, assinatura=ASSINATURA):
        assert cluster.modo == MODO_REAL
        assert not any("delete secret" in c for c in cluster.comandos())

    assert cluster.modo == MODO_SIMULADO
    assert any("delete secret" in c for c in cluster.comandos())


def test_sessao_real_desfaz_mesmo_quando_o_corpo_levanta(relogio: Relogio) -> None:
    cluster = Cluster()
    modo, _ = _modo(cluster, relogio)

    with (
        pytest.raises(KeyboardInterrupt),
        modo.sessao(real=True, token=CHAVE_DO_MP, assinatura=ASSINATURA),
    ):
        raise KeyboardInterrupt

    assert cluster.modo == MODO_SIMULADO
    assert any("delete secret" in c for c in cluster.comandos())


def test_sessao_real_desfaz_mesmo_quando_ligar_falha_no_meio(relogio: Relogio) -> None:
    cluster = Cluster(falhas=("rollout restart",))
    modo, _ = _modo(cluster, relogio)
    cluster.modo = MODO_REAL

    with (
        pytest.raises(DesfazerFalhouError) as erro,
        modo.sessao(real=True, token=CHAVE_DO_MP, assinatura=ASSINATURA),
    ):
        pytest.fail("o corpo nao devia rodar")  # pragma: no cover

    # O desfazer tambem falhou no restart; o apagar e o tirar variaveis rodaram.
    assert "reiniciar" in str(erro.value)
    assert any("delete secret" in c for c in cluster.comandos())


def test_sessao_real_com_falha_do_apply_desfaz_e_propaga_o_erro_original(
    relogio: Relogio,
) -> None:
    cluster = Cluster(falhas=("apply",))
    modo, _ = _modo(cluster, relogio)

    with (
        pytest.raises(ErroDeComandoError, match="apply"),
        modo.sessao(real=True, token=CHAVE_DO_MP, assinatura=ASSINATURA),
    ):
        pytest.fail("o corpo nao devia rodar")  # pragma: no cover

    assert any("delete secret" in c for c in cluster.comandos())


def test_sessao_real_com_manter_nao_desfaz_e_diz_como_voltar(relogio: Relogio) -> None:
    cluster = Cluster()
    modo, avisos = _modo(cluster, relogio)

    with modo.sessao(real=True, token=CHAVE_DO_MP, assinatura=ASSINATURA, manter=True):
        pass

    assert cluster.modo == MODO_REAL
    assert not any("delete secret" in c for c in cluster.comandos())
    assert any(
        "E2E_MP_MANTER=1" in aviso and "make mp-sandbox-ensaio" in aviso
        for aviso in avisos
    )


def test_sessao_ensaio_com_o_billing_no_simulador_nao_mexe_em_nada(
    relogio: Relogio,
) -> None:
    cluster = Cluster()
    modo, _ = _modo(cluster, relogio)

    with modo.sessao(real=False):
        pass

    assert cluster.chamadas == []


def test_sessao_ensaio_com_modo_real_que_sobrou_volta_ao_simulador(
    relogio: Relogio,
) -> None:
    cluster = Cluster()
    cluster.modo = MODO_REAL
    modo, avisos = _modo(cluster, relogio)

    with modo.sessao(real=False):
        assert cluster.modo == MODO_SIMULADO
        chamadas_no_inicio = len(cluster.chamadas)

    assert any("estava em modo real" in aviso for aviso in avisos)
    # Nada mais no fim: o ensaio so garantiu o simulador.
    assert len(cluster.chamadas) == chamadas_no_inicio


def test_sessao_real_com_manter_mas_ligar_que_falha_desfaz_assim_mesmo(
    relogio: Relogio,
) -> None:
    cluster = Cluster(falhas=("apply",))
    modo, avisos = _modo(cluster, relogio)

    with (
        pytest.raises(ErroDeComandoError),
        modo.sessao(real=True, token=CHAVE_DO_MP, assinatura=ASSINATURA, manter=True),
    ):
        pytest.fail("o corpo nao devia rodar")  # pragma: no cover

    assert any("delete secret" in c for c in cluster.comandos())
    assert not any("E2E_MP_MANTER" in aviso for aviso in avisos)


def test_desfazer_avisa_quando_o_billing_voltou_ao_simulador(relogio: Relogio) -> None:
    cluster = Cluster()
    cluster.modo = MODO_REAL
    modo, avisos = _modo(cluster, relogio)

    modo.desfazer()

    assert avisos[-1] == "[mp-sandbox] Billing de volta ao simulador"


@pytest.mark.parametrize("erro", [KeyError("modo"), ValueError("sem json")])
def test_saude_ilegivel_no_desfazer_e_falha_do_passo_e_nao_excecao_estranha(
    erro: Exception, relogio: Relogio
) -> None:
    cluster = Cluster()

    def saude() -> str:
        raise erro

    modo = ModoDoBilling(
        cluster.kubectl(),
        saude,
        avisar=lambda _: None,
        relogio=relogio,
        dormir=relogio.dormir,
    )

    with pytest.raises(DesfazerFalhouError, match="reiniciar e esperar o Billing"):
        modo.desfazer()

    assert any("delete secret" in c for c in cluster.comandos())


def test_saude_ilegivel_uma_vez_conta_como_ainda_nao(relogio: Relogio) -> None:
    cluster = Cluster()
    respostas: Iterator[Exception | str] = iter([ValueError("sem json"), MODO_REAL])

    def saude() -> str:
        resposta = next(respostas)
        if isinstance(resposta, Exception):
            raise resposta
        return resposta

    modo = ModoDoBilling(
        cluster.kubectl(),
        saude,
        avisar=lambda _: None,
        relogio=relogio,
        dormir=relogio.dormir,
    )

    modo.ligar_real(CHAVE_DO_MP, ASSINATURA)

    assert relogio.dormidas == [2.0]
