"""A collection executa assertions reais e termina suas esperas sem expor dados."""

from __future__ import annotations

import base64
import json
import shutil
import subprocess  # nosec B404
from pathlib import Path
from typing import Any, cast

import pytest

RAIZ = Path(__file__).resolve().parents[2]
COLLECTION = RAIZ / "docs/api/fluxo-completo.postman_collection.json"
HISTORICO = [
    "recebida",
    "em_diagnostico",
    "aguardando_aprovacao",
    "aguardando_pagamento",
    "aguardando_execucao",
    "em_execucao",
    "finalizada",
    "entregue",
]
# Executa o script do artefato: assert do Node valida os booleanos do pm.expect,
# sem biblioteca ou copia da logica de negocio no teste.
VM = r"""
const vm = require('node:vm'), assert = require('node:assert/strict');
let raw = ''; process.stdin.on('data', x => raw += x);
process.stdin.on('end', () => {
  const p = JSON.parse(raw), vars = new Map(Object.entries(p.vars || {}));
  const out = {failed: [], passed: [], next: 'automatico', waits: []};
  const pm = {
    variables: {get: k => vars.get(k), set: (k,v) => vars.set(k,v),
      unset: k => vars.delete(k),
      replaceIn: s => s.replace(/{{(.*?)}}/g, (_,k) => vars.get(k) || '')},
    info: {requestName: p.name, requestId: p.name},
    response: {code: p.code || 200, json: () => p.body,
      headers: {get: k => (p.headers || {})[k]}},
    execution: {setNextRequest: v => out.next = v},
    test: (name, f) => {try {f(); out.passed.push(name)} catch {out.failed.push(name)}},
    expect: v => ({to: {be: {get true() {assert.equal(v, true)}}}})
  };
  try {vm.runInNewContext(p.script, {pm, require, Date: {now: () => p.now || 1000},
    setTimeout: (f, ms) => {out.waits.push(ms); f()}}, {timeout: 1000})}
  catch (e) {out.error = e.name}
  out.vars = Object.fromEntries(vars); process.stdout.write(JSON.stringify(out));
});
"""


def collection() -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(COLLECTION.read_text()))


def executar_script(
    nome: str,
    corpo: Any,
    *,
    codigo: int = 200,
    variaveis: dict[str, Any] | None = None,
    agora: int = 1000,
    headers: dict[str, str] | None = None,
    fase: str = "test",
) -> dict[str, Any]:
    artefato = collection()
    script = "\n".join(
        next(e for e in artefato["event"] if e["listen"] == fase)["script"]["exec"]
    )
    entrada = json.dumps(
        {
            "script": script,
            "name": nome,
            "body": corpo,
            "code": codigo,
            "vars": variaveis or {},
            "now": agora,
            "headers": headers,
        }
    )
    node = shutil.which("node")
    assert node is not None
    r = subprocess.run(  # noqa: S603  # nosec B603
        [node, "-e", VM],
        input=entrada,
        text=True,
        capture_output=True,
        check=True,
        timeout=5,
    )
    return cast("dict[str, Any]", json.loads(r.stdout))


def test_artefato_v21_rotas_papeis_e_variaveis_sem_credencial() -> None:
    d = collection()
    assert d["info"]["schema"].endswith("/v2.1.0/collection.json")
    itens = d["item"]
    assert len({x["id"] for x in itens}) == len(itens)
    assert len({x["name"] for x in itens}) == len(itens)
    por_nome = {x["name"]: x["request"] for x in itens}
    assert por_nome["Abrir OS"]["auth"]["bearer"][0]["value"] == "{{jwt_atendente}}"
    assert (
        por_nome["Iniciar diagnostico"]["auth"]["bearer"][0]["value"]
        == "{{jwt_mecanico}}"
    )
    assert por_nome["Metricas admin"]["auth"]["bearer"][0]["value"] == "{{jwt_admin}}"
    assert por_nome["Aprovar orcamento"]["auth"]["type"] == "noauth"
    assert por_nome["Aprovar pagamento"]["auth"]["type"] == "noauth"
    assert por_nome["Metricas sem token"]["auth"]["type"] == "noauth"
    assert por_nome["Metricas admin"]["url"].endswith(
        "/os/api/v1/ordens-de-servico/metricas"
    )
    assert all(x["value"] in ("", "https://localhost") for x in d["variable"])
    for request in por_nome.values():
        assert request["url"].startswith(
            ("{{baseUrl}}/", "{{mailpitUrl}}/", "{{link_decisao}}", "{{checkout_url}}")
        )
        assert "/admin/" not in request["url"]


