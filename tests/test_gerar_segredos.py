"""scripts/gerar-segredos.sh contra um kubectl falso.

O kubectl falso guarda os Secrets num JSON e registra os argumentos de cada
chamada. O teste confere o que o script cria num cluster novo, que nao toca no
que ja existe, que o Secret de um servico novo usa a senha que o broker ja tem,
que erro ao ler o cluster nao vira "nao existe" e que nenhuma senha passa por
argumento de processo ou pela saida (no GitHub Actions, so pelo ::add-mask::).
"""

from __future__ import annotations

import json
import os
import re

# subprocess so roda o script do repositorio, sem shell.
import subprocess  # nosec B404
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "gerar-segredos.sh"
BROKER = "rabbitmq.pytstop-plataforma.svc.cluster.local:5672"
USUARIOS = ("os", "billing", "execucao")
CREDENCIAIS = "pytstop-plataforma/rabbitmq-credenciais"
GRAFANA = "pytstop-plataforma/grafana-admin"

# "<namespace>/<nome>" -> stringData do Secret.
type Segredos = dict[str, dict[str, str]]

# kubectl falso: so as tres formas que o script usa. KUBECTL_FALSO_FALHA=get
# faz toda leitura falhar como um cluster fora do ar.
KUBECTL_FALSO = r"""
import base64
import json
import os
import re
import sys
from pathlib import Path

import yaml

estado = Path(os.environ["KUBECTL_FALSO"])
arquivo = estado / "segredos.json"
segredos = json.loads(arquivo.read_text())
args = sys.argv[1:]
with (estado / "chamadas.jsonl").open("a") as log:
    log.write(json.dumps(args) + "\n")
resto = args[2:]  # depois do --context, que o teste confere no log
ns = ""
if resto[:1] == ["-n"]:
    ns, resto = resto[1], resto[2:]
if resto[:2] == ["get", "secret"]:
    if os.environ.get("KUBECTL_FALSO_FALHA") == "get":
        sys.exit("The connection to the server localhost:8080 was refused")
    chave = f"{ns}/{resto[2]}"
    if "--ignore-not-found" in resto:
        if chave in segredos:
            print(f"secret/{resto[2]}")
        sys.exit(0)
    saida = resto[resto.index("-o") + 1]
    (campo,) = re.findall(r"^jsonpath=\{\.data\.([\w.-]+)\}$", saida)
    print(base64.b64encode(segredos[chave][campo].encode()).decode(), end="")
elif resto == ["create", "-f", "-"]:
    doc = yaml.safe_load(sys.stdin)
    chave = f"{doc['metadata']['namespace']}/{doc['metadata']['name']}"
    if chave in segredos:
        sys.exit(f"secrets {doc['metadata']['name']!r} already exists")
    if not all(isinstance(v, str) for v in doc["stringData"].values()):
        sys.exit("stringData com valor que nao e string")
    segredos[chave] = doc["stringData"]
    arquivo.write_text(json.dumps(segredos))
else:
    sys.exit(f"chamada inesperada: {args}")
"""


def roda(
    tmp_path: Path, segredos: Segredos, **ambiente: str
) -> tuple[subprocess.CompletedProcess[str], Segredos, list[list[str]]]:
    """Roda o script com o kubectl falso: processo, Secrets e chamadas."""
    binarios = tmp_path / "bin"
    binarios.mkdir()
    kubectl = binarios / "kubectl"
    kubectl.write_text(f"#!{sys.executable}\n{KUBECTL_FALSO}", encoding="utf-8")
    kubectl.chmod(0o755)
    (tmp_path / "segredos.json").write_text(json.dumps(segredos), encoding="utf-8")
    (tmp_path / "chamadas.jsonl").touch()
    env = {
        chave: valor
        for chave, valor in os.environ.items()
        # O CI define GITHUB_ACTIONS; contexto e namespace vem dos padroes.
        if chave not in {"GITHUB_ACTIONS", "KUBE_CONTEXT", "NAMESPACE"}
    }
    env |= {
        "PATH": f"{binarios}{os.pathsep}{env['PATH']}",
        "KUBECTL_FALSO": str(tmp_path),
        **ambiente,
    }
    processo = subprocess.run(  # noqa: S603  # nosec B603
        [str(SCRIPT)], env=env, capture_output=True, text=True, check=False
    )
    chamadas = (tmp_path / "chamadas.jsonl").read_text(encoding="utf-8")
    depois = json.loads((tmp_path / "segredos.json").read_text(encoding="utf-8"))
    return processo, depois, [json.loads(linha) for linha in chamadas.splitlines()]


