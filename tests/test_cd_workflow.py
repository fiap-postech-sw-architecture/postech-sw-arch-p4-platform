"""Estrutura do cd.yml do platform: o job e2e (ADR-041, ADR-042).

O workflow so roda no GitHub, e o run do proprio PR e a prova de que ele
funciona. Aqui se trava o que um run verde nao mostra: se alguem tirar o
diagnostico, o `if: always()` dos relatorios, o prazo de um passo, o SHA de uma
action de terceiro ou o commit certo de um servico, o run seguinte continua
verde e a diferenca so aparece no dia em que o job falha. O actionlint (make
lint-scripts) confere a sintaxe e o shellcheck dos `run:`.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

RAIZ = Path(__file__).resolve().parents[1]
WORKFLOWS = RAIZ / ".github" / "workflows"
CD_TEXTO = (WORKFLOWS / "cd.yml").read_text(encoding="utf-8")
CD: dict[Any, Any] = yaml.safe_load(CD_TEXTO)
JOBS: dict[str, Any] = CD["jobs"]
E2E: dict[str, Any] = JOBS["e2e"]
PASSOS: list[dict[str, Any]] = E2E["steps"]
SERVICOS = ("os-service", "billing-service", "execution-service")


def passo(trecho: str) -> dict[str, Any]:
    """O unico passo cujo `run` ou `uses` contem o trecho."""
    achados = [
        p for p in PASSOS if trecho in p.get("run", "") or trecho in p.get("uses", "")
    ]
    assert len(achados) == 1, f"{len(achados)} passos com {trecho!r}"
    return achados[0]


def posicao(trecho: str) -> int:
    return PASSOS.index(passo(trecho))


def com_artefato(nome: str) -> dict[str, Any]:
    achados = [p for p in PASSOS if p.get("with", {}).get("name") == nome]
    assert len(achados) == 1, f"{len(achados)} passos publicam o artefato {nome}"
    return achados[0]


def test_o_cd_tem_o_ci_o_deploy_kind_e_o_e2e() -> None:
    assert set(JOBS) == {"ci", "deploy-kind", "e2e"}


def test_gatilhos_e_entradas_do_dispatch() -> None:
    # O PyYAML le a chave `on` como True.
    gatilhos = CD[True]
    assert set(gatilhos) == {"pull_request", "push", "workflow_dispatch"}
    assert gatilhos["pull_request"] == {"branches": ["main"]}
    assert gatilhos["push"] == {"branches": ["main"]}
    # Os mesmos quatro inputs do dispatch do CD de cada servico, todos opcionais.
    entradas = gatilhos["workflow_dispatch"]["inputs"]
    assert set(entradas) == {
        "sha_platform",
        "sha_os_service",
        "sha_billing_service",
        "sha_execution_service",
    }
    assert all(not entrada["required"] for entrada in entradas.values())


def test_o_e2e_roda_em_todo_pr_e_com_o_ci_pulado_como_o_deploy_kind() -> None:
    assert E2E["needs"] == "ci"
    # A mesma condicao do deploy-kind: no PR o ci fica skipped; na main, so com
    # o CI verde; cancelado, nao roda.
    assert E2E["if"] == JOBS["deploy-kind"]["if"]
    assert "!cancelled()" in E2E["if"]
    assert "needs.ci.result == 'skipped'" in E2E["if"]
    assert "paths" not in CD[True]["pull_request"]


def test_runner_prazo_e_permissoes_minimas() -> None:
    assert E2E["runs-on"] == "ubuntu-24.04"
    assert E2E["timeout-minutes"] == 50
    assert CD["permissions"] == {"contents": "read"}
    # Ler os runs de CD dos servicos pede actions: read; nada escreve.
    assert E2E["permissions"] == {"contents": "read", "actions": "read"}
    assert "secrets." not in yaml.dump(E2E)


def test_um_run_por_ref_e_so_o_pr_cancela_o_run_em_curso() -> None:
    concorrencia = CD["concurrency"]
    assert concorrencia["group"] == "cd-${{ github.ref }}"
    assert concorrencia["cancel-in-progress"] == (
        "${{ github.event_name == 'pull_request' }}"
    )


def test_o_e2e_nao_interpola_expressao_no_script() -> None:
    """Input do dispatch e saida de passo entram por env, nunca no `run`."""
    for p in PASSOS:
        assert "${{" not in p.get("run", ""), p.get("name")


def test_os_shas_dos_servicos_vem_do_ultimo_cd_verde_com_aviso_na_falta() -> None:
    script = passo("ultimo_verde()")["run"]
    # A consulta e o fallback do cd.yml de cada servico, palavra por palavra
    # (a continuacao de linha do shell vira um espaco so).
    linhas = re.sub(r" *\\\n\s+", " ", script)
    assert (
        'gh api -X GET "repos/$DONO/$1/actions/workflows/cd.yml/runs"'
        " -f branch=main -f event=push -f status=success -f per_page=1"
        " --jq '.workflow_runs[0].head_sha // empty'"
    ) in linhas
    assert "grep -q 'HTTP 404'" in script
    assert 'gh api "repos/$DONO/$repo/commits/main" --jq .sha' in script
    assert "::warning::$repo has no green CD run on main yet" in script
    for servico in ("os_service", "billing_service", "execution_service"):
        assert f'resolver {servico} "$SHA_{servico.upper()}"' in script
    # O platform nao se resolve: e o commit do run, e o input so aceita esse.
    assert "resolver platform" not in script
    assert '"$SHA_PLATFORM" != "$SHA_PROPRIO"' in script
    # Cada input casa 40 hexadecimais minusculos antes de qualquer checkout.
    assert "padrao='^[0-9a-f]{40}$'" in script
    ambiente = passo("ultimo_verde()")["env"]
    assert ambiente["SHA_PROPRIO"] == "${{ github.sha }}"
    # Expressao do Actions que le o token do run, nao um segredo no arquivo.
    assert ambiente["GH_TOKEN"] == "${{ github.token }}"  # noqa: S105
    for nome in ("platform", "os_service", "billing_service", "execution_service"):
        assert ambiente[f"SHA_{nome.upper()}"] == f"${{{{ inputs.sha_{nome} }}}}"
    assert posicao("ultimo_verde()") < min(
        i for i, p in enumerate(PASSOS) if "actions/checkout" in p.get("uses", "")
    )


def test_checkouts_do_platform_deste_commit_e_dos_servicos_nos_shas() -> None:
    checkouts = [p for p in PASSOS if "actions/checkout" in p.get("uses", "")]
    assert [c["with"]["path"] for c in checkouts] == ["platform", *SERVICOS]
    for c in checkouts:
        assert c["with"]["persist-credentials"] is False
    platform, *vizinhos = checkouts
    # O commit do run: sem `ref`, o checkout usa o do gatilho (no PR, o merge).
    assert "ref" not in platform["with"]
    assert "repository" not in platform["with"]
    for servico, c in zip(SERVICOS, vizinhos, strict=True):
        saida = servico.replace("-", "_")
        assert c["with"]["repository"] == (
            f"${{{{ github.repository_owner }}}}/postech-sw-arch-p4-{servico}"
        )
        assert c["with"]["ref"] == f"${{{{ steps.shas.outputs.sha_{saida} }}}}"


def test_os_tres_servicos_sao_construidos_do_codigo_sem_imagem_pronta() -> None:
    implantar = passo("implantar-servicos.sh")["run"]
    assert "--overlay kind-ci" in implantar
    assert "--tar" not in implantar
    assert "--imagem" not in implantar
    for servico in SERVICOS:
        assert f"{servico}={servico}" in implantar
    # Sem job image: nada publica no GHCR nem baixa artefato de imagem.
    assert "actions/download-artifact" not in CD_TEXTO
    assert "packages" not in E2E["permissions"]


def test_ordem_dos_passos_da_plataforma_ao_diagnostico() -> None:
    ordem = [
        posicao("ultimo_verde()"),
        posicao("astral-sh/setup-uv"),
        posicao("scripts/ci/deploy-kind.sh"),
        posicao("implantar-servicos.sh"),
        posicao("smoke-servicos.sh"),
        posicao("make -C platform e2e"),
        posicao("scripts/ci/zap-baseline.sh"),
        posicao("medir-kind.sh resumo"),
        PASSOS.index(com_artefato("e2e-kind")),
        PASSOS.index(com_artefato("zap-baseline")),
        posicao("diagnostico.sh"),
    ]
    assert ordem == sorted(ordem)
    assert len(set(ordem)) == len(ordem)


def test_cada_etapa_e_marcada_para_a_medicao() -> None:
    for trecho, etapa in (
        ("implantar-servicos.sh", "servicos"),
        ("smoke-servicos.sh", "smoke"),
        ("make -C platform e2e", "e2e"),
        ("scripts/ci/zap-baseline.sh", "zap"),
    ):
        assert f"platform/scripts/medir-kind.sh etapa {etapa}\n" in passo(trecho)["run"]


def test_resumo_e_artefatos_sempre_e_diagnostico_na_falha_ou_cancelamento() -> None:
    assert passo("medir-kind.sh resumo")["if"] == "always()"
    assert com_artefato("e2e-kind")["if"] == "always()"
    assert com_artefato("zap-baseline")["if"] == "always()"
    # Tambem no cancelamento, inclusive o do timeout-minutes do job.
    assert passo("diagnostico.sh")["if"] == "failure() || cancelled()"
    assert passo("diagnostico.sh")["run"] == "platform/scripts/ci/diagnostico.sh"


def test_o_zap_roda_apos_o_e2e_reprovado_mas_nao_sem_o_smoke() -> None:
    zap = passo("scripts/ci/zap-baseline.sh")
    assert zap["if"] == "${{ !cancelled() && steps.smoke.conclusion == 'success' }}"
    assert passo("smoke-servicos.sh")["id"] == "smoke"
    # O E2E e o smoke nao tem `if`: o padrao, success(), reprova o job na falha.
    assert "if" not in passo("make -C platform e2e")
    assert "if" not in passo("smoke-servicos.sh")


def test_artefatos_e2e_kind_e_zap_baseline_por_90_dias() -> None:
    e2e_kind = com_artefato("e2e-kind")
    zap = com_artefato("zap-baseline")
    for artefato in (e2e_kind, zap):
        assert artefato["uses"] == "actions/upload-artifact@v7"
        assert artefato["with"]["retention-days"] == 90
    # reports/e2e (e reports/demo, quando o make demo rodar), sem o do ZAP, que
    # tem artefato proprio.
    assert e2e_kind["with"]["path"].split() == [
        "platform/reports/",
        "!platform/reports/zap/**",
    ]
    assert zap["with"]["path"] == "platform/reports/zap/"


def test_passos_longos_tem_prazo_proprio_dentro_do_do_job() -> None:
    longos = {
        "scripts/ci/deploy-kind.sh": 15,
        "implantar-servicos.sh": 25,
        "smoke-servicos.sh": 10,
        "make -C platform e2e": 20,
        "scripts/ci/zap-baseline.sh": 20,
    }
    for trecho, minutos in longos.items():
        assert passo(trecho)["timeout-minutes"] == minutos, trecho
        assert minutos < E2E["timeout-minutes"]


def test_prazo_do_zap_por_servico_cabe_no_prazo_do_passo() -> None:
    """Tres servicos no prazo padrao do script nao passam do prazo do passo."""
    script = (RAIZ / "scripts" / "ci" / "zap-baseline.sh").read_text(encoding="utf-8")
    padrao = re.search(r'^PRAZO_ZAP="\$\{PRAZO_ZAP:-(\d+)\}"$', script, re.MULTILINE)
    assert padrao is not None
    minutos = passo("scripts/ci/zap-baseline.sh")["timeout-minutes"]
    assert len(SERVICOS) * int(padrao.group(1)) <= minutos * 60


def workflows_e_usos() -> list[tuple[str, str]]:
    """(workflow, valor de cada `uses`) de todos os workflows do repositorio."""
    usos = []
    for arquivo in sorted(WORKFLOWS.glob("*.yml")):
        documento = yaml.safe_load(arquivo.read_text(encoding="utf-8"))
        for job in documento["jobs"].values():
            usos += [(arquivo.name, job["uses"])] if "uses" in job else []
            usos += [
                (arquivo.name, p["uses"]) for p in job.get("steps", []) if "uses" in p
            ]
    return usos


@pytest.mark.parametrize(("workflow", "uses"), workflows_e_usos())
def test_action_de_terceiro_por_sha_de_commit_e_oficial_por_tag(
    workflow: str, uses: str
) -> None:
    if uses.startswith("./"):
        return
    dono, _, versao = uses.partition("@")
    if dono.startswith("actions/"):
        assert re.fullmatch(r"v\d+", versao), f"{workflow}: {uses}"
    else:
        assert re.fullmatch(r"[0-9a-f]{40}", versao), f"{workflow}: {uses}"


def test_o_sha_da_action_de_terceiro_leva_a_tag_ao_lado() -> None:
    for linha in CD_TEXTO.splitlines():
        if "uses: astral-sh/" in linha:
            assert re.search(r"@[0-9a-f]{40} # v\d+\.\d+\.\d+$", linha), linha


def test_o_e2e_usa_o_mesmo_setup_uv_do_deploy_kind() -> None:
    usos = [
        p["uses"]
        for p in JOBS["deploy-kind"]["steps"]
        if "setup-uv" in p.get("uses", "")
    ]
    assert usos
    assert passo("astral-sh/setup-uv")["uses"] == usos[0]
