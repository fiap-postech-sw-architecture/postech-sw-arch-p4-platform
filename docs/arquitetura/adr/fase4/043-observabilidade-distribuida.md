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

Todo Deployment expõe a porta `metrics`, com as anotações de descoberta, e o Prometheus usa `kubernetes_sd` nos três namespaces `pytstop-*` e no da plataforma, raspando por pod, com o rótulo `processo` (`api`, `relay`, `consumidor`, `notificador` e `prazos`; o `notificador` só existe no OS Service). As métricas de saga, mensageria e negócio nascem em processos sem tráfego HTTP de negócio, como relay e consumidor; por isso cada processo serve a sua porta `metrics`, como o relay do p3 já fazia (`relay/metrics.py:117-125`).

### Rastreamento (RNF-056)

- OpenTelemetry nos três serviços, instrumentando FastAPI, SQLAlchemy/psycopg, PyMongo e httpx, com exportação OTLP para o Jaeger. A mensageria não usa o `PikaInstrumentor`: os serviços criam os spans próprios de publicação (`publish`) e de consumo (`process`) e propagam o contexto pelo envelope, à mão.
- O contexto W3C (`traceparent`, `tracestate`) viaja nos headers AMQP (*Advanced Message Queuing Protocol*) do envelope ([ADR-036](036-mensageria-rabbitmq.md)). Quem publica é o relay, fora da requisição de origem, e por isso o instrumentador do pika não teria o contexto certo para injetar: a outbox grava o `traceparent` (e o `tracestate`) com a mensagem, o relay publica dentro desse contexto e escreve os dois nos headers AMQP, e o consumidor os lê dos headers ao abrir o span de consumo. O span do consumidor é filho do span de publicação, e cada passagem por uma fila de retry acrescenta spans ao mesmo trace. Na chamada REST de negócio entre serviços (Execução para Billing), o httpx propaga o contexto.
- Passos retomados por pessoa, sistema externo ou prazo (diagnóstico e execução pelo mecânico, decisão do cliente, webhook do Mercado Pago, processos `prazos`) começam com trace próprio. Para não partir a saga, o registro que espera o passo guarda o `traceparent` da mensagem que o pôs em espera, e o evento seguinte é publicado como filho desse contexto, com span link para o trace de quem retomou. Cada saga vira um trace no Jaeger, com raiz na abertura da OS.
- Laços ociosos (poll de segurança do relay, relay do MongoDB, coletores de métricas e processos `prazos`) só abrem span quando há trabalho: o amostrador de cada serviço é um `ParentBased` com uma raiz que descarta o span de cliente sem pai (a consulta de poll, a do coletor e o ciclo vazio do `prazos` são só consultas ao banco), e `/metrics` e as sondas ficam fora da instrumentação HTTP. O Jaeger guarda os traces em memória, com retenção por contagem (`MEMORY_MAX_TRACES` em 250, o `--memory.max-traces`: o trace de uma saga chega a 339 spans com os três serviços, perto de 4 MB, e o teto vale para o mix medido do E2E, em que 1 trace em 66 é de saga; umas 110 sagas esgotam os 512 Mi do pod, o limite que protege o resto) e sem TTL: o trace mais antigo sai quando entra o seguinte, então, para a demonstração, gera-se o tráfego e captura-se o trace logo ([Retenção e prazos](../../../../observabilidade/README.md#retenção-e-prazos)). O token do link de decisão e do checkout nunca vai para um atributo de span: o hook de cada serviço grava o template da rota.

### Correlação e logs

`correlation_id` = `ordem_id` (o mesmo `saga_id`) em todas as mensagens e em toda linha de log. Os logs JSON levam também `trace_id`, `span_id` e `request_id`, sem dado pessoal e sem os campos de texto livre (`descricao_problema`, `observacoes`, `motivo`); a limpeza de logs mascara o `{token}` do link de decisão e trata `link_decisao` e `checkout_url` como sensíveis ([ADR-039](039-autenticacao-entre-servicos.md)), e o Promtail mascara o mesmo token no access log antes de enviá-lo ao Loki. Uma consulta por `correlation_id` no Loki traz a OS nos três serviços, e o `trace_id` leva ao trace no Jaeger. O `X-Request-ID` nasce na borda, no plugin `correlation-id` do Kong, com gerador `uuid` ([ADR-038](038-borda-e-comunicacao-sincrona.md)).

### Métricas

Métricas novas levam o prefixo `pytstop_`; as herdadas do p3 mantêm o nome (`outbox_pendentes`, `outbox_dead`, `http_request_duration_seconds`), para reaproveitar regras e painéis.

- Saga: os contadores `pytstop_saga_iniciadas_total`, `pytstop_saga_finalizadas_total{resultado}` (`resultado` em `concluida` ou `compensada`), `pytstop_saga_compensacoes_total{motivo}`, `pytstop_saga_reenvios_total{comando}` e `pytstop_saga_prazos_esgotados_total{comando}`, estes dois do processo `prazos`, com o tipo do comando no label; o histograma `pytstop_saga_etapa_duracao_segundos{etapa}`; e os gauges da saga, `pytstop_saga_ativas{etapa}`, `pytstop_saga_etapa_mais_antiga_segundos{etapa}` (idade da instância mais antiga em cada etapa) e `pytstop_saga_prazo_vencido_segundos` (maior atraso, `agora` menos (`entregue_em` mais `SAGA_PRAZO_RESPOSTA_SEGUNDOS`) da linha da outbox do envio mais recente do comando em voo, entre as instâncias com esse envio entregue e o prazo vencido; zero sem atraso, e o comando pendente ou `dead` na outbox não conta: a pendente é acusada por "Outbox parada", e a `dead`, por "Outbox com linha morta"). Os gauges da saga são calculados por um coletor da API na hora da raspagem, por consulta às tabelas `sagas` e `outbox`, como as métricas de outbox do p3, e continuam certos com o `prazos` fora do ar. O coletor publica ainda `pytstop_saga_coletor_disponivel` (1 se leu as sagas, 0 se a leitura falhou, caso em que os gauges de contagem e de idade saem ausentes, nunca em zero) e conta as falhas em `pytstop_saga_coletor_falhas_total`. O label `etapa` leva o nome da etapa em minúsculas, e o `motivo` é enumeração fechada: `orcamento_recusado`, `orcamento_expirado`, `geracao_falhou`, `reserva_falhou`, `pagamento_recusado`, `pagamento_expirado`, `cancelamento` e `prazo_tecnico`. O texto livre fica só na OS, nunca no log.
- Mensageria: `pytstop_mensagens_publicadas_total{tipo}`, `pytstop_mensagens_consumidas_total{tipo,resultado}`, `outbox_pendentes` e `outbox_dead`, que o relay de cada serviço exporta e a API do Billing também, `pytstop_outbox_mais_antiga_segundos` (idade da linha pendente mais antiga de cada serviço, zero sem pendente, calculada pelo coletor da API, que continua exportando com o relay parado; no Billing o relay também a exporta, e os painéis e alertas usam `max` por namespace, nunca `sum`) e `pytstop_reconexoes_ao_broker_total{componente}` (esperas antes de reconectar ao RabbitMQ, com `componente` em `relay` ou `consumidor`), mais o plugin Prometheus do RabbitMQ (profundidade por fila, inclusive das filas de mensagens mortas, as DLQ, consumidores e taxas de publicação e confirmação).
- Integrações: `pytstop_mercadopago_requisicoes_total{operacao,resultado}`, `pytstop_circuit_breaker_aberto{dependencia}` (1 aberto, 0 fechado e, na Execução, 0,5 em meia-abertura; o disjuntor `mercadopago` do Billing só existe com o gateway real) e `pytstop_pagamentos_estornados_total{motivo}`, com `motivo` em `compensacao` ou `pagamento_apos_encerramento`; mais `pytstop_estornos_automaticos_recusados_total` e `pytstop_cancelamentos_de_cobranca_recusados_total` (o provedor recusou o estorno automático ou fechar o checkout) e `pytstop_prazos_ultimo_ciclo_timestamp_seconds` (fim de cada ciclo do `prazos` do OS Service e do Billing).
- Negócio: `pytstop_os_criadas_total`, `pytstop_os_por_status{status}` e `pytstop_os_tempo_medio_status_segundos{status}` (gauges por consulta do coletor da API do OS Service, a mesma conta do `GET /api/v1/ordens-de-servico/metricas`; a segunda só existe para o status com permanência concluída nos últimos 30 dias, e some, nunca vira zero), `pytstop_orcamentos_tempo_decisao_segundos{decisao}` (histograma da geração à decisão, do Billing), `pytstop_pagamentos_valor_centavos_total{estado}` (centavos inteiros em `confirmado` e `estornado`, do Billing: o Prometheus guarda `float64`, e o painel divide por 100; o estorno no consumidor conta pelo menos uma vez) e, na Execução, `pytstop_execucao_duracao_media_segundos{servico}` e `pytstop_pecas_em_falta{sku}` (gauges por consulta com janela de 7 dias, ausentes sem dado). As séries de rótulo fechado nascem com zero no boot, para o `increase()` não perder o primeiro evento; as de rótulo aberto saem do banco.
- Segurança: `pytstop_webhook_assinatura_invalida_total` e `pytstop_jwks_falhas_total`, mais as respostas 401, 403 e 429 do Kong por rota.
- Bancos: `postgres_exporter` ao lado de cada PostgreSQL (conexões, transações, locks e tamanho) e `mongodb_exporter` ao lado do MongoDB (documentos, tamanho e estado do replica set, com as flags `--collector.dbstats --collector.replicasetstatus`; as conexões e as operações do MongoDB exigem `--collector.diagnosticdata`, que soma cerca de 2.100 séries ao alvo e fica fora por ora), o monitoramento centralizado de bancos da Aula 07 de Data Engineering.
- As métricas HTTP da fase 3 em cada serviço e o plugin `prometheus` do Kong na borda.

O rótulo de `pytstop_reconexoes_ao_broker_total` é `componente`, e não `processo`, porque o Prometheus já põe `processo` em todo alvo (`relabel_configs`) e um rótulo da métrica com o mesmo nome viraria `exported_processo`. Cada métrica, com o tipo, os rótulos e o processo que a emite, está no catálogo do [`observabilidade/README.md`](../../../../observabilidade/README.md#catálogo-de-métricas), que o teste de consistência do `platform` confere contra as consultas de todo painel e de todo alerta. O prazo de raspagem é o `scrape_timeout` de 10 s do Prometheus, com os coletores dos serviços limitados a 5 s (OS e Execução) e 2 s (Billing) no total.

### Dashboards

Um arquivo JSON por dashboard em `observabilidade/dashboards/` no `platform`, cada painel com descrição e documentado numa tabela (pergunta, consulta e como ler), no formato do [documento de dashboards da fase 3](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p3/blob/main/docs/observabilidade/dashboards-grafana.md), com o teste de consistência que falha se um painel ficar sem descrição ou sem documentação, se o texto do painel divergir do `description` do JSON ou se uma consulta usar métrica ou rótulo que o catálogo não lista. Os de negócio (tag `negocio`) ficam em JSON separado dos técnicos (tag `tecnico`), como a banca da fase 3 pediu, e documentados em [`observabilidade/negocio.md`](../../../../observabilidade/negocio.md); os técnicos, no [`observabilidade/README.md`](../../../../observabilidade/README.md). Os quatro temas abaixo se dividem em nove arquivos: o da plataforma (broker e borda) e os quatro técnicos (Saga, Mensageria dos serviços, Serviços e Bancos), mais os quatro de negócio.

| Dashboard | Arquivos | Responde |
|---|---|---|
| Saga | `pytstop-saga` | quantas sagas começam, terminam e compensam; em que etapa estão as ativas e há quanto tempo; quanto dura cada etapa; reenvios e prazos esgotados |
| Mensageria | `pytstop-plataforma` (filas, DLQ e dead-letter do broker) e `pytstop-mensageria` | profundidade das filas de trabalho, de retry e de DLQ; outbox pendente, morta e a idade da mais antiga; mensagens publicadas e consumidas por tipo e resultado; reconexões |
| Serviços | `pytstop-plataforma` (alvos e borda), `pytstop-servicos` e `pytstop-bancos` | taxa, erros e duração (RED, de *rate*, *errors* e *duration*) por serviço e na borda; taxa de sucesso por serviço (um menos a razão de 5xx); 401, 403 e 429 do Kong; circuitos abertos; chamadas ao Mercado Pago; CPU e memória por pod; conexões, transações, locks e tamanho de cada PostgreSQL, e documentos, tamanho e estado do replica set do MongoDB |
| Negócio | `pytstop-negocio-atendimento`, `-orcamentos`, `-pagamentos` e `-execucao` | volume diário de OS e tempo médio por status (o RF-027 da fase 3, que a banca pediu), no mesmo cálculo de `GET /api/v1/ordens-de-servico/metricas`; funil, desfecho e motivos de cancelamento das sagas; orçamentos por desfecho e tempo até a decisão; faturamento e estornos; filas da oficina, tempo médio de execução por serviço (o RF-008 da fase 1) e peças em falta |

### Alertas

No Grafana, como na fase 3, separando aviso de alerta crítico, como recomenda a Aula 06. As cinco regras da fase 3 continuam, aplicadas a cada serviço, e a saga acrescenta o conjunto abaixo. Sem dado, as regras ficam em OK (`noDataState`), como na fase 3, exceto as de serviço e banco fora do ar, que usam `noDataState: Alerting`. A regra de serviço consulta `up{job=...}` com condição menor que 1: alvo derrubado (`up` em 0) e alvo que sumiu da descoberta (sem série) alertam, e serviço no ar fica em OK.

| Alerta | Condição | Janela (`for`) | Severidade |
|---|---|---|---|
| DLQ com mensagens | alguma fila `.dlq` com mensagem, pela métrica por fila do plugin do RabbitMQ | 1 min | crítico |
| Saga parada | prazo técnico vencido e não tratado há mais de 60 s, em qualquer etapa, alguma instância em `falha_na_compensacao`, ou o coletor das sagas indisponível (consulta abaixo) | 5 min | crítico |
| Compensações acima do normal | razão entre compensações e sagas iniciadas acima de um limite tirado do comportamento normal | 30 min | aviso |
| Erro 5xx acima de 1% | regra da fase 3, agregada por serviço | 5 min | crítico |
| Circuito aberto | `max_over_time(pytstop_circuit_breaker_aberto[2m])` acima de 0,5 (1, aberto) para qualquer dependência e qualquer réplica; a meia-abertura (0,5) que a Execução publica não conta, porque sem tráfego o gauge fica nela. A janela de 2 min existe porque o disjuntor da Execução fica aberto só 30 s: sem ela, o `for` de 1 min não veria duas avaliações seguidas em 1 com tráfego raro | 1 min | aviso |
| Outbox parada | `pytstop_outbox_mais_antiga_segundos` acima de 300 s em qualquer serviço, o que mostra broker fora do ar ou relay parado (`outbox_pendentes` acima de zero dispararia em falso com tráfego contínuo) | 5 min | crítico |
| Outbox com linha morta | `outbox_dead` acima de zero em qualquer serviço (o relay desistiu de publicar a linha; a saga que a espera não anda sozinha) | 1 min | crítico |
| Latência p95 acima de 500 ms | regra da fase 3, agregada por serviço, sem as sondas; o limiar é um fim de faixa do histograma (250 ms, 500 ms, 1 s), porque o `histogram_quantile` interpola dentro da faixa e um limiar no meio dela dispararia sem o p95 ter passado dele | 5 min | aviso |
| Serviço fora do ar | `max(up{job="<serviço>-api"})` abaixo de 1, ou sem série (nenhuma réplica da API de pé) | 2 min | crítico |
| Banco fora do ar | `min by (job) (pg_up) or min by (job) (mongodb_up)` abaixo de 1 (o exporter do banco não o alcança), ou sem série (nenhum exporter de banco na descoberta); `noDataState: Alerting`, como as de serviço fora do ar | 1 min | crítico |
| Fila de trabalho sem consumidor | `rabbitmq_queue_consumers` abaixo de 1 em `billing.comandos`, `execucao.comandos` ou `os.eventos` (consumidor do serviço fora) | 2 min | crítico |
| Assinatura inválida no webhook | `pytstop_webhook_assinatura_invalida_total` crescendo | 5 min | aviso |
| Falha na busca do conjunto de chaves públicas (JWKS) | `pytstop_jwks_falhas_total` crescendo | 5 min | aviso |

A regra de saga parada é uma consulta só, `max(pytstop_saga_prazo_vencido_segundos) > 60 or max(pytstop_saga_ativas{etapa="falha_na_compensacao"}) > 0 or (1 - min(pytstop_saga_coletor_disponivel)) > 0 or (max(up{job=~"os-service(-api)?"}) unless on() pytstop_saga_coletor_disponivel) or vector(0)`, que dispara acima de 0. Com o `or`, a série que falta numa condição não esconde a outra, e o `vector(0)` deixa a regra com valor zero quando nenhuma condição vale, inclusive sem o OS Service no ar. As duas últimas condições existem porque o coletor, quando não lê as sagas, omite os gauges das duas primeiras: o `min` pega a réplica com o coletor em 0, e a série ausente com a API de pé (o `max` do `up` do job, `os-service-api` no cluster e `os-service` no compose, vale 1 com ao menos uma réplica de pé e 0 com todas caídas, que o limiar descarta) pega o OS Service que não exporta o coletor. Os 60 s são duas vezes o `PRAZOS_INTERVALO_SEGUNDOS` padrão (30 s); o limiar e a `summary` ficam literais em `alertas.yaml` e não acompanham a variável, então quem muda o intervalo muda também os dois. O `make manifests` do `platform` prova com o promtool que cada condição dispara sozinha e que coletor sadio, queda do coletor menor que a janela e OS Service fora do ar não disparam.

Todos os alertas da tabela estão implementados em `observabilidade/grafana/`: `alertas.yaml` (no cluster e no compose), `alertas-cluster.yaml` (só no cluster, porque dependem do Kong, do relay e do consumidor) e `alertas-outbox-parada.yaml`. "Outbox com linha morta" é `max by (namespace) (outbox_dead)`: o `max`, e nunca o `sum`, porque o Billing exporta a série da API e do relay. Cada regra tem na tabela do `observabilidade/README.md` o painel relacionado e, em `tests/alertas.promtool.yml`, um caso que dispara e um que não dispara, provados no promtool pelo `make manifests`; "sem dado" é conferido contra o `noDataState` de cada regra. Com o banco fora a série da outbox some, e a regra fica em OK sem dado (ausência não é zero); o alerta próprio de banco fora usa `pg_up` e `mongodb_up`, como o dashboard Bancos. Ele dispara se um exporter alcançável não acessar seu banco ou se nenhum exporter de banco estiver na descoberta. A ausência de um único exporter, enquanto os demais permanecem, não é detectada por essa regra; falha na raspagem é coberta pelo alerta de alvo fora.

Os valores de "Outbox parada" (300 s e 5 min) são os de produção, nos overlays `base` e `k3s`. Com eles, mostrar o alerta disparado no vídeo (escalar o relay de um serviço a 0, gerar tráfego e esperar) levaria cerca de 11 minutos, porque a linha pendente precisa envelhecer 300 s e a janela soma mais 5 min. Por isso o overlay `kind` troca, no ConfigMap `grafana-alerting`, o arquivo da regra por uma cópia que usa 30 s e 1 min, só nessa regra; o `observabilidade/README.md` diz os dois conjuntos de valores e o procedimento da captura, e o teste de consistência confere que só o `kind` traz os valores curtos e que a diferença para o `k3s` é só essa regra. O promtool testa os valores de produção.

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

* O item do vídeo (l. 122) se demonstra com o trace da saga no Jaeger, os dashboards de Saga e Mensageria, o de negócio (volume diário de OS e tempo médio por status) e os logs da OS no Loki por `correlation_id`
* A única peça nova são os exportadores dos bancos; o resto do trabalho é instrumentação, propagação e oito dashboards novos
* Saga parada, DLQ e sinais de segurança (assinatura inválida, falha do JWKS, 401, 403 e 429) têm métrica e regra
* Dashboards, regras e documentação ficam versionados no `platform` e passam por PR (pull request)

### Negativas

* Um serviço que esqueça de gravar ou restaurar o contexto parte o trace; a propagação pela outbox e pelos passos humanos tem teste próprio ([ADR-041](041-estrategia-de-testes-e-qualidade.md)), mas depende de cada processo seguir a regra
* Um trace de saga pode durar dias (o orçamento vale 72 horas), e o Jaeger da fase 3 guarda em memória: reiniciar o pod apaga os traces. A evidência permanente são os prints do trace da saga, de cada dashboard e de um alerta disparado, versionados em `docs/entrega/fase4/evidencias/`
* O endpoint padrão do plugin do RabbitMQ devolve métricas agregadas, sem o detalhe por fila; o alerta de DLQ exige raspar o endpoint por objeto (`/metrics/per-object` ou `/metrics/detailed`), que cresce com o número de filas
* O Promtail está em fim de vida desde 02/03/2026, sem correções novas; fica por exigência do enunciado (l. 102), e a saída é o Grafana Alloy, para onde a documentação do Loki recomenda migrar
* Mais componentes num cluster que já tem três serviços, três bancos, RabbitMQ e Kong; no kind da integração contínua, Loki, Promtail e Grafana ficam de fora ([ADR-042](042-cicd-e-deploy-kubernetes.md))
* "Acima do normal" pede linha de base; na demonstração o limite é fixado à mão e documentado com o painel

### Neutras

* O amostrador é o `ParentBased` do kit de desenvolvimento (SDK) do OpenTelemetry com uma raiz que só descarta o span de cliente sem pai: segue a decisão do pai, que viaja no `traceparent`, então uma saga amostrada aparece inteira, e todo o resto é amostrado; reduzir a taxa (a Aula 06 cita 50%) fica para volume real
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
* W3C Trace Context: https://www.w3.org/TR/trace-context/; plugin Prometheus do RabbitMQ: https://www.rabbitmq.com/docs/prometheus; propagação no Istio: https://istio.io/latest/docs/tasks/observability/distributed-tracing/overview/

> [↑ Raiz do projeto](../../../../README.md) · [↑ Arquitetura](../../README.md)