@pytest.mark.parametrize(
    "mudancas", [HISTORICO[:-1], list(reversed(HISTORICO)), [*HISTORICO, "entregue"]]
)
def test_historico_incompleto_invertido_ou_duplicado_reprova(
    mudancas: list[str],
) -> None:
    r = executar_script(
        "Historico",
        {"ordem_id": "os", "mudancas": [{"para": x, "de": None} for x in mudancas]},
        variaveis={"ordem_id": "os"},
    )
    assert r["failed"]
    assert "error" not in r


def test_historico_exige_os_e_oito_status_exatos() -> None:
    r = executar_script(
        "Historico",
        {
            "ordem_id": "os",
            "mudancas": [
                {"para": x, "de": None if i == 0 else HISTORICO[i - 1]}
                for i, x in enumerate(HISTORICO)
            ],
        },
        variaveis={"ordem_id": "os"},
    )
    assert not r["failed"]
    assert "error" not in r
    assert r["passed"]


@pytest.mark.parametrize("status", ["cancelada", "inventada"])
def test_poll_reprova_estado_terminal_ou_desconhecido(status: str) -> None:
    r = executar_script(
        "OS em_diagnostico",
        {"id": "os", "status": status},
        variaveis={"ordem_id": "os"},
    )
    assert r["failed"]
    assert r["next"] is None


def test_poll_espera_evento_e_termina_quando_observado() -> None:
    r = executar_script(
        "OS em_diagnostico",
        {"id": "os", "status": "recebida"},
        variaveis={"ordem_id": "os"},
    )
    assert r["next"] == "OS em_diagnostico"
    assert not r["failed"]
    r = executar_script(
        "OS em_diagnostico",
        {"id": "os", "status": "em_diagnostico"},
        variaveis=r["vars"],
    )
    assert r["next"] == "automatico"
    assert not r["failed"]


@pytest.mark.parametrize(("agora", "contador"), [(31001, 1), (1001, 60)])
def test_poll_esgotado_reprova(agora: int, contador: int) -> None:
    r = executar_script(
        "OS em_diagnostico",
        {"id": "os", "status": "recebida"},
        variaveis={"ordem_id": "os", "poll_inicio": 1000, "poll_tentativas": contador},
        agora=agora,
    )
    assert r["failed"]
    assert r["next"] is None


def test_lista_busca_segunda_pagina_sem_reiniciar_prazo() -> None:
    r = executar_script(
        "Fila diagnostico",
        {"items": [{"ordem_id": "outro"}], "total": 2, "offset": 0, "limit": 1},
        variaveis={"ordem_id": "os", "offset": 0},
    )
    assert r["vars"]["offset"] == 1
    inicio = r["vars"]["poll_inicio"]
    r = executar_script(
        "Fila diagnostico",
        {"items": [{"ordem_id": "os"}], "total": 2, "offset": 1, "limit": 1},
        variaveis=r["vars"],
    )
    assert not r["failed"]
    assert r["next"] == "automatico"
    assert inicio == 1000
    assert r["vars"]["offset"] == 0


def test_lista_ausente_nao_reinicia_deadline() -> None:
    r = executar_script(
        "Fila diagnostico",
        {"items": [], "total": 0, "offset": 0, "limit": 100},
        variaveis={"ordem_id": "os", "poll_inicio": 1000},
        agora=31001,
    )
    assert r["failed"]
    assert r["next"] is None


