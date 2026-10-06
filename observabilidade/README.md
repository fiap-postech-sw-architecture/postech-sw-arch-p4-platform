# Observabilidade da plataforma

> [↑ Raiz do projeto](../README.md)

Dashboards, alertas e datasources do Grafana da infraestrutura compartilhada, no formato do [documento de dashboards da fase 3](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p3/blob/main/docs/observabilidade/dashboards-grafana.md). Decisão: [ADR-043](../docs/arquitetura/adr/fase4/043-observabilidade-distribuida.md). Cada painel traz uma descrição, que aparece como dica no Grafana e se repete aqui.

## Onde estão e como sobem

| Item | Caminho |
|---|---|
| Dashboard da plataforma | [`dashboards/pytstop-plataforma.json`](dashboards/pytstop-plataforma.json) |
| Regras de alerta, no cluster e no compose | [`grafana/alertas.yaml`](grafana/alertas.yaml) |
| Regras de alerta só do cluster (dependem do Kong, que o compose não tem) | [`grafana/alertas-cluster.yaml`](grafana/alertas-cluster.yaml) |
| Datasources (Prometheus, Loki e Jaeger, com UIDs fixos; o `trace_id` dos logs vira link para o trace) | [`grafana/datasources.yaml`](grafana/datasources.yaml) |
| Provider que carrega os JSON de `dashboards/` na pasta PytStop | [`grafana/dashboards.yaml`](grafana/dashboards.yaml) |
| ConfigMaps do Kubernetes, gerados dos arquivos acima | [`kustomization.yaml`](kustomization.yaml) (configMapGenerator) |
| Teste de consistência | [`tests/test_observabilidade.py`](../tests/test_observabilidade.py) |

Os arquivos são a fonte única. No Kubernetes viram ConfigMaps com hash no nome, então mudar um dashboard troca o pod do Grafana no próximo `make deploy`; o compose monta os mesmos arquivos. Um dashboard novo entra também no `configMapGenerator`, e o `make manifests` reprova o que ficar de fora. O teste de consistência falha se um painel ficar sem descrição, se o título ou alguma consulta de um painel não estiver neste documento, ou se uma regra de alerta não estiver na tabela de alertas com UID, título e consulta, ou se severidade, janela, "sem dado" ou "onde" da tabela forem diferentes dos da regra.

Para ver no kind: `make port-forward` e `http://localhost:3000/d/pytstop-plataforma`. O acesso anônimo entra como Viewer; o admin usa a senha de demonstração do Secret `grafana-admin`.

## Dashboard PytStop - Mensageria e Serviços (infraestrutura) (`pytstop-plataforma`)

Cobre a parte de infraestrutura de dois dashboards do ADR-043: **Mensageria** (painéis 1 a 8, filas, DLQ e dead-letter do RabbitMQ) e **Serviços** (painéis 9 a 11, alvos do Prometheus e tráfego da borda). Os painéis que dependem das métricas dos serviços (saga, outbox, mensagens por tipo, RED por serviço, negócio) não estão neste arquivo. Janela padrão de 1 hora, atualização a cada 30 segundos.

