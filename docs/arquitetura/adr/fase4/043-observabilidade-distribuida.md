# Stack da fase 3 reaproveitada com rastreamento da saga ponta a ponta

> [↑ Raiz do projeto](../../../../README.md) · [↑ Arquitetura](../../README.md)

* Status: Aceita
* Data: 2026-10-06

## Contexto e Problema

O [enunciado](../../../requisitos/fase4/desafio-tech-fase-4.md) pede, na infraestrutura, as ferramentas de monitoramento e observabilidade já implementadas na fase 3 (l. 102) e, no vídeo, o monitoramento e o rastreamento dos fluxos distribuídos (l. 122). Na [gap analysis](../../../requisitos/fase4/gap-analysis-fase-4.md), são os requisitos não funcionais RNF-046 (gap parcial) e RNF-056, derivado da l. 122.

No p3 (código da fase 3, commit `08dcffe`), a stack serve um único serviço (ADR-020, ADR-024 e ADR-032): Prometheus com kube-state-metrics e cAdvisor, Grafana com dois dashboards em JSON documentados painel a painel e cinco regras de alerta, Loki com Promtail sobre logs JSON sem dado pessoal e Jaeger recebendo traces pelo protocolo do OpenTelemetry (OTLP). Nada disso atravessa serviços: o `service.name` é fixo em `pytstop-api`, o relay não gera trace, a outbox não guarda `traceparent` nem `correlation_id`, e o `X-Request-ID` para na outbox.

Com a saga cruzando três serviços pelo RabbitMQ e esperando horas pelo cliente, cada serviço veria só a sua parte, e não haveria como saber onde está uma ordem de serviço (OS) nem por que ela parou. A banca da fase 3 pediu dashboards de negócio em JSON separado e documentados painel a painel; o formato vale para todos os dashboards novos.

A Aula 06 de Estrutura de Microsserviços Parte II trata de métricas, logs e traces, com o trace distribuído como visão de ponta a ponta e o OpenTelemetry exportando OTLP para Prometheus e Jaeger, com dados contextuais, nomenclatura padrão e amostragem. A mesma aula trata de alertas com limiar de aviso e de alerta calibrados pelo comportamento normal e de objetivo de nível de serviço (SLO) com error budget; o hands-on usa Elasticsearch, Logstash e Kibana.

Propagar contexto por mensageria não está no material, e a disciplina SAGA Pattern acompanha a saga pelo console do RabbitMQ e por logs (Aula 05). A Aula 02 de Estrutura de Microsserviços separa a mensagem em header de metadados e body, e o contexto de trace vai no header; a Aula 07 de Data Engineering trata do monitoramento centralizado dos bancos.

**Como reaproveitar a stack da fase 3 para três serviços de modo que uma OS possa ser seguida da abertura à entrega, ou à compensação, num trace só, nos logs e nas métricas?**

## Decisão

Prometheus, Grafana, Loki com Promtail e Jaeger, os mesmos da fase 3, passam para o `platform` e servem os três serviços (OS Service, Billing Service e Execution Service, do contexto Execução), cada um com `service.name` próprio. O `platform` também instala o metrics-server, pré-requisito do autoescalonamento horizontal (HPA) no kind, e as versões de todos os componentes ficam na tabela de versões fixadas do `platform` ([ADR-041](041-estrategia-de-testes-e-qualidade.md)). O Promtail continua porque o enunciado exige reaproveitar as ferramentas da fase 3 (l. 102), apesar do fim de vida registrado nas consequências.

### Coleta de métricas

Todo Deployment expõe a porta `metrics`, com as anotações de descoberta, e o Prometheus usa `kubernetes_sd` nos três namespaces `pytstop-*` e no da plataforma, raspando por pod, com o rótulo `processo` (`api`, `relay`, `consumidor`, `prazos`). As métricas de saga, mensageria e negócio nascem em processos sem tráfego HTTP de negócio, como relay e consumidor; por isso cada processo serve a sua porta `metrics`, como o relay do p3 já fazia (`relay/metrics.py:117-125`).

