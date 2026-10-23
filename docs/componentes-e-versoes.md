# Componentes e versões

> [↑ Raiz do projeto](../README.md)

Todas as imagens têm tag fixa, e a mesma versão roda no kind, no k3s e no compose: o `make manifests` reprova imagem com mais de uma tag entre `k8s/`, compose e Makefile, ou fora desta tabela. Nos manifests dos serviços, o `implantar-servicos.sh` reprova imagem de terceiro fora desta tabela ([Contrato com os serviços](contrato-com-os-servicos.md#contrato-com-os-serviços)).

| Componente | Versão | Para que serve | Endereço no cluster |
|---|---|---|---|
| RabbitMQ | `rabbitmq:4.3.6-management` | Broker da saga: comandos do OS para Billing e Execução, eventos de volta | `rabbitmq.pytstop-plataforma.svc.cluster.local:5672` |
| Kong Gateway | `kong:3.9.3` (chart `kong/kong` 3.4.1) | Gateway único (`/os`, `/billing`, `/execucao`), X-Request-ID, rate limit, métricas | `kong-proxy` (portas 80/443 do host no kind) |
| Kong Ingress Controller | `kong/kubernetes-ingress-controller:3.5.13` | Lê os Ingress dos quatro namespaces da fase 4 (`pytstop-plataforma`, `pytstop-os`, `pytstop-billing` e `pytstop-execucao`; IngressClass `kong`) e configura o Kong sem banco | sidecar do pod do Kong |
| Prometheus | `prom/prometheus:v2.54.1` | Métricas: pods anotados dos namespaces `pytstop-*`, cAdvisor e kube-state-metrics | `prometheus.pytstop-plataforma.svc.cluster.local:9090` |
| Grafana | `grafana/grafana:11.1.0` | Dashboards, logs, traces e alertas provisionados de `observabilidade/` | `grafana.pytstop-plataforma.svc.cluster.local:3000` |
| Loki | `grafana/loki:2.9.8` | Armazena e consulta os logs | `loki.pytstop-plataforma.svc.cluster.local:3100` |
| Promtail | `grafana/promtail:3.6.11` | Coleta os logs de todos os pods dos namespaces `pytstop-*` | DaemonSet |
| Jaeger | `jaegertracing/all-in-one:1.76.0` | Traces OTLP (*OpenTelemetry Protocol*) de todos os serviços, com o trace da saga atravessando HTTP e mensagens | `jaeger.pytstop-plataforma.svc.cluster.local:4317` (gRPC) e `:4318` (HTTP) |
| kube-state-metrics | `registry.k8s.io/kube-state-metrics/kube-state-metrics:v2.13.0` | Limites de recursos dos pods, para o alerta de CPU | interno ao Prometheus |
| metrics-server | `registry.k8s.io/metrics-server/metrics-server:v0.9.0` | Métricas de CPU e memória para o HPA dos serviços e o `kubectl top` (só no kind; o k3s traz o dele) | `kube-system` |
| Mailpit | `axllent/mailpit:v1.31.4` | SMTP de demonstração e caixa de entrada web das notificações ao cliente | `mailpit.pytstop-plataforma.svc.cluster.local:1025` |
| Kubernetes do kind | `kindest/node:v1.35.0` (por digest em [`kind/cluster.yaml`](../kind/cluster.yaml)) | Nó do cluster local; o `make manifests` valida os manifests contra a mesma versão | - |
| PostgreSQL | `postgres:16.15` | Banco do OS e da Execução: no Kubernetes, o StatefulSet que cada serviço traz no próprio namespace; no compose, um container por serviço | `os-postgres.pytstop-os.svc.cluster.local:5432` e `execucao-postgres.pytstop-execucao.svc.cluster.local:5432`; no compose, `postgres-os:5432` e `postgres-execucao:5432` |
| MongoDB | `mongo:7.0.43` | Banco do Billing, em replica set de um nó (`rs0`): StatefulSet no namespace do Billing e um container no compose | `billing-mongo-0.billing-mongo.pytstop-billing.svc.cluster.local:27017`; no compose, `mongo-billing:27017` |
| postgres_exporter | `prometheuscommunity/postgres-exporter:v0.20.1` | Métricas do PostgreSQL (conexões, transações, locks, tamanho), sidecar do banco do OS e da Execução, porta 9187, que conecta com o papel `os_exporter` ou `execucao_exporter` (`pg_monitor`), não com o superusuário ([ADR-043](arquitetura/adr/fase4/043-observabilidade-distribuida.md)) | sidecar do StatefulSet do banco |
| mongodb_exporter | `percona/mongodb_exporter:0.53.0` | Métricas do MongoDB, sidecar do banco do Billing, porta 9216, que conecta com o usuário `exporter`, com `--collector.dbstats` e `--collector.replicasetstatus` | sidecar do StatefulSet do banco |
| SonarQube (CI dos serviços) | `sonarqube:26.9.0.129388-community` | Servidor efêmero do job `sonarqube` de cada serviço, que aplica o quality gate ([ADR-041](arquitetura/adr/fase4/041-estrategia-de-testes-e-qualidade.md)) | service container do job |
| SonarScanner (CI dos serviços) | `sonarsource/sonar-scanner-cli:12.2.0.4256_8.1.0` | Análise do código no mesmo job | - |
| OWASP ZAP (job `e2e` do `platform`) | `ghcr.io/zaproxy/zaproxy:2.17.0@sha256:7aaa659b0d43078febd82e29bad112285c370727e86ab8340444220e17d9f0d2` | Varredura *baseline* da borda do kind, um serviço por vez, com um spider que chama cada operação do `openapi.json` ([ZAP baseline na borda](zap.md#zap-baseline-na-borda), [ADR-041](arquitetura/adr/fase4/041-estrategia-de-testes-e-qualidade.md)); o digest é o do índice da imagem, que serve amd64 e arm64 | container do runner, na rede do host |

Prometheus, Grafana, Loki, Promtail, kube-state-metrics, Mailpit e Jaeger vieram dos manifests da fase 3, ajustados para vários serviços em vários namespaces e com probes de liveness e readiness em todos.

O Promtail está em fim de vida desde 02/03/2026. Ele continua aqui porque o enunciado pede a observabilidade da fase 3, que o usa. Saiu do 2.9 da fase 3 para a 3.6, a última linha, porque o cliente Docker do 2.9 fala uma versão de API que o Docker 29 do compose recusa. A saída é o Grafana Alloy, que lê os mesmos pods e empurra para o mesmo Loki.
