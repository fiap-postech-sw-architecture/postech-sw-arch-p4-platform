# Scans de segurança da fase 4

Detalhe da seção 10 do documento de entrega. Bateria da `main` de 20/10/2026, nos CDs do [OS Service](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-os-service/actions/runs/39449191933) (`3ce582b`), do [Billing](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-billing-service/actions/runs/39449241713) (`76b5f9b`), da [Execução](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-execution-service/actions/runs/39449216419) (`5b1bef4`) e do [`platform`](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-platform/actions/runs/39458619627) (`d703200`), cujo job `e2e` roda o ZAP contra os três serviços nesses commits. Os números foram lidos nos logs e nos artefatos desses runs, menos o SonarQube (CDs de 21/10, UTC).

| Ferramenta | OS Service | Billing | Execução |
|---|---|---|---|
| bandit 1.9.4 (SAST) | 0 achados | 0 achados | 0 achados |
| pip-audit 2.10.1 (SCA) | 70 dependências, nenhuma vulnerável | 57, nenhuma | 61, nenhuma |
| trivy 0.72.0 (imagem) | 73 alvos, 0 achados | 59 alvos, 0 | 64 alvos, 0 |
| gitleaks (histórico) | 26 commits, 0 vazamentos | 24 commits, 0 | 20 commits, 0 |
| SonarQube 26.9: linhas e cobertura | 11.111; 97,2% | 7.802; 98,8% | 6.078; 98,6% |
| SonarQube: bugs, vulnerabilidades, hotspots, duplicação | 0, 0, 0 e 0,0% | 0, 0, 0 e 0,0% | 0, 0, 0 e 0,0% |
| ZAP 2.17.0: URLs; FAIL, WARN e PASS | 38; 0, 1 e 59 | 38; 0, 2 e 58 | 24; 0, 1 e 59 |
| SBOM em SPDX | 171 pacotes | 147 pacotes | 162 pacotes |

O bandit reprova qualquer severidade, o pip-audit roda com `--strict` nas dependências de runtime e o trivy barra HIGH e CRITICAL com correção. O gitleaks do `platform` varreu 32 commits, sem vazamento, e um controle negativo confere que as regras pegam senha plantada. O kubeconform e o `trivy config` aprovaram os overlays `kind`, `kind-ci` e `k3s`. O ZAP varre a borda como um cliente de fora a vê, no kind descartável do job `e2e`, e chama cada operação do OpenAPI uma vez. Os avisos:

| Achado | Onde | Tratamento |
|---|---|---|
| 10035, `Strict-Transport-Security` ausente (WARN) | só nos 404 do próprio Kong (`/`, o prefixo, `/robots.txt` e `/sitemap.xml`) | o Kong sem rota casada não executa plugin |
| 10024, dado sensível na URL (WARN, só no Billing) | o checkout do simulador, com o `token` na query | só existe com `MP_MODE=simulado`; o Promtail mascara o `token=` |
| 10015, `Cache-Control` (IGNORE) | `saude` e `openapi.json`, com `no-store`, e o JWKS, com `max-age=600` | `no-store` já proíbe o cache |

Ficam em FAIL, e reprovam o job, o nome e a versão de produto nos cabeçalhos `Server` e `X-Powered-By` e a falta de `X-Content-Type-Options` ([regras](../../../../README.md#regras-e-allowlist)). O relatório da fase 1, com o OWASP Top 10, está no [repositório da fase 3](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p3/blob/main/docs/seguranca/relatorio-vulnerabilidades.md).
