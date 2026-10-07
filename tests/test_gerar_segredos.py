"""scripts/gerar-segredos.sh contra um kubectl falso.

O kubectl falso guarda os Secrets num JSON, registra os argumentos de cada
chamada e recusa manifesto que o apiserver recusaria. O teste confere o que o
script cria num cluster novo; que as fontes (rabbitmq-credenciais e
grafana-admin) que ja existem ficam como estao; que o Secret rabbitmq de cada
servico, derivado da fonte, e regravado a cada deploy, inclusive quando tem a
senha antiga; que erro ao ler ou gravar no cluster, chave ausente e senha com
caractere fora de letras e digitos param o script; e que nenhuma senha passa
por argumento de processo ou pela saida (no GitHub Actions, so pelo
::add-mask::).
"""

from __future__ import annotations

import json
import os
import re

# subprocess so roda o script do repositorio, sem shell.
import subprocess  # nosec B404
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "gerar-segredos.sh"
BROKER = "rabbitmq.pytstop-plataforma.svc.cluster.local:5672"
USUARIOS = ("os", "billing", "execucao")
CREDENCIAIS = "pytstop-plataforma/rabbitmq-credenciais"
GRAFANA = "pytstop-plataforma/grafana-admin"

# "<namespace>/<nome>" -> stringData do Secret.
type Segredos = dict[str, dict[str, str]]

# kubectl falso: so as formas que o script usa. KUBECTL_FALSO_FALHA=<comando>
# (get, create ou apply) faz esse comando falhar como um cluster fora do ar.
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
if resto[:1] and resto[0] == os.environ.get("KUBECTL_FALSO_FALHA"):
    sys.exit("The connection to the server localhost:8080 was refused")


def manifesto():
    doc = yaml.safe_load(sys.stdin)
    if (doc["apiVersion"], doc["kind"], doc["type"]) != ("v1", "Secret", "Opaque"):
        sys.exit(f"manifesto que nao e Secret v1 Opaque: {doc}")
    if not all(isinstance(v, str) for v in doc["stringData"].values()):
        sys.exit("stringData com valor que nao e string")
    return f"{doc['metadata']['namespace']}/{doc['metadata']['name']}", doc


if resto[:2] == ["get", "secret"]:
    chave = f"{ns}/{resto[2]}"
    if "--ignore-not-found" in resto:
        if chave in segredos:
            print(f"secret/{resto[2]}")
        sys.exit(0)
    if chave not in segredos:
        sys.exit(f'Error from server (NotFound): secrets "{resto[2]}" not found')
    saida = resto[resto.index("-o") + 1]
    (campo,) = re.findall(r"^jsonpath=\{\.data\.([\w.-]+)\}$", saida)
    # Como o kubectl: chave ausente sai vazia, com status 0.
    valor = segredos[chave].get(campo, "")
    print(base64.b64encode(valor.encode()).decode(), end="")
elif resto == ["create", "-f", "-"]:
    chave, doc = manifesto()
    if chave in segredos:
        sys.exit(f"secrets {doc['metadata']['name']!r} already exists")
    segredos[chave] = doc["stringData"]
    arquivo.write_text(json.dumps(segredos))
elif resto == [
    "apply", "--server-side", "--force-conflicts",
    "--field-manager=gerar-segredos", "-f", "-",
]:
    # Server-side apply: grava as chaves do manifesto e mantem as outras.
    chave, doc = manifesto()
    segredos[chave] = {**segredos.get(chave, {}), **doc["stringData"]}
    arquivo.write_text(json.dumps(segredos))
else:
    sys.exit(f"chamada inesperada: {args}")
"""

# openssl falso: senhas so de digitos, diferentes a cada chamada. Sem aspas no
# stringData, o YAML as leria como numero.
OPENSSL_SO_DIGITOS = r"""
import os
from pathlib import Path

