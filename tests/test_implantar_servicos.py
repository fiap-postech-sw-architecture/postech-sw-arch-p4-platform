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

import io
import json
import os
import re
import shutil

# subprocess so roda o script do repositorio e o git dos checkouts de teste,
# sem shell.
import subprocess  # nosec B404
import sys
import tarfile
import time
from pathlib import Path
from typing import Any

import pytest
import yaml

SCRIPT = (
    Path(__file__).resolve().parents[1] / "scripts" / "ci" / "implantar-servicos.sh"
)
LEITOR_DO_README = SCRIPT.with_name("imagens-do-readme.sh")
GIT = shutil.which("git") or "git"
SERVICOS = {
    "os-service": "pytstop-os",
    "billing-service": "pytstop-billing",
    "execution-service": "pytstop-execucao",
}
REF_DO_CD = "ghcr.io/fiap/pytstop-os-service:5f2a9c1"
INICIALIZACAO = "app.kubernetes.io/component=inicializacao"

# docker falso: registra a chamada. Com DOCKER_FALSO_BARREIRA=<n>, cada build
# marca que comecou e espera os n comecarem (com teto de 30 s): o paralelismo se
# prova pelos n terem se visto, sem comparar tempos. DOCKER_FALSO_FALHA=<servico>
# faz o build dele falhar, e DOCKER_FALSO_PENDURA=<servico>, pendurar.
DOCKER_FALSO = r"""
import json
import os
import sys
import time
from pathlib import Path

args = sys.argv[1:]
if args[0] != "build":
    sys.exit(f"chamada inesperada: {args}")
dir_ = Path(os.environ["FALSOS"])
juntos = True
esperados = int(os.environ.get("DOCKER_FALSO_BARREIRA", "0"))
if esperados:
    (dir_ / f"inicio-{os.getpid()}").touch()
    limite = time.monotonic() + 10
    while len(list(dir_.glob("inicio-*"))) < esperados:
        if time.monotonic() > limite:
            juntos = False
            break
        time.sleep(0.02)
# Onde o script guarda o log do build: sob o TMPDIR, se o teste o definiu.
tmp = len(list(Path(os.environ.get("TMPDIR", "/nao/existe")).glob("*/build-*.log")))
with (dir_ / "docker.jsonl").open("a") as log:
    log.write(json.dumps({"args": args, "juntos": juntos, "tmp": tmp}) + "\n")
ref = args[args.index("-t") + 1]
if os.environ.get("DOCKER_FALSO_FALHA") and os.environ["DOCKER_FALSO_FALHA"] in ref:
    sys.exit("ERROR: failed to solve: process did not complete successfully")
if os.environ.get("DOCKER_FALSO_PENDURA") and os.environ["DOCKER_FALSO_PENDURA"] in ref:
    time.sleep(120)
"""

# kind falso: KIND_FALSO=falha faz o load falhar, e KIND_FALSO=pendura, pendurar.
KIND_FALSO = r"""
import json
import os
import sys
import tarfile
import time
from pathlib import Path

with (Path(os.environ["FALSOS"]) / "kind.jsonl").open("a") as log:
    log.write(json.dumps(sys.argv[1:]) + "\n")
if os.environ.get("KIND_FALSO") == "falha":
    sys.exit("ERROR: failed to load image")
if os.environ.get("KIND_FALSO") == "pendura":
    time.sleep(120)
"""

# So o Linux tem timeout; o falso o poe no PATH tambem no macOS (onde o script
# cai no alarm do perl) e registra o prazo de cada chamada.
TIMEOUT_FALSO = r"""
import json
import os
import sys
from pathlib import Path

with (Path(os.environ["FALSOS"]) / "timeout.jsonl").open("a") as log:
    log.write(json.dumps(sys.argv[1:]) + "\n")
os.execvp(sys.argv[2], sys.argv[2:])
"""

