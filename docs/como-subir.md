# Como subir a plataforma

> [↑ Raiz do projeto](../README.md)

## Pré-requisitos

| Alvo do `make` | Precisa de |
|---|---|
| `kind-up`, `deploy`, `smoke`, `redrive`, `kong-check`, `status`, `port-forward` | Docker, [kind](https://kind.sigs.k8s.io/) 0.31.0, a versão que publicou o nó pinado e a que o CI instala (o 0.32.0 também sobe o cluster), kubectl de 1.34 a 1.36 (no máximo uma minor de distância do nó 1.35; traz o kustomize 5), jq, curl e openssl; portas 80 e 443 do loopback livres; o `smoke` também usa o uv (a prova do retry roda em Python) |
| `e2e`, `demo` | O cluster com a plataforma no overlay `kind-ci` e os três serviços implantados ([E2E da saga](e2e-da-saga.md#e2e-da-saga)), uv, kubectl e a porta 443 do loopback |
| `newman` | Os pré-requisitos do E2E acima, Node 24 e npx; usa `newman@6.2.3` e o simulador do Billing, sem credenciais do Mercado Pago |
| `paineis` | O cluster com a plataforma (o Prometheus) e, para os painéis de negócio terem série, os três serviços e o E2E ou o `make demo` já rodados; uv e kubectl |
| `mp-sandbox-ensaio`, `mp-sandbox` | O cluster com a plataforma no overlay `kind` (o padrão) e os três serviços implantados, uv, kubectl, Docker (a conferência prévia usa o `docker port`) e a porta 443 do loopback; o `mp-sandbox` também precisa do Access Token de teste e da assinatura do webhook no ambiente do shell ([Mercado Pago na sandbox](mercado-pago-na-sandbox.md#mercado-pago-na-sandbox)) |
| `up`, `down` | Docker com Compose v2 |
| `lint`, `test` | [uv](https://docs.astral.sh/uv/), que instala o Python 3.14 do `.python-version`; Node 24 com npx (o `make test` roda o `@asyncapi/cli`); Docker (o `make lint` roda o shellcheck e o actionlint pelas imagens pinadas, o `make lint-scripts`); kubectl (o teste de observabilidade renderiza os overlays com `kubectl kustomize`) e jq (o filtro do promtool tem teste próprio) |
| `prova-retry` | Docker e uv: o broker roda num container avulso, e a prova, em Python |
| `manifests` | Docker, kubectl e jq, com acesso a ghcr.io, Docker Hub, charts.konghq.com e raw.githubusercontent.com (imagens das ferramentas, chart do Kong e schemas do Kubernetes) |
| `kong-render` | Docker, com acesso a charts.konghq.com |

`make check` roda `lint`, `test`, `prova-retry` e `manifests`, como o CI.

## Kubernetes local (kind)

```bash
make kind-up
make deploy
make smoke
make status
make port-forward
make kind-down
```

| Alvo | O que faz |
|---|---|
| `make kind-up` | cria o cluster `pytstop-p4` (contexto `kind-pytstop-p4`) |
| `make deploy` | segredos gerados, CRDs do Kong, overlay kind, rollouts, Job de usuários do RabbitMQ e kong-check |
| `make smoke` | borda, barra codificada, rate limit, cabeçalhos do Kong (nenhum `Server`, `Via` ou `X-Kong-*`), máscara de token, RabbitMQ, fallback do Kong, dashboards e alertas carregados pelo Grafana (um dashboard por JSON de `observabilidade/dashboards`, uma regra por regra de `observabilidade/grafana`, e só as cinco de serviço fora, de fila sem consumidor e de banco fora disparando, porque ainda não há serviços) e pods endurecidos; sai com status 1 se uma prova não valer |
| `make status` | pods, serviços, volumes e filas do RabbitMQ |
| `make port-forward` | Grafana :3000, Jaeger :16686, RabbitMQ :15672, Prometheus :9090, Mailpit :8025 |
| `make kind-down` | apaga o cluster |

O `make smoke` pede um cluster só com a plataforma: ele recusa um namespace de serviço com Ingress. Para implantar os serviços no mesmo cluster, depois do `make deploy`, veja o [Contrato com os serviços](contrato-com-os-servicos.md#contrato-com-os-serviços) (o `make kind-deploy` de cada serviço); para voltar ao cluster só da plataforma, apague os namespaces `pytstop-os`, `pytstop-billing` e `pytstop-execucao`.

O cluster se chama `pytstop-p4` para não colidir com o `pytstop` que o `make cd-local` da fase 3 cria na mesma máquina. Todo `kubectl` do Makefile usa o contexto `kind-pytstop-p4` explicitamente; para olhar outro cluster, `make status KUBE_CONTEXT=<contexto>`.

O gateway responde em `http://localhost/`. Sem nenhum serviço publicado ele devolve 404 (`no Route matched`), o que já mostra o Kong no ar.

Senhas dos admins do Grafana e do RabbitMQ: o `make deploy` as gera no primeiro deploy do cluster ([Segredos gerados](segredos.md#segredos-gerados); um cluster criado antes das senhas geradas ainda tem as de demonstração e precisa ser recriado, como diz a [troca de senha](segredos.md#troca-de-senha-do-rabbitmq)) e elas se leem do Secret (no compose, os valores de demonstração estão em [`compose/docker-compose.yml`](../compose/docker-compose.yml)):

| Onde | Usuário | Senha |
|---|---|---|
| Grafana (`http://localhost:3000`, anônimo entra como Viewer) | `admin` | `kubectl -n pytstop-plataforma get secret grafana-admin -o jsonpath='{.data.GF_SECURITY_ADMIN_PASSWORD}' \| base64 -d` |
| RabbitMQ management (`http://localhost:15672`) | `admin` | `kubectl -n pytstop-plataforma get secret rabbitmq-credenciais -o jsonpath='{.data.admin-senha}' \| base64 -d` |

## Kind no CI (overlay `kind-ci`)

O job `deploy-kind` do [`cd.yml`](../.github/workflows/cd.yml) roda em todo pull request para a `main`, a cada push na `main` e sob demanda, sem filtro de caminhos, porque é check obrigatório do ruleset da `main` e tem de rodar em todo pull request. No runner `ubuntu-24.04` (16 GB de memória, o padrão do GitHub para repositório público, como os quatro da fase 4), ele instala o kind 0.31.0 e o kubectl 1.35.9, com versão e sha256 fixados em [`instalar-ferramentas.sh`](../scripts/ci/instalar-ferramentas.sh), e roda os mesmos alvos do kind local com `OVERLAY=kind-ci`: `make kind-up` e `make deploy` pelo [`deploy-kind.sh`](../scripts/ci/deploy-kind.sh), o mesmo ponto de entrada do CD do OS Service, o [`gerar-segredos.sh`](../scripts/gerar-segredos.sh) uma segunda vez, que tem de deixar cada Secret como estava ([Segredos gerados](segredos.md#segredos-gerados)), e `make smoke`. O kind é a versão que publicou o `kindest/node:v1.35.0` pinado em [`kind/cluster.yaml`](../kind/cluster.yaml), e o kubectl, a mesma minor do nó; os que vêm no runner mudam com a imagem dele (hoje, kind 0.33 e kubectl 1.37, duas minors acima do nó).

O [`kind-ci`](../k8s/overlays/kind-ci/kustomization.yaml) é o overlay `kind` sem Loki, Promtail e Grafana: o mesmo metrics-server, o Kong em NodePort, os limites de rate limit ×10 e uma réplica por Deployment, como no base. A plataforma fica com 1.088 Mi de requests e 3 Gi de limits de memória, mais os 200 Mi que o metrics-server reserva; o orçamento com os três serviços e os valores medidos estão no [ADR-042](arquitetura/adr/fase4/042-cicd-e-deploy-kubernetes.md). Com `OVERLAY=kind-ci`, o `make smoke` pula, com aviso, as provas que dependem de Loki, Promtail e Grafana (token mascarado no Loki e regras de alerta carregadas) e roda as demais como no kind local, e a linha final diz quantos grupos de provas pulou; nos outros overlays, componente ausente ou quebrado continua reprovando. Trocar de overlay no mesmo cluster exige recriá-lo (`make kind-down kind-up`): o apply não apaga o que saiu do overlay, e um cluster que passou do `kind` para o `kind-ci` mantém Loki, Promtail e Grafana de pé, com as provas deles puladas.

O job mede a duração de cada etapa e a memória do nó do kind e escreve as duas no summary ([`medir-kind.sh`](../scripts/medir-kind.sh)): o `memory.peak` do cgroup do nó, que conta também o cache de arquivos que o kernel devolve sob pressão, o maior working set amostrado a cada 5 s (a conta que o kubelet usa para despejar pod) e o maior uso de cada pod no `kubectl top`, sem os servidores de eco do `make smoke`. Se uma etapa falha ou o job é cancelado, inclusive pelo `timeout-minutes`, o [`diagnostico.sh`](../scripts/ci/diagnostico.sh) despeja os pods, os últimos eventos, os logs do Kong e do RabbitMQ e o `describe` e os logs, inclusive da execução anterior, dos pods que não ficaram prontos ou que reiniciaram; localmente, `scripts/ci/diagnostico.sh` faz o mesmo no contexto `KUBE_CONTEXT` (padrão `kind-pytstop-p4`).

Localmente, o mesmo fluxo:

```bash
make kind-up deploy smoke OVERLAY=kind-ci
```

Para medir como o job, cada etapa é marcada antes do alvo, e o resumo sai no fim. Os arquivos da medição ficam no `TMPDIR`; sem ele (comum no Linux), exporte antes `MEDICAO=$(mktemp -d)`. O amostrador para no resumo ou quando o shell que marcou a primeira etapa termina:

```bash
scripts/medir-kind.sh etapa kind-up && make kind-up
scripts/medir-kind.sh etapa deploy && make deploy OVERLAY=kind-ci
scripts/medir-kind.sh etapa smoke && make smoke OVERLAY=kind-ci
scripts/medir-kind.sh resumo
```

## Cluster persistente (overlay `k3s`)

O overlay `k3s` assume o k3s instalado com `--disable traefik`: o Service `kong-proxy` continua `LoadBalancer` e o ServiceLB do k3s publica as portas 80/443 da VM no Kong. O k3s já traz metrics-server. O mesmo alvo do kind aplica o overlay, espera os rollouts e confere o Kong:

```bash
make deploy OVERLAY=k3s KUBE_CONTEXT=k3s-pytstop
```

No lugar de `k3s-pytstop`, use o nome do contexto do k3s no seu kubeconfig (`kubectl config get-contexts` lista os nomes).

A diferença para o kind está no próprio [`kustomization.yaml`](../k8s/overlays/k3s/kustomization.yaml): StorageClass `local-path`, volume de 5Gi e mais memória reservada (request) para o RabbitMQ, e limite de memória de 1Gi no Prometheus, que aqui fica de pé por dias. O Prometheus retém 15 dias num PVC de 2Gi nos dois overlays ([Retenção e prazos](../observabilidade/README.md#retenção-e-prazos)).

Nenhum k3s faz parte do estado entregue da fase 4, que implanta só no kind. O que o dono de um cluster persistente teria de fazer (as receitas do k3s numa VM da Azure e do EKS no AWS Academy, e como ligar o deploy remoto do CD, que vem desligado) está em [Nuvem opcional](operacao/nuvem-opcional.md).

## docker compose

```bash
make up
make up PROFILE=servicos
make down
```

`make up` sobe a infraestrutura; com `PROFILE=servicos`, sobe também os três serviços, construídos dos repositórios irmãos. `make down` derruba tudo e deixa os volumes (`docker compose -f compose/docker-compose.yml down -v` os apaga).

O compose serve para desenvolver um serviço, não reproduz o cluster: RabbitMQ (mesmas definitions, policies e usuários), Loki (mesma configuração), Grafana (mesmo provisioning), Prometheus, Promtail, Jaeger e Mailpit, mais os bancos. Não tem o Kong, então não há `/os`, `/billing` e `/execucao`, nem `X-Request-ID` ou rate limit da borda (os serviços respondem direto nas portas abaixo, e os painéis 10 e 11 e o alerta de 5xx do gateway ficam sem dado). A regra `pytstop-kong-fora`, que trata ausência de dado como alerta, só é carregada no cluster ([`alertas-cluster.yaml`](../observabilidade/grafana/alertas-cluster.yaml)): no compose ela ficaria disparada para sempre. Também não tem kube-state-metrics nem metrics-server: sem o alerta de CPU e sem HPA (*Horizontal Pod Autoscaler*, o autoescalonamento horizontal).

O serviço `rabbitmq-usuarios` roda o mesmo script do Job do Kubernetes e fica saudável quando os usuários estão criados; os serviços do profile só sobem depois disso. O profile `servicos` constrói `../postech-sw-arch-p4-os-service`, `../postech-sw-arch-p4-billing-service` e `../postech-sw-arch-p4-execution-service` (clones irmãos deste repositório) e sobe a API de cada um; relay, consumidor, `prazos` e `notificador` não estão no compose.

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