def test_429_login_respeita_retry_after_e_prazo() -> None:
    r = executar_script("Login admin", {}, codigo=429, headers={"Retry-After": "2"})
    assert r["waits"] == [2000]
    assert r["next"] == "Login admin"
    r = executar_script("Login admin", {}, codigo=429, variaveis=r["vars"], agora=71001)
    assert r["failed"]
    assert r["next"] is None


def test_503_nao_repete_escrita() -> None:
    r = executar_script("Abrir OS", {}, codigo=503)
    assert r["failed"]
    assert r["next"] is None


@pytest.mark.parametrize(
    "url",
    [
        "https://outro.test/billing/simulador/checkout/p?token=segredo",
        "https://localhost@outro.test/billing/simulador/checkout/p?token=segredo",
        "https://localhost/caminho?token=segredo",
    ],
)
def test_checkout_externo_ou_path_errado_reprova_antes_de_chamar(url: str) -> None:
    r = executar_script(
        "Pagamento solicitado",
        {
            "id": "p",
            "ordem_id": "os",
            "orcamento_id": "orc",
            "valor": "210.00",
            "moeda": "BRL",
            "provedor": "simulado",
            "status": "SOLICITADO",
            "checkout_url": url,
        },
        variaveis={
            "baseUrl": "https://localhost",
            "ordem_id": "os",
            "orcamento_id": "orc",
            "pagamento_id": "p",
        },
    )
    assert r["failed"]
    assert r["next"] is None
    assert "checkout_url" not in r["vars"]


@pytest.mark.parametrize("falha", ["chave", "soma", "media"])
def test_metricas_incoerentes_reprovam(falha: str) -> None:
    por_status = dict.fromkeys([*HISTORICO, "cancelada"], 0)
    por_status["entregue"] = 1
    b = {
        "total": 1,
        "por_status": por_status,
        "tempo_medio_por_status_segundos": {"recebida": 1.0},
    }
    if falha == "chave":
        del por_status["cancelada"]
    if falha == "soma":
        b["total"] = 2
    if falha == "media":
        b["tempo_medio_por_status_segundos"] = {"recebida": -1}
    r = executar_script("Metricas admin", b)
    assert r["failed"]


def test_metricas_aceitam_outros_dados_e_media_esparsa() -> None:
    por_status = dict.fromkeys([*HISTORICO, "cancelada"], 0)
    por_status.update(entregue=2, cancelada=3)
    r = executar_script(
        "Metricas admin",
        {
            "total": 5,
            "por_status": por_status,
            "tempo_medio_por_status_segundos": {"recebida": 0},
        },
    )
    assert not r["failed"]
    assert "error" not in r
    assert r["passed"]


def test_pagamento_ainda_sem_resumo_preserva_deadline() -> None:
    r = executar_script(
        "OS aguardando_pagamento",
        {"id": "os", "status": "aguardando_pagamento", "pagamento": None},
        variaveis={"ordem_id": "os", "poll_inicio": 1000},
        agora=31001,
    )
    assert r["failed"]
    assert r["next"] is None


def test_email_com_link_de_outra_origem_nao_e_seguido() -> None:
    link = "https://outro.test/billing/api/v1/publico/orcamentos/hmac-secreto"
    r = executar_script(
        "Ler email",
        {"Text": link},
        variaveis={"baseUrl": "https://localhost", "os_link_decisao": link},
    )
    assert r["failed"]
    assert r["next"] is None
    assert "link_decisao" not in r["vars"]


