"""scripts/ci/deploy-remoto.sh com kubectl falso.

O falso e o do teste do implantar-servicos.sh (as mesmas funcoes de cluster,
em scripts/ci/implantacao.sh), mais o kustomize que renderiza o overlay
gerado. O teste confere a chamada do job deploy-remote do CD (a imagem com
tag e digest) para cada servico: o overlay gerado parte do overlay pedido e
fixa a imagem pelo digest, a ordem do namespace, o contexto do argumento em
toda chamada (nunca o KUBE_CONTEXT do ambiente), os prazos e o overlay gerado
apagado no fim; que falha no cluster nomeia o servico; que checkout errado
(sem o overlay, de outro repositorio, overlay gerado ja existente) e render
com objeto fora do namespace do servico param antes do cluster; os argumentos
recusados; e, com o kubectl kustomize de verdade, que o render real passa nas
guardas com a imagem fixada pelo digest.
"""

from __future__ import annotations

import json
import os
import re
import shutil

# subprocess so roda o script do repositorio, sem shell.
import subprocess  # nosec B404
import sys
import time
from pathlib import Path
from typing import Any

import pytest
import yaml
from test_implantar_servicos import (
    ATE_A_FALHA,
    COMUM,
    KUBECTL_FALSO,
    SEM_RECURSO,
    SERVICOS,
    TIMEOUT_FALSO,
    ambiente_sem_o_que_o_script_le,
    prazos_do_script,
    verbo_com_prazo,
    verbos,
)

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ci" / "deploy-remoto.sh"
REGISTRY = "ghcr.io/fiap-postech-sw-architecture"
COMMIT = "5f2a9c1e" * 5
DIGEST = "sha256:" + "0123456789abcdef" * 4
CONTEXTO = "cluster-remoto"
GERADO = Path("k8s") / "overlays" / "execucao"
KUBECTL_REAL = shutil.which("kubectl")

# O kustomize do falso renderiza o overlay gerado como o real: o Namespace do
# servico e um Deployment nele, com a imagem trocada pelo nome e pelo digest
# (o namespace sai do caminho do checkout, <tmp>/<namespace>/repo).
# KUSTOMIZE_FALSO_SEM_A_IMAGEM simula o checkout de outro repositorio (a troca
# nao casa nada), KUSTOMIZE_FALSO_FALHA, um overlay que nao renderiza, e
# KUSTOMIZE_FALSO_A_MAIS, documentos acrescentados ao render. O resto das
# chamadas vai para o kubectl falso do teste do implantar-servicos.sh.
# Com KUBECTL_REAL, o kustomize e o de verdade, e o render fica tambem em
# render.yaml.
KUBECTL_REMOTO = (
    r"""
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

if sys.argv[1:2] == ["kustomize"]:
    falsos = Path(os.environ["FALSOS"])
    with (falsos / "kustomize.jsonl").open("a") as log:
        log.write(json.dumps(sys.argv[1:]) + "\n")
    if os.environ.get("KUBECTL_REAL"):
        real = subprocess.run([os.environ["KUBECTL_REAL"], *sys.argv[1:]],
                              capture_output=True, text=True)
        (falsos / "render.yaml").write_text(real.stdout)
        sys.stdout.write(real.stdout)
        sys.stderr.write(real.stderr)
        sys.exit(real.returncode)
    if os.environ.get("KUSTOMIZE_FALSO_FALHA"):
        sys.exit("error: accumulating resources")
    gerado = yaml.safe_load((Path(sys.argv[2]) / "kustomization.yaml").read_text())
    imagem = gerado["images"][0]
    if os.environ.get("KUSTOMIZE_FALSO_SEM_A_IMAGEM"):
        trocada = "pytstop-outro-servico"
    else:
        trocada = f"{imagem['newName']}@{imagem['digest']}"
    ns = Path.cwd().parts[-2]
    print(f"apiVersion: v1\nkind: Namespace\nmetadata:\n  name: {ns}\n---")
    print("apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: api")
    print(f"  namespace: {ns}\nspec:\n  template:\n    spec:\n      containers:")
    print(f"      - image: {trocada}\n        name: api")
    print(os.environ.get("KUSTOMIZE_FALSO_A_MAIS", ""), end="")
    sys.exit(0)
"""
    + KUBECTL_FALSO
)


