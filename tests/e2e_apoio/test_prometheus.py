"""A espera de uma raspagem do Prometheus antes de derrubar um pod.

O contador de um pod mora na memoria dele e so chega ao Prometheus na raspagem (15 s).
O cenario do consumidor do Billing parado derrubava o pod 8 a 9 s depois do estorno do
cenario anterior, e o estorno ficava de fora do painel Pagamentos (6 do Billing contra 8
do OS). Aqui o Prometheus e um falso que raspa a cada 15 s no relogio do teste, e a
espera tem de durar o que falta para a raspagem seguinte, nem mais nem menos.
"""

from __future__ import annotations

import re

import pytest

from e2e.apoio.espera import TempoEsgotadoError
from e2e.apoio.kube import ErroDeComandoError, Kubectl
from e2e.apoio.prometheus import (
    agora,
    consultar,
    esperar_raspagem,
    expressao_da_raspagem,
    ultima_raspagem,
)
from e2e_apoio.falsos import (
    DESLOCAMENTO_DO_PROMETHEUS,
    ExecutorFalso,
    PrometheusRaspando,
    Relogio,
)

NAMESPACE = "pytstop-billing"
JOB = "billing-service-consumidor"
PROXY = "/api/v1/namespaces/pytstop-plataforma/services/prometheus:9090/proxy"
INICIO = 100.0


def esperar(
    prometheus: PrometheusRaspando | ExecutorFalso,
    relogio: Relogio,
    prazo: float = 60.0,
) -> None:
    esperar_raspagem(
        Kubectl("c", executor=prometheus),
        NAMESPACE,
        JOB,
        prazo=prazo,
        relogio=relogio,
        dormir=relogio.dormir,
    )


def test_espera_so_a_raspagem_que_falta_quando_a_ultima_foi_antes_do_inicio(
    relogio: Relogio,
) -> None:
    # A ultima raspagem foi ha 8 s (o estorno do cenario anterior, antes do pod cair):
    # a seguinte vem 7 s depois, e a espera nao dorme um segundo a mais nem a menos.
    esperar(PrometheusRaspando(relogio, ha=8), relogio)

    assert relogio.agora == INICIO + 7


def test_a_raspagem_exatamente_no_inicio_da_espera_nao_conta(relogio: Relogio) -> None:
    # Uma raspagem que comecou no instante da referencia pode ter lido o /metrics antes
    # do estorno: vale so a que comecou depois.
    esperar(PrometheusRaspando(relogio, ha=0), relogio)

    assert relogio.agora == INICIO + 15


def test_raspagem_que_falhou_nao_conta_e_a_espera_segue_ate_a_proxima(
    relogio: Relogio,
) -> None:
    # A raspagem de 7 s falhou (up 0): o pod nao foi lido. Vale a de 22 s.
    esperar(PrometheusRaspando(relogio, ha=8, falhas={1}), relogio)

    assert relogio.agora == INICIO + 22


def test_o_prometheus_que_deixa_de_raspar_reprova_pelo_prazo_e_diz_o_que_viu(
    relogio: Relogio,
) -> None:
    prometheus = PrometheusRaspando(relogio, ha=8, parar_em=INICIO)

    with pytest.raises(TempoEsgotadoError) as erro:
        esperar(prometheus, relogio, prazo=60)

    assert str(erro.value) == (
        f"raspagem de {JOB} ({NAMESPACE}) pelo Prometheus depois do inicio da espera: "
        "nao ocorreu em 60 s; a ultima raspagem foi 8 s antes do inicio"
    )
    assert relogio.agora == INICIO + 60


def test_alvo_sem_a_serie_up_reprova_dizendo_que_nao_esta_sendo_raspado(
    relogio: Relogio,
) -> None:
    with pytest.raises(TempoEsgotadoError, match="nao esta sendo raspado"):
        esperar(PrometheusRaspando(relogio, sem_serie=True), relogio, prazo=5)