def test_runner_publica_so_campos_permitidos_e_remove_raw(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from e2e.apoio import newman
    from e2e.apoio.newman import executar_newman

    artefato = collection()
    ids = [i["id"] for i in artefato["item"]]
    segredo = "senha-particular-do-kind"
    jwt = (
        ".".join(
            base64.urlsafe_b64encode(json.dumps(parte).encode()).decode().rstrip("=")
            for parte in ({"alg": "RS256"}, {"sub": "pessoa-sintetica"})
        )
        + ".assinatura"
    )
    hmac = "hmac-privado-do-checkout"
    vistos: list[Path] = []

    def processo(argv: list[str], prazo: float, **opcoes: Any) -> int:
        assert prazo == 630
        assert segredo not in " ".join(argv)
        assert jwt not in " ".join(argv)
        assert "MP_ACCESS_TOKEN" not in opcoes["env"]
        env = Path(argv[argv.index("--environment") + 1])
        vistos.append(env.parent)
        assert env.stat().st_mode & 0o777 == 0o600
        runtime = json.loads(env.read_text())
        assert any(x["value"] == segredo for x in runtime["values"])
        report = {
            "environment": {"values": [{"value": segredo}]},
            "run": {
                "stats": {"assertions": {"total": len(ids), "failed": 0}},
                "failures": [],
                "executions": [
                    {
                        "item": {"id": identificador, "name": segredo},
                        "request": {"url": hmac},
                        "response": {
                            "code": 200,
                            "responseTime": 2,
                            "stream": {"data": list(jwt.encode())},
                        },
                        "assertions": [{"assertion": "HTTP esperado"}],
                    }
                    for identificador in ids
                ],
            },
        }
        Path(argv[argv.index("--reporter-json-export") + 1]).write_text(
            json.dumps(report)
        )
        return 0

    monkeypatch.setattr(newman, "_rodar", processo)
    monkeypatch.setenv("MP_ACCESS_TOKEN", "nao-passar-ao-filho")
    monkeypatch.setattr(newman, "_conferir_versao", lambda *_: None)
    with pytest.raises(AssertionError, match="Newman reprovou"):
        executar_newman(
            {"admin_senha": segredo, "cpf": "12345678909", "placa": "ABC1D23"},
            pacote="newman@6.2.3",
            relatorios=tmp_path,
        )
    texto = "\n".join(f.read_text() for f in tmp_path.iterdir())
    assert all(x not in texto for x in [segredo, jwt, hmac, "12345678909", "ABC1D23"])
    assert not any(p.exists() for p in vistos)
    resumo = json.loads((tmp_path / "resumo.json").read_text())
    assert resumo["resultado"] == "reprovado"
    assert len(resumo["requisicoes"]) == len(ids)


@pytest.mark.parametrize(
    ("saida", "bruto"), [(1, None), (0, "json invalido"), (0, "{}")]
)
def test_runner_falha_sem_dump_e_nao_aceita_run_vazio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, saida: int, bruto: str | None
) -> None:
    from e2e.apoio import newman

    def processo(argv: list[str], *_: Any, **__: Any) -> int:
        if bruto is not None:
            Path(argv[argv.index("--reporter-json-export") + 1]).write_text(bruto)
        return saida

    monkeypatch.setattr(newman, "_rodar", processo)
    monkeypatch.setattr(newman, "_conferir_versao", lambda *_: None)
    with pytest.raises(AssertionError, match="Newman reprovou"):
        newman.executar_newman(
            {"admin_senha": "segredo-que-nao-pode-sair"},
            pacote="newman@6.2.3",
            relatorios=tmp_path,
        )
    assert (
        json.loads((tmp_path / "resumo.json").read_text())["resultado"] == "reprovado"
    )


def test_runner_versao_errada_reprova_sem_executar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from e2e.apoio import newman

    def versao_errada(*_: Any, **opcoes: Any) -> int:
        opcoes["stdout"].write(b"6.2.2\n")
        return 0

    monkeypatch.setattr(newman, "_rodar", versao_errada)
    with pytest.raises(AssertionError, match="versao"):
        newman.executar_newman({}, pacote="newman@6.2.3", relatorios=tmp_path)