class Remoto:
    """kubectl falso no PATH e o checkout de cada servico no tmp_path."""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp = tmp_path
        binarios = tmp_path / "bin"
        binarios.mkdir()
        kubectl = binarios / "kubectl"
        kubectl.write_text(f"#!{sys.executable}\n{KUBECTL_REMOTO}", encoding="utf-8")
        kubectl.chmod(0o755)
        # O KUBE_CONTEXT do ambiente nao pode trocar o contexto do argumento.
        self.env = ambiente_sem_o_que_o_script_le() | {
            "PATH": f"{binarios}{os.pathsep}{os.environ['PATH']}",
            "FALSOS": str(tmp_path),
            "KUBE_CONTEXT": "contexto-do-ambiente",
        }
        self.script = SCRIPT

    def checkout(self, servico: str, overlay: str = "k3s") -> Path:
        """O checkout do servico com o overlay. O caminho leva o namespace: o
        kubectl falso o le no apply."""
        dir_ = self.tmp / SERVICOS[servico] / "repo"
        (dir_ / "k8s" / "overlays" / overlay).mkdir(parents=True)
        (dir_ / "k8s" / "overlays" / overlay / "kustomization.yaml").write_text(
            "resources: [../../base]\n", encoding="utf-8"
        )
        return dir_

    def roda(
        self, *args: str, cwd: Path, **ambiente: str
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603  # nosec B603
            [str(self.script), *args],
            cwd=cwd,
            env=self.env | ambiente,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )

    def do_cd(
        self, servico: str, cwd: Path, **ambiente: str
    ) -> subprocess.CompletedProcess[str]:
        """A chamada do job deploy-remote: a imagem do job image com tag e digest."""
        return self.roda(
            "--contexto",
            CONTEXTO,
            "--overlay",
            "k3s",
            "--servico",
            servico,
            "--imagem",
            f"{REGISTRY}/pytstop-{servico}:{COMMIT}@{DIGEST}",
            cwd=cwd,
            **ambiente,
        )

    def chamadas(self, falso: str) -> list[Any]:
        arquivo = self.tmp / f"{falso}.jsonl"
        if not arquivo.exists():
            return []
        return [json.loads(linha) for linha in arquivo.read_text().splitlines()]


@pytest.fixture
def remoto(tmp_path: Path) -> Remoto:
    return Remoto(tmp_path)


def overlay_aplicado(remoto: Remoto) -> Any:
    """O overlay gerado, como o apply o leu."""
    (aplicado,) = [
        c["kustomization"] for c in remoto.chamadas("kubectl") if "kustomization" in c
    ]
    return yaml.safe_load(aplicado)


@pytest.mark.parametrize("servico", SERVICOS)
def test_cd_implanta_pelo_digest_na_ordem_e_apaga_o_overlay(
    remoto: Remoto, servico: str
) -> None:
    ns = SERVICOS[servico]
    dir_ = remoto.checkout(servico)

    processo = remoto.do_cd(servico, dir_)

    assert processo.returncode == 0, processo.stderr
    kubectl = remoto.chamadas("kubectl")
    assert {tuple(chamada["args"][:2]) for chamada in kubectl} == {
        ("--context", CONTEXTO)
    }
    assert {chamada["ns"] for chamada in kubectl} == {ns}
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
    # O overlay pedido com a imagem fixada pelo digest; a tag do CD sai.
    assert overlay_aplicado(remoto) == {
        "apiVersion": "kustomize.config.k8s.io/v1beta1",
        "kind": "Kustomization",
        "resources": ["../k3s"],
        "images": [
            {
                "name": f"pytstop-{servico}",
                "newName": f"{REGISTRY}/pytstop-{servico}",
                "digest": DIGEST,
            }
        ],
    }
    # Renderizado antes do cluster, pelo caminho relativo ao checkout.
    assert remoto.chamadas("kustomize") == [["kustomize", str(GERADO)]]
    assert not (dir_ / GERADO).exists()
    assert processo.stdout.endswith(
        f"deployed: {servico} ({REGISTRY}/pytstop-{servico}@{DIGEST})"
        f" in context {CONTEXTO}\n"
    )


