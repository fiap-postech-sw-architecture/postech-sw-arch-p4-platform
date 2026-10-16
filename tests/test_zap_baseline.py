"""ZAP baseline na borda (ADR-041, RNF-049).

O scripts/ci/zap-baseline.sh roda com um docker falso que escreve os relatorios
na pasta montada e imprime a saida que o zap-baseline.py imprime (a linha de
contagem e o "Total of N URLs"). O teste confere o comando exato de cada
servico, que FAIL de regra, scan sem pagina lida, ZAP que pendura e saida sem
resumo reprovam sem esconder os outros servicos, e a tabela do summary. O
e2e/zap/regras.conf e lido como o ZAP o le, e cada regra tem de estar no README
com a mesma acao.
"""

from __future__ import annotations

import json
import os
import re

# subprocess so roda scripts do repositorio, sem shell.
import subprocess  # nosec B404
import sys
from pathlib import Path
from typing import Any

import pytest

RAIZ = Path(__file__).resolve().parents[1]
SCRIPT = RAIZ / "scripts" / "ci" / "zap-baseline.sh"
REGRAS = RAIZ / "e2e" / "zap" / "regras.conf"
README = (RAIZ / "README.md").read_text(encoding="utf-8")
PREFIXOS = {
    "os-service": "/os",
    "billing-service": "/billing",
    "execution-service": "/execucao",
}
IMAGEM = re.search(r'^ZAP_IMAGE="([^"]+)"$', SCRIPT.read_text(), re.MULTILINE)
NIVEIS = {"FAIL", "WARN", "IGNORE", "INFO"}

# docker falso: guarda a chamada, escreve os tres relatorios na pasta montada
# (-v <pasta>:/zap/wrk) e imprime o resumo do ZAP conforme o estado do servico.
DOCKER_FALSO = """
import json
import os
import sys
import time
from pathlib import Path

falsos = Path(os.environ["FALSOS"])
args = sys.argv[1:]
with (falsos / "docker.jsonl").open("a") as log:
    log.write(json.dumps(args) + "\\n")
estado = json.loads((falsos / "estado.json").read_text())
pasta = Path(args[args.index("-v") + 1].split(":")[0])
nome = args[args.index("-w") + 1].removeprefix("zap-").removesuffix(".md")
cfg = estado.get(nome, {})
time.sleep(cfg.get("dorme", 0))
for extensao in ("html", "json"):
    (pasta / f"zap-{nome}.{extensao}").write_text("{}")
(pasta / f"zap-{nome}.md").write_text(f"# ZAP Scanning Report de {nome}\\n")
if not cfg.get("sem_resumo"):
    print("Using the Automation Framework")
    print(f"Total of {cfg.get('urls', 6)} URLs")
    fim = "WARN-INPROG: 0\\tINFO: 0\\tIGNORE: 1\\tPASS: 59"
    print(
        f"FAIL-NEW: {cfg.get('fail', 0)}\\tFAIL-INPROG: 0\\t"
        f"WARN-NEW: {cfg.get('warn', 1)}\\t{fim}"
    )
sys.exit(cfg.get("codigo", 0))
"""


class Zap:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp = tmp_path
        binarios = tmp_path / "bin"
        binarios.mkdir()
        docker = binarios / "docker"
        docker.write_text(f"#!{sys.executable}\n{DOCKER_FALSO}", encoding="utf-8")
        docker.chmod(0o755)
        self.summary = tmp_path / "summary.md"
        self.pasta = tmp_path / "relatorios"
        self.env = {
            chave: valor
            for chave, valor in os.environ.items()
            if chave
            not in {
                "BORDA",
                "ZAP_REDE",
                "RELATORIOS",
                "PRAZO_ZAP",
                "GITHUB_STEP_SUMMARY",
            }
        } | {
            "PATH": f"{binarios}{os.pathsep}{os.environ['PATH']}",
            "FALSOS": str(tmp_path),
            "GITHUB_STEP_SUMMARY": str(self.summary),
            "RELATORIOS": str(self.pasta),
        }

    def roda(
        self, estado: dict[str, Any], *servicos: str, **ambiente: str
    ) -> subprocess.CompletedProcess[str]:
        (self.tmp / "estado.json").write_text(json.dumps(estado), encoding="utf-8")
        return subprocess.run(  # noqa: S603  # nosec B603
            [str(SCRIPT), *servicos],
            env=self.env | ambiente,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )

    def chamadas(self) -> list[list[str]]:
        arquivo = self.tmp / "docker.jsonl"
        if not arquivo.exists():
            return []
        return [json.loads(linha) for linha in arquivo.read_text().splitlines()]

    def linhas(self) -> dict[str, str]:
        """Servico -> resultado, da tabela do summary."""
        return dict(
            re.findall(
                r"^\| (\S+-service) \| `[^`]+` \| \S+ \| \S+ \| \S+ \| ([^|]+) \|$",
                self.summary.read_text(),
                flags=re.MULTILINE,
            )
        )


