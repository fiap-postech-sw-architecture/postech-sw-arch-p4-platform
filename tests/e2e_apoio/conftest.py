"""Fixtures comuns dos testes do codigo auxiliar do E2E."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from e2e.apoio import segredos
from e2e_apoio.falsos import Relogio

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture
def relogio() -> Relogio:
    return Relogio()


@pytest.fixture(autouse=True)
def _sem_segredos_registrados() -> Iterator[None]:
    segredos.esquecer_todos()
    yield
    segredos.esquecer_todos()