@pytest.mark.parametrize(
    ("imagem", "nome"),
    [
        ("pytstop-os-service", "pytstop-os-service"),
        ("ghcr.io/x/pytstop-os-service", "ghcr.io/x/pytstop-os-service"),
        ("localhost:5000/pytstop-os-service", "localhost:5000/pytstop-os-service"),
        (
            "localhost:5000/x/pytstop-os-service:v1.2",
            "localhost:5000/x/pytstop-os-service",
        ),
    ],
    ids=["sem-registry", "sem-tag", "porta-sem-tag", "porta-e-tag"],
)
def test_so_a_tag_sai_do_nome_e_a_porta_do_registry_fica(
    remoto: Remoto, imagem: str, nome: str
) -> None:
    dir_ = remoto.checkout("os-service")

    processo = remoto.roda(
        "--contexto",
        CONTEXTO,
        "--overlay",
        "k3s",
        "--servico",
        "os-service",
        "--imagem",
        f"{imagem}@{DIGEST}",
        cwd=dir_,
    )

    assert processo.returncode == 0, processo.stderr
    assert overlay_aplicado(remoto)["images"] == [
        {"name": "pytstop-os-service", "newName": nome, "digest": DIGEST}
    ]


def test_o_overlay_pedido_e_a_base_do_overlay_gerado(remoto: Remoto) -> None:
    # Fora do k3s, o padrao do CD: o kind local, por exemplo.
    dir_ = remoto.checkout("os-service", overlay="kind")

    processo = remoto.roda(
        "--contexto",
        "kind-pytstop-p4",
        "--overlay",
        "kind",
        "--servico",
        "os-service",
        "--imagem",
        f"{REGISTRY}/pytstop-os-service@{DIGEST}",
        cwd=dir_,
    )

    assert processo.returncode == 0, processo.stderr
    assert overlay_aplicado(remoto)["resources"] == ["../kind"]
    assert f"{GERADO} = kind with image" in processo.stdout


ARGUMENTOS = {
    "contexto": ["--contexto", CONTEXTO],
    "overlay": ["--overlay", "k3s"],
    "servico": ["--servico", "os-service"],
    "imagem": ["--imagem", f"{REGISTRY}/pytstop-os-service:{COMMIT}@{DIGEST}"],
}


def sem(chave: str) -> list[str]:
    """Os quatro argumentos menos um."""
    return [a for nome, par in ARGUMENTOS.items() if nome != chave for a in par]


def com(chave: str, valor: str) -> list[str]:
    """Os quatro argumentos, um deles com outro valor."""
    return [*sem(chave), f"--{chave}", valor]


