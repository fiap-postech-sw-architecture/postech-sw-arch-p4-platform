"""scripts/ci/implantar-servicos.sh com docker, kind e kubectl falsos.

Os falsos registram cada chamada (o kubectl, tambem o overlay da execucao que
o apply recebe). O teste confere que os servicos sem --tar saem do docker
build do proprio checkout, em paralelo, com o commit como tag e GIT_SHA; que
cada imagem entra no kind pelo caminho certo (arquivo ou imagem local); que o
overlay da execucao parte do overlay pedido, troca a imagem e some no fim; a
ordem de cada namespace (Jobs de inicializacao apagados, apply, banco, Job,
Deployments); que falha de build, de Job, de rollout ou de apply nomeia o
servico e o commit; que servico sem o overlay pedido, ou com imagem de
terceiro fora da tabela de versoes do README (citada ou nao em outro trecho
dele), falha antes de tudo; e os argumentos recusados.
"""

from __future__ import annotations

import json
import os
import shutil

# subprocess so roda o script do repositorio e o git dos checkouts de teste,
# sem shell.
import subprocess  # nosec B404
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

SCRIPT = (
    Path(__file__).resolve().parents[1] / "scripts" / "ci" / "implantar-servicos.sh"
)
GIT = shutil.which("git") or "git"
SERVICOS = {
    "os-service": "pytstop-os",
    "billing-service": "pytstop-billing",
    "execution-service": "pytstop-execucao",
}
REF_DO_CD = "ghcr.io/fiap/pytstop-os-service:5f2a9c1"
INICIALIZACAO = "app.kubernetes.io/component=inicializacao"

# docker falso: build que leva 0,5 s e registra inicio e fim (o paralelismo se
# ve na sobreposicao). DOCKER_FALSO_FALHA=<servico> faz o build dele falhar.
DOCKER_FALSO = r"""
import json
import os
import sys
import time
from pathlib import Path

args = sys.argv[1:]
if args[0] != "build":
    sys.exit(f"chamada inesperada: {args}")
inicio = time.monotonic()
time.sleep(0.5)
registro = {"args": args, "inicio": inicio, "fim": time.monotonic()}
with (Path(os.environ["FALSOS"]) / "docker.jsonl").open("a") as log:
    log.write(json.dumps(registro) + "\n")
ref = args[args.index("-t") + 1]
if os.environ.get("DOCKER_FALSO_FALHA") and os.environ["DOCKER_FALSO_FALHA"] in ref:
    sys.exit("ERROR: failed to solve: process did not complete successfully")
"""

KIND_FALSO = r"""
import json
import os
import sys
from pathlib import Path

with (Path(os.environ["FALSOS"]) / "kind.jsonl").open("a") as log:
    log.write(json.dumps(sys.argv[1:]) + "\n")
"""

