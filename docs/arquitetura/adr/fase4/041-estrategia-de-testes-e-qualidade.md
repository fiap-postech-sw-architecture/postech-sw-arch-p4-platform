# Estratégia de testes e qualidade por serviço

> [↑ Raiz do projeto](../../../../README.md) · [↑ Arquitetura](../../README.md)

* Status: Aceita
* Data: 2026-10-06

## Contexto e Problema

A seção "Testes e Qualidade" do [enunciado](../../../requisitos/fase4/desafio-tech-fase-4.md) pede testes unitários em todos os microsserviços, ao menos um fluxo completo testado com BDD (*behavior-driven development*), cobertura mínima de 80% por serviço e SonarQube ou similar no CI, o pipeline de integração contínua (l. 81-84); cada repositório entrega evidência de cobertura no README (l. 111). Na [gap analysis](../../../requisitos/fase4/gap-analysis-fase-4.md), são os requisitos não funcionais RNF-038 a RNF-041 e RNF-050, mais as regras de negócio RN-023 (compensação testada em cada passo que pode falhar), RN-028 (mensagem reentregue não repete efeito) e RN-029 (sem cancelamento depois do início da execução).

O p3 (código da fase 3, commit `08dcffe`) tem 1.554 funções de teste unitário e 165 de integração com testcontainers, sob gate de 95%, mas mede um monolito. O BDD ficou como proposta desde a fase 1 (ADR-013, dívida técnica TD-013), sem nenhum `.feature`. O SonarQube rodou só como scan manual, fora do CI por decisão (ADR-011, TD-010): com o repositório privado, o SonarCloud seria pago e um servidor próprio parecia desproporcional; os repositórios da fase 4 são públicos.

O teste de fluxo completo do p3 tinha matriz de papéis e OWASP ZAP baseline como gate (gap analysis, seção 7.1; `.github/workflows/full-test-ci.yml:121-137`). Faltam testes de orquestração, compensação, idempotência, contrato de mensagens, MongoDB e RabbitMQ, e a banca da fase 2 achou a cobertura "mencionada, mas não detalhada".

Os níveis de teste vêm de Estrutura de Microsserviços Parte II. A Aula 03 trata de unitários solitários e sociáveis, com mocks e stubs; a Aula 04, de integração de persistência, contrato de API, componente, que testa "o serviço como um todo, abstraindo a integração com suas dependências", e ponta a ponta, caro e frágil e restrito às jornadas principais, além de BDD em Gherkin e SonarQube no pipeline, sem meta numérica de cobertura. Contrato de eventos e BDD em Python não estão no material, e a disciplina SAGA Pattern só testa controllers e só demonstra o caminho feliz (Aulas 04 e 05).

**Como testar três serviços independentes e uma saga distribuída para que cada repositório prove o que lhe cabe, com evidência legível pela banca e sem conta ou segredo externo?**

## Decisão

### Pirâmide de cada serviço

Cada serviço (OS Service, de ordens de serviço, OS; Billing Service; Execution Service, do contexto Execução) tem a própria pirâmide, executada no job `test` do CI ([ADR-042](042-cicd-e-deploy-kubernetes.md)):

- Unitários por camada (`dominio`, `aplicacao`, `infraestrutura`, `interfaces`), com fakes e stubs (RNF-038); os testes do p3 migram com o código de cada contexto. Cada máquina de estados (OS, saga, orçamento, pagamento, reserva, diagnóstico e execução) tem uma tabela parametrizada com as transições válidas e as inválidas, cada caso com nome (`pytest.param(..., id=...)`).
- Integração com testcontainers: PostgreSQL 16 (OS Service e Execução), MongoDB 7 em replica set de um nó (Billing; a transação com a outbox exige replica set) e RabbitMQ nos três, cobrindo relay, consumidor, retry, fila de mensagens mortas (DLQ) e a mesma mensagem entregue duas vezes (RN-028). Teste com commit real usa banco, vhost ou fila próprios, ou limpa o que gravou no teardown, porque o isolamento por transação com SAVEPOINT do p3 não alcança relay e consumidor.
- Resiliência: o circuit breaker da chamada ao Billing contra um servidor falso (abre com 5 falhas, responde 503, deixa passar a chamada de teste depois de 30 s) e a validação pelo conjunto de chaves públicas, o JWKS (cache, timeout, `kid` novo, 503 sem chave).
- Propagação de contexto: o relay publica no contexto gravado na outbox, o consumidor fica filho da publicação, a retomada por pessoa mantém o `trace_id`, e cada passagem por uma fila de retry acrescenta spans ao mesmo trace ([ADR-043](043-observabilidade-distribuida.md)).

### Contratos

