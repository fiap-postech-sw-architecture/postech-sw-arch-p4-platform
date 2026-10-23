# Endereços e variáveis

> [↑ Raiz do projeto](../README.md)

São as variáveis que o profile `servicos` do compose passa aos serviços; nos manifests Kubernetes de cada serviço os mesmos nomes recebem os endereços completos. `<svc>` é o nome do Service que o repositório do serviço define.

| Variável | Serviços | Kubernetes | compose |
|---|---|---|---|
| `RABBITMQ_URL` | todos | do Secret `rabbitmq` do namespace do serviço: `amqp://<usuario>:<senha>@rabbitmq.pytstop-plataforma.svc.cluster.local:5672/%2F` | `amqp://<usuario>:<senha>@rabbitmq:5672/%2F` |
| `OTEL_ENABLED`, `OTEL_SERVICE_NAME` | todos | `true`, nome do serviço (`os-service`, `billing-service`, `execution-service`) | iguais |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | todos | `http://jaeger.pytstop-plataforma.svc.cluster.local:4317` (gRPC) ou `:4318` (HTTP) | `http://jaeger:4317` |
| `SMTP_HOST` / `SMTP_PORT` | OS | `mailpit.pytstop-plataforma.svc.cluster.local` / `1025` | `mailpit` / `1025` |
| `DATABASE_URL` | OS e Execução | PostgreSQL do próprio serviço, no namespace dele, com o papel `os_app` ou `execucao_app` nos processos e o dono (`os` ou `execucao`) no Job de migração ([Contrato com os serviços](contrato-com-os-servicos.md#contrato-com-os-serviços)) | `postgresql://pytstop:pytstop@postgres-os:5432/os` e `...@postgres-execucao:5432/execucao` |
| `MONGODB_URI` | Billing | MongoDB do próprio serviço, no namespace dele | `mongodb://mongo-billing:27017/billing?replicaSet=rs0` |
| `RUN_MIGRATIONS_ON_STARTUP` | OS e Execução | `false` (migração em Job antes do rollout) | `true` |
| `JWKS_URL` | Billing e Execução | `http://<svc>.pytstop-os.svc.cluster.local:8000/.well-known/jwks.json` | `http://os-service:8000/.well-known/jwks.json` |
| `BILLING_URL` | Execução | `http://<svc>.pytstop-billing.svc.cluster.local:8000` | `http://billing-service:8000` |
| `MP_MODE` | Billing | `simulado` | `simulado` |

Métricas, o contrato do [ADR-043](arquitetura/adr/fase4/043-observabilidade-distribuida.md): cada processo do serviço (`api`, `relay`, `consumidor`, `notificador` e `prazos`) roda no seu Deployment e serve `/metrics` numa porta declarada em `ports` do container, com o nome `metrics` (a API serve na própria porta HTTP). O Prometheus raspa sozinho, por pod, todo pod dos namespaces `pytstop-*` com as anotações abaixo no template; a porta anotada precisa estar em `ports`. O label `app` do pod vira o `job` nos painéis, e o label `processo` vai para a série como `processo`.

```yaml
metadata:
  labels:
    app: os-service-relay
    processo: relay
  annotations:
    prometheus.io/scrape: "true"
    prometheus.io/port: "9100"
    prometheus.io/path: /metrics
spec:
  containers:
    - name: relay
      ports:
        - name: metrics
          containerPort: 9100
```

Logs: JSON no stdout basta. O Promtail coleta todos os pods dos namespaces `pytstop-*` com os labels `namespace`, `app`, `pod` e `container`; o campo `trace_id` do JSON vira link para o trace no Jaeger dentro do Grafana. `request_id` e `correlation_id` se buscam por filtro de linha (`{namespace="pytstop-os"} |= "<correlation_id>"`), nunca por label.

Antes de enviar ao Loki, o Promtail troca por `***` o token de `/publico/orcamentos/<token>`, de `/simulador/checkout/<token>` e de `token=<valor>`, em qualquer linha, com a barra também como `%2F` (o Kong loga o caminho como chegou, inclusive o do pedido que ele barra com 404): no access log do Kong e no log dos serviços ([RFC-004, seção 8](arquitetura/rfc/fase4/rfc-004-microsservicos-saga.md#8-segurança)). O `make manifests` roda o pipeline real, o do cluster e o do compose, com `promtail -dry-run` sobre linhas de exemplo e reprova token sem máscara em qualquer um dos dois. O `kubectl logs` do pod continua com a linha original, por isso o serviço não deve logar o token.
