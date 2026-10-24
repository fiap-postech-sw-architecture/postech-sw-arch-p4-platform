# Proteção da `main`

Conferido em 20/10/2026 e de novo em 23 e 24/10/2026 com a API do GitHub, nos quatro repositórios da fase 4; a leitura de 24/10 (GET de `rulesets` e do detalhe de cada um) deu a tabela do A8. O ruleset da `main` é visível a quem tem leitura no repositório, e é ele que exige os checks ([ADR-042](../../../arquitetura/adr/fase4/042-cicd-e-deploy-kubernetes.md)).

| Repositório | Ruleset | Criado em (Brasília) | Checks obrigatórios |
|---|---|---|---|
| OS Service | [24594457](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-os-service/rules/24594457) | 06/10/2026, 13:50 | `lint`, `type-check`, `security`, `test`, `sonarqube`, `build`, `pip-audit`, `gitleaks`, `trivy` |
| Billing Service | [24594468](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-billing-service/rules/24594468) | 06/10/2026, 13:50 | `lint`, `type-check`, `security`, `test`, `sonarqube`, `build`, `pip-audit`, `gitleaks`, `trivy` |
| Execution Service | [24594458](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-execution-service/rules/24594458) | 06/10/2026, 13:50 | `lint`, `type-check`, `security`, `test`, `sonarqube`, `build`, `pip-audit`, `gitleaks`, `trivy` |
| Plataforma | [24599837](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-platform/rules/24599837) | 06/10/2026, 14:54 | `manifests`, `contratos`, `gitleaks`, `deploy-kind` |

Os quatro rulesets estão ativos, valem para a branch padrão e não têm exceção: `bypass_actors` vazio e `current_user_can_bypass` igual a `never`, conferidos em 23 e 24/10/2026. Todos têm as mesmas regras: pull request obrigatório, merge só por squash, conversas resolvidas antes do merge, histórico linear, sem force push e sem exclusão da branch. A aprovação de revisão não é exigida (`Required approvals: 0`): o ruleset exige o PR e os checks.

Revisão: em 24/10/2026, 113 dos 122 PRs mesclados do grupo (32 no OS Service, 24 no Billing, 21 na Execução e 45 no `platform`) trazem no corpo o relato da revisão (a caixa "Revisão deep" marcada, uma seção de revisão ou o registro da revisão independente); nos outros nove (o #1 de cada repositório, OS #22 e #26, Billing #23 e Execução #16 e #20) a caixa "Revisão deep" está desmarcada ou ausente, e os do Dependabot (3, 7, 5 e 1) só passam pelos checks. Conferido em cada repositório com `gh pr list --state merged --limit 200 --json number,author,body`.

## Quando o ruleset veio

Os repositórios foram criados em 06/10/2026, às 11:55 (14:55 UTC). O PR #1 de cada um, "base do repositório", foi mesclado entre 11:59 e 12:00, e os rulesets foram criados depois: às 13:50 no OS Service, no Billing e na Execução, e às 14:54 no `platform`. Por isso a frase do documento é "ganharam o ruleset no dia da criação": o `Initial commit` e o PR #1 são anteriores a ele. Todo commit depois do `Initial commit` entrou por PR, o do PR #1 inclusive.

## Commits da `main`

Capturas de 23/10/2026, entre 15:59 e 16:04 UTC. Em todos os repositórios só o `Initial commit` não tem o `(#N)` do PR no título.

| Repositório | Commits | Com `(#N)` | `Initial commit` |
|---|---|---|---|
| OS Service | 30 | 29 | `4ad6f3d` |
| Billing Service | 28 | 27 | `68f326d` |
| Execution Service | 24 | 23 | `b77d564` |
| Plataforma | 39 | 38 | `16f93ce` |

A versão anterior do documento de entrega contava 26, 24, 20 e 32 commits, os que cada `main` tinha nos CDs de 20/10/2026 (plataforma `d703200`, OS Service `3ce582b`, Billing `76b5f9b` e Execução `5b1bef4`). A conta sobe a cada merge. Os quatro commits iniciais estão no [registro de evidências](README.md#coleta-e-conferência-reproduzíveis), e o `verificar --final` só aceita esses.

## Prints do Anexo A, A8

- [protecao-ruleset-os-service-2026-10-23.png](protecao-ruleset-os-service-2026-10-23.png): página do ruleset do OS Service, aberta sem login, com os dois "Show additional settings" abertos; capturada em 23/10/2026, 15:59:49 UTC. A página pública não mostra a lista de exceções (o cabeçalho traz "Sign in"); as exceções vêm da API, na tabela acima. O recorte, de 1.400 x 1.893 px e sem reamostragem, termina na regra "Block force pushes": abaixo dela a página traz a seção "Restrictions", das restrições de metadados de commit (mensagem, autor, nome do ramo), vazia nos quatro rulesets, cujas regras, pela API, são só `deletion`, `non_fast_forward`, `required_linear_history`, `pull_request` e `required_status_checks`.
- [protecao-commits-main-os-service-2026-10-23.png](protecao-commits-main-os-service-2026-10-23.png): lista dos 30 commits da `main` do OS Service, capturada às 15:59:22 UTC. O X de CI do commit `28d6240` (#15, 19/10) foi o job `security-scan / trivy` do run depois do merge: `TOOMANYREQUESTS` ao baixar o banco de vulnerabilidades, limite do registro de imagens e não achado de segurança. Os nove checks do PR #15 passaram, `trivy` inclusive (conferido pela API do GitHub em 23/10/2026).
- [protecao-ruleset-billing-service-2026-10-23.png](protecao-ruleset-billing-service-2026-10-23.png): o mesmo ruleset no Billing (24594468), capturado às 16:04:23 UTC, com o mesmo recorte.

Para repetir a conferência de um repositório, com o número do ruleset da tabela:

```bash
gh api repos/fiap-postech-sw-architecture/postech-sw-arch-p4-os-service/rulesets/24594457 --jq '{enforcement, excecoes: (.bypass_actors | length), regras: [.rules[].type], checks: [.rules[] | select(.type == "required_status_checks") | .parameters.required_status_checks[].context]}'
```