### Rastreamento (RNF-056)

- OpenTelemetry nos três serviços, instrumentando FastAPI, SQLAlchemy/psycopg, PyMongo, pika e httpx, com exportação OTLP para o Jaeger.
- O contexto W3C (`traceparent`, `tracestate`) viaja nos headers AMQP (*Advanced Message Queuing Protocol*) do envelope ([ADR-036](036-mensageria-rabbitmq.md)). A instrumentação do pika injeta e extrai esses headers, mas quem publica é o relay, fora da transação de origem; por isso a outbox grava o `traceparent` com a mensagem, e o relay publica dentro desse contexto. O span do consumidor é filho do span de publicação, e cada passagem por uma fila de retry acrescenta spans ao mesmo trace. Na chamada REST de negócio entre serviços (Execução para Billing), o httpx propaga o contexto.
- Passos retomados por pessoa, sistema externo ou prazo (diagnóstico e execução pelo mecânico, decisão do cliente, webhook do Mercado Pago, processos `prazos`) começam com trace próprio. Para não partir a saga, o registro que espera o passo guarda o `traceparent` da mensagem que o pôs em espera, e o evento seguinte é publicado como filho desse contexto, com span link para o trace de quem retomou. Cada saga vira um trace no Jaeger, com raiz na abertura da OS.
- Laços ociosos (poll de segurança do relay, relay do MongoDB e processos `prazos`) só abrem span quando há trabalho, e o `--memory.max-traces` do Jaeger fica em cerca de 5000 traces, o que cabe no limite de 512 Mi do pod, para que ciclos vazios não encham a memória nem escondam as sagas.

### Correlação e logs

`correlation_id` = `ordem_id` (o mesmo `saga_id`) em todas as mensagens e em toda linha de log. Os logs JSON levam também `trace_id`, `span_id` e `request_id`, sem dado pessoal e sem os campos de texto livre (`descricao_problema`, `observacoes`, `motivo`); a limpeza de logs mascara o `{token}` do link de decisão e trata `link_decisao` e `checkout_url` como sensíveis ([ADR-039](039-autenticacao-entre-servicos.md)), e o Promtail mascara o mesmo token no access log antes de enviá-lo ao Loki. Uma consulta por `correlation_id` no Loki traz a OS nos três serviços, e o `trace_id` leva ao trace no Jaeger. O `X-Request-ID` nasce na borda, no plugin `correlation-id` do Kong, com gerador `uuid` ([ADR-038](038-borda-e-comunicacao-sincrona.md)).

### Métricas

Métricas novas levam o prefixo `pytstop_`; as herdadas do p3 mantêm o nome (`outbox_pendentes`, `outbox_dead`, `http_request_duration_seconds`), para reaproveitar regras e painéis.

