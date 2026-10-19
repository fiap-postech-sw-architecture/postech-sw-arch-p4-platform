"""Estrutura do cd.yml do platform: o job e2e (ADR-041, ADR-042).

O workflow so roda no GitHub, e o run do proprio PR e a prova de que ele
funciona. Aqui se trava o que um run verde nao mostra: se alguem tirar o
diagnostico, o `if: always()` dos relatorios, o prazo de um passo, o SHA de uma
action de terceiro ou o commit certo de um servico, o run seguinte continua
verde e a diferenca so aparece no dia em que o job falha. O passo `shas`, que
decide o commit de cada servico, roda de verdade em `/bin/bash` com um `gh`
falso no PATH. O actionlint (make lint-scripts) confere a sintaxe e o
shellcheck dos `run:`.
"""

from __future__ import annotations

import json
import os
import re

# subprocess so roda o passo shas do proprio cd.yml, sem shell do usuario.
import subprocess  # nosec B404
import sys
from pathlib import Path
from typing import Any, NamedTuple

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
    # Os repositorios dos servicos sao publicos: ler os runs de CD deles nao
    # pede actions: read, e nada escreve.
    assert E2E["permissions"] == {"contents": "read"}
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
    # O runner roda o `run` sem `shell:` com `bash -e`: nounset e pipefail
    # sao do proprio passo.
    assert script.startswith("set -euo pipefail\n")
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


def test_o_token_do_run_so_existe_no_passo_shas() -> None:
    """Os passos que constroem o codigo dos servicos nao enxergam o token."""
    assert "env" not in CD
    assert "env" not in E2E
    com_token = [p.get("id") for p in PASSOS if "GH_TOKEN" in p.get("env", {})]
    assert com_token == ["shas"]


# gh falso do passo shas: guarda a chamada e responde, por repositorio, o
# head_sha do ultimo CD verde (vazio, 404 ou 500) ou a main HEAD.
GH_FALSO = """
import json
import os
import sys
from pathlib import Path

falsos = Path(os.environ["FALSOS"])
args = sys.argv[1:]
with (falsos / "gh.jsonl").open("a") as log:
    log.write(json.dumps(args) + "\\n")
estado = json.loads((falsos / "estado.json").read_text())
caminho = next(a for a in args if a.startswith("repos/"))
_, _, repo, *resto = caminho.split("/")
cfg = estado[repo]
if resto[0] != "actions":
    print(cfg["main"])
elif cfg["runs"] in (404, 500):
    print(f"gh: erro (HTTP {cfg['runs']})", file=sys.stderr)
    sys.exit(1)
else:
    print(cfg["runs"])
"""
A, B, C, D = ("a" * 40, "b" * 40, "c" * 40, "d" * 40)


class Shas(NamedTuple):
    processo: subprocess.CompletedProcess[str]
    saida: dict[str, str]
    resumo: str
    chamadas: list[list[str]]


