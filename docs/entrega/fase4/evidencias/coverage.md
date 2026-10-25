# Cobertura publicada

Estado: medida anterior ao congelamento, nos CDs da `main` de 21/10/2026 (UTC; em Brasília, os runs começaram entre 23:08 de 20/10 e 00:03 de 21/10). Os testes de cada serviço rodaram em jobs Linux do GitHub Actions, com bancos descartáveis de integração. A cobertura soma linhas e ramos; o enunciado exige 80% e os serviços adotam gate de 95%. O quality gate do SonarQube está na [seção SonarQube](#sonarqube). As tabelas abaixo preservam a medida depois que os artefatos expiram.

## Runs citados

Cada serviço tem um run só: o CD da `main` de 21/10/2026 (UTC), o primeiro aprovado depois dos PRs que zeraram os code smells do SonarQube. A cobertura por camada, o quality gate e as medidas do SonarQube deste arquivo saem desse mesmo run, e as tabelas são geradas por `scripts/cobertura_resumo.py` a partir do `coverage.xml` dele ([Reprodução](#reprodução)). O README de cada serviço mostra a tabela do run que ele cita, que muda com os PRs e pode ser outro, anterior ou posterior a estes.

| Serviço | Run | Commit medido | PR que zerou os code smells |
|---|---|---|---|
| OS Service | [39531343409](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-os-service/actions/runs/39531343409), CD da `main` | `c0f5a57605e586f474542b71734f8ace8944a080` | [OS #27](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-os-service/pull/27) |
| Billing Service | [39531974299](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-billing-service/actions/runs/39531974299), CD da `main` | `8a367e1665116234937e3def79b519869ab7b998` | [Billing #24](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-billing-service/pull/24) |
| Execution Service | [39536414057](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-execution-service/actions/runs/39536414057), CD da `main` | `0ec76febda2954e36bd0930c419fc3b8144f9785` | [Execução #21](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-execution-service/pull/21) |

O CD da Execução no commit do #21 (`ec4721b`, [run 39531912471](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-execution-service/actions/runs/39531912471)) reprovou no job `ci / test` por um teste de integração instável do relay (`test_bloqueio_no_meio_do_lote_devolve_as_linhas_que_sobraram`). O [Execução #23](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-execution-service/pull/23) corrigiu o teste, sem mudar o código do serviço, e o run citado é o do commit seguinte, `0ec76fe`, que traz as duas mudanças.

O `platform`, que não tem serviço, cita o run 39458619627 (CD da `main` de 20/10, commit `d703200`), na seção Platform abaixo.

A coleta final repete a medida sobre os commits das tags.

## OS Service

**99,61% no gate** (linhas e ramos somados): 6.261 linhas, 6.245 cobertas (99,7%), e 930 ramos, 918 cobertos (98,7%), medidos no [run 39531343409 do CI](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-os-service/actions/runs/39531343409). Tabelas geradas por `scripts/cobertura_resumo.py` a partir do `coverage.xml` desse run. Foram 10.312 testes, todos aprovados.

| Contexto | Linhas | Cobertas | Cobertura |
|---|---:|---:|---:|
| `src` (processos) | 240 | 235 | 97,9% |
| `src/autenticacao` | 562 | 562 | 100,0% |
| `src/cliente_veiculo` | 903 | 902 | 99,9% |
| `src/compartilhado` | 1.853 | 1.843 | 99,5% |
| `src/ordem_servico` | 2.703 | 2.703 | 100,0% |
| **total** | 6.261 | 6.245 | 99,7% |

| Camada | Linhas | Cobertas | Cobertura |
|---|---:|---:|---:|
| `dominio` | 943 | 940 | 99,7% |
| `aplicacao` | 1.790 | 1.790 | 100,0% |
| `infraestrutura` | 2.492 | 2.488 | 99,8% |
| `interfaces` | 796 | 792 | 99,5% |

## Billing Service

**100,00% no gate** (linhas e ramos somados): 4.547 linhas, 4.547 cobertas (100,0%), e 624 ramos, 624 cobertos (100,0%), medidos pelo `make test` com o `src/` do [run 39531974299 do CI](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-billing-service/actions/runs/39531974299). Tabelas geradas por `scripts/cobertura_resumo.py` a partir do `coverage.xml` desse `make test`. Foram 1.731 testes, todos aprovados.

| Contexto | Linhas | Cobertas | Cobertura |
|---|---:|---:|---:|
| `src` (processos) | 570 | 570 | 100,0% |
| `src/compartilhado` | 1.576 | 1.576 | 100,0% |
| `src/orcamento` | 672 | 672 | 100,0% |
| `src/pagamento` | 1.292 | 1.292 | 100,0% |
| `src/precos` | 437 | 437 | 100,0% |
| **total** | 4.547 | 4.547 | 100,0% |

| Camada | Linhas | Cobertas | Cobertura |
|---|---:|---:|---:|
| `dominio` | 895 | 895 | 100,0% |
| `aplicacao` | 773 | 773 | 100,0% |
| `infraestrutura` | 1.661 | 1.661 | 100,0% |
| `interfaces` | 648 | 648 | 100,0% |

## Execution Service

Tabela gerada a partir do `coverage.xml` do [run 39536414057 do CI](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-execution-service/actions/runs/39536414057). Foram 1.475 testes, todos aprovados.

### Cobertura de testes: 100.0% no gate (linhas e ramos)

100.0% de linhas e 100.0% de ramos.

| Pacote | Linhas | Cobertas | Cobertura |
|---|---:|---:|---:|
| `src` | 318 | 318 | 100.0% |
| `src/compartilhado/aplicacao` | 59 | 59 | 100.0% |
| `src/compartilhado/dominio` | 144 | 144 | 100.0% |
| `src/compartilhado/infraestrutura` | 1325 | 1325 | 100.0% |
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
| **total** | 3682 | 3682 | 100.0% |

## Platform

O `platform` não tem serviço (nem domínio, API de negócio ou banco), e o `make test` roda no job `ci / contratos`. No [run 39458619627](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-platform/actions/runs/39458619627) (CD da `main` de 20/10/2026, commit `d703200`), o pytest coletou e aprovou 3.366 testes em 315,85 s, com 99,85% de linhas e ramos cobertos (12.377 linhas, 8 sem cobertura, e 1.196 ramos, 13 parciais; gate de 90%). Os testes cobrem os contratos de mensageria, os dashboards e alertas, os scripts de deploy e smoke e o apoio do E2E. A cobertura é a do código de teste, e não a de um serviço: o que protege os contratos são os negativos gerados dos exemplos ([contratos de mensageria](../../../contratos-de-mensageria.md)).

## SonarQube

Cada CI sobe um SonarQube efêmero no runner, analisa o código com o `coverage.xml` do job `test` e reprova o run se o quality gate falhar. O gate versionado em `.sonar/quality-gate.json` é o mesmo nos três serviços: cobertura de pelo menos 80%, no máximo 3% de linhas duplicadas e nota A em confiabilidade, segurança e manutenibilidade. Resultado no CD da `main` de 21/10/2026 (UTC) de cada serviço, o que o documento de entrega cita: o gate e os arquivos indexados vêm do log do job `ci / sonarqube`, e as medidas, do artefato `sonarqube` do run, que expira em 90 dias. Os três têm 0 code smells: o CD de 20/10 mostrava 247, e os PRs citados em [Code smells por regra](#code-smells-por-regra) os zeraram. Os prints do painel de cada serviço estão no [Anexo A, A2](../entrega-fase-4.md#a2--sonarqube) do documento de entrega. A cobertura do SonarQube é menor que a do gate porque ele conta também as linhas dos módulos só com `Protocol` (`repository.py`, `ports.py` e `unit_of_work.py`), que o `.coveragerc` omite por não terem lógica.

| Serviço | Run | Commit | Arquivos indexados | Quality gate | Linhas; cobertura | Bugs, vulnerabilidades e hotspots | Code smells |
|---|---|---|---:|---|---|---|---:|
| OS Service | [39531343409](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-os-service/actions/runs/39531343409) | `c0f5a57605e586f474542b71734f8ace8944a080` | 352 | aprovado (`QUALITY GATE STATUS: PASSED`, 21/10/2026 02:32 UTC) | 11.111; 97,2% | 0, 0 e 0 | 0 |
| Billing Service | [39531974299](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-billing-service/actions/runs/39531974299) | `8a367e1665116234937e3def79b519869ab7b998` | 166 | aprovado (`QUALITY GATE STATUS: PASSED`, 21/10/2026 02:25 UTC) | 7.802; 98,8% | 0, 0 e 0 | 0 |
| Execution Service | [39536414057](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-execution-service/actions/runs/39536414057) | `0ec76febda2954e36bd0930c419fc3b8144f9785` | 186 | aprovado (`QUALITY GATE STATUS: PASSED`, 21/10/2026 03:08 UTC) | 6.078; 98,6% | 0, 0 e 0 | 0 |

### Code smells por regra

Histórico. No CD da `main` de 20/10/2026 os três serviços somavam 247 code smells (138, 91 e 18). Os PRs [OS #27](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-os-service/pull/27), [Billing #24](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-billing-service/pull/24) e [Execução #21](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-execution-service/pull/21) zeraram todos, sem `# NOSONAR` e sem mudar o comportamento, e o CD de 21/10/2026 (UTC) mostra 0 nos três (tabela acima). As 15 supressões `# NOSONAR` que já existiam, 9 no Billing e 6 na Execução (handlers `async` de propósito, regra S7503, e heartbeats em `/tmp`), têm o motivo no código. A contagem por regra abaixo é a de 20/10, antes das correções.

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
| Total em 20/10/2026 | | 138 | 91 | 18 |
| Total no CD de 21/10/2026 (UTC) | | 0 | 0 | 0 |

## Mutação

A mutação usa mutantes escritos à mão nos módulos críticos, sem gate de CI ([ADR-041](../../../arquitetura/adr/fase4/041-estrategia-de-testes-e-qualidade.md#teste-de-mutação)): o resultado está na seção Mutação do README de cada serviço ([OS Service](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-os-service/blob/main/README.md#mutação), [Billing](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-billing-service/blob/main/README.md#mutação) e [Execução](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-execution-service/blob/main/README.md#mutação)), e a lista dos mutantes, em `scripts/mutantes.toml` e em `docs/` de cada um.

## Reprodução

Baixar `relatorios-de-teste` com `gh run download <run> --repo <organização/repositório> --name relatorios-de-teste --dir <destino>`. Nos checkouts dos SHAs indicados, OS e Billing geram o trecho oficial com `python scripts/cobertura_resumo.py coverage.xml --readme README.md --run <URL>`; a Execução usa `python scripts/cobertura_resumo.py coverage.xml README.md <URL>`. As tabelas deste relatório são saídas literais desses geradores.

Os prints do SonarQube (Anexo A, A2) vêm de uma análise local de cada commit, com as mesmas imagens do CI, o `sonar-project.properties` do repositório, o quality gate de `.sonar/quality-gate.json` aplicado como o `scripts/sonar/analisar.sh` faz e o `coverage.xml` do artefato `relatorios-de-teste` do run citado. As medidas locais (linhas, cobertura, bugs, vulnerabilidades, hotspots, duplicação, code smells e notas) são as do artefato `sonarqube` desse run nos três serviços.

Os limites de medição e os módulos omitidos estão no README e na configuração de cobertura de cada serviço.
