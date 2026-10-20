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
from typing import TYPE_CHECKING, Final
from urllib.parse import parse_qs, urlsplit

import httpx

from e2e.apoio import diagnostico
from e2e.apoio.conferencias import (
    DivergenciaComOMercadoPagoError,
    conferir_aprovado,
    conferir_estornado,
    conferir_preferencia_expirada,
)
from e2e.apoio.espera import TempoEsgotadoError, esperar
from e2e.apoio.evidencia import (
    RegistroDoCenario,
    descricao_do_trace,
    gravar_evidencia,
    pagamento_do_billing,
    saga_resumida,
    transicoes_da_os,
)
from e2e.apoio.humano import (
    INTERVALO_DO_PAGAMENTO,
    INTERVALO_NO_ENSAIO,
    PRAZO_DO_PAGAMENTO,
    PRAZO_NO_ENSAIO,
    esperar_pagamento,
    instrucoes_de_pagamento,
)
from e2e.apoio.kube import FILA_MORTA_DO_BILLING
from e2e.apoio.mercadopago import ErroDoMercadoPagoError, registrar_conta
from e2e.apoio.modo_billing import NAMESPACE_BILLING, sem_consulta
from e2e.apoio.segredos import mascarar, registrar
from e2e.apoio.trace_higienizado import (
    INTERROMPIDO,
    PRAZO_DO_TRACE,
    TraceDoCenario,
    esperar_trace,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping
    from pathlib import Path

    from e2e.apoio.jaeger import Trace
    from e2e.apoio.kube import Kubectl
    from e2e.apoio.preflight_mp import Sandbox
    from e2e.servicos import Api, Cenario, Json

# Dois cenarios pedem pagamento de uma pessoa (o 3o fecha a cobranca sem pagar).
PAGAMENTOS_A_FAZER: Final = 2
# O Mercado Pago responde a criacao da preferencia em segundos, e o comando volta
# pela fila de retry se ele estiver lento.
PRAZO_DA_COBRANCA: Final = 120.0
PRAZO_DA_COBRANCA_NO_ENSAIO: Final = 30.0
INTERVALO_DA_COBRANCA: Final = 1.0
# O estorno aparece na consulta ao Mercado Pago em segundos.
PRAZO_DO_ESTORNO: Final = 60.0
INTERVALO_DO_ESTORNO: Final = 3.0
# De quanto em quanto tempo as esperas olham a DLQ do Billing: um comando que foi
# para la nao se resolve esperando mais.
INTERVALO_DA_DLQ: Final = 10.0
# A tag que cada cenario do feature tem de seu; entra no nome do arquivo do trace.
TAGS_DOS_CENARIOS: Final = ("pagamento", "estorno", "cobranca-aberta")
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
    (
        'O trace de um cenário aberto no Jaeger (Search, aba "Upload", arraste o '
        "`trace-*.json`), com o span CLIENT do Billing para `api.mercadopago.com`."
    ),
    "O `resumo.md` desta pasta (já sem token nem dado do pagador).",
    (
        "Cuidado com os prints: cubra e-mail, nome, User ID e CPF das contas de "
        "teste, e nunca mostre a tela de Credenciais nem a de Webhooks."
    ),
    (
        "Cuidado com os arquivos: anexe só o `resumo.md`, os `trace-*.json` e os "
        "prints, nunca o `junit.xml` (leva o nome da máquina), o `cucumber.json`, o "
        "`cenarios.json` nem a pasta inteira; antes de commitar, rode "
        "`python -m e2e.varredura <pasta>` e `gitleaks dir <pasta>`."
    ),
)
PRINTS_DO_ENSAIO: Final = (
    "Nenhum: o ensaio não fala com o Mercado Pago. Os prints são do `make mp-sandbox`.",
)
SEM_CONSULTA: Final = "[ensaio] sem consulta ao Mercado Pago neste passo"


class DlqDoBillingCresceuError(AssertionError):
    """Um comando do Billing foi recusado de vez no cenario; esperar nao ajuda."""


def _link_do_checkout(pagamento: Json) -> str:
    """O ``checkout_url`` do Billing: um link https, que a pessoa vai abrir."""
    link = pagamento.get("checkout_url")
    partes = urlsplit(link) if isinstance(link, str) else None
    if partes is None or partes.scheme != "https" or not partes.netloc:
        msg = (
            "o Billing não devolveu o link do checkout (checkout_url vazio ou fora "
            "de https): sem ele não há como pagar"
        )
        raise AssertionError(msg)
    return str(link)


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