@pytest.mark.parametrize(
    ("argumentos", "mensagem"),
    [
        ([], "usage:"),
        *((sem(chave), "usage:") for chave in ARGUMENTOS),
        ([*sem("imagem"), "--imagem"], "usage:"),
        ([*sem(""), "--namespace", "pytstop-os"], "usage:"),
        ([*sem(""), "os-service=."], "usage:"),
        ([*sem(""), "--contexto", "outro"], "--contexto given twice"),
        (
            [*sem(""), "--imagem", f"pytstop-os-service@{DIGEST}"],
            "--imagem given twice",
        ),
        (com("contexto", ""), "--contexto is empty"),
        (com("overlay", ""), "--overlay is empty"),
        # O "#" cortaria o nome no YAML e a quebra de linha acrescentaria um
        # resource; o caminho com ".." existe no checkout e passaria do -f.
        (com("overlay", "k3s #x"), "--overlay needs a plain overlay name"),
        (com("overlay", "k3s\n  - ../../.."), "--overlay needs a plain overlay name"),
        (com("overlay", "../overlays/k3s"), "--overlay needs a plain overlay name"),
        (com("overlay", ".."), "--overlay needs a plain overlay name"),
        (com("servico", "web-service"), "unknown service web-service"),
        (
            com("imagem", f"{REGISTRY}/pytstop-os-service:{COMMIT}"),
            "needs <ref>@sha256",
        ),
        (com("imagem", f"pytstop-os-service@{DIGEST[:-1]}"), "needs <ref>@sha256"),
        (com("imagem", f"pytstop-os-service@{DIGEST}x"), "needs <ref>@sha256"),
        (
            com("imagem", f"pytstop-os-service@sha256:{DIGEST[7:].upper()}"),
            "needs <ref>@sha256",
        ),
        (com("imagem", "pytstop-os-service@sha512:" + "0" * 128), "needs <ref>@sha256"),
        (
            com("imagem", f"pytstop-os-service@sha512:{DIGEST[7:]}"),
            "needs <ref>@sha256",
        ),
        (
            com("imagem", f"pytstop-os-service\n    newTag: latest@{DIGEST}"),
            "needs <ref>@sha256",
        ),
        (
            com("imagem", f"{REGISTRY}/pytstop-billing-service@{DIGEST}"),
            "is not an image of os-service (pytstop-os-service)",
        ),
        (
            com("imagem", f"{REGISTRY}/meu-pytstop-os-service@{DIGEST}"),
            "is not an image of os-service",
        ),
        (
            com("imagem", f"{REGISTRY}/pytstop-os-service-rc@{DIGEST}"),
            "is not an image of os-service",
        ),
    ],
    ids=[
        "nenhum",
        "sem-contexto",
        "sem-overlay",
        "sem-servico",
        "sem-imagem",
        "imagem-sem-valor",
        "opcao-desconhecida",
        "par-do-implantar-servicos",
        "contexto-repetido",
        "imagem-repetida",
        "contexto-vazio",
        "overlay-vazio",
        "overlay-com-cerquilha",
        "overlay-com-quebra-de-linha",
        "overlay-por-caminho",
        "overlay-ponto-ponto",
        "servico-desconhecido",
        "imagem-sem-digest",
        "digest-curto",
        "digest-com-sobra",
        "digest-em-maiusculas",
        "outro-algoritmo",
        "sha512-com-64-hex",
        "quebra-de-linha-no-nome",
        "imagem-de-outro-servico",
        "nome-que-so-termina-igual",
        "nome-com-sufixo",
    ],
)
def test_argumentos_recusados_sem_tocar_no_cluster(
    remoto: Remoto, argumentos: list[str], mensagem: str
) -> None:
    dir_ = remoto.checkout("os-service")

    processo = remoto.roda(*argumentos, cwd=dir_)

    assert processo.returncode == 2
    assert mensagem in processo.stderr
    assert remoto.chamadas("kubectl") == []
    assert remoto.chamadas("kustomize") == []
    assert not (dir_ / GERADO).exists()


@pytest.mark.parametrize(
    "overlay_sem_kustomization",
    [False, True],
    ids=["fora-do-checkout", "diretorio-do-overlay-sem-kustomization"],
)
def test_fora_do_checkout_do_servico_para_antes_de_tudo(
    remoto: Remoto, overlay_sem_kustomization: bool
) -> None:
    cwd = remoto.tmp
    if overlay_sem_kustomization:
        cwd = remoto.tmp / "repo"
        (cwd / "k8s" / "overlays" / "k3s").mkdir(parents=True)

    processo = remoto.do_cd("os-service", cwd)

    assert processo.returncode == 1
    assert (
        f"os-service: no k8s/overlays/k3s/kustomization.yaml in {cwd.resolve()}"
        " (run from the checkout of os-service)"
    ) in processo.stderr
    assert remoto.chamadas("kustomize") == []
    assert remoto.chamadas("kubectl") == []
    assert not (cwd / GERADO).exists()


