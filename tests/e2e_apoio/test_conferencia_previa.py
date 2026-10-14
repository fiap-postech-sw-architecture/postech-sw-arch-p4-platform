"""A conferencia do sandbox antes do pytest: mensagem limpa, cluster so se preciso."""

from __future__ import annotations

import io
import json
from typing import TYPE_CHECKING, Any

import httpx
import pytest

from e2e.apoio.conferencia_previa import SUBIR_O_CLUSTER, conferir_antes_do_pytest
from e2e.apoio.http import ClienteHttp
from e2e.apoio.kube import ErroDeComandoError, Kubectl
from e2e.apoio.mercadopago import TokenRecusadoError
from e2e_apoio.falsos import ExecutorFalso, Relogio

if TYPE_CHECKING:
    from collections.abc import Sequence

CHAVE_DO_MP = "TEST-1234567890123456-101420-0a1b2c3d4e5f60718293a4b5c6d7e8f9-123456789"
ASSINATURA = "assinatura-do-webhook-0123456789abcdef"
KIND = {
    "ORCAMENTO_VALIDADE_HORAS": "72",
    "PAGAMENTO_VALIDADE_MINUTOS": "60",
    "PAGAMENTO_MAX_RECUSAS": "3",
}
KIND_CI = {**KIND, "ORCAMENTO_VALIDADE_HORAS": "0.02", "PAGAMENTO_MAX_RECUSAS": "1"}
AMBIENTE = {"MP_ACCESS_TOKEN": CHAVE_DO_MP, "MP_WEBHOOK_SECRET": ASSINATURA}
CONTEXTO = "kind-pytstop-p4"
NOS = "node/pytstop-p4-control-plane\n"


class BordaFalsa(ClienteHttp):
    """A borda: os tres servicos saudaveis, o Billing no simulador."""

    def __init__(self, relogio: Relogio) -> None:
        super().__init__(
            "https://localhost",
            transporte=httpx.MockTransport(
                lambda _: httpx.Response(200, json={"status": "ok", "modo": "simulado"})
            ),
            relogio=relogio,
            dormir=relogio.dormir,
        )
        self.fechada = False

    def fechar(self) -> None:
        self.fechada = True
        super().fechar()


class MercadoPagoFalso:
    def __init__(self, erro: Exception | None = None) -> None:
        self.erro = erro
        self.fechado = False
        self.token: str | None = None

    def validar_token(self) -> None:
        if self.erro:
            raise self.erro

    def fechar(self) -> None:
        self.fechado = True


class ExecutorQueFalha:
    """O kubectl que falha em tudo, com o erro dado."""

    def __init__(self, erro: ErroDeComandoError) -> None:
        self.erro = erro
        self.comandos: list[list[str]] = []

    def __call__(self, argumentos: Sequence[str], prazo: float) -> str:
        del prazo
        self.comandos.append(list(argumentos))
        raise self.erro


class Mundo:
    """Cluster, borda, Mercado Pago e Docker falsos de uma conferencia."""

    def __init__(
        self,
        relogio: Relogio,
        *,
        configmap: dict[str, str] | None = None,
        publicacao: str = "127.0.0.1:443\n",
        executor: Any = None,
        mp: MercadoPagoFalso | None = None,
    ) -> None:
        self.executor = executor or ExecutorFalso(
            {
                "get nodes": NOS,
                "get deployment": "billing-service-t5bghkfd67\n",
                "get configmap": json.dumps(configmap or KIND),
            }
        )
        self.docker = ExecutorFalso({"docker port": publicacao})
        self.borda = BordaFalsa(relogio)
        self.mp = mp or MercadoPagoFalso()

    def conferir(
        self,
        argumentos: Sequence[str],
        ambiente: dict[str, str] | None = None,
        contexto: str = CONTEXTO,
    ) -> tuple[int, str]:
        erro = io.StringIO()
        codigo = conferir_antes_do_pytest(
            argumentos,
            AMBIENTE if ambiente is None else ambiente,
            contexto=contexto,
            url_da_borda="https://localhost",
            saida=erro,
            criar_kubectl=lambda ctx: Kubectl(ctx, executor=self.executor),
            criar_borda=lambda _url: self.borda,
            criar_cliente=self._cliente,
            executor_docker=self.docker,
        )
        return codigo, erro.getvalue()

    def _cliente(self, token: str) -> Any:
        self.mp.token = token
        return self.mp


def test_uso_errado_diz_o_uso_e_sai_com_2(relogio: Relogio) -> None:
    mundo = Mundo(relogio)

    for argumentos in ([], ["real", "ensaio"], ["tanto-faz"], ["REAL"]):
        codigo, erro = mundo.conferir(argumentos)

        assert codigo == 2
        assert erro == "uso: python -m e2e.conferir_sandbox <real|ensaio>\n"
    assert mundo.executor.comandos == []


def test_ensaio_confere_o_cluster_e_a_borda_e_diz_que_esta_ok(
    relogio: Relogio, capsys: pytest.CaptureFixture[str]
) -> None:
    mundo = Mundo(relogio)

    codigo, erro = mundo.conferir(["ensaio"], {})

    assert (codigo, erro) == (0, "")
    assert (
        capsys.readouterr().out
        == f"[mp-sandbox] conferência ok (ensaio) em {CONTEXTO}\n"
    )
    assert mundo.docker.comandos == [
        ["docker", "port", "pytstop-p4-control-plane", "30443/tcp"]
    ]
    assert mundo.borda.fechada
    assert mundo.mp.token is None, "o ensaio nao fala com o Mercado Pago"


