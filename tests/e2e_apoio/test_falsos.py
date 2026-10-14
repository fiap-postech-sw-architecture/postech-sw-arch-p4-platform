"""Os proprios falsos: o relogio que corta o laco e o teste de processo vivo."""

from __future__ import annotations

import os

import pytest

from e2e_apoio.falsos import Relogio, processo_vivo


def test_relogio_avanca_o_tempo_ao_dormir() -> None:
    relogio = Relogio()

    relogio.dormir(2.5)

    assert relogio() == 102.5
    assert relogio.dormidas == [2.5]


def test_relogio_corta_o_laco_que_dorme_mais_vezes_que_o_limite() -> None:
    relogio = Relogio(limite=2)
    relogio.dormir(1)
    relogio.dormir(1)

    with pytest.raises(AssertionError, match="regressao no prazo"):
        relogio.dormir(1)


def test_processo_vivo_distingue_o_processo_atual_de_um_pid_inexistente() -> None:
    assert processo_vivo(os.getpid())
    assert not processo_vivo(2**22 + 12345)
