# PytStop fase 4: plataforma

Infraestrutura compartilhada da fase 4 e os contratos de mensageria entre os serviços: o RabbitMQ, o gateway Kong, o Mailpit e a stack de observabilidade (Prometheus, Grafana, Loki, Promtail, Jaeger e kube-state-metrics), todos no namespace `pytstop-plataforma`, mais o metrics-server do kind, uma stack docker compose para desenvolver um serviço e o catálogo de comandos e eventos da saga em AsyncAPI e JSON Schema. Os manifests de cada serviço ficam no repositório do serviço, em namespace próprio (`pytstop-os`, `pytstop-billing`, `pytstop-execucao`).

O PytStop é o sistema de gestão de oficina mecânica das fases anteriores do Tech Challenge (FIAP Pós Tech, Software Architecture, 15SOAT), refatorado na fase 4 em microsserviços com Saga Pattern, mensageria assíncrona, CI/CD por serviço e deploy automatizado em Kubernetes. A arquitetura está na [RFC-004](docs/arquitetura/rfc/fase4/rfc-004-microsservicos-saga.md) e nos ADRs 034 a 043 de [`docs/arquitetura/`](docs/arquitetura).

## Repositórios da fase 4

| Repositório | Papel |
|---|---|
| [postech-sw-arch-p4-os-service](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-os-service) | OS Service: ordens de serviço (OS), clientes e veículos, usuários internos e orquestrador da saga |
| [postech-sw-arch-p4-billing-service](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-billing-service) | Billing Service: orçamentos, pagamentos via Mercado Pago e tabela de preços |
| [postech-sw-arch-p4-execution-service](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-execution-service) | Execution Service, do contexto Execução (no texto, "Execução"): fila de diagnóstico e de execução e estoque de peças |
| [postech-sw-arch-p4-platform](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-platform) | Este: infraestrutura compartilhada, contratos, testes ponta a ponta (E2E), arquitetura global e documentos da entrega ([ADR-034](docs/arquitetura/adr/fase4/034-decomposicao-em-microsservicos.md)) |

O único commit da `main` fora de pull request é o `Initial commit` que o GitHub cria com o repositório. Desde então tudo entra por PR com squash, e o [ruleset da `main`](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-platform/rules/24599837) exige os checks `manifests` e `contratos` do [CI](.github/workflows/ci.yml) ([ADR-042](docs/arquitetura/adr/fase4/042-cicd-e-deploy-kubernetes.md)).

## Papel deste repositório

É complementar aos três serviços. O enunciado pede no mínimo três microsserviços, cada um com repositório, infraestrutura e banco próprios ([desafio, l. 27](docs/requisitos/fase4/desafio-tech-fase-4.md)), e eles são os três repositórios acima. Aqui fica o que eles compartilham e que não pertence a nenhum: o broker, o gateway, a observabilidade e o contrato das mensagens. Não é um quarto microsserviço: não tem código de domínio nem banco.

| O que o enunciado pede | Onde está aqui |
|---|---|
| Mensageria assíncrona para eventos e integração desacoplada (l. 66) e para a orquestração da saga (l. 101) | RabbitMQ em [`k8s/base/rabbitmq/`](k8s/base/rabbitmq), com topologia, policies e um usuário por serviço ([ADR-036](docs/arquitetura/adr/fase4/036-mensageria-rabbitmq.md)); o contrato das mensagens em [`contratos/`](contratos) |
| Nenhum serviço acessa o banco de outro (l. 67) | Os serviços trocam só mensagens e chamadas REST pela borda; as permissões do broker limitam o que cada usuário publica e lê |
| Deploy automatizado em Kubernetes (l. 94 e 100) | `make kind-up deploy`, que o CD de cada serviço chama, e o mesmo alvo com o overlay `k3s` ([ADR-042](docs/arquitetura/adr/fase4/042-cicd-e-deploy-kubernetes.md)); o job `deploy-kind` do [CD](.github/workflows/cd.yml) implanta a plataforma no kind do runner, com o overlay `kind-ci`, em todo PR e push na `main` |
| Ferramentas de monitoramento e observabilidade da fase 3 (l. 102) | Prometheus, Grafana, Loki, Promtail e Jaeger em [`k8s/base/observabilidade/`](k8s/base/observabilidade); dashboards e alertas documentados em [`observabilidade/`](observabilidade/README.md) ([ADR-043](docs/arquitetura/adr/fase4/043-observabilidade-distribuida.md)) |
| `main` com PR obrigatório e checagens automáticas (l. 95) | Ruleset da `main` com os checks `manifests` e `contratos` do CI, que roda também o `gitleaks` |
| Diagrama geral, estratégia da saga e justificativa da divisão (l. 131 a 133) | [RFC-004](docs/arquitetura/rfc/fase4/rfc-004-microsservicos-saga.md) e ADRs em [`docs/arquitetura/`](docs/arquitetura) |