contador = Path(os.environ["KUBECTL_FALSO"]) / "openssl"
n = int(contador.read_text()) + 1 if contador.exists() else 1
contador.write_text(str(n))
print(f"{n:048d}")
"""


def roda(
    tmp_path: Path, segredos: Segredos, *, openssl: str | None = None, **ambiente: str
) -> tuple[subprocess.CompletedProcess[str], Segredos, list[list[str]]]:
    """Roda o script com o kubectl falso: processo, Secrets e chamadas.

    ``openssl``, se dado, e o codigo de um openssl falso.
    """
    binarios = tmp_path / "bin"
    binarios.mkdir()
    falsos = {"kubectl": KUBECTL_FALSO} | ({"openssl": openssl} if openssl else {})
    for nome, codigo in falsos.items():
        binario = binarios / nome
        binario.write_text(f"#!{sys.executable}\n{codigo}", encoding="utf-8")
        binario.chmod(0o755)
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
        [str(SCRIPT)], env=env, capture_output=True, text=True, check=False, timeout=30
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


def url(usuario: str, senha: str) -> str:
    return f"amqp://{usuario}:{senha}@{BROKER}/%2F"


def existentes() -> Segredos:
    """Cluster de pe: credenciais, Grafana e o Secret de cada servico."""
    senha = {usuario: f"{usuario}{'1' * 40}" for usuario in ("admin", *USUARIOS)}
    return {
        CREDENCIAIS: {
            "admin-usuario": "admin",
            "admin-senha": senha["admin"],
            **{f"senha-{usuario}": senha[usuario] for usuario in USUARIOS},
            "admin.json": "{}",
        },
        GRAFANA: {"GF_SECURITY_ADMIN_PASSWORD": "grafana" + "2" * 40},
        **{
            f"pytstop-{usuario}/rabbitmq": {
                "RABBITMQ_URL": url(usuario, senha[usuario])
            }
            for usuario in USUARIOS
        },
    }


def gravacoes(chamadas: list[list[str]]) -> list[list[str]]:
    return [chamada for chamada in chamadas if {"create", "apply"} & set(chamada)]


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
            "RABBITMQ_URL": url(usuario, credenciais[f"senha-{usuario}"])
        }
    assert len(segredos) == 5
    # Nenhuma senha em argumento de processo ou na saida; contexto explicito.
    fora = json.dumps(chamadas) + processo.stdout + processo.stderr
    assert [senha for senha in senhas if senha in fora] == []
    assert {tuple(chamada[:2]) for chamada in chamadas} == {
        ("--context", "kind-pytstop-p4")
    }


def test_fontes_que_ja_existem_ficam_e_o_derivado_e_regravado_igual(
    tmp_path: Path,
) -> None:
    antes = existentes()

    processo, segredos, chamadas = roda(tmp_path, antes)

    assert processo.returncode == 0, processo.stderr
    assert segredos == antes
    assert [chamada for chamada in chamadas if "create" in chamada] == []
    assert processo.stdout.count("already exists: kept") == 2
    assert processo.stdout.count("rabbitmq applied") == 3


def test_servico_novo_recebe_a_senha_que_o_broker_ja_tem(tmp_path: Path) -> None:
    antes = existentes()
    del antes["pytstop-billing/rabbitmq"]

    processo, segredos, _ = roda(tmp_path, antes)

    assert processo.returncode == 0, processo.stderr
    assert segredos == existentes()


def test_secret_do_servico_com_a_senha_antiga_ganha_a_da_fonte(
    tmp_path: Path,
) -> None:
    # Senha trocada na fonte depois que o Secret do servico foi criado; a
    # chave antiga do contrato anterior fica, sem uso.
    antes = existentes()
    antes["pytstop-billing/rabbitmq"] = {
        "RABBITMQ_URL": url("billing", "antiga" + "3" * 40),
        "AMQP_URL": "valor-antigo",
    }

    processo, segredos, _ = roda(tmp_path, antes)

    assert processo.returncode == 0, processo.stderr
    assert segredos["pytstop-billing/rabbitmq"] == {
        "RABBITMQ_URL": url("billing", antes[CREDENCIAIS]["senha-billing"]),
        "AMQP_URL": "valor-antigo",
    }


def test_erro_ao_ler_o_cluster_aborta_sem_gravar_nada(tmp_path: Path) -> None:
    processo, segredos, chamadas = roda(tmp_path, {}, KUBECTL_FALSO_FALHA="get")

    assert processo.returncode != 0
    assert segredos == {}
    assert gravacoes(chamadas) == []


@pytest.mark.parametrize(
    ("comando", "gravados", "saida"),
    [
        ("create", set(), ""),
        ("apply", {CREDENCIAIS}, f"secret {CREDENCIAIS} created\n"),
    ],
    ids=["create-da-fonte", "apply-do-derivado"],
)
def test_erro_ao_gravar_no_cluster_para_o_script(
    tmp_path: Path, comando: str, gravados: set[str], saida: str
) -> None:
    processo, segredos, chamadas = roda(tmp_path, {}, KUBECTL_FALSO_FALHA=comando)

    assert processo.returncode != 0
    assert "connection to the server" in processo.stderr
    # Nada depois do comando que falhou: nem a mensagem dele, nem outra
    # gravacao.
    assert processo.stdout == saida
    assert set(segredos) == gravados
    assert len(gravacoes(chamadas)) == len(gravados) + 1


def test_chave_ausente_na_fonte_para_o_script(tmp_path: Path) -> None:
    antes = existentes()
    del antes[CREDENCIAIS]["senha-execucao"]
    del antes["pytstop-execucao/rabbitmq"]

    processo, segredos, _ = roda(tmp_path, antes)

    assert processo.returncode != 0
    assert "has no key senha-execucao" in processo.stderr
    assert "pytstop-execucao/rabbitmq" not in segredos
    assert "grafana-admin" not in processo.stdout


@pytest.mark.parametrize(
    "senha",
    ["pytstop-os-demo-2026", "abc@def/ghi:jkl", "abc def", "abc\ndef"],
    ids=["demonstracao-com-hifen", "caracteres-de-url", "espaco", "quebra-de-linha"],
)
def test_senha_fora_de_letras_e_digitos_para_sem_mostrar_a_senha(
    tmp_path: Path, senha: str
) -> None:
    antes = existentes()
    antes[CREDENCIAIS]["senha-os"] = senha
    del antes["pytstop-os/rabbitmq"]

    processo, segredos, _ = roda(tmp_path, antes)

    assert processo.returncode != 0
    assert "senha-os must have only letters and digits" in processo.stderr
    assert senha not in processo.stdout + processo.stderr
    assert "pytstop-os/rabbitmq" not in segredos


def test_senha_so_de_digitos_chega_ao_secret_como_texto(tmp_path: Path) -> None:
    processo, segredos, _ = roda(tmp_path, {}, openssl=OPENSSL_SO_DIGITOS)

    assert processo.returncode == 0, processo.stderr
    senhas = senhas_de(segredos)
    assert all(re.fullmatch(r"\d{48}", senha) for senha in senhas)
    assert len(set(senhas)) == len(senhas)
    admin = json.loads(segredos[CREDENCIAIS]["admin.json"])
    assert admin["users"][0]["password"] == segredos[CREDENCIAIS]["admin-senha"]


def test_no_github_actions_cada_senha_gerada_e_mascarada(tmp_path: Path) -> None:
    processo, segredos, _ = roda(tmp_path, {}, GITHUB_ACTIONS="true")

    assert processo.returncode == 0, processo.stderr
    senhas = senhas_de(segredos)
    mascaradas = re.findall(r"^::add-mask::(.*)$", processo.stdout, flags=re.MULTILINE)
    assert set(mascaradas) == set(senhas)
    resto = re.sub(r"^::add-mask::.*$", "", processo.stdout, flags=re.MULTILINE)
    assert [senha for senha in senhas if senha in resto] == []


def test_no_github_actions_a_senha_lida_da_fonte_e_mascarada(tmp_path: Path) -> None:
    antes = existentes()

    processo, _, _ = roda(tmp_path, antes, GITHUB_ACTIONS="true")

    assert processo.returncode == 0, processo.stderr
    mascaradas = re.findall(r"^::add-mask::(.*)$", processo.stdout, flags=re.MULTILINE)
    lidas = [antes[CREDENCIAIS][f"senha-{usuario}"] for usuario in USUARIOS]
    assert mascaradas == lidas