def test_sem_o_arquivo_comum_para_antes_de_tudo(remoto: Remoto) -> None:
    # Uma copia do script sem o scripts/ci/implantacao.sh ao lado: o source
    # falha e o set -e para ali, em vez de seguir sem as funcoes de cluster.
    copia = remoto.tmp / "plataforma" / "scripts" / "ci" / SCRIPT.name
    copia.parent.mkdir(parents=True)
    shutil.copy(SCRIPT, copia)
    remoto.script = copia
    dir_ = remoto.checkout("os-service")

    processo = remoto.do_cd("os-service", dir_)

    assert processo.returncode == 1
    assert f"{COMUM.name}: No such file or directory" in processo.stderr
    assert remoto.chamadas("kustomize") == []
    assert remoto.chamadas("kubectl") == []
    assert not (dir_ / GERADO).exists()


@pytest.mark.parametrize(
    ("ambiente", "mensagem"),
    [
        (
            {"KUSTOMIZE_FALSO_SEM_A_IMAGEM": "1"},
            (
                "k8s/overlays/k3s in {dir} does not use the image pytstop-os-service"
                " (run from the checkout of os-service)"
            ),
        ),
        ({"KUSTOMIZE_FALSO_FALHA": "1"}, f"kubectl kustomize {GERADO} failed"),
    ],
    ids=["checkout-de-outro-repositorio", "overlay-que-nao-renderiza"],
)
def test_overlay_sem_a_imagem_do_servico_para_antes_do_cluster(
    remoto: Remoto, ambiente: dict[str, str], mensagem: str
) -> None:
    dir_ = remoto.checkout("os-service")

    processo = remoto.do_cd("os-service", dir_, **ambiente)

    assert processo.returncode == 1
    assert f"os-service: {mensagem.format(dir=dir_.resolve())}" in processo.stderr
    assert len(remoto.chamadas("kustomize")) == 1
    assert remoto.chamadas("kubectl") == []
    assert not (dir_ / GERADO).exists()


# Documentos que o render nao pode ter: objeto de outro namespace, objeto sem
# namespace (de cluster) e o Namespace de outro.
FORA_DO_NAMESPACE = {
    "objeto-de-outro-namespace": (
        (
            "---\napiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: x\n"
            "  namespace: pytstop-plataforma\n"
        ),
        "ConfigMap/x",
    ),
    # O namespace do ServiceAccount em subjects nao e o do objeto.
    "objeto-de-cluster": (
        (
            "---\napiVersion: rbac.authorization.k8s.io/v1\n"
            "kind: ClusterRoleBinding\nmetadata:\n  name: admin-do-servico\n"
            "roleRef:\n  name: cluster-admin\nsubjects:\n- kind: ServiceAccount\n"
            "  name: api\n  namespace: pytstop-os\n"
        ),
        "ClusterRoleBinding/admin-do-servico",
    ),
    "namespace-de-outro": (
        "---\napiVersion: v1\nkind: Namespace\nmetadata:\n  name: pytstop-plataforma\n",
        "Namespace/pytstop-plataforma",
    ),
}


@pytest.mark.parametrize(
    ("a_mais", "objeto"), FORA_DO_NAMESPACE.values(), ids=FORA_DO_NAMESPACE
)
def test_render_com_objeto_fora_do_namespace_para_antes_do_cluster(
    remoto: Remoto, a_mais: str, objeto: str
) -> None:
    dir_ = remoto.checkout("os-service")

    processo = remoto.do_cd("os-service", dir_, KUSTOMIZE_FALSO_A_MAIS=a_mais)

    assert processo.returncode == 1
    assert (
        f"os-service: k8s/overlays/k3s renders objects outside pytstop-os: {objeto}\n"
    ) in processo.stderr
    assert remoto.chamadas("kubectl") == []
    assert not (dir_ / GERADO).exists()


def test_overlay_gerado_que_ja_existe_fica_intocado(remoto: Remoto) -> None:
    dir_ = remoto.checkout("os-service")
    (dir_ / GERADO).mkdir()
    (dir_ / GERADO / "kustomization.yaml").write_text("de quem escreveu\n")

    processo = remoto.do_cd("os-service", dir_)

    assert processo.returncode == 1
    assert f"{GERADO} already exists" in processo.stderr
    assert (dir_ / GERADO / "kustomization.yaml").read_text() == "de quem escreveu\n"
    assert remoto.chamadas("kustomize") == []
    assert remoto.chamadas("kubectl") == []