@pytest.mark.parametrize(
    "ambiente",
    [
        {"E2E_MP_MODO": "real"},
        {"E2E_CONTEXTO_NAO_DESCARTAVEL": "kind-x"},
        {"E2E_URL": "https://outro.test"},
        {"KUBE_CONTEXT": "producao"},
    ],
)
def test_ambiente_perigoso_recusado_antes_de_fixtures(ambiente: dict[str, str]) -> None:
    from e2e.apoio.newman import conferir_ambiente

    with pytest.raises(AssertionError, match="kind local"):
        conferir_ambiente(ambiente)


def test_subprocesso_tem_timeout_e_mata_grupo(tmp_path: Path) -> None:
    import os
    import sys
    import time

    from e2e.apoio.newman import _rodar

    pid = tmp_path / "pid"
    programa = (
        "import subprocess,sys,time; "
        "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
        "open(sys.argv[1],'w').write(str(p.pid)); time.sleep(60)"
    )
    with pytest.raises(AssertionError, match="prazo"):
        _rodar([sys.executable, "-c", programa, str(pid)], 0.3, env=dict(os.environ))
    child = int(pid.read_text())
    for _ in range(30):
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        pytest.fail("filho ficou vivo apos o timeout")


def test_runner_recusa_origem_remota_antes_de_iniciar_processo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from e2e.apoio import newman

    def nao_iniciar(*_: Any) -> str:
        pytest.fail("iniciou ferramenta para origem remota")

    monkeypatch.setattr(newman, "_conferir_versao", nao_iniciar)
    with pytest.raises(AssertionError, match="kind local"):
        newman.executar_newman(
            {"baseUrl": "https://outro.test"},
            pacote="newman@6.2.3",
            relatorios=tmp_path,
        )


def test_runtime_real_newman_executa_script_e_valida_checkout_local(
    tmp_path: Path,
) -> None:
    import os
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from e2e.apoio.newman import _rodar

    class PagamentoHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            porta = cast("ThreadingHTTPServer", self.server).server_port
            base = f"http://127.0.0.1:{porta}"
            corpo = json.dumps(
                {
                    "id": "p",
                    "ordem_id": "os",
                    "orcamento_id": "orc",
                    "status": "SOLICITADO",
                    "valor": "210.00",
                    "moeda": "BRL",
                    "provedor": "simulado",
                    "checkout_url": base
                    + "/billing/simulador/checkout/p?token=token-local-do-teste",
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)

        def log_message(self, *_: Any) -> None:
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), PagamentoHandler) as servidor:
        thread = threading.Thread(target=servidor.serve_forever, daemon=True)
        thread.start()
        try:
            d = collection()
            d["item"] = [i for i in d["item"] if i["name"] == "Pagamento solicitado"]
            base = f"http://127.0.0.1:{servidor.server_port}"
            d["variable"] = [
                {"key": k, "value": v}
                for k, v in {
                    "baseUrl": base,
                    "pagamento_id": "p",
                    "ordem_id": "os",
                    "orcamento_id": "orc",
                }.items()
            ]
            arquivo = tmp_path / "collection.json"
            arquivo.write_text(json.dumps(d))
            raw = tmp_path / "raw.json"
            npx = shutil.which("npx")
            assert npx is not None
            saida = _rodar(
                [
                    npx,
                    "--yes",
                    "newman@6.2.3",
                    "run",
                    str(arquivo),
                    "--reporters",
                    "json",
                    "--reporter-json-export",
                    str(raw),
                    "--timeout",
                    "10000",
                    "--timeout-request",
                    "1000",
                    "--timeout-script",
                    "1000",
                    "--bail",
                    "failure",
                ],
                30,
                env={
                    k: v
                    for k, v in os.environ.items()
                    if k not in {"MP_ACCESS_TOKEN", "MP_WEBHOOK_SECRET"}
                },
            )
            report = json.loads(raw.read_text())
            assert saida == 0
            assert report["run"]["failures"] == []
            assert report["run"]["stats"]["assertions"]["total"] == 4
        finally:
            servidor.shutdown()
            thread.join(timeout=5)