- Mensagens: AsyncAPI e um JSON Schema por mensagem em `contratos/` no `platform`. Cada serviço copia os schemas que produz e consome, guarda em `contratos/ORIGEM` o commit do `platform` de onde os copiou e valida, em teste de contrato, o envelope e os `dados` de cada mensagem. Outro teste compara o checksum da cópia com o `contratos/` do `platform` naquele commit, e uma cópia alterada à mão falha no CI do próprio serviço. É o contrato de API da Aula 04 estendido a eventos.
- REST de preços: o OpenAPI de `POST /api/v1/precos/validacao` é testado nos dois lados, no Billing, que o atende, e na Execução, que o chama.
- Mercado Pago: o adapter real tem contrato próprio ([ADR-040](040-integracao-mercado-pago.md)).

### Segurança

Em cada serviço, a matriz de papel por rota do [ADR-039](039-autenticacao-entre-servicos.md) vira teste de 401 e 403, e o token JWT (JSON Web Token) passa por casos negativos: `alg=none`, assinatura simétrica HS256 feita com a chave pública, `aud` ou `iss` errados, expirado, sem `papel` ou com `papel` desconhecido, refresh no lugar de access e `kid` desconhecido. No Billing, entram também webhook com assinatura inválida ou repetida e link de decisão expirado ou repetido.

No OS Service, o acompanhamento público valida CPF e CNPJ pelo dígito verificador (módulo 11) e a placa antes de consultar o repositório, com a mesma resposta 404 do "não encontrado", e o teste prova que documento inválido não chega ao banco.

### BDD em dois níveis (RNF-039)

Os cenários usam o pytest-bdd com Gherkin em português (`# language: pt`), recurso que exige `pytest-bdd>=8.0`.

Componente, em cada serviço: o serviço inteiro, com as dependências trocadas por fakes que montam as mensagens a partir dos mesmos schemas de `contratos/`. Roda em todo pull request (PR) e conta para a cobertura (RN-023).

- OS Service: a saga, com um barramento falso em memória no lugar do RabbitMQ e os steps no papel de Billing e Execução. Cobre orçamento recusado ou expirado, falha na geração do orçamento, falta de peça, pagamento recusado ou expirado, cancelamento em cada etapa antes do pivot (ponto sem retorno, RN-029), inclusive com passo em voo e com a ordem das compensações conferida, prazo técnico esgotado, o `prazos` em pausa sem consumidor em `os.eventos` ou com o broker fora, `FALHA_NA_COMPENSACAO` e retomada, evento obsoleto e evento adiantado, a corrida do pivot e o 409 depois do início da execução. Fora do BDD, um teste da configuração confere que a janela de reenvio do `prazos` fica maior que a soma dos atrasos das filas de retry ([ADR-035](035-saga-orquestrada.md)).
- Billing: orçamento expirado, pagamento recusado pelo limite de recusas, pagamento aprovado depois de cancelado, expirado ou recusado, com estorno automático, estorno repetido sem segunda chamada ao provedor e compensação que chega antes do comando.
- Execução: reserva tudo ou nada, liberação que chega antes da reserva e início da execução que vence o cancelamento.

Ponta a ponta (E2E), no `platform`: `e2e/features/saga_atendimento.feature` roda contra os três serviços implantados no kind, no job `deploy-kind` do pipeline de entrega contínua (CD) de cada serviço, com poucas jornadas, como recomenda a Aula 04. Cada cenário cria os próprios clientes, peças e OS, com identificadores únicos, sem depender de estado deixado por outro cenário. O pagamento usa o simulador do Mercado Pago, que percorre o mesmo caso de uso do webhook.

- `@caminho-feliz`: os oito status, de `RECEBIDA` a `ENTREGUE`, com consulta à API do Jaeger que exige spans dos três serviços no mesmo trace, e o `X-Request-ID` gerado pelo Kong presente nos logs do serviço.
- `@compensacao`: recusa do orçamento, falta de peça, pagamento recusado e cancelamento depois do pagamento, com estorno e a ordem das compensações conferida.
- `@expiracao`: orçamento vencido, com validade curta no overlay do kind.
- `@ponto-de-nao-retorno`: cancelamento depois do início da execução responde 409.
- `@resiliencia`: consumidor do Billing parado por 20 s, sem mensagem na DLQ e com a saga seguindo na volta; API do Billing parada na conclusão do diagnóstico, com 503, circuito aberto e conclusão aceita quando o Billing volta. O cenário derruba o componente com `kubectl scale --replicas=0`.
- O Swagger (`/docs`) de cada serviço abre através do Kong.

O OWASP ZAP baseline contra o Kong e a collection do fluxo completo, executada com newman, rodam no job de E2E do pipeline do `platform`, não no CD de cada serviço, para não somar minutos a cada deploy.

