"""O pacote reprova requisitos ou destinos ausentes antes de gerar o PDF."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

import pytest

from scripts.evidencias.verificar import verificar


@pytest.fixture
def pacote(tmp_path: Path) -> Path:
    requisitos = tmp_path / "docs/requisitos/fase4/gap-analysis-fase-4.md"
    requisitos.parent.mkdir(parents=True)
    requisitos.write_text("| RF-028 | Abertura |\n| RF-029 | Status |\n")
    matriz = tmp_path / "docs/entrega/matriz-de-rastreabilidade.md"
    matriz.parent.mkdir(parents=True)
    matriz.write_text("| RF-028 | código |\n| RF-029 | código |\n")
    (tmp_path / "INDICE-DA-ENTREGA.md").write_text(
        "RF-028 a RF-029 [matriz](docs/entrega/matriz-de-rastreabilidade.md)\n"
    )
    documento = tmp_path / "docs/entrega/fase4/entrega-fase-4.md"
    documento.parent.mkdir()
    documento.write_text("# Ensaio\n\n[índice](../../../INDICE-DA-ENTREGA.md)\n")
    return tmp_path


def test_pacote_completo_resolve_links_a_partir_de_cada_documento(pacote: Path) -> None:
    assert verificar(pacote) == []


def test_requisito_ausente_na_matriz_reprova(pacote: Path) -> None:
    (pacote / "docs/entrega/matriz-de-rastreabilidade.md").write_text("RF-028\n")
    assert "matriz: requisito ausente RF-029" in verificar(pacote)


def test_requisito_ausente_no_indice_reprova(pacote: Path) -> None:
    (pacote / "INDICE-DA-ENTREGA.md").write_text("RF-028\n")
    assert "índice: requisito ausente RF-029" in verificar(pacote)


def test_link_quebrado_reprova_mesmo_com_fragmento(pacote: Path) -> None:
    doc = pacote / "docs/entrega/fase4/entrega-fase-4.md"
    doc.write_text("[prova](evidencias/ausente.md#resultado)\n")
    assert any("evidencias/ausente.md" in erro for erro in verificar(pacote))


def test_link_nao_pode_sair_do_repositorio(pacote: Path) -> None:
    (pacote / "INDICE-DA-ENTREGA.md").write_text("RF-028 a RF-029 [fora](../fora.md)")
    assert any("fora do repositório" in erro for erro in verificar(pacote))


def test_ensaio_nao_passa_por_documento_final(pacote: Path) -> None:
    erros = verificar(pacote, final=True)
    assert "final: identificação dos participantes ausente" in erros
    assert "final: link do vídeo ausente" in erros


def test_final_exige_links_congelados(pacote: Path) -> None:
    doc = pacote / "docs/entrega/fase4/entrega-fase-4.md"
    doc.write_text(
        "| João | RM123456 |\n[vídeo](https://youtu.be/exemplo)\n"
        "[fonte](https://github.com/grupo/repo/blob/main/README.md)\n"
    )
    assert "final: link de código ainda aponta para main" in verificar(
        pacote, final=True
    )


def test_documento_obrigatorio_ausente_reprova(pacote: Path) -> None:
    (pacote / "docs/entrega/fase4/entrega-fase-4.md").unlink()
    assert "arquivo ausente: docs/entrega/fase4/entrega-fase-4.md" in verificar(pacote)


def test_ancora_inexistente_reprova(pacote: Path) -> None:
    (pacote / "INDICE-DA-ENTREGA.md").write_text(
        "RF-028 a RF-029 [documento](docs/entrega/fase4/entrega-fase-4.md#nao-existe)"
    )
    assert any("âncora ausente" in erro for erro in verificar(pacote))


def test_final_exige_provas_operacionais_e_metadados(pacote: Path) -> None:
    erros = verificar(pacote, final=True)
    assert any("metadados GitHub ausentes" in erro for erro in erros)
    assert any("bdd-resumo.md" in erro for erro in erros)


def test_github_reprova_link_remoto_inexistente(pacote: Path) -> None:
    (pacote / "INDICE-DA-ENTREGA.md").write_text(
        "RF-028 a RF-029 [fonte](https://github.com/grupo/repo/blob/main/ausente.py)"
    )
    assert any(
        "link GitHub ausente" in e
        for e in verificar(
            pacote,
            github={
                "repositorios": [
                    {"repo": "grupo/repo", "head": "a" * 40, "arvore": ["README.md"]}
                ]
            },
        )
    )


def test_github_link_diretorio_e_arquivo_presentes(pacote: Path) -> None:
    (pacote / "INDICE-DA-ENTREGA.md").write_text(
        "RF-028 a RF-029 [fonte](https://github.com/grupo/repo/blob/main/a.py) "
        "[pasta](https://github.com/grupo/repo/tree/main/docs)"
    )
    assert (
        verificar(
            pacote,
            github={
                "repositorios": [
                    {"repo": "grupo/repo", "head": "a" * 40, "arvore": ["a.py", "docs"]}
                ]
            },
        )
        == []
    )


@pytest.mark.parametrize(
    "destino",
    [
        "https://github.com/grupo/repo/tree/main",
        "https://github.com/grupo/repo/blob/main/README.md",
    ],
)
def test_final_reprova_main_inclusive_raiz_da_arvore(
    pacote: Path, destino: str
) -> None:
    (pacote / "INDICE-DA-ENTREGA.md").write_text(f"RF-028 a RF-029 [código]({destino})")
    assert "final: link de código ainda aponta para main" in verificar(
        pacote, final=True
    )


FASE_3 = "fiap-postech-sw-architecture/postech-sw-arch-p3"


@pytest.mark.parametrize(("arvore", "quebrado"), [(["docs/x.md"], False), ([], True)])
def test_github_confere_link_da_fase_3_pela_arvore_coletada(
    pacote: Path, arvore: list[str], quebrado: bool
) -> None:
    (pacote / "INDICE-DA-ENTREGA.md").write_text(
        f"RF-028 a RF-029 [fase 3](https://github.com/{FASE_3}/blob/main/docs/x.md)"
    )
    erros = verificar(
        pacote,
        github={
            "repositorios": [],
            "referencias": [{"repo": FASE_3, "head": "a" * 40, "arvore": arvore}],
        },
    )
    assert not any("metadados GitHub ausentes" in erro for erro in erros)
    assert any("link GitHub ausente" in erro for erro in erros) is quebrado


@pytest.mark.parametrize(
    ("repo", "reprova"),
    [
        (FASE_3, False),
        (f"{FASE_3}-infra-k8s", True),
        ("fiap-postech-sw-architecture/postech-sw-arch-p4-platform", True),
    ],
)
def test_final_so_aceita_main_no_repositorio_da_fase_3(
    pacote: Path, repo: str, reprova: bool
) -> None:
    (pacote / "INDICE-DA-ENTREGA.md").write_text(
        f"RF-028 a RF-029 [código](https://github.com/{repo}/blob/main/README.md)"
    )
    erros = verificar(pacote, final=True)
    assert ("final: link de código ainda aponta para main" in erros) is reprova


def test_github_reprova_pr_citado_inexistente(pacote: Path) -> None:
    (pacote / "INDICE-DA-ENTREGA.md").write_text(
        "RF-028 a RF-029 [PR](https://github.com/grupo/repo/pull/99)"
    )
    erros = verificar(
        pacote,
        github={
            "repositorios": [
                {
                    "repo": "grupo/repo",
                    "prs_citados": [1],
                    "runs_citados": [],
                }
            ]
        },
    )
    assert any("link GitHub ausente" in erro for erro in erros)


@pytest.mark.parametrize(
    "trecho",
    [
        "Versão de ensaio.",
        "Documento de ensaio da turma",
        "Versão preliminar do pacote",
        "Durante o ensaio, os links apontam para main",
        "Inserir o link público após a gravação",
        "O vídeo ainda será gravado",
        "Esta versão não serve para submissão no portal",
        "Antes da submissão: confirmar participantes",
        "Implementado; evidência final em coleta",
        "aguardam confirmação do grupo",
        "Identificação pendente de confirmação",
        "Etapas que dependem do grupo",
    ],
)
def test_final_reprova_texto_preliminar(pacote: Path, trecho: str) -> None:
    (pacote / "docs/entrega/matriz-de-rastreabilidade.md").write_text(
        f"| RF-028 | código |\n| RF-029 | {trecho} |\n"
    )
    erros = [e for e in verificar(pacote, final=True) if "texto preliminar" in e]
    assert len(erros) == 1
    assert erros[0].startswith(
        "final: texto preliminar em docs/entrega/matriz-de-rastreabilidade.md: "
    )
    assert not any("texto preliminar" in e for e in verificar(pacote))


def test_final_confere_documento_e_indice(pacote: Path) -> None:
    (pacote / "docs/entrega/fase4/entrega-fase-4.md").write_text("Versão preliminar\n")
    (pacote / "INDICE-DA-ENTREGA.md").write_text("RF-028 a RF-029; vídeo pendente\n")
    erros = verificar(pacote, final=True)
    assert (
        "final: texto preliminar em docs/entrega/fase4/entrega-fase-4.md: "
        "versão preliminar"
    ) in erros
    assert "final: texto preliminar em INDICE-DA-ENTREGA.md: pendente" in erros


def test_final_ignora_bloco_de_codigo_e_acusa_o_texto_entre_blocos(
    pacote: Path,
) -> None:
    # Os diagramas da RFC copiados no documento trazem etapas e situações.
    (pacote / "docs/entrega/fase4/entrega-fase-4.md").write_text(
        "```mermaid\nstateDiagram-v2\n  AGUARDANDO_DECISAO --> X\n```\n"
        "Captura pendente.\n"
        '```mermaid\nerDiagram\n  n { varchar situacao "pendente ou dead" }\n```\n'
    )
    erros = [e for e in verificar(pacote, final=True) if "texto preliminar" in e]
    assert erros == [
        "final: texto preliminar em docs/entrega/fase4/entrega-fase-4.md: pendente"
    ]


def test_final_sem_marca_preliminar_nao_acusa_texto(pacote: Path) -> None:
    (pacote / "docs/entrega/fase4/entrega-fase-4.md").write_text(
        "| João | RM123456 |\nEnsaio local de 19/10 com 14 cenários.\n"
        "Pipeline independente de CI/CD; comando para coletar o snapshot.\n"
        "Etapa `AGUARDANDO_DECISAO`; métrica `outbox_pendentes`.\n"
    )
    assert not any("texto preliminar" in e for e in verificar(pacote, final=True))
