# Cobertura publicada — 19/10/2026

Estado: evidência de ensaio, anterior ao congelamento. Os testes de cada serviço rodaram em jobs Linux do GitHub Actions, com bancos descartáveis de integração. A cobertura soma linhas e ramos; o enunciado exige 80% e os serviços adotam gate de 95%. Os três jobs de SonarQube correspondentes foram aprovados. Tabelas e hashes abaixo preservam a medida após a expiração dos artefatos.

## Referência dos quatro repositórios

| Repositório | Commit na preparação deste relatório |
|---|---|
| Plataforma, base do pacote | `bfa8c72f1f8bf4c7af2994b73421137f00d02d64` |
| OS Service | `b88410a94d52b3a483a34fec7051962a8eb7e8dd` |
| Billing Service | `248c4071d357a867db1571081b012ff57753f834` |
| Execution Service | `c33824f801280a115e07e64b93185a64e9f700c1` |

Essa referência não representa uma única execução integrada. Cada job de cobertura mede somente o serviço e a fonte explicitados abaixo. A coleta final precisa ser repetida depois de todas as integrações e antes das tags.

## OS Service

Fonte declarada pelo run: `b88410a94d52b3a483a34fec7051962a8eb7e8dd`. [Execução e artefato `relatorios-de-teste`](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-os-service/actions/runs/39237955241). SHA256 do `coverage.xml`: `fed06faf89d60c199bd7c316330b52eefdbc60c7b562d7f4b1b2b653ecc7cb9a`.

**99,62% no gate** (linhas e ramos somados): 6.254 linhas, 6.238 cobertas (99,7%), e 928 ramos, 917 cobertos (98,8%), medidos no [run 39237955241 do CI](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-os-service/actions/runs/39237955241). Tabelas geradas por `scripts/cobertura_resumo.py` a partir do `coverage.xml` desse run.

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

Fonte declarada pelo run: `1789c27ed0e0259e2e42656e267869f19b20b54e`. [Execução e artefato `relatorios-de-teste`](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-billing-service/actions/runs/39193537819). SHA256 do `coverage.xml`: `ceb6fa947d0abcc7861783b759ecf8726a954dfa7a673af209deafc28b59c6ae`.

**100,00% no gate** (linhas e ramos somados): 4.516 linhas, 4.516 cobertas (100,0%), e 618 ramos, 618 cobertos (100,0%), medidos pelo `make test` com o `src/` do [run 39193537819 do CI](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-billing-service/actions/runs/39193537819). Tabelas geradas por `scripts/cobertura_resumo.py` a partir do `coverage.xml` desse `make test`.

| Contexto | Linhas | Cobertas | Cobertura |
|---|---:|---:|---:|
| `src` (processos) | 568 | 568 | 100,0% |
| `src/compartilhado` | 1.554 | 1.554 | 100,0% |
| `src/orcamento` | 672 | 672 | 100,0% |
| `src/pagamento` | 1.285 | 1.285 | 100,0% |
| `src/precos` | 437 | 437 | 100,0% |
| **total** | 4.516 | 4.516 | 100,0% |

| Camada | Linhas | Cobertas | Cobertura |
|---|---:|---:|---:|
| `dominio` | 895 | 895 | 100,0% |
| `aplicacao` | 773 | 773 | 100,0% |
| `infraestrutura` | 1.632 | 1.632 | 100,0% |
| `interfaces` | 648 | 648 | 100,0% |

O run é do PR #17; a árvore de `1789c27` é idêntica à do squash integrado `248c407`. A medida não é atribuída às correções de observabilidade ainda não integradas, mesmo que elas apresentem o mesmo percentual local.

## Execution Service

Fonte declarada pelo run: `c33824f801280a115e07e64b93185a64e9f700c1`. [Execução e artefato `relatorios-de-teste`](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-execution-service/actions/runs/39237570013). SHA256 do `coverage.xml`: `9c42c103c9e67d781465fb21f0d5641614a241590a7987ab11768f6eb1bae2d6`.

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

## Reprodução

Baixar `relatorios-de-teste` com `gh run download <run> --repo <organização/repositório> --name relatorios-de-teste --dir <destino>`. Conferir o SHA256 do XML. Nos checkouts dos SHAs indicados, OS e Billing geram o trecho oficial com `python scripts/cobertura_resumo.py coverage.xml --readme README.md --run <URL>`; a Execução usa `python scripts/cobertura_resumo.py coverage.xml README.md <URL>`. As tabelas deste relatório são saídas literais desses geradores, sem atualizar outros READMEs por este arquivo.

Cobertura não substitui sandbox real do Mercado Pago, prova de histórico, vídeo ou auditoria dos quatro commits finais. Os limites de medição e os módulos omitidos estão no README e na configuração de cobertura de cada serviço.