# kubectl falso: o kustomize devolve as imagens de imagens.txt do overlay (cada
# uma na forma que o prefixo escolhe: "image:", "lista:", "aspas:" ou "volume:");
# cada namespace tem o banco, o Job de inicializacao e dois Deployments.
# KUBECTL_FALSO_FALHA=<namespace>:<verbo> faz o verbo falhar naquele namespace
# (secret, delete, apply, statefulset, job, deployment; job e o Job que falha, e
# sem-statefulset, sem-job e sem-deployment, a lista vazia), e
# KUBECTL_FALSO_PENDURA=<namespace>:<verbo>, pendurar.
# KUBECTL_FALSO_JOB_PENDENTE=<namespace> deixa o Job rodando para sempre.
# KUSTOMIZE_FALSO_FALHA=1 faz o kustomize falhar.
KUBECTL_FALSO = r"""
import json
import os
import sys
import tarfile
import time
from pathlib import Path

if sys.argv[1:2] == ["kustomize"]:
    with (Path(os.environ["FALSOS"]) / "kustomize.jsonl").open("a") as log:
        log.write(json.dumps(sys.argv[1:]) + "\n")
    if os.environ.get("KUSTOMIZE_FALSO_FALHA"):
        sys.exit("error: accumulating resources")
    # O kustomize emite "image:" como chave de um item com outras chaves antes
    # dela e como primeira chave do item ("- image:"), entre aspas quando o
    # nome e so de digitos, e o volume de imagem com a ref em "reference:". No
    # imagens.txt, o prefixo "lista:", "aspas:" ou "volume:" escolhe a forma.
    for imagem in (Path(sys.argv[2]) / "imagens.txt").read_text().split():
        if imagem.startswith("lista:"):
            print("      - image: " + imagem.removeprefix("lista:"))
        elif imagem.startswith("aspas:"):
            print('        image: "' + imagem.removeprefix("aspas:") + '"')
        elif imagem.startswith("volume:"):
            print("      - image:\n          pullPolicy: IfNotPresent")
            print("          reference: " + imagem.removeprefix("volume:"))
        else:
            print("        image: " + imagem)
    sys.exit(0)

BANCOS = {"pytstop-os": "os-postgres", "pytstop-billing": "billing-mongo",
          "pytstop-execucao": "execucao-postgres"}
JOBS = {"pytstop-os": "os-migracao", "pytstop-billing": "billing-inicializacao",
        "pytstop-execucao": "execucao-migracao"}
SEGREDOS_DO_BANCO = {"pytstop-os": "os-postgres", "pytstop-billing": "billing-mongo",
                     "pytstop-execucao": "execucao-postgres"}
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
pendura = os.environ.get("KUBECTL_FALSO_PENDURA", "")


def pendura_em(verbo):
    if pendura == f"{ns}:{verbo}":
        time.sleep(120)


def falha_em(verbo):
    pendura_em(verbo)
    if falha == f"{ns}:{verbo}":
        sys.exit(f"error: {verbo} failed in {ns}")


servico = ns.removeprefix("pytstop-")
if resto[:2] == ["delete", "job"]:
    falha_em("delete")
elif resto[:3] == ["apply", "--server-side", "-k"]:
    falha_em("apply")
    print(f"deployment.apps/{servico}-api serverside-applied")
elif resto == ["get", "statefulset", "-o", "name"]:
    falha_em("get-statefulset")
    if falha != f"{ns}:sem-statefulset":
        print(f"statefulset.apps/{BANCOS[ns]}")
elif resto[:2] == ["rollout", "status"] and resto[2].startswith("statefulset"):
    falha_em("statefulset")
    print(f"{resto[2]} rolling update complete")
elif resto[:2] == ["get", "job"]:
    falha_em("get-job")
    if falha != f"{ns}:sem-job":
        print(f"job.batch/{JOBS[ns]}")
elif resto[0] == "get" and resto[1].startswith("job.batch/"):
    # As condicoes verdadeiras do Job: Failed no namespace de "job", nenhuma
    # (ainda rodando) no de KUBECTL_FALSO_JOB_PENDENTE.
    pendura_em("job")
    falha_em("poll-job")
    if falha == f"{ns}:job":
        print("Failed ", end="")
    elif os.environ.get("KUBECTL_FALSO_JOB_PENDENTE") != ns:
        print("Complete ", end="")
elif resto[:2] == ["get", "secret"]:
    # Os dois Secrets que o make deploy cria no namespace: o rabbitmq e o do banco.
    assert resto[2:] == ["rabbitmq", SEGREDOS_DO_BANCO[ns], "-o", "name"], resto
    falha_em("secret")
    print("secret/rabbitmq")
elif resto[0] == "logs":
    falha_em("logs")
    print(f"migration log of {resto[1]}")
elif resto == ["get", "deployment", "-o", "name"]:
    falha_em("get-deployment")
    if falha != f"{ns}:sem-deployment":
        print(f"deployment.apps/{servico}-api\ndeployment.apps/{servico}-relay")
elif resto[:2] == ["rollout", "status"] and resto[2].startswith("deployment"):
    falha_em("deployment")
    print(f"{resto[2]} successfully rolled out")
else:
    sys.exit(f"chamada inesperada: {args}")
"""


