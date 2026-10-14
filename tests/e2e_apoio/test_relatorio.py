"""Resumo do E2E e registro do que cada cenario descobriu."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from e2e.apoio.relatorio import (
    Registro,
    escrever_resumo,
    gerar_resumo,
    principal,
)

if TYPE_CHECKING:
    from pathlib import Path


def _cucumber() -> list[dict[str, Any]]:
    def passo(status: str, ns: int) -> dict[str, Any]:
        return {"result": {"status": status, "duration": ns}}

    return [
        {
            "elements": [
                {
                    "name": "A OS percorre os tres servicos",
                    "tags": [{"name": "caminho-feliz"}, {"name": "demo"}],
                    "steps": [
                        passo("passed", 1_500_000_000),
                        passo("passed", 2_500_000_000),
                    ],
                },
                {
                    "name": "Orcamento vence",
                    "tags": [{"name": "expiracao"}],
                    "steps": [
                        passo("passed", 1_000_000_000),
                        passo("failed", 3_000_000_000),
                    ],
                },
                {
                    "name": "Pulado",
                    "tags": [],
                    "steps": [passo("passed", 0), passo("skipped", 0)],
                },
            ]
        }
    ]


def test_gerar_resumo_lista_cada_cenario_com_resultado_duracao_e_rastreio() -> None:
    registros = {
        "A OS percorre os tres servicos": {"ordem_id": "ord-1", "trace_id": "trace-1"}
    }

    texto = gerar_resumo(_cucumber(), registros, "Titulo")

    linhas = texto.splitlines()
    assert linhas[0] == "## Titulo"
    assert "3 cenários, 2 sem passar, 8 s no total." in texto
    assert (
        "| A OS percorre os tres servicos | `@caminho-feliz` `@demo` | passou | 4,0 | "
        "`ord-1` | `trace-1` |"
    ) in linhas
    assert "| Orcamento vence | `@expiracao` | falhou | 4,0 | `-` | `-` |" in linhas
    assert "| Pulado |  | não executado | 0,0 | `-` | `-` |" in linhas


def test_gerar_resumo_cenario_de_esquema_leva_o_exemplo_no_nome() -> None:
    cucumber = [
        {
            "elements": [
                {
                    "id": "test_swagger[/os]",
                    "name": "Swagger de cada servico",
                    "tags": [{"name": "borda"}],
                    "steps": [{"result": {"status": "passed", "duration": 0}}],
                },
                {
                    "id": "test_swagger[/billing]",
                    "name": "Swagger de cada servico",
                    "tags": [{"name": "borda"}],
                    "steps": [{"result": {"status": "passed", "duration": 0}}],
                },
            ]
        }
    ]

    linhas = gerar_resumo(cucumber, {}, "T").splitlines()

    assert any(
        linha.startswith("| Swagger de cada servico [/os] |") for linha in linhas
    )
    assert any(
        linha.startswith("| Swagger de cada servico [/billing] |") for linha in linhas
    )


def test_gerar_resumo_sem_cenarios() -> None:
    texto = gerar_resumo([{"elements": []}], {}, "Vazio")

    assert "0 cenários, 0 sem passar, 0 s no total." in texto


def test_registro_anota_por_cenario_e_salva_json(tmp_path: Path) -> None:
    registro = Registro()
    registro.anotar("A", ordem_id="o1")
    registro.anotar("A", trace_id="t1")
    registro.anotar("B", ordem_id="o2")

    registro.salvar(tmp_path / "cenarios.json")

    assert json.loads((tmp_path / "cenarios.json").read_text()) == {
        "A": {"ordem_id": "o1", "trace_id": "t1"},
        "B": {"ordem_id": "o2"},
    }


def test_escrever_resumo_junta_cucumber_e_registro_e_anexa_ao_step_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "cucumber.json").write_text(json.dumps(_cucumber()))
    (tmp_path / "cenarios.json").write_text(
        json.dumps({"Orcamento vence": {"ordem_id": "ord-9"}})
    )
    sumario = tmp_path / "step-summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(sumario))

    destino = escrever_resumo(tmp_path, "Meu resumo")

    assert destino == tmp_path / "resumo.md"
    assert "`ord-9`" in destino.read_text()
    assert sumario.read_text().startswith("## Meu resumo")


def test_escrever_resumo_sem_registro_e_sem_step_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "cucumber.json").write_text(json.dumps(_cucumber()))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    destino = escrever_resumo(tmp_path)

    assert "| Pulado |" in destino.read_text()


@pytest.mark.parametrize(
    "argumentos",
    [
        pytest.param([], id="nenhum-argumento"),
        pytest.param(["a", "b", "c", "d"], id="argumentos-demais"),
    ],
)
def test_principal_exige_o_diretorio_dos_relatorios(
    argumentos: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert principal(argumentos) == 2
    assert "uso:" in capsys.readouterr().err


def test_principal_escreve_o_resumo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "cucumber.json").write_text(json.dumps(_cucumber()))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    assert principal([str(tmp_path)]) == 0
    assert "resumo escrito em" in capsys.readouterr().out


def _cenario_com_passos(*estados: str) -> list[dict[str, Any]]:
    passos = [{"result": {"status": estado, "duration": 0}} for estado in estados]
    return [{"elements": [{"name": "C", "tags": [], "steps": passos}]}]


@pytest.mark.parametrize(
    ("estados", "resultado"),
    [
        pytest.param(("passed", "passed"), "passou", id="tudo-passou"),
        pytest.param(("passed", "failed"), "falhou", id="um-falhou"),
        pytest.param(("passed", "pending"), "não executado", id="passo-pendente"),
        pytest.param(("passed", "skipped"), "não executado", id="passo-pulado"),
        pytest.param(("passed", "undefined"), "não executado", id="sem-definicao"),
        pytest.param((), "não executado", id="sem-passos"),
    ],
)
def test_gerar_resumo_so_diz_passou_se_todo_passo_passou(
    estados: tuple[str, ...], resultado: str
) -> None:
    linhas = gerar_resumo(_cenario_com_passos(*estados), {}, "T").splitlines()

    assert any(
        f"| {resultado} |" in linha for linha in linhas if linha.startswith("| C")
    )


def test_principal_sem_cucumber_json_diz_o_que_aconteceu(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert principal([str(tmp_path)]) == 1
    assert "terminou antes de escrever" in capsys.readouterr().err


def test_escrever_resumo_com_outro_nome_nao_toca_no_resumo_md(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "cucumber.json").write_text(json.dumps(_cucumber()))
    (tmp_path / "resumo.md").write_text("a evidencia do sandbox\n")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    destino = escrever_resumo(tmp_path, "Relatorio", "relatorio-e2e.md")

    assert destino == tmp_path / "relatorio-e2e.md"
    assert destino.read_text().startswith("## Relatorio")
    assert (tmp_path / "resumo.md").read_text() == "a evidencia do sandbox\n"


def test_principal_com_arquivo_e_titulo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "cucumber.json").write_text(json.dumps(_cucumber()))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    assert principal([str(tmp_path), "outro.md", "Meu titulo"]) == 0
    assert (tmp_path / "outro.md").read_text().startswith("## Meu titulo")
    assert principal([str(tmp_path), "so-o-arquivo.md"]) == 0
    assert (
        (tmp_path / "so-o-arquivo.md")
        .read_text()
        .startswith("## Resumo do E2E da saga")
    )
