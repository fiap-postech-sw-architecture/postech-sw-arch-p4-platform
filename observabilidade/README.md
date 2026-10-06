# Observabilidade da plataforma

Provisioning do Grafana usado pelo Kubernetes (ConfigMaps gerados por [`kustomization.yaml`](kustomization.yaml)) e pelo compose (os mesmos arquivos montados nos containers):

| Arquivo | Conteúdo |
|---|---|
| [`grafana/datasources.yaml`](grafana/datasources.yaml) | Prometheus (padrão), Loki e Jaeger, com UIDs fixos; o `trace_id` dos logs vira link para o trace |
| [`grafana/dashboards.yaml`](grafana/dashboards.yaml) | Provider que carrega os JSON de `dashboards/` na pasta PytStop |
| [`grafana/alertas.yaml`](grafana/alertas.yaml) | Regras de alerta da plataforma |
| [`dashboards/`](dashboards) | Um JSON por dashboard; todo arquivo novo entra também no `configMapGenerator` (o CI reprova o que ficar de fora) |

Os dashboards de saga e de negócio chegam com os serviços; o desta pasta cobre a infraestrutura compartilhada.

## PytStop - Plataforma

[`dashboards/pytstop-plataforma.json`](dashboards/pytstop-plataforma.json), uid `pytstop-plataforma`, atualização a cada 30s, janela padrão de 1 hora. As métricas do RabbitMQ vêm do endpoint `/metrics/per-object` (porta 15692), que traz uma série por fila; as do Kong, do status listener (porta 8100) com o plugin `prometheus` global.

| # | Painel | Consulta | Como ler |
|---|---|---|---|
| 1 | Mensagens nas DLQs | `sum by (queue) (rabbitmq_queue_messages{queue=~".+[.]dlq"})` | Um quadro por DLQ, verde em zero e vermelho a partir de uma mensagem. Mensagem aqui esgotou os retries ou falhou de forma permanente, e a saga daquela OS está parada esperando alguém olhar. A DLQ guarda cada mensagem por até 7 dias (`x-message-ttl`, porque ela carrega dado pessoal) e depois a descarta. Mesmo critério do alerta "DLQ com mensagens". |
| 2 | Consumidores por fila | `sum by (queue) (rabbitmq_queue_consumers{queue!~".+[.](dlq\|retry)"})` | Consumidores conectados em `billing.comandos`, `execucao.comandos` e `os.eventos`. Zero (vermelho) quer dizer que o consumidor do serviço caiu e as mensagens vão acumular no painel 4. |
| 3 | Alarmes do broker | `max(rabbitmq_alarms_memory_used_watermark)` e `max(rabbitmq_alarms_free_disk_space_watermark)` | OK ou ALARME para memória e disco. Com qualquer alarme ativo o RabbitMQ bloqueia todos os publishers; o limite de memória é o `vm_memory_high_watermark` de `k8s/base/rabbitmq/rabbitmq.conf`. |
| 4 | Mensagens prontas por fila | `sum by (queue) (rabbitmq_queue_messages_ready{queue!~".+[.](dlq\|retry)"})` | Mensagens esperando consumidor em cada fila de trabalho. Pico que desce é carga normal; crescimento contínuo é consumidor lento ou parado (confira o painel 2). |
| 5 | Mensagens em processamento (sem ack) | `sum by (queue) (rabbitmq_queue_messages_unacked{queue!~".+[.](dlq\|retry)"})` | Entregues e ainda sem confirmação. O teto é o prefetch de cada consumidor; valor alto e parado sugere handler travado. |
| 6 | Entrada por fila (msg/s) | `sum by (queue) (rate(rabbitmq_queue_exchange_messages_published_total[$__rate_interval]))` | Ritmo de comandos e eventos roteados para cada fila, incluindo as republicações nas `.retry`. Durante uma saga aparecem os degraus de cada passo. |
| 7 | Aguardando retry e DLQ | `sum by (queue) (rabbitmq_queue_messages{queue=~".+[.](retry\|dlq)"})` | Profundidade das `.retry` (mensagens esperando o TTL para voltar) e das `.dlq` ao longo do tempo. Retry que sobe e desce é o mecanismo funcionando; DLQ deveria ficar em zero e descarta o que passar de 7 dias. |
| 8 | Dead-letter por motivo (msg/s) | `rate` de `rabbitmq_global_messages_dead_lettered_{rejected,expired,delivery_limit}_total` e de `rabbitmq_global_messages_unroutable_dropped_total` | "rejeitada" é o que foi para a DLQ; "volta do retry" é o TTL vencendo nas `.retry` (`dead_letter_strategy="at_least_once"`), o caminho normal de uma nova tentativa; "descartada da DLQ" é mensagem que passou 7 dias na DLQ sem tratamento (`dead_letter_strategy="disabled"`, a DLQ não tem dead-letter); "limite de entregas" é mensagem que derrubou o consumidor 20 vezes; "sem rota" é publicação com routing key que nenhuma fila escuta, sinal de contrato quebrado entre os serviços. |
| 9 | Alvos raspados pelo Prometheus | `min by (job) (up{job!="kubelet-cadvisor"})` | Um quadro por job (label `app` do pod anotado, mais o kube-state-metrics). Vermelho quando o Prometheus não alcança o `/metrics`: serviço, broker ou gateway fora do ar. Mesmo critério do alerta "Alvo de métricas fora do ar". |
| 10 | Gateway: requisições por status (req/s) | `sum by (code) (rate(kong_http_requests_total[$__rate_interval]))` | Tráfego que passou pelo Kong por código HTTP. 429 é o rate limiting das rotas públicas; 5xx acima de 1% do total dispara o alerta do gateway. |
| 11 | Gateway: latência p95 por serviço | `histogram_quantile(0.95, sum by (le, service) (rate(kong_request_latency_ms_bucket[$__rate_interval])))` | Percentil 95 do tempo total da requisição no Kong (gateway mais serviço), por Service de destino (`<namespace>.<service>.<porta>`). |

## Alertas

Provisionados em [`grafana/alertas.yaml`](grafana/alertas.yaml), pasta PytStop, avaliados a cada minuto e notificados pela policy padrão do Grafana (sem canal externo, como na fase 3).

| Alerta | Condição | Severidade |
|---|---|---|
| DLQ com mensagens | alguma `.dlq` com mensagem por 1 minuto | critical |
| RabbitMQ com alarme de memória ou disco | alarme ativo por 1 minuto | critical |
| Gateway com mais de 1% de 5xx | razão de 5xx sobre o total do Kong acima de 1% por 5 minutos | critical |
| Alvo de métricas fora do ar | `up` de algum job abaixo de 1 por 2 minutos | critical |
| CPU de pod acima de 80% do limite | uso do cAdvisor sobre o limite do kube-state-metrics acima de 0,8 por 10 minutos, nos namespaces `pytstop-*` | warning |

Alertas de saga (compensações acima do normal, saga parada, circuito aberto) entram junto com os dashboards de saga.