@pytest.mark.parametrize("verbo", ATE_A_FALHA)
def test_falha_no_cluster_nomeia_o_servico_e_apaga_o_overlay(
    remoto: Remoto, verbo: str
) -> None:
    dir_ = remoto.checkout("billing-service")

    processo = remoto.do_cd(
        "billing-service", dir_, KUBECTL_FALSO_FALHA=f"pytstop-billing:{verbo}"
    )

    assert processo.returncode == 1
    assert (
        f"deploy failed: billing-service ({REGISTRY}/pytstop-billing-service@{DIGEST})"
        f" in context {CONTEXTO}"
    ) in processo.stderr
    assert "deployed:" not in processo.stdout
    # Depois da falha, nenhuma chamada a mais.
    assert verbos(remoto.chamadas("kubectl"), "pytstop-billing") == ATE_A_FALHA[verbo]
    if verbo in SEM_RECURSO:
        assert SEM_RECURSO[verbo] in processo.stderr
    assert not (dir_ / GERADO).exists()


AUSENTES = SEM_RECURSO["sem-secret"]
INACESSIVEIS = (
    "cannot read the Secrets rabbitmq and billing-mongo in pytstop-billing"
    " (kubectl error above; the cluster credential may have expired)"
)


@pytest.mark.parametrize(
    ("verbo", "erro", "mensagem", "outra"),
    [
        (
            "sem-secret",
            'Error from server (NotFound): secrets "billing-mongo" not found',
            AUSENTES,
            INACESSIVEIS,
        ),
        ("secret", "error: secret failed in pytstop-billing", INACESSIVEIS, AUSENTES),
    ],
    ids=["ausentes-pedem-o-make-deploy", "inacessiveis-falam-da-credencial"],
)
def test_secrets_da_plataforma_ausentes_ou_inacessiveis(
    remoto: Remoto, verbo: str, erro: str, mensagem: str, outra: str
) -> None:
    dir_ = remoto.checkout("billing-service")

    processo = remoto.do_cd(
        "billing-service", dir_, KUBECTL_FALSO_FALHA=f"pytstop-billing:{verbo}"
    )

    assert processo.returncode == 1
    assert f"{erro}\n{mensagem}\n" in processo.stderr
    assert outra not in processo.stderr


def test_job_que_falha_mostra_o_log_dele(remoto: Remoto) -> None:
    dir_ = remoto.checkout("billing-service")

    processo = remoto.do_cd(
        "billing-service", dir_, KUBECTL_FALSO_FALHA="pytstop-billing:job"
    )

    assert processo.returncode == 1
    assert "job.batch/billing-inicializacao failed" in processo.stderr
    assert "migration log of job.batch/billing-inicializacao" in processo.stderr


@pytest.mark.parametrize(
    ("ambiente", "prazos"),
    [
        ({}, (120, 180, 300, 300)),
        (
            {
                "PRAZO_KUBECTL": "9",
                "ESPERA_BANCO": "10",
                "ESPERA_JOB": "11",
                "ESPERA_DEPLOYMENT": "12",
            },
            (9, 10, 11, 12),
        ),
    ],
    ids=["padroes", "variaveis-de-ambiente"],
)
def test_toda_chamada_ao_cluster_roda_com_prazo(
    remoto: Remoto, ambiente: dict[str, str], prazos: tuple[int, int, int, int]
) -> None:
    comum, banco, job, deployment = prazos
    timeout = remoto.tmp / "bin" / "timeout"
    timeout.write_text(f"#!{sys.executable}\n{TIMEOUT_FALSO}", encoding="utf-8")
    timeout.chmod(0o755)
    dir_ = remoto.checkout("billing-service")

    processo = remoto.do_cd("billing-service", dir_, **ambiente)

    assert processo.returncode == 0, processo.stderr
    chamadas = remoto.chamadas("timeout")
    assert {chamada[1] for chamada in chamadas} == {"kubectl"}
    # O kustomize renderiza local, mas tambem com prazo: um overlay com base
    # remota penduraria ate o timeout do job.
    kustomize = [chamada for chamada in chamadas if chamada[2] == "kustomize"]
    assert kustomize == [[str(comum), "kubectl", "kustomize", str(GERADO)]]
    esperado = prazos_do_script(banco, deployment, comum)
    assert sorted(
        verbo_com_prazo(chamada) for chamada in chamadas if chamada not in kustomize
    ) == sorted(
        [*esperado.items(), ("rollout deployment", esperado["rollout deployment"])]
    )
    job_ = "job.batch/billing-inicializacao"
    assert f"waiting for {job_} (up to {job}s)" in processo.stdout