### Cobertura (RNF-040, RNF-050)

`.coveragerc` com `fail_under = 90`, `branch = True`, `source = src` e `relative_files = True`, mais `diff-cover --fail-under=90` no job `test`, para que um PR sem teste não passe só porque o total absorveu o código novo. O job `test` escreve no summary a tabela por contexto e camada (`scripts/cobertura_resumo.py`) e publica `coverage.xml`, `htmlcov/` e `reports/` no artefato `relatorios-de-teste`, com retenção de 90 dias. O README de cada serviço repete a tabela, com print do relatório e link para a execução do CI, e os prints do quality gate e do relatório do E2E ficam versionados em `docs/entrega/fase4/evidencias/`.

### SonarQube efêmero no CI (RNF-041)

O job `sonarqube`, depois de `test`, sobe `sonarqube:26.9.0.129388-community` como service container e analisa com `sonarsource/sonar-scanner-cli:12.2.0.4256_8.1.0`, as duas imagens fixadas também por digest. O `scripts/sonar/analisar.sh` troca a senha padrão por uma aleatória, aplica o quality gate versionado em `.sonar/quality-gate.json` e gera o token de análise; senha e token morrem com o runner. O gate reprova com cobertura abaixo de 80%, duplicação acima de 3% ou rating pior que A em confiabilidade, segurança e manutenibilidade, e `sonar.qualitygate.wait=true` falha o job; o resultado vai ao summary (`scripts/sonar/resumo.sh`) e ao artefato `reports/sonarqube.json`.

Na validação local de 06/10/2026, sem `relative_files = True` o SonarQube não resolveu os caminhos do `coverage.xml` e o gate reprovou; com o ajuste e 100% de cobertura, aprovou. Uma análise com zero arquivos indexados também aprovou, porque o gate avaliou só as três notas e ignorou cobertura e duplicação ausentes. Por isso o `analisar.sh` falha o job se `reports/sonarqube-medidas.json` não trouxer `coverage` e `ncloc`.

A imagem do SonarQube pede `vm.max_map_count` de pelo menos 524288 no host. A primeira execução em runner real mede o tempo de subida e confirma esse valor, e o job só se reexecuta sozinho quando o servidor não fica `UP` no prazo, falha de infraestrutura sem relação com a qualidade do código.

O gate do coverage.py fica em 90%, e o do SonarQube, no mínimo do enunciado, porque recalcula a cobertura com fórmula própria (94,6% contra 96,4% do gate na fase 3).

### Versões fixadas

As versões de que os testes e o CI dependem ficam fixadas: `pytest-bdd>=8.0` no `pyproject.toml` de cada serviço, e RabbitMQ, Kong e Kong Ingress Controller, Prometheus, Grafana, Loki, Jaeger, exportadores de banco, metrics-server, SonarQube e scanner numa tabela de versões no README do `platform`, com tag ou digest fixo nos manifestos.

## Alternativas Consideradas

* Pirâmide por serviço, BDD em dois níveis, gate de 90% e SonarQube efêmero
* behave no lugar do pytest-bdd
* BDD só no ponta a ponta
* Pact para os contratos
* SonarCloud
* CodeQL, Codacy ou qlty como "similar"
* SonarQube manual de fechamento, como na fase 3
* Gate de cobertura em 80%

### Pirâmide por serviço, BDD em dois níveis, gate de 90% e SonarQube efêmero

* Bom, porque cada repositório prova sozinho unitários, cobertura, BDD de componente e SonarQube, e o fluxo completo roda com os três serviços no E2E
* Bom, porque a compensação é testada no PR do serviço que a implementa, antes do merge
* Bom, porque não pede conta, aprovação humana nem segredo
* Ruim, porque o CI fica mais lento: contêineres de banco e broker no `test` e a subida do SonarQube (o script espera até 7,5 minutos)
* Ruim, porque são dois níveis de cenários para manter, e cenários BDD envelhecem com o código, custo apontado na Aula 04

### behave no lugar do pytest-bdd

* Bom, porque é o framework BDD mais conhecido em Python e aceita Gherkin em português
* Ruim, porque roda fora do pytest: não reaproveita fixtures (testcontainers, fakes), mede cobertura à parte e duplica a infraestrutura de teste, os motivos que levaram o ADR-013 ao pytest-bdd

### BDD só no ponta a ponta

* Bom, porque um único conjunto de cenários exercita o sistema real
* Ruim, porque o E2E só roda no CD, depois do merge, e falhas raras (prazo esgotado, falha na compensação, evento fora de ordem) exigiriam injeção de falha no cluster; no componente, são um step

### Pact para os contratos