@pytest.fixture
def zap(tmp_path: Path) -> Zap:
    return Zap(tmp_path)


def comando(zap: Zap, servico: str, borda: str = "https://localhost") -> list[str]:
    """O que o script tem de pedir ao docker para um servico."""
    assert IMAGEM is not None
    return [
        "run",
        "--rm",
        "--network",
        "host",
        "-v",
        f"{zap.pasta}:/zap/wrk",
        IMAGEM.group(1),
        "zap-baseline.py",
        "-t",
        f"{borda}{PREFIXOS[servico]}/openapi.json",
        "-c",
        "regras.conf",
        "-m",
        "1",
        "-I",
        "-z",
        "-silent",
        "-r",
        f"zap-{servico}.html",
        "-J",
        f"zap-{servico}.json",
        "-w",
        f"zap-{servico}.md",
    ]


def test_sem_argumento_varre_os_tres_servicos_pela_borda(zap: Zap) -> None:
    processo = zap.roda({})
    assert processo.returncode == 0, processo.stderr
    assert zap.chamadas() == [comando(zap, s) for s in PREFIXOS]
    assert "ZAP baseline OK: os-service billing-service execution-service" in (
        processo.stdout
    )


def test_so_o_servico_pedido_e_varrido(zap: Zap) -> None:
    processo = zap.roda({}, "billing-service")
    assert processo.returncode == 0, processo.stderr
    assert zap.chamadas() == [comando(zap, "billing-service")]
    assert list(zap.linhas()) == ["billing-service"]


def test_borda_e_rede_do_container_por_variavel(zap: Zap) -> None:
    zap.roda({}, "os-service", BORDA="https://kong:8443", ZAP_REDE="rede-de-teste")
    esperado = comando(zap, "os-service", "https://kong:8443")
    esperado[esperado.index("host")] = "rede-de-teste"
    assert zap.chamadas() == [esperado]


def test_a_imagem_do_zap_vai_por_digest_e_esta_na_tabela_do_readme() -> None:
    assert IMAGEM is not None
    imagem = IMAGEM.group(1)
    assert re.fullmatch(
        r"ghcr\.io/zaproxy/zaproxy:\d+\.\d+\.\d+@sha256:[0-9a-f]{64}", imagem
    )
    tabela = subprocess.run(  # noqa: S603  # nosec B603
        [str(RAIZ / "scripts" / "ci" / "imagens-do-readme.sh")],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    ).stdout.splitlines()
    assert imagem in tabela


def test_regras_vao_para_a_pasta_montada_que_o_container_consegue_gravar(
    zap: Zap,
) -> None:
    zap.roda({}, "os-service")
    assert (zap.pasta / "regras.conf").read_text() == REGRAS.read_text()
    assert (zap.pasta.stat().st_mode & 0o777) == 0o777


def test_relatorios_e_log_de_cada_servico_ficam_na_pasta(zap: Zap) -> None:
    zap.roda({})
    for servico in PREFIXOS:
        for extensao in ("html", "json", "md", "log"):
            assert (zap.pasta / f"zap-{servico}.{extensao}").is_file()
    assert "Total of 6 URLs" in (zap.pasta / "zap-os-service.log").read_text()


def test_summary_traz_a_tabela_e_o_relatorio_de_cada_servico(zap: Zap) -> None:
    zap.roda({"billing-service": {"warn": 3}})
    resumo = zap.summary.read_text()
    assert resumo.startswith("### ZAP baseline\n")
    assert zap.linhas() == dict.fromkeys(PREFIXOS, "ok")
    linha = "| billing-service | `https://localhost/billing/openapi.json` |"
    assert f"{linha} 0 | 3 | 6 | ok |" in resumo
    for servico in PREFIXOS:
        assert f"#### {servico}\n\n# ZAP Scanning Report de {servico}" in resumo


