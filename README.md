# PytStop fase 4: plataforma

Infraestrutura compartilhada da fase 4 e os contratos de mensageria entre os serviços. Aqui ficam o RabbitMQ, o gateway Kong, o Mailpit e a stack de observabilidade (Prometheus, Grafana, Loki, Promtail, Jaeger, kube-state-metrics), todos no namespace `pytstop-plataforma`, mais o metrics-server do kind, a mesma stack em docker compose e o catálogo de comandos e eventos da saga em AsyncAPI e JSON Schema. Os manifests de cada serviço ficam no repositório do serviço, em namespace próprio (`pytstop-os`, `pytstop-billing`, `pytstop-execucao`).

Parte da fase 4 do Tech Challenge (FIAP Pós Tech, Software Architecture, 15SOAT): o PytStop, sistema de gestão de oficina mecânica das fases anteriores, refatorado em microsserviços com Saga Pattern, mensageria assíncrona, CI/CD por serviço e deploy automatizado em Kubernetes. Testes E2E entre os serviços, arquitetura global (requisitos, ADRs, RFC-004) e os documentos da entrega também vão morar neste repositório.

## Repositórios da fase 4

| Repositório | Papel |
|---|---|
| [postech-sw-arch-p4-os-service](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-os-service) | Ordens de serviço, clientes e veículos, usuários internos e orquestrador da saga |
| [postech-sw-arch-p4-billing-service](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-billing-service) | Orçamentos, pagamentos via Mercado Pago e tabela de preços |
| [postech-sw-arch-p4-execution-service](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-execution-service) | Fila de diagnóstico e execução e estoque de peças |
| [postech-sw-arch-p4-platform](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-platform) | Infraestrutura compartilhada, contratos, testes E2E, arquitetura global e entrega |

A `main` é protegida desde o primeiro commit: toda mudança entra por pull request com squash.

## Conteúdo

| Caminho | O que é |
|---|---|
| [`kind/cluster.yaml`](kind/cluster.yaml) | Cluster kind `pytstop-p4` de um nó, com as portas 80/443 do host (só loopback) mapeadas para o Kong |
| [`k8s/base/`](k8s/base) | Kustomize da infraestrutura compartilhada no namespace `pytstop-plataforma` |
| [`k8s/overlays/kind`](k8s/overlays/kind), [`k8s/overlays/k3s`](k8s/overlays/k3s) | StorageClass, exposição do Kong e recursos de cada ambiente; o kind leva também o metrics-server |
| [`observabilidade/`](observabilidade) | Datasources, alertas e dashboards do Grafana, usados pelo Kubernetes e pelo compose; [documentação painel a painel](observabilidade/README.md) |
| [`compose/`](compose) | A mesma infraestrutura em docker compose, com os bancos de cada serviço e um profile que sobe os três serviços |
| [`contratos/`](contratos) | AsyncAPI 3.0 dos comandos e eventos, JSON Schema do envelope e de cada mensagem, exemplos e testes |
| [`Makefile`](Makefile) | Atalhos de cluster, deploy, compose e testes (`make` lista os alvos) |

## Subir a plataforma

### Kubernetes local (kind)