- Saga: os contadores `pytstop_saga_iniciadas_total`, `pytstop_saga_finalizadas_total{resultado}` (`resultado` em `concluida` ou `compensada`), `pytstop_saga_compensacoes_total{motivo}`, `pytstop_saga_reenvios_total{comando}` e `pytstop_saga_prazos_esgotados_total{comando}`, estes dois do processo `prazos`, com o tipo do comando no label; o histograma `pytstop_saga_etapa_duracao_segundos{etapa}`; e três gauges, `pytstop_saga_ativas{etapa}`, `pytstop_saga_etapa_mais_antiga_segundos{etapa}` (idade da instância mais antiga em cada etapa) e `pytstop_saga_prazo_vencido_segundos` (maior atraso entre as instâncias cujo envio mais recente já foi entregue e passou do prazo, contado do `entregue_em` mais `SAGA_PRAZO_RESPOSTA_SEGUNDOS`; zero sem atraso, e o comando que ainda espera na outbox não conta). Os gauges são calculados por um coletor da API na hora da raspagem, por consulta às tabelas `sagas` e `outbox`, como as métricas de outbox do p3, e continuam certos com o `prazos` fora do ar. O label `etapa` leva o nome da etapa em minúsculas, e o `motivo` é enumeração fechada: `orcamento_recusado`, `orcamento_expirado`, `geracao_falhou`, `reserva_falhou`, `pagamento_recusado`, `pagamento_expirado`, `cancelamento` e `prazo_tecnico`. O texto livre fica só na OS, nunca no log.
- Mensageria: `pytstop_mensagens_publicadas_total{tipo}`, `pytstop_mensagens_consumidas_total{tipo,resultado}`, `outbox_pendentes` e `outbox_dead`, que o relay do Billing também exporta, mais o plugin Prometheus do RabbitMQ (profundidade por fila, inclusive das filas de mensagens mortas, as DLQ, consumidores e taxas de publicação e confirmação).
- Integrações: `pytstop_mercadopago_requisicoes_total{operacao,resultado}`, `pytstop_circuit_breaker_aberto{dependencia}` e `pytstop_pagamentos_estornados_total{motivo}`, com `motivo` em `compensacao` ou `pagamento_apos_encerramento`.
- Segurança: `pytstop_webhook_assinatura_invalida_total` e `pytstop_jwks_falhas_total`, mais as respostas 401, 403 e 429 do Kong por rota.
- Bancos: `postgres_exporter` ao lado de cada PostgreSQL e `mongodb_exporter` ao lado do MongoDB (conexões, transações, locks, tamanho e replicação), o monitoramento centralizado de bancos da Aula 07 de Data Engineering.
- As métricas HTTP da fase 3 em cada serviço e o plugin `prometheus` do Kong na borda.

### Dashboards

Um arquivo JSON por dashboard em `observabilidade/dashboards/` no `platform`, cada painel com descrição e documentado numa tabela (consulta e como ler), no formato do [documento de dashboards da fase 3](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p3/blob/main/docs/observabilidade/dashboards-grafana.md), com o teste de consistência que falha se um painel ficar sem descrição ou sem documentação. A lista de painéis de cada dashboard fica nesse documento do `platform`.

| Dashboard | Responde |
|---|---|
| Saga | quantas sagas começam, terminam e compensam, e por quê; em que etapa estão as ativas e há quanto tempo; quanto dura cada etapa |
| Mensageria | profundidade das filas de trabalho, de retry e de DLQ; outbox pendente e morta; mensagens publicadas e consumidas por tipo e resultado |
| Serviços | taxa, erros e duração (RED, de *rate*, *errors* e *duration*) por serviço e na borda; 401, 403 e 429 do Kong; circuitos abertos; chamadas ao Mercado Pago e estornos por motivo; CPU e memória por pod; conexões, transações e locks de cada banco |
| Negócio | volume de OS e tempo médio por status, o requisito funcional RF-008 da fase 1, no mesmo cálculo de `GET /api/v1/ordens-de-servico/metricas`; desfecho das sagas por resultado |

### Alertas

No Grafana, como na fase 3, separando aviso de alerta crítico, como recomenda a Aula 06. As cinco regras da fase 3 continuam, aplicadas a cada serviço, e a saga acrescenta o conjunto abaixo. Sem dado, as regras ficam em OK (`noDataState`), como na fase 3, exceto a de serviço fora do ar, que consulta `up{job=...}` com condição menor que 1 e `noDataState: Alerting`: alvo derrubado (`up` em 0) e alvo que sumiu da descoberta (sem série) alertam, e serviço no ar fica em OK.

| Alerta | Condição | Janela (`for`) | Severidade |
|---|---|---|---|
| DLQ com mensagens | alguma fila `.dlq` com mensagem, pela métrica por fila do plugin do RabbitMQ | 1 min | crítico |
| Saga parada | prazo técnico vencido e não tratado há mais de 60 s, em qualquer etapa, ou alguma instância em `falha_na_compensacao` (consulta abaixo) | 5 min | crítico |
| Compensações acima do normal | razão entre compensações e sagas iniciadas acima de um limite tirado do comportamento normal | 30 min | aviso |
| Erro 5xx acima de 1% | regra da fase 3, agregada por serviço | 5 min | crítico |
| Circuito aberto | `pytstop_circuit_breaker_aberto` em 1 para qualquer dependência | 1 min | aviso |
| Outbox parada | `outbox_pendentes` acima de zero em qualquer serviço (broker fora do ar ou relay parado) | 5 min | crítico |
| Assinatura inválida no webhook | `pytstop_webhook_assinatura_invalida_total` crescendo | 5 min | aviso |
| Falha na busca do conjunto de chaves públicas (JWKS) | `pytstop_jwks_falhas_total` crescendo | 5 min | aviso |