def git(*args: str, cwd: Path) -> str:
    """O git dos checkouts de teste, sem a configuracao de quem roda (assinatura
    de commit, hooks globais)."""
    processo = subprocess.run(  # noqa: S603  # nosec B603
        [
            GIT,
            "-c",
            "user.name=teste",
            "-c",
            "user.email=teste@exemplo.dev",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "core.hooksPath=/dev/null",
            *args,
        ],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
        env=os.environ | {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"},
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
            f"lista:pytstop-{servico} pytstop-{servico}:dev {DE_TERCEIROS[servico]}\n",
            encoding="utf-8",
        )
    git("init", "-q", cwd=dir_)
    git("add", "-A", cwd=dir_)
    git("commit", "-q", "--allow-empty", "-m", "teste", cwd=dir_)
    return dir_


def sha(dir_: Path) -> str:
    return git("rev-parse", "HEAD", cwd=dir_)


def faz_tar(destino: Path, *refs: str) -> Path:
    """Um arquivo no formato do docker save, com o manifest.json das refs."""
    manifest = json.dumps([{"Config": "c.json", "RepoTags": list(refs), "Layers": []}])
    dados = manifest.encode()
    with tarfile.open(destino, "w") as arquivo:
        info = tarfile.TarInfo("manifest.json")
        info.size = len(dados)
        arquivo.addfile(info, io.BytesIO(dados))
    return destino


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
        self.tar = faz_tar(tmp_path / "imagem.tar", REF_DO_CD)
        self.imagem = REF_DO_CD
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
            f"os-service={self.imagem}",
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
        if resto[0] == "get" and resto[1].startswith("job.batch/"):
            resultado.append("poll job")
        else:
            resultado.append(" ".join(resto[:2]))
    return resultado


# Verbos no namespace que falhou, ate a falha: depois dela, nada.
_ANTES_DO_BANCO = ["get secret", "delete job", "apply --server-side"]
_ANTES_DO_JOB = [*_ANTES_DO_BANCO, "get statefulset", "rollout status", "get job"]
_ANTES_DOS_DEPLOYMENTS = [*_ANTES_DO_JOB, "poll job", "get deployment"]
ATE_A_FALHA = {
    "secret": ["get secret"],
    "delete": ["get secret", "delete job"],
    "apply": _ANTES_DO_BANCO,
    "get-statefulset": [*_ANTES_DO_BANCO, "get statefulset"],
    "sem-statefulset": [*_ANTES_DO_BANCO, "get statefulset"],
    "statefulset": [*_ANTES_DO_BANCO, "get statefulset", "rollout status"],
    "get-job": _ANTES_DO_JOB,
    "sem-job": _ANTES_DO_JOB,
    # Job que falha, ou erro do cluster ao le-lo: o log vem do mesmo jeito.
    "poll-job": [*_ANTES_DO_JOB, "poll job", "logs job.batch/billing-inicializacao"],
    "job": [*_ANTES_DO_JOB, "poll job", "logs job.batch/billing-inicializacao"],
    "get-deployment": _ANTES_DOS_DEPLOYMENTS,
    "sem-deployment": _ANTES_DOS_DEPLOYMENTS,
    "deployment": [*_ANTES_DOS_DEPLOYMENTS, "rollout status"],
}
# A lista vazia que cada verbo "sem-" provoca, e a mensagem do script.
SEM_RECURSO = {
    "sem-statefulset": "no StatefulSet in pytstop-billing",
    "sem-job": f"no Job labeled {INICIALIZACAO} in pytstop-billing",
    "sem-deployment": "no Deployment in pytstop-billing",
}


@pytest.fixture
def implantacao(tmp_path: Path) -> Implantacao:
    return Implantacao(tmp_path)


def test_cd_constroi_os_vizinhos_carrega_e_implanta_na_ordem(
    implantacao: Implantacao,
) -> None:
    processo = implantacao.do_cd(DOCKER_FALSO_BARREIRA="2")

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
    # Em paralelo: cada build viu o outro comecar antes de terminar.
    assert [build["juntos"] for build in builds] == [True, True]
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
            "get secret",
            "delete job",
            "apply --server-side",
            "get statefulset",
            "rollout status",
            "get job",
            "poll job",
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
        "get",
        "job.batch/billing-inicializacao",
        "-o",
        'jsonpath={range .status.conditions[?(@.status=="True")]}{.type} {end}',
    ] in kubectl


@pytest.mark.parametrize("verbo", ATE_A_FALHA)
def test_falha_num_namespace_nomeia_o_servico_e_os_outros_seguem(
    implantacao: Implantacao, verbo: str
) -> None:
    # Com o prazo do Job curto, um Job Failed que fosse esperado ate o fim
    # estouraria o timeout do teste.
    processo = implantacao.do_cd(
        KUBECTL_FALSO_FALHA=f"pytstop-billing:{verbo}", ESPERA_JOB="5"
    )

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
        # O Job que falha para a espera na hora, sem esperar o prazo todo.
        assert "[billing-service] job.batch/billing-inicializacao failed" in (
            processo.stdout
        )
    # Lista vazia diz qual; com erro do cluster, so o erro dele.
    for sem, mensagem in SEM_RECURSO.items():
        assert (mensagem in processo.stdout) == (verbo == sem)
    if verbo == "secret":
        assert (
            "[billing-service] Secrets rabbitmq and billing-mongo are missing in "
            "pytstop-billing: run make deploy first"
        ) in processo.stdout
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


FORMAS_DA_IMAGEM = pytest.mark.parametrize(
    "forma",
    ["", "lista:", "aspas:", "volume:"],
    ids=["chave", "primeira-chave", "aspas", "volume-de-imagem"],
)


def copia_da_plataforma(tmp_path: Path, readme: str) -> Path:
    """Uma copia do script e dos leitores de imagem ao lado do README dado."""
    plataforma = tmp_path / "plataforma"
    (plataforma / "scripts" / "ci").mkdir(parents=True)
    copia = plataforma / "scripts" / "ci" / SCRIPT.name
    shutil.copy(SCRIPT, copia)
    for leitor in SCRIPT.parent.glob("imagens-*.sh"):
        shutil.copy(leitor, copia.with_name(leitor.name))
    (plataforma / "README.md").write_text(readme, encoding="utf-8")
    return copia


