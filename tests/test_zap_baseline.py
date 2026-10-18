"""ZAP baseline na borda (ADR-041).

O scripts/ci/zap-baseline.sh roda com um docker falso que escreve os relatorios
na pasta montada e imprime a saida que o zap-baseline.py imprime (a linha de
contagem, o "Total of N URLs" e o aviso de alvo inacessivel), e com um curl
falso para a conferencia do openapi.json antes do scan. O teste confere o
comando exato de cada servico, a recusa de borda fora do loopback, que FAIL de
regra, alvo que nao responde 200, scan sem pagina lida, ZAP que pendura e saida
sem resumo reprovam sem esconder os outros servicos, e a tabela do summary. O
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

# Os falsos guardam cada chamada, com o nome do programa na frente, num log so,
# que mostra tambem a ordem entre o curl e o docker.
REGISTRA = """
import json
import os
import sys
from pathlib import Path

falsos = Path(os.environ["FALSOS"])
args = sys.argv[1:]
with (falsos / "chamadas.jsonl").open("a") as log:
    log.write(json.dumps([Path(sys.argv[0]).name, *args]) + "\\n")
estado = json.loads((falsos / "estado.json").read_text())
"""

# docker falso: escreve os tres relatorios na pasta montada (-v <pasta>:/zap/wrk)
# e imprime o que o ZAP imprime conforme o estado do servico.
DOCKER_FALSO = f"""{REGISTRA}
import time

pasta = Path(args[args.index("-v") + 1].split(":")[0])
nome = args[args.index("-w") + 1].removeprefix("zap-").removesuffix(".md")
alvo = args[args.index("-t") + 1]
cfg = estado.get(nome, {{}})
time.sleep(cfg.get("dorme", 0))
for extensao in ("html", "json"):
    (pasta / f"zap-{{nome}}.{{extensao}}").write_text("{{}}")
(pasta / f"zap-{{nome}}.md").write_text(f"# ZAP Scanning Report de {{nome}}\\n")
if not cfg.get("sem_resumo"):
    print("Using the Automation Framework")
    print(f"Total of {{cfg.get('urls', 6)}} URLs")
    if cfg.get("acesso"):
        print(f"\\tJob spider {{cfg['acesso']}} URL {{alvo}} : detalhe do ZAP")
    if cfg.get("fail"):
        print("FAIL-NEW: HTTP Server Response Header [10036] x 4")
    fim = "WARN-INPROG: 0\\tINFO: 0\\tIGNORE: 1\\tPASS: 59"
    print(
        f"FAIL-NEW: {{cfg.get('fail', 0)}}\\tFAIL-INPROG: 0\\t"
        f"WARN-NEW: {{cfg.get('warn', 1)}}\\t{{fim}}"
    )
sys.exit(cfg.get("codigo", 0))
"""

# curl falso: o openapi.json do servico responde 200, salvo o codigo de saida do
# curl no estado (22 e o do -f com 404 ou 503).
CURL_FALSO = f"""{REGISTRA}
prefixos = {{"/os/": "os-service", "/billing/": "billing-service",
             "/execucao/": "execution-service"}}
nome = next(n for p, n in prefixos.items() if p in args[-1])
codigo = estado.get(nome, {{}}).get("curl", 0)
if codigo:
    print(f"curl: ({{codigo}}) The requested URL returned error: 404", file=sys.stderr)
