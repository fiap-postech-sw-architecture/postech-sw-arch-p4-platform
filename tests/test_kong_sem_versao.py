"""Kong sem Server, Via e X-Kong-* nas respostas (headers=off, ADR-038).

O values.yaml e o kong.yaml que o make deploy aplica trazem o headers=off, e o
`reveladores` do scripts/smoke.sh, que prova no cluster que nenhum desses
cabecalhos sai, enxerga os tres em qualquer caixa e nao confunde o X-Request-ID
nem o rate limit com eles. A prova contra um Kong 3.9.3 de verdade esta no
README (Gateway): sem o headers=off, ele responde `Server: kong/3.9.3`.
"""

from __future__ import annotations

import re

# subprocess so roda trechos do scripts/smoke.sh, sem shell do usuario.
import subprocess  # nosec B404
from pathlib import Path

import pytest
import yaml

RAIZ = Path(__file__).resolve().parents[1]
KONG = RAIZ / "k8s" / "base" / "kong"


def test_kong_sem_server_via_e_x_kong_nas_respostas() -> None:
    """headers=off no values.yaml e no kong.yaml que o make deploy aplica."""
    values = yaml.safe_load((KONG / "values.yaml").read_text(encoding="utf-8"))
    assert values["env"]["headers"] == "off"
    for documento in yaml.safe_load_all(
        (KONG / "kong.yaml").read_text(encoding="utf-8")
    ):
        if documento and documento["kind"] == "Deployment":
            proxy = next(
                c
                for c in documento["spec"]["template"]["spec"]["containers"]
                if c["name"] == "proxy"
            )
            ambiente = {e["name"]: e.get("value") for e in proxy["env"]}
            assert ambiente["KONG_HEADERS"] == "off"
            return
    pytest.fail("sem Deployment do Kong no kong.yaml")


def reveladores(cabecalhos: str, tmp_path: Path) -> str:
    """A funcao `reveladores` do scripts/smoke.sh sobre uma resposta HTTP."""
    smoke = (RAIZ / "scripts" / "smoke.sh").read_text(encoding="utf-8")
    funcao = re.search(r"^reveladores\(\) \{\n.*?^\}\n", smoke, re.M | re.S)
    assert funcao is not None
    (tmp_path / "h").write_text(cabecalhos.replace("\n", "\r\n"), encoding="utf-8")
    return subprocess.run(  # noqa: S603  # nosec B603
        [
            "/bin/bash",
            "-c",
            f'TMP="$1"\n{funcao.group(0)}\nreveladores',
            "bash",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    ).stdout.strip()


def test_make_smoke_enxerga_server_via_e_x_kong_em_qualquer_caixa(
    tmp_path: Path,
) -> None:
    resposta = (
        "HTTP/1.1 200 OK\nContent-Type: application/json\nServer: kong/3.9.3\n"
        "x-kong-upstream-latency: 5\nVIA: 1.1 kong/3.9.3\nX-Kong-Request-Id: abc\n\n"
    )
    assert reveladores(resposta, tmp_path) == (
        "Server,x-kong-upstream-latency,VIA,X-Kong-Request-Id"
    )


def test_make_smoke_nao_confunde_os_cabecalhos_do_rate_limit_e_do_request_id(
    tmp_path: Path,
) -> None:
    resposta = (
        "HTTP/1.1 429 Too Many Requests\nX-Request-ID: abc\n"
        "X-RateLimit-Limit-Minute: 5\nRetry-After: 9\nServer-Timing: x\n"
        "X-Kongo: y\n\n"
    )
    assert reveladores(resposta, tmp_path) == "none"
