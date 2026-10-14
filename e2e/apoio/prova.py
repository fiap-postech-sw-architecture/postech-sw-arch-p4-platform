"""O cenario do sandbox: o que cada passo do Gherkin faz, sem depender do pytest-bdd.

``Prova`` junta as chamadas aos servicos (``Api``), as conferencias no Mercado
Pago e o registro da evidencia. Os passos de ``e2e/test_mp_sandbox.py`` so ligam o
texto do Gherkin a um metodo daqui, e por isso a logica dos dois modos (real e
ensaio) e testada sem cluster. O que depende do E2E da saga (esperar o status da
OS, descrever o estado) chega pelo construtor.
"""

from __future__ import annotations

import itertools
import time
from datetime import UTC, datetime
from functools import partial
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import parse_qs, urlsplit

import httpx

from e2e.apoio import diagnostico
from e2e.apoio.conferencias import (
    conferir_aprovado,
    conferir_estornado,
    conferir_preferencia_expirada,
)
from e2e.apoio.espera import TempoEsgotadoError, esperar
from e2e.apoio.evidencia import pagamento_do_billing, saga_resumida, transicoes_da_os
from e2e.apoio.humano import (
    INTERVALO_DO_PAGAMENTO,
    INTERVALO_NO_ENSAIO,
    PRAZO_DO_PAGAMENTO,
    PRAZO_NO_ENSAIO,
    esperar_pagamento,
    instrucoes_de_pagamento,
)
from e2e.apoio.mercadopago import ErroDoMercadoPagoError
from e2e.apoio.modo_billing import NAMESPACE_BILLING
from e2e.apoio.segredos import mascarar, registrar

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping

    from e2e.apoio.evidencia import RegistroDoCenario
    from e2e.apoio.kube import Kubectl
    from e2e.apoio.preflight_mp import Sandbox
    from e2e.servicos import Api, Cenario, Json

# Dois cenarios pedem pagamento de uma pessoa (o 3o fecha a cobranca sem pagar).
PAGAMENTOS_A_FAZER: Final = 2
# O Mercado Pago responde a criacao da preferencia em segundos, e o comando volta
# pela fila de retry se ele estiver lento.
PRAZO_DA_COBRANCA: Final = 120.0
PRAZO_DA_COBRANCA_NO_ENSAIO: Final = 30.0
# O estorno aparece na consulta ao Mercado Pago em segundos.
PRAZO_DO_ESTORNO: Final = 60.0
PRINTS: Final = (
    (
        "O checkout do Mercado Pago aberto na janela anônima, com o valor da cobrança "
        "(antes de pagar)."
    ),
    "A tela de pagamento aprovado do Mercado Pago (cenários 1 e 2).",
    "O terminal com o pagamento CONFIRMADO e a OS em `aguardando_execucao`.",
    (
        "No painel do Mercado Pago, na conta do Vendedor de teste: o pagamento "
        "aprovado e, depois do cancelamento, o estorno."
    ),
    "O `resumo.md` desta pasta (já sem token nem dado do pagador).",
)
PRINTS_DO_ENSAIO: Final = (
    "Nenhum: o ensaio não fala com o Mercado Pago. Os prints são do `make mp-sandbox`.",
)
SEM_CONSULTA: Final = "[ensaio] sem consulta ao Mercado Pago neste passo"


def _referencia(pagamento: Json, campo: str, rotulo: str) -> str:
    """O id que o Billing guardou do Mercado Pago, ou a falha que diz que faltou.

    Sem ele a consulta iria a ``/v1/payments/None`` e o 404 esconderia a causa.
    """
    valor = pagamento.get(campo)
    if not valor:
        msg = (
            f"o Billing não guardou {rotulo} deste pagamento ({campo} vazio): "
            "sem ela não há o que conferir no Mercado Pago"
        )
        raise AssertionError(msg)
    return str(valor)