def test_fail_de_regra_reprova_nomeia_o_servico_e_varre_os_outros(zap: Zap) -> None:
    processo = zap.roda({"billing-service": {"fail": 1, "codigo": 1}})
    assert processo.returncode == 1
    assert "ZAP baseline FAILED: billing-service" in processo.stderr
    assert [c[c.index("-t") + 1] for c in zap.chamadas()] == [
        f"https://localhost{p}/openapi.json" for p in PREFIXOS.values()
    ]
    assert zap.linhas() == {
        "os-service": "ok",
        "billing-service": "FAILED (ZAP exit 1)",
        "execution-service": "ok",
    }


def test_scan_que_nao_leu_pagina_reprova_mesmo_com_exit_0(zap: Zap) -> None:
    """Certificado recusado ou borda fora: nada lido nao e 'nada a reportar'."""
    processo = zap.roda({"os-service": {"urls": 0}}, "os-service")
    assert processo.returncode == 1
    assert "ZAP baseline FAILED: os-service" in processo.stderr
    assert "no URL scanned" in zap.linhas()["os-service"]


def test_saida_sem_a_linha_de_resumo_reprova(zap: Zap) -> None:
    processo = zap.roda({"os-service": {"sem_resumo": True}}, "os-service")
    assert processo.returncode == 1
    assert "no summary line" in zap.linhas()["os-service"]


def test_zap_que_nao_consegue_varrer_reprova_com_o_status_dele(zap: Zap) -> None:
    processo = zap.roda({"os-service": {"codigo": 3}}, "os-service")
    assert processo.returncode == 1
    assert zap.linhas() == {"os-service": "FAILED (ZAP exit 3)"}


def test_zap_que_pendura_estoura_o_prazo_e_nao_esconde_os_outros(zap: Zap) -> None:
    processo = zap.roda({"os-service": {"dorme": 20}}, PRAZO_ZAP="1")
    assert processo.returncode == 1
    assert "ZAP baseline FAILED: os-service" in processo.stderr
    assert zap.linhas()["os-service"].startswith("FAILED (ZAP exit ")
    assert zap.linhas()["billing-service"] == "ok"
    assert zap.linhas()["execution-service"] == "ok"


def test_servico_desconhecido_sai_2_sem_chamar_o_docker(zap: Zap) -> None:
    processo = zap.roda({}, "os-service", "outro-service")
    assert processo.returncode == 2
    assert "unknown service outro-service" in processo.stderr
    assert zap.chamadas() == []


def regras_do_arquivo() -> list[tuple[str, str, str]]:
    """(id, acao, motivo) como o zap_common.load_config do ZAP le o arquivo."""
    regras = []
    for linha in REGRAS.read_text(encoding="utf-8").splitlines():
        if linha.startswith("#") or not linha.strip():
            continue
        # O ZAP recusa a linha com menos de tres campos separados por TAB.
        assert linha.count("\t") >= 2, linha
        regra, acao, motivo = linha.rstrip().split("\t", 2)
        regras.append((regra, acao, motivo))
    return regras


def test_regras_conf_no_formato_do_zap_com_motivo_em_toda_linha() -> None:
    regras = regras_do_arquivo()
    assert regras
    assert [r for r, _, _ in regras if not r.isdigit()] == []
    ids = [regra for regra, _, _ in regras]
    assert len(ids) == len(set(ids)), "regra repetida"
    for regra, acao, motivo in regras:
        assert acao in NIVEIS, regra
        assert len(motivo) > 10, f"{regra}: sem motivo"


def test_versao_nos_cabecalhos_reprova_e_o_resto_so_avisa_ou_e_ignorado() -> None:
    acoes = {regra: acao for regra, acao, _ in regras_do_arquivo()}
    # Server e X-Powered-By com versao: o Kong sem headers=off e o servico sem
    # --no-server-header voltariam a anunciar a pilha.
    assert acoes["10036"] == acoes["10037"] == "FAIL"
    assert [r for r, a in acoes.items() if a == "FAIL"] == ["10036", "10037"]
    assert {r for r, a in acoes.items() if a == "WARN"} == {
        "10020",
        "10021",
        "10035",
        "10038",
    }
    assert {r for r, a in acoes.items() if a == "IGNORE"} == {
        "10017",
        "90003",
        "10027",
        "10110",
        "10096",
        "10109",
        "10049",
        "10015",
    }


def test_readme_documenta_cada_regra_com_a_mesma_acao() -> None:
    linhas = {
        (m.group(1), m.group(2))
        for m in re.finditer(r"^\| (\d+) \| (FAIL|WARN|IGNORE|INFO) \|", README, re.M)
    }
    assert linhas == {(regra, acao) for regra, acao, _ in regras_do_arquivo()}