def gravar_evidencia_da_sessao(
    pasta: Path,
    registros: list[RegistroDoCenario],
    sandbox: Sandbox,
    *,
    contexto: str,
    avisar: Callable[[str], None] = print,
) -> None:
    """No fim da sessao: ``resumo.md``, ``evidencia.json`` e ``trace-*.json`` com os
    prints do modo.

    Sem cenario nenhum (a sessao parou antes do primeiro), nao grava nada.
    """
    __tracebackhide__ = True  # os registros levam as observacoes, que a varredura le
    if not registros:
        return
    gravar_evidencia(
        pasta,
        registros,
        modo=sandbox.modo,
        contexto=contexto,
        prints=PRINTS if sandbox.real else PRINTS_DO_ENSAIO,
        url_de_notificacao=sem_consulta(sandbox.url_de_notificacao)
        if sandbox.url_de_notificacao
        else "",
    )
    avisar(f"[mp-sandbox] evidência em {pasta}/resumo.md")


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
        traces_da_ordem: Callable[[str], list[Trace]],
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
        self._traces_da_ordem = traces_da_ordem
        self._mortas_antes = filas_mortas_antes
        self._leitura_da_dlq = float("-inf")
        self._avisar = avisar
        self._numeros = numeros if numeros is not None else itertools.count(1)
        self._relogio = relogio
        self._dormir = dormir
        self._agora = agora

    @classmethod
    def abrir(  # cada parametro e um ponto de injecao dos testes
        cls,
        *,
        nome: str,
        evidencia: list[RegistroDoCenario],
        api: Api,
        kubectl: Kubectl,
        sandbox: Sandbox,
        cenario: Cenario,
        esperar_status: Callable[[Api, Cenario, str], Json],
        descrever_estado: Callable[[Api, Cenario], str],
        traces_da_ordem: Callable[[str], list[Trace]],
        avisar: Callable[[str], None] = print,
        numeros: Iterator[int] | None = None,
    ) -> Prova:
        """Um cenario novo: o registro entra na evidencia da sessao.

        As DLQs de agora ficam como foto de comparacao: so o que entra nelas depois
        e causa deste cenario.
        """
        registro = RegistroDoCenario(nome=nome)
        evidencia.append(registro)
        return cls(
            api=api,
            kubectl=kubectl,
            sandbox=sandbox,
            cenario=cenario,
            registro=registro,
            esperar_status=esperar_status,
            descrever_estado=descrever_estado,
            traces_da_ordem=traces_da_ordem,
            filas_mortas_antes=diagnostico.coletar(kubectl.filas_mortas),
            avisar=avisar,
            numeros=numeros,
        )

    @property
    def real(self) -> bool:
        return self.sandbox.real

    def cobranca_aberta(self) -> Json:
        """A OS espera o pagamento e o Billing criou a cobranca (``SOLICITADO``)."""
        self._esperar_status(self.api, self.cenario, "aguardando_pagamento")
        resumo = esperar(
            self._resumo_do_pagamento,
            prazo=PRAZO_DA_COBRANCA if self.real else PRAZO_DA_COBRANCA_NO_ENSAIO,
            intervalo=INTERVALO_DA_COBRANCA,
            descricao=f"cobrança aberta da {self.cenario.resumo}",
            ignorar=(httpx.TransportError,),
            relogio=self._relogio,
            dormir=self._dormir,
        )
        pagamento = self._pagamento_do_billing(resumo["pagamento_id"])
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

    def _resumo_do_pagamento(self) -> Json | None:
        """O resumo do pagamento na OS; sem ele, falha na hora se a DLQ cresceu."""
        resumo: Json | None = self.api.os.ordem(self.cenario.ordem_id)["pagamento"]
        if not resumo:
            self._conferir_dlq()
        return resumo or None

    def _conferir_dlq(self) -> None:
        """Falha na hora se um comando do Billing foi para a DLQ no cenario.

        Olha a fila de ``INTERVALO_DA_DLQ`` em ``INTERVALO_DA_DLQ`` segundos, contra a
        foto do inicio do cenario. Leitura que falha nao reprova: o diagnostico a
        repete.
        """
        if self._mortas_antes is None:
            return
        agora = self._relogio()
        if agora - self._leitura_da_dlq < INTERVALO_DA_DLQ:
            return
        self._leitura_da_dlq = agora
        atuais = diagnostico.coletar(self.kubectl.filas_mortas)
        if atuais is None:
            return
        novas = atuais.get(FILA_MORTA_DO_BILLING, 0) - self._mortas_antes.get(
            FILA_MORTA_DO_BILLING, 0
        )
        if novas > 0:
            msg = (
                f"{novas} comando(s) do Billing foram para a {FILA_MORTA_DO_BILLING} "
                "depois do início do cenário: o Billing recusou de vez um comando "
                "da saga, e esperar mais não resolve"
            )
            raise DlqDoBillingCresceuError(msg)

    def _pagamento_do_billing(self, pagamento_id: str) -> Json:
        """O pagamento do Billing; o User ID da vendedora, que vem no id da preferencia
        (e no link), passa para a mascara antes de qualquer frame o mostrar."""
        pagamento: Json = self.api.billing.pagamento(pagamento_id)
        registrar_conta(str(pagamento.get("referencia_preferencia") or ""))
        return pagamento

    def _pagamento_ou_dlq(self) -> Json:
        pagamento = self._pagamento_do_billing(self.cenario.pagamento_id)
        if pagamento["status"] != "CONFIRMADO":
            self._conferir_dlq()
        return pagamento

    def pagar(self, pagamento: Json) -> None:
        """Real: imprime o link e as instrucoes. Ensaio: o simulador aprova."""
        link = _link_do_checkout(pagamento)
        if self.real:
            self._avisar(
                instrucoes_de_pagamento(
                    link=link,
                    valor=pagamento["valor"],
                    moeda=pagamento["moeda"],
                    numero=next(self._numeros),
                    total=PAGAMENTOS_A_FAZER,
                )
            )
            self.registro.anotar("link impresso; esperando o comprador de teste")
            return
        token = parse_qs(urlsplit(link).query)["token"][0]
        registrar(token)
        self._avisar(
            "[ensaio] o simulador do Billing aprova o pagamento no lugar do comprador"
        )
        self.api.billing.simular_pagamento(pagamento["id"], token, "aprovar")
        self.registro.anotar("simulador aprovou o pagamento")

    def esperar_confirmacao(self) -> Json:
        """Espera o Billing confirmar; no modo real, com contagem regressiva."""
        pagamento = esperar_pagamento(
            self._pagamento_ou_dlq,
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
        nao_provada = conferir_aprovado(
            mp,
            pagamento_id=pagamento["id"],
            valor=pagamento["valor"],
            moeda=pagamento["moeda"],
        )
        if nao_provada:
            self.registro.observacoes.append(nao_provada)
            self._avisar(f"[mp-sandbox] atenção: {nao_provada}")
        live = "ausente" if mp.live_mode is None else mp.live_mode
        self.registro.anotar(f"Mercado Pago: {mp.status}, live_mode={live}")

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
                intervalo=INTERVALO_DO_ESTORNO,
                descricao="estorno visível no Mercado Pago",
                # O cliente troca o erro de rede por este; o que persistir volta
                # na leitura final, com a causa.
                ignorar=(ErroDoMercadoPagoError,),
                relogio=self._relogio,
                dormir=self._dormir,
            )
        except TempoEsgotadoError:
            # A leitura final: se ainda nao estornou, a divergencia diz o que o Mercado
            # Pago mostra (no lugar do "nao ocorreu"); se o estorno apareceu no ultimo
            # instante, o cenario passa.
            final = mercadopago.pagamento(referencia)
            self.registro.mercadopago = final.para_evidencia()
            conferir_estornado(final)
            self.registro.anotar(
                "Mercado Pago mostra o pagamento estornado (na leitura final)"
            )
            return
        self.registro.anotar("Mercado Pago mostra o pagamento estornado")

    def conferir_preferencia_expirada(self) -> None:
        """Real: a preferencia do checkout expirou (o ``PUT`` do Billing valeu)."""
        if not self.real:
            self._avisar(SEM_CONSULTA)
            return
        assert self.sandbox.mercadopago is not None
        pagamento = self.api.billing.pagamento(self.cenario.pagamento_id)
        # ``preferencia`` poe o User ID da vendedora na mascara antes de qualquer falha.
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
        """O texto do diagnostico do ``passo`` que falhou com ``erro``, ja mascarado.

        Junta o estado da OS e da saga, o pagamento no Billing e no Mercado Pago, as
        DLQs, o log filtrado das tres pecas do Billing e a causa provavel.
        """
        sinais = diagnostico.Sinais(
            cenario=self.registro.nome,
            passo=passo,
            erro=mascarar(f"{type(erro).__name__}: {erro}")[:600],
            esperado=passo,
            real=self.real,
            contexto=self.kubectl.contexto,
            url_de_notificacao=self.sandbox.url_de_notificacao,
            divergencia=isinstance(erro, DivergenciaComOMercadoPagoError),
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
        pagamento: Json = {}
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
        # Interrompido (Ctrl-C): nada mais o interrompe e o desfazer do modo real
        # espera, entao fica sem trace e sem religar o port-forward que o Ctrl-C matou.
        if self.registro.resultado != "interrompido":
            self._avisar(
                f"[mp-sandbox] lendo o trace da OS no Jaeger (até {PRAZO_DO_TRACE:g} s)"
            )
            chave = next(
                (tag for tag in TAGS_DOS_CENARIOS if tag in self.cenario.tags),
                f"cenario-{self.cenario.numero}",
            )
            try:
                achado = esperar_trace(
                    lambda: self._traces_da_ordem(self.cenario.ordem_id),
                    chave=chave,
                    real=self.real,
                    relogio=self._relogio,
                    dormir=self._dormir,
                )
            except KeyboardInterrupt:
                # O Ctrl-C na espera: o resumo diz que o trace nao foi procurado ate o
                # fim, e nada mais espera aqui, para o desfazer do modo real vir ja.
                self.registro.trace = TraceDoCenario(chave, None, INTERROMPIDO)
                raise
            self.registro.trace = achado
            self._avisar(f"[mp-sandbox] {descricao_do_trace(achado, real=self.real)}")
