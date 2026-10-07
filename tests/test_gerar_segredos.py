"""scripts/gerar-segredos.sh contra um kubectl falso.

O kubectl falso guarda os Secrets num JSON, registra os argumentos de cada
chamada e recusa manifesto que o apiserver recusaria. O teste confere o que o
script cria num cluster novo, com o formato de cada chave dos servicos; que
dois deploys seguidos mantem os valores; que as fontes que ja existem, da
plataforma e dos servicos, ficam como estao, e a que falta nasce sozinha; que
o Secret rabbitmq de cada servico, derivado da fonte, e regravado a cada
deploy, inclusive quando tem a senha antiga; que erro ao ler ou gravar no
cluster, openssl que falha, chave ausente e senha com caractere fora de letras
e digitos param o script; que KUBE_CONTEXT e NAMESPACE do ambiente (make
deploy KUBE_CONTEXT=<contexto>) valem no lugar dos padroes; e que nenhuma
senha ou chave passa por argumento de processo ou pela saida (no GitHub
Actions, so pelo ::add-mask::, a chave PEM uma linha por vez).
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil

# subprocess so roda o script do repositorio e o openssl, sem shell.
import subprocess  # nosec B404
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "gerar-segredos.sh"
OPENSSL = shutil.which("openssl") or "openssl"
NAMESPACE = "pytstop-plataforma"
USUARIOS = ("os", "billing", "execucao")
CREDENCIAIS = f"{NAMESPACE}/rabbitmq-credenciais"
GRAFANA = f"{NAMESPACE}/grafana-admin"
NAMESPACES_DOS_SERVICOS = {f"pytstop-{usuario}" for usuario in USUARIOS}
# Fontes dos servicos ("<namespace>/<nome>") e as chaves de cada uma.
FONTES_DOS_SERVICOS = {
    "pytstop-os/os-postgres": {"POSTGRES_PASSWORD"},
    "pytstop-execucao/execucao-postgres": {"POSTGRES_PASSWORD"},
    "pytstop-os/os-jwt": {"JWT_PRIVATE_KEY", "JWT_PREVIOUS_PUBLIC_KEY"},
    "pytstop-os/os-cripto": {"ENCRYPTION_KEY"},
    "pytstop-os/os-admin": {"ADMIN_PASSWORD"},
    "pytstop-billing/billing-mongo": {
        "MONGO_INITDB_ROOT_PASSWORD",
        "MONGO_BILLING_PASSWORD",
        "MONGO_EXPORTER_PASSWORD",
        "MONGO_KEYFILE",
    },
    "pytstop-billing/billing-link": {"ORCAMENTO_LINK_SECRET"},
}
# As que guardam estado no banco do servico: nao nascem de novo com o volume
# dele de pe.
FONTES_DO_BANCO = {
    "pytstop-os/os-postgres",
    "pytstop-execucao/execucao-postgres",
    "pytstop-os/os-cripto",
    "pytstop-os/os-admin",
    "pytstop-billing/billing-mongo",
}
# Formato de cada chave, o valor inteiro.
HEX_48 = r"[0-9a-f]{48}"
HEX_64 = r"[0-9a-f]{64}"
FORMATOS = {
    "POSTGRES_PASSWORD": HEX_48,
    "ADMIN_PASSWORD": HEX_48,
    "MONGO_INITDB_ROOT_PASSWORD": HEX_48,
    "MONGO_BILLING_PASSWORD": HEX_48,
    "MONGO_EXPORTER_PASSWORD": HEX_48,
    "ORCAMENTO_LINK_SECRET": HEX_64,
    # Fernet: 32 bytes em base64 url-safe, com o "=" do fim.
    "ENCRYPTION_KEY": r"[A-Za-z0-9_-]{43}=",
    # 756 bytes em base64, numa linha so.
    "MONGO_KEYFILE": r"[A-Za-z0-9+/]{1008}",
    # PKCS#8 sem senha; o bloco literal do YAML termina com quebra de linha.
    "JWT_PRIVATE_KEY": (
        r"-----BEGIN PRIVATE KEY-----\n"
        r"(?:[A-Za-z0-9+/=]{1,64}\n)+"
        r"-----END PRIVATE KEY-----\n"
    ),
    "JWT_PREVIOUS_PUBLIC_KEY": r"",
}
# O que o make deploy passa a outro cluster, no lugar dos padroes do kind
# (make deploy OVERLAY=k3s KUBE_CONTEXT=<contexto do k3s>).
CONTEXTO_OUTRO = "k3s-vm"
NAMESPACE_OUTRO = "outro"

# "<namespace>/<nome>" -> stringData do Secret.
type Segredos = dict[str, dict[str, str]]

# kubectl falso: so as formas que o script usa. KUBECTL_FALSO_FALHA=<comando>
# (get, create ou apply) faz esse comando falhar como um cluster fora do ar, e
# KUBECTL_FALSO_VOLUMES ("<namespace>/<pvc> ...") lista os volumes de pe.
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
elif resto == ["get", "pvc", "-o", "name"]:
    for volume in os.environ.get("KUBECTL_FALSO_VOLUMES", "").split():
        if volume.startswith(f"{ns}/"):
            print(f"persistentvolumeclaim/{volume.split('/')[1]}")
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

# openssl falso: valores so de digitos, diferentes a cada chamada. Sem aspas
# no stringData, o YAML os leria como numero. Comecam por 1: com zero a
# esquerda e um 8 ou 9 o valor nao e octal valido, o PyYAML o le como texto e
# a falta de aspas passaria.
OPENSSL_SO_DIGITOS = r"""
import os
from pathlib import Path