sys.exit(codigo)
"""

# timeout falso: registra o prazo e roda o resto, sem esperar o relogio.
TIMEOUT_FALSO = f"""{REGISTRA}
os.execvp(args[1], args[1:])
"""


class Zap:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp = tmp_path
        self.binarios = tmp_path / "bin"
        self.binarios.mkdir()
        self.falso("docker", DOCKER_FALSO)
        self.falso("curl", CURL_FALSO)
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
                "ZAP_ALVO_DESCARTAVEL",
                "GITHUB_STEP_SUMMARY",
            }
        } | {
            "PATH": f"{self.binarios}{os.pathsep}{os.environ['PATH']}",
            "FALSOS": str(tmp_path),
            "GITHUB_STEP_SUMMARY": str(self.summary),
            "RELATORIOS": str(self.pasta),
        }

    def falso(self, nome: str, codigo: str) -> None:
        programa = self.binarios / nome
        programa.write_text(f"#!{sys.executable}\n{codigo}", encoding="utf-8")
        programa.chmod(0o755)

    def roda(
        self,
        estado: dict[str, Any],
        *servicos: str,
        cwd: Path | None = None,
        **ambiente: str,
    ) -> subprocess.CompletedProcess[str]:
        (self.tmp / "estado.json").write_text(json.dumps(estado), encoding="utf-8")
        return subprocess.run(  # noqa: S603  # nosec B603
            [str(SCRIPT), *servicos],
            env=self.env | ambiente,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )

    def todas(self) -> list[list[str]]:
        """Cada chamada aos falsos, em ordem, com o nome do programa na frente."""
        arquivo = self.tmp / "chamadas.jsonl"
        if not arquivo.exists():
            return []
        return [json.loads(linha) for linha in arquivo.read_text().splitlines()]

    def chamadas(self, programa: str = "docker") -> list[list[str]]:
        """Os argumentos de cada chamada ao programa, com o PID do script no
        nome do container trocado por <pid>."""
        return [
            [re.sub(r"^(zap-\S+-service)-\d+$", r"\1-<pid>", a) for a in c[1:]]
            for c in self.todas()
            if c[0] == programa
        ]

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
        "--init",
        "--rm",
        "--name",
        f"zap-{servico}-<pid>",
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
    """Borda fora do loopback (um Kong avulso numa rede Docker) so com o escape."""
    processo = zap.roda(
        {},
        "os-service",
        BORDA="https://kong:8443",
        ZAP_REDE="rede-de-teste",
        ZAP_ALVO_DESCARTAVEL="https://kong:8443",
    )
    assert processo.returncode == 0, processo.stderr
    esperado = comando(zap, "os-service", "https://kong:8443")
    esperado[esperado.index("host")] = "rede-de-teste"
    assert zap.chamadas() == [esperado]


@pytest.mark.parametrize(
    "borda",
    [
        "https://localhost",
        "https://localhost:8443",
        "http://127.0.0.1:9000",
        "https://[::1]:8443",
        "https://kong.localhost",
    ],
)
def test_borda_no_loopback_dispensa_o_escape(zap: Zap, borda: str) -> None:
    processo = zap.roda({}, "os-service", BORDA=borda)
    assert processo.returncode == 0, processo.stderr
    assert zap.chamadas() == [comando(zap, "os-service", borda)]


@pytest.mark.parametrize(
    "borda",
    [
        "https://staging.example.com",
        "https://localhost.example.com",
        "https://localhost@example.com",
        "https://example.com#@localhost",
        "https://example.com/https://localhost",
        "https://exemplolocalhost",
        "https://127.0.0.1.nip.io",
        "https://localhost/caminho",
        "ftp://localhost",
    ],
)
def test_borda_fora_do_loopback_sai_2_sem_chamar_nada(zap: Zap, borda: str) -> None:
    """O spider chama POST, PUT e DELETE: nada roda contra um alvo com dados."""
    processo = zap.roda({}, BORDA=borda)
    assert processo.returncode == 2
    assert f"refusing BORDA={borda}" in processo.stderr
    assert f"ZAP_ALVO_DESCARTAVEL={borda}" in processo.stderr
    assert zap.todas() == []
    assert not zap.pasta.exists()


def test_o_escape_vale_so_para_a_propria_borda(zap: Zap) -> None:
    processo = zap.roda(
        {},
        BORDA="https://staging.example.com",
        ZAP_ALVO_DESCARTAVEL="https://outra.example.com",
    )
    assert processo.returncode == 2
    assert zap.todas() == []


def test_o_curl_confere_o_alvo_antes_de_cada_scan(zap: Zap) -> None:
    zap.roda({})
    programas = [(c[0], c[-1]) for c in zap.todas()]
    alvos = [f"https://localhost{p}/openapi.json" for p in PREFIXOS.values()]
    assert [p for p, _ in programas] == ["curl", "docker"] * 3
    assert zap.chamadas("curl") == [
        ["-fsSk", "--max-time", "10", "-o", "/dev/null", alvo] for alvo in alvos
    ]


def test_alvo_que_nao_responde_200_reprova_sem_scan_e_varre_os_outros(
    zap: Zap,
) -> None:
    """openapi.json com 404 ou 503: o spider ainda contaria os 404 do Kong."""
    processo = zap.roda({"billing-service": {"curl": 22}})
    assert processo.returncode == 1
    assert "ZAP baseline FAILED: billing-service" in processo.stderr
    assert "curl: (22)" in processo.stderr
    assert "curl: (22)" in (zap.pasta / "zap-billing-service.log").read_text()
    assert [c[c.index("-t") + 1] for c in zap.chamadas()] == [
        "https://localhost/os/openapi.json",
        "https://localhost/execucao/openapi.json",
    ]
    assert zap.linhas() == {
        "os-service": "ok",
        "billing-service": "FAILED (target did not answer 200)",
        "execution-service": "ok",
    }


@pytest.mark.parametrize("aviso", ["error accessing", "failed to access"])
def test_zap_que_nao_le_o_alvo_reprova_mesmo_com_urls_lidas(
    zap: Zap, aviso: str
) -> None:
    processo = zap.roda({"os-service": {"acesso": aviso}}, "os-service")
    assert processo.returncode == 1
    assert zap.linhas() == {"os-service": "FAILED (ZAP could not read the target)"}


def test_relatorios_com_caminho_relativo_vao_ao_docker_como_absoluto(
    zap: Zap,
) -> None:
    """Com o caminho relativo, o docker leria um volume nomeado e recusaria."""
    processo = zap.roda({}, "os-service", cwd=zap.tmp, RELATORIOS="relatorios")
    assert processo.returncode == 0, processo.stderr
    montagem = zap.chamadas()[0][zap.chamadas()[0].index("-v") + 1]
    assert montagem == f"{zap.pasta.resolve()}:/zap/wrk"


@pytest.mark.parametrize(
    ("prazo", "segundos"), [({}, "300"), ({"PRAZO_ZAP": "7"}, "7")]
)
def test_o_prazo_envolve_cada_docker_run(
    zap: Zap, prazo: dict[str, str], segundos: str
) -> None:
    """Com o timeout do Linux no PATH (aqui, um falso que so registra)."""
    zap.falso("timeout", TIMEOUT_FALSO)
    zap.env.update(prazo)
    processo = zap.roda({})
    assert processo.returncode == 0, processo.stderr
    # So o docker run passa pelo timeout: o curl tem prazo proprio (--max-time).
    assert zap.chamadas("timeout") == [
        [segundos, "docker", *comando(zap, s)] for s in PREFIXOS
    ]


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


def test_resumo_sem_a_linha_total_de_urls_reprova(zap: Zap) -> None:
    """O falso imprime 'Total of None URLs', que nao casa: nada lido."""
    processo = zap.roda({"os-service": {"urls": None}}, "os-service")
    assert processo.returncode == 1
    assert "no URL scanned" in zap.linhas()["os-service"]


def test_uma_url_lida_basta(zap: Zap) -> None:
    processo = zap.roda({"os-service": {"urls": 1}}, "os-service")
    assert processo.returncode == 0, processo.stderr
    assert zap.linhas() == {"os-service": "ok"}


def test_dois_servicos_reprovados_saem_nomeados_juntos(zap: Zap) -> None:
    estado = {
        "os-service": {"codigo": 1, "fail": 1},
        "execution-service": {"codigo": 3},
    }
    processo = zap.roda(estado)
    assert processo.returncode == 1
    assert "ZAP baseline FAILED: os-service execution-service" in processo.stderr


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
    assert zap.todas() == []


def regras_do_arquivo() -> list[tuple[str, str, str]]:
    """(id, acao, motivo) como o zap_common.load_config do ZAP le o arquivo."""
    regras = []
    for linha in REGRAS.read_text(encoding="utf-8").splitlines():
        if linha.startswith("#") or not linha.strip():
            continue
        # O load_config do ZAP separa a linha em exatamente tres campos por TAB:
        # com menos, recusa o arquivo; com dois TABs a mais, quebra o scan.
        assert linha.count("\t") == 2, linha
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


def test_cabecalhos_reprovam_so_o_hsts_avisa_e_so_o_10015_e_ignorado() -> None:
    acoes = {regra: acao for regra, acao, _ in regras_do_arquivo()}
    # Server e X-Powered-By com versao: o Kong sem headers=off e o servico sem
    # --no-server-header voltariam a anunciar a pilha. Dos cabecalhos de
    # seguranca, o 10021 e o guarda da API JSON; o 10020 e o 10038 so avaliam
    # resposta HTML e ficam em FAIL por valerem se um servico servir HTML.
    assert {r for r, a in acoes.items() if a == "FAIL"} == {
        "10036",
        "10037",
        "10020",
        "10021",
        "10038",
    }
    # O HSTS falta nos 404 que o Kong gera sozinho, sem rota casada.
    assert {r for r, a in acoes.items() if a == "WARN"} == {"10035"}
    # Ignorada so a regra que o relatorio mostrou (o Cache-Control no-store).
    assert {r for r, a in acoes.items() if a == "IGNORE"} == {"10015"}


def test_readme_documenta_cada_regra_com_a_mesma_acao() -> None:
    linhas = {
        (m.group(1), m.group(2))
        for m in re.finditer(r"^\| (\d+) \| (FAIL|WARN|IGNORE|INFO) \|", README, re.M)
    }
    assert linhas == {(regra, acao) for regra, acao, _ in regras_do_arquivo()}