A regra de saga parada é uma consulta só, `max(pytstop_saga_prazo_vencido_segundos) > 60 or max(pytstop_saga_ativas{etapa="falha_na_compensacao"}) > 0 or vector(0)`, que dispara acima de 0. Com o `or`, a série que falta numa condição não esconde a outra, e o `vector(0)` deixa a regra com valor zero quando nenhuma condição vale, inclusive antes de o OS Service exportar as métricas da saga. Os 60 s são duas vezes o `PRAZOS_INTERVALO_SEGUNDOS` padrão (30 s), e o limiar muda junto quando a variável muda. O `make manifests` do `platform` prova com o promtool que cada condição dispara sozinha.

O que fazer quando "Saga parada" ou "DLQ com mensagens" dispara está no [runbook da saga](../../../operacao/runbook-saga.md).

## Alternativas Consideradas

* Stack da fase 3 com propagação pela mensageria
* Grafana Tempo no lugar do Jaeger
* Elasticsearch, Logstash e Kibana (ELK), como no hands-on da Aula 06
* Datadog ou New Relic
* Service mesh para gerar os traces

### Stack da fase 3 com propagação pela mensageria

* Bom, porque é o que o enunciado pede: as ferramentas da fase 3, estendidas a três serviços
* Bom, porque o trace único mostra a ordem das compensações e cada retry, o que o console do RabbitMQ não mostra
* Ruim, porque a propagação pela outbox e pelos passos humanos é código próprio em cada serviço

### Grafana Tempo no lugar do Jaeger

* Bom, porque levaria os traces para o Grafana, ao lado de métricas e logs, com busca por TraceQL
* Ruim, porque troca uma ferramenta da fase 3 sem ganho para o requisito, e o material ensina Jaeger (Aula 06), não Tempo

### Elasticsearch, Logstash e Kibana (ELK), como no hands-on da Aula 06

* Bom, porque é o hands-on da Aula 06, com busca textual completa nos logs
* Ruim, porque troca Loki e Promtail, já entregues na fase 3, por um Elasticsearch que pesa mais num cluster com três serviços e três bancos
* Ruim, porque cobre só logs: métricas e traces continuariam no Prometheus e no Jaeger

### Datadog ou New Relic

* Bom, porque trazem monitoramento de desempenho de aplicação (APM) e correlação prontos, e o módulo Monitoramento Avançado da fase 3 os usa
* Bom, porque dispensariam operar a stack no cluster
* Ruim, porque exigem conta, agente proprietário e chave de API guardada como segredo, não rodam no kind efêmero da integração contínua sem conta externa, e a fase 3 já os descartou (ADR-032)

### Service mesh para gerar os traces

* Bom, porque o proxy gera spans das chamadas HTTP sem código, e o Istio é o hands-on da Aula 05
* Ruim, porque a saga anda por mensagens: o proxy enxerga a conexão AMQP, não a mensagem, e não propaga contexto por ela
* Ruim, porque nem no HTTP dispensa código (a documentação do Istio exige que a aplicação repasse os headers de trace), e o sidecar em cada pod pesa no kind

## Consequências

### Positivas

* O item do vídeo (l. 122) se demonstra com o trace da saga no Jaeger, os dashboards de Saga e Mensageria e os logs da OS no Loki por `correlation_id`
* A única peça nova são os exportadores dos bancos; o resto do trabalho é instrumentação, propagação e quatro dashboards
* Saga parada, DLQ e sinais de segurança (assinatura inválida, falha do JWKS, 401, 403 e 429) têm métrica e regra
* Dashboards, regras e documentação ficam versionados no `platform` e passam por PR (pull request)