def test_prazo_do_poll_comeca_antes_da_primeira_resposta_http() -> None:
    r = executar_script("OS em_diagnostico", {}, agora=1000, fase="prerequest")
    assert r["vars"]["poll_inicio"] == 1000


def test_checkout_recusa_json_em_vez_da_pagina_html() -> None:
    r = executar_script("Checkout", {}, headers={"Content-Type": "application/json"})
    assert r["failed"]
    assert r["next"] is None


def test_subprocesso_sigterm_encerra_filhos(tmp_path: Path) -> None:
    import os
    import signal
    import sys
    import threading

    from e2e.apoio.newman import _rodar
    from e2e_apoio.falsos import processo_vivo

    pid = tmp_path / "pid-sigterm"
    programa = (
        "import subprocess,sys,time; "
        "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
        "open(sys.argv[1],'w').write(str(p.pid)); time.sleep(60)"
    )
    terminou = threading.Event()

    def interromper() -> None:
        while not terminou.wait(0.01):
            if pid.exists():
                os.kill(os.getpid(), signal.SIGTERM)
                return

    anterior = signal.signal(signal.SIGTERM, signal.default_int_handler)
    thread = threading.Thread(target=interromper, daemon=True)
    thread.start()
    try:
        with pytest.raises(KeyboardInterrupt):
            _rodar([sys.executable, "-c", programa, str(pid)], 10, env=dict(os.environ))
    finally:
        terminou.set()
        thread.join(timeout=5)
        signal.signal(signal.SIGTERM, anterior)
    from e2e.apoio.espera import esperar

    esperar(
        lambda: not processo_vivo(int(pid.read_text())),
        prazo=3,
        intervalo=0.01,
        descricao="filho encerrado apos SIGTERM",
    )


def test_relatorio_inesperado_com_segredo_impede_gravacao(tmp_path: Path) -> None:
    from e2e.apoio.newman import _salvar
    from e2e.apoio.segredos import registrar

    segredo = "documento-privado-de-teste"
    registrar(segredo)
    (tmp_path / "inesperado.txt").write_text(segredo)
    with pytest.raises(AssertionError, match="recusado pela varredura"):
        _salvar(tmp_path, {"resultado": "reprovado", "requisicoes": []})
    assert not (tmp_path / "resumo.json").exists()
    assert not (tmp_path / "resumo.md").exists()


def test_prova_do_fluxo_publica_so_valores_fechados() -> None:
    from e2e.apoio.newman import _resumir

    corpos: dict[str, Any] = {
        "Historico": {"mudancas": [{"para": x} for x in HISTORICO]},
        "Estoque reservado": {
            "quantidade_disponivel": 10,
            "quantidade_reservada": 2,
            "quantidade_livre": 8,
        },
        "Estoque baixado": {
            "quantidade_disponivel": 8,
            "quantidade_reservada": 0,
            "quantidade_livre": 8,
        },
        "Pagamento confirmado": {
            "status": "CONFIRMADO",
            "valor": "210.00",
            "moeda": "BRL",
        },
        "Saga concluida": {"etapa": "concluida"},
        "Entregar": {"status": "entregue"},
        "Metricas admin": {
            "total": 2,
            "por_status": dict.fromkeys([*HISTORICO, "cancelada"], 0),
            "tempo_medio_por_status_segundos": {"recebida": 1},
        },
    }
    corpos["Metricas admin"]["por_status"]["entregue"] = 2
    d = collection()
    d["item"] = [i for i in d["item"] if i["name"] in corpos]
    bruto = {
        "run": {
            "stats": {"assertions": {"total": 7, "failed": 0}},
            "failures": [],
            "executions": [
                {
                    "item": {"id": i["id"]},
                    "response": {
                        "code": 200,
                        "responseTime": 1,
                        "stream": {
                            "data": list(
                                json.dumps(
                                    corpos[i["name"]]
                                    if i["name"] == "Metricas admin"
                                    else {
                                        **corpos[i["name"]],
                                        "documento": "dado-privado-sintetico",
                                        "checkout_url": "hmac-fora-da-prova",
                                    }
                                ).encode()
                            )
                        },
                    },
                    "assertions": [{"assertion": "HTTP esperado"}],
                }
                for i in d["item"]
            ],
        }
    }
    r = _resumir(bruto, d, 0)
    assert r["resultado"] == "aprovado"
    assert r["evidencias"]["Historico"] == HISTORICO
    assert r["evidencias"]["Estoque baixado"] == {
        "quantidade_disponivel": 8,
        "quantidade_reservada": 0,
        "quantidade_livre": 8,
    }
    assert r["evidencias"]["Pagamento confirmado"]["status"] == "CONFIRMADO"
    assert r["evidencias"]["Metricas admin"]["total"] == 2
    assert len(r["evidencias"]["Metricas admin"]["por_status"]) == 9
    assert "dado-privado-sintetico" not in json.dumps(r)
    assert "hmac-fora-da-prova" not in json.dumps(r)