def test_real_confere_credencial_overlay_servicos_e_token_e_fecha_tudo(
    relogio: Relogio, capsys: pytest.CaptureFixture[str]
) -> None:
    mundo = Mundo(relogio)
    ambiente = dict(AMBIENTE)

    codigo, erro = mundo.conferir(["real"], ambiente)

    assert (codigo, erro) == (0, "")
    saida = capsys.readouterr().out
    assert saida == f"[mp-sandbox] conferência ok (real) em {CONTEXTO}\n"
    assert CHAVE_DO_MP not in saida
    assert mundo.mp.token == CHAVE_DO_MP, "validou o token no Mercado Pago"
    assert mundo.mp.fechado
    assert mundo.borda.fechada
    assert ambiente == AMBIENTE, "as credenciais do chamador seguem onde estavam"


def test_real_sem_credencial_para_antes_de_tocar_no_cluster(relogio: Relogio) -> None:
    mundo = Mundo(relogio)

    codigo, erro = mundo.conferir(["real"], {})

    assert codigo == 2
    assert erro.startswith("[mp-sandbox] não posso seguir: MP_ACCESS_TOKEN não está")
    assert 'MP_WEBHOOK_SECRET="$MP_WEBHOOK_SECRET" make mp-sandbox' in erro
    assert mundo.executor.comandos == []
    assert mundo.docker.comandos == []
    assert mundo.borda.fechada


def test_ensaio_nao_pede_credencial(relogio: Relogio) -> None:
    codigo, _ = Mundo(relogio).conferir(["ensaio"], {})

    assert codigo == 0


@pytest.mark.parametrize("escape", [False, True], ids=["sem-escape", "com-escape"])
def test_contexto_que_nao_e_kind_recusa_antes_do_cluster_mesmo_com_o_escape(
    relogio: Relogio, escape: bool
) -> None:
    mundo = Mundo(relogio)
    ambiente = (
        {**AMBIENTE, "E2E_CONTEXTO_NAO_DESCARTAVEL": "k3s-da-vm"}
        if escape
        else AMBIENTE
    )

    codigo, erro = mundo.conferir(["real"], ambiente, contexto="k3s-da-vm")

    assert codigo == 2
    assert "não é um kind" in erro
    assert "E2E_CONTEXTO_NAO_DESCARTAVEL não vale aqui" in erro
    assert mundo.executor.comandos == []


def test_cluster_fora_do_ar_mostra_o_que_o_kubectl_disse_e_como_subir(
    relogio: Relogio,
) -> None:
    falha = ErroDeComandoError(
        "kubectl --context kind-pytstop-p4 get nodes -o name: saiu com 1: "
        "Unable to connect to the server: dial tcp 127.0.0.1:6443: refused"
    )
    mundo = Mundo(relogio, executor=ExecutorQueFalha(falha))

    codigo, erro = mundo.conferir(["ensaio"], {})

    assert codigo == 2
    assert erro == (
        "[mp-sandbox] não posso seguir: o kubectl não conseguiu ler o cluster "
        "(Unable to connect to the server: dial tcp 127.0.0.1:6443: refused). "
        f"{SUBIR_O_CLUSTER}\n"
    )
    assert "_pytest" not in erro
    assert "deselected" not in erro
    assert mundo.borda.fechada


def test_kubectl_que_estoura_o_prazo_mostra_a_mensagem_inteira(
    relogio: Relogio,
) -> None:
    falha = ErroDeComandoError(
        "kubectl --context kind-pytstop-p4 get nodes: passou de 30 s"
    )
    mundo = Mundo(relogio, executor=ExecutorQueFalha(falha))

    codigo, erro = mundo.conferir(["ensaio"], {})

    assert codigo == 2
    assert "(kubectl --context kind-pytstop-p4 get nodes: passou de 30 s)" in erro


def test_borda_de_outro_cluster_recusa_dizendo_o_que_o_no_publica(
    relogio: Relogio,
) -> None:
    mundo = Mundo(relogio, publicacao="127.0.0.1:8443\n")

    codigo, erro = mundo.conferir(["ensaio"], {})

    assert codigo == 2
    assert "nao publica a borda em 127.0.0.1:443" in erro


def test_overlay_do_kind_ci_recusa_com_a_instrucao_de_refazer_o_cluster(
    relogio: Relogio,
) -> None:
    mundo = Mundo(relogio, configmap=KIND_CI)

    codigo, erro = mundo.conferir(["ensaio"], {})

    assert codigo == 2
    assert "o Billing está com os prazos do E2E (kind-ci)" in erro
    assert "make kind-down" in erro
    assert 'README, "Mercado Pago na sandbox", "Como rodar"' in erro


def test_token_recusado_pelo_mercado_pago_diz_isso_sem_repetir_o_valor(
    relogio: Relogio,
) -> None:
    recusa = TokenRecusadoError("GET /v1/payments/search: HTTP 401", status=401)
    mundo = Mundo(relogio, mp=MercadoPagoFalso(erro=recusa))

    codigo, erro = mundo.conferir(["real"])

    assert codigo == 2
    assert "o Mercado Pago não aceita o MP_ACCESS_TOKEN (HTTP 401)" in erro
    assert CHAVE_DO_MP not in erro
    assert ASSINATURA not in erro
    assert mundo.mp.fechado