def test_chamada_pendurada_estoura_o_prazo_e_nomeia_a_chamada(remoto: Remoto) -> None:
    dir_ = remoto.checkout("billing-service")
    inicio = time.monotonic()

    processo = remoto.do_cd(
        "billing-service",
        dir_,
        KUBECTL_FALSO_PENDURA="pytstop-billing:apply",
        PRAZO_KUBECTL="1",
    )

    assert time.monotonic() - inicio < 30
    assert processo.returncode == 1
    assert re.search(r"kubectl apply --server-side -k .* exceeded 1s", processo.stderr)
    assert "deploy failed: billing-service" in processo.stderr
    assert not (dir_ / GERADO).exists()


# A base minima de um servico: o Namespace e um Deployment nele, a imagem com
# tag no initContainer e no container, como nos manifests dos servicos.
BASE_DO_SERVICO = """\
apiVersion: v1
kind: Namespace
metadata:
  name: pytstop-os
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: os-service-api
  namespace: pytstop-os
spec:
  selector:
    matchLabels:
      app: os-service-api
  template:
    metadata:
      labels:
        app: os-service-api
    spec:
      initContainers:
        - name: espera
          image: pytstop-os-service:dev
      containers:
        - name: api
          image: pytstop-os-service:dev
"""


@pytest.mark.skipif(KUBECTL_REAL is None, reason="kubectl is not on the PATH")
@pytest.mark.parametrize(
    ("imagem", "nome"),
    [
        (
            f"{REGISTRY}/pytstop-os-service:{COMMIT}",
            f"{REGISTRY}/pytstop-os-service",
        ),
        (
            "localhost:5000/x/pytstop-os-service:v1.2",
            "localhost:5000/x/pytstop-os-service",
        ),
    ],
    ids=["imagem-do-cd", "registry-com-porta"],
)
def test_render_do_kubectl_kustomize_real_passa_nas_guardas_pelo_digest(
    remoto: Remoto, imagem: str, nome: str
) -> None:
    # O falso fabrica a linha que a guarda procura; aqui, o kustomize de
    # verdade: se o formato do render mudar, este teste avisa antes do deploy.
    dir_ = remoto.checkout("os-service")
    base = dir_ / "k8s" / "base"
    base.mkdir()
    (base / "kustomization.yaml").write_text("resources: [servico.yaml]\n")
    (base / "servico.yaml").write_text(BASE_DO_SERVICO)

    processo = remoto.roda(
        *sem("imagem"),
        "--imagem",
        f"{imagem}@{DIGEST}",
        cwd=dir_,
        KUBECTL_REAL=str(KUBECTL_REAL),
    )

    assert processo.returncode == 0, processo.stderr
    render = list(yaml.safe_load_all((remoto.tmp / "render.yaml").read_text()))
    assert [(d["kind"], d["metadata"].get("namespace")) for d in render] == [
        ("Namespace", None),
        ("Deployment", "pytstop-os"),
    ]
    pod = render[1]["spec"]["template"]["spec"]
    assert [c["image"] for c in pod["initContainers"] + pod["containers"]] == [
        f"{nome}@{DIGEST}"
    ] * 2