class Prova:
    """Um cenario do sandbox: o registro da evidencia e as chamadas dos passos."""

    def __init__(  # cada parametro e um ponto de injecao dos testes
        self,
        *,
        api: Api,
        kubectl: Kubectl,
        sandbox: Sandbox,
        cenario: Cenario,
        registro: RegistroDoCenario,
        esperar_status: Callable[[Api, Cenario, str], Json],
        descrever_estado: Callable[[Api, Cenario], str],
        filas_mortas_antes: Mapping[str, int] | None = None,
        avisar: Callable[[str], None] = print,
        numeros: Iterator[int] | None = None,
        relogio: Callable[[], float] = time.monotonic,
        dormir: Callable[[float], None] = time.sleep,
        agora: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.api = api
        self.kubectl = kubectl
        self.sandbox = sandbox
        self.cenario = cenario
        self.registro = registro
        self.falhou = ""
        self._esperar_status = esperar_status
        self._descrever_estado = descrever_estado
        self._mortas_antes = filas_mortas_antes
        self._avisar = avisar
        self._numeros = numeros if numeros is not None else itertools.count(1)
        self._relogio = relogio
        self._dormir = dormir
        self._agora = agora

    @property
    def real(self) -> bool:
        return self.sandbox.real

    def cobranca_aberta(self) -> Json:
        """A OS espera o pagamento e o Billing criou a cobranca (``SOLICITADO``)."""
        self._esperar_status(self.api, self.cenario, "aguardando_pagamento")
        resumo = esperar(
            lambda: self.api.os.ordem(self.cenario.ordem_id)["pagamento"] or None,
            prazo=PRAZO_DA_COBRANCA if self.real else PRAZO_DA_COBRANCA_NO_ENSAIO,
            intervalo=1.0,
            descricao=f"cobrança aberta da {self.cenario.resumo}",
            ignorar=(httpx.TransportError,),
            relogio=self._relogio,
            dormir=self._dormir,
        )
        pagamento: Json = self.api.billing.pagamento(resumo["pagamento_id"])
        self.cenario.pagamento_id = pagamento["id"]
        self.registro.ordem_id = self.cenario.ordem_id
        self.registro.pagamento_id = pagamento["id"]
        esperado = "mercadopago" if self.real else "simulado"
        if pagamento["provedor"] != esperado:
            msg = (
                f"o Billing criou a cobrança no provedor {pagamento['provedor']!r}, e "
                f"o esperado era {esperado!r}"
            )
            raise AssertionError(msg)
        self.registro.anotar("cobrança criada no provedor; link do checkout pronto")
        return pagamento

    def pagar(self, pagamento: Json) -> None:
        """Real: imprime o link e as instrucoes. Ensaio: o simulador aprova."""
        if self.real:
            self._avisar(
                instrucoes_de_pagamento(
                    link=pagamento["checkout_url"],
                    valor=pagamento["valor"],
                    moeda=pagamento["moeda"],
                    numero=next(self._numeros),
                    total=PAGAMENTOS_A_FAZER,
                )
            )
            self.registro.anotar("link impresso; esperando o comprador de teste")
            return
        token = parse_qs(urlsplit(pagamento["checkout_url"]).query)["token"][0]
        registrar(token)
        self._avisar(
            "[ensaio] o simulador do Billing aprova o pagamento no lugar do comprador"
        )
        self.api.billing.simular_pagamento(pagamento["id"], token, "aprovar")
        self.registro.anotar("simulador aprovou o pagamento")

    def esperar_confirmacao(self) -> Json:
        """Espera o Billing confirmar; no modo real, com contagem regressiva."""
        pagamento = esperar_pagamento(
            lambda: self.api.billing.pagamento(self.cenario.pagamento_id),
            prazo=PRAZO_DO_PAGAMENTO if self.real else PRAZO_NO_ENSAIO,
            intervalo=INTERVALO_DO_PAGAMENTO if self.real else INTERVALO_NO_ENSAIO,
            max_recusas=self.sandbox.max_recusas,
            avisar=self._avisar,
            relogio=self._relogio,
            dormir=self._dormir,
        )
        self.registro.anotar("Billing mostra o pagamento CONFIRMADO")
        if self.real:
            self.registro.pagamento_mp_id = str(
                pagamento.get("referencia_pagamento") or ""
            )
        return dict(pagamento)

    def conferir_aprovado(self, pagamento: Json) -> None:
        """Real: aprovado no Mercado Pago, no valor, de teste e desta cobranca."""
        if not self.real:
            self._avisar(SEM_CONSULTA)
            return
        assert self.sandbox.mercadopago is not None
        mp = self.sandbox.mercadopago.pagamento(
            _referencia(pagamento, "referencia_pagamento", "o id do pagamento")
        )
        # Guarda antes de conferir: o que o Mercado Pago disse fica na evidencia mesmo
        # quando a conferencia reprova.
        self.registro.mercadopago = mp.para_evidencia()
        self.registro.pagamento_mp_id = mp.id
        conferir_aprovado(
            mp,
            pagamento_id=pagamento["id"],
            valor=pagamento["valor"],
            moeda=pagamento["moeda"],
        )
        self.registro.anotar(f"Mercado Pago: {mp.status}, live_mode={mp.live_mode}")

    def conferir_estornado(self, pagamento: Json) -> None:
        """Real: o estorno aparece no Mercado Pago em ate ``PRAZO_DO_ESTORNO``."""
        if not self.real:
            self._avisar(SEM_CONSULTA)
            return
        assert self.sandbox.mercadopago is not None
        mercadopago = self.sandbox.mercadopago
        referencia = _referencia(pagamento, "referencia_pagamento", "o id do pagamento")

        def estornado() -> bool:
            mp = mercadopago.pagamento(referencia)
            self.registro.mercadopago = mp.para_evidencia()
            return mp.estornado

        try:
            esperar(
                estornado,
                prazo=PRAZO_DO_ESTORNO,
                intervalo=3.0,
                descricao="estorno visível no Mercado Pago",
                # O cliente troca o erro de rede por este; o que persistir volta
                # na leitura final, com a causa.
                ignorar=(ErroDoMercadoPagoError,),
                relogio=self._relogio,
                dormir=self._dormir,
            )
        except TempoEsgotadoError:
            # A divergencia diz o que o Mercado Pago mostra, no lugar do "nao ocorreu".
            conferir_estornado(mercadopago.pagamento(referencia))
            raise
        self.registro.anotar("Mercado Pago mostra o pagamento estornado")

    def conferir_preferencia_expirada(self) -> None:
        """Real: a preferencia do checkout expirou (o ``PUT`` do Billing valeu)."""
        if not self.real:
            self._avisar(SEM_CONSULTA)
            return
        assert self.sandbox.mercadopago is not None
        pagamento = self.api.billing.pagamento(self.cenario.pagamento_id)
        preferencia = self.sandbox.mercadopago.preferencia(
            _referencia(
                pagamento, "referencia_preferencia", "a preferência do checkout"
            )
        )
        self.registro.preferencia = preferencia.para_evidencia()
        nao_provada = conferir_preferencia_expirada(preferencia, agora=self._agora())
        if nao_provada:
            self.registro.observacoes.append(nao_provada)
            self._avisar(f"[mp-sandbox] atenção: {nao_provada}")
        else:
            self.registro.anotar("Mercado Pago mostra a preferência expirada")

    def falha_no_passo(self, passo: str, erro: Exception) -> None:
        """Marca a falha e imprime o diagnostico (estado, logs e dica provavel)."""
        self.falhou = passo
        self._avisar(self.diagnostico(passo, erro))

    def diagnostico(self, passo: str, erro: Exception) -> str:
        sinais = diagnostico.Sinais(
            cenario=self.registro.nome,
            passo=passo,
            erro=mascarar(f"{type(erro).__name__}: {erro}")[:600],
            esperado=passo,
            real=self.real,
        )
        sinais.estado_da_os = diagnostico.coletar(
            lambda: self._descrever_estado(self.api, self.cenario)
        )
        if self.cenario.pagamento_id:
            sinais.pagamento = diagnostico.coletar(
                lambda: self.api.billing.pagamento(self.cenario.pagamento_id)
            )
            mercadopago = self.sandbox.mercadopago
            if self.real and mercadopago is not None:
                sinais.mercadopago = diagnostico.coletar(
                    lambda: mercadopago.buscar_por_referencia(self.cenario.pagamento_id)
                )
        sinais.filas_mortas = diagnostico.coletar(self.kubectl.filas_mortas)
        sinais.filas_mortas_antes = self._mortas_antes
        for nome, app, container in diagnostico.PROCESSOS_DO_BILLING:
            saida = diagnostico.coletar(
                partial(
                    self.kubectl.ultimas_linhas,
                    NAMESPACE_BILLING,
                    app,
                    container=container,
                )
            )
            sinais.logs[nome] = diagnostico.filtrar_log(saida or "")
        return diagnostico.montar(sinais)

    def concluir(self, desfecho: str | None) -> None:
        """No fim do cenario: duracao, resultado e o que os servicos registraram.

        ``desfecho`` e o que o pytest registrou para a chamada (``passed`` ou
        ``failed``); ``None`` e o cenario que parou antes do fim (Ctrl-C).
        """
        self.registro.duracao = self._relogio() - self.cenario.inicio
        if self.falhou or desfecho == "failed":
            self.registro.resultado = "falhou"
        elif desfecho == "passed":
            self.registro.resultado = "passou"
        else:
            self.registro.resultado = "interrompido"
            self.registro.observacoes.append(
                "a execução parou antes do fim deste cenário"
            )
        self.registro.ordem_id = self.cenario.ordem_id
        if self.falhou:
            self.registro.observacoes.append(f"falhou no passo: {self.falhou}")
        if not self.cenario.ordem_id:
            return
        pagamento: dict[str, Any] = {}
        if self.cenario.pagamento_id:
            pagamento = (
                diagnostico.coletar(
                    lambda: self.api.billing.pagamento(self.cenario.pagamento_id)
                )
                or {}
            )
        saga = (
            diagnostico.coletar(lambda: self.api.os.saga(self.cenario.ordem_id)) or {}
        )
        historico = (
            diagnostico.coletar(lambda: self.api.os.historico(self.cenario.ordem_id))
            or {}
        )
        self.registro.billing = pagamento_do_billing(pagamento)
        self.registro.saga = saga_resumida(saga)
        self.registro.transicoes += transicoes_da_os(historico, saga, pagamento)
