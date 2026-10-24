"""Nenhuma Role do controller do Kong le Secrets (kong.yaml que o make deploy aplica).

O chart kong/kong 3.4.1 poe `list` e `watch` em Secrets na Role de cada
namespace de watchNamespaces, e o scripts/kong-render.sh tira a regra: a
plataforma nao usa Secret em Ingress nem em plugin. O `make manifests` confere
que o kong.yaml e o do render; este teste, que o render tirou a regra.
"""

from __future__ import annotations

from pathlib import Path

import yaml

KONG = Path(__file__).resolve().parents[1] / "k8s" / "base" / "kong"


def test_nenhuma_role_do_kong_lista_ou_observa_secrets() -> None:
    documentos = yaml.safe_load_all((KONG / "kong.yaml").read_text(encoding="utf-8"))
    roles = [d for d in documentos if d and d["kind"] in {"Role", "ClusterRole"}]
    # O controller tem uma Role por namespace vigiado, a de lideranca e a
    # ClusterRole: lista vazia seria um kong.yaml que o teste nao le.
    assert len(roles) >= 4
    com_secrets = [
        r["metadata"]["name"]
        for r in roles
        for regra in r["rules"]
        if "secrets" in regra.get("resources", [])
        and {"list", "watch"} & set(regra["verbs"])
    ]
    assert com_secrets == []