contador = Path(os.environ["KUBECTL_FALSO"]) / "openssl"
n = int(contador.read_text()) + 1 if contador.exists() else 1
contador.write_text(str(n))
print(10**47 + n)
"""

# openssl falso que desvia o subcomando de OPENSSL_SUBCOMANDO: imprime
# OPENSSL_SAIDA ou, sem ela, falha como um openssl quebrado. Os outros
# subcomandos vao ao openssl real (OPENSSL_REAL).
OPENSSL_DESVIADO = r"""
import os
import sys

if os.environ["OPENSSL_SUBCOMANDO"] in " ".join(sys.argv[1:]):
    if "OPENSSL_SAIDA" not in os.environ:
        sys.exit("openssl: falha simulada")
    print(os.environ["OPENSSL_SAIDA"])
    sys.exit(0)
os.execv(os.environ["OPENSSL_REAL"], sys.argv)
"""


def roda(
    tmp_path: Path, segredos: Segredos, *, openssl: str | None = None, **ambiente: str
) -> tuple[subprocess.CompletedProcess[str], Segredos, list[list[str]]]:
    """Roda o script com o kubectl falso: processo, Secrets e chamadas.

    ``openssl``, se dado, e o codigo de um openssl falso.
    """
    binarios = tmp_path / "bin"
    binarios.mkdir(parents=True)
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
        # O CI define GITHUB_ACTIONS, e quem roda aqui pode ter KUBE_CONTEXT e
        # NAMESPACE: os padroes do script so valem sem eles; os testes de
        # override os passam em `ambiente`.
        if chave not in {"GITHUB_ACTIONS", "KUBE_CONTEXT", "NAMESPACE"}
    }
    env |= {
        "PATH": f"{binarios}{os.pathsep}{env['PATH']}",
        "KUBECTL_FALSO": str(tmp_path),
        **ambiente,
    }
    processo = subprocess.run(  # noqa: S603  # nosec B603
        [str(SCRIPT)], env=env, capture_output=True, text=True, check=False, timeout=60
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


def valores_gerados(segredos: Segredos) -> list[str]:
    """Senhas e chaves geradas, com a chave PEM linha a linha, como o runner a
    mascara; sem a chave anterior do JWT, que nasce vazia."""
    valores = senhas_de(segredos)
    for fonte in FONTES_DOS_SERVICOS:
        for chave, valor in segredos[fonte].items():
            if chave == "JWT_PRIVATE_KEY":
                valores += valor.splitlines()
            elif chave != "JWT_PREVIOUS_PUBLIC_KEY":
                valores.append(valor)
    return valores


def url(usuario: str, senha: str, ns: str = NAMESPACE) -> str:
    return f"amqp://{usuario}:{senha}@rabbitmq.{ns}.svc.cluster.local:5672/%2F"


def existentes(ns: str = NAMESPACE) -> Segredos:
    """Cluster de pe, com a plataforma no namespace ``ns``: credenciais, Grafana,
    o Secret rabbitmq de cada servico e as fontes dos servicos.
    """
    senha = {usuario: f"{usuario}{'1' * 40}" for usuario in ("admin", *USUARIOS)}
    return {
        f"{ns}/rabbitmq-credenciais": {
            "admin-usuario": "admin",
            "admin-senha": senha["admin"],
            **{f"senha-{usuario}": senha[usuario] for usuario in USUARIOS},
            "admin.json": "{}",
        },
        f"{ns}/grafana-admin": {"GF_SECURITY_ADMIN_PASSWORD": "grafana" + "2" * 40},
        **{
            f"pytstop-{usuario}/rabbitmq": {
                "RABBITMQ_URL": url(usuario, senha[usuario], ns)
            }
            for usuario in USUARIOS
        },
        **{
            fonte: {chave: f"{chave.lower()}-de-pe" for chave in chaves}
            for fonte, chaves in FONTES_DOS_SERVICOS.items()
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
    assert all(re.fullmatch(HEX_48, senha) for senha in senhas)
    valores = valores_gerados(segredos)
    assert len(set(valores)) == len(valores)
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
    assert set(segredos) == set(existentes())
    # Nenhuma senha ou chave em argumento de processo ou na saida; contexto
    # explicito.
    fora = json.dumps(chamadas) + processo.stdout + processo.stderr
    assert [valor for valor in valores if valor in fora] == []
    assert {tuple(chamada[:2]) for chamada in chamadas} == {
        ("--context", "kind-pytstop-p4")
    }


def test_fontes_dos_servicos_nascem_no_formato_do_contrato(tmp_path: Path) -> None:
    processo, segredos, _ = roda(tmp_path, {})

    assert processo.returncode == 0, processo.stderr
    assert {
        fonte: set(segredos[fonte]) for fonte in FONTES_DOS_SERVICOS
    } == FONTES_DOS_SERVICOS
    fora_do_formato = [
        f"{fonte} {chave}"
        for fonte, chaves in FONTES_DOS_SERVICOS.items()
        for chave in chaves
        if not re.fullmatch(FORMATOS[chave], segredos[fonte][chave])
    ]
    assert fora_do_formato == []
    fernet = segredos["pytstop-os/os-cripto"]["ENCRYPTION_KEY"]
    assert len(base64.urlsafe_b64decode(fernet)) == 32
    keyfile = segredos["pytstop-billing/billing-mongo"]["MONGO_KEYFILE"]
    assert len(base64.b64decode(keyfile, validate=True)) == 756
    # RSA de 2048 bits que o proprio openssl le.
    chave_rsa = subprocess.run(  # noqa: S603  # nosec B603
        [OPENSSL, "pkey", "-noout", "-text"],
        input=segredos["pytstop-os/os-jwt"]["JWT_PRIVATE_KEY"],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    assert re.match(r"(?:RSA )?Private-Key: \(2048 bit", chave_rsa.stdout)


def test_chave_fernet_troca_o_alfabeto_do_base64_pelo_url_safe(
    tmp_path: Path,
) -> None:
    # 32 bytes cujo base64 padrao tem "+" e "/", os dois caracteres que o
    # Fernet recusa.
    chave = b"\xfb\xff" * 16
    padrao = base64.b64encode(chave).decode()
    assert {"+", "/"} <= set(padrao)

    processo, segredos, _ = roda(
        tmp_path,
        {},
        openssl=OPENSSL_DESVIADO,
        OPENSSL_SUBCOMANDO="rand -base64 32",
        OPENSSL_SAIDA=padrao,
        OPENSSL_REAL=OPENSSL,
    )

    assert processo.returncode == 0, processo.stderr
    assert segredos["pytstop-os/os-cripto"]["ENCRYPTION_KEY"] == (
        base64.urlsafe_b64encode(chave).decode()
    )


def test_segundo_deploy_mantem_todos_os_valores(tmp_path: Path) -> None:
    primeiro, criados, _ = roda(tmp_path / "primeiro", {})
    segundo, depois, chamadas = roda(tmp_path / "segundo", criados)

    assert primeiro.returncode == 0, primeiro.stderr
    assert segundo.returncode == 0, segundo.stderr
    assert depois == criados
    assert [chamada for chamada in chamadas if "create" in chamada] == []


def test_fontes_que_ja_existem_ficam_e_o_derivado_e_regravado_igual(
    tmp_path: Path,
) -> None:
    antes = existentes()

    processo, segredos, chamadas = roda(tmp_path, antes)

    assert processo.returncode == 0, processo.stderr
    assert segredos == antes
    assert [chamada for chamada in chamadas if "create" in chamada] == []
    assert processo.stdout.count("already exists: kept") == 2 + len(FONTES_DOS_SERVICOS)
    assert processo.stdout.count("rabbitmq applied") == 3


@pytest.mark.parametrize("fonte", FONTES_DOS_SERVICOS)
def test_fonte_de_servico_que_falta_nasce_e_as_outras_ficam(
    tmp_path: Path, fonte: str
) -> None:
    antes = existentes()
    del antes[fonte]

    processo, segredos, chamadas = roda(tmp_path, antes)

    assert processo.returncode == 0, processo.stderr
    assert set(segredos.pop(fonte)) == FONTES_DOS_SERVICOS[fonte]
    assert segredos == antes
    assert len([chamada for chamada in chamadas if "create" in chamada]) == 1
    assert f"secret {fonte} created" in processo.stdout


@pytest.mark.parametrize("fonte", sorted(FONTES_DO_BANCO))
def test_fonte_do_banco_que_falta_com_o_volume_de_pe_para_sem_gerar(
    tmp_path: Path, fonte: str
) -> None:
    antes = existentes()
    del antes[fonte]
    ns = fonte.split("/")[0]

    processo, segredos, _ = roda(tmp_path, antes, KUBECTL_FALSO_VOLUMES=f"{ns}/dados-0")

    assert processo.returncode != 0
    assert f"secret {fonte} is missing but {ns} already has a database volume" in (
        processo.stderr
    )
    assert segredos == antes


@pytest.mark.parametrize("fonte", sorted(set(FONTES_DOS_SERVICOS) - FONTES_DO_BANCO))
def test_chave_sem_estado_no_banco_nasce_de_novo_com_os_volumes_de_pe(
    tmp_path: Path, fonte: str
) -> None:
    # A troca da chave HMAC e a da RSA de uma vez: apagar o Secret e reimplantar.
    antes = existentes()
    del antes[fonte]
    volumes = " ".join(f"{ns}/dados-0" for ns in NAMESPACES_DOS_SERVICOS)

    processo, segredos, _ = roda(tmp_path, antes, KUBECTL_FALSO_VOLUMES=volumes)

    assert processo.returncode == 0, processo.stderr
    assert set(segredos.pop(fonte)) == FONTES_DOS_SERVICOS[fonte]
    assert segredos == antes


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


@pytest.mark.parametrize("de_pe", [False, True], ids=["cluster-novo", "cluster-de-pe"])
def test_contexto_e_namespace_do_ambiente_valem_no_lugar_dos_padroes(
    tmp_path: Path, de_pe: bool
) -> None:
    antes = existentes(NAMESPACE_OUTRO) if de_pe else {}

    processo, segredos, chamadas = roda(
        tmp_path, antes, KUBE_CONTEXT=CONTEXTO_OUTRO, NAMESPACE=NAMESPACE_OUTRO
    )

    assert processo.returncode == 0, processo.stderr
    # Fontes da plataforma no namespace pedido, as dos servicos e os derivados
    # nos dos servicos, nada no padrao.
    assert set(segredos) == set(existentes(NAMESPACE_OUTRO))
    credenciais = segredos[f"{NAMESPACE_OUTRO}/rabbitmq-credenciais"]
    for usuario in USUARIOS:
        senha = credenciais[f"senha-{usuario}"]
        assert segredos[f"pytstop-{usuario}/rabbitmq"] == {
            "RABBITMQ_URL": url(usuario, senha, NAMESPACE_OUTRO)
        }
    # O contexto pedido em toda chamada, e toda leitura no namespace pedido ou
    # no de um servico.
    assert {tuple(chamada[:2]) for chamada in chamadas} == {
        ("--context", CONTEXTO_OUTRO)
    }
    assert {chamada[3] for chamada in chamadas if chamada[2] == "-n"} == {
        NAMESPACE_OUTRO,
        *NAMESPACES_DOS_SERVICOS,
    }
    assert {
        chamada[3]
        for chamada in chamadas
        if chamada[2] == "-n"
        and chamada[6] in {"rabbitmq-credenciais", "grafana-admin"}
    } == {NAMESPACE_OUTRO}


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


def test_erro_ao_criar_a_fonte_de_um_servico_para_o_script(tmp_path: Path) -> None:
    antes = existentes()
    del antes["pytstop-os/os-admin"]

    processo, segredos, _ = roda(tmp_path, antes, KUBECTL_FALSO_FALHA="create")

    assert processo.returncode != 0
    assert "connection to the server" in processo.stderr
    assert segredos == antes
    # Para ali: nem a mensagem de criada, nem as fontes que vem depois.
    assert "os-admin created" not in processo.stdout
    assert "billing-link" not in processo.stdout


@pytest.mark.parametrize(
    ("falha", "fonte"),
    [
        ("genpkey", "pytstop-os/os-jwt"),
        ("rand -base64 32", "pytstop-os/os-cripto"),
        ("rand -base64 756", "pytstop-billing/billing-mongo"),
    ],
    ids=["chave-rsa", "chave-fernet-no-pipe", "keyfile-no-pipe"],
)
def test_openssl_que_falha_para_o_script_sem_gravar_a_fonte(
    tmp_path: Path, falha: str, fonte: str
) -> None:
    processo, segredos, _ = roda(
        tmp_path,
        {},
        openssl=OPENSSL_DESVIADO,
        OPENSSL_SUBCOMANDO=falha,
        OPENSSL_REAL=OPENSSL,
    )

    assert processo.returncode != 0
    assert "falha simulada" in processo.stderr
    # Nem a fonte, nem a ultima do script, que vem depois de todas.
    assert fonte not in segredos
    assert "pytstop-billing/billing-link" not in segredos


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
    valores = valores_gerados(segredos)
    assert all(re.fullmatch(r"\d{48}", valor) for valor in valores)
    assert len(set(valores)) == len(valores)
    admin = json.loads(segredos[CREDENCIAIS]["admin.json"])
    assert admin["users"][0]["password"] == segredos[CREDENCIAIS]["admin-senha"]


def test_no_github_actions_cada_senha_e_chave_gerada_e_mascarada(
    tmp_path: Path,
) -> None:
    processo, segredos, _ = roda(tmp_path, {}, GITHUB_ACTIONS="true")

    assert processo.returncode == 0, processo.stderr
    valores = valores_gerados(segredos)
    mascaradas = re.findall(r"^::add-mask::(.*)$", processo.stdout, flags=re.MULTILINE)
    assert set(mascaradas) == set(valores)
    resto = re.sub(r"^::add-mask::.*$", "", processo.stdout, flags=re.MULTILINE)
    assert [valor for valor in valores if valor in resto] == []


def test_no_github_actions_a_senha_lida_da_fonte_e_mascarada(tmp_path: Path) -> None:
    antes = existentes()

    processo, _, _ = roda(tmp_path, antes, GITHUB_ACTIONS="true")

    assert processo.returncode == 0, processo.stderr
    mascaradas = re.findall(r"^::add-mask::(.*)$", processo.stdout, flags=re.MULTILINE)
    lidas = [antes[CREDENCIAIS][f"senha-{usuario}"] for usuario in USUARIOS]
    assert mascaradas == lidas