* Bom, porque é o contrato consumer-driven da Aula 04 (o Pact está na bibliografia) e também cobre mensagens
* Ruim, porque pede um broker de contratos (Pact Broker próprio ou PactFlow, com conta e token) e amarra o pipeline do produtor aos pactos dos consumidores
* Ruim, porque na saga orquestrada cada comando tem um só consumidor e o catálogo já tem dono; um schema por mensagem basta

### SonarCloud

* Bom, porque é gratuito para repositório público, guarda histórico, decora PR e dá link permanente para o README
* Ruim, porque exige conta, autorização do app na organização por um administrador e token guardado como segredo, contra a política de segredos da fase ([ADR-042](042-cicd-e-deploy-kubernetes.md))

### CodeQL, Codacy ou qlty como "similar"

* Bom, porque o CodeQL é gratuito em repositório público e já rodou no p3
* Bom, porque Codacy e qlty reúnem análise estática e cobertura
* Ruim, porque o CodeQL não mede cobertura nem duplicação, e Codacy e a nuvem do qlty pedem conta e token
* Ruim, porque o enunciado e a Aula 04 nomeiam o SonarQube; com ele, o "similar" não precisa ser defendido

### SonarQube manual de fechamento, como na fase 3

* Bom, porque não gasta CI e já deu evidência na fase 3 (gate aprovado, zero code smells)
* Ruim, porque o enunciado pede a validação no CI, e os motivos do ADR-011 caíram: repositórios públicos e servidor dentro do job

### Gate de cobertura em 80%

* Bom, porque é o mínimo exigido e custa menos teste
* Ruim, porque não deixa margem: um PR sem teste derruba o serviço abaixo do requisito, e o SonarQube pode medir menos que o coverage.py

## Consequências

### Positivas

* Cada repositório atende RNF-038 a RNF-041 e RNF-050, com evidência no summary, em artefato, no README e em `docs/entrega/fase4/evidencias/`
* Cada compensação da saga e cada caso de borda dos participantes tem cenário executável em português, legível pela banca
* O quality gate é código, revisado em PR como o resto, e não aprova análise vazia
* A matriz de papéis e o ZAP da fase 3 continuam, por serviço e contra a borda

### Negativas

* SonarQube efêmero não guarda histórico nem decora PR, e o gate vale sobre o código total, porque não há baseline de código novo; o `diff-cover` cobre o código novo, e não há painel permanente para linkar
* Os artefatos expiram em 90 dias (`retention-days`); tabela e prints no README e em `docs/entrega/fase4/evidencias/` são a evidência permanente
* O teste de contrato confere a estrutura da mensagem: um campo que muda de sentido sem mudar de tipo passa por ele
* O E2E roda no CD, depois do merge: uma falha de integração entre serviços aparece com a `main` já alterada, e a correção é um PR de revert ([ADR-042](042-cicd-e-deploy-kubernetes.md))

### Neutras

* A cobertura mede linhas e ramos executados, não a força das asserções; teste de mutação continua fora, como nas fases anteriores

## Decisões Relacionadas

- [ADR-005](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p3/blob/main/docs/arquitetura/adr/005-estrategia-testes.md): fakes e testcontainers continuam, agora por serviço
- [ADR-011](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p3/blob/main/docs/arquitetura/adr/011-pipeline-seguranca-analise-estatica.md): revertido na parte do SonarQube fora do CI (TD-010)
- [ADR-013](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p3/blob/main/docs/arquitetura/adr/013-testes-bdd-pytest-bdd.md): superado; o pytest-bdd sai do papel, em dois níveis
- [ADR-035](035-saga-orquestrada.md): orquestrador e compensações cobertos pelo BDD de componente
- [ADR-036](036-mensageria-rabbitmq.md): envelope, retry e DLQ exercitados na integração e no contrato
- [ADR-039](039-autenticacao-entre-servicos.md): matriz de papel por rota testada em cada serviço
- [ADR-040](040-integracao-mercado-pago.md): simulador do E2E e contrato do adapter real
- [ADR-042](042-cicd-e-deploy-kubernetes.md): `test` e `sonarqube` como checks obrigatórios; `deploy-kind` executa o E2E

## Notas

* Material: Estrutura de Microsserviços Parte II, Aulas 03 e 04; Estrutura de Microsserviços, Aula 04 (AsyncAPI); SAGA Pattern, Aulas 04 e 05
* pytest-bdd: https://pytest-bdd.readthedocs.io/; imagem do SonarQube e requisitos do host: https://hub.docker.com/_/sonarqube; Pact: https://docs.pact.io/

> [↑ Raiz do projeto](../../../../README.md) · [↑ Arquitetura](../../README.md)