| # | Painel | Tipo | Consulta (PromQL) | Como ler |
|---|---|---|---|---|
| 1 | Mensagens nas DLQs | stat | `sum by (queue) (rabbitmq_queue_messages{queue=~".+[.]dlq"})` | Um quadro por DLQ, verde em zero e vermelho a partir de uma mensagem. Mensagem aqui esgotou os retries ou falhou de forma permanente, e a saga daquela OS (ordem de serviço) está parada esperando alguém olhar. A DLQ guarda cada mensagem por até 7 dias e depois a descarta, porque ela carrega dado pessoal. Mesmo critério do alerta `pytstop-dlq-com-mensagens`; corrigida a causa, `make redrive FILA=<fila>` a devolve para a fila. |
| 2 | Consumidores por fila | stat | `sum by (queue) (rabbitmq_queue_consumers{queue!~".+[.](dlq\|retry)"})` | Consumidores conectados em `billing.comandos`, `execucao.comandos` e `os.eventos`. Zero (vermelho) quer dizer que o consumidor do serviço caiu e as mensagens vão acumular no painel 4. |
| 3 | Alarmes do broker | stat | `max(rabbitmq_alarms_memory_used_watermark)` e `max(rabbitmq_alarms_free_disk_space_watermark)` | OK ou ALARME para memória e disco. Com qualquer alarme ativo o RabbitMQ bloqueia todos os publishers; o limite de memória é o `vm_memory_high_watermark` de `k8s/base/rabbitmq/rabbitmq.conf`. |
| 4 | Mensagens prontas por fila | série | `sum by (queue) (rabbitmq_queue_messages_ready{queue!~".+[.](dlq\|retry)"})` | Mensagens esperando consumidor em cada fila de trabalho. Pico que desce é carga normal; crescimento contínuo é consumidor lento ou parado (confira o painel 2). A fila cheia (10000 mensagens) recusa a publicação. |
| 5 | Mensagens em processamento (sem ack) | série | `sum by (queue) (rabbitmq_queue_messages_unacked{queue!~".+[.](dlq\|retry)"})` | Entregues e ainda sem confirmação. O teto é o prefetch de cada consumidor; valor alto e parado sugere handler travado. |
| 6 | Entrada por fila (msg/s) | série | `sum by (queue) (rate(rabbitmq_queue_exchange_messages_published_total[$__rate_interval]))` | Ritmo de comandos e eventos roteados para cada fila, incluindo as republicações nas `.retry`. Durante uma saga aparecem os degraus de cada passo. |
| 7 | Aguardando retry e DLQ | série | `sum by (queue) (rabbitmq_queue_messages{queue=~".+[.](retry\|dlq)"})` | Profundidade das `.retry` (mensagens esperando o TTL para voltar) e das `.dlq` ao longo do tempo. Retry que sobe e desce é o mecanismo funcionando; DLQ deveria ficar em zero e descarta o que passar de 7 dias. |
| 8 | Dead-letter por motivo (msg/s) | série | `sum(rate(rabbitmq_global_messages_dead_lettered_rejected_total[$__rate_interval]))`; `sum(rate(rabbitmq_global_messages_dead_lettered_expired_total{dead_letter_strategy="at_least_once"}[$__rate_interval]))`; `sum(rate(rabbitmq_global_messages_dead_lettered_expired_total{dead_letter_strategy="disabled"}[$__rate_interval]))`; `sum(rate(rabbitmq_global_messages_dead_lettered_delivery_limit_total[$__rate_interval]))`; `sum(rate(rabbitmq_global_messages_unroutable_dropped_total[$__rate_interval]))` | Na ordem: "rejeitada" é o que foi para a DLQ; "volta do retry" é o TTL vencendo nas `.retry`, o caminho normal de uma nova tentativa; "descartada da DLQ" é mensagem que passou 7 dias na DLQ sem tratamento (a DLQ não tem dead-letter); "limite de entregas" é mensagem que derrubou o consumidor 20 vezes; "sem rota" é publicação com routing key que nenhuma fila escuta, sinal de contrato quebrado entre os serviços. |
| 9 | Alvos raspados pelo Prometheus | stat | `min by (job) (up{job!="kubelet-cadvisor"})` | Um quadro por job (label `app` do pod anotado, mais o kube-state-metrics). Vermelho quando o Prometheus não alcança o `/metrics`: serviço, broker ou gateway fora do ar. Pod que some da descoberta deixa de aparecer; para o broker e o gateway, os alertas `pytstop-rabbitmq-fora` e `pytstop-kong-fora` cobrem esse caso (o do gateway só no cluster). |
| 10 | Gateway: requisições por status (req/s) | série | `sum by (code) (rate(kong_http_requests_total[$__rate_interval]))` | Tráfego que passou pelo Kong, por código HTTP. 429 é o rate limiting do gateway; 5xx acima de 1% do total dispara o alerta `pytstop-gateway-5xx`. |
| 11 | Gateway: latência p95 por serviço | série | `histogram_quantile(0.95, sum by (le, service) (rate(kong_request_latency_ms_bucket[$__rate_interval])))` | Percentil 95 do tempo total da requisição no Kong (gateway mais serviço), por Service de destino (`<namespace>.<service>.<porta>`). |

## Regras de alerta (pasta PytStop)

Avaliadas a cada minuto e notificadas pela política padrão do Grafana, sem canal externo, como na fase 3. "Sem dado" é o estado da regra quando a consulta não devolve série: `OK` nas regras de valor, e `Alerting` nas de alvo ausente, em que a falta de série é o próprio problema. "Onde" diz em que ambiente o Grafana carrega a regra: `cluster e compose` vem de `alertas.yaml`; `só cluster` vem de `alertas-cluster.yaml`, que o compose não monta. A regra do Kong é só do cluster porque o compose não tem Kong: lá ela estaria sempre em alerta. No compose, as regras de 5xx do gateway e de CPU ficam sem dado (`OK`), pois não há Kong nem kube-state-metrics.