Precisa de Docker, [kind](https://kind.sigs.k8s.io/) e kubectl (o kustomize vem embutido). As portas 80 e 443 do loopback precisam estar livres.

```bash
make kind-up        # cria o cluster pytstop-p4 (contexto kind-pytstop-p4)
make deploy         # CRDs do Kong, overlay kind, rollouts e o Job de usuários do RabbitMQ
make status         # pods, serviços, volumes e filas do RabbitMQ
make port-forward   # Grafana :3000, Jaeger :16686, RabbitMQ :15672, Prometheus :9090, Mailpit :8025
make kind-down      # apaga o cluster
```

O cluster se chama `pytstop-p4` para não colidir com o `pytstop` que o `make cd-local` da fase 3 cria na mesma máquina. Todo `kubectl` do Makefile usa o contexto `kind-pytstop-p4` explicitamente; para olhar outro cluster, `make status KUBE_CONTEXT=<contexto>`.

O gateway responde em `http://localhost/`. Sem nenhum serviço publicado ele devolve 404 (`no Route matched`), o que já mostra o Kong no ar.

Credenciais de demonstração (no compose, os mesmos valores estão em [`compose/docker-compose.yml`](compose/docker-compose.yml)):

| Onde | Usuário | Senha |
|---|---|---|
| Grafana (`http://localhost:3000`, anônimo entra como Viewer) | `admin` | `kubectl -n pytstop-plataforma get secret grafana-admin -o jsonpath='{.data.GF_SECURITY_ADMIN_PASSWORD}' \| base64 -d` |
| RabbitMQ management (`http://localhost:15672`) | `admin` | `kubectl -n pytstop-plataforma get secret rabbitmq-credenciais -o jsonpath='{.data.admin-senha}' \| base64 -d` |

### k3s (VM na Azure)

O overlay `k3s` assume o k3s instalado com `--disable traefik`: o Service `kong-proxy` continua `LoadBalancer` e o ServiceLB do k3s publica as portas 80/443 da VM no Kong. O k3s já traz metrics-server. Com o contexto do k3s:

```bash
kubectl apply --server-side -f k8s/base/kong/crds.yaml
kubectl wait --for=condition=Established -f k8s/base/kong/crds.yaml
kubectl -n pytstop-plataforma delete job rabbitmq-usuarios --ignore-not-found
kubectl apply --server-side -k k8s/overlays/k3s
kubectl -n pytstop-plataforma wait --for=condition=Complete job/rabbitmq-usuarios --timeout=180s
```

A diferença para o kind está no próprio [`kustomization.yaml`](k8s/overlays/k3s/kustomization.yaml): StorageClass `local-path`, volume de 5Gi e mais memória reservada (request) para o RabbitMQ, e sete dias de retenção no Prometheus.

### docker compose

```bash
make up                    # infraestrutura
make up PROFILE=servicos   # infraestrutura + os três serviços, construídos dos repositórios irmãos
make down                  # derruba tudo; os volumes ficam (docker compose -f compose/docker-compose.yml down -v apaga)
```

O serviço `rabbitmq-usuarios` roda o mesmo script do Job do Kubernetes e fica saudável quando os usuários estão criados; os serviços do profile só sobem depois disso. O profile `servicos` constrói `../postech-sw-arch-p4-os-service`, `../postech-sw-arch-p4-billing-service` e `../postech-sw-arch-p4-execution-service` (clones irmãos deste repositório) e sobe a API de cada um. Relay e consumidor entram no profile quando as imagens dos serviços tiverem esses comandos.

Portas no host, todas no loopback e trocáveis por variável de ambiente (`GRAFANA_PORT=3001 make up`) para conviver com o compose de cada serviço:

| Serviço | Porta | Variável |
|---|---|---|
| RabbitMQ AMQP / management | 5672 / 15672 | `RABBITMQ_PORT` / `RABBITMQ_UI_PORT` |
| PostgreSQL do OS / da Execução | 5433 / 5434 | `POSTGRES_OS_PORT` / `POSTGRES_EXECUCAO_PORT` |
| MongoDB do Billing (replica set `rs0`) | 27017 | `MONGO_BILLING_PORT` |
| Grafana / Prometheus / Loki | 3000 / 9090 / 3100 | `GRAFANA_PORT` / `PROMETHEUS_PORT` / `LOKI_PORT` |
| Jaeger UI / OTLP gRPC / OTLP HTTP | 16686 / 4317 / 4318 | `JAEGER_UI_PORT` / `OTLP_GRPC_PORT` / `OTLP_HTTP_PORT` |
| Mailpit UI / SMTP | 8025 / 1025 | `MAILPIT_UI_PORT` / `MAILPIT_SMTP_PORT` |
| OS / Billing / Execução (profile `servicos`) | 8001 / 8002 / 8003 | `OS_SERVICE_PORT` / `BILLING_SERVICE_PORT` / `EXECUTION_SERVICE_PORT` |

Do host, o MongoDB do replica set responde em `mongodb://localhost:27017/billing?directConnection=true` (o membro do replica set se anuncia como `mongo-billing`, nome que só resolve dentro da rede do compose).

## Componentes e versões

Todas as imagens têm tag fixa; a mesma versão roda no kind, no k3s e no compose.

| Componente | Versão | Para que serve | Endereço no cluster |
|---|---|---|---|
| RabbitMQ | `rabbitmq:4.3.6-management` | Broker da saga: comandos do OS para Billing e Execução, eventos de volta | `rabbitmq.pytstop-plataforma.svc.cluster.local:5672` |
| Kong Gateway | `kong:3.9.3` (chart `kong/kong` 3.4.1) | Gateway único (`/os`, `/billing`, `/execucao`), X-Request-ID, rate limit, métricas | `kong-proxy` (portas 80/443 do host no kind) |
| Kong Ingress Controller | `kong/kubernetes-ingress-controller:3.5.13` | Lê os Ingress de todos os namespaces (IngressClass `kong`) e configura o Kong sem banco | sidecar do pod do Kong |
| Prometheus | `prom/prometheus:v2.54.1` | Métricas: pods anotados de qualquer namespace, cAdvisor e kube-state-metrics | `prometheus.pytstop-plataforma.svc.cluster.local:9090` |
| Grafana | `grafana/grafana:11.1.0` | Dashboards, logs, traces e alertas provisionados de `observabilidade/` | `grafana.pytstop-plataforma.svc.cluster.local:3000` |
| Loki | `grafana/loki:2.9.8` | Armazena e consulta os logs | `loki.pytstop-plataforma.svc.cluster.local:3100` |
| Promtail | `grafana/promtail:3.6.11` | Coleta os logs de todos os pods dos namespaces `pytstop-*` | DaemonSet |
| Jaeger | `jaegertracing/all-in-one:1.76.0` | Traces OTLP de todos os serviços, com o trace da saga atravessando HTTP e mensagens | `jaeger.pytstop-plataforma.svc.cluster.local:4317` (gRPC) e `:4318` (HTTP) |
| kube-state-metrics | `registry.k8s.io/kube-state-metrics/kube-state-metrics:v2.13.0` | Limites de recursos dos pods, para o alerta de CPU | interno ao Prometheus |
| metrics-server | `registry.k8s.io/metrics-server/metrics-server:v0.9.0` | Métricas de CPU e memória para o HPA dos serviços e o `kubectl top` (só no kind; o k3s traz o dele) | `kube-system` |
| Mailpit | `axllent/mailpit:v1.30.3` | SMTP de demonstração e caixa de entrada web das notificações ao cliente | `mailpit.pytstop-plataforma.svc.cluster.local:1025` |

Prometheus, Grafana, Loki, Promtail, kube-state-metrics, Mailpit e Jaeger vieram dos manifests da fase 3, ajustados para vários serviços em vários namespaces e com probes de liveness e readiness em todos.

O Promtail está em fim de vida desde 02/03/2026. Ele continua aqui porque o enunciado pede a observabilidade da fase 3, que o usa. Saiu do 2.9 da fase 3 para a 3.6, a última linha, porque o cliente Docker do 2.9 fala uma versão de API que o Docker 29 do compose recusa. A saída é o Grafana Alloy, que lê os mesmos pods e empurra para o mesmo Loki.

## Como os serviços se conectam

### Usuário e permissões no RabbitMQ

Cada serviço tem um usuário próprio, criado pelo Job `rabbitmq-usuarios` ([`criar-usuarios.sh`](k8s/base/rabbitmq/criar-usuarios.sh)) com as senhas do Secret `rabbitmq-credenciais` e as permissões de [`permissoes.json`](k8s/base/rabbitmq/permissoes.json). Ninguém tem permissão de configure: a topologia inteira vem do [`definitions.json`](k8s/base/rabbitmq/definitions.json), importado no boot do broker, e o serviço só confere o que precisa com declaração passiva. Assim nenhum comando volta como não roteável porque o consumidor do destino ainda não subiu.

Além do exchange, a permissão de tópico limita as routing keys que cada usuário publica. Sem ela, um serviço poderia publicar evento em nome de outro ou mandar uma cópia ao `pytstop.retry` com a routing key da fila de outro serviço e entregar mensagem lá.

| Usuário | Publica em | Routing keys permitidas | Lê de | Senha (chave do Secret) |
|---|---|---|---|---|
| `os` | `pytstop.comandos`, `pytstop.retry` | `comando.billing.*` e `comando.execucao.*`; no retry, só `os.eventos` | `os.eventos` | `senha-os` |
| `billing` | `pytstop.eventos`, `pytstop.retry` | `evento.billing.*`; no retry, só `billing.comandos` | `billing.comandos` | `senha-billing` |
| `execucao` | `pytstop.eventos`, `pytstop.retry` | `evento.execucao.*`; no retry, só `execucao.comandos` | `execucao.comandos` | `senha-execucao` |
| `admin` | tudo (operação e management) | tudo | tudo | `admin-senha` |

Secret não atravessa namespace: cada serviço tem no próprio namespace um Secret com a `AMQP_URL` completa, usando a senha de demonstração da chave correspondente.

### Endereços e variáveis

São as variáveis que o profile `servicos` do compose passa aos serviços; nos manifests Kubernetes de cada serviço os mesmos nomes recebem os endereços completos. `<svc>` é o nome do Service que o repositório do serviço define.

| Variável | Serviços | Kubernetes | compose |
|---|---|---|---|
| `AMQP_URL` | todos | `amqp://<usuario>:<senha>@rabbitmq.pytstop-plataforma.svc.cluster.local:5672/%2F` | `amqp://<usuario>:<senha>@rabbitmq:5672/%2F` |
| `OTEL_ENABLED`, `OTEL_SERVICE_NAME` | todos | `true`, nome do serviço (`os-service`, `billing-service`, `execution-service`) | iguais |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | todos | `http://jaeger.pytstop-plataforma.svc.cluster.local:4317` (gRPC) ou `:4318` (HTTP) | `http://jaeger:4317` |
| `SMTP_HOST` / `SMTP_PORT` | OS | `mailpit.pytstop-plataforma.svc.cluster.local` / `1025` | `mailpit` / `1025` |
| `DATABASE_URL` | OS e Execução | PostgreSQL do próprio serviço, no namespace dele | `postgresql://pytstop:pytstop@postgres-os:5432/os` e `...@postgres-execucao:5432/execucao` |
| `MONGODB_URL` | Billing | MongoDB do próprio serviço, no namespace dele | `mongodb://mongo-billing:27017/billing?replicaSet=rs0` |
| `RUN_MIGRATIONS_ON_STARTUP` | OS e Execução | `false` (migração em Job antes do rollout) | `true` |
| `JWKS_URL` | Billing e Execução | `http://<svc>.pytstop-os.svc.cluster.local:8000/.well-known/jwks.json` | `http://os-service:8000/.well-known/jwks.json` |
| `BILLING_URL` | Execução | `http://<svc>.pytstop-billing.svc.cluster.local:8000` | `http://billing-service:8000` |
| `MP_MODE` | Billing | `simulado` | `simulado` |

Métricas: o Prometheus raspa sozinho qualquer pod, de qualquer namespace, com estas anotações no template do pod. A porta anotada precisa estar declarada em `ports` do container; o label `app` do pod vira o `job` nos painéis.

```yaml
metadata:
  labels:
    app: os-service-api
  annotations:
    prometheus.io/scrape: "true"
    prometheus.io/port: "8000"
    prometheus.io/path: /metrics
```

Logs: JSON no stdout basta. O Promtail coleta todos os pods dos namespaces `pytstop-*` com os labels `namespace`, `app`, `pod` e `container`; o campo `trace_id` do JSON vira link para o trace no Jaeger dentro do Grafana. `request_id` e `correlation_id` se buscam por filtro de linha (`{namespace="pytstop-os"} |= "<correlation_id>"`), nunca por label.

### Gateway: como um serviço publica as rotas

O serviço cria os próprios Ingress, no próprio namespace, com `ingressClassName: kong`. Os plugins `correlation-id` e `prometheus` são globais e valem para toda rota sem anotação. O rate limiting (60 requisições por minuto por IP) entra só nas rotas públicas, pela anotação `konghq.com/plugins: rate-limiting-publico`; como os três plugins são `KongClusterPlugin`, o Ingress de qualquer namespace pode usá-los.

Com `strip-path`, o Kong tira do caminho tudo o que a regra casou. Um Ingress em `/os` entrega `/os/api/v1/...` ao serviço como `/api/v1/...`. Para limitar só as rotas públicas, o segundo Ingress casa `/os/api/v1/publico` e aponta para um Service extra com `konghq.com/path`, que devolve o prefixo `/api/v1/publico` ao caminho. O Kong escolhe a regra de caminho mais longo, então a rota pública não cai na geral.

```yaml
# Todas as rotas do serviço, sem limite: /os/api/v1/... chega como /api/v1/...
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: os-service
  namespace: pytstop-os
  annotations:
    konghq.com/strip-path: "true"
spec:
  ingressClassName: kong
  rules:
    - http:
        paths:
          - path: /os
            pathType: Prefix
            backend:
              service:
                name: os-service-api
                port:
                  number: 8000
---
# Mesmos pods; o Kong prefixa /api/v1/publico no que sobrar depois do strip.
apiVersion: v1
kind: Service
metadata:
  name: os-service-publico
  namespace: pytstop-os
  annotations:
    konghq.com/path: /api/v1/publico
spec:
  selector:
    app: os-service-api
  ports:
    - port: 8000
      targetPort: 8000
---
# Rotas públicas, com rate limiting: /os/api/v1/publico/x chega como /api/v1/publico/x
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: os-service-publico
  namespace: pytstop-os
  annotations:
    konghq.com/strip-path: "true"
    konghq.com/plugins: rate-limiting-publico
spec:
  ingressClassName: kong
  rules:
    - http:
        paths:
          - path: /os/api/v1/publico
            pathType: Prefix
            backend:
              service:
                name: os-service-publico
                port:
                  number: 8000
```

O Kong informa o trecho tirado no header `X-Forwarded-Prefix` (`/os/` na rota geral); o FastAPI precisa de `root_path="/os"` para o Swagger em `/os/docs` achar o `openapi.json`. O `X-Request-ID` gerado pelo Kong é um UUID simples (`generator: uuid`), aceito como está pelo middleware de request id que os serviços herdaram da fase 3 (`[A-Za-z0-9._=-]{1,128}`); o formato `uuid#counter` seria descartado por ele. Se o cliente mandar um `X-Request-ID`, o Kong o mantém e devolve na resposta. O `kong-proxy` usa `externalTrafficPolicy: Local` para o rate limiting enxergar o IP real do cliente. No k3s, confira no log de acesso do Kong que o IP do cliente chega: dependendo da configuração de rede do nó (por exemplo, com `--node-external-ip`), o ServiceLB pode mascarar o endereço, e aí o limite vira um balde só para todos.

### Filas, exchanges e argumentos

Toda a topologia está em [`k8s/base/rabbitmq/definitions.json`](k8s/base/rabbitmq/definitions.json), importada pelo RabbitMQ no boot (kind, k3s e compose). Os serviços não declaram nada com efeito: só conferem com declaração passiva (`passive=True`), que não exige permissão. Os argumentos abaixo servem para quem precisar recriar a topologia em outro broker.

| Exchange | Tipo | Para que serve |
|---|---|---|
| `pytstop.comandos` | topic | Comandos do OS (`comando.<serviço de destino>.<ação>`) |
| `pytstop.eventos` | topic | Eventos de Billing e Execução (`evento.<serviço de origem>.<fato>`) |
| `pytstop.retry` | topic | Cópias para nova tentativa; a routing key é o nome da fila de trabalho. É topic, com bindings de chave exata, só para aceitar permissão de tópico; num direct qualquer serviço com escrita no exchange alcançaria a fila de outro |
| `pytstop.dlx` | direct | Dead-letter das filas de trabalho; a routing key é o nome da fila |

| Fila | Consumidor | Bindings | Argumentos |
|---|---|---|---|
| `billing.comandos` | Billing | `pytstop.comandos` com `comando.billing.#` | `x-queue-type=quorum`, `x-dead-letter-exchange=pytstop.dlx`, `x-dead-letter-routing-key=billing.comandos`, `x-dead-letter-strategy=at-least-once`, `x-overflow=reject-publish` |
| `execucao.comandos` | Execução | `pytstop.comandos` com `comando.execucao.#` | os mesmos, com `x-dead-letter-routing-key=execucao.comandos` |
| `os.eventos` | OS | `pytstop.eventos` com `evento.billing.#` e `evento.execucao.#` | os mesmos, com `x-dead-letter-routing-key=os.eventos` |
| `<fila>.retry` | ninguém | `pytstop.retry` com routing key `<fila>` | `x-queue-type=quorum`, `x-dead-letter-exchange=""` (default exchange), `x-dead-letter-routing-key=<fila>`, `x-dead-letter-strategy=at-least-once`, `x-overflow=reject-publish`; sem `x-message-ttl`: o TTL vem em cada mensagem |
| `<fila>.dlq` | ninguém (análise e replay manual) | `pytstop.dlx` com routing key `<fila>` | `x-queue-type=quorum`, `x-message-ttl=604800000` (7 dias: as mensagens carregam dado pessoal, como a placa) |

Todas duráveis, não exclusivas e sem auto-delete. No consumidor do Billing, com pika:

```python
canal.queue_declare("billing.comandos", passive=True)  # confere, não cria
canal.basic_qos(prefetch_count=10)  # por consumidor; a fila quorum não aceita global
canal.confirm_delivery()  # basic_publish espera o broker confirmar


def nova_tentativa(canal, entrega, propriedades, corpo, tentativa):
    atrasos_ms = ["1000", "5000", "15000", "60000", "300000"]
    # mandatory + confirm: se a cópia não for roteada ou o broker a recusar,
    # o pika levanta UnroutableError/NackError antes do ack, e a original fica.
    canal.basic_publish(
        exchange="pytstop.retry",
        routing_key="billing.comandos",
        body=corpo,
        properties=pika.BasicProperties(
            message_id=propriedades.message_id,
            correlation_id=propriedades.correlation_id,
            type=propriedades.type,
            content_type="application/json",
            delivery_mode=2,
            expiration=atrasos_ms[tentativa - 1],
            headers={**(propriedades.headers or {}), "x-tentativa": tentativa},
        ),
        mandatory=True,
    )
    canal.basic_ack(entrega.delivery_tag)
```

Fluxo de uma mensagem que falha no consumidor:

1. Erro transitório: o consumidor publica uma cópia no `pytstop.retry` com a routing key igual ao nome da fila, `expiration` crescente por tentativa (1s, 5s, 15s, 60s, 300s) e o header `x-tentativa`, espera a confirmação do broker (publisher confirms, `mandatory`) e só então dá ack na original. O broker põe a cópia em `<fila>.retry`.
2. Quando o TTL vence, a `.retry` devolve a mensagem para `<fila>` pelo default exchange, com o histórico no header `x-death`. Esse dead-letter é interno ao broker e não pede permissão do serviço.
3. Depois da 5ª tentativa, ou em erro permanente (validação, schema), o consumidor faz `basic_reject(requeue=False)` e a mensagem vai para `<fila>.dlq` pelo `pytstop.dlx`, onde fica até 7 dias.
4. Mensagem que derruba o consumidor sem ack (conexão ou canal fechados) volta para a fila; no RabbitMQ 4 a fila quorum manda para a DLQ depois de 20 reentregas (limite padrão de entregas). `basic_nack` ou `basic_reject` com `requeue=True` não conta para esse limite: a mensagem volta para a fila indefinidamente. Retry é sempre pelo `pytstop.retry`.

Por que filas quorum e não classic duráveis: a quorum grava em log Raft com fsync antes de confirmar, aceita TTL por mensagem e faz dead-lettering at-least-once (exige `x-overflow=reject-publish`). Assim a volta da `.retry` e a ida para a `.dlq` não perdem mensagem; na classic o dead-lettering é at-most-once. Com um nó não há replicação, mas os clientes não mudam se o broker virar cluster. O custo é um pouco mais de memória e disco por fila, e o prefetch tem de ser por consumidor, porque a quorum não aceita prefetch global.

Limite conhecido: TTL por mensagem só vence quando a mensagem chega à cabeça da fila. Numa `.retry` com uma mensagem de 300s na frente, uma de 1s espera os 300s. Com o volume da demonstração isso não aparece; se aparecer, a saída é uma fila de retry por atraso.

## Contratos de mensageria

| Arquivo | Conteúdo |
|---|---|
| [`contratos/asyncapi.yaml`](contratos/asyncapi.yaml) | AsyncAPI 3.0: um canal por routing key (exchange e chave), um por fila de trabalho, a operação de envio de cada mensagem e a de consumo de cada fila |
| [`contratos/schemas/envelope.schema.json`](contratos/schemas/envelope.schema.json) | JSON Schema 2020-12 do envelope comum |
| `contratos/schemas/<Mensagem>.schema.json` | JSON Schema 2020-12 do campo `dados` de cada uma das 34 mensagens |
| `contratos/exemplos/<Mensagem>.json` | Envelope completo de exemplo; juntos contam uma saga do pedido de diagnóstico até a compensação |
| [`contratos/tests/test_contratos.py`](contratos/tests/test_contratos.py) | Testes que amarram catálogo, AsyncAPI, schemas, exemplos e a topologia do RabbitMQ |

O catálogo é o da seção 4 do design brief, mais `AnonimizarVeiculo` (comando do OS para a Execução, LGPD: a Execução troca a placa guardada pelo marcador `ANONIMIZADO:{veiculo_id}`) e `PagamentoCancelado` (resposta do Billing ao `EstornarPagamento` quando o pagamento ainda estava pendente); `SolicitarDiagnostico` leva também o `veiculo_id`. `AnonimizarVeiculo` é o único comando sem evento de resposta: se falhar de vez, o sinal é a mensagem na `execucao.comandos.dlq` e o alerta "DLQ com mensagens", e ela some da DLQ em 7 dias.

Envelope de toda mensagem:

```json
{"id": "<uuid>", "tipo": "GerarOrcamento", "versao": 1, "origem": "os-service",
 "correlation_id": "<ordem_id>", "causation_id": "<id da mensagem que causou ou null>",
 "ocorrido_em": "2026-10-06T12:45:00Z", "dados": {}}
```

Propriedades AMQP: `message_id` = `id`, `correlation_id`, `type` = `tipo`, `content_type=application/json`, `delivery_mode=2` e os headers `traceparent`/`tracestate` (W3C), mais `x-tentativa` nas republicações. `correlation_id` é o id da OS (a instância da saga); fora da saga, o id do agregado tratado (`AnonimizarVeiculo`: `veiculo_id`).

Regras que os schemas impõem:

- Routing key `comando.<serviço de destino>.<ação>` ou `evento.<serviço de origem>.<fato>`, com o nome da mensagem em snake_case: `GerarOrcamento` vai em `comando.billing.gerar_orcamento`, `PecasReservadas` em `evento.execucao.pecas_reservadas`.
- Valor monetário em string decimal com duas casas (`"820.00"`) e `moeda: "BRL"`; número em ponto flutuante é rejeitado.
- Data e hora em RFC 3339 e em UTC (`Z` ou `+00:00`).
- Ids (`ordem_id`, `veiculo_id`, `orcamento_id`, `pagamento_id`, `reserva_id`, `mecanico_id`) são UUID; placa normalizada sem hífen (`ABC1234` ou `ABC1D23`).
- `codigo` de serviço e `sku` de peça: até 50 caracteres entre letras, dígitos, `.`, `_` e `-`, começando por letra ou dígito.
- Diagnóstico concluído, pedido de orçamento e orçamento gerado têm ao menos um item; `ReservarPecas` e `ExecucaoFinalizada` aceitam lista vazia (orçamento só de serviços).
- `prioridade` do `AgendarExecucao`: `normal` (padrão) ou `alta`; a fila de execução atende `alta` antes e, dentro da mesma prioridade, por ordem de agendamento.
- Nenhum campo além dos definidos (`additionalProperties: false`).

Mudança de contrato começa por um PR aqui. Campo novo opcional: atualiza o schema e o exemplo, depois os consumidores copiam o schema e só então o produtor passa a enviar. Mudança incompatível vira `versao: 2` do tipo. Cada serviço copia os schemas que produz e consome e os valida no próprio teste de contrato.

```bash
make test   # exemplos contra schemas, referências do AsyncAPI, convenção de routing key, topologia
make lint   # ruff, mypy strict e bandit
```

## CI

O workflow [`ci.yml`](.github/workflows/ci.yml) roda em pull request para a `main`, sob demanda e quando o CD o chama (`workflow_call`), com dois jobs que são checks obrigatórios da branch protection:

- `manifests`: `make manifests`, ou seja, `kustomize build` dos dois overlays validado pelo kubeconform (schemas do Kubernetes e, para os plugins do Kong, o catálogo de CRDs da datree), `docker compose config` com o profile `servicos` e a checagem de que todo dashboard JSON está no configMapGenerator.
- `contratos`: `uv lock --check`, `make lint` e `make test`.

`make check` roda os três alvos localmente.

## Decisões e limites desta versão

- Kong por `helm template` do chart `kong/kong` 3.4.1 versionado em [`k8s/base/kong/kong.yaml`](k8s/base/kong/kong.yaml): o Kong Ingress Controller 3.x não publica mais os manifests all-in-one. `make kong-render` regenera a partir de [`values.yaml`](k8s/base/kong/values.yaml). O webhook de validação ficou desligado porque o chart gera o certificado dele na renderização, e versionar o resultado poria uma chave privada no repositório.
- Senhas de demonstração versionadas (Secrets `rabbitmq-credenciais` e `grafana-admin`, marcadas com `gitleaks:allow`), as mesmas no kind e no k3s. O brief prevê credenciais geradas no cluster; a geração no deploy fica para a próxima onda, e até lá o k3s de avaliação usa os valores de demonstração.
- O admin do RabbitMQ entra no boot junto com a topologia (arquivo `admin.json` do Secret), porque com definitions no boot o broker não cria usuário nenhum e o Job de usuários precisa de alguém para falar com a API.
- `pytstop.retry` é topic, não direct como na decisão de topologia: o RabbitMQ só aplica permissão por routing key em exchange topic, e sem ela a escrita no `pytstop.retry` deixaria qualquer serviço pôr mensagem na fila de trabalho de outro. Os bindings usam a chave exata (o nome da fila), então o roteamento é o mesmo de um direct.
- Versões de Prometheus, Grafana e Loki iguais às da fase 3. Jaeger fixado na última 1.x; a linha 2.x fica para depois.
- Sem persistência em Prometheus, Loki e Grafana (o estado do Grafana vem todo do provisioning; o TSDB do Prometheus fica num emptyDir). Só o RabbitMQ tem volume.