@pytest.mark.parametrize("modo", ["timeout", "interrupcao"])
def test_preflight_versao_encerra_grupo_em_timeout_ou_interrupcao(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, modo: str
) -> None:
    import contextlib
    import os
    import signal
    import sys
    import threading

    from e2e.apoio import newman
    from e2e.apoio.espera import esperar
    from e2e_apoio.falsos import processo_vivo

    binario = tmp_path / "npx"
    meta = tmp_path / "processos.json"
    heartbeat = tmp_path / "heartbeat"
    filho = (
        "import sys,time; from pathlib import Path; p=Path(sys.argv[1]); "
        "\nwhile True:\n with p.open('a') as f: f.write('x')\n time.sleep(0.01)"
    )
    binario.write_text(
        f"#!{sys.executable}\n"
        "import json,os,subprocess,sys,time\n"
        "from pathlib import Path\n"
        "assert sys.argv[1:] == ['--yes','newman@6.2.3','--version']\n"
        f"p=subprocess.Popen([sys.executable,'-c',{filho!r},{str(heartbeat)!r}])\n"
        f"Path({str(meta)!r}).write_text(json.dumps({{'group':os.getpgrp(),'child':p.pid}}))\n"
        "print('6.2.3',flush=True)\ntime.sleep(60)\n"
    )
    binario.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    monkeypatch.setattr(newman, "_PRAZO_DA_VERSAO", 0.6, raising=False)
    terminou = threading.Event()

    def interromper() -> None:
        while not terminou.wait(0.01):
            if meta.exists() and heartbeat.exists():
                os.kill(os.getpid(), signal.SIGTERM)
                return

    anterior = signal.signal(signal.SIGTERM, signal.default_int_handler)
    thread = threading.Thread(target=interromper, daemon=True)
    try:
        if modo == "interrupcao":
            thread.start()
            with pytest.raises(KeyboardInterrupt):
                newman.executar_newman(
                    {}, pacote="newman@6.2.3", relatorios=tmp_path / "reports"
                )
        else:
            with pytest.raises(AssertionError):
                newman.executar_newman(
                    {}, pacote="newman@6.2.3", relatorios=tmp_path / "reports"
                )
        processos = json.loads(meta.read_text())
        esperar(
            lambda: not processo_vivo(processos["child"]),
            prazo=0.3,
            intervalo=0.01,
            descricao="filho do preflight encerrado",
        )
    finally:
        terminou.set()
        if thread.is_alive():
            thread.join(timeout=5)
        signal.signal(signal.SIGTERM, anterior)
        if meta.exists():
            with contextlib.suppress(ProcessLookupError):
                os.killpg(json.loads(meta.read_text())["group"], signal.SIGKILL)