def api(**por_servico: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Estado do gh falso: sem CD verde e main HEAD D, salvo o que vier."""
    estado = {f"postech-sw-arch-p4-{s}": {"runs": "", "main": D} for s in SERVICOS}
    for servico, cfg in por_servico.items():
        estado[f"postech-sw-arch-p4-{servico.replace('_', '-')}"] = cfg
    return estado


def roda_shas(tmp_path: Path, estado: dict[str, Any], **entradas: str) -> Shas:
    """O `run` do passo shas como o runner o roda: `bash -e` (sem `shell:`)."""
    binarios = tmp_path / "bin"
    binarios.mkdir(exist_ok=True)
    gh = binarios / "gh"
    gh.write_text(f"#!{sys.executable}\n{GH_FALSO}", encoding="utf-8")
    gh.chmod(0o755)
    (tmp_path / "estado.json").write_text(json.dumps(estado), encoding="utf-8")
    script = tmp_path / "shas.sh"
    script.write_text(passo("ultimo_verde()")["run"], encoding="utf-8")
    saida = tmp_path / "output"
    resumo = tmp_path / "summary"
    saida.write_text("")
    resumo.write_text("")
    ambiente = {
        "PATH": f"{binarios}{os.pathsep}{os.environ['PATH']}",
        "FALSOS": str(tmp_path),
        "DONO": "dono",
        "SHA_PROPRIO": A,
        "SHA_PLATFORM": "",
        "SHA_OS_SERVICE": "",
        "SHA_BILLING_SERVICE": "",
        "SHA_EXECUTION_SERVICE": "",
        "GITHUB_OUTPUT": str(saida),
        "GITHUB_STEP_SUMMARY": str(resumo),
    } | {chave.upper(): valor for chave, valor in entradas.items()}
    processo = subprocess.run(  # noqa: S603  # nosec B603
        ["/bin/bash", "-e", str(script)],
        env=ambiente,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    log = tmp_path / "gh.jsonl"
    chamadas = (
        [json.loads(linha) for linha in log.read_text().splitlines()]
        if log.exists()
        else []
    )
    pares = dict(linha.split("=", 1) for linha in saida.read_text().splitlines())
    return Shas(processo, pares, resumo.read_text(), chamadas)


def test_shas_usa_o_ultimo_cd_verde_de_cada_servico(tmp_path: Path) -> None:
    estado = api(
        os_service={"runs": A, "main": D},
        billing_service={"runs": B, "main": D},
        execution_service={"runs": C, "main": D},
    )
    r = roda_shas(tmp_path, estado)
    assert r.processo.returncode == 0, r.processo.stderr
    assert r.saida == {
        "sha_os_service": A,
        "sha_billing_service": B,
        "sha_execution_service": C,
    }
    assert r.resumo.count("| last green CD |") == 3
    assert "::warning::" not in r.processo.stdout
    # So a consulta do ultimo CD verde de cada um, sem ler a main.
    assert len(r.chamadas) == 3
    assert all("actions/workflows/cd.yml/runs" in " ".join(c) for c in r.chamadas)


def test_shas_404_cai_na_main_head_com_aviso(tmp_path: Path) -> None:
    r = roda_shas(tmp_path, api(billing_service={"runs": 404, "main": B}))
    assert r.processo.returncode == 0, r.processo.stderr
    assert r.saida["sha_billing_service"] == B
    assert (
        "::warning::postech-sw-arch-p4-billing-service has no green CD run on main"
        f" yet: using main HEAD {B}"
    ) in r.processo.stdout
    assert f"| `{B}` | main HEAD, no green CD yet |" in r.resumo


def test_shas_erro_da_api_que_nao_e_404_reprova_sem_cair_na_main(
    tmp_path: Path,
) -> None:
    r = roda_shas(tmp_path, api(execution_service={"runs": 500, "main": C}))
    assert r.processo.returncode != 0
    assert "HTTP 500" in r.processo.stderr
    assert r.saida == {}
    lidas = [" ".join(c) for c in r.chamadas]
    assert not any("execution-service/commits/main" in c for c in lidas)


@pytest.mark.parametrize("sha", ["", "lixo", "ABC"])
def test_shas_sem_commit_valido_reprova_nomeando_o_repositorio(
    tmp_path: Path, sha: str
) -> None:
    """Run sem head_sha e main sem SHA valido, ou head_sha fora do formato."""
    estado = api(os_service={"runs": sha, "main": "lixo" if not sha else D})
    r = roda_shas(tmp_path, estado)
    assert r.processo.returncode == 1
    assert (
        "::error::could not resolve a commit for postech-sw-arch-p4-os-service"
        in r.processo.stdout
    )
    assert r.saida == {}


@pytest.mark.parametrize(
    "entrada",
    ["sha_platform", "sha_os_service", "sha_billing_service", "sha_execution_service"],
)
@pytest.mark.parametrize(
    "valor", ["ABC123", A.upper(), "a" * 39, "a" * 41, f" {A}", "g" * 40]
)
def test_shas_input_fora_do_formato_reprova_antes_de_qualquer_consulta(
    tmp_path: Path, valor: str, entrada: str
) -> None:
    """Cada um dos quatro inputs do dispatch passa pela validacao do formato."""
    r = roda_shas(tmp_path, api(), **{entrada: valor})
    assert r.processo.returncode == 1
    assert (
        f"::error::input {entrada} must be 40 lowercase hexadecimal characters"
        in r.processo.stdout
    )
    # O valor recusado nao vai para o log.
    assert valor.strip() not in r.processo.stdout
    assert r.chamadas == []
    assert r.saida == {}


def test_shas_input_valido_e_usado_sem_consultar_aquele_servico(
    tmp_path: Path,
) -> None:
    r = roda_shas(
        tmp_path, api(os_service={"runs": A, "main": D}), sha_billing_service=B
    )
    assert r.processo.returncode == 0, r.processo.stderr
    assert r.saida["sha_billing_service"] == B
    assert r.saida["sha_os_service"] == A
    assert f"| `{B}` | dispatch input |" in r.resumo
    assert not any("billing-service" in " ".join(c) for c in r.chamadas)


def test_shas_sha_platform_so_aceita_o_commit_do_run(tmp_path: Path) -> None:
    r = roda_shas(tmp_path, api(), sha_platform=B)
    assert r.processo.returncode == 1
    assert "input sha_platform must be empty or the commit of this run" in (
        r.processo.stdout
    )
    assert r.chamadas == []
    r = roda_shas(tmp_path, api(), sha_platform=A)
    assert r.processo.returncode == 0, r.processo.stderr
    assert f"| postech-sw-arch-p4-platform | `{A}` | this run |" in r.resumo


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


def test_ordem_dos_passos_da_plataforma_ao_diagnostico() -> None:
    ordem = [
        posicao("ultimo_verde()"),
        posicao("astral-sh/setup-uv"),
        posicao("actions/setup-node"),
        posicao("scripts/ci/deploy-kind.sh"),
        posicao("implantar-servicos.sh"),
        posicao("smoke-servicos.sh"),
        posicao("make -C platform e2e"),
        posicao("make -C platform newman"),
        posicao("scripts/ci/zap-baseline.sh"),
        posicao("medir-kind.sh resumo"),
        posicao("e2e.varredura"),
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
        ("make -C platform newman", "newman"),
        ("scripts/ci/zap-baseline.sh", "zap"),
    ):
        assert f"platform/scripts/medir-kind.sh etapa {etapa}\n" in passo(trecho)["run"]


def test_resumo_e_artefatos_sempre_e_diagnostico_na_falha_ou_cancelamento() -> None:
    # Os scripts do platform so rodam depois do checkout dele: o passo shas
    # reprova antes de qualquer checkout com um input invalido.
    assert passo("medir-kind.sh resumo")["if"] == (
        "always() && hashFiles('platform/scripts/medir-kind.sh') != ''"
    )
    assert com_artefato("e2e-kind")["if"] == "always()"
    assert com_artefato("zap-baseline")["if"] == "always()"
    # Tambem no cancelamento, inclusive o do timeout-minutes do job.
    assert passo("diagnostico.sh")["if"] == (
        "(failure() || cancelled())"
        " && hashFiles('platform/scripts/ci/diagnostico.sh') != ''"
    )
    assert passo("diagnostico.sh")["run"] == "platform/scripts/ci/diagnostico.sh"


def test_a_varredura_de_segredos_roda_antes_do_upload_do_e2e_kind() -> None:
    """O artefato fica 90 dias num repositorio publico: a varredura apaga o
    arquivo com segredo e reprova, e o upload sobe so a pasta que ela olha."""
    varredura = passo("e2e.varredura")
    assert varredura["if"] == "always() && hashFiles('platform/reports/e2e/**') != ''"
    assert varredura["working-directory"] == "platform"
    assert varredura["run"] == "uv run --group e2e python -m e2e.varredura reports/e2e"
    assert posicao("e2e.varredura") < PASSOS.index(com_artefato("e2e-kind"))
    assert com_artefato("e2e-kind")["with"]["path"] == "platform/reports/e2e/"


def test_o_zap_roda_apos_o_e2e_reprovado_mas_nao_sem_o_smoke() -> None:
    zap = passo("scripts/ci/zap-baseline.sh")
    assert zap["if"] == "${{ !cancelled() && steps.smoke.conclusion == 'success' }}"
    assert passo("smoke-servicos.sh")["id"] == "smoke"
    # O E2E e o smoke nao tem `if`: o padrao, success(), reprova o job na falha.
    assert "if" not in passo("make -C platform e2e")
    assert "if" not in passo("smoke-servicos.sh")


def test_o_newman_roda_apos_tentativa_do_bdd_com_smoke_verde_sem_cancelamento() -> None:
    newman = passo("make -C platform newman")
    assert newman["if"] == "${{ !cancelled() && steps.smoke.conclusion == 'success' }}"
    assert posicao("make -C platform e2e") < PASSOS.index(newman)
    assert PASSOS.index(newman) < posicao("scripts/ci/zap-baseline.sh")


def test_o_newman_usa_node_24_e_o_pin_do_makefile_sem_instalacao_global() -> None:
    node = passo("actions/setup-node")
    assert node["uses"] == "actions/setup-node@v7"
    assert node["with"] == {"node-version": "24"}
    assert PASSOS.index(node) < posicao("make -C platform newman")
    makefile = (RAIZ / "Makefile").read_text(encoding="utf-8")
    assert re.search(r"^NEWMAN := newman@6\.2\.3$", makefile, re.MULTILINE)
    assert passo("make -C platform newman")["run"] == (
        "platform/scripts/medir-kind.sh etapa newman\nmake -C platform newman\n"
    )


def test_os_relatorios_newman_ficam_na_pasta_varrida_e_publicada_do_e2e() -> None:
    makefile = (RAIZ / "Makefile").read_text(encoding="utf-8")
    assert "--junitxml=reports/e2e/newman/junit.xml" in makefile
    assert posicao("make -C platform newman") < posicao("e2e.varredura")
    assert posicao("e2e.varredura") < PASSOS.index(com_artefato("e2e-kind"))
    assert com_artefato("e2e-kind")["with"]["path"] == "platform/reports/e2e/"


def test_nada_no_job_e2e_engole_a_falha_de_um_passo() -> None:
    """Um `continue-on-error` ou um `|| true` deixaria o job verde com o E2E,
    o ZAP ou o smoke vermelhos."""
    assert "continue-on-error" not in E2E
    for p in PASSOS:
        assert "continue-on-error" not in p, p.get("name")
        for linha in p.get("run", "").splitlines():
            assert "|| true" not in linha, linha
            assert "; true" not in linha, linha


def test_smoke_e2e_e_zap_rodam_so_a_marca_da_etapa_e_o_comando() -> None:
    assert passo("smoke-servicos.sh")["run"] == (
        "platform/scripts/medir-kind.sh etapa smoke\n"
        "platform/scripts/ci/smoke-servicos.sh\n"
    )
    assert passo("make -C platform e2e")["run"] == (
        "platform/scripts/medir-kind.sh etapa e2e\nmake -C platform e2e\n"
    )
    assert passo("scripts/ci/zap-baseline.sh")["run"] == (
        "platform/scripts/medir-kind.sh etapa zap\n"
        "platform/scripts/ci/zap-baseline.sh\n"
    )


def test_artefatos_e2e_kind_e_zap_baseline_por_90_dias() -> None:
    e2e_kind = com_artefato("e2e-kind")
    zap = com_artefato("zap-baseline")
    for artefato in (e2e_kind, zap):
        assert artefato["uses"] == "actions/upload-artifact@v7"
        assert artefato["with"]["retention-days"] == 90
        # O artefato e do run, nao da tentativa: sem overwrite, o upload do
        # "Re-run failed jobs" falha com o nome ja usado.
        assert artefato["with"]["overwrite"] is True
    assert e2e_kind["with"]["path"] == "platform/reports/e2e/"
    assert zap["with"]["path"] == "platform/reports/zap/"


def test_passos_longos_tem_prazo_proprio_dentro_do_do_job() -> None:
    longos = {
        "scripts/ci/deploy-kind.sh": 15,
        "implantar-servicos.sh": 25,
        "smoke-servicos.sh": 10,
        "make -C platform e2e": 20,
        "make -C platform newman": 12,
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
    if dono.startswith("actions/") and re.fullmatch(r"v\d+", versao):
        return
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


def test_uv_dos_dois_jobs_do_cd_tem_versao_fixa() -> None:
    for nome in ("deploy-kind", "e2e"):
        [uv] = [
            p
            for p in JOBS[nome]["steps"]
            if p.get("uses", "").startswith("astral-sh/setup-uv@")
        ]
        assert (
            uv["uses"] == "astral-sh/setup-uv@1c37ad07a6a961277cf70c0d37d6f313000f5884"
        )
        assert uv["with"]["version"] == "0.13.0"
