# Proteção da `main`

Conferido em 20/10/2026 com a API do GitHub, nos quatro repositórios da fase 4. O ruleset da `main` é visível a quem tem leitura no repositório, e é ele que exige os checks ([ADR-042](../../../arquitetura/adr/fase4/042-cicd-e-deploy-kubernetes.md)).

| Repositório | Ruleset | Checks obrigatórios |
|---|---|---|
| OS Service | [24594457](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-os-service/rules/24594457) | `lint`, `type-check`, `security`, `test`, `sonarqube`, `build`, `pip-audit`, `gitleaks`, `trivy` |
| Billing Service | [24594468](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-billing-service/rules/24594468) | `lint`, `type-check`, `security`, `test`, `sonarqube`, `build`, `pip-audit`, `gitleaks`, `trivy` |
| Execution Service | [24594458](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-execution-service/rules/24594458) | `lint`, `type-check`, `security`, `test`, `sonarqube`, `build`, `pip-audit`, `gitleaks`, `trivy` |
| Plataforma | [24599837](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-platform/rules/24599837) | `manifests`, `contratos`, `gitleaks`, `deploy-kind` |

Os quatro rulesets estão ativos, valem para a branch padrão e não têm exceção (nenhum ator pode ignorá-los). Todos têm as mesmas regras: pull request obrigatório, merge só por squash, conversas resolvidas antes do merge, histórico linear, sem force push e sem exclusão da branch.

Nos commits dos CDs de 20/10/2026 que o documento de entrega cita (plataforma `d703200`, OS Service `3ce582b`, Billing `76b5f9b` e Execução `5b1bef4`), a `main` tinha 32 commits na plataforma, 26 no OS Service, 24 no Billing e 20 na Execução. Todos entraram por pull request, exceto o commit inicial de cada repositório, que o GitHub cria junto com ele. Os quatro commits iniciais estão no [registro de evidências](README.md#coleta-e-conferência-reproduzíveis), e o `verificar --final` só aceita esses.

Para repetir a conferência de um repositório, com o número do ruleset da tabela:

```bash
gh api repos/fiap-postech-sw-architecture/postech-sw-arch-p4-os-service/rulesets/24594457 --jq '{enforcement, excecoes: (.bypass_actors | length), regras: [.rules[].type], checks: [.rules[] | select(.type == "required_status_checks") | .parameters.required_status_checks[].context]}'
```