def test_raspagem_que_falha_ate_o_fim_do_prazo_reprova_dizendo_up_0(
    relogio: Relogio,
) -> None:
    prometheus = PrometheusRaspando(relogio, falhas=range(1, 10))

    with pytest.raises(TempoEsgotadoError, match=r"falhou \(up 0\)"):
        esperar(prometheus, relogio, prazo=60)


def test_proxy_do_apiserver_que_recusa_um_instante_nao_derruba_a_espera(
    relogio: Relogio,
) -> None:
    # As tres primeiras consultas falham; a quarta ja acha o Prometheus e a espera
    # termina na mesma raspagem de 7 s.
    prometheus = PrometheusRaspando(relogio, ha=8, erros=3)

    esperar(prometheus, relogio)

    assert relogio.agora == INICIO + 7


def test_erro_que_nao_passa_aparece_na_mensagem_do_prazo(relogio: Relogio) -> None:
    prometheus = PrometheusRaspando(relogio, erros=1_000)

    with pytest.raises(
        TempoEsgotadoError, match=r"ErroDeComandoError: .*nao alcancou o Prometheus"
    ):
        esperar(prometheus, relogio, prazo=5)


def test_resposta_que_nao_e_json_tambem_conta_como_ainda_nao(relogio: Relogio) -> None:
    with pytest.raises(TempoEsgotadoError, match="JSONDecodeError"):
        esperar(ExecutorFalso({"get --raw": "<html>"}), relogio, prazo=3)


def test_pergunta_o_time_do_prometheus_e_depois_o_up_do_job_no_namespace(
    relogio: Relogio,
) -> None:
    prometheus = PrometheusRaspando(relogio, ha=8)

    esperar(prometheus, relogio)

    assert prometheus.consultas[0] == "time()"
    assert set(prometheus.consultas[1:]) == {expressao_da_raspagem(NAMESPACE, JOB)}
    assert prometheus.caminhos[0] == f"{PROXY}/api/v1/query?query=time%28%29"
    seletor = 'up{job="billing-service-consumidor", namespace="pytstop-billing"}'
    assert expressao_da_raspagem(NAMESPACE, JOB) == (
        f"min(timestamp({seletor}) * {seletor})"
    )


def test_o_timestamp_recebe_o_seletor_sozinho() -> None:
    # De uma expressao (timestamp(up == 1)) o timestamp() devolve o instante da propria
    # consulta, e a espera passaria na hora: so o seletor direto devolve o da raspagem.
    # O promtool prova isso em tests/alertas.promtool.yml.
    expressao = expressao_da_raspagem(NAMESPACE, JOB)

    assert re.search(r"timestamp\(up\{[^{}()]*\}\)", expressao)
    assert len(re.findall(r"timestamp\(", expressao)) == 1


def test_o_relogio_do_prometheus_e_o_da_resposta_dele(relogio: Relogio) -> None:
    prometheus = PrometheusRaspando(relogio)

    assert agora(Kubectl("c", executor=prometheus)) == (
        INICIO + DESLOCAMENTO_DO_PROMETHEUS
    )


def test_sem_serie_o_instante_e_none_e_com_serie_e_o_da_raspagem(
    relogio: Relogio,
) -> None:
    sem_serie = Kubectl("c", executor=PrometheusRaspando(relogio, sem_serie=True))
    com_serie = Kubectl("c", executor=PrometheusRaspando(relogio, ha=8))

    assert ultima_raspagem(sem_serie, NAMESPACE, JOB) is None
    assert ultima_raspagem(com_serie, NAMESPACE, JOB) == (
        INICIO + DESLOCAMENTO_DO_PROMETHEUS - 8
    )


def test_consulta_com_status_de_erro_levanta_com_a_resposta_do_prometheus() -> None:
    erro = '{"status": "error", "errorType": "bad_data", "error": "parse error"}'

    with pytest.raises(ErroDeComandoError, match="bad_data"):
        consultar(Kubectl("c", executor=ExecutorFalso({"get --raw": erro})), "up{")
