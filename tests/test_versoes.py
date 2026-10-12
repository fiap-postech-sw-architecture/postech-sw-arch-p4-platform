"""scripts/versoes.sh e o leitor de imagens dos manifests que ele divide com o
scripts/ci/implantar-servicos.sh.

O versoes.sh roda numa copia da plataforma (README com a tabela de versoes,
kind/cluster.yaml, e os scripts), com kubectl e docker falsos que devolvem os
manifests e as imagens do compose do teste. O teste confere que ele reprova a
imagem de terceiro fora da tabela em cada forma que o kustomize a emite (chave
de um item com outras antes, primeira chave do item, valor entre aspas, volume
de imagem), e que o leitor devolve so as imagens.
"""

from __future__ import annotations

import shutil

# subprocess so roda scripts do repositorio, sem shell.
import subprocess  # nosec B404
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
CI = RAIZ / "scripts" / "ci"
LEITOR = CI / "imagens-dos-manifests.sh"
TABELA = ("busybox:1.37", "123", "postgres:16.15")
KIND = "kindest/node:v1.35.0@sha256:0123456789abcdef"

# kubectl falso: o kustomize devolve o manifests.yaml da copia, e docker falso:
# o compose config --images devolve o compose.txt dela.
KUBECTL_FALSO = """
from pathlib import Path
import sys

if sys.argv[1] != "kustomize":
    sys.exit(f"chamada inesperada: {sys.argv[1:]}")
print(Path("manifests.yaml").read_text())
"""
DOCKER_FALSO = """
from pathlib import Path
import sys

if sys.argv[1:3] != ["compose", "-f"]:
    sys.exit(f"chamada inesperada: {sys.argv[1:]}")
print(Path("compose.txt").read_text(), end="")
"""


def le(manifests: str) -> list[str]:
    """As imagens que o leitor tira de um texto de manifests."""
    processo = subprocess.run(  # noqa: S603  # nosec B603
        [str(LEITOR)],
        input=manifests,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return processo.stdout.split("\n")[:-1]


def test_leitor_devolve_so_as_imagens_nas_formas_do_kustomize() -> None:
    manifests = """\
spec:
  containers:
  - env:
    - name: IMAGE_DE_ENV
      value: nao-e-imagem
    image: a:1
    name: a
  - image: b:2
    name: b
  - image: "123"
    name: c
  - image:
    name: sem-valor
  initContainers:
  - image: "d:4"
    # image: comentado:9
    imagePullPolicy: IfNotPresent
  volumes:
  - image:
      pullPolicy: IfNotPresent
      reference: vol.example/e:5
    name: volume
  - configMap:
      name: image
    name: outro
"""

    assert le(manifests) == ["a:1", "b:2", "123", "d:4", "vol.example/e:5"]


class Plataforma:
    """A copia da plataforma em que o versoes.sh roda."""

    def __init__(self, raiz: Path) -> None:
        self.raiz = raiz
        (raiz / "scripts" / "ci").mkdir(parents=True)
        (raiz / "kind").mkdir()
        (raiz / "bin").mkdir()
        shutil.copy(RAIZ / "scripts" / "versoes.sh", raiz / "scripts" / "versoes.sh")
        for leitor in CI.glob("imagens-*.sh"):
            shutil.copy(leitor, raiz / "scripts" / "ci" / leitor.name)
        for nome, codigo in (("kubectl", KUBECTL_FALSO), ("docker", DOCKER_FALSO)):
            binario = raiz / "bin" / nome
            binario.write_text(f"#!{sys.executable}\n{codigo}", encoding="utf-8")
            binario.chmod(0o755)
        linhas = "".join(f"| item | `{imagem}` | serve |\n" for imagem in TABELA)
        (raiz / "README.md").write_text(
            "| Componente | Versão | Para que serve |\n|---|---|---|\n" + linhas,
            encoding="utf-8",
        )
        (raiz / "kind" / "cluster.yaml").write_text(f"image: {KIND}\n")
        (raiz / "compose.txt").write_text("busybox:1.37\npytstop-os-service:dev\n")

    def roda(self, manifests: str) -> subprocess.CompletedProcess[str]:
        (self.raiz / "manifests.yaml").write_text(manifests, encoding="utf-8")
        return subprocess.run(  # noqa: S603  # nosec B603
            [str(self.raiz / "scripts" / "versoes.sh"), "postgres:16.15"],
            cwd=self.raiz,
            env={
                "PATH": f"{self.raiz / 'bin'}:/usr/bin:/bin",
                "KUBERNETES_VERSION": "1.35.0",
            },
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )


@pytest.fixture
def plataforma(tmp_path: Path) -> Plataforma:
    return Plataforma(tmp_path)


def test_versoes_aceita_as_imagens_da_tabela_em_qualquer_forma(
    plataforma: Plataforma,
) -> None:
    processo = plataforma.roda(
        "      - image: busybox:1.37\n        name: a\n"
        '        image: "123"\n'
        "  volumes:\n  - image:\n      reference: postgres:16.15\n"
    )

    assert processo.returncode == 0, processo.stdout
    assert processo.stdout.startswith("versions: 3 images, one tag each, all in")


@pytest.mark.parametrize(
    ("trecho", "imagem"),
    [
        ("        image: evil.example/x:1\n", "evil.example/x:1"),
        ("      - image: evil.example/x:1\n", "evil.example/x:1"),
        ('        image: "456"\n', "456"),
        ("  - image:\n      reference: evil.example/v:1\n", "evil.example/v:1"),
    ],
    ids=["chave", "primeira-chave", "aspas", "volume-de-imagem"],
)
def test_versoes_reprova_a_imagem_fora_da_tabela_em_qualquer_forma(
    plataforma: Plataforma, trecho: str, imagem: str
) -> None:
    processo = plataforma.roda("        image: busybox:1.37\n" + trecho)

    assert processo.returncode == 1
    assert f"{imagem} missing from the README versions table" in processo.stdout