def senhas_de(segredos: Segredos) -> list[str]:
    credenciais = segredos[CREDENCIAIS]
    return [
        credenciais["admin-senha"],
        *(credenciais[f"senha-{usuario}"] for usuario in USUARIOS),
        segredos[GRAFANA]["GF_SECURITY_ADMIN_PASSWORD"],
    ]


def existentes() -> Segredos:
    """Cluster de pe: credenciais, Grafana e o Secret de cada servico."""
    senha = {usuario: f"{usuario}-{'1' * 40}" for usuario in ("admin", *USUARIOS)}
    return {
        CREDENCIAIS: {
            "admin-usuario": "admin",
            "admin-senha": senha["admin"],
            **{f"senha-{usuario}": senha[usuario] for usuario in USUARIOS},
            "admin.json": "{}",
        },
        GRAFANA: {"GF_SECURITY_ADMIN_PASSWORD": "grafana-" + "2" * 40},
        **{
            f"pytstop-{usuario}/rabbitmq": {
                "RABBITMQ_URL": f"amqp://{usuario}:{senha[usuario]}@{BROKER}/"
            }
            for usuario in USUARIOS
        },
    }


def test_cluster_novo_recebe_todos_os_secrets_com_senhas_geradas(
    tmp_path: Path,
) -> None:
    processo, segredos, chamadas = roda(tmp_path, {})

    assert processo.returncode == 0, processo.stderr
    senhas = senhas_de(segredos)
    assert all(re.fullmatch(r"[0-9a-f]{48}", senha) for senha in senhas)
    assert len(set(senhas)) == len(senhas)
    credenciais = segredos[CREDENCIAIS]
    assert credenciais["admin-usuario"] == "admin"
    admin = json.loads(credenciais["admin.json"])
    assert admin["vhosts"] == [{"name": "/"}]
    assert admin["users"] == [
        {
            "name": "admin",
            "password": credenciais["admin-senha"],
            "tags": ["administrator"],
        }
    ]
    assert admin["permissions"] == [
        {"user": "admin", "vhost": "/", "configure": ".*", "write": ".*", "read": ".*"}
    ]
    for usuario in USUARIOS:
        assert segredos[f"pytstop-{usuario}/rabbitmq"] == {
            "RABBITMQ_URL": f"amqp://{usuario}:{credenciais[f'senha-{usuario}']}@{BROKER}/"
        }
    assert len(segredos) == 5
    # Nenhuma senha em argumento de processo ou na saida; contexto explicito.
    fora = json.dumps(chamadas) + processo.stdout + processo.stderr
    assert [senha for senha in senhas if senha in fora] == []
    assert {tuple(chamada[:2]) for chamada in chamadas} == {
        ("--context", "kind-pytstop-p4")
    }


def test_secrets_que_ja_existem_ficam_como_estao(tmp_path: Path) -> None:
    antes = existentes()

    processo, segredos, chamadas = roda(tmp_path, antes)

    assert processo.returncode == 0, processo.stderr
    assert segredos == antes
    assert [chamada for chamada in chamadas if "create" in chamada] == []
    assert processo.stdout.count("already exists: kept") == 5


def test_servico_novo_recebe_a_senha_que_o_broker_ja_tem(tmp_path: Path) -> None:
    antes = existentes()
    del antes["pytstop-billing/rabbitmq"]

    processo, segredos, _ = roda(tmp_path, antes)

    assert processo.returncode == 0, processo.stderr
    assert segredos == existentes()


def test_erro_ao_ler_o_cluster_aborta_sem_criar_nada(tmp_path: Path) -> None:
    processo, segredos, chamadas = roda(tmp_path, {}, KUBECTL_FALSO_FALHA="get")

    assert processo.returncode != 0
    assert segredos == {}
    assert [chamada for chamada in chamadas if "create" in chamada] == []


def test_no_github_actions_cada_senha_gerada_e_mascarada(tmp_path: Path) -> None:
    processo, segredos, _ = roda(tmp_path, {}, GITHUB_ACTIONS="true")

    assert processo.returncode == 0, processo.stderr
    senhas = senhas_de(segredos)
    mascaradas = re.findall(r"^::add-mask::(.*)$", processo.stdout, flags=re.MULTILINE)
    assert set(mascaradas) == set(senhas)
    resto = re.sub(r"^::add-mask::.*$", "", processo.stdout, flags=re.MULTILINE)
    assert [senha for senha in senhas if senha in resto] == []
