# Índice da entrega: fase 4

O PytStop é o sistema de gestão de uma oficina mecânica. Na fase 4 ele virou três microsserviços ligados por uma saga, que acompanha cada ordem de serviço (OS) da abertura à entrega do veículo. Nas tabelas, RF é requisito funcional, RNF é requisito não funcional e RN é regra de negócio. A numeração vem da [gap analysis](docs/requisitos/fase4/gap-analysis-fase-4.md), o levantamento que liga cada requisito à linha do enunciado.

Versão de ensaio. Os links de código apontam para `main`; a tag `entrega-fase-4` será criada após o congelamento e a gravação. Este índice acompanha o [documento](docs/entrega/fase4/entrega-fase-4.md), a [matriz dos 44 requisitos](docs/entrega/matriz-de-rastreabilidade.md) e o [roteiro de 14 minutos](docs/entrega/fase4/roteiro-video.md).

## Participantes e vídeo

A identificação dos participantes e o link do vídeo aguardam confirmação dos responsáveis. Esta versão não serve para submissão no portal.

## Repositórios

| Componente | Repositório | Documentação | Fonte e infraestrutura | CI/CD |
|---|---|---|---|---|
| OS Service | [repositório](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-os-service) | [README](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-os-service/blob/main/README.md) | [código](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-os-service/tree/main) | [pipelines](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-os-service/actions) |
| Billing Service | [repositório](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-billing-service) | [README](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-billing-service/blob/main/README.md) | [código](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-billing-service/tree/main) | [pipelines](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-billing-service/actions) |
| Execution Service | [repositório](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-execution-service) | [README](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-execution-service/blob/main/README.md) | [código](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-execution-service/tree/main) | [pipelines](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-execution-service/actions) |
| Plataforma | [repositório](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-platform) | [README](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-platform/blob/main/README.md) | [código](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-platform/tree/main) | [pipelines](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-platform/actions) |

Cada repositório de serviço contém `Dockerfile`, `k8s/`, `.github/workflows/`, `docs/arquitetura.md` e `docs/api/`. A plataforma reúne a infraestrutura compartilhada e as provas integradas.

## Exigências e artefatos

| Requisitos | Artefato |
|---|---|
| RF-028 a RF-038; RN-023 a RN-029 | [BDD do fluxo, compensações e pivot](e2e/features/saga_atendimento.feature); [runbook da saga](docs/operacao/runbook-saga.md) |
| RNF-031 a RNF-037; RNF-044; RNF-045; RNF-055 | [RFC-004](docs/arquitetura/rfc/fase4/rfc-004-microsservicos-saga.md), [decisões de arquitetura](docs/arquitetura/adr/fase4/) e [contratos](contratos/asyncapi.yaml) |
| RNF-038 a RNF-041; RNF-050 | [Workflows dos serviços](docs/entrega/matriz-de-rastreabilidade.md); [evidências de fechamento](docs/entrega/fase4/evidencias/README.md) |
| RNF-042; RNF-043; RNF-048; RNF-049 | [CI/CD e deploy em Kubernetes](docs/arquitetura/adr/fase4/042-cicd-e-deploy-kubernetes.md); [execuções da plataforma](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-platform/actions) |
| RNF-046; RNF-056 | [Dashboards de negócio](observabilidade/negocio.md), [técnicos, alertas e métricas](observabilidade/README.md), [ensaio integrado](docs/operacao/ensaio-integrado.md); [trace e alerta do ensaio local](docs/entrega/fase4/evidencias/observabilidade.md) |
| RNF-047; RNF-051; RNF-052 | Código e documentação de cada serviço, nas linhas de [rastreabilidade](docs/entrega/matriz-de-rastreabilidade.md); [duas provas locais do Newman](docs/entrega/fase4/evidencias/newman-resumo.md) |
| RNF-053; RNF-054 | [Documento de entrega](docs/entrega/fase4/entrega-fase-4.md), [roteiro do vídeo](docs/entrega/fase4/roteiro-video.md) e este índice |
| Feedback da fase 3 | CPF/CNPJ por módulo 11 antes da consulta no OS; cenário `@validacao` no BDD; dashboards e índice versionados |

## Dashboards

| Dashboard | JSON | Como ler |
|---|---|---|
| Negócio — Atendimento: volume diário de OS e tempo médio por status | [atendimento](observabilidade/dashboards/pytstop-negocio-atendimento.json) | [painéis de negócio](observabilidade/negocio.md) |
| Negócio — Orçamentos | [orçamentos](observabilidade/dashboards/pytstop-negocio-orcamentos.json) | [painéis de negócio](observabilidade/negocio.md) |
| Negócio — Pagamentos | [pagamentos](observabilidade/dashboards/pytstop-negocio-pagamentos.json) | [painéis de negócio](observabilidade/negocio.md) |
| Negócio — Execução | [execução](observabilidade/dashboards/pytstop-negocio-execucao.json) | [painéis de negócio](observabilidade/negocio.md) |
| Saga | [saga](observabilidade/dashboards/pytstop-saga.json) | [painéis técnicos](observabilidade/README.md) |
| Mensageria dos serviços | [mensageria](observabilidade/dashboards/pytstop-mensageria.json) | [painéis técnicos](observabilidade/README.md) |
| Serviços | [serviços](observabilidade/dashboards/pytstop-servicos.json) | [painéis técnicos](observabilidade/README.md) |
| Bancos | [bancos](observabilidade/dashboards/pytstop-bancos.json) | [painéis técnicos](observabilidade/README.md) |
| Plataforma: broker, borda e alvos | [plataforma](observabilidade/dashboards/pytstop-plataforma.json) | [painéis técnicos](observabilidade/README.md) |

Os JSONs e a documentação estão versionados. O trace local e as capturas do alerta disparado e recuperado estão preservados no [ensaio de observabilidade](docs/entrega/fase4/evidencias/observabilidade.md). As nove capturas finais com três dias de histórico continuam pendentes, conforme o [registro de evidências](docs/entrega/fase4/evidencias/README.md).

## Conferência

[Auditoria pré-entrega e dívida técnica](docs/entrega/fase4/auditoria-e-divida-tecnica.md). Pendências humanas: identificação do grupo, teste real da sandbox, gravação/publicação do vídeo e submissão do PDF no portal. O acesso do avaliador deve ser conferido pelos responsáveis.
