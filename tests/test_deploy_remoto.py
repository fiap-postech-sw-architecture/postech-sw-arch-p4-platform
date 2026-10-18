"""scripts/ci/deploy-remoto.sh com kubectl falso.

O falso e o do teste do implantar-servicos.sh (as mesmas funcoes de cluster,
em scripts/ci/implantacao.sh), mais o kustomize que renderiza o overlay
gerado. O teste confere a chamada do job deploy-remote do CD (a imagem com
tag e digest) para cada servico: o overlay gerado parte do overlay pedido e
fixa a imagem pelo digest, a ordem do namespace, o contexto do argumento em
toda chamada (nunca o KUBE_CONTEXT do ambiente), os prazos e o overlay gerado
apagado no fim; que falha no cluster nomeia o servico; que checkout errado
(sem o overlay, de outro repositorio, overlay gerado ja existente) para antes
do cluster; e os argumentos recusados.
"""

from __future__ import annotations

import json
import os
import re

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
    KUBECTL_FALSO,
    SEM_RECURSO,
    SERVICOS,
    TIMEOUT_FALSO,
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

# O kustomize do falso renderiza o overlay gerado como o real: com a imagem
# trocada pelo nome e pelo digest dele. KUSTOMIZE_FALSO_SEM_A_IMAGEM simula o
# checkout de outro repositorio (a troca nao casa nada), e
# KUSTOMIZE_FALSO_FALHA, um overlay que nao renderiza. O resto das chamadas
# vai para o kubectl falso do teste do implantar-servicos.sh.
KUBECTL_REMOTO = (
    r"""
import json
import os
import sys
from pathlib import Path

import yaml

if sys.argv[1:2] == ["kustomize"]:
    with (Path(os.environ["FALSOS"]) / "kustomize.jsonl").open("a") as log:
        log.write(json.dumps(sys.argv[1:]) + "\n")
    if os.environ.get("KUSTOMIZE_FALSO_FALHA"):
        sys.exit("error: accumulating resources")
    gerado = yaml.safe_load((Path(sys.argv[2]) / "kustomization.yaml").read_text())
    imagem = gerado["images"][0]
    if os.environ.get("KUSTOMIZE_FALSO_SEM_A_IMAGEM"):
        print("        image: pytstop-outro-servico")
    else:
        print(f"        image: {imagem['newName']}@{imagem['digest']}")
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
        self.env = os.environ | {
            "PATH": f"{binarios}{os.pathsep}{os.environ['PATH']}",
            "FALSOS": str(tmp_path),
            "KUBE_CONTEXT": "contexto-do-ambiente",
        }

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
            [str(SCRIPT), *args],
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
        (com("servico", "web-service"), "unknown service web-service"),
        (
            com("imagem", f"{REGISTRY}/pytstop-os-service:{COMMIT}"),
            "needs <ref>@sha256",
        ),
        (com("imagem", f"pytstop-os-service@{DIGEST[:-1]}"), "needs <ref>@sha256"),
        (
            com("imagem", f"pytstop-os-service@sha256:{DIGEST[7:].upper()}"),
            "needs <ref>@sha256",
        ),
        (com("imagem", "pytstop-os-service@sha512:" + "0" * 128), "needs <ref>@sha256"),
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
        "servico-desconhecido",
        "imagem-sem-digest",
        "digest-curto",
        "digest-em-maiusculas",
        "outro-algoritmo",
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


def test_fora_do_checkout_do_servico_para_antes_de_tudo(remoto: Remoto) -> None:
    processo = remoto.do_cd("os-service", remoto.tmp)

    assert processo.returncode == 1
    assert (
        f"os-service: no k8s/overlays/k3s/kustomization.yaml in {remoto.tmp.resolve()}"
        " (run from the checkout of os-service)"
    ) in processo.stderr
    assert remoto.chamadas("kustomize") == []
    assert remoto.chamadas("kubectl") == []


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


def test_sem_os_secrets_da_plataforma_pede_o_make_deploy(remoto: Remoto) -> None:
    dir_ = remoto.checkout("billing-service")

    processo = remoto.do_cd(
        "billing-service", dir_, KUBECTL_FALSO_FALHA="pytstop-billing:secret"
    )

    assert processo.returncode == 1
    assert (
        "Secrets rabbitmq and billing-mongo are missing in pytstop-billing:"
        " run make deploy first"
    ) in processo.stderr


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
    # So o kubectl do cluster: o kustomize renderiza local, sem prazo.
    assert {chamada[1] for chamada in chamadas} == {"kubectl"}
    esperado = prazos_do_script(banco, deployment, comum)
    assert sorted(verbo_com_prazo(chamada) for chamada in chamadas) == sorted(
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
