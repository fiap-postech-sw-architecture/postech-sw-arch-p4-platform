"""Nenhum texto de passo dos features casa com duas definicoes diferentes.

O pytest-bdd escolhe a definicao de um passo pela ordem em que as encontra: com duas
que casam o mesmo texto, qual vale depende de quem registrou primeiro. Foi o que quebrou
5 dos 13 cenarios do ``make e2e``: ``parsers.parse('... "{etapa}"')`` casa tambem
``... "x" pelo motivo "y"``, e o sandbox registrou o passo mais longo. Nenhum teste
offline via isso, porque o E2E so roda no kind.

O teste le as definicoes pelo codigo (as chamadas a ``given``, ``when`` e ``then``) e os
passos pelos features, e exige exatamente um padrao por texto.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import TYPE_CHECKING, Final, NamedTuple

import pytest
from pytest_bdd import parsers

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

RAIZ: Final = Path(__file__).resolve().parents[2]
E2E: Final = RAIZ / "e2e"
TIPOS_DE_DEFINICAO: Final = {"given": "dado", "when": "quando", "then": "entao"}
# Palavras do Gherkin em portugues; "E" e "Mas" repetem o tipo do passo anterior.
PALAVRAS: Final = {
    "dado": "dado",
    "quando": "quando",
    "então": "entao",
    "entao": "entao",
}
CONTINUACOES: Final = frozenset({"e", "mas"})
CONSTRUTORES: Final = {"parse": parsers.parse, "re": parsers.re}


class PadraoNaoConstanteError(AssertionError):
    """O padrao de um passo nao e um texto fixo: este teste nao consegue conferi-lo."""


class Definicao(NamedTuple):
    """Uma definicao de passo achada no codigo."""

    tipo: str
    padrao: str
    casa: Callable[[str], bool]
    onde: str


class Passo(NamedTuple):
    """Um passo de um feature."""

    tipo: str
    texto: str
    onde: str


def _padrao(argumento: ast.expr, onde: str) -> tuple[str, Callable[[str], bool]]:
    """O texto do padrao e quem o testa; recusa o que nao for um texto fixo."""
    if isinstance(argumento, ast.Constant) and isinstance(argumento.value, str):
        valor = argumento.value
        return valor, lambda texto: texto == valor
    if (
        isinstance(argumento, ast.Call)
        and isinstance(argumento.func, ast.Attribute)
        and isinstance(argumento.func.value, ast.Name)
        and argumento.func.value.id == "parsers"
        and argumento.func.attr in CONSTRUTORES
        and argumento.args
        and isinstance(argumento.args[0], ast.Constant)
        and isinstance(argumento.args[0].value, str)
    ):
        valor = argumento.args[0].value
        return valor, CONSTRUTORES[argumento.func.attr](valor).is_matching
    msg = (
        f"{onde}: o padrao do passo precisa ser um texto fixo ou parsers.parse/re de um"
    )
    raise PadraoNaoConstanteError(msg)


def definicoes() -> list[Definicao]:
    """Toda chamada a given/when/then em ``e2e/`` (decorador ou chamada direta)."""
    achadas: list[Definicao] = []
    for arquivo in sorted(E2E.rglob("*.py")):
        arvore = ast.parse(arquivo.read_text(encoding="utf-8"))
        for no in ast.walk(arvore):
            if (
                isinstance(no, ast.Call)
                and isinstance(no.func, ast.Name)
                and no.func.id in TIPOS_DE_DEFINICAO
                and no.args
            ):
                onde = f"{arquivo.relative_to(RAIZ)}:{no.lineno}"
                padrao, casa = _padrao(no.args[0], onde)
                achadas.append(
                    Definicao(TIPOS_DE_DEFINICAO[no.func.id], padrao, casa, onde)
                )
    return achadas


def passos() -> list[Passo]:
    """Todo passo dos features de ``e2e/features``."""
    achados: list[Passo] = []
    for arquivo in sorted((E2E / "features").glob("*.feature")):
        tipo = ""
        for numero, linha in enumerate(
            arquivo.read_text(encoding="utf-8").splitlines(), start=1
        ):
            palavra, _, texto = linha.strip().partition(" ")
            minuscula = palavra.lower()
            if minuscula in PALAVRAS:
                tipo = PALAVRAS[minuscula]
            elif minuscula not in CONTINUACOES or not tipo:
                continue
            achados.append(
                Passo(tipo, texto.strip(), f"{arquivo.relative_to(RAIZ)}:{numero}")
            )
    return achados


def ambiguidades(
    todas: Sequence[Definicao], dos_features: Sequence[Passo]
) -> list[str]:
    """Os passos cujo texto casa com dois padroes diferentes do mesmo tipo."""
    achadas: list[str] = []
    for passo in dos_features:
        padroes = {
            d.padrao: d.onde
            for d in todas
            if d.tipo == passo.tipo and d.casa(passo.texto)
        }
        if len(padroes) > 1:
            lista = "; ".join(f"{p!r} ({onde})" for p, onde in sorted(padroes.items()))
            achadas.append(f"{passo.onde} {passo.tipo} {passo.texto!r}: {lista}")
    return achadas


def test_ha_definicoes_e_passos_para_conferir() -> None:
    """O leitor acha o que conferir (um leitor que acha zero passa vazio)."""
    assert len(definicoes()) >= 20
    assert len(passos()) >= 40


def test_cada_texto_de_passo_casa_com_um_unico_padrao() -> None:
    """Nenhum texto de feature casa com dois padroes diferentes do mesmo tipo."""
    achadas = ambiguidades(definicoes(), passos())
    assert not achadas, "\n".join(achadas)


def test_a_conferencia_acusa_dois_padroes_para_o_mesmo_texto() -> None:
    """O caso que quebrou o E2E: o padrao curto engole o longo."""
    curto = 'a saga terminou como "{etapa}"'
    longo = 'a saga terminou como "{etapa}" pelo motivo "{motivo}"'
    todas = [
        Definicao("entao", curto, parsers.parse(curto).is_matching, "a.py:1"),
        Definicao("entao", longo, parsers.parse(longo).is_matching, "b.py:2"),
    ]
    texto = 'a saga terminou como "compensada" pelo motivo "estoque"'
    achadas = ambiguidades(todas, [Passo("entao", texto, "f.feature:3")])
    assert len(achadas) == 1
    assert "f.feature:3" in achadas[0]
    assert "a.py:1" in achadas[0]
    assert "b.py:2" in achadas[0]
    # Passos de outro tipo, ou com um padrao so, nao sao ambiguos.
    assert ambiguidades(todas, [Passo("dado", texto, "f.feature:4")]) == []
    assert ambiguidades(todas[:1], [Passo("entao", texto, "f.feature:5")]) == []


def test_o_passo_curto_nao_casa_o_texto_com_motivo() -> None:
    """O padrao do ``test_saga.py``: casa o passo sem motivo e so ele."""
    curto = parsers.re(r'a saga terminou como "(?P<etapa>[^"]+)"')
    assert curto.is_matching('a saga terminou como "concluida"')
    assert not curto.is_matching('a saga terminou como "compensada" pelo motivo "x"')


def test_padrao_que_nao_e_texto_fixo_e_recusado() -> None:
    """Um padrao montado em tempo de execucao nao se confere: o teste avisa."""
    variavel = ast.parse("PADRAO", mode="eval").body
    with pytest.raises(PadraoNaoConstanteError, match=r"a\.py:7.*texto fixo"):
        _padrao(variavel, "a.py:7")