### Negativas

* Um serviço que esqueça de gravar ou restaurar o contexto parte o trace; a propagação pela outbox e pelos passos humanos tem teste próprio ([ADR-041](041-estrategia-de-testes-e-qualidade.md)), mas depende de cada processo seguir a regra
* Um trace de saga pode durar dias (o orçamento vale 72 horas), e o Jaeger da fase 3 guarda em memória: reiniciar o pod apaga os traces. A evidência permanente são os prints do trace da saga, dos quatro dashboards e de um alerta disparado, versionados em `docs/entrega/fase4/evidencias/`
* O endpoint padrão do plugin do RabbitMQ devolve métricas agregadas, sem o detalhe por fila; o alerta de DLQ exige raspar o endpoint por objeto (`/metrics/per-object` ou `/metrics/detailed`), que cresce com o número de filas
* O Promtail está em fim de vida desde 02/03/2026, sem correções novas; fica por exigência do enunciado (l. 102), e a saída é o Grafana Alloy, para onde a documentação do Loki recomenda migrar
* Mais componentes num cluster que já tem três serviços, três bancos, RabbitMQ e Kong; no kind da integração contínua, Loki, Promtail e Grafana ficam de fora ([ADR-042](042-cicd-e-deploy-kubernetes.md))
* "Acima do normal" pede linha de base; na demonstração o limite é fixado à mão e documentado com o painel

### Neutras

* Sem amostragem configurada, como na fase 3: o amostrador padrão do kit de desenvolvimento (SDK) do OpenTelemetry segue a decisão do pai, que viaja no `traceparent`, então uma saga amostrada aparece inteira; amostrar (a Aula 06 cita 50%) fica para volume real
* Sem OpenTelemetry Collector, como na fase 3 (ADR-020); o SDK exporta direto para o Jaeger
* Os limites dos alertas seguem a fase 3 e o documento dos dashboards, sem SLO formal nem error budget (Aula 06), e a notificação usa a política padrão do Grafana, sem canal externo

## Decisões Relacionadas

- [ADR-020](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p3/blob/main/docs/arquitetura/adr/fase2/020-observabilidade-opentelemetry.md): traces no Jaeger por OTLP, agora em três serviços e pela mensageria
- [ADR-024](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p3/blob/main/docs/arquitetura/adr/fase2/024-metricas-prometheus.md): base das métricas de outbox e da porta de métricas do relay
- [ADR-032](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p3/blob/main/docs/arquitetura/adr/fase3/032-monitoramento-grafana-loki.md): stack, formato dos dashboards e regras reaproveitados
- [ADR-035](035-saga-orquestrada.md): etapas, prazos e `FALHA_NA_COMPENSACAO` medidos e alertados
- [ADR-036](036-mensageria-rabbitmq.md): envelope AMQP com `traceparent` e `correlation_id`, retry e DLQ
- [ADR-038](038-borda-e-comunicacao-sincrona.md): `X-Request-ID` e métricas do Kong; circuit breaker
- [ADR-042](042-cicd-e-deploy-kubernetes.md): stack instalada com a plataforma no kind e no k3s

## Notas

* Material: Estrutura de Microsserviços Parte II, Aulas 05 e 06; Estrutura de Microsserviços, Aula 02; SAGA Pattern, Aula 05; Data Engineering, Aula 07
* Fim de vida do Promtail e migração para o Grafana Alloy: https://grafana.com/docs/loki/latest/send-data/promtail/
* W3C Trace Context: https://www.w3.org/TR/trace-context/; plugin Prometheus do RabbitMQ: https://www.rabbitmq.com/docs/prometheus; instrumentação do pika: https://opentelemetry-python-contrib.readthedocs.io/en/latest/instrumentation/pika/pika.html; propagação no Istio: https://istio.io/latest/docs/tasks/observability/distributed-tracing/overview/

> [↑ Raiz do projeto](../../../../README.md) · [↑ Arquitetura](../../README.md)
