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

Cada CI sobe um SonarQube efêmero no runner, analisa o código com o `coverage.xml` do job `test` e reprova o run se o quality gate falhar. O gate versionado em `.sonar/quality-gate.json` é o mesmo nos três serviços: cobertura de pelo menos 80%, no máximo 3% de linhas duplicadas e nota A em confiabilidade, segurança e manutenibilidade. Resultado no CD da `main` de 20/10/2026 de cada serviço, o que o documento de entrega cita: o gate e os arquivos indexados vêm do log do job `ci / sonarqube`, e as medidas, do artefato `sonarqube` do run, que expira em 90 dias.

| Serviço | Run | Commit | Arquivos indexados | Quality gate | Linhas; cobertura | Bugs, vulnerabilidades e hotspots | Code smells |
|---|---|---|---:|---|---|---|---:|
| OS Service | [39449191933](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-os-service/actions/runs/39449191933) | `3ce582ba38aeb0b18a2de57adf58d05d514de95b` | 352 | aprovado (`QUALITY GATE STATUS: PASSED`, 20/10/2026 15:40 UTC) | 11.107; 97,2% | 0, 0 e 0 | 138 |
| Billing Service | [39449241713](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-billing-service/actions/runs/39449241713) | `76b5f9b59da4a6557de24ac08b1ee26920fdf27a` | 166 | aprovado (`QUALITY GATE STATUS: PASSED`, 20/10/2026 15:36 UTC) | 7.790; 98,8% | 0, 0 e 0 | 91 |
| Execution Service | [39449216419](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-execution-service/actions/runs/39449216419) | `5b1bef4738c728bfc4f34820ee55d0959fd0dcfb` | 186 | aprovado (`QUALITY GATE STATUS: PASSED`, 20/10/2026 15:37 UTC) | 6.077; 98,6% | 0, 0 e 0 | 18 |

### Code smells por regra

O artefato guarda só as medidas, e o log não lista os avisos. Para saber o que são os code smells, a análise foi refeita em 20/10/2026 numa máquina local, com as mesmas imagens do CI (`sonarqube:26.9.0.129388-community` e `sonarsource/sonar-scanner-cli:12.2.0.4256_8.1.0`, perfil padrão Sonar way), sobre os mesmos commits e sem o `coverage.xml`, que não muda a contagem. Deu os mesmos 138, 91 e 18 code smells e as mesmas linhas (11.107, 7.790 e 6.077), sem bug nem vulnerabilidade. Os nomes das regras são os da API do mesmo servidor.

| Regra | O que pede | OS Service | Billing | Execução |
|---|---|---:|---:|---:|
| python:S5778 | uma só chamada dentro do bloco que testa a exceção (`pytest.raises`) | 125 | 76 | 13 |
| python:S3415 | a mesma ordem dos argumentos nas asserções de um arquivo | 2 | 3 | 0 |
| python:S7632 | comentário de supressão de aviso no formato certo | 0 | 5 | 1 |
| python:S5886 | tipo de retorno igual ao da anotação | 4 | 0 | 1 |
| python:S1192 | literal de texto sem repetição | 3 | 1 | 0 |
| python:S1110 | sem par de parênteses redundante | 2 | 1 | 1 |
| python:S3776 | complexidade cognitiva da função dentro do limite | 0 | 2 | 0 |
| python:S1172 | sem parâmetro de função sem uso | 0 | 2 | 0 |
| python:S8714 | asserção própria de exceção, em vez de `try`/`except` com `fail()` | 0 | 0 | 2 |
| python:S107 | função sem parâmetros demais | 0 | 1 | 0 |
| python:S8997 | o fixture `monkeypatch` para mudança temporária nos testes | 1 | 0 | 0 |
| python:S1135 | acompanhar as marcas `TODO` | 1 | 0 | 0 |
| Total | | 138 | 91 | 18 |

## Reprodução

Baixar `relatorios-de-teste` com `gh run download <run> --repo <organização/repositório> --name relatorios-de-teste --dir <destino>`. Nos checkouts dos SHAs indicados, OS e Billing geram o trecho oficial com `python scripts/cobertura_resumo.py coverage.xml --readme README.md --run <URL>`; a Execução usa `python scripts/cobertura_resumo.py coverage.xml README.md <URL>`. As tabelas deste relatório são saídas literais desses geradores.

Os limites de medição e os módulos omitidos estão no README e na configuração de cobertura de cada serviço.
