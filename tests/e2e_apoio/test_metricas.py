"""Leitura de uma serie no formato texto do Prometheus."""

from __future__ import annotations

from e2e.apoio.metricas import valor_da_serie

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