| UID | Alerta | Condição (PromQL) | Janela | Severidade | Sem dado | Onde | Painel relacionado |
|---|---|---|---|---|---|---|---|
| `pytstop-dlq-com-mensagens` | DLQ com mensagens | `sum by (queue) (rabbitmq_queue_messages{queue=~".+[.]dlq"})` acima de 0 | 1 min | critical | OK | cluster e compose | 1 e 7 |
| `pytstop-rabbitmq-alarme` | RabbitMQ com alarme de memória ou disco | `max(rabbitmq_alarms_memory_used_watermark) + max(rabbitmq_alarms_free_disk_space_watermark)` acima de 0 | 1 min | critical | OK | cluster e compose | 3 |
| `pytstop-gateway-5xx` | Gateway com mais de 1% de 5xx (5min) | `sum(rate(kong_http_requests_total{code=~"5.."}[5m])) / sum(rate(kong_http_requests_total[5m]))` acima de 0,01 | 5 min | critical | OK | cluster e compose | 10 |
| `pytstop-alvo-fora` | Alvo de métricas fora do ar (2min) | `min by (job) (up{job!="kubelet-cadvisor"})` abaixo de 1 | 2 min | critical | OK | cluster e compose | 9 |
| `pytstop-rabbitmq-fora` | RabbitMQ fora do ar ou sem alvo de métricas (2min) | `up{job="rabbitmq"}` abaixo de 1, ou sem série (pod apagado, Pending ou em falha some da descoberta); com o broker de pé, `up` = 1 e a regra fica OK | 2 min | critical | Alerting | cluster e compose | 9 |
| `pytstop-kong-fora` | Kong fora do ar ou sem alvo de métricas (2min) | `up{job="kong"}` abaixo de 1, ou sem série; com o Kong de pé, OK | 2 min | critical | Alerting | só cluster | 9 e 10 |
| `pytstop-cpu-pod-alta` | CPU de pod acima de 80% do limite (10min) | `sum by (namespace, pod) (rate(container_cpu_usage_seconds_total{namespace=~"pytstop-.+", container!=""}[5m])) / sum by (namespace, pod) (kube_pod_container_resource_limits{namespace=~"pytstop-.+", resource="cpu"})` acima de 0,8 | 10 min | warning | OK | cluster e compose | nenhum (CPU por pod é do dashboard Serviços do ADR-043) |

## De onde vêm as métricas

| Métrica | Tipo | Origem |
|---|---|---|
| `rabbitmq_queue_messages`, `rabbitmq_queue_messages_ready`, `rabbitmq_queue_messages_unacked`, `rabbitmq_queue_consumers` | gauges, label `queue` | Plugin `rabbitmq_prometheus` do broker, endpoint `/metrics/per-object` da porta 15692 (anotação do StatefulSet em [`rabbitmq.yaml`](../k8s/base/rabbitmq/rabbitmq.yaml)), que traz uma série por fila |
| `rabbitmq_queue_exchange_messages_published_total` | contador, label `queue` | Mesmo endpoint |
| `rabbitmq_global_messages_dead_lettered_rejected_total`, `..._expired_total`, `..._delivery_limit_total`, `rabbitmq_global_messages_unroutable_dropped_total` | contadores, label `dead_letter_strategy` | Mesmo endpoint, métricas globais do broker |
| `rabbitmq_alarms_memory_used_watermark`, `rabbitmq_alarms_free_disk_space_watermark` | gauges 0 ou 1 | Mesmo endpoint |
| `kong_http_requests_total`, `kong_request_latency_ms_bucket` | contador (labels `code`, `service`, `route`) e histograma | Plugin `prometheus` global do Kong ([`plugins.yaml`](../k8s/base/kong/plugins.yaml), com `status_code_metrics` e `latency_metrics`), status listener da porta 8100 |
| `up` | gauge do Prometheus | Job `pods-anotados` (job = label `app` do pod) e `kube-state-metrics`, em [`config/prometheus.yml`](../k8s/base/observabilidade/config/prometheus.yml) |
| `container_cpu_usage_seconds_total` | contador | cAdvisor do kubelet (job `kubelet-cadvisor`) |
| `kube_pod_container_resource_limits` | gauge | kube-state-metrics ([`kube-state-metrics.yaml`](../k8s/base/observabilidade/kube-state-metrics.yaml)) |

## Evidências

O `make smoke` mostra, no kind, o dashboard e as regras carregados pelo Grafana e quantas séries cada consulta acima devolve, e sai com status 1 se faltar regra (a conta vem dos arquivos de `grafana/`) ou se alguma não estiver saudável; a saída de uma execução está no corpo do PR que introduziu este documento.
