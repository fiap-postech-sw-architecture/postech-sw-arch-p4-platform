# Cobertura publicada

Estado: medida anterior ao congelamento, em runs de 19 e 20/10/2026. Os testes de cada serviço rodaram em jobs Linux do GitHub Actions, com bancos descartáveis de integração. A cobertura soma linhas e ramos; o enunciado exige 80% e os serviços adotam gate de 95%. O quality gate do SonarQube está na [seção SonarQube](#sonarqube). As tabelas abaixo preservam a medida depois que os artefatos expiram.

## Runs citados

Cada serviço tem um run só, o mesmo que a seção Cobertura do README dele cita. As tabelas são as do README, geradas por `scripts/cobertura_resumo.py` a partir do `coverage.xml` desse run.

| Serviço | Run | Commit medido | Relação com a `main` de 20/10/2026 |
|---|---|---|---|
| OS Service | [39233375064](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-os-service/actions/runs/39233375064), CD da `main` | `5e4ed2a1c2d74bdc65cc207c3f5a208b4ea672ca` | a `main` (`ffcc2c1`) passou o mesmo gate no [CD 39357871773](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-os-service/actions/runs/39357871773) |
| Billing Service | [39353965791](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-billing-service/actions/runs/39353965791), CI do [Billing #18](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-billing-service/pull/18) | `b53bb38ab04bbc3ff1d1f304913c92d7266c5d54` | mesmo `src/` da `main` (`f99e164`) |
| Execution Service | [39235791515](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-execution-service/actions/runs/39235791515), CI da [Execução #15](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-execution-service/pull/15) | `91a05bfa6c57055746bf61cf205778183a8b1542` | mesmo `src/` da `main` (`a1ede85`) |

A coleta final repete a medida sobre os commits das tags.

## OS Service

**99,62% no gate** (linhas e ramos somados): 6.254 linhas, 6.238 cobertas (99,7%), e 928 ramos, 917 cobertos (98,8%), medidos no [run 39233375064 do CI](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-os-service/actions/runs/39233375064). Tabelas geradas por `scripts/cobertura_resumo.py` a partir do `coverage.xml` desse run.

| Contexto | Linhas | Cobertas | Cobertura |
|---|---:|---:|---:|
| `src` (processos) | 236 | 231 | 97,9% |
| `src/autenticacao` | 562 | 562 | 100,0% |
| `src/cliente_veiculo` | 903 | 902 | 99,9% |
| `src/compartilhado` | 1.854 | 1.844 | 99,5% |
| `src/ordem_servico` | 2.699 | 2.699 | 100,0% |
| **total** | 6.254 | 6.238 | 99,7% |

| Camada | Linhas | Cobertas | Cobertura |
|---|---:|---:|---:|
| `dominio` | 942 | 939 | 99,7% |
| `aplicacao` | 1.788 | 1.788 | 100,0% |
| `infraestrutura` | 2.491 | 2.487 | 99,8% |
| `interfaces` | 797 | 793 | 99,5% |

## Billing Service

**100,00% no gate** (linhas e ramos somados): 4.536 linhas, 4.536 cobertas (100,0%), e 624 ramos, 624 cobertos (100,0%), medidos pelo `make test` com o `src/` do [run 39353965791 do CI](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-billing-service/actions/runs/39353965791). Tabelas geradas por `scripts/cobertura_resumo.py` a partir do `coverage.xml` desse `make test`.

| Contexto | Linhas | Cobertas | Cobertura |
|---|---:|---:|---:|
| `src` (processos) | 568 | 568 | 100,0% |
| `src/compartilhado` | 1.574 | 1.574 | 100,0% |
| `src/orcamento` | 672 | 672 | 100,0% |
| `src/pagamento` | 1.285 | 1.285 | 100,0% |
| `src/precos` | 437 | 437 | 100,0% |
| **total** | 4.536 | 4.536 | 100,0% |

| Camada | Linhas | Cobertas | Cobertura |
|---|---:|---:|---:|
| `dominio` | 895 | 895 | 100,0% |
| `aplicacao` | 773 | 773 | 100,0% |
| `infraestrutura` | 1.652 | 1.652 | 100,0% |
| `interfaces` | 648 | 648 | 100,0% |

## Execution Service

Tabela gerada a partir do `coverage.xml` do [run 39235791515 do CI](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-execution-service/actions/runs/39235791515).

### Cobertura de testes: 100.0% no gate (linhas e ramos)

100.0% de linhas e 100.0% de ramos.

| Pacote | Linhas | Cobertas | Cobertura |
|---|---:|---:|---:|
| `src` | 318 | 318 | 100.0% |
| `src/compartilhado/aplicacao` | 59 | 59 | 100.0% |
| `src/compartilhado/dominio` | 144 | 144 | 100.0% |
| `src/compartilhado/infraestrutura` | 1324 | 1324 | 100.0% |
| `src/compartilhado/interfaces` | 236 | 236 | 100.0% |
| `src/diagnostico/aplicacao` | 127 | 127 | 100.0% |
| `src/diagnostico/dominio` | 177 | 177 | 100.0% |
| `src/diagnostico/infraestrutura` | 127 | 127 | 100.0% |
| `src/diagnostico/interfaces` | 92 | 92 | 100.0% |
| `src/estoque/aplicacao` | 155 | 155 | 100.0% |
| `src/estoque/dominio` | 226 | 226 | 100.0% |
| `src/estoque/infraestrutura` | 105 | 105 | 100.0% |
| `src/estoque/interfaces` | 113 | 113 | 100.0% |
| `src/execucao/aplicacao` | 173 | 173 | 100.0% |
| `src/execucao/dominio` | 122 | 122 | 100.0% |
| `src/execucao/infraestrutura` | 99 | 99 | 100.0% |
| `src/execucao/interfaces` | 84 | 84 | 100.0% |
| **total** | 3681 | 3681 | 100.0% |

## SonarQube

Cada CI sobe um SonarQube efêmero no runner, analisa o código com o `coverage.xml` do job `test` e reprova o run se o quality gate falhar. O gate versionado em `.sonar/quality-gate.json` é o mesmo nos três serviços: cobertura de pelo menos 80%, no máximo 3% de linhas duplicadas e nota A em confiabilidade, segurança e manutenibilidade. Resultado no último CD da `main` de cada serviço, tirado do log do job `ci / sonarqube`:

| Serviço | Run | Commit | Arquivos indexados | Quality gate |
|---|---|---|---:|---|
| OS Service | [39357871773](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-os-service/actions/runs/39357871773) | `ffcc2c12645642410a748fa73a5c2a807c8a0a9b` | 352 | aprovado (`QUALITY GATE STATUS: PASSED`, 20/10/2026 02:24 UTC) |
| Billing Service | [39358245264](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-billing-service/actions/runs/39358245264) | `f99e1646398f18b68e3e65b2633cea8b1976bac8` | 166 | aprovado (`QUALITY GATE STATUS: PASSED`, 20/10/2026 02:33 UTC) |
| Execution Service | [39357862805](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-execution-service/actions/runs/39357862805) | `a1ede8551f50a34ac9228f36c38d5f1a6da6d581` | 186 | aprovado (`QUALITY GATE STATUS: PASSED`, 20/10/2026 02:20 UTC) |

As medidas de cada análise (bugs, vulnerabilidades, code smells, duplicação e cobertura) ficam no summary do job e no artefato `sonarqube` do run, que expira em 90 dias.

## Reprodução

Baixar `relatorios-de-teste` com `gh run download <run> --repo <organização/repositório> --name relatorios-de-teste --dir <destino>`. Nos checkouts dos SHAs indicados, OS e Billing geram o trecho oficial com `python scripts/cobertura_resumo.py coverage.xml --readme README.md --run <URL>`; a Execução usa `python scripts/cobertura_resumo.py coverage.xml README.md <URL>`. As tabelas deste relatório são saídas literais desses geradores.

Os limites de medição e os módulos omitidos estão no README e na configuração de cobertura de cada serviço.