# kubectl falso: o kustomize devolve as imagens de imagens.txt do overlay;
# cada namespace tem o banco, o Job de inicializacao e dois Deployments.
# KUBECTL_FALSO_FALHA=<namespace>:<verbo> faz o verbo falhar naquele namespace
# (apply, statefulset, job, deployment, sem-job).
KUBECTL_FALSO = r"""
import json
import os
import sys
from pathlib import Path

if sys.argv[1:2] == ["kustomize"]:
    with (Path(os.environ["FALSOS"]) / "kustomize.jsonl").open("a") as log:
        log.write(json.dumps(sys.argv[1:]) + "\n")
    for imagem in (Path(sys.argv[2]) / "imagens.txt").read_text().split():
        print(f"        image: {imagem}")
    sys.exit(0)

BANCOS = {"pytstop-os": "os-postgres", "pytstop-billing": "billing-mongo",
          "pytstop-execucao": "execucao-postgres"}
JOBS = {"pytstop-os": "os-migracao", "pytstop-billing": "billing-inicializacao",
        "pytstop-execucao": "execucao-migracao"}
args = sys.argv[1:]
resto = args[2:]
ns = ""
if resto[:1] == ["-n"]:
    ns, resto = resto[1], resto[2:]
registro = {"args": args}
if resto[:3] == ["apply", "--server-side", "-k"]:
    registro["kustomization"] = (Path(resto[3]) / "kustomization.yaml").read_text()
    # <tmp>/<namespace>/repo/k8s/overlays/execucao: o teste poe o namespace no
    # caminho do checkout, e o apply o le dali.
    ns = Path(resto[3]).parts[-5]
registro["ns"] = ns
with (Path(os.environ["FALSOS"]) / "kubectl.jsonl").open("a") as log:
    log.write(json.dumps(registro) + "\n")
falha = os.environ.get("KUBECTL_FALSO_FALHA", "")


def falha_em(verbo):
    if falha == f"{ns}:{verbo}":
        sys.exit(f"error: {verbo} failed in {ns}")


servico = ns.removeprefix("pytstop-")
if resto[:2] == ["delete", "job"]:
    pass
elif resto[:3] == ["apply", "--server-side", "-k"]:
    falha_em("apply")
    print(f"deployment.apps/{servico}-api serverside-applied")
elif resto == ["get", "statefulset", "-o", "name"]:
    falha_em("get-statefulset")
    print(f"statefulset.apps/{BANCOS[ns]}")
elif resto[:2] == ["rollout", "status"] and resto[2].startswith("statefulset"):
    falha_em("statefulset")
    print(f"{resto[2]} rolling update complete")
elif resto[:2] == ["get", "job"]:
    falha_em("get-job")
    if falha != f"{ns}:sem-job":
        print(f"job.batch/{JOBS[ns]}")
elif resto[0] == "wait":
    falha_em("job")
elif resto[0] == "logs":
    print(f"migration log of {resto[1]}")
elif resto == ["get", "deployment", "-o", "name"]:
    falha_em("get-deployment")
    print(f"deployment.apps/{servico}-api\ndeployment.apps/{servico}-relay")
elif resto[:2] == ["rollout", "status"] and resto[2].startswith("deployment"):
    falha_em("deployment")
    print(f"{resto[2]} successfully rolled out")
else:
    sys.exit(f"chamada inesperada: {args}")
"""