O gateway segue o [ADR-038](docs/arquitetura/adr/fase4/038-borda-e-comunicacao-sincrona.md). Cobertura dos testes deste repositório: 100% de linhas e ramos do código de teste (gate de 90%), que é só um indicador aqui; o que protege os contratos é a bateria de negativos gerados (seção [Contratos de mensageria](#contratos-de-mensageria)).

## Pré-requisitos

| Alvo do `make` | Precisa de |
|---|---|
| `kind-up`, `deploy`, `smoke`, `redrive`, `kong-check`, `status`, `port-forward` | Docker, [kind](https://kind.sigs.k8s.io/) 0.31.0, a versão que publicou o nó pinado e a que o CI instala (o 0.32.0 também sobe o cluster), kubectl de 1.34 a 1.36 (no máximo uma minor de distância do nó 1.35; traz o kustomize 5), jq, curl e openssl; portas 80 e 443 do loopback livres |
| `up`, `down` | Docker com Compose v2 |
| `lint`, `test` | [uv](https://docs.astral.sh/uv/), que instala o Python 3.14 do `.python-version`; Node 24 com npx (o `make test` roda o `@asyncapi/cli`) |
| `manifests` | Docker, kubectl e jq, com acesso a ghcr.io, Docker Hub, charts.konghq.com e raw.githubusercontent.com (imagens das ferramentas, chart do Kong e schemas do Kubernetes) |
| `kong-render` | Docker, com acesso a charts.konghq.com |

`make check` roda `lint`, `test` e `manifests`, como o CI.

## Conteúdo

| Caminho | O que é |
|---|---|
| [`kind/cluster.yaml`](kind/cluster.yaml) | Cluster kind `pytstop-p4` de um nó, com o Kubernetes fixo por digest e as portas 80/443 do host (só loopback) mapeadas para o Kong |
| [`k8s/base/`](k8s/base) | Kustomize da infraestrutura compartilhada no namespace `pytstop-plataforma` |
| [`k8s/overlays/kind`](k8s/overlays/kind), [`k8s/overlays/kind-ci`](k8s/overlays/kind-ci), [`k8s/overlays/k3s`](k8s/overlays/k3s) | StorageClass, exposição do Kong e recursos de cada ambiente; o kind leva também o metrics-server e os limites de rate limit ×10, e o `kind-ci` é o kind sem Loki, Promtail e Grafana, para o runner do CI |
| [`k8s/exemplos/`](k8s/exemplos) | Exemplos de borda do OS e do Billing (Ingress e Services do Kong), que o `make smoke` aplica no kind |
| [`observabilidade/`](observabilidade) | Datasources, alertas e dashboards do Grafana, usados pelo Kubernetes e pelo compose; [documentação painel a painel](observabilidade/README.md) |
| [`compose/`](compose) | Stack docker compose para desenvolver um serviço: RabbitMQ, observabilidade e Mailpit com a configuração do cluster, os bancos de cada serviço e um profile que sobe os três; sem o Kong |
| [`contratos/`](contratos) | AsyncAPI 3.0 dos comandos e eventos, JSON Schema do envelope e de cada mensagem, exemplos e testes |
| [`scripts/`](scripts) | Smoke do cluster, checagem do Kong, redrive da DLQ (fila de mensagens mortas, *dead letter queue*), render do Kong, segredos gerados no deploy, medição do kind e checagens do `make manifests` |
| [`tests/`](tests) | Teste de consistência da observabilidade (dashboards, alertas e documentação) e teste do script de segredos |
| [`Makefile`](Makefile) | Atalhos de cluster, deploy, compose e testes (`make` lista os alvos) |

## Subir a plataforma

### Kubernetes local (kind)

```bash
make kind-up        # cria o cluster pytstop-p4 (contexto kind-pytstop-p4)
make deploy         # segredos gerados, CRDs do Kong, overlay kind, rollouts, Job de usuários do RabbitMQ e kong-check
make smoke          # borda, barra codificada, rate limit, máscara de token, RabbitMQ, fallback do Kong, alertas e pods endurecidos; sai com status 1 se uma prova não valer
make status         # pods, serviços, volumes e filas do RabbitMQ
make port-forward   # Grafana :3000, Jaeger :16686, RabbitMQ :15672, Prometheus :9090, Mailpit :8025
make kind-down      # apaga o cluster
```

O cluster se chama `pytstop-p4` para não colidir com o `pytstop` que o `make cd-local` da fase 3 cria na mesma máquina. Todo `kubectl` do Makefile usa o contexto `kind-pytstop-p4` explicitamente; para olhar outro cluster, `make status KUBE_CONTEXT=<contexto>`.

O gateway responde em `http://localhost/`. Sem nenhum serviço publicado ele devolve 404 (`no Route matched`), o que já mostra o Kong no ar.

Senhas dos admins do Grafana e do RabbitMQ: o `make deploy` as gera no primeiro deploy do cluster ([Segredos gerados](#segredos-gerados)) e elas se leem do Secret (no compose, os valores de demonstração estão em [`compose/docker-compose.yml`](compose/docker-compose.yml)):

| Onde | Usuário | Senha |
|---|---|---|
| Grafana (`http://localhost:3000`, anônimo entra como Viewer) | `admin` | `kubectl -n pytstop-plataforma get secret grafana-admin -o jsonpath='{.data.GF_SECURITY_ADMIN_PASSWORD}' \| base64 -d` |
| RabbitMQ management (`http://localhost:15672`) | `admin` | `kubectl -n pytstop-plataforma get secret rabbitmq-credenciais -o jsonpath='{.data.admin-senha}' \| base64 -d` |

### Kind no CI (overlay `kind-ci`)

O job `deploy-kind` do [`cd.yml`](.github/workflows/cd.yml) roda em todo pull request para a `main`, a cada push na `main` e sob demanda, sem filtro de caminhos, para poder virar check obrigatório. No runner `ubuntu-24.04` (16 GB de memória), ele instala o kind 0.31.0 e o kubectl 1.35.9, com versão e sha256 fixados em [`instalar-ferramentas.sh`](scripts/ci/instalar-ferramentas.sh), e roda os mesmos alvos do kind local com `OVERLAY=kind-ci`: `make kind-up` e `make deploy` pelo [`deploy-kind.sh`](scripts/ci/deploy-kind.sh), o mesmo ponto de entrada do CD dos serviços, e `make smoke`. O kind é a versão que publicou o `kindest/node:v1.35.0` pinado em [`kind/cluster.yaml`](kind/cluster.yaml), e o kubectl, a mesma minor do nó; os que vêm no runner mudam com a imagem dele (hoje, kind 0.33 e kubectl 1.37, duas minors acima do nó).

O [`kind-ci`](k8s/overlays/kind-ci/kustomization.yaml) é o overlay `kind` sem Loki, Promtail e Grafana: o mesmo metrics-server, o Kong em NodePort, os limites de rate limit ×10 e uma réplica por Deployment, como no base. A plataforma fica com 1.088 Mi de requests e 3 Gi de limits de memória, mais os 200 Mi que o metrics-server reserva; o orçamento com os três serviços e os valores medidos estão no [ADR-042](docs/arquitetura/adr/fase4/042-cicd-e-deploy-kubernetes.md). Com `OVERLAY=kind-ci`, o `make smoke` pula, com aviso, as provas que dependem de Loki, Promtail e Grafana (token mascarado no Loki e regras de alerta carregadas) e roda as demais como no kind local; nos outros overlays, componente ausente ou quebrado continua reprovando.

O job mede a duração de cada etapa e a memória do nó do kind e escreve as duas no summary ([`medir-kind.sh`](scripts/medir-kind.sh)): o `memory.peak` do cgroup do nó, que conta também o cache de arquivos que o kernel devolve sob pressão, o maior working set amostrado a cada 5 s (a conta que o kubelet usa para despejar pod) e o maior uso de cada pod no `kubectl top`. Se uma etapa falha ou o job é cancelado, inclusive pelo `timeout-minutes`, o [`diagnostico.sh`](scripts/ci/diagnostico.sh) despeja os pods, os últimos eventos, os logs do Kong e do RabbitMQ e o `describe` e os logs, inclusive da execução anterior, dos pods que não ficaram prontos ou que reiniciaram; localmente, `scripts/ci/diagnostico.sh` faz o mesmo no contexto `KUBE_CONTEXT` (padrão `kind-pytstop-p4`).

Localmente, o mesmo fluxo:

```bash
make kind-up deploy smoke OVERLAY=kind-ci
```

Para medir como o job, cada etapa é marcada antes do alvo, e o resumo sai no fim:

```bash
scripts/medir-kind.sh etapa kind-up && make kind-up
scripts/medir-kind.sh etapa deploy && make deploy OVERLAY=kind-ci
scripts/medir-kind.sh etapa smoke && make smoke OVERLAY=kind-ci
scripts/medir-kind.sh resumo
```

### Segredos gerados

Nenhuma senha da plataforma fica nos manifests. O `make deploy` roda o [`gerar-segredos.sh`](scripts/gerar-segredos.sh) antes do apply, e ele gera com `openssl rand` (24 bytes, em hexadecimal) as senhas do admin do RabbitMQ, dos usuários `os`, `billing` e `execucao` e do admin do Grafana, e cria cada Secret só se ele ainda não existe:

| Secret | Namespace | Chaves |
|---|---|---|
| `rabbitmq-credenciais` | `pytstop-plataforma` | `admin-usuario`, `admin-senha`, `senha-os`, `senha-billing`, `senha-execucao` e o `admin.json` que o broker importa no boot |
| `grafana-admin` | `pytstop-plataforma` | `GF_SECURITY_ADMIN_PASSWORD` (no `kind-ci`, sem Grafana, fica sem uso) |
| `rabbitmq` | `pytstop-os`, `pytstop-billing` e `pytstop-execucao` | `RABBITMQ_URL` do usuário do serviço, com a senha do `rabbitmq-credenciais` ([contrato com os serviços](#usuário-e-permissões-no-rabbitmq)) |

Os Secrets nascem no primeiro deploy de cada cluster, e não a cada deploy: o RabbitMQ lê o `admin.json` só no boot, e uma senha nova com o broker de pé deixaria o Job `rabbitmq-usuarios` sem acesso à API (401) até o próximo restart. Nenhuma senha passa por argumento de processo, pela saída ou pelo repositório: os Secrets chegam ao `kubectl` pela entrada padrão, e no GitHub Actions cada senha é registrada com `::add-mask::` antes do uso, então o log do job a mostra como `***`. No kind do CI as senhas morrem com o runner. O [`test_gerar_segredos.py`](tests/test_gerar_segredos.py) roda o script contra um `kubectl` falso: cluster novo, Secrets que já existem, serviço novo com o broker de pé, erro ao ler o cluster e a máscara do GitHub Actions.

Troca de senha do RabbitMQ, executada no kind: a de um usuário de serviço vai para a chave `senha-<usuario>` do `rabbitmq-credenciais` (sem caractere que precise de escape na URL, como a do `openssl rand -hex 24`); depois de apagar o Secret `rabbitmq` do namespace do serviço, o `make deploy` o recria com a URL nova e o Job `rabbitmq-usuarios` aplica a senha no broker, e os pods do serviço precisam reiniciar para ler a variável. A do admin vai para `admin-senha` e para o `admin.json`, no mesmo formato (o `make smoke` lê a senha do arquivo montado no pod); o broker a aplica no boot (`kubectl -n pytstop-plataforma rollout restart statefulset/rabbitmq`), e o `make deploy` seguinte roda o Job com ela.

### k3s (VM na Azure)

O overlay `k3s` assume o k3s instalado com `--disable traefik`: o Service `kong-proxy` continua `LoadBalancer` e o ServiceLB do k3s publica as portas 80/443 da VM no Kong. O k3s já traz metrics-server. O mesmo alvo do kind aplica o overlay, espera os rollouts e confere o Kong:

```bash
make deploy OVERLAY=k3s KUBE_CONTEXT=<contexto do k3s>
```

A diferença para o kind está no próprio [`kustomization.yaml`](k8s/overlays/k3s/kustomization.yaml): StorageClass `local-path`, volume de 5Gi e mais memória reservada (request) para o RabbitMQ, e sete dias de retenção no Prometheus.

### docker compose

```bash
make up                    # infraestrutura
make up PROFILE=servicos   # infraestrutura + os três serviços, construídos dos repositórios irmãos
make down                  # derruba tudo; os volumes ficam (docker compose -f compose/docker-compose.yml down -v apaga)
```

O compose serve para desenvolver um serviço, não reproduz o cluster: RabbitMQ (mesmas definitions, policies e usuários), Loki (mesma configuração), Grafana (mesmo provisioning), Prometheus, Promtail, Jaeger e Mailpit, mais os bancos. Não tem o Kong, então não há `/os`, `/billing` e `/execucao`, nem `X-Request-ID` ou rate limit da borda (os serviços respondem direto nas portas abaixo, e os painéis 10 e 11 e o alerta de 5xx do gateway ficam sem dado). A regra `pytstop-kong-fora`, que trata ausência de dado como alerta, só é carregada no cluster ([`alertas-cluster.yaml`](observabilidade/grafana/alertas-cluster.yaml)): no compose ela ficaria disparada para sempre. Também não tem kube-state-metrics nem metrics-server: sem o alerta de CPU e sem HPA (*Horizontal Pod Autoscaler*, o autoescalonamento horizontal).

O serviço `rabbitmq-usuarios` roda o mesmo script do Job do Kubernetes e fica saudável quando os usuários estão criados; os serviços do profile só sobem depois disso. O profile `servicos` constrói `../postech-sw-arch-p4-os-service`, `../postech-sw-arch-p4-billing-service` e `../postech-sw-arch-p4-execution-service` (clones irmãos deste repositório) e sobe a API de cada um; relay, consumidor e `prazos` não estão no compose.

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

O Promtail lê os logs pela API do Docker e escolhe os containers pelo rótulo `pytstop.logs=true`, que todo serviço do compose tem, e não pelo nome do projeto: `-p` e `COMPOSE_PROJECT_NAME` funcionam. O socket do Docker vai montado com `:ro`, o que não limita a API (vale para o arquivo, não para as chamadas): o Promtail do compose tem acesso total ao Docker da máquina, aceitável só em desenvolvimento local.

Do host, o MongoDB do replica set responde em `mongodb://localhost:27017/billing?directConnection=true` (o membro do replica set se anuncia como `mongo-billing`, nome que só resolve dentro da rede do compose).

## Componentes e versões

Todas as imagens têm tag fixa, e a mesma versão roda no kind, no k3s e no compose: o `make manifests` reprova imagem com mais de uma tag entre `k8s/`, compose e Makefile, ou fora desta tabela.

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
| Kubernetes do kind | `kindest/node:v1.35.0` (por digest em [`kind/cluster.yaml`](kind/cluster.yaml)) | Nó do cluster local; o `make manifests` valida os manifests contra a mesma versão | - |
| PostgreSQL (só compose) | `postgres:16.15` | Banco do OS e da Execução no compose; no Kubernetes cada serviço traz o seu | `postgres-os:5432`, `postgres-execucao:5432` |
| MongoDB (só compose) | `mongo:7.0.43` | Banco do Billing no compose, em replica set de um nó | `mongo-billing:27017` |
| SonarQube (CI dos serviços) | `sonarqube:26.9.0.129388-community` | Servidor efêmero do job `sonarqube` de cada serviço, que aplica o quality gate ([ADR-041](docs/arquitetura/adr/fase4/041-estrategia-de-testes-e-qualidade.md)) | service container do job |
| SonarScanner (CI dos serviços) | `sonarsource/sonar-scanner-cli:12.2.0.4256_8.1.0` | Análise do código no mesmo job | - |

Prometheus, Grafana, Loki, Promtail, kube-state-metrics, Mailpit e Jaeger vieram dos manifests da fase 3, ajustados para vários serviços em vários namespaces e com probes de liveness e readiness em todos.

O Promtail está em fim de vida desde 02/03/2026. Ele continua aqui porque o enunciado pede a observabilidade da fase 3, que o usa. Saiu do 2.9 da fase 3 para a 3.6, a última linha, porque o cliente Docker do 2.9 fala uma versão de API que o Docker 29 do compose recusa. A saída é o Grafana Alloy, que lê os mesmos pods e empurra para o mesmo Loki.

## Como os serviços se conectam

### Usuário e permissões no RabbitMQ

Cada serviço tem um usuário próprio, criado pelo Job `rabbitmq-usuarios` ([`criar-usuarios.sh`](k8s/base/rabbitmq/criar-usuarios.sh)) com as senhas do Secret `rabbitmq-credenciais` e as permissões de [`permissoes.json`](k8s/base/rabbitmq/permissoes.json). Nenhum serviço tem permissão de configure: a topologia inteira vem do [`definitions.json`](k8s/base/rabbitmq/definitions.json), importado no boot do broker, e o serviço só confere o que precisa com declaração passiva. Assim nenhum comando volta como não roteável porque o consumidor do destino ainda não subiu.

Além do exchange, a permissão de tópico limita as routing keys que cada usuário publica. Sem ela, um serviço poderia publicar evento em nome de outro ou mandar uma cópia ao `pytstop.retry` com a routing key da fila de outro serviço e entregar mensagem lá.

Origem conferida ([ADR-036](docs/arquitetura/adr/fase4/036-mensageria-rabbitmq.md)): toda publicação leva na propriedade `user_id` do AMQP (*Advanced Message Queuing Protocol*) o usuário da conexão, e o broker recusa outro valor (`406 PRECONDITION_FAILED`), porque nenhum usuário de serviço tem a tag `impersonator`. O consumidor confere o `user_id` contra o produtor do tipo da mensagem, o `userId` da operação de envio no [`asyncapi.yaml`](contratos/asyncapi.yaml) (a routing key não serve, porque na cópia de retry ela é o nome da fila). A cópia de retry é republicada pelo próprio consumidor e leva o `user_id` dele, então com `x-tentativa` de 1 em diante ele aceita o próprio usuário; qualquer outro valor é erro permanente e vai para a DLQ. O snippet de [Filas, exchanges e argumentos](#filas-exchanges-e-argumentos) traz as duas regras.

| Usuário | Publica em | Routing keys permitidas | Lê de | Senha (chave do Secret) |
|---|---|---|---|---|
| `os` | `pytstop.comandos`, `pytstop.retry` | `comando.billing.*` e `comando.execucao.*`; no retry, só `os.eventos` | `os.eventos` | `senha-os` |
| `billing` | `pytstop.eventos`, `pytstop.retry` | `evento.billing.*`; no retry, só `billing.comandos` | `billing.comandos` | `senha-billing` |
| `execucao` | `pytstop.eventos`, `pytstop.retry` | `evento.execucao.*`; no retry, só `execucao.comandos` | `execucao.comandos` | `senha-execucao` |
| `admin` | tudo (operação e management) | tudo | tudo | `admin-senha` |

Secret não atravessa namespace: o `make deploy` cria no namespace de cada serviço o Secret `rabbitmq`, com a chave `RABBITMQ_URL` (`amqp://<usuario>:<senha>@rabbitmq.pytstop-plataforma.svc.cluster.local:5672/%2F`; o `%2F` é o vhost padrão `/` codificado, a forma da [especificação de URI AMQP do RabbitMQ](https://www.rabbitmq.com/docs/uri-spec), em que `amqp://host/` seria o vhost vazio) montada com a senha do usuário dele ([Segredos gerados](#segredos-gerados)). Esse é o contrato com os serviços: cada processo lê a `RABBITMQ_URL` do Secret, e senha do broker não vai para os manifests do serviço.

```yaml
env:
  - name: RABBITMQ_URL
    valueFrom:
      secretKeyRef:
        name: rabbitmq
        key: RABBITMQ_URL
```

### Endereços e variáveis

São as variáveis que o profile `servicos` do compose passa aos serviços; nos manifests Kubernetes de cada serviço os mesmos nomes recebem os endereços completos. `<svc>` é o nome do Service que o repositório do serviço define.

| Variável | Serviços | Kubernetes | compose |
|---|---|---|---|
| `RABBITMQ_URL` | todos | do Secret `rabbitmq` do namespace do serviço: `amqp://<usuario>:<senha>@rabbitmq.pytstop-plataforma.svc.cluster.local:5672/%2F` | `amqp://<usuario>:<senha>@rabbitmq:5672/%2F` |
| `OTEL_ENABLED`, `OTEL_SERVICE_NAME` | todos | `true`, nome do serviço (`os-service`, `billing-service`, `execution-service`) | iguais |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | todos | `http://jaeger.pytstop-plataforma.svc.cluster.local:4317` (gRPC) ou `:4318` (HTTP) | `http://jaeger:4317` |
| `SMTP_HOST` / `SMTP_PORT` | OS | `mailpit.pytstop-plataforma.svc.cluster.local` / `1025` | `mailpit` / `1025` |
| `DATABASE_URL` | OS e Execução | PostgreSQL do próprio serviço, no namespace dele | `postgresql://pytstop:pytstop@postgres-os:5432/os` e `...@postgres-execucao:5432/execucao` |
| `MONGODB_URL` | Billing | MongoDB do próprio serviço, no namespace dele | `mongodb://mongo-billing:27017/billing?replicaSet=rs0` |
| `RUN_MIGRATIONS_ON_STARTUP` | OS e Execução | `false` (migração em Job antes do rollout) | `true` |
| `JWKS_URL` | Billing e Execução | `http://<svc>.pytstop-os.svc.cluster.local:8000/.well-known/jwks.json` | `http://os-service:8000/.well-known/jwks.json` |
| `BILLING_URL` | Execução | `http://<svc>.pytstop-billing.svc.cluster.local:8000` | `http://billing-service:8000` |
| `MP_MODE` | Billing | `simulado` | `simulado` |

Métricas, o contrato do [ADR-043](docs/arquitetura/adr/fase4/043-observabilidade-distribuida.md): cada processo do serviço (`api`, `relay`, `consumidor`, `prazos`) roda no seu Deployment e serve `/metrics` numa porta declarada em `ports` do container, com o nome `metrics` (a API serve na própria porta HTTP). O Prometheus raspa sozinho, por pod, todo pod dos namespaces `pytstop-*` com as anotações abaixo no template; a porta anotada precisa estar em `ports`. O label `app` do pod vira o `job` nos painéis, e o label `processo` vai para a série como `processo`.

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

Antes de enviar ao Loki, o Promtail troca por `***` o token de `/publico/orcamentos/<token>`, de `/simulador/checkout/<token>` e de `token=<valor>`, em qualquer linha, com a barra também como `%2F` (o Kong loga o caminho como chegou, inclusive o do pedido que ele barra com 404): no access log do Kong e no log dos serviços ([RFC-004, seção 8](docs/arquitetura/rfc/fase4/rfc-004-microsservicos-saga.md#8-segurança)). O `make manifests` roda o pipeline real, o do cluster e o do compose, com `promtail -dry-run` sobre linhas de exemplo e reprova token sem máscara em qualquer um dos dois. O `kubectl logs` do pod continua com a linha original, por isso o serviço não deve logar o token.

### Gateway: como um serviço publica as rotas

O serviço cria os próprios Ingress, no próprio namespace, com `ingressClassName: kong`, a partir do exemplo do OS ([`borda-os-service.yaml`](k8s/exemplos/borda-os-service.yaml)) ou do Billing ([`borda-billing-service.yaml`](k8s/exemplos/borda-billing-service.yaml), com o webhook do Mercado Pago e o checkout do simulador); a Execução segue o molde do OS, sem JWKS nem rotas públicas. O `make smoke` aplica os dois exemplos no kind como estão. Pela borda só saem os caminhos que o [ADR-038](docs/arquitetura/adr/fase4/038-borda-e-comunicacao-sincrona.md) permite: `/api/v1/*`, `/docs` e `/openapi.json` de cada serviço, o JWKS (*JSON Web Key Set*, as chaves públicas do JWT) do OS e o checkout do simulador do Billing. `/metrics` e `/api/v1/admin/*` casam um Ingress anotado com o plugin `fora-da-borda`, que responde 404 sem chamar o serviço; como o Kong escolhe o caminho mais longo, esse Ingress vence o de `/api/v1`.

Com `strip-path`, o Kong tira do caminho tudo o que a regra casou e põe no lugar o `konghq.com/path` do Service de destino: `/os/api/v1/x` casa a regra `/os/api/v1` e chega ao serviço como `/api/v1` + `/x`. Por isso cada prefixo publicado tem um Service próprio, todos com os mesmos pods; o Service interno do serviço (o do `JWKS_URL` e do `BILLING_URL`) fica sem a anotação.

Barra codificada: o Kong casa as rotas por segmento e não trata `%2F` (nem `%5C`) como `/`, e o uvicorn dos serviços decodifica o `%2F` do caminho. Sem proteção, `/os/api/v1/admin%2Foutbox` passaria pelo Ingress de `/os/api/v1` em vez de cair no `fora-da-borda`, e `/os/api/v1/autenticacao%2Flogin` ficaria fora do limite de 5/min do login. O plugin global `bloqueia-barra-codificada` (um `pre-function` em [`plugins.yaml`](k8s/base/kong/plugins.yaml)) responde 404 a todo caminho com `%2F` ou `%5C`, em maiúsculas ou minúsculas, antes de qualquer rota e de qualquer rate limit; esse 404 não gasta balde. Só o caminho conta: `%2F` na query string passa. O resto o Kong já normaliza antes de casar a rota (barras repetidas, `.` e `..` e letra codificada como `%61`), e as demais grafias que passam, como `%252F`, `;x=1` e `ADMIN`, o FastAPI trata como outro caminho. O `make smoke` prova com sondas `%2F` ao admin, ao login, ao acompanhamento e ao link de decisão do Billing, mais três grafias do caminho do admin, e sai com status 1 se alguma não responder 404.

Os plugins são `KongClusterPlugin`, que o Ingress de qualquer namespace pode usar ([`plugins.yaml`](k8s/base/kong/plugins.yaml)). `correlation-id`, `prometheus`, `bloqueia-barra-codificada` e `rate-limiting-global` são globais e valem para toda rota sem anotação; os outros entram pela anotação `konghq.com/plugins`. O rate limiting conta por IP do cliente, com contador local no pod do Kong. O global usa um balde por IP para todas as rotas que não têm plugin de rate limiting próprio, e cada rota anotada conta num balde só dela.

| Serviço | Caminho na borda | Plugin | Limite por IP |
|---|---|---|---|
| OS | `POST /os/api/v1/autenticacao/login` | `rate-limiting-login` | 5/min |
| OS | `/os/api/v1/autenticacao/*` (refresh, logout e registrar) | `rate-limiting-sessao` | 10/min |
| OS | `/os/api/v1/publico/*` (acompanhamento) | `rate-limiting-publico` | 10/min |
| OS | `GET /os/.well-known/jwks.json` | `rate-limiting-jwks` | 60/min |
| Billing | `/billing/api/v1/publico/*` (link de decisão) | `rate-limiting-publico` | 10/min |
| Billing | `/billing/simulador/checkout/*` e `/billing/api/v1/simulador/*` | `rate-limiting-publico` | 10/min |
| Billing | `POST /billing/api/v1/webhooks/mercadopago` | `rate-limiting-webhook` | 120/min |
| todos | demais rotas de `/api/v1/*`, `/docs` e `/openapi.json` | `rate-limiting-global` (sem anotação) | 60/min |
| todos | `/metrics` e `/api/v1/admin/*` | `fora-da-borda` | sempre 404 |
| todos | qualquer caminho com `%2F` ou `%5C` | `bloqueia-barra-codificada` (global) | sempre 404 |

No overlay kind os limites são multiplicados por 10 ([`rate-limit-x10.yaml`](k8s/overlays/kind/rate-limit-x10.yaml)), para que o E2E e a demonstração não recebam 429.

IP do cliente: o `kong-proxy` usa `externalTrafficPolicy: Local`, que entrega o pacote sem o SNAT (*source NAT*) do kube-proxy. No kind, o tráfego entra pelo mapeamento de porta do Docker, e todo cliente do host chega com o IP do gateway da rede do Docker: um balde só por limite, o que basta para a demonstração. No k3s, o ServiceLB com `externalTrafficPolicy: Local` deve entregar o IP de origem, mas isso ainda não foi conferido com dois clientes: até lá, o limite por IP no k3s é esperado, não verificado. Se um balanceador ou proxy entrar na frente da VM, configure em [`values.yaml`](k8s/base/kong/values.yaml) `env.trusted_ips` com o CIDR exato dele e `env.real_ip_header: X-Forwarded-For` e rode `make kong-render`. Nunca use `0.0.0.0/0`: o cliente escolheria o próprio IP pelo header e escaparia do limite.

O `X-Request-ID` gerado pelo Kong é um UUID simples (`generator: uuid`), aceito como está pelo middleware de request id que os serviços herdaram da fase 3 (`[A-Za-z0-9._=-]{1,128}`); o formato `uuid#counter` seria descartado por ele. Se o cliente mandar um `X-Request-ID`, o Kong o mantém e o devolve na resposta. O FastAPI precisa de `root_path="/os"` fixo para o Swagger em `/os/docs` achar o `/os/openapi.json`; o header `X-Forwarded-Prefix` não serve, porque traz o trecho inteiro que a regra casou.

### Filas, exchanges e argumentos

Toda a topologia está em [`k8s/base/rabbitmq/definitions.json`](k8s/base/rabbitmq/definitions.json), importada pelo RabbitMQ no boot (kind, k3s e compose). Os serviços não declaram nada com efeito: só conferem com declaração passiva (`passive=True`). No RabbitMQ 4.3 a declaração passiva também exige permissão no recurso: cada usuário confere a própria fila (permissão de leitura) e os exchanges em que publica (escrita). Fila ou exchange de outro serviço, `.retry` e `.dlq` respondem `403 ACCESS_REFUSED` e fecham o canal, então o check de topologia do boot fica nesta lista:

| Usuário | Pode conferir com declaração passiva |
|---|---|
| `os` | fila `os.eventos`; exchanges `pytstop.comandos` e `pytstop.retry` |
| `billing` | fila `billing.comandos`; exchanges `pytstop.eventos` e `pytstop.retry` |
| `execucao` | fila `execucao.comandos`; exchanges `pytstop.eventos` e `pytstop.retry` |

As policies abaixo servem também para quem precisar recriar a topologia em outro broker. O desenho é o da [RFC-004, seção 5.1](docs/arquitetura/rfc/fase4/rfc-004-microsservicos-saga.md#51-topologia):

```mermaid
flowchart LR
    r_os["relay do OS"] -->|"comando.billing.*<br/>comando.execucao.*"| x_cmd{{"pytstop.comandos<br/>(topic)"}}
    r_ex["relay da Execução"] -->|"evento.execucao.*"| x_evt{{"pytstop.eventos<br/>(topic)"}}
    r_bi["relay do Billing"] -->|"evento.billing.*"| x_evt

    x_cmd -->|"bind comando.billing.#"| q_bi["billing.comandos"]
    x_cmd -->|"bind comando.execucao.#"| q_ex["execucao.comandos"]
    x_evt -->|"bind evento.billing.#<br/>e evento.execucao.#"| q_os["os.eventos"]

    q_bi --> c_bi["consumidor do Billing"]
    q_ex --> c_ex["consumidor da Execução"]
    q_os --> c_os["consumidor do OS"]

    c_bi -.->|"erro transitório: cópia com expiration<br/>em pytstop.retry, chave billing.comandos"| rt_bi["billing.comandos.retry"]
    c_ex -.->|"erro transitório: idem,<br/>chave execucao.comandos"| rt_ex["execucao.comandos.retry"]
    c_os -.->|"erro transitório: idem,<br/>chave os.eventos"| rt_os["os.eventos.retry"]
    rt_bi -.->|"TTL vence: dead-letter<br/>de volta à fila"| q_bi
    rt_ex -.->|"TTL vence"| q_ex
    rt_os -.->|"TTL vence"| q_os

    q_bi -.->|"reject: 5ª tentativa<br/>ou erro permanente"| dlx{{"pytstop.dlx<br/>(direct)"}}
    q_ex -.->|"reject"| dlx
    q_os -.->|"reject"| dlx
    dlx -.->|"billing.comandos"| dlq_bi["billing.comandos.dlq"]
    dlx -.->|"execucao.comandos"| dlq_ex["execucao.comandos.dlq"]
    dlx -.->|"os.eventos"| dlq_os["os.eventos.dlq"]
```

| Exchange | Tipo | Para que serve |
|---|---|---|
| `pytstop.comandos` | topic | Comandos do OS (`comando.<serviço de destino>.<ação>`) |
| `pytstop.eventos` | topic | Eventos de Billing e Execução (`evento.<serviço de origem>.<fato>`) |
| `pytstop.retry` | topic | Cópias para nova tentativa; a routing key é o nome da fila de trabalho. É topic, com bindings de chave exata, só para aceitar permissão de tópico; num direct qualquer serviço com escrita no exchange alcançaria a fila de outro |
| `pytstop.dlx` | direct | Dead-letter das filas de trabalho; a routing key é o nome da fila |

| Fila | Consumidor | Bindings | Policy |
|---|---|---|---|
| `billing.comandos` | Billing | `pytstop.comandos` com `comando.billing.#` | `trabalho-billing.comandos`: `dead-letter-exchange=pytstop.dlx`, `dead-letter-routing-key=billing.comandos`, `dead-letter-strategy=at-least-once`, `overflow=reject-publish`, `max-length=10000` |
| `execucao.comandos` | Execução | `pytstop.comandos` com `comando.execucao.#` | `trabalho-execucao.comandos`: as mesmas, com `dead-letter-routing-key=execucao.comandos` |
| `os.eventos` | OS | `pytstop.eventos` com `evento.billing.#` e `evento.execucao.#` | `trabalho-os.eventos`: as mesmas, com `dead-letter-routing-key=os.eventos` |
| `<fila>.retry` | ninguém | `pytstop.retry` com routing key `<fila>` | `retry-<fila>`: `dead-letter-exchange=""` (default exchange), `dead-letter-routing-key=<fila>`, `dead-letter-strategy=at-least-once`, `overflow=reject-publish`, `message-ttl=300000` |
| `<fila>.dlq` | ninguém (análise e `make redrive`) | `pytstop.dlx` com routing key `<fila>` | `dlq`: `message-ttl=604800000` (7 dias: as mensagens carregam dado pessoal, como a placa) |

Todas são quorum, duráveis, não exclusivas e sem auto-delete, e o tipo (`x-queue-type`) é o único argumento. O resto vem de policies, porque argumento de fila é imutável e a importação do boot ignora a mudança numa fila que já existe, enquanto as policies são regravadas a cada boot: mudar o `definitions.json` muda as filas no próximo restart do broker. Um broker criado com uma versão anterior deste arquivo, com os argumentos nas filas, precisa apagar as nove filas (ou o volume) uma vez.

Tetos: o `message-ttl` de 300 s da `.retry` vale para a cópia que chegar sem `expiration`, que assim não fica parada para sempre; a fila de trabalho cheia (10000 mensagens) recusa a publicação, que o relay do produtor retenta; e o broker recusa mensagem acima de 1 MiB (`max_message_size` no `rabbitmq.conf`).

No consumidor do Billing, com pika (o `user_id` de toda publicação é o usuário da conexão; o broker recusa outro valor com `406 PRECONDITION_FAILED`, porque nenhum usuário de serviço tem a tag `impersonator`):

```python
import os

import pika

USUARIO = "billing"  # o user_id das cópias de retry é o do próprio consumidor
ATRASOS_MS = ["1000", "5000", "15000", "60000", "300000"]


def origem_valida(propriedades: pika.BasicProperties, produtor: str) -> bool:
    """produtor: usuário que publica o tipo (o userId da operação no AsyncAPI)."""
    tentativa = (propriedades.headers or {}).get("x-tentativa", 0)
    return propriedades.user_id == produtor or (
        tentativa >= 1 and propriedades.user_id == USUARIO
    )


def nova_tentativa(canal, entrega, propriedades, corpo) -> None:
    tentativa = (propriedades.headers or {}).get("x-tentativa", 0) + 1
    if tentativa > len(ATRASOS_MS):
        canal.basic_reject(entrega.delivery_tag, requeue=False)  # vai para a DLQ
        return
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
            user_id=USUARIO,
            content_type="application/json",
            delivery_mode=2,
            expiration=ATRASOS_MS[tentativa - 1],
            headers={**(propriedades.headers or {}), "x-tentativa": tentativa},
        ),
        mandatory=True,
    )
    canal.basic_ack(entrega.delivery_tag)


conexao = pika.BlockingConnection(pika.URLParameters(os.environ["RABBITMQ_URL"]))
canal = conexao.channel()
canal.queue_declare("billing.comandos", passive=True)  # confere, não cria
canal.basic_qos(prefetch_count=10)  # por consumidor; a fila quorum não aceita global
canal.confirm_delivery()  # basic_publish espera o broker confirmar
```

Fluxo de uma mensagem que falha no consumidor:

1. Erro transitório: o consumidor publica uma cópia no `pytstop.retry` com a routing key igual ao nome da fila, o próprio `user_id`, `expiration` crescente por tentativa (1s, 5s, 15s, 60s, 300s) e o header `x-tentativa`, espera a confirmação do broker (publisher confirms, `mandatory`) e só então dá ack na original. O broker põe a cópia em `<fila>.retry`.
2. Quando o TTL (*time to live*) vence, a `.retry` devolve a mensagem para `<fila>` pelo default exchange, com o histórico no header `x-death`. Esse dead-letter é interno ao broker e não pede permissão do serviço.
3. Depois da 5ª tentativa, ou em erro permanente (validação, schema), o consumidor faz `basic_reject(requeue=False)` e a mensagem vai para `<fila>.dlq` pelo `pytstop.dlx`, onde fica até 7 dias. Corrigida a causa, `make redrive FILA=<fila>` a devolve para `<fila>` (abaixo).
4. Mensagem que derruba o consumidor sem ack (conexão ou canal fechados) volta para a fila; no RabbitMQ 4 a fila quorum manda para a DLQ depois de 20 reentregas (limite padrão de entregas). `basic_nack` ou `basic_reject` com `requeue=True` não conta para esse limite: a mensagem volta para a fila indefinidamente. Retry é sempre pelo `pytstop.retry`.

Por que filas quorum e não classic duráveis: a quorum grava em log Raft com fsync antes de confirmar, aceita TTL por mensagem e faz dead-lettering at-least-once (exige `overflow=reject-publish`). Assim a volta da `.retry` e a ida para a `.dlq` não perdem mensagem; na classic o dead-lettering é at-most-once.

Com um nó não há replicação, mas os clientes não mudam se o broker virar cluster. O custo é um pouco mais de memória e disco por fila, e o prefetch tem de ser por consumidor, porque a quorum não aceita prefetch global.

Redrive: `make redrive FILA=billing.comandos` (ou `execucao.comandos`, `os.eventos`) cria um shovel no próprio broker (plugin `rabbitmq_shovel`, ligado em [`enabled_plugins`](k8s/base/rabbitmq/enabled_plugins)) que move para a fila as mensagens que estavam na DLQ quando ele começou e se apaga ao terminar. O shovel só tira a mensagem da DLQ depois de a fila confirmar o recebimento, e preserva as propriedades (`user_id`, `message_id`, `x-tentativa`), então o consumidor a trata como a última tentativa. No compose, o mesmo comando do [`redrive.sh`](scripts/redrive.sh) roda com `docker compose -f compose/docker-compose.yml exec rabbitmq rabbitmqctl set_parameter shovel ...`.

Limite conhecido: TTL por mensagem só vence quando a mensagem chega à cabeça da fila. Numa `.retry` com uma mensagem de 300s na frente, uma de 1s espera os 300s. Com o volume da demonstração isso não aparece; se aparecer, a saída é uma fila de retry por atraso.

## Contratos de mensageria

| Arquivo | Conteúdo |
|---|---|
| [`contratos/asyncapi.yaml`](contratos/asyncapi.yaml) | AsyncAPI 3.0: um canal por routing key (exchange e chave), um por fila de trabalho, a operação de envio de cada mensagem e a de consumo de cada fila |
| [`contratos/schemas/envelope.schema.json`](contratos/schemas/envelope.schema.json) | JSON Schema 2020-12 do envelope comum |
| `contratos/schemas/<Mensagem>.schema.json` | JSON Schema 2020-12 do campo `dados` de cada uma das 34 mensagens |
| `contratos/exemplos/<Mensagem>.json` | Envelope completo de exemplo; juntos contam uma saga do pedido de diagnóstico até a compensação |
| [`contratos/tests/test_contratos.py`](contratos/tests/test_contratos.py) | Testes que amarram catálogo, AsyncAPI, schemas, exemplos e a topologia do RabbitMQ |

O catálogo e os campos de cada mensagem são os da [RFC-004, seção 5.3](docs/arquitetura/rfc/fase4/rfc-004-microsservicos-saga.md#53-catálogo-de-comandos-e-eventos), e o teste confere campo a campo cada schema contra uma cópia dessa tabela. `AnonimizarVeiculo` (LGPD, Lei Geral de Proteção de Dados: a Execução troca a placa guardada pelo marcador `ANONIMIZADO:{veiculo_id}`) é o único comando sem evento de resposta: se falhar de vez, o sinal é a mensagem na `execucao.comandos.dlq` e o alerta "DLQ com mensagens", e ela some da DLQ em 7 dias.

Envelope de toda mensagem:

```json
{"id": "<uuid>", "tipo": "GerarOrcamento", "versao": 1, "origem": "os-service",
 "correlation_id": "<ordem_id>", "causation_id": "<id da mensagem que causou ou null>",
 "ocorrido_em": "2026-10-06T12:45:00Z", "dados": {}}
```

Propriedades AMQP: `message_id` = `id`, `correlation_id`, `type` = `tipo`, `user_id` (o usuário do serviço que publica), `content_type=application/json`, `delivery_mode=2` e os headers `traceparent`/`tracestate` (W3C Trace Context), mais `x-tentativa` nas republicações. `correlation_id` é o id da OS (ordem de serviço, a instância da saga); fora da saga, o id do agregado tratado (`AnonimizarVeiculo`: `veiculo_id`). `causation_id` é o `id` da mensagem que causou esta (a resposta a um comando leva o `id` do comando) e só fica `null` quando a causa é uma requisição HTTP, um webhook ou um prazo.

Regras que os schemas impõem:

- Routing key `comando.<serviço de destino>.<ação>` ou `evento.<serviço de origem>.<fato>`, com o nome da mensagem em snake_case: `GerarOrcamento` vai em `comando.billing.gerar_orcamento`, `PecasReservadas` em `evento.execucao.pecas_reservadas`.
- Valor monetário em string decimal com duas casas e até 10 dígitos inteiros (`"820.00"`, no máximo `"9999999999.99"`) e `moeda: "BRL"`; número em ponto flutuante é rejeitado.
- Data e hora em RFC 3339 e em UTC (`Z` ou `+00:00`).
- Ids (`ordem_id`, `veiculo_id`, `orcamento_id`, `pagamento_id`, `reserva_id`, `mecanico_id`, `decidido_por`) são UUID; placa normalizada sem hífen (`ABC1234` ou `ABC1D23`).
- `codigo` de serviço e `sku` de peça: até 50 caracteres entre letras, dígitos, `.`, `_` e `-`, começando por letra ou dígito. `quantidade` de 1 a 1000, e cada lista com no máximo 50 itens.
- Diagnóstico concluído, pedido de orçamento e orçamento gerado têm ao menos um item; `ReservarPecas` e `ExecucaoFinalizada` aceitam lista vazia (orçamento só de serviços).
- `prioridade` do `AgendarExecucao`: `normal` (padrão) ou `alta`; a fila de execução atende `alta` antes e, dentro da mesma prioridade, por ordem de agendamento.
- `motivo` dos cinco comandos de compensação é um código da enumeração de `pytstop_saga_compensacoes_total` (`orcamento_recusado`, `orcamento_expirado`, `geracao_falhou`, `reserva_falhou`, `pagamento_recusado`, `pagamento_expirado`, `cancelamento`, `prazo_tecnico`); o texto que o atendente escreve fica só no histórico da OS. Texto livre (até 500 caracteres) só nos eventos de falha, e nunca vai para log.
- `CancelarOrcamento` e `EstornarPagamento` vão sem `orcamento_id` ou `pagamento_id` quando o passo estava em voo; o participante localiza o recurso pelo `ordem_id`. O estorno usa no provedor a chave de idempotência `estorno-{pagamento_id}`; o `id` da mensagem só deduplica a entrega.
- `PagamentoEstornado` diz o `motivo` (`compensacao` ou `pagamento_apos_encerramento`), e `PagamentoCancelado`, o `cancelado_em`.
- `OrcamentoAprovado` e `OrcamentoRecusado` com `canal=atendente` exigem `decidido_por` (o `sub` do atendente); com `canal=link`, ele não vai.
- `link_decisao` e `checkout_url` são `http` ou `https`, sem usuário na URL, e contêm o token do link: nunca vão para log nem para span.
- Mensagens sem nome, documento nem contato do cliente; a placa só aparece no `SolicitarDiagnostico`.
- Leitor tolerante: o schema aceita campo desconhecido, em qualquer nível, e o consumidor o ignora.

Mudança de contrato começa por um PR aqui. Campo novo opcional mantém a `versao`: atualiza o schema, o exemplo e a tabela da RFC copiada no teste, e o produtor pode enviá-lo antes de os consumidores o conhecerem. Mudança incompatível vira `versao: 2` do tipo, com o consumidor implantado antes do produtor. Cada serviço copia os schemas que produz e consome, e o `asyncapi.yaml`, que traz o usuário AMQP que publica cada tipo (`userId`, de onde o consumidor tira o produtor esperado); e os valida no próprio teste de contrato.

```bash
make test   # exemplos e negativos gerados contra os schemas, campos da RFC, AsyncAPI, routing key e topologia
make lint   # ruff, mypy strict e bandit
```

A cobertura de linha do `make test` mede só o arquivo de teste. O que protege os schemas é a bateria de negativos gerados de cada exemplo (campo removido, tipo errado, valor fora do domínio, texto gigante, lista vazia), que precisa ser toda rejeitada, mais os testes de fronteira: toda lista vai de 1 a 50 itens (vazia só onde a RFC deixa), cada limite de tamanho, quantidade, valor e formato tem o valor no limite aceito e o seguinte rejeitado, e a regra do `decidido_por` vale nos dois sentidos em `OrcamentoAprovado` e `OrcamentoRecusado`.

## CI

O workflow [`ci.yml`](.github/workflows/ci.yml) roda em pull request para a `main`, sob demanda e quando o CD o chama (`workflow_call`). `manifests` e `contratos` são checks obrigatórios do [ruleset da `main`](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-platform/rules/24599837); o checkout não guarda a credencial do GitHub (`persist-credentials: false`).

- `manifests`: `make manifests`, ou seja, os três overlays (`kind`, `kind-ci` e `k3s`) e os dois exemplos de borda validados pelo kubeconform (schemas do Kubernetes 1.35, a versão do nó do kind, e o do `KongClusterPlugin` gerado das CRDs do chart) e pelo `trivy config` (nenhum achado HIGH ou CRITICAL); `docker compose config` com o profile `servicos`; `promtool`, `loki -verify-config` e `promtail -check-syntax` nas configs do cluster e do compose, mais a máscara de token do Promtail (`promtail -dry-run`); o `k8s/base/kong` igual ao que o `make kong-render` gera; a mesma tag de cada imagem em `k8s/`, no compose e na tabela de versões; e todo dashboard JSON no configMapGenerator.
- `contratos`: `uv lock --check`, `make lint` (ruff, mypy strict e bandit) e `make test` (testes de contrato, de observabilidade e do `gerar-segredos.sh` e o `asyncapi.yaml` validado pelo `@asyncapi/cli`).
- `gitleaks`: o histórico inteiro do repositório com as regras do [`.gitleaks.toml`](.gitleaks.toml), pelo binário com versão e sha256 fixados, como nos repositórios de serviço.

`make check` roda `lint`, `test` e `manifests` localmente.

O workflow [`cd.yml`](.github/workflows/cd.yml) tem o job `deploy-kind` ([Kind no CI](#kind-no-ci-overlay-kind-ci)) e, no push na `main`, o job `ci`, que roda o `ci.yml` no commit que entrou; ali o `deploy-kind` só começa com o CI verde. Os jobs dos dois workflows rodam no runner fixo `ubuntu-24.04`: o `ubuntu-latest` passa para o Ubuntu 26.04 a partir de 19/10/2026, e a imagem do CI só muda com commit.

## Decisões e limites

- Kong por `helm template` do chart `kong/kong` 3.4.1 versionado em [`k8s/base/kong/kong.yaml`](k8s/base/kong/kong.yaml): o Kong Ingress Controller 3.x não publica mais os manifests all-in-one. `make kong-render` regenera a partir de [`values.yaml`](k8s/base/kong/values.yaml). O webhook de validação ficou desligado porque o chart gera o certificado dele na renderização, e versionar o resultado poria uma chave privada no repositório.
- Sem o webhook, Ingress ou plugin inválido de um serviço não falha no `kubectl apply`. Para que ele não derrube a configuração dos outros serviços (o Kong sem banco recusa a configuração inteira), o controller roda com o gate `FallbackConfiguration`: tira o objeto com erro e o que depende dele, aplica o resto e registra um evento no objeto. O `make deploy` termina com o `make kong-check`, que falha e lista o objeto recusado; o `make smoke` prova os dois lados com um plugin inválido de propósito.
- Senhas geradas no cluster pelo `make deploy`, no primeiro deploy de cada cluster ([Segredos gerados](#segredos-gerados), [ADR-042](docs/arquitetura/adr/fase4/042-cicd-e-deploy-kubernetes.md)). Os valores de demonstração ficam só no compose, marcados com `gitleaks:allow` e na allowlist do [`.gitleaks.toml`](.gitleaks.toml).
- Pods endurecidos: todos rodam sem root, sem escalar privilégio, sem capability, com seccomp `RuntimeDefault` e raiz somente leitura (`emptyDir` com `sizeLimit` onde a imagem grava). A exceção é o Promtail, que roda como root para ler os arquivos `0640` de `/var/log/pods` por `hostPath`, ainda sem capability. Só montam token de ServiceAccount os pods que falam com a API do Kubernetes: Prometheus, Promtail, kube-state-metrics e o controller do Kong. O namespace tem Pod Security `restricted` em `warn` e `audit`; o `make smoke` mostra o contexto efetivo de cada container e que, com `enforce`, só o Promtail ficaria de fora. O `make manifests` roda `trivy config` (HIGH e CRITICAL) nos três overlays e nos exemplos de borda.
- O controller do Kong lê Ingress, Services e Secrets só dos quatro namespaces da fase 4 (`watchNamespaces`), com uma Role em cada um, em vez de ler os Secrets do cluster inteiro. Por isso o `make deploy` cria vazios os namespaces dos serviços que ainda não existem; o repositório de cada serviço continua dono do namespace dele. Ingress de outro namespace não chega ao Kong. Risco que sobra, aceito: o controller roda no pod exposto à internet (`kong-proxy`) e a Role de cada um dos quatro namespaces ainda lhe dá `list` e `watch` em Secrets, inclusive os dos serviços (chave RSA do JWT, segredo do webhook, credenciais de banco e a URL do broker); quem tomasse o controle desse pod os leria. A plataforma não referencia Secret em Ingress nem em plugin, e uma saída a avaliar é tirar a regra de Secrets das Roles, se o controller subir sem ela (dívida no MEMORY).
- O admin do RabbitMQ entra no boot junto com a topologia (arquivo `admin.json` do Secret), porque com definitions no boot o broker não cria usuário nenhum e o Job de usuários precisa de alguém para falar com a API.
- `pytstop.retry` é topic, com bindings de chave exata ([ADR-036](docs/arquitetura/adr/fase4/036-mensageria-rabbitmq.md)): o RabbitMQ só aplica permissão por routing key em exchange topic, e sem ela a escrita no `pytstop.retry` deixaria qualquer serviço pôr mensagem na fila de trabalho de outro. Com a chave exata (o nome da fila), o roteamento é o mesmo de um direct.
- Versões de Prometheus, Grafana e Loki iguais às da fase 3. Jaeger na última 1.x: a 2.x troca a configuração pelo formato do OpenTelemetry Collector.
- CVEs conhecidas nas imagens (trivy, HIGH e CRITICAL com correção publicada, out/2026): Prometheus v2.54.1 (96 e 6), Loki 2.9.8 (53 e 3) e kube-state-metrics v2.13.0 (44 e 1) não têm versão de correção na própria linha (o Loki 2.9.17 tem mais achados, e o Prometheus 2.55.1 tira só quatro) e ficam como estão: rodam só dentro do cluster, sem Ingress, e o acesso de fora é por port-forward ou túnel. Sair delas é trocar de linha (Prometheus 3, Loki 3, kube-state-metrics 2.17), com mudança de configuração. O Mailpit subiu para v1.31.4, sem achado HIGH.
- Sem persistência em Prometheus, Loki e Grafana (o estado do Grafana vem todo do provisioning; o TSDB do Prometheus fica num emptyDir). Só o RabbitMQ tem volume. Cada emptyDir tem teto (`sizeLimit`) para não encher o disco do nó, que no k3s guarda também os volumes do broker e dos bancos: o Prometheus guarda 2 dias (7 no k3s) e no máximo 1 GB, e o Loki apaga os logs com mais de 7 dias (compactor com retenção).