@FORMAS_DA_IMAGEM
@pytest.mark.parametrize(
    "imagem",
    [
        "busybox:1.37",
        "postgres",
        "postgres:16.4",
        "pytstop-os-service:dev",
        "evil.example/x:latest",
        "kong/kong",
        "123",
    ],
    ids=[
        "outra-imagem",
        "sem-tag",
        "outra-versao",
        "imagem-de-outro-servico",
        "registry-de-terceiro",
        "chart-citado-na-linha-do-kong",
        "so-digitos",
    ],
)
def test_imagem_fora_da_tabela_de_versoes_para_antes_de_tudo(
    implantacao: Implantacao, imagem: str, forma: str
) -> None:
    # Container sem args, command nem env: o kustomize abre o item com o image:.
    dir_overlay = implantacao.dirs["billing-service"] / "k8s" / "overlays" / "kind-ci"
    (dir_overlay / "imagens.txt").write_text(
        f"pytstop-billing-service {DE_TERCEIROS['billing-service']} {forma}{imagem}\n"
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


@FORMAS_DA_IMAGEM
def test_imagem_da_tabela_passa_em_qualquer_forma_em_que_o_kustomize_a_emite(
    implantacao: Implantacao, forma: str
) -> None:
    dir_overlay = implantacao.dirs["billing-service"] / "k8s" / "overlays" / "kind-ci"
    (dir_overlay / "imagens.txt").write_text(
        f"pytstop-billing-service {DE_TERCEIROS['billing-service']} "
        f"{forma}postgres:16.15\n"
    )

    processo = implantacao.do_cd()

    assert processo.returncode == 0, processo.stderr


def test_nome_so_de_digitos_entre_aspas_vale_se_esta_na_tabela(
    implantacao: Implantacao, tmp_path: Path
) -> None:
    # O kustomize emite `image: "123"` para o nome so de digitos: sem as aspas
    # tiradas, a guarda leria a imagem `"123"` e a reprovaria.
    imagens = {i for lista in DE_TERCEIROS.values() for i in lista.split()}
    linhas = "".join(f"| item | `{imagem}` | serve |\n" for imagem in sorted(imagens))
    implantacao.script = copia_da_plataforma(
        tmp_path,
        "| Componente | Versão | Para que serve |\n|---|---|---|\n"
        + linhas
        + "| digitos | `123` | serve |\n",
    )
    dir_overlay = implantacao.dirs["billing-service"] / "k8s" / "overlays" / "kind-ci"
    (dir_overlay / "imagens.txt").write_text(
        f"pytstop-billing-service {DE_TERCEIROS['billing-service']} aspas:123\n"
    )

    processo = implantacao.do_cd()

    assert processo.returncode == 0, processo.stderr


def test_so_a_tabela_de_versoes_vale_como_lista_de_imagens(
    implantacao: Implantacao, tmp_path: Path
) -> None:
    # README de mentira, ao lado de uma copia do script: a tabela tem as imagens
    # de terceiros dos tres servicos menos a postgres:16.15, que so aparece na
    # prosa e na segunda coluna de outra tabela, depois da de versoes, como o
    # `postgres` do superusuario no README de verdade.
    imagens = {i for lista in DE_TERCEIROS.values() for i in lista.split()}
    linhas = "".join(
        f"| item | `{imagem}` | para que serve |\n"
        for imagem in sorted(imagens - {"postgres:16.15"})
    )
    implantacao.script = copia_da_plataforma(
        tmp_path,
        "| Componente | Versão | Para que serve |\n|---|---|---|\n"
        + linhas
        + "\nO banco roda `postgres:16.15`.\n\n"
        "| Item | Outra tabela |\n|---|---|\n"
        "| a | `postgres:16.15` |\n",
    )

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


def test_imagens_do_readme_sao_so_o_primeiro_trecho_da_coluna_versao(
    tmp_path: Path,
) -> None:
    plataforma = tmp_path / "plataforma"
    (plataforma / "scripts" / "ci").mkdir(parents=True)
    leitor = plataforma / "scripts" / "ci" / LEITOR_DO_README.name
    shutil.copy(LEITOR_DO_README, leitor)
    (plataforma / "README.md").write_text(
        "O banco roda `postgres:16.15` no cluster.\n\n"
        "| Componente | Versão | Para que serve |\n|---|---|---|\n"
        "| Kong | `kong:3.9.3` (chart `kong/kong` 3.4.1) | `fora/da-coluna:1` |\n"
        "| Sem imagem | 1.2.3 | `papel` |\n"
        "| Mailpit | `axllent/mailpit:v1.31.4` | - |\n\n"
        "| Item | Outra tabela |\n|---|---|\n"
        "| a | `postgres:16.15` |\n",
        encoding="utf-8",
    )

    processo = subprocess.run(  # noqa: S603  # nosec B603
        [str(leitor)], capture_output=True, text=True, check=True, timeout=30
    )

    assert processo.stdout.split() == ["kong:3.9.3", "axllent/mailpit:v1.31.4"]


def tags_dos_builds(implantacao: Implantacao) -> dict[str, str]:
    """A tag de cada imagem construida, na ultima chamada do docker por servico."""
    tags: dict[str, str] = {}
    for build in implantacao.chamadas("docker"):
        args = build["args"]
        ref = args[args.index("-t") + 1]
        git_sha = args[args.index("--build-arg") + 1].removeprefix("GIT_SHA=")
        assert ref.split(":")[1] == git_sha
        tags[ref.split(":")[0].removeprefix("pytstop-")] = git_sha
    return tags


def test_arvore_suja_vira_tag_sujo_com_o_hash_e_o_aviso(
    implantacao: Implantacao,
) -> None:
    dir_ = implantacao.dirs["billing-service"]
    (dir_ / "src.py").write_text("print('a')\n")
    commit = sha(dir_)

    processo = implantacao.do_cd()

    assert processo.returncode == 0, processo.stderr
    tags = tags_dos_builds(implantacao)
    assert re.fullmatch(f"{commit}-sujo-[0-9a-f]{{12}}", tags["billing-service"])
    # A arvore limpa do outro vizinho segue com o commit puro.
    assert tags["execution-service"] == sha(implantacao.dirs["execution-service"])
    assert f"uncommitted changes in {dir_}; image tag {tags['billing-service']}" in (
        processo.stderr
    )
    kubectl = implantacao.chamadas("kubectl")
    novas = {
        yaml.safe_load(c["kustomization"])["images"][0]["newTag"]
        for c in kubectl
        if "kustomization" in c
    }
    assert tags["billing-service"] in novas


def test_tag_sujo_muda_com_o_codigo_e_repete_com_o_mesmo_codigo(
    implantacao: Implantacao,
) -> None:
    dir_ = implantacao.dirs["billing-service"]
    tags = []
    for conteudo in ("a", "b", "b"):
        (dir_ / "src.py").write_text(conteudo)
        assert implantacao.do_cd().returncode == 0
        tags.append(tags_dos_builds(implantacao)["billing-service"])

    assert tags[0] != tags[1]
    assert tags[1] == tags[2]


def test_arquivo_ignorado_nao_suja_a_arvore(implantacao: Implantacao) -> None:
    dir_ = implantacao.dirs["billing-service"]
    (dir_ / ".gitignore").write_text("cache/\n")
    git("add", "-A", cwd=dir_)
    git("commit", "-q", "-m", "ignora", cwd=dir_)
    (dir_ / "cache").mkdir()
    (dir_ / "cache" / "x").write_text("x")

    processo = implantacao.do_cd()

    assert processo.returncode == 0, processo.stderr
    assert tags_dos_builds(implantacao)["billing-service"] == sha(dir_)
    assert "uncommitted" not in processo.stderr


def test_arvore_suja_nao_mexe_no_indice_do_checkout(implantacao: Implantacao) -> None:
    dir_ = implantacao.dirs["billing-service"]
    (dir_ / "src.py").write_text("print('a')\n")

    assert implantacao.do_cd().returncode == 0

    assert git("status", "--porcelain", cwd=dir_) == "?? src.py"


# git falso: falha no comando que GIT_FALSO_FALHA nomeia (status, add ou
# write-tree) e repassa os outros ao git de verdade (GIT_REAL).
GIT_FALSO = r"""
import os
import sys

if os.environ["GIT_FALSO_FALHA"] in sys.argv:
    sys.exit("fatal: unable to read the working tree")
os.execv(os.environ["GIT_REAL"], ["git", *sys.argv[1:]])
"""


@pytest.mark.parametrize("comando", ["status", "add", "write-tree"])
def test_arvore_que_o_git_nao_le_para_antes_de_construir_em_vez_de_virar_tag_vazia(
    implantacao: Implantacao, comando: str
) -> None:
    # Sem o status, a arvore suja pareceria limpa; sem o add ou o write-tree, a
    # tag sairia do hash da arvore vazia, igual para qualquer codigo.
    dir_ = implantacao.dirs["billing-service"]
    (dir_ / "src.py").write_text("print('a')\n")
    falso = implantacao.tmp / "bin" / "git"
    falso.write_text(f"#!{sys.executable}\n{GIT_FALSO}", encoding="utf-8")
    falso.chmod(0o755)

    processo = implantacao.do_cd(GIT_FALSO_FALHA=comando, GIT_REAL=GIT)

    assert processo.returncode == 1
    assert (
        f"billing-service (commit {sha(dir_)}): could not hash the working tree "
        f"of {dir_}"
    ) in processo.stderr
    assert "uncommitted changes" not in processo.stderr
    assert implantacao.chamadas("docker") == []
    assert implantacao.chamadas("kind") == []
    assert implantacao.chamadas("kubectl") == []


# Prazo de cada chamada do kubectl, por verbo, com os padroes do script: 120 s
# nas comuns e, nas esperas, o --timeout (180 s do banco, 300 s dos
# Deployments) mais 120 s. O Job e lido de 2 em 2 s, cada leitura com 120 s.
def prazos_do_script(
    banco: int, deployment: int, comum: int
) -> dict[str, tuple[str, str | None]]:
    return {
        "delete job": (str(comum), "--timeout=60s"),
        "apply --server-side": (str(comum), None),
        "get statefulset": (str(comum), None),
        "rollout statefulset": (str(banco + comum), f"--timeout={banco}s"),
        "get secret": (str(comum), None),
        "get job": (str(comum), None),
        "poll job": (str(comum), None),
        "get deployment": (str(comum), None),
        "rollout deployment": (str(deployment + comum), f"--timeout={deployment}s"),
    }


def verbo_com_prazo(chamada: list[str]) -> tuple[str, tuple[str, str | None]]:
    """O verbo do kubectl de uma chamada do timeout falso e o prazo dela."""
    prazo, args = chamada[0], chamada[chamada.index("kubectl") + 1 :]
    resto = args[4:] if args[2] == "-n" else args[2:]
    verbo = " ".join(resto[:2])
    if resto[0] == "get" and resto[1].startswith("job.batch/"):
        verbo = "poll job"
    elif resto[0] == "rollout":
        verbo = "rollout " + resto[2].split("/")[0].split(".")[0]
    ultimo = args[-1] if args[-1].startswith("--timeout=") else None
    return verbo, (prazo, ultimo)


@pytest.mark.parametrize(
    ("ambiente", "prazos"),
    [
        ({}, (900, 300, 120, 180, 300, 300)),
        (
            {
                "PRAZO_BUILD": "7",
                "PRAZO_CARGA": "8",
                "PRAZO_KUBECTL": "9",
                "ESPERA_BANCO": "10",
                "ESPERA_JOB": "11",
                "ESPERA_DEPLOYMENT": "12",
            },
            (7, 8, 9, 10, 11, 12),
        ),
    ],
    ids=["padroes", "variaveis-de-ambiente"],
)
def test_todo_comando_que_pode_pendurar_roda_com_prazo(
    implantacao: Implantacao,
    ambiente: dict[str, str],
    prazos: tuple[int, int, int, int, int, int],
) -> None:
    build, carga, comum, banco, _job, deployment = prazos
    timeout = implantacao.tmp / "bin" / "timeout"
    timeout.write_text(f"#!{sys.executable}\n{TIMEOUT_FALSO}", encoding="utf-8")
    timeout.chmod(0o755)

    processo = implantacao.do_cd(**ambiente)

    assert processo.returncode == 0, processo.stderr
    chamadas = implantacao.chamadas("timeout")
    # docker build e kind load: o prazo e o primeiro argumento do timeout.
    assert sorted(c[0] for c in chamadas if c[1] == "docker") == [str(build)] * 2
    assert sorted(c[0] for c in chamadas if c[1] == "kind") == [str(carga)] * 3
    kubectl = [c for c in chamadas if c[1] == "kubectl"]
    esperado = prazos_do_script(banco, deployment, comum)
    # Cada namespace faz as dez chamadas, e nenhuma fica sem prazo.
    assert sorted(verbo_com_prazo(c) for c in kubectl) == sorted(
        [(verbo, prazo) for verbo, prazo in esperado.items() for _ in SERVICOS]
        + [("rollout deployment", esperado["rollout deployment"])] * len(SERVICOS)
    )
    assert len(kubectl) == 10 * len(SERVICOS)


@pytest.mark.parametrize(
    ("falha", "pendura"),
    [
        *((None, verbo) for verbo in ATE_A_FALHA if verbo not in SEM_RECURSO),
        # O log do Job, lido depois da falha dele, tambem tem prazo.
        ("pytstop-billing:job", "logs"),
    ],
    ids=[*(v for v in ATE_A_FALHA if v not in SEM_RECURSO), "logs-do-job"],
)
def test_chamada_ao_cluster_pendurada_estoura_o_prazo_e_nomeia_o_servico(
    implantacao: Implantacao, falha: str | None, pendura: str
) -> None:
    inicio = time.monotonic()

    processo = implantacao.do_cd(
        KUBECTL_FALSO_PENDURA=f"pytstop-billing:{pendura}",
        KUBECTL_FALSO_FALHA=falha or "",
        PRAZO_KUBECTL="1",
        ESPERA_BANCO="1",
        ESPERA_JOB="1",
        ESPERA_DEPLOYMENT="1",
    )

    assert time.monotonic() - inicio < 60
    assert processo.returncode == 1
    commit = sha(implantacao.dirs["billing-service"])
    assert f"deploy failed: billing-service (commit {commit})" in processo.stderr
    assert re.search(r"\[billing-service\] kubectl .* exceeded [12]s", processo.stdout)
    for ns in ("pytstop-os", "pytstop-execucao"):
        assert verbos(implantacao.chamadas("kubectl"), ns).count("rollout status") == 3


def test_build_pendurado_estoura_o_prazo_e_para_antes_do_kind(
    implantacao: Implantacao,
) -> None:
    processo = implantacao.do_cd(
        DOCKER_FALSO_PENDURA="execution-service", PRAZO_BUILD="1"
    )

    assert processo.returncode == 1
    commit = sha(implantacao.dirs["execution-service"])
    assert (
        f"execution-service (commit {commit}): docker build of "
        f"pytstop-execution-service:{commit} exceeded 1s"
    ) in processo.stderr
    assert (
        f"docker build failed: execution-service (commit {commit})" in processo.stderr
    )
    assert implantacao.chamadas("kind") == []
    assert implantacao.chamadas("kubectl") == []


def test_kind_load_pendurado_estoura_o_prazo_antes_de_chamar_o_cluster(
    implantacao: Implantacao,
) -> None:
    processo = implantacao.do_cd(KIND_FALSO="pendura", PRAZO_CARGA="1")

    assert processo.returncode == 1
    commit = sha(implantacao.dirs["os-service"])
    assert (
        f"os-service (commit {commit}): kind load of {REF_DO_CD} exceeded 1s"
        in processo.stderr
    )
    assert implantacao.chamadas("kubectl") == []
    for dir_ in implantacao.dirs.values():
        assert not (dir_ / "k8s" / "overlays" / "execucao").exists()


def test_kind_load_que_falha_para_antes_do_cluster_e_apaga_o_overlay(
    implantacao: Implantacao,
) -> None:
    processo = implantacao.do_cd(KIND_FALSO="falha")

    assert processo.returncode == 1
    commit = sha(implantacao.dirs["os-service"])
    assert f"os-service (commit {commit}): kind load of {REF_DO_CD} failed" in (
        processo.stderr
    )
    assert implantacao.chamadas("kubectl") == []
    for dir_ in implantacao.dirs.values():
        assert not (dir_ / "k8s" / "overlays" / "execucao").exists()


def test_kustomize_que_falha_para_antes_de_construir(implantacao: Implantacao) -> None:
    processo = implantacao.do_cd(KUSTOMIZE_FALSO_FALHA="1")

    assert processo.returncode == 1
    commit = sha(implantacao.dirs["os-service"])
    assert (
        f"os-service (commit {commit}): kubectl kustomize k8s/overlays/kind-ci failed"
        in processo.stderr
    )
    assert implantacao.chamadas("docker") == []
    assert implantacao.chamadas("kind") == []


def test_diretorio_sem_git_para_antes_de_tudo(
    implantacao: Implantacao, tmp_path: Path
) -> None:
    sem_git = tmp_path / "sem-git"
    sem_git.mkdir()
    implantacao.dirs["billing-service"] = sem_git

    processo = implantacao.do_cd()

    assert processo.returncode == 1
    assert f"billing-service: {sem_git} is not a git checkout" in processo.stderr
    assert implantacao.chamadas("docker") == []
    assert implantacao.chamadas("kind") == []


def test_job_que_nao_completa_no_prazo_mostra_o_log_e_nomeia_o_servico(
    implantacao: Implantacao,
) -> None:
    inicio = time.monotonic()

    processo = implantacao.do_cd(
        KUBECTL_FALSO_JOB_PENDENTE="pytstop-billing", ESPERA_JOB="3"
    )

    # O SECONDS do bash conta segundos inteiros: 3 s de espera podem ser 2 s e pouco.
    assert time.monotonic() - inicio >= 2
    assert processo.returncode == 1
    commit = sha(implantacao.dirs["billing-service"])
    assert f"deploy failed: billing-service (commit {commit})" in processo.stderr
    assert (
        "[billing-service] job.batch/billing-inicializacao not complete after 3s"
        in processo.stdout
    )
    assert (
        "[billing-service] migration log of job.batch/billing-inicializacao"
        in processo.stdout
    )
    verbos_billing = verbos(implantacao.chamadas("kubectl"), "pytstop-billing")
    assert verbos_billing.count("poll job") >= 2
    assert verbos_billing[-1] == "logs job.batch/billing-inicializacao"
    # Os outros namespaces seguem ate o fim.
    for ns in ("pytstop-os", "pytstop-execucao"):
        assert verbos(implantacao.chamadas("kubectl"), ns).count("rollout status") == 3


def test_tar_que_nao_tem_a_ref_de_imagem_para_antes_de_tudo(
    implantacao: Implantacao,
) -> None:
    ref = "ghcr.io/fiap/pytstop-os-service:outra"
    implantacao.imagem = ref

    processo = implantacao.do_cd()

    assert processo.returncode == 1
    commit = sha(implantacao.dirs["os-service"])
    assert (
        f"os-service (commit {commit}): {implantacao.tar} does not hold the image {ref}"
        in processo.stderr
    )
    assert implantacao.chamadas("docker") == []
    assert implantacao.chamadas("kind") == []
    assert implantacao.chamadas("kubectl") == []


def test_tar_inexistente_para_antes_de_tudo(
    implantacao: Implantacao, tmp_path: Path
) -> None:
    inexistente = tmp_path / "nao-existe.tar"
    implantacao.tar = inexistente

    processo = implantacao.do_cd()

    assert processo.returncode == 1
    assert f"os-service: {inexistente} not found" in processo.stderr
    assert implantacao.chamadas("docker") == []
    assert implantacao.chamadas("kubectl") == []


def test_registry_com_porta_e_tag_so_de_digitos_no_overlay_gerado(
    implantacao: Implantacao, tmp_path: Path
) -> None:
    ref = "localhost:5000/pytstop-os-service:20261012"
    implantacao.tar = faz_tar(tmp_path / "porta.tar", ref)
    implantacao.imagem = ref

    processo = implantacao.do_cd()

    assert processo.returncode == 0, processo.stderr
    overlays = [
        yaml.safe_load(c["kustomization"])
        for c in implantacao.chamadas("kubectl")
        if "kustomization" in c
    ]
    (do_os,) = (o for o in overlays if o["images"][0]["name"] == "pytstop-os-service")
    # newName vai ate a ultima barra-e-dois-pontos (a porta e do registry), e a
    # tag de digitos entra como texto, nao como numero do YAML.
    assert do_os["images"] == [
        {
            "name": "pytstop-os-service",
            "newName": "localhost:5000/pytstop-os-service",
            "newTag": "20261012",
        }
    ]


RAIZ = SCRIPT.parents[2]


def test_mapa_servico_namespace_dos_scripts_e_do_makefile_concorda() -> None:
    # O mapa vive em cada script (e no Makefile): acrescentar um servico muda
    # todos, e este teste reprova o que ficar para tras.
    implantar = dict(
        re.findall(r"(\w+-service)\) echo (pytstop-\w+) ;;", SCRIPT.read_text())
    )
    smoke = dict(
        re.findall(
            r'(\w+-service)\) echo "(pytstop-\w+) ',
            SCRIPT.with_name("smoke-servicos.sh").read_text(),
        )
    )
    makefile = re.search(
        r"^NAMESPACES_SERVICOS := (.*)$", (RAIZ / "Makefile").read_text(), re.MULTILINE
    )
    assert makefile is not None

    assert implantar == smoke == SERVICOS
    assert set(makefile.group(1).split()) == set(SERVICOS.values())


def test_secret_do_banco_de_cada_namespace_e_o_da_tabela_do_readme() -> None:
    no_script = dict(
        re.findall(r"(pytstop-\w+)\) echo ([\w-]+) ;;", SCRIPT.read_text())
    )
    linha = next(
        linha
        for linha in (RAIZ / "README.md").read_text().splitlines()
        if linha.startswith("| Secret com as senhas do banco")
    )

    assert no_script == {
        "pytstop-os": "os-postgres",
        "pytstop-billing": "billing-mongo",
        "pytstop-execucao": "execucao-postgres",
    }
    assert all(f"`{nome}`" in linha for nome in no_script.values())


def test_log_do_job_que_falha_vem_dos_dois_containers_com_50_linhas(
    implantacao: Implantacao,
) -> None:
    processo = implantacao.do_cd(KUBECTL_FALSO_FALHA="pytstop-billing:job")

    assert processo.returncode == 1
    logs = [
        chamada["args"]
        for chamada in implantacao.chamadas("kubectl")
        if "logs" in chamada["args"]
    ]
    assert logs == [
        [
            "--context",
            "kind-pytstop-p4",
            "-n",
            "pytstop-billing",
            "logs",
            "job.batch/billing-inicializacao",
            "--all-containers",
            "--tail=50",
        ]
    ]


@pytest.mark.parametrize("falha", [False, True], ids=["sucesso", "falha"])
def test_nao_deixa_temporario_para_tras(
    implantacao: Implantacao, tmp_path: Path, falha: bool
) -> None:
    temporarios = tmp_path / "temporarios"
    temporarios.mkdir()
    # Sujo, para o indice temporario do hash da arvore tambem existir.
    (implantacao.dirs["billing-service"] / "src.py").write_text("print('a')\n")

    processo = implantacao.do_cd(
        TMPDIR=str(temporarios),
        KUBECTL_FALSO_FALHA="pytstop-billing:apply" if falha else "",
    )

    assert processo.returncode == (1 if falha else 0), processo.stderr
    # O temporario nasceu sob o TMPDIR (o log de cada build ja estava la quando
    # o docker rodou) e nao sobrou nada.
    builds = implantacao.chamadas("docker")
    assert len(builds) == 2
    assert all(build["tmp"] >= 1 for build in builds)
    assert list(temporarios.iterdir()) == []


def test_tar_no_formato_oci_tem_a_ref_no_index_json(
    implantacao: Implantacao, tmp_path: Path
) -> None:
    # Um arquivo de buildx/OCI traz o nome da imagem no index.json, sem manifest.json.
    oci = tmp_path / "oci.tar"
    dados = json.dumps(
        {"manifests": [{"annotations": {"io.containerd.image.name": REF_DO_CD}}]}
    ).encode()
    with tarfile.open(oci, "w") as arquivo:
        info = tarfile.TarInfo("index.json")
        info.size = len(dados)
        arquivo.addfile(info, io.BytesIO(dados))
    implantacao.tar = oci

    processo = implantacao.do_cd()

    assert processo.returncode == 0, processo.stderr


def test_ref_so_vale_inteira_no_manifest_do_tar(
    implantacao: Implantacao, tmp_path: Path
) -> None:
    # A ref pedida e prefixo da gravada: nao e a mesma imagem.
    implantacao.tar = faz_tar(tmp_path / "maior.tar", f"{REF_DO_CD}-rc1")

    processo = implantacao.do_cd()

    assert processo.returncode == 1
    assert f"does not hold the image {REF_DO_CD}" in processo.stderr


@pytest.mark.parametrize(
    ("ambiente", "segundos"),
    [({}, 300), ({"ESPERA_JOB": "11"}, 11)],
    ids=["padrao", "env"],
)
def test_espera_do_job_diz_ate_quando(
    implantacao: Implantacao, ambiente: dict[str, str], segundos: int
) -> None:
    processo = implantacao.do_cd(**ambiente)

    assert processo.returncode == 0, processo.stderr
    job = "job.batch/billing-inicializacao"
    assert f"[billing-service] waiting for {job} (up to {segundos}s)" in processo.stdout