def git(*args: str, cwd: Path) -> str:
    processo = subprocess.run(  # noqa: S603  # nosec B603
        [GIT, "-c", "user.name=teste", "-c", "user.email=teste@exemplo.dev", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return processo.stdout.strip()


# Imagens de terceiros que os manifests de cada servico usam, todas na tabela
# de versoes do README.
DE_TERCEIROS = {
    "os-service": "postgres:16.15 prometheuscommunity/postgres-exporter:v0.20.1",
    "billing-service": "mongo:7.0.43 percona/mongodb_exporter:0.53.0",
    "execution-service": "postgres:16.15 prometheuscommunity/postgres-exporter:v0.20.1",
}


def checkout(raiz: Path, servico: str, *, overlay: str | None = "kind-ci") -> Path:
    """Checkout de um servico com um commit e, se pedido, o overlay."""
    # O nome do diretorio leva o namespace: o kubectl falso o le no apply.
    dir_ = raiz / SERVICOS[servico] / "repo"
    (dir_ / "k8s" / "overlays").mkdir(parents=True)
    if overlay:
        dir_overlay = dir_ / "k8s" / "overlays" / overlay
        dir_overlay.mkdir()
        (dir_overlay / "kustomization.yaml").write_text(
            "resources: [../../base]\n", encoding="utf-8"
        )
        # A propria imagem sem tag e com a do kind local, e as de terceiros.
        (dir_overlay / "imagens.txt").write_text(
            f"pytstop-{servico} pytstop-{servico}:dev {DE_TERCEIROS[servico]}\n",
            encoding="utf-8",
        )
    git("init", "-q", cwd=dir_)
    git("commit", "-q", "--allow-empty", "-m", "teste", cwd=dir_)
    return dir_


def sha(dir_: Path) -> str:
    return git("rev-parse", "HEAD", cwd=dir_)


class Implantacao:
    """Falsos no PATH, checkouts dos tres servicos e o tar do CD no tmp_path."""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp = tmp_path
        binarios = tmp_path / "bin"
        binarios.mkdir()
        for nome, codigo in (
            ("docker", DOCKER_FALSO),
            ("kind", KIND_FALSO),
            ("kubectl", KUBECTL_FALSO),
        ):
            binario = binarios / nome
            binario.write_text(f"#!{sys.executable}\n{codigo}", encoding="utf-8")
            binario.chmod(0o755)
        self.env = {
            chave: valor
            for chave, valor in os.environ.items()
            if chave not in {"KUBE_CONTEXT", "CLUSTER"}
        } | {
            "PATH": f"{binarios}{os.pathsep}{os.environ['PATH']}",
            "FALSOS": str(tmp_path),
        }
        self.dirs = {servico: checkout(tmp_path, servico) for servico in SERVICOS}
        self.tar = tmp_path / "imagem.tar"
        self.tar.write_bytes(b"tar")
        self.script = SCRIPT

    def roda(self, *args: str, **ambiente: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603  # nosec B603
            [str(self.script), *args],
            env=self.env | ambiente,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )

    def do_cd(self, **ambiente: str) -> subprocess.CompletedProcess[str]:
        """A chamada do CD do OS: a propria imagem pelo tar, os vizinhos do codigo."""
        return self.roda(
            "--overlay",
            "kind-ci",
            "--tar",
            f"os-service={self.tar}",
            "--imagem",
            f"os-service={REF_DO_CD}",
            *(f"{servico}={dir_}" for servico, dir_ in self.dirs.items()),
            **ambiente,
        )

    def chamadas(self, falso: str) -> list[Any]:
        arquivo = self.tmp / f"{falso}.jsonl"
        if not arquivo.exists():
            return []
        return [json.loads(linha) for linha in arquivo.read_text().splitlines()]


def verbos(chamadas: list[Any], ns: str) -> list[str]:
    """O verbo de cada chamada do kubectl naquele namespace, em ordem."""
    resultado = []
    for chamada in chamadas:
        if chamada["ns"] != ns:
            continue
        args: list[str] = chamada["args"]
        resto = args[4:] if args[2] == "-n" else args[2:]
        resultado.append(" ".join(resto[:2]) if resto[0] != "wait" else "wait")
    return resultado


# Verbos no namespace que falhou, ate a falha: depois dela, nada.
ATE_A_FALHA = {
    "apply": ["delete job", "apply --server-side"],
    "get-statefulset": ["delete job", "apply --server-side", "get statefulset"],
    "statefulset": [
        "delete job",
        "apply --server-side",
        "get statefulset",
        "rollout status",
    ],
    "sem-job": [
        "delete job",
        "apply --server-side",
        "get statefulset",
        "rollout status",
        "get job",
    ],
    "get-job": [
        "delete job",
        "apply --server-side",
        "get statefulset",
        "rollout status",
        "get job",
    ],
    "job": [
        "delete job",
        "apply --server-side",
        "get statefulset",
        "rollout status",
        "get job",
        "wait",
        "logs job.batch/billing-inicializacao",
    ],
    "deployment": [
        "delete job",
        "apply --server-side",
        "get statefulset",
        "rollout status",
        "get job",
        "wait",
        "get deployment",
        "rollout status",
    ],
    "get-deployment": [
        "delete job",
        "apply --server-side",
        "get statefulset",
        "rollout status",
        "get job",
        "wait",
        "get deployment",
    ],
}


@pytest.fixture
def implantacao(tmp_path: Path) -> Implantacao:
    return Implantacao(tmp_path)


def test_cd_constroi_os_vizinhos_carrega_e_implanta_na_ordem(
    implantacao: Implantacao,
) -> None:
    processo = implantacao.do_cd()

    assert processo.returncode == 0, processo.stderr
    dirs = implantacao.dirs
    # Vizinhos pelo docker build do checkout, com o commit como tag e GIT_SHA.
    builds = implantacao.chamadas("docker")
    assert sorted(tuple(build["args"]) for build in builds) == sorted(
        (
            "build",
            "--build-arg",
            f"GIT_SHA={sha(dirs[servico])}",
            "--build-arg",
            f"GIT_DATE={git('log', '-1', '--format=%cI', cwd=dirs[servico])}",
            "-t",
            f"pytstop-{servico}:{sha(dirs[servico])}",
            str(dirs[servico]),
        )
        for servico in ("billing-service", "execution-service")
    )
    # Em paralelo: um build comeca antes de o outro terminar.
    primeiro, segundo = sorted(builds, key=lambda build: float(build["inicio"]))
    assert segundo["inicio"] < primeiro["fim"]
    assert sorted(implantacao.chamadas("kind")) == sorted(
        [
            ["load", "image-archive", str(implantacao.tar), "--name", "pytstop-p4"],
            *(
                [
                    "load",
                    "docker-image",
                    f"pytstop-{servico}:{sha(dirs[servico])}",
                    "--name",
                    "pytstop-p4",
                ]
                for servico in ("billing-service", "execution-service")
            ),
        ]
    )
    kubectl = implantacao.chamadas("kubectl")
    assert {tuple(chamada["args"][:2]) for chamada in kubectl} == {
        ("--context", "kind-pytstop-p4")
    }
    # Overlay da execucao: o kind-ci com a imagem trocada.
    overlays = [
        yaml.safe_load(c["kustomization"]) for c in kubectl if "kustomization" in c
    ]
    imagens = {overlay["images"][0]["name"]: overlay for overlay in overlays}
    assert imagens == {
        "pytstop-os-service": {
            "apiVersion": "kustomize.config.k8s.io/v1beta1",
            "kind": "Kustomization",
            "resources": ["../kind-ci"],
            "images": [
                {
                    "name": "pytstop-os-service",
                    "newName": "ghcr.io/fiap/pytstop-os-service",
                    "newTag": "5f2a9c1",
                }
            ],
        },
        **{
            f"pytstop-{servico}": {
                "apiVersion": "kustomize.config.k8s.io/v1beta1",
                "kind": "Kustomization",
                "resources": ["../kind-ci"],
                "images": [
                    {
                        "name": f"pytstop-{servico}",
                        "newName": f"pytstop-{servico}",
                        "newTag": sha(dirs[servico]),
                    }
                ],
            }
            for servico in ("billing-service", "execution-service")
        },
    }
    for servico, ns in SERVICOS.items():
        assert verbos(kubectl, ns) == [
            "delete job",
            "apply --server-side",
            "get statefulset",
            "rollout status",
            "get job",
            "wait",
            "get deployment",
            "rollout status",
            "rollout status",
        ]
        assert not (dirs[servico] / "k8s" / "overlays" / "execucao").exists()
        assert (
            f"[{servico}] deployment.apps/{ns.removeprefix('pytstop-')}-relay"
            " successfully rolled out"
        ) in processo.stdout
    assert processo.stdout.endswith(
        "deployed: os-service billing-service execution-service\n"
    )


def test_job_de_inicializacao_apagado_esperado_pelo_rotulo(
    implantacao: Implantacao,
) -> None:
    processo = implantacao.do_cd()

    assert processo.returncode == 0, processo.stderr
    kubectl = [
        chamada["args"]
        for chamada in implantacao.chamadas("kubectl")
        if chamada["ns"] == "pytstop-billing"
    ]
    assert [
        "--context",
        "kind-pytstop-p4",
        "-n",
        "pytstop-billing",
        "delete",
        "job",
        "-l",
        INICIALIZACAO,
        "--ignore-not-found",
        "--timeout=60s",
    ] in kubectl
    assert [
        "--context",
        "kind-pytstop-p4",
        "-n",
        "pytstop-billing",
        "wait",
        "--for=condition=Complete",
        "job.batch/billing-inicializacao",
        "--timeout=300s",
    ] in kubectl


@pytest.mark.parametrize("verbo", ATE_A_FALHA)
def test_falha_num_namespace_nomeia_o_servico_e_os_outros_seguem(
    implantacao: Implantacao, verbo: str
) -> None:
    processo = implantacao.do_cd(KUBECTL_FALSO_FALHA=f"pytstop-billing:{verbo}")

    assert processo.returncode == 1
    commit = sha(implantacao.dirs["billing-service"])
    assert f"deploy failed: billing-service (commit {commit})" in processo.stderr
    kubectl = implantacao.chamadas("kubectl")
    # Os outros namespaces vao ate os Deployments; o que falhou para ali.
    for ns in ("pytstop-os", "pytstop-execucao"):
        assert verbos(kubectl, ns).count("rollout status") == 3
    assert verbos(kubectl, "pytstop-billing") == ATE_A_FALHA[verbo]
    assert "deployed:" not in processo.stdout
    if verbo == "job":
        assert (
            "[billing-service] migration log of job.batch/billing-inicializacao"
            in processo.stdout
        )
    # Sem Job, a mensagem diz isso; com erro do cluster, so o erro dele.
    assert (
        f"no Job labeled {INICIALIZACAO} in pytstop-billing" in processo.stdout
    ) == (verbo == "sem-job")
    for dir_ in implantacao.dirs.values():
        assert not (dir_ / "k8s" / "overlays" / "execucao").exists()


def test_build_que_falha_para_antes_do_kind_e_do_cluster(
    implantacao: Implantacao,
) -> None:
    processo = implantacao.do_cd(DOCKER_FALSO_FALHA="execution-service")

    assert processo.returncode == 1
    commit = sha(implantacao.dirs["execution-service"])
    assert (
        f"docker build failed: execution-service (commit {commit})" in processo.stderr
    )
    assert "failed to solve" in processo.stderr
    assert implantacao.chamadas("kind") == []
    assert implantacao.chamadas("kubectl") == []


def test_servico_sem_o_overlay_falha_antes_de_tudo_com_o_commit(
    implantacao: Implantacao, tmp_path: Path
) -> None:
    sem_overlay = checkout(tmp_path / "outro", "execution-service", overlay=None)
    implantacao.dirs["execution-service"] = sem_overlay

    processo = implantacao.do_cd()

    assert processo.returncode == 1
    assert (
        f"execution-service (commit {sha(sem_overlay)}) has no "
        "k8s/overlays/kind-ci/kustomization.yaml"
    ) in processo.stderr
    assert implantacao.chamadas("docker") == []
    assert implantacao.chamadas("kind") == []
    assert implantacao.chamadas("kubectl") == []


def test_overlay_da_execucao_que_ja_existe_fica_intocado(
    implantacao: Implantacao,
) -> None:
    existente = implantacao.dirs["billing-service"] / "k8s" / "overlays" / "execucao"
    existente.mkdir()
    (existente / "kustomization.yaml").write_text("de quem escreveu\n")

    processo = implantacao.do_cd()

    assert processo.returncode == 1
    assert "k8s/overlays/execucao already exists" in processo.stderr
    assert (existente / "kustomization.yaml").read_text() == "de quem escreveu\n"
    assert implantacao.chamadas("kubectl") == []


def test_contexto_e_cluster_do_ambiente(implantacao: Implantacao) -> None:
    processo = implantacao.do_cd(KUBE_CONTEXT="outro-contexto", CLUSTER="outro")

    assert processo.returncode == 0, processo.stderr
    assert {
        tuple(chamada["args"][:2]) for chamada in implantacao.chamadas("kubectl")
    } == {("--context", "outro-contexto")}
    assert {tuple(chamada[-2:]) for chamada in implantacao.chamadas("kind")} == {
        ("--name", "outro")
    }


@pytest.mark.parametrize(
    ("argumentos", "mensagem"),
    [
        (["os-service=DIR"], "usage:"),
        (["--overlay", "kind-ci"], "usage:"),
        (["--overlay", "kind-ci", "web-service=DIR"], "unknown service web-service"),
        (["--overlay", "kind-ci", "os-service=DIR", "os-service=DIR"], "given twice"),
        (
            ["--overlay", "kind-ci", "--tar", "os-service=TAR", "os-service=DIR"],
            "--tar and --imagem go together",
        ),
        (
            [
                "--overlay",
                "kind-ci",
                "--imagem",
                f"os-service={REF_DO_CD}",
                "os-service=DIR",
            ],
            "--tar and --imagem go together",
        ),
        (
            [
                "--overlay",
                "kind-ci",
                "--tar",
                "os-service=TAR",
                "--imagem",
                "os-service=ghcr.io/fiap/pytstop-os-service@sha256:abc",
                "os-service=DIR",
            ],
            "--imagem needs <name>:<tag>",
        ),
        (
            [
                "--overlay",
                "kind-ci",
                "--tar",
                "os-service=TAR",
                "--imagem",
                "os-service=localhost:5000/pytstop-os-service",
                "os-service=DIR",
            ],
            "--imagem needs <name>:<tag>",
        ),
        (
            [
                "--overlay",
                "kind-ci",
                "--tar",
                "billing-service=TAR",
                "--imagem",
                f"billing-service={REF_DO_CD}",
                "os-service=DIR",
            ],
            "billing-service: --tar or --imagem for a service that is not being",
        ),
    ],
    ids=[
        "sem-overlay",
        "sem-servico",
        "servico-desconhecido",
        "servico-repetido",
        "tar-sem-imagem",
        "imagem-sem-tar",
        "imagem-por-digest",
        "imagem-sem-tag",
        "tar-de-servico-fora",
    ],
)
def test_argumentos_recusados_sem_chamar_nada(
    implantacao: Implantacao, argumentos: list[str], mensagem: str
) -> None:
    trocas = {"DIR": str(implantacao.dirs["os-service"]), "TAR": str(implantacao.tar)}
    for chave, valor in trocas.items():
        argumentos = [argumento.replace(chave, valor) for argumento in argumentos]

    processo = implantacao.roda(*argumentos)

    assert processo.returncode == 2
    assert mensagem in processo.stderr
    assert implantacao.chamadas("docker") == []
    assert implantacao.chamadas("kubectl") == []


@pytest.mark.parametrize(
    "imagem",
    ["busybox:1.37", "postgres", "postgres:16.4", "pytstop-os-service:dev"],
    ids=["outra-imagem", "sem-tag", "outra-versao", "imagem-de-outro-servico"],
)
def test_imagem_fora_da_tabela_de_versoes_para_antes_de_tudo(
    implantacao: Implantacao, imagem: str
) -> None:
    dir_overlay = implantacao.dirs["billing-service"] / "k8s" / "overlays" / "kind-ci"
    (dir_overlay / "imagens.txt").write_text(
        f"pytstop-billing-service {DE_TERCEIROS['billing-service']} {imagem}\n"
    )

    processo = implantacao.do_cd()

    assert processo.returncode == 1
    commit = sha(implantacao.dirs["billing-service"])
    assert (
        f"billing-service (commit {commit}): images outside the versions table "
        f"of the platform README: {imagem}"
    ) in processo.stderr
    assert implantacao.chamadas("docker") == []
    assert implantacao.chamadas("kubectl") == []


def test_so_a_tabela_de_versoes_vale_como_lista_de_imagens(
    implantacao: Implantacao, tmp_path: Path
) -> None:
    # README de mentira, ao lado de uma copia do script: a tabela tem as imagens
    # de terceiros dos tres servicos menos a postgres:16.15, que so aparece na
    # prosa e na segunda coluna de outra tabela, depois da de versoes, como o
    # `postgres` do superusuario no README de verdade.
    plataforma = tmp_path / "plataforma"
    (plataforma / "scripts" / "ci").mkdir(parents=True)
    copia = plataforma / "scripts" / "ci" / SCRIPT.name
    shutil.copy(SCRIPT, copia)
    imagens = {i for lista in DE_TERCEIROS.values() for i in lista.split()}
    linhas = "".join(
        f"| item | `{imagem}` | para que serve |\n"
        for imagem in sorted(imagens - {"postgres:16.15"})
    )
    (plataforma / "README.md").write_text(
        "| Componente | Versão | Para que serve |\n|---|---|---|\n"
        + linhas
        + "\nO banco roda `postgres:16.15`.\n\n"
        "| Item | Outra tabela |\n|---|---|\n"
        "| a | `postgres:16.15` |\n",
        encoding="utf-8",
    )
    implantacao.script = copia

    processo = implantacao.do_cd()

    assert processo.returncode == 1
    commit = sha(implantacao.dirs["os-service"])
    assert (
        f"os-service (commit {commit}): images outside the versions table "
        "of the platform README: postgres:16.15"
    ) in processo.stderr
    assert implantacao.chamadas("docker") == []
    assert implantacao.chamadas("kubectl") == []


def test_versoes_conferidas_no_overlay_pedido(implantacao: Implantacao) -> None:
    processo = implantacao.do_cd()

    assert processo.returncode == 0, processo.stderr
    assert sorted(implantacao.chamadas("kustomize")) == sorted(
        ["kustomize", str(dir_ / "k8s" / "overlays" / "kind-ci")]
        for dir_ in implantacao.dirs.values()
    )
