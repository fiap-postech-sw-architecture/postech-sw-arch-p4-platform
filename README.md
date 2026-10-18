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

O único commit da `main` fora de pull request é o `Initial commit` que o GitHub cria com o repositório. Desde então tudo entra por PR com squash, e o [ruleset da `main`](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-platform/rules/24599837) exige os checks `manifests`, `contratos` e `gitleaks` do [CI](.github/workflows/ci.yml) e `deploy-kind` do [CD](.github/workflows/cd.yml) ([ADR-042](docs/arquitetura/adr/fase4/042-cicd-e-deploy-kubernetes.md)).

## Papel deste repositório

É complementar aos três serviços. O enunciado pede no mínimo três microsserviços, cada um com repositório, infraestrutura e banco próprios ([desafio, l. 27](docs/requisitos/fase4/desafio-tech-fase-4.md)), e eles são os três repositórios acima. Aqui fica o que eles compartilham e que não pertence a nenhum: o broker, o gateway, a observabilidade e o contrato das mensagens. Não é um quarto microsserviço: não tem código de domínio nem banco.

| O que o enunciado pede | Onde está aqui |
|---|---|
| Mensageria assíncrona para eventos e integração desacoplada (l. 66) e para a orquestração da saga (l. 101) | RabbitMQ em [`k8s/base/rabbitmq/`](k8s/base/rabbitmq), com topologia, policies e um usuário por serviço ([ADR-036](docs/arquitetura/adr/fase4/036-mensageria-rabbitmq.md)); o contrato das mensagens em [`contratos/`](contratos) |
| Nenhum serviço acessa o banco de outro (l. 67) | Os serviços trocam só mensagens e chamadas REST pela borda; as permissões do broker limitam o que cada usuário publica e lê |
| Deploy automatizado em Kubernetes (l. 94 e 100) | `make kind-up deploy` com o overlay `kind-ci`, que o CD do OS Service chama pelo [`deploy-kind.sh`](scripts/ci/deploy-kind.sh) (`make -C platform kind-up deploy OVERLAY=kind-ci`, [ADR-042](docs/arquitetura/adr/fase4/042-cicd-e-deploy-kubernetes.md); em 18/10/2026 só ele tem `cd.yml` na `main`, e o Billing e a Execução têm `ci.yml` e `security.yml`); o job `deploy-kind` do [CD](.github/workflows/cd.yml) implanta a plataforma no kind do runner, com o overlay `kind-ci`, em todo PR e push na `main`; os serviços entram em seguida pelo [`implantar-servicos.sh`](scripts/ci/implantar-servicos.sh) (no CD do OS Service, ou pelo `make kind-deploy` que cada serviço traz), conferidos pelo [`smoke-servicos.sh`](scripts/ci/smoke-servicos.sh) ([Contrato com os serviços](#contrato-com-os-serviços)); o deploy num cluster persistente vem desligado ([Nuvem opcional](docs/operacao/nuvem-opcional.md)) |
| Ferramentas de monitoramento e observabilidade da fase 3 (l. 102) | Prometheus, Grafana, Loki, Promtail e Jaeger em [`k8s/base/observabilidade/`](k8s/base/observabilidade); quatro dashboards de negócio (com o volume diário de OS e o tempo médio por status, que a banca da fase 3 pediu) documentados painel a painel em [`observabilidade/negocio.md`](observabilidade/negocio.md), e os técnicos (Saga, Mensageria, Serviços, Bancos e a plataforma), os alertas e o catálogo de métricas em [`observabilidade/README.md`](observabilidade/README.md) ([ADR-043](docs/arquitetura/adr/fase4/043-observabilidade-distribuida.md)) |
| `main` com PR obrigatório e checagens automáticas (l. 95) | Ruleset da `main` com os checks `manifests`, `contratos` e `gitleaks` do CI e `deploy-kind` do CD |
| Pelo menos um fluxo completo testado com BDD (l. 82) | `make e2e`: a feature em português com a saga inteira e cada compensação, contra os três serviços no kind ([E2E da saga](#e2e-da-saga), [ADR-041](docs/arquitetura/adr/fase4/041-estrategia-de-testes-e-qualidade.md)) |
| Integração com o Mercado Pago nos pagamentos (l. 47) | O simulador do Billing no CI, no `make e2e` e no `make demo`; a evidência na sandbox do Mercado Pago, com credenciais de teste, em `make mp-sandbox` (e `make mp-sandbox-ensaio`, sem credencial) ([Mercado Pago na sandbox](#mercado-pago-na-sandbox), [ADR-040](docs/arquitetura/adr/fase4/040-integracao-mercado-pago.md)) |
| Vídeo: fluxo completo de uma OS e saga com falhas (l. 119 e 120) | `make demo`: as demonstrações 1 e 2, com o status da OS depois de cada `Então` ([E2E da saga](#e2e-da-saga)) |
| Diagrama geral, estratégia da saga e justificativa da divisão (l. 131 a 133) | [RFC-004](docs/arquitetura/rfc/fase4/rfc-004-microsservicos-saga.md) e ADRs em [`docs/arquitetura/`](docs/arquitetura) |

O gateway segue o [ADR-038](docs/arquitetura/adr/fase4/038-borda-e-comunicacao-sincrona.md). Cobertura dos testes deste repositório: acima de 99% de linhas e ramos do código de teste (gate de 90%), que é só um indicador aqui; o que protege os contratos é a bateria de negativos gerados (seção [Contratos de mensageria](#contratos-de-mensageria)).

## Pré-requisitos

| Alvo do `make` | Precisa de |
|---|---|
| `kind-up`, `deploy`, `smoke`, `redrive`, `kong-check`, `status`, `port-forward` | Docker, [kind](https://kind.sigs.k8s.io/) 0.31.0, a versão que publicou o nó pinado e a que o CI instala (o 0.32.0 também sobe o cluster), kubectl de 1.34 a 1.36 (no máximo uma minor de distância do nó 1.35; traz o kustomize 5), jq, curl e openssl; portas 80 e 443 do loopback livres; o `smoke` também usa o uv (a prova do retry roda em Python) |
| `e2e`, `demo` | O cluster com a plataforma no overlay `kind-ci` e os três serviços implantados ([E2E da saga](#e2e-da-saga)), uv, kubectl e a porta 443 do loopback |
| `paineis` | O cluster com a plataforma (o Prometheus) e, para os painéis de negócio terem série, os três serviços e o E2E ou o `make demo` já rodados; uv e kubectl |
| `mp-sandbox-ensaio`, `mp-sandbox` | O cluster com a plataforma no overlay `kind` (o padrão) e os três serviços implantados, uv, kubectl, Docker (a conferência prévia usa o `docker port`) e a porta 443 do loopback; o `mp-sandbox` também precisa do Access Token de teste e da assinatura do webhook no ambiente do shell ([Mercado Pago na sandbox](#mercado-pago-na-sandbox)) |
| `up`, `down` | Docker com Compose v2 |
| `lint`, `test` | [uv](https://docs.astral.sh/uv/), que instala o Python 3.14 do `.python-version`; Node 24 com npx (o `make test` roda o `@asyncapi/cli`); Docker (o `make lint` roda o shellcheck e o actionlint pelas imagens pinadas, o `make lint-scripts`); kubectl (o teste de observabilidade renderiza os overlays com `kubectl kustomize`) e jq (o filtro do promtool tem teste próprio) |
| `prova-retry` | Docker e uv: o broker roda num container avulso, e a prova, em Python |
| `manifests` | Docker, kubectl e jq, com acesso a ghcr.io, Docker Hub, charts.konghq.com e raw.githubusercontent.com (imagens das ferramentas, chart do Kong e schemas do Kubernetes) |
| `kong-render` | Docker, com acesso a charts.konghq.com |

`make check` roda `lint`, `test`, `prova-retry` e `manifests`, como o CI.

## Conteúdo

| Caminho | O que é |
|---|---|
| [`kind/cluster.yaml`](kind/cluster.yaml) | Cluster kind `pytstop-p4` de um nó, com o Kubernetes fixo por digest e as portas 80/443 do host (só loopback) mapeadas para o Kong |
| [`k8s/base/`](k8s/base) | Kustomize da infraestrutura compartilhada no namespace `pytstop-plataforma` |
| [`k8s/overlays/kind`](k8s/overlays/kind), [`k8s/overlays/kind-ci`](k8s/overlays/kind-ci), [`k8s/overlays/k3s`](k8s/overlays/k3s) | StorageClass, exposição do Kong e recursos de cada ambiente; o kind leva também o metrics-server e os limites de rate limit ×10, e o `kind-ci` é o kind sem Loki, Promtail e Grafana e com o Prometheus efêmero, para o runner do CI |
| [`k8s/componentes/`](k8s/componentes) | Componente do kustomize que o kind e o k3s usam: o Prometheus com 15 dias num PVC |
| [`k8s/exemplos/`](k8s/exemplos) | Exemplos de borda do OS, do Billing e da Execução (Ingress e Services do Kong), que o `make smoke` aplica no kind |
| [`observabilidade/`](observabilidade) | Datasources, alertas e dashboards do Grafana, usados pelo Kubernetes e pelo compose; documentação painel a painel dos [dashboards de negócio](observabilidade/negocio.md) e dos [técnicos, alertas e catálogo de métricas](observabilidade/README.md) |
| [`compose/`](compose) | Stack docker compose para desenvolver um serviço: RabbitMQ, observabilidade e Mailpit com a configuração do cluster, os bancos de cada serviço e um profile que sobe os três; sem o Kong |
| [`contratos/`](contratos) | AsyncAPI 3.0 dos comandos e eventos, JSON Schema do envelope e de cada mensagem, exemplos e testes |
| [`scripts/`](scripts) | Smoke do cluster (com a prova do retry no broker, [`prova_retry.py`](scripts/prova_retry.py), que o [`prova-retry-avulso.sh`](scripts/prova-retry-avulso.sh) roda também num RabbitMQ avulso, e a espera do broker que o smoke reinicia no fim, [`esperar-pod.sh`](scripts/esperar-pod.sh)), checagem do Kong, redrive da DLQ (fila de mensagens mortas, *dead letter queue*), render do Kong, segredos gerados no deploy, medição do kind, checagens do `make manifests` e, em [`scripts/ci/`](scripts/ci), os scripts do CD: deploy da plataforma, implantação e smoke dos serviços, diagnóstico e o deploy remoto, desligado ([Contrato com os serviços](#contrato-com-os-serviços), [Nuvem opcional](docs/operacao/nuvem-opcional.md)) |
| [`docs/`](docs) | [Arquitetura da fase 4](docs/arquitetura/README.md) (RFC-004 e ADRs 034 a 043), [requisitos e gap analysis](docs/requisitos/README.md), o [runbook da saga](docs/operacao/runbook-saga.md) (saga parada, falha na compensação, retomada e redrive da DLQ), o [ensaio integrado](docs/operacao/ensaio-integrado.md) (os três serviços no kind, com tempo, memória e CPU por pod) e a [nuvem opcional](docs/operacao/nuvem-opcional.md) (o deploy remoto desligado e as receitas de EKS e k3s, fora do estado entregue) |
| [`e2e/`](e2e) | O E2E BDD da saga (`make e2e`, que confere também que cada painel de negócio tem série), as demonstrações 1 e 2 do vídeo (`make demo`) e a evidência do Mercado Pago na sandbox (`make mp-sandbox` e `make mp-sandbox-ensaio`): as features em português, os steps, as fixtures e o código auxiliar com testes próprios ([E2E da saga](#e2e-da-saga), [Mercado Pago na sandbox](#mercado-pago-na-sandbox)) |
| [`tests/`](tests) | Teste de consistência da observabilidade (dashboards, alertas e documentação, e os filtros por fila contra a topologia do RabbitMQ) e testes dos scripts de segredos, de medição do kind e de implantação e smoke dos serviços, do código auxiliar do E2E (em [`tests/e2e_apoio/`](tests/e2e_apoio)) e dos links, das âncoras, das cercas de código e dos blocos de comando de todos os `.md` versionados ([`test_documentacao.py`](tests/test_documentacao.py)) |
| [`Makefile`](Makefile) | Atalhos de cluster, deploy, compose e testes (`make` lista os alvos) |

## Subir a plataforma

### Kubernetes local (kind)

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
| `make smoke` | borda, barra codificada, rate limit, máscara de token, RabbitMQ, fallback do Kong, dashboards e alertas carregados pelo Grafana (um dashboard por JSON de `observabilidade/dashboards`, uma regra por regra de `observabilidade/grafana`, e só as cinco de serviço fora, de fila sem consumidor e de banco fora disparando, porque ainda não há serviços) e pods endurecidos; sai com status 1 se uma prova não valer |
| `make status` | pods, serviços, volumes e filas do RabbitMQ |
| `make port-forward` | Grafana :3000, Jaeger :16686, RabbitMQ :15672, Prometheus :9090, Mailpit :8025 |
| `make kind-down` | apaga o cluster |

O `make smoke` pede um cluster só com a plataforma: ele recusa um namespace de serviço com Ingress. Para implantar os serviços no mesmo cluster, depois do `make deploy`, veja o [Contrato com os serviços](#contrato-com-os-serviços) (o `make kind-deploy` de cada serviço); para voltar ao cluster só da plataforma, apague os namespaces `pytstop-os`, `pytstop-billing` e `pytstop-execucao`.

O cluster se chama `pytstop-p4` para não colidir com o `pytstop` que o `make cd-local` da fase 3 cria na mesma máquina. Todo `kubectl` do Makefile usa o contexto `kind-pytstop-p4` explicitamente; para olhar outro cluster, `make status KUBE_CONTEXT=<contexto>`.

O gateway responde em `http://localhost/`. Sem nenhum serviço publicado ele devolve 404 (`no Route matched`), o que já mostra o Kong no ar.

Senhas dos admins do Grafana e do RabbitMQ: o `make deploy` as gera no primeiro deploy do cluster ([Segredos gerados](#segredos-gerados); um cluster criado antes das senhas geradas ainda tem as de demonstração e precisa ser recriado, como diz a [troca de senha](#troca-de-senha-do-rabbitmq)) e elas se leem do Secret (no compose, os valores de demonstração estão em [`compose/docker-compose.yml`](compose/docker-compose.yml)):

| Onde | Usuário | Senha |
|---|---|---|
| Grafana (`http://localhost:3000`, anônimo entra como Viewer) | `admin` | `kubectl -n pytstop-plataforma get secret grafana-admin -o jsonpath='{.data.GF_SECURITY_ADMIN_PASSWORD}' \| base64 -d` |
| RabbitMQ management (`http://localhost:15672`) | `admin` | `kubectl -n pytstop-plataforma get secret rabbitmq-credenciais -o jsonpath='{.data.admin-senha}' \| base64 -d` |

### Kind no CI (overlay `kind-ci`)

O job `deploy-kind` do [`cd.yml`](.github/workflows/cd.yml) roda em todo pull request para a `main`, a cada push na `main` e sob demanda, sem filtro de caminhos, porque é check obrigatório do ruleset da `main` e tem de rodar em todo pull request. No runner `ubuntu-24.04` (16 GB de memória, o padrão do GitHub para repositório público, como os quatro da fase 4), ele instala o kind 0.31.0 e o kubectl 1.35.9, com versão e sha256 fixados em [`instalar-ferramentas.sh`](scripts/ci/instalar-ferramentas.sh), e roda os mesmos alvos do kind local com `OVERLAY=kind-ci`: `make kind-up` e `make deploy` pelo [`deploy-kind.sh`](scripts/ci/deploy-kind.sh), o mesmo ponto de entrada do CD dos serviços, o [`gerar-segredos.sh`](scripts/gerar-segredos.sh) uma segunda vez, que tem de deixar cada Secret como estava ([Segredos gerados](#segredos-gerados)), e `make smoke`. O kind é a versão que publicou o `kindest/node:v1.35.0` pinado em [`kind/cluster.yaml`](kind/cluster.yaml), e o kubectl, a mesma minor do nó; os que vêm no runner mudam com a imagem dele (hoje, kind 0.33 e kubectl 1.37, duas minors acima do nó).

O [`kind-ci`](k8s/overlays/kind-ci/kustomization.yaml) é o overlay `kind` sem Loki, Promtail e Grafana: o mesmo metrics-server, o Kong em NodePort, os limites de rate limit ×10 e uma réplica por Deployment, como no base. A plataforma fica com 1.088 Mi de requests e 3 Gi de limits de memória, mais os 200 Mi que o metrics-server reserva; o orçamento com os três serviços e os valores medidos estão no [ADR-042](docs/arquitetura/adr/fase4/042-cicd-e-deploy-kubernetes.md). Com `OVERLAY=kind-ci`, o `make smoke` pula, com aviso, as provas que dependem de Loki, Promtail e Grafana (token mascarado no Loki e regras de alerta carregadas) e roda as demais como no kind local, e a linha final diz quantos grupos de provas pulou; nos outros overlays, componente ausente ou quebrado continua reprovando. Trocar de overlay no mesmo cluster exige recriá-lo (`make kind-down kind-up`): o apply não apaga o que saiu do overlay, e um cluster que passou do `kind` para o `kind-ci` mantém Loki, Promtail e Grafana de pé, com as provas deles puladas.

O job mede a duração de cada etapa e a memória do nó do kind e escreve as duas no summary ([`medir-kind.sh`](scripts/medir-kind.sh)): o `memory.peak` do cgroup do nó, que conta também o cache de arquivos que o kernel devolve sob pressão, o maior working set amostrado a cada 5 s (a conta que o kubelet usa para despejar pod) e o maior uso de cada pod no `kubectl top`, sem os servidores de eco do `make smoke`. Se uma etapa falha ou o job é cancelado, inclusive pelo `timeout-minutes`, o [`diagnostico.sh`](scripts/ci/diagnostico.sh) despeja os pods, os últimos eventos, os logs do Kong e do RabbitMQ e o `describe` e os logs, inclusive da execução anterior, dos pods que não ficaram prontos ou que reiniciaram; localmente, `scripts/ci/diagnostico.sh` faz o mesmo no contexto `KUBE_CONTEXT` (padrão `kind-pytstop-p4`).

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

### Segredos gerados

Nenhuma senha ou chave fica nos manifests. O `make deploy` roda o [`gerar-segredos.sh`](scripts/gerar-segredos.sh) antes do apply, e ele cuida de dois tipos de Secret: a fonte, criada só se ainda não existe, ou seja, no primeiro deploy de cada cluster, e o derivado, regravado em todo deploy a partir da fonte. Os Secrets dos serviços nascem no namespace de cada um, que o `make deploy` cria vazio se ainda não existe, e o serviço não os declara nos manifests dele: só os lê, por `secretKeyRef`. Os comandos de troca usam o contexto do kind; no k3s, troque o `--context`.

| Secret | Namespace | Chaves (formato) | Quem lê | Quando o script grava | Como girar |
|---|---|---|---|---|---|
| `rabbitmq-credenciais` (fonte) | `pytstop-plataforma` | `admin-usuario` (`admin`), `admin-senha`, `senha-os`, `senha-billing` e `senha-execucao` (48 hexadecimais cada) e o `admin.json` que o broker importa no boot | RabbitMQ e Job `rabbitmq-usuarios` | Só se ainda não existe | [Troca de senha do RabbitMQ](#troca-de-senha-do-rabbitmq) |
| `grafana-admin` (fonte) | `pytstop-plataforma` | `GF_SECURITY_ADMIN_PASSWORD` (48 hexadecimais) | Grafana (no `kind-ci`, sem Grafana, fica sem uso) | Só se ainda não existe | Apagar o Secret, `make deploy` e `rollout restart deployment/grafana` no `pytstop-plataforma`: sem volume, o Grafana cria o admin com a senha do Secret a cada start |
| `rabbitmq` (derivado) | `pytstop-os`, `pytstop-billing` e `pytstop-execucao` | `RABBITMQ_URL` do usuário do serviço, com a senha do `rabbitmq-credenciais` ([contrato com os serviços](#usuário-e-permissões-no-rabbitmq)) | relay, consumidor e `prazos` | Em todo deploy, com a senha que está na fonte | Segue a fonte: a senha trocada no `rabbitmq-credenciais` chega aqui no `make deploy` seguinte |
| `os-postgres` (fonte) | `pytstop-os` | Uma senha por papel, 48 hexadecimais cada: `POSTGRES_PASSWORD` (superusuário `postgres`), `POSTGRES_OWNER_PASSWORD` (`os`, dono das tabelas: DDL, *data definition language*, criar e alterar tabelas), `POSTGRES_APP_PASSWORD` (`os_app`: só DML, *data manipulation language*: SELECT, INSERT, UPDATE e DELETE, nas tabelas do dono) e `POSTGRES_EXPORTER_PASSWORD` (`os_exporter`: `pg_monitor`) | PostgreSQL, que cria os papéis na primeira inicialização do volume (script de init nos manifests do serviço); `os`: Job de migração; `os_app`: API, relay, consumidor, `prazos` e `notificador`; `os_exporter`: exporter | Só se ainda não existe | Com janela, pelos passos de [Troca de senha do banco](#troca-de-senha-do-banco): a senha nova no Secret, o `ALTER ROLE` do papel, como `postgres`, sem a senha em argumento nem no log do servidor, e o restart de quem usa o papel: `os_app`, os Deployments do serviço; `os_exporter`, o StatefulSet do banco, porque o exporter é sidecar dele e o banco reinicia junto; `os`, o Job, que a relê no deploy seguinte do serviço; `postgres`, o StatefulSet do banco, que lê a senha dele só no start (sem o restart, a próxima troca não autentica). Até o restart, conexão nova com a senha antiga é recusada |
| `execucao-postgres` (fonte) | `pytstop-execucao` | Uma senha por papel, 48 hexadecimais cada: `POSTGRES_PASSWORD` (superusuário `postgres`), `POSTGRES_OWNER_PASSWORD` (`execucao`, dono das tabelas: DDL), `POSTGRES_APP_PASSWORD` (`execucao_app`: só DML nas tabelas do dono) e `POSTGRES_EXPORTER_PASSWORD` (`execucao_exporter`: `pg_monitor`) | PostgreSQL, que cria os papéis na primeira inicialização do volume (script de init nos manifests do serviço); `execucao`: Job de migração; `execucao_app`: API, relay e consumidor; `execucao_exporter`: exporter | Só se ainda não existe | Como a do `os-postgres`, com o namespace `pytstop-execucao`, o StatefulSet `execucao-postgres` e os papéis `execucao`, `execucao_app` e `execucao_exporter` |
| `os-jwt` (fonte) | `pytstop-os` | `JWT_PRIVATE_KEY` (RSA de 2048 bits em PEM PKCS#8) e `JWT_PREVIOUS_PUBLIC_KEY` (vazia; durante a rotação, recebe a chave pública que entra, na etapa 1, ou a que sai, na etapa 2, só publicada no JWKS) | API do OS Service | Só se ainda não existe | Sem derrubar sessão, pelas etapas da [rotação da chave](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-os-service#rotação-da-chave) do OS Service ([ADR-039](docs/arquitetura/adr/fase4/039-autenticacao-entre-servicos.md)): as chaves de cada etapa no Secret e o `rollout restart` da API do OS. Apagar o Secret, rodar o `make deploy` e reiniciar a API é a troca de emergência, que derruba as sessões |
| `os-cripto` (fonte) | `pytstop-os` | `ENCRYPTION_KEY` (chave Fernet: 32 bytes em base64 url-safe, 44 caracteres) | API e relay do OS Service | Só se ainda não existe; nunca é regenerada | Não gira sem migração: a chave nova exige recifrar os dados pessoais e recalcular o hash do documento ([ADR-042](docs/arquitetura/adr/fase4/042-cicd-e-deploy-kubernetes.md)) |
| `os-admin` (fonte) | `pytstop-os` | `ADMIN_PASSWORD` (48 hexadecimais), a senha do admin | Job de migração do OS Service (semente) e E2E | Só se ainda não existe | Não gira pelo Secret: a semente só cria o admin que ainda não existe, e o OS Service não tem troca de senha; o Secret guarda a senha da primeira semente |
| `billing-mongo` (fonte) | `pytstop-billing` | `MONGO_INITDB_ROOT_PASSWORD` (root), `MONGO_BILLING_PASSWORD` (`billing`) e `MONGO_EXPORTER_PASSWORD` (`exporter`), 48 hexadecimais cada, e `MONGO_KEYFILE` (756 bytes em base64, 1.008 caracteres numa linha) | mongod (o root, no primeiro boot, e o keyfile), Job de inicialização, processos do serviço e exporter | Só se ainda não existe | Senhas, com janela, pelos passos de [Troca de senha do banco](#troca-de-senha-do-banco): a senha nova no Secret, o `changeUserPassword` no banco do usuário (`billing` no banco `billing`, o `exporter` e o root em `admin`), como root, sem a senha em argumento, e o restart de quem usa o usuário: `billing`, os Deployments do Billing; `exporter`, o StatefulSet do banco; o root, o Job, que a relê no deploy seguinte do serviço, e o StatefulSet do banco, para a variável `MONGO_INITDB_ROOT_PASSWORD` do contêiner voltar a ser a do Secret (a troca seguinte autentica o root pela senha do Secret, e não pela variável). Keyfile, com o banco fora durante o restart: o valor novo no Secret e `rollout restart statefulset/billing-mongo`; o replica set tem um membro só, e nenhum outro precisa da chave antiga |
| `billing-link` (fonte) | `pytstop-billing` | `ORCAMENTO_LINK_SECRET` (64 hexadecimais), a chave HMAC do link de decisão e do checkout do simulador | API e consumidor do Billing | Só se ainda não existe | Apagar o Secret, `make deploy` e o `rollout restart` dos Deployments do Billing, a API e o consumidor juntos: os links e checkouts já enviados deixam de valer (o orçamento que aguarda decisão fica sem link até vencer, e o atendente ainda decide por ele), e até o fim do restart um link pode abrir numa réplica e dar 404 em outra |

Os valores saem do `openssl`: as senhas são 24 bytes do `openssl rand` em hexadecimal (48 caracteres, que entram em URL, JSON e YAML sem escape), e a chave RSA vem do `openssl genpkey`. O restart que cada troca pede é o `rollout restart` do Deployment ou do StatefulSet no namespace do serviço (`kubectl --context kind-pytstop-p4 -n pytstop-billing rollout restart deployment` reinicia todos os Deployments do Billing), porque o pod lê o Secret só no start.

As fontes ficam como estão nos deploys seguintes porque o valor de cada uma já está gravado em outro lugar: no broker, que lê o `admin.json` só no boot (uma senha de admin nova com o broker de pé deixaria o Job `rabbitmq-usuarios` sem acesso à API, 401, até o próximo restart); no volume do banco, onde o PostgreSQL e o MongoDB aplicam as senhas do Secret só na primeira inicialização; nos tokens emitidos, que uma chave RSA nova invalidaria; e nos dados cifrados, que uma `ENCRYPTION_KEY` nova deixaria ilegíveis. Antes de gerar qualquer valor, o script confere todas as fontes e para sem gravar nada em dois casos. Uma fonte que existe sem uma das chaves da tabela, editada à mão ou criada antes de a chave entrar no contrato, volta a valer com a chave acrescentada à mão, no formato da tabela (uma senha nova de papel do PostgreSQL pede também o `CREATE ROLE` no banco; num cluster de demonstração, recriar o cluster é mais curto). E, se uma fonte que guarda estado no banco do serviço (`os-postgres`, `execucao-postgres`, `os-cripto`, `os-admin` ou `billing-mongo`) some com o volume do banco de pé, o caminho é devolver o Secret ou, num cluster de demonstração, apagar o namespace do serviço, que leva o banco junto, e implantar de novo a plataforma e o serviço (apagar só o volume não basta: o Kubernetes não o apaga enquanto o pod do banco o usa, e o StatefulSet cria outro, vazio); erro ao listar os volumes também para o script.

O derivado é regravado em todo deploy, com a mesma senha que o Job aplica no broker, e assim uma senha trocada na fonte chega ao serviço no deploy seguinte. Antes de gravá-lo, o script confere que a senha da fonte tem só letras e dígitos, porque ela entra crua na URL, e para com erro, sem mostrar a senha, se não tiver. Os bancos não têm derivado: a URL de conexão se monta no pod, por expansão de variável (`$(POSTGRES_APP_PASSWORD)` dentro da `DATABASE_URL` dos processos), e o `kubectl describe` do pod mostra o molde, não a senha.

No PostgreSQL, os papéis separados só mantêm o superusuário fora do alcance de um sidecar comprometido se o banco pedir senha também na loopback. O exporter é sidecar do pod do banco e chega a ele por ela, e a imagem oficial do `postgres` deixa o socket, o `127.0.0.1` e o `::1` em `trust`: num contêiner avulso do `postgres:16.15`, `psql -h 127.0.0.1 -U postgres` entra como superusuário sem senha. Por isso o StatefulSet do banco de cada serviço define `POSTGRES_INITDB_ARGS="--auth-host=scram-sha-256 --auth-local=scram-sha-256"`, requisito do contrato com os serviços. Com ele, a loopback e o socket pedem senha (a do exporter não abre o `postgres`) e o entrypoint da imagem ainda roda o script de init dos papéis. Como as senhas, ele vale só na primeira inicialização do volume: num volume que nasceu sem ele, o `pg_hba.conf` continua em `trust`.

O admin é o único usuário semeado no OS Service: o Job de migração o cria com o `ADMIN_EMAIL` do ConfigMap do serviço e a senha do `os-admin`, e atendente e mecânico são cadastrados pela API, com o token do admin. O `billing-mercadopago` (`MP_ACCESS_TOKEN` e `MP_WEBHOOK_SECRET`) não sai do script de segredos: são as credenciais do Mercado Pago. Nunca vão para o GitHub ([ADR-042](docs/arquitetura/adr/fase4/042-cicd-e-deploy-kubernetes.md)): no kind local são as credenciais de teste, que ficam só no ambiente do shell de quem roda a prova, e num cluster remoto o dono do ambiente cria o Secret no cluster ([Nuvem opcional](docs/operacao/nuvem-opcional.md#o-que-o-gancho-não-faz)). O `make mp-sandbox` cria o Secret pelo stdin (nunca em argumento nem em arquivo), liga o modo real e o desfaz no fim ([Mercado Pago na sandbox](#mercado-pago-na-sandbox)). Sem ele, o Billing usa o simulador, que assina o checkout com a mesma `ORCAMENTO_LINK_SECRET`, num domínio próprio: o token do link não abre o checkout, e o do checkout não abre o link.

Nenhuma senha ou chave passa por argumento de processo, por variável exportada, pela saída ou pelo repositório: os Secrets chegam ao `kubectl` pela entrada padrão, o script desliga o trace do bash, e no GitHub Actions cada valor, gerado ou lido da fonte, é registrado com `::add-mask::` antes do uso, então o log do job o mostra como `***`. A chave PEM é registrada uma linha por vez, porque o comando vale até o fim da linha: com ela inteira, o resto da chave sairia em claro no log. O derivado é gravado por apply server-side, que não guarda o Secret inteiro, com a senha em claro, na anotação `last-applied-configuration`. No kind do CI os valores morrem com o runner, e o job `deploy-kind` roda o script uma segunda vez e confere que nenhum Secret mudou. O [`test_gerar_segredos.py`](tests/test_gerar_segredos.py) roda o script contra um `kubectl` falso e confere, entre outros casos, as linhas das fontes dos serviços desta tabela contra o que ele cria: nome, namespace, chaves, formato e quando o script grava.

#### Troca de senha do RabbitMQ

A senha nova tem só letras e dígitos, porque entra crua na URL; a do `openssl rand -hex 24` serve. Os comandos usam o contexto do kind (no k3s, troque o `--context`), e a senha vai do shell ao `jq` por variável de ambiente, não por argumento.

Usuário de serviço (`os`, `billing` ou `execucao`; o exemplo troca a do `billing`):

1. Grave a senha nova na chave `senha-billing` do `rabbitmq-credenciais`:

   ```bash
   senha=$(openssl rand -hex 24)
   kubectl --context kind-pytstop-p4 -n pytstop-plataforma get secret rabbitmq-credenciais -o json \
     | SENHA="$senha" jq '.data["senha-billing"] = (env.SENHA | @base64)' \
     | kubectl --context kind-pytstop-p4 replace -f -
   ```

2. `make deploy`: o Job `rabbitmq-usuarios` aplica a senha no broker, e o `gerar-segredos.sh` regrava com ela a `RABBITMQ_URL` do Secret `rabbitmq` do `pytstop-billing`.
3. Reinicie os Deployments do serviço, que leem a variável só no start: `kubectl --context kind-pytstop-p4 -n pytstop-billing rollout restart deployment`.

Admin:

1. Grave a senha nova em `admin-senha` e dentro do `admin.json`, que mantém o formato `"password": "<senha>"` (o `make smoke` lê a senha do arquivo montado no pod por esse padrão):

   ```bash
   senha=$(openssl rand -hex 24)
   kubectl --context kind-pytstop-p4 -n pytstop-plataforma get secret rabbitmq-credenciais -o json \
     | SENHA="$senha" jq '.data["admin-senha"] = (env.SENHA | @base64)
         | .data["admin.json"] = (.data["admin.json"] | @base64d
             | sub("\"password\": \"[^\"]*\""; "\"password\": \"\(env.SENHA)\"") | @base64)' \
     | kubectl --context kind-pytstop-p4 replace -f -
   ```

2. Reinicie o broker, que aplica o `admin.json` só no boot, e espere: `kubectl --context kind-pytstop-p4 -n pytstop-plataforma rollout restart statefulset/rabbitmq` e, em seguida, `rollout status statefulset/rabbitmq`.
3. `make deploy`: o Job `rabbitmq-usuarios` volta a falar com a API, agora com a senha nova.

Um cluster criado antes das senhas geradas ainda tem as de demonstração, que têm hífen: o `make deploy` para na conferência da senha, e `make kind-down kind-up deploy` recria o cluster com senhas geradas.

#### Troca de senha do banco

A senha nova vai do shell ao pod pela entrada padrão do `kubectl exec -i`, e o `psql` ou o `mongosh` a lê da variável de ambiente `SENHA_NOVA`, nunca de um argumento: o argumento de um `kubectl exec` fica no `ps` da máquina e na URL do pedido ao apiserver, que o log de auditoria, quando ligado, registra, e o de um `psql -c "ALTER ROLE … PASSWORD '<senha>'"` ainda vai para o log do servidor se o comando falhar. O `printf` do bash e do zsh é interno ao shell, então a senha também não aparece no `ps`. Os comandos usam o contexto do kind (no k3s, troque o `--context`) e supõem os nomes que os manifests dos serviços devem ter: o StatefulSet `os-postgres` com o contêiner `postgres`, e o `billing-mongo` com o `mongo`.

PostgreSQL (o exemplo troca a do `os_app`; para outro papel, troque a chave do Secret e o nome do papel). Grave a senha nova no Secret antes de aplicá-la no banco, para que o valor não fique só numa variável do shell:

```bash
senha=$(openssl rand -hex 24)
kubectl --context kind-pytstop-p4 -n pytstop-os get secret os-postgres -o json \
  | SENHA="$senha" jq '.data["POSTGRES_APP_PASSWORD"] = (env.SENHA | @base64)' \
  | kubectl --context kind-pytstop-p4 replace -f -
```

Aplique no banco, como `postgres`: o contêiner do banco já tem a senha dele em `POSTGRES_PASSWORD`, e o `-w` impede o `psql` de pedir senha de conexão, que sem terminal ele leria do próprio script. A saída esperada é cinco `SET` e um `ALTER ROLE`:

```bash
{ printf '%s\n' "$senha"; cat <<'SQL'
SET log_statement = 'none';
SET log_min_error_statement = 'panic';
SET log_min_duration_statement = -1;
SET log_min_duration_sample = -1;
SET log_transaction_sample_rate = 0;
\getenv senha SENHA_NOVA
ALTER ROLE os_app PASSWORD :'senha';
SQL
} | kubectl --context kind-pytstop-p4 -n pytstop-os exec -i statefulset/os-postgres -c postgres -- \
    sh -c 'read -r SENHA_NOVA && [ -n "$SENHA_NOVA" ] && export SENHA_NOVA && PGPASSWORD=$POSTGRES_PASSWORD exec psql -w -U postgres -v ON_ERROR_STOP=1'
```

O `psql` troca `:'senha'` pelo valor antes de enviar o comando (o `psql -c` do 16 não faz essa troca), então o servidor recebe a senha em claro. Os cinco `SET`, que valem só para a sessão, a tiram do log do servidor: sem eles, um `log_statement` em `all` ou `ddl` registra o comando, um comando que falha registra a linha `STATEMENT` com a senha, e `log_min_duration_statement`, `log_min_duration_sample` ou `log_transaction_sample_rate` ligados registram o texto do comando pela duração ou por amostragem. A regra é desligar todo parâmetro que grava o texto do comando. Por fim, reinicie quem usa o papel, como diz a coluna "Como girar" da tabela; para o `os_app`, `kubectl --context kind-pytstop-p4 -n pytstop-os rollout restart deployment`.

MongoDB. O `replica-set.js` do Billing cria o `billing` no banco `billing` (`authSource=billing`), e o `exporter` e o root ficam em `admin`: a troca vai no banco do usuário, e no banco errado o `mongosh` responde `User billing@admin not found`. Os três seguem os mesmos passos, e a tabela diz o que muda; o exemplo é o do `billing`:

| Credencial | Chave do Secret `billing-mongo` | Usuário | Banco | O que reiniciar depois |
|---|---|---|---|---|
| `billing` | `MONGO_BILLING_PASSWORD` | `billing` | `billing` | os Deployments do Billing |
| `exporter` | `MONGO_EXPORTER_PASSWORD` | `exporter` | `admin` | o StatefulSet do banco, porque o exporter é sidecar dele |
| root | `MONGO_INITDB_ROOT_PASSWORD` | `root` | `admin` | o StatefulSet do banco; o Job relê a senha no deploy seguinte |

Leia primeiro a senha do root que o banco tem agora, a do Secret, e só então gere a senha nova e grave-a. O root autentica com a senha do Secret, e não com a variável do contêiner, que só acompanha o Secret no restart: se o restart de uma troca anterior do root foi pulado, a variável guarda uma senha que o banco já não aceita.

```bash
chave=MONGO_BILLING_PASSWORD usuario=billing banco=billing
senha_root=$(kubectl --context kind-pytstop-p4 -n pytstop-billing get secret billing-mongo -o json \
  | jq -r '.data.MONGO_INITDB_ROOT_PASSWORD | @base64d')
senha=$(openssl rand -hex 24)
kubectl --context kind-pytstop-p4 -n pytstop-billing get secret billing-mongo -o json \
  | VALOR="$senha" jq --arg chave "$chave" '.data[$chave] = (env.VALOR | @base64)' \
  | kubectl --context kind-pytstop-p4 replace -f -
```

Aplique no banco, como root. As duas senhas vão nas duas primeiras linhas da entrada, e o `sh` do contêiner as lê para `SENHA_NOVA` e `SENHA_ROOT`:

```bash
{ printf '%s\n%s\n' "$senha" "$senha_root"; cat <<JS
db.getSiblingDB("admin").auth(process.env.MONGO_INITDB_ROOT_USERNAME, process.env.SENHA_ROOT)
db.getSiblingDB("$banco").changeUserPassword("$usuario", process.env.SENHA_NOVA)
print("senha de $usuario trocada")
JS
} | kubectl --context kind-pytstop-p4 -n pytstop-billing exec -i statefulset/billing-mongo -c mongo -- \
    sh -c 'read -r SENHA_NOVA && read -r SENHA_ROOT && [ -n "$SENHA_NOVA" ] && [ -n "$SENHA_ROOT" ] && export SENHA_NOVA SENHA_ROOT && exec mongosh --quiet --norc --file /dev/stdin'
```

O `mongosh` lê o script como arquivo (`--file /dev/stdin`) e não da entrada interativa, que sai com 0 mesmo quando a autenticação falha. Deu certo quando o comando sai com 0 e imprime `senha de billing trocada`; se a autenticação ou a troca falhar, ele imprime o erro do MongoDB (`MongoServerError: Authentication failed.` ou `User billing@admin not found`) e sai com código diferente de zero. Se o passo falhar, repita-o com a mesma senha: o Secret já tem a nova, e reiniciar os pods com o Secret diferente do banco os deixa sem acesso. Se a sessão do shell acabou entre o Secret e o banco, leia a senha nova do Secret em vez de gerar outra (`senha=$(kubectl --context kind-pytstop-p4 -n pytstop-billing get secret billing-mongo -o json | jq -r --arg chave "$chave" '.data[$chave] | @base64d')`). Na troca do root, `$senha_root` é a única cópia da senha anterior depois de gravar o Secret, então não feche a sessão antes de o passo dar certo; se já a perdeu, a variável `MONGO_INITDB_ROOT_PASSWORD` do contêiner do banco ainda guarda a anterior, enquanto o banco não reiniciou. Quando der certo, limpe as senhas do shell com `unset senha senha_root`. O restart de quem usa o usuário vem da coluna da tabela e da coluna "Como girar" dos segredos. O [README do Billing](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-billing-service#troca-de-senhas-e-chaves) traz o procedimento de cada credencial do serviço.

### Cluster persistente (overlay `k3s`)

O overlay `k3s` assume o k3s instalado com `--disable traefik`: o Service `kong-proxy` continua `LoadBalancer` e o ServiceLB do k3s publica as portas 80/443 da VM no Kong. O k3s já traz metrics-server. O mesmo alvo do kind aplica o overlay, espera os rollouts e confere o Kong:

```bash
make deploy OVERLAY=k3s KUBE_CONTEXT=k3s-pytstop
```

No lugar de `k3s-pytstop`, use o nome do contexto do k3s no seu kubeconfig (`kubectl config get-contexts` lista os nomes).

A diferença para o kind está no próprio [`kustomization.yaml`](k8s/overlays/k3s/kustomization.yaml): StorageClass `local-path`, volume de 5Gi e mais memória reservada (request) para o RabbitMQ, e limite de memória de 1Gi no Prometheus, que aqui fica de pé por dias. O Prometheus retém 15 dias num PVC de 2Gi nos dois overlays ([Retenção e prazos](observabilidade/README.md#retenção-e-prazos)).

Nenhum k3s faz parte do estado entregue da fase 4, que implanta só no kind. O que o dono de um cluster persistente teria de fazer (as receitas do k3s numa VM da Azure e do EKS no AWS Academy, e como ligar o deploy remoto do CD, que vem desligado) está em [Nuvem opcional](docs/operacao/nuvem-opcional.md).

### docker compose

```bash
make up
make up PROFILE=servicos
make down
```

`make up` sobe a infraestrutura; com `PROFILE=servicos`, sobe também os três serviços, construídos dos repositórios irmãos. `make down` derruba tudo e deixa os volumes (`docker compose -f compose/docker-compose.yml down -v` os apaga).

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

Todas as imagens têm tag fixa, e a mesma versão roda no kind, no k3s e no compose: o `make manifests` reprova imagem com mais de uma tag entre `k8s/`, compose e Makefile, ou fora desta tabela. Nos manifests dos serviços, o `implantar-servicos.sh` reprova imagem de terceiro fora desta tabela ([Contrato com os serviços](#contrato-com-os-serviços)).

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
| PostgreSQL | `postgres:16.15` | Banco do OS e da Execução: no Kubernetes, o StatefulSet que cada serviço traz no próprio namespace; no compose, um container por serviço | `os-postgres.pytstop-os.svc.cluster.local:5432` e `execucao-postgres.pytstop-execucao.svc.cluster.local:5432`; no compose, `postgres-os:5432` e `postgres-execucao:5432` |
| MongoDB | `mongo:7.0.43` | Banco do Billing, em replica set de um nó (`rs0`): StatefulSet no namespace do Billing e um container no compose | `billing-mongo-0.billing-mongo.pytstop-billing.svc.cluster.local:27017`; no compose, `mongo-billing:27017` |
| postgres_exporter | `prometheuscommunity/postgres-exporter:v0.20.1` | Métricas do PostgreSQL (conexões, transações, locks, tamanho), sidecar do banco do OS e da Execução, porta 9187, que conecta com o papel `os_exporter` ou `execucao_exporter` (`pg_monitor`), não com o superusuário ([ADR-043](docs/arquitetura/adr/fase4/043-observabilidade-distribuida.md)) | sidecar do StatefulSet do banco |
| mongodb_exporter | `percona/mongodb_exporter:0.53.0` | Métricas do MongoDB, sidecar do banco do Billing, porta 9216, que conecta com o usuário `exporter`, com `--collector.dbstats` e `--collector.replicasetstatus` | sidecar do StatefulSet do banco |
| SonarQube (CI dos serviços) | `sonarqube:26.9.0.129388-community` | Servidor efêmero do job `sonarqube` de cada serviço, que aplica o quality gate ([ADR-041](docs/arquitetura/adr/fase4/041-estrategia-de-testes-e-qualidade.md)) | service container do job |
| SonarScanner (CI dos serviços) | `sonarsource/sonar-scanner-cli:12.2.0.4256_8.1.0` | Análise do código no mesmo job | - |

Prometheus, Grafana, Loki, Promtail, kube-state-metrics, Mailpit e Jaeger vieram dos manifests da fase 3, ajustados para vários serviços em vários namespaces e com probes de liveness e readiness em todos.

O Promtail está em fim de vida desde 02/03/2026. Ele continua aqui porque o enunciado pede a observabilidade da fase 3, que o usa. Saiu do 2.9 da fase 3 para a 3.6, a última linha, porque o cliente Docker do 2.9 fala uma versão de API que o Docker 29 do compose recusa. A saída é o Grafana Alloy, que lê os mesmos pods e empurra para o mesmo Loki.

## Como os serviços se conectam

### Usuário e permissões no RabbitMQ

Cada serviço tem um usuário próprio, criado pelo Job `rabbitmq-usuarios` ([`criar-usuarios.sh`](k8s/base/rabbitmq/criar-usuarios.sh)) com as senhas do Secret `rabbitmq-credenciais` e as permissões de [`permissoes.json`](k8s/base/rabbitmq/permissoes.json). Nenhum serviço tem permissão de configure: a topologia inteira vem do [`definitions.json`](k8s/base/rabbitmq/definitions.json), importado no boot do broker, e o serviço só confere o que precisa com declaração passiva. Assim nenhum comando volta como não roteável porque o consumidor do destino ainda não subiu.

Além do exchange, a permissão de tópico limita as routing keys que cada usuário publica. Sem ela, um serviço poderia publicar evento em nome de outro ou mandar uma cópia ao `pytstop.retry` com a routing key de uma fila de retry de outro serviço e entregar mensagem lá.

Os padrões de nome exato do `permissoes.json` terminam em `\z`, não em `$`: na expressão regular do broker o `$` também casa antes de um `\n` final, e com ele a chave `billing.comandos.retry.1s` seguida de `\n` passava pela permissão do `billing` (RabbitMQ 4.3.6; com `\z`, 403). Os de prefixo, das routing keys de comando e de evento, ficam abertos no fim, porque a chave continua com o nome da ação ou do fato.

Origem conferida ([ADR-036](docs/arquitetura/adr/fase4/036-mensageria-rabbitmq.md)): toda publicação leva na propriedade `user_id` do AMQP (*Advanced Message Queuing Protocol*) o usuário da conexão, e o broker recusa outro valor (`406 PRECONDITION_FAILED`), porque nenhum usuário de serviço tem a tag `impersonator`. O consumidor confere o `user_id` contra o produtor do tipo da mensagem, o `userId` da operação de envio no [`asyncapi.yaml`](contratos/asyncapi.yaml) (a routing key não serve, porque na cópia de retry ela é o nome da fila de retry). A cópia de retry é republicada pelo próprio consumidor e leva o `user_id` dele, então com `x-tentativa` de 1 em diante ele aceita o próprio usuário; qualquer outro valor é erro permanente e vai para a DLQ. O snippet de [Filas, exchanges e argumentos](#filas-exchanges-e-argumentos) traz as duas regras.

| Usuário | Publica em | Routing keys permitidas | Lê de | Senha (chave do Secret) |
|---|---|---|---|---|
| `os` | `pytstop.comandos`, `pytstop.retry` | `comando.billing.*` e `comando.execucao.*`; no retry, só `os.eventos.retry.1s` a `.300s` | `os.eventos` | `senha-os` |
| `billing` | `pytstop.eventos`, `pytstop.retry` | `evento.billing.*`; no retry, só `billing.comandos.retry.1s` a `.300s` | `billing.comandos` | `senha-billing` |
| `execucao` | `pytstop.eventos`, `pytstop.retry` | `evento.execucao.*`; no retry, só `execucao.comandos.retry.1s` a `.300s` | `execucao.comandos` | `senha-execucao` |
| `admin` | tudo (operação e management) | tudo | tudo | `admin-senha` |

Secret não atravessa namespace: o `make deploy` cria no namespace de cada serviço o Secret `rabbitmq`, com a chave `RABBITMQ_URL` (`amqp://<usuario>:<senha>@rabbitmq.pytstop-plataforma.svc.cluster.local:5672/%2F`; o `%2F` é o vhost padrão `/` codificado, a forma da [especificação de URI AMQP do RabbitMQ](https://www.rabbitmq.com/docs/uri-spec), em que `amqp://host/` seria o vhost vazio) montada com a senha do usuário dele ([Segredos gerados](#segredos-gerados)). Esse é o contrato com os serviços: cada processo lê a `RABBITMQ_URL` do Secret, e senha do broker não vai para os manifests do serviço. O Secret é da plataforma: o `make deploy` do `platform` o grava antes dos manifests do serviço, e o serviço não declara Secret com esse nome. Cada namespace recebe o usuário dele: `pytstop-os` o `os`, `pytstop-billing` o `billing` e `pytstop-execucao` (do repositório `execution-service`) o `execucao`.

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
| `DATABASE_URL` | OS e Execução | PostgreSQL do próprio serviço, no namespace dele, com o papel `os_app` ou `execucao_app` nos processos e o dono (`os` ou `execucao`) no Job de migração ([Contrato com os serviços](#contrato-com-os-serviços)) | `postgresql://pytstop:pytstop@postgres-os:5432/os` e `...@postgres-execucao:5432/execucao` |
| `MONGODB_URI` | Billing | MongoDB do próprio serviço, no namespace dele | `mongodb://mongo-billing:27017/billing?replicaSet=rs0` |
| `RUN_MIGRATIONS_ON_STARTUP` | OS e Execução | `false` (migração em Job antes do rollout) | `true` |
| `JWKS_URL` | Billing e Execução | `http://<svc>.pytstop-os.svc.cluster.local:8000/.well-known/jwks.json` | `http://os-service:8000/.well-known/jwks.json` |
| `BILLING_URL` | Execução | `http://<svc>.pytstop-billing.svc.cluster.local:8000` | `http://billing-service:8000` |
| `MP_MODE` | Billing | `simulado` | `simulado` |

Métricas, o contrato do [ADR-043](docs/arquitetura/adr/fase4/043-observabilidade-distribuida.md): cada processo do serviço (`api`, `relay`, `consumidor`, `notificador` e `prazos`) roda no seu Deployment e serve `/metrics` numa porta declarada em `ports` do container, com o nome `metrics` (a API serve na própria porta HTTP). O Prometheus raspa sozinho, por pod, todo pod dos namespaces `pytstop-*` com as anotações abaixo no template; a porta anotada precisa estar em `ports`. O label `app` do pod vira o `job` nos painéis, e o label `processo` vai para a série como `processo`.

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

O serviço cria os próprios Ingress, no próprio namespace, com `ingressClassName: kong`, a partir do exemplo do OS ([`borda-os-service.yaml`](k8s/exemplos/borda-os-service.yaml)) ou do Billing ([`borda-billing-service.yaml`](k8s/exemplos/borda-billing-service.yaml), com o webhook do Mercado Pago e o checkout do simulador); a Execução, do dela ([`borda-execution-service.yaml`](k8s/exemplos/borda-execution-service.yaml), o molde do OS sem JWKS nem rotas públicas). O `make smoke` aplica os três exemplos no kind como estão. Pela borda só saem os caminhos que o [ADR-038](docs/arquitetura/adr/fase4/038-borda-e-comunicacao-sincrona.md) permite: `/api/v1/*`, `/docs` e `/openapi.json` de cada serviço, o JWKS (*JSON Web Key Set*, as chaves públicas do JWT) do OS e o checkout do simulador do Billing. `/metrics` e `/api/v1/admin/*` casam um Ingress anotado com o plugin `fora-da-borda`, que responde 404 sem chamar o serviço; como o Kong escolhe o caminho mais longo, esse Ingress vence o de `/api/v1`.

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

Toda a topologia está em [`k8s/base/rabbitmq/definitions.json`](k8s/base/rabbitmq/definitions.json), importada pelo RabbitMQ no boot (kind, k3s e compose). Os serviços não declaram nada com efeito: só conferem com declaração passiva (`passive=True`). No RabbitMQ 4.3 a declaração passiva também exige permissão no recurso: cada usuário confere a própria fila (permissão de leitura) e os exchanges em que publica (escrita). Fila ou exchange de outro serviço, filas de retry e `.dlq` respondem `403 ACCESS_REFUSED` e fecham o canal, então o check de topologia do boot fica nesta lista:

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

    c_bi -.->|"erro transitório: cópia em pytstop.retry,<br/>chave = fila do atraso da tentativa"| rt_bi["billing.comandos.retry.1s<br/>.5s · .15s · .60s · .300s"]
    c_ex -.->|"erro transitório: idem"| rt_ex["execucao.comandos.retry.1s<br/>.5s · .15s · .60s · .300s"]
    c_os -.->|"erro transitório: idem"| rt_os["os.eventos.retry.1s<br/>.5s · .15s · .60s · .300s"]
    rt_bi -.->|"TTL da fila vence: dead-letter<br/>de volta à fila"| q_bi
    rt_ex -.->|"TTL da fila vence"| q_ex
    rt_os -.->|"TTL da fila vence"| q_os

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
| `pytstop.retry` | topic | Cópias para nova tentativa; a routing key é o nome da fila de retry do atraso daquela tentativa. É topic, com bindings de chave exata, só para aceitar permissão de tópico; num direct qualquer serviço com escrita no exchange alcançaria a fila de outro |
| `pytstop.dlx` | direct | Dead-letter das filas de trabalho; a routing key é o nome da fila |

| Fila | Consumidor | Bindings | Policy |
|---|---|---|---|
| `billing.comandos` | Billing | `pytstop.comandos` com `comando.billing.#` | `trabalho-billing.comandos`: `dead-letter-exchange=pytstop.dlx`, `dead-letter-routing-key=billing.comandos`, `dead-letter-strategy=at-least-once`, `overflow=reject-publish`, `max-length=10000`, `delivery-limit=5` |
| `execucao.comandos` | Execução | `pytstop.comandos` com `comando.execucao.#` | `trabalho-execucao.comandos`: as mesmas, com `dead-letter-routing-key=execucao.comandos` |
| `os.eventos` | OS | `pytstop.eventos` com `evento.billing.#` e `evento.execucao.#` | `trabalho-os.eventos`: as mesmas, com `dead-letter-routing-key=os.eventos` |
| `<fila>.retry.1s`, `.5s`, `.15s`, `.60s` e `.300s` | ninguém | `pytstop.retry` com routing key igual ao nome da fila de retry | `retry-<fila>` (padrão `^<fila>\.retry\.`): `dead-letter-exchange=""` (default exchange), `dead-letter-routing-key=<fila>`, `dead-letter-strategy=at-least-once`, `overflow=reject-publish`, sem `message-ttl`; o TTL é o argumento `x-message-ttl` de cada fila (1000 a 300000) |
| `<fila>.dlq` | ninguém (análise e `make redrive`) | `pytstop.dlx` com routing key `<fila>` | `dlq`: `message-ttl=604800000` (7 dias: as mensagens carregam dado pessoal, como a placa) |

Todas são quorum, duráveis, não exclusivas e sem auto-delete. O tipo (`x-queue-type`) é argumento de todas, e o TTL (`x-message-ttl`), só das filas de retry. O resto vem de policies, porque argumento de fila é imutável e a importação do boot ignora a mudança numa fila que já existe, enquanto as policies são regravadas a cada boot: mudar uma policy no `definitions.json` muda as filas no próximo restart do broker.

O TTL da fila de retry fica no argumento de propósito: o atraso está no nome da fila, e mudar um atraso é criar outra fila (com a permissão de tópico e os consumidores), nunca mudar o argumento de uma que já existe. E não vai para a `retry-<fila>`, comum às cinco: com policy e argumento, a fila quorum usa o menor dos dois ([ADR-036](docs/arquitetura/adr/fase4/036-mensageria-rabbitmq.md)), e um `message-ttl` ali cortaria os atrasos maiores.

A importação do boot não apaga fila, e fila que já existe fica com os argumentos com que nasceu. Um broker com volume (compose) ou PVC (StatefulSet) que ainda tem a fila de retry única de cada fila de trabalho (`<fila>.retry`, sem o atraso no nome) passa às filas por atraso sem perder cópia assim:

1. Pare os consumidores dos serviços (réplicas em zero no cluster), para nenhuma cópia nova entrar na `<fila>.retry`, e espere as três esvaziarem: em até 300 s, o maior `expiration` que as cópias levavam, todas voltam para a fila de trabalho pela policy que ainda vale. Confira na coluna `messages`:

   No kind (no k3s, troque o contexto em `--context`):

   ```bash
   kubectl --context kind-pytstop-p4 -n pytstop-plataforma exec rabbitmq-0 -c rabbitmq -- rabbitmqctl -q list_queues name messages
   ```

   No compose:

   ```bash
   docker compose -f compose/docker-compose.yml exec rabbitmq rabbitmqctl -q list_queues name messages
   ```

2. Aplique as definitions e as permissões: `make deploy` no kind e no k3s (o ConfigMap novo reinicia o broker, e o Job `rabbitmq-usuarios` roda de novo) ou `make down && make up` no compose (só recriando os containers o broker reimporta as definitions e o `rabbitmq-usuarios` reaplica o `permissoes.json`). Daqui em diante a `<fila>.retry` fica sem policy, porque a `retry-<fila>` passa a casar só as filas por atraso: cópia que ainda estivesse nela expiraria sem dead letter e se perderia (conferido no 4.3.6), e por isso o passo 1 vem antes.

3. Apague as três filas antigas, que até lá aparecem como fila de trabalho sem consumidor nos painéis 2, 4 e 5 do dashboard:

   No kind:

   ```bash
   for fila in billing.comandos.retry execucao.comandos.retry os.eventos.retry; do
     kubectl --context kind-pytstop-p4 -n pytstop-plataforma exec rabbitmq-0 -c rabbitmq -- rabbitmqctl delete_queue "$fila"
   done
   ```

   No compose:

   ```bash
   for fila in billing.comandos.retry execucao.comandos.retry os.eventos.retry; do
     docker compose -f compose/docker-compose.yml exec rabbitmq rabbitmqctl delete_queue "$fila"
   done
   ```

4. Suba os consumidores já publicando nas chaves `<fila>.retry.1s` a `.300s`: a permissão de tópico recusa a chave antiga, o nome da fila de trabalho.

Fila de trabalho ou DLQ com argumento além de `x-queue-type` (dead letter, TTL ou tamanho, que hoje vêm das policies; o `list_queues name arguments` mostra) também não muda na importação: apague-a, com as mensagens dela. Quando o conteúdo do broker não importa, apagar o volume resolve tudo de uma vez: `docker compose -f compose/docker-compose.yml down -v` no compose, ou `make kind-down` e `make kind-up deploy` no kind.

Limites: a cópia volta no atraso da fila de retry em que entrou; a fila de trabalho cheia (10000 mensagens) recusa a publicação, que o relay do produtor retenta; e o broker recusa mensagem acima de 1 MiB (`max_message_size` no `rabbitmq.conf`).

No consumidor do Billing, com pika (o `user_id` de toda publicação é o usuário da conexão; o broker recusa outro valor com `406 PRECONDITION_FAILED`, porque nenhum usuário de serviço tem a tag `impersonator`):

```python
import os

import pika

USUARIO = "billing"  # o user_id das cópias de retry é o do próprio consumidor
FILA = "billing.comandos"
ATRASOS = ["1s", "5s", "15s", "60s", "300s"]  # x-tentativa 1 a 5: <fila>.retry.<atraso>


def origem_valida(propriedades: pika.BasicProperties, produtor: str) -> bool:
    """produtor: usuário que publica o tipo (o userId da operação no AsyncAPI)."""
    tentativa = (propriedades.headers or {}).get("x-tentativa", 0)
    return propriedades.user_id == produtor or (
        tentativa >= 1 and propriedades.user_id == USUARIO
    )


def nova_tentativa(canal, entrega, propriedades, corpo) -> None:
    tentativa = (propriedades.headers or {}).get("x-tentativa", 0) + 1
    if tentativa > len(ATRASOS):
        canal.basic_reject(entrega.delivery_tag, requeue=False)  # vai para a DLQ
        return
    # mandatory + confirm: se a cópia não for roteada ou o broker a recusar,
    # o pika levanta UnroutableError/NackError antes do ack, e a original fica.
    canal.basic_publish(
        exchange="pytstop.retry",
        routing_key=f"{FILA}.retry.{ATRASOS[tentativa - 1]}",  # fila de retry do atraso
        body=corpo,
        properties=pika.BasicProperties(
            message_id=propriedades.message_id,
            correlation_id=propriedades.correlation_id,
            type=propriedades.type,
            user_id=USUARIO,
            content_type="application/json",
            delivery_mode=2,
            headers={**(propriedades.headers or {}), "x-tentativa": tentativa},
        ),
        mandatory=True,
    )
    canal.basic_ack(entrega.delivery_tag)


conexao = pika.BlockingConnection(pika.URLParameters(os.environ["RABBITMQ_URL"]))
canal = conexao.channel()
canal.queue_declare(FILA, passive=True)  # confere, não cria
canal.basic_qos(prefetch_count=10)  # por consumidor; a fila quorum não aceita global
canal.confirm_delivery()  # basic_publish espera o broker confirmar
```

Fluxo de uma mensagem que falha no consumidor:

1. Erro transitório: o consumidor publica uma cópia no `pytstop.retry`, sem `expiration`, com a routing key da fila de retry do atraso da nova tentativa (`x-tentativa` 1 vai para `<fila>.retry.1s`, 2 para `.5s`, 3 para `.15s`, 4 para `.60s` e 5 para `.300s`), o próprio `user_id` e o header `x-tentativa`, espera a confirmação do broker (publisher confirms, `mandatory`) e só então dá ack na original.
2. Quando o TTL (*time to live*) da fila vence, a fila de retry devolve a mensagem para `<fila>` pelo default exchange, com o histórico no header `x-death`. Como todas as cópias de uma fila de retry têm o mesmo TTL, a ordem de chegada é a de expiração, e nenhuma espera atrás de outra mais longa. Esse dead-letter é interno ao broker e não pede permissão do serviço.
3. Depois da 5ª tentativa, ou em erro permanente (validação, schema), o consumidor faz `basic_reject(requeue=False)` e a mensagem vai para `<fila>.dlq` pelo `pytstop.dlx`, onde fica até 7 dias. Corrigida a causa, `make redrive FILA=<fila>` a devolve para `<fila>` (abaixo).
4. Mensagem que derruba o consumidor sem ack (conexão ou canal fechados) volta para a fila e gasta uma entrega. É o caminho da mensagem venenosa, como a que traz um header que o pika não decodifica e derruba a conexão a cada entrega:
   - O limite: a policy da fila de trabalho limita as entregas a 5 (`delivery-limit`; o padrão da fila quorum é 20), e na sexta a mensagem vai para a DLQ com o motivo `delivery_limit`. Com o limite padrão, o consumidor passaria 21 entregas reconectando.
   - O que conta (conferido no 4.3.6): `basic_reject` com `requeue=True` conta entrega, e `basic_nack` com `requeue=True` não conta (a mensagem volta para a fila indefinidamente). Por isso o retry é sempre pelo `pytstop.retry`.
   - A cópia de retry entra na fila como mensagem nova, com a contagem de entregas do broker zerada, e não gasta o limite.

Por que uma fila de retry por atraso: TTL só vence quando a mensagem chega à cabeça da fila. Numa fila de retry única, com `expiration` em cada cópia, uma cópia de 1 s publicada atrás de uma de 8 s só voltou aos 8 s (RabbitMQ 4.3.6); no uso real, a cópia de 300 s da quinta tentativa seguraria por 5 minutos as primeiras tentativas de todas as mensagens atrás dela. Com o TTL fixo em cada fila, a cópia volta no atraso dela. O `make smoke` prova isso no kind, e o `make prova-retry` num RabbitMQ avulso (também no CI), publicando como o usuário `billing` ([`prova_retry.py`](scripts/prova_retry.py)): a cópia de 1 s publicada depois de uma de 5 s volta em 1 s, e o broker recusa a cópia na fila de retry de outro serviço, na chave antiga e na chave da própria fila seguida de `\n`.

Por que filas quorum e não classic duráveis: a quorum grava em log Raft com fsync antes de confirmar, aceita TTL e faz dead-lettering at-least-once (exige `overflow=reject-publish`). Assim a volta das filas de retry e a ida para a `.dlq` não perdem mensagem; na classic o dead-lettering é at-most-once.

Com um nó não há replicação, mas os clientes não mudam se o broker virar cluster. O custo é um pouco mais de memória e disco por fila, e o prefetch tem de ser por consumidor, porque a quorum não aceita prefetch global.

Redrive: `make redrive FILA=billing.comandos` (ou `execucao.comandos`, `os.eventos`) cria um shovel no próprio broker (plugin `rabbitmq_shovel`, ligado em [`enabled_plugins`](k8s/base/rabbitmq/enabled_plugins)) que move para a fila as mensagens que estavam na DLQ quando ele começou e se apaga ao terminar. O shovel só tira a mensagem da DLQ depois de a fila confirmar o recebimento, e preserva as propriedades (`user_id`, `message_id`, `x-tentativa`), então o consumidor a trata como a última tentativa. No compose, o mesmo shovel do [`redrive.sh`](scripts/redrive.sh) roda por `docker compose -f compose/docker-compose.yml exec rabbitmq rabbitmqctl set_parameter shovel`; o comando completo e quando fazer o redrive estão no [runbook da saga](docs/operacao/runbook-saga.md#como).

## Contrato com os serviços

O que o repositório de cada serviço precisa ter para o CD dele subir os três no kind, e o que o `platform` entrega. No job `deploy-kind` de um serviço, a ordem é: o [`deploy-kind.sh`](scripts/ci/deploy-kind.sh) sobe a plataforma e gera os Secrets ([Segredos gerados](#segredos-gerados)); o [`implantar-servicos.sh`](scripts/ci/implantar-servicos.sh) implanta os três serviços; o [`smoke-servicos.sh`](scripts/ci/smoke-servicos.sh) confere cada namespace; e, se algo falha, o [`diagnostico.sh`](scripts/ci/diagnostico.sh) despeja pods, eventos e logs de todos os namespaces.

### O que o `platform` entrega

| Item | Onde |
|---|---|
| Namespace do serviço, criado vazio pelo `make deploy` se ainda não existe, com a Role do Kong | [Gateway](#gateway-como-um-serviço-publica-as-rotas) |
| Secret `rabbitmq` com a `RABBITMQ_URL` do usuário do serviço | [Segredos gerados](#segredos-gerados) |
| As fontes do serviço, criadas só se ainda não existem: as senhas do banco, uma por papel, as chaves e a senha do admin semeado | [Segredos gerados](#segredos-gerados) |
| Usuário no RabbitMQ, com as permissões do serviço e a topologia pronta | [Usuário e permissões no RabbitMQ](#usuário-e-permissões-no-rabbitmq) |
| Kong com os `KongClusterPlugin` (rate limit por classe e `fora-da-borda`), que o Ingress do serviço referencia por anotação, e um exemplo de borda por serviço | [Gateway](#gateway-como-um-serviço-publica-as-rotas) e [`k8s/exemplos/`](k8s/exemplos) |
| Métricas pelo Prometheus (pod anotado), logs pelo Promtail, traces no Jaeger e SMTP no Mailpit | [Endereços e variáveis](#endereços-e-variáveis) |
| Versões fixas do PostgreSQL, do MongoDB e dos exporters | [Componentes e versões](#componentes-e-versões) |
| Scripts do CD: `deploy-kind.sh`, `implantar-servicos.sh`, `smoke-servicos.sh`, `diagnostico.sh` e o [`medir-kind.sh`](scripts/medir-kind.sh) | [`scripts/ci/`](scripts/ci) |
| O gancho de deploy remoto, desligado: o [`deploy-remoto.sh`](scripts/ci/deploy-remoto.sh), que o job `deploy-remote` do CD chama para implantar um serviço num cluster persistente pelo digest da imagem | [Nuvem opcional](docs/operacao/nuvem-opcional.md) |

### O que cada serviço precisa ter

| | OS | Billing | Execução |
|---|---|---|---|
| Nome no `implantar-servicos.sh` e imagem (`pytstop-<nome>`) | `os-service` | `billing-service` | `execution-service` |
| Namespace | `pytstop-os` | `pytstop-billing` | `pytstop-execucao` |
| Prefixo na borda | `/os` | `/billing` | `/execucao` |
| Rótulo do pod da API (seletor dos Services de borda, das NetworkPolicies e do smoke) | `app: os-service-api` | `app: billing-service-api` | `app: execution-service-api` |
| Service interno da API, porta 8000, sem a anotação do Kong (alvo do `JWKS_URL` e do `BILLING_URL`) | `os-service` | `billing-service` | `execution-service` |
| Banco (Service e porta; o StatefulSet tem o mesmo nome, e o contêiner do PostgreSQL se chama `postgres`), que só o próprio namespace alcança | `os-postgres:5432` | `billing-mongo:27017` | `execucao-postgres:5432` |
| Secret com as senhas do banco, uma por papel | `os-postgres` | `billing-mongo` | `execucao-postgres` |
| Papel dos processos (API, relay, consumidor e, conforme o serviço, `prazos` e `notificador`) | `os_app`, só DML nas tabelas do dono | `billing` | `execucao_app`, só DML nas tabelas do dono |
| Papel do Job de inicialização | `os`, dono do banco e das tabelas | `billing`; o root só inicia o replica set e cria os usuários | `execucao`, dono do banco e das tabelas |
| Papel do exporter, sidecar do banco | `os_exporter`, com `pg_monitor` | `exporter` | `execucao_exporter`, com `pg_monitor` |
| Exemplo de borda | [`borda-os-service.yaml`](k8s/exemplos/borda-os-service.yaml) | [`borda-billing-service.yaml`](k8s/exemplos/borda-billing-service.yaml) | [`borda-execution-service.yaml`](k8s/exemplos/borda-execution-service.yaml) |

Para escrever os manifests de um serviço novo, nesta ordem:

1. **Imagem e overlays.** `Dockerfile` na raiz, com os `ARG` `GIT_SHA` e `GIT_DATE`: quando o serviço entra como vizinho no CD de outro, a imagem dele sai do `docker build` do checkout, em paralelo com os outros builds. `k8s/overlays/kind-ci/kustomization.yaml`, o overlay do CD, ao lado de `kind` e `k3s`: sem ele, o `implantar-servicos.sh` falha nomeando o serviço e o commit, antes de construir qualquer imagem. A imagem do serviço leva o nome fixo `pytstop-<nome>` e `imagePullPolicy: IfNotPresent`.
   - A tag vem na implantação: o script gera `k8s/overlays/execucao/` (o overlay pedido com a imagem trocada pelo `images:` do kustomize), aplica e o apaga no fim. O diretório não pode existir no repositório e entra no `.gitignore`; se uma execução morreu no meio, apague `k8s/overlays/execucao` antes da próxima.
   - Toda outra imagem dos manifests (banco, exporter, initContainers, volumes de imagem) tem de estar na [tabela de versões](#componentes-e-versões), com a mesma tag: o script confere antes de construir e para nomeando a imagem que falta.
2. **Secrets.** Nenhum `Secret` nos manifests: os do serviço vêm do `make deploy` e entram por `secretKeyRef`, com os nomes e as chaves da tabela [Segredos gerados](#segredos-gerados). Sem o `rabbitmq` e o do banco, o script para antes do apply pedindo o `make deploy`.
3. **Banco.** StatefulSet, Service e o exporter como sidecar, no mesmo pod.
   - No PostgreSQL, o smoke entra no banco pelo nome da tabela acima: o StatefulSet tem o nome do Service do banco, então o pod é `<banco>-0`, e o contêiner do banco se chama `postgres` (o `kubectl exec -c postgres` da prova do `127.0.0.1`). Com outro nome, a etapa falha com `no answer from <banco>-0`. O controle da NetworkPolicy abre a conexão com `python`, por `kubectl exec -c api`, a partir do pod da API, então o contêiner da API se chama `api` e a imagem dela traz o `python` no `PATH`.
   - Um papel por uso ([ADR-042](docs/arquitetura/adr/fase4/042-cicd-e-deploy-kubernetes.md)): cada processo monta a `DATABASE_URL` (ou a `MONGODB_URI`) no pod, por expansão de variável, com a senha do papel da tabela acima, e nenhum processo do serviço usa o superusuário `postgres`, que só inicializa o banco.
   - No PostgreSQL, os papéis nascem de um script de init que o serviço traz num ConfigMap montado em `/docker-entrypoint-initdb.d`: a imagem o roda uma vez, na primeira inicialização do volume, com as senhas lidas do ambiente do contêiner do banco, nunca de argumento. Se o init falhar no meio, o volume fica inicializado sem os papéis: apague o PVC do banco.
   - O script abre, antes do primeiro comando com senha, desligando todo parâmetro que grava o texto do comando (o `psql` troca `:'senha'` pelo valor antes de enviá-lo, e o servidor a recebe em claro; o mecanismo está em [Troca de senha do banco](#troca-de-senha-do-banco)):

     ```sql
     SET log_statement = 'none';
     SET log_min_error_statement = 'panic';
     SET log_min_duration_statement = -1;
     SET log_min_duration_sample = -1;
     SET log_transaction_sample_rate = 0;
     ```

   - As tabelas nascem do Job, depois do script, e por isso o papel da aplicação ganha o DML por `ALTER DEFAULT PRIVILEGES FOR ROLE <dono>`, que cobre também a `alembic_version`, lida pelos pods para esperar a migração. Um `GRANT` sobre as tabelas existentes não alcançaria nenhuma.
   - O StatefulSet do PostgreSQL define `POSTGRES_INITDB_ARGS="--auth-host=scram-sha-256 --auth-local=scram-sha-256"` (requisito do ADR-042). A imagem oficial deixa o socket, o `127.0.0.1` e o `::1` em `trust`, e o exporter conecta por `127.0.0.1`: sem os argumentos, a senha do papel dele não seria conferida, e um exporter comprometido entraria como `postgres`. Os argumentos valem só na primeira inicialização do volume, e o `psql` dentro do contêiner passa a pedir a senha (`PGPASSWORD="$POSTGRES_PASSWORD"` e `-w`, como na [troca de senha do banco](#troca-de-senha-do-banco)).
4. **Job de inicialização**, a migração ou a preparação do banco, com o papel dele na tabela acima, o rótulo `app.kubernetes.io/component: inicializacao` e idempotente. O script apaga os Jobs com esse rótulo antes do apply (Job é imutável), aplica com `apply --server-side` e espera o banco (StatefulSet, 180 s), o Job (300 s; se ele falha, a espera acaba na hora, e o log dele vai para a saída) e cada Deployment (300 s).
5. **Deployments** (API, relay, consumidor e, conforme o serviço, `prazos` e `notificador`). O pod da API leva o rótulo `app: <nome>-api` e responde `GET /api/v1/saude`, `/docs` e `/openapi.json` com o `--root-path` do prefixo. Todo pod de processo, e o do banco pelo exporter, vem anotado para o Prometheus.
6. **NetworkPolicy de entrada**, que nega tudo e libera só o previsto: na API, o Kong (`app: kong` no `pytstop-plataforma`) e o Prometheus, na porta 8000; em cada processo além da API (relay, consumidor e, conforme o serviço, `prazos` e `notificador`), o Prometheus na 9100; no banco, o próprio namespace na porta do banco e o Prometheus na do exporter. Sem a regra do Kong, a saúde pela borda fica em 503; sem as do Prometheus, o `up` não chega a 1.
7. **Borda.** O Ingress e os Services de borda saem do exemplo da tabela acima, copiado sem mudança (o `make smoke` já valida os três). Pela borda, `GET <prefixo>/api/v1/saude`, `<prefixo>/docs` e `<prefixo>/openapi.json` respondem 200; `<prefixo>/metrics` e `<prefixo>/api/v1/admin/*` respondem 404 (o Ingress `fora-da-borda` dos exemplos).
8. **Conferir** com o `implantar-servicos.sh` e o `smoke-servicos.sh` (exemplos abaixo) ou com o `make kind-deploy` do próprio serviço, que chama o script só para ele.

O smoke confere, por namespace e nesta ordem:

- o Job de inicialização completo e cada Deployment e StatefulSet com todas as réplicas prontas e atualizadas, na geração atual do objeto;
- a borda: a saúde em 200 (o Kong recebe a rota de um Service novo antes do alvo e responde 503 até lá, então o smoke espera até 1 min), o Swagger em 200, e o `/metrics` e o `/api/v1/admin/outbox` em 404 com o corpo `no Route matched with those values`. Para o `/metrics`, que nenhum Ingress publica, a prova é que não é servido: o Kong sem rota responde o mesmo 404 e a mesma mensagem (a do plugin `request-termination` copia a do Kong de propósito). O corte pelo Ingress `fora-da-borda` só se distingue no `admin/outbox`: ele não existe em nenhum dos três serviços, e sem o Ingress a requisição chegaria ao serviço, que também responderia 404, com o corpo dele (conferido no Kong do kind: com o Ingress, o corpo é `{"message":"no Route matched with those values"}`; sem ele, a requisição segue para o serviço);
- cada pod anotado em `up = 1` no Prometheus (o pod do Job e o que está saindo de um rollout não contam) e o exporter do banco com `pg_up` (PostgreSQL) ou `mongodb_up` (MongoDB) em 1, as duas esperas juntas por até 45 s. O `up` diz só que o exporter responde ao Prometheus: o `postgres_exporter` serve o `/metrics` mesmo sem entrar no banco (papel inexistente, senha errada ou banco fora: `pg_up 0`), e o `mongodb_exporter`, quando o MongoDB recusa o usuário (`mongodb_up 0`; com o servidor inalcançável na partida do exporter, ele nem serve o `/metrics`, e o `up` cai);
- no PostgreSQL, o `psql` como `postgres`, sem senha, no `127.0.0.1` do pod do banco, recusado por falta de senha (sem `trust`);
- a NetworkPolicy do banco: um controle, em que o pod da API (do próprio namespace) conecta à porta do banco, e a prova, em que o `rabbitmq-0` da plataforma não conecta. A conexão do `rabbitmq-0` tem de esgotar o prazo de 3 s, porque o kindnet (a rede do kind) descarta o pacote barrado; conexão aceita, recusada ou nome que não resolve reprovam, e o prazo esgotado só vale se o controle conectou.

O smoke escreve a tabela `Service | Stage | Result` na saída e, no GitHub Actions, no summary do job, uma linha por etapa, com `ok: <detalhe>` ou `FAILED: <detalhe>`, e sai com status 1 nomeando os serviços que falharam, ou com 2 se faltar `jq`, `curl` ou `timeout` (no macOS, `perl`). O `BORDA` (padrão `https://localhost`) e o `KUBE_CONTEXT` (padrão `kind-$CLUSTER`) vêm do ambiente; o certificado só deixa de ser verificado para `localhost`, com ou sem porta.

A chamada do CD de um serviço leva a imagem dele pelo arquivo do `docker save` e a ref gravada nele, que o script confere contra o `manifest.json` do arquivo; no exemplo, a do OS, no commit `5f2a9c1`, com os vizinhos clonados ao lado:

```bash
scripts/ci/implantar-servicos.sh --overlay kind-ci \
  --tar os-service=imagem.tar --imagem os-service=ghcr.io/fiap-postech-sw-architecture/pytstop-os-service:5f2a9c1 \
  os-service=../os-service billing-service=../billing-service execution-service=../execution-service
scripts/ci/smoke-servicos.sh
```

Localmente, com a plataforma no kind (`make kind-up deploy`) e os três repositórios clonados ao lado deste, sem `--tar` o script constrói as três imagens, com o commit como tag. Com mudança não commitada ou arquivo novo, a tag vira `<commit>-sujo-<hash da árvore>` e o script avisa: um segundo deploy depois de editar o código reinicia os Deployments, em vez de reaproveitar a imagem de mesma tag.

```bash
scripts/ci/implantar-servicos.sh --overlay kind \
  os-service=../postech-sw-arch-p4-os-service \
  billing-service=../postech-sw-arch-p4-billing-service \
  execution-service=../postech-sw-arch-p4-execution-service
scripts/ci/smoke-servicos.sh
```

Um cluster com os serviços implantados não serve ao `make smoke`, que recusa um namespace de serviço com Ingress (ele aplica os exemplos de borda com servidores de eco). Para voltar a um cluster só da plataforma: `kubectl --context kind-pytstop-p4 delete namespace pytstop-os pytstop-billing pytstop-execucao` e `make deploy`, que recria os namespaces vazios.

Tudo o que pode pendurar no `implantar-servicos.sh` roda com prazo, e o estouro reprova o serviço nomeando a chamada, em vez de consumir o timeout do job: `PRAZO_BUILD` (900 s, o `docker build`), `PRAZO_CARGA` (300 s, o `kind load`) e `PRAZO_KUBECTL` (120 s por chamada ao cluster; nas esperas, somado ao tempo delas) e, nas esperas, `ESPERA_BANCO` (180 s), `ESPERA_JOB` (300 s) e `ESPERA_DEPLOYMENT` (300 s).

Os testes dos dois scripts ([`test_implantar_servicos.py`](tests/test_implantar_servicos.py) e [`test_smoke_servicos.py`](tests/test_smoke_servicos.py)) rodam com `docker`, `kind`, `kubectl`, `curl`, `sleep` e `date` falsos e conferem a ordem de cada namespace, os prazos, cada etapa reprovando o que deve (cada código HTTP errado, cada réplica fora do lugar), as esperas pelo tempo e o nome do serviço em toda falha.

O ensaio com os três serviços reais no kind (tempos, memória e CPU de cada pod contra o orçamento do ADR-042, e a saída do smoke) está em [`docs/operacao/ensaio-integrado.md`](docs/operacao/ensaio-integrado.md).

## Mercado Pago na sandbox

Prova que o Billing cria uma cobrança no Mercado Pago, confirma o pagamento e estorna, com as credenciais de teste do Mercado Pago e sem mover dinheiro ([ADR-040](docs/arquitetura/adr/fase4/040-integracao-mercado-pago.md), RF-032 a RF-034). O CI, o `make e2e` e o `make demo` ficam no simulador do Billing; esta prova roda à mão, num kind local, com dois alvos:

| Alvo | O que faz | Credencial |
|---|---|---|
| `make mp-sandbox-ensaio` | O mesmo roteiro, com o simulador do Billing no lugar do comprador. Prova o fluxo, o formato da evidência e o desfazer, e não fala com o Mercado Pago | nenhuma |
| `make mp-sandbox` | O roteiro de verdade: o Billing em modo `mercadopago`, o link do checkout impresso no terminal e o pagamento feito por você no navegador | `MP_ACCESS_TOKEN` e `MP_WEBHOOK_SECRET` no ambiente do shell |

### O que prova e o que não prova

| Cenário | O que afirma |
|---|---|
| Pagamento no checkout | O pagamento nasce `SOLICITADO` com `provedor=mercadopago`; depois que o comprador de teste paga, o Billing o confirma (conciliação do `prazos`) e a OS chega a `aguardando_execucao`. No Mercado Pago, `GET /v1/payments/{id}` mostra `approved`, no valor e na moeda do orçamento, com o `external_reference` igual ao `pagamento_id` do Billing e `live_mode` falso. Se a resposta não trouxer `live_mode`, o cenário passa e o `resumo.md` registra que a natureza de teste do pagamento não foi provada pela consulta |
| Cancelamento depois do pagamento | Segunda OS, paga do mesmo jeito e cancelada antes da execução: saga `compensada` (`CancelarExecucao`, `EstornarPagamento`, `LiberarReserva`, `CancelarOrcamento`, `DescartarDiagnostico`), pagamento `ESTORNADO` no Billing e `refunded` no Mercado Pago |
| Cancelamento sem pagar | Terceira OS, levada ao checkout e cancelada: pagamento `CANCELADO` no Billing e, no Mercado Pago, `GET /checkout/preferences/{id}` com `expires` verdadeiro e `expiration_date_to` vencido (com até 5 min de folga de relógio). Prova que a preferência consta como expirada; não prova que o checkout recusaria um pagamento depois disso. Se a resposta não trouxer esses dois campos, o cenário passa e o `resumo.md` registra que a expiração não foi provada pela consulta |

**Não prova o webhook.** A documentação do Mercado Pago diz que pagamentos de teste não enviam notificações. No modo real, o Billing recebe uma `notification_url` pública (`https://example.com/api/v1/webhooks/mercadopago`, ou a de `E2E_MP_NOTIFICATION_URL`) só para o Mercado Pago aceitar criar a cobrança: a do kind (`https://localhost/billing/...`) não é alcançável de fora, e a documentação manda não usá-la. A confirmação vem da conciliação do processo `prazos` do Billing (`GET /v1/payments/search?external_reference=` a cada 30 s), e o `resumo.md` diz isso e qual URL o Mercado Pago recebeu. O `MP_WEBHOOK_SECRET` é exigido porque o Billing não sobe em modo real sem ele, mas nenhuma notificação o exercita. Também não prova pagamento em produção, e o formato real das respostas do Mercado Pago só aparece no primeiro uso com credencial (o ensaio usa o simulador).

### Como rodar

Precisa do cluster no overlay `kind` (o padrão do `make deploy`; o `kind-ci` expira o orçamento em 72 s, curto demais para abrir o link e pagar) com a plataforma e os três serviços, `uv` e `kubectl`. Com os repositórios dos serviços ao lado deste:

```bash
make kind-up deploy
scripts/ci/implantar-servicos.sh --overlay kind \
  os-service=../postech-sw-arch-p4-os-service \
  billing-service=../postech-sw-arch-p4-billing-service \
  execution-service=../postech-sw-arch-p4-execution-service
make mp-sandbox-ensaio
```

O ensaio leva cerca de meio minuto num kind sem outra carga e termina com `3 passed, 14 deselected` (e o tempo) e `varredura de reports/mp-sandbox-ensaio: nenhum segredo`, e deixa `reports/mp-sandbox-ensaio/resumo.md`. O Billing continua em `simulado` (`curl -sk https://localhost/billing/api/v1/saude` diz `"modo":"simulado"`), e o Secret `billing-mercadopago` não existe.

Se um ensaio foi interrompido ou reprovado, apague o cluster e suba outro (`make kind-down` e o bloco acima de novo) antes do `make mp-sandbox`: um pagamento `SOLICITADO` que sobrou dele seria conciliado no Mercado Pago de verdade. A conferência prévia avisa disso, mas não tem como conferir.

Para o modo real você precisa de quatro coisas do painel do Mercado Pago (os nomes dos menus vêm da documentação consultada em 14/10/2026; se o painel estiver diferente, siga o que ele mostrar):

1. uma aplicação do tipo Checkout Pro, em [Mercado Pago Developers](https://www.mercadopago.com.br/developers/panel/app), Suas integrações;
2. duas contas de teste do Brasil (o Billing cobra em BRL, e o checkout de outro país não paga nessa moeda), uma Vendedor e outra Comprador, na página da aplicação, Contas de teste (anote usuário e senha de cada uma; elas não podem ser apagadas);
3. o Access Token de teste, em Suas integrações, Dados da integração, Testes, Credenciais de teste (entre com a sua conta real para ver essa tela; o prefixo pode ser `TEST-` ou `APP_USR-`);
4. a assinatura secreta do webhook, em Webhooks, Configurar notificações: em Modo produtivo, informe uma URL HTTPS pública qualquer (por exemplo `https://example.com/api/v1/webhooks/mercadopago`), marque o evento Pagamentos e salve; a chave aparece depois de salvar. A sandbox não envia webhook, então a URL só precisa ser pública.

As duas credenciais ficam só no ambiente do shell, sem `export`. Cada `read` espera você colar o valor e teclar Enter; o `make` recebe as duas por atribuição na própria linha, e o `unset` as tira do shell no fim:

```bash
printf 'Access Token de teste: '; read -rs MP_ACCESS_TOKEN; echo
printf 'Assinatura secreta do webhook: '; read -rs MP_WEBHOOK_SECRET; echo
MP_ACCESS_TOKEN="$MP_ACCESS_TOKEN" MP_WEBHOOK_SECRET="$MP_WEBHOOK_SECRET" make mp-sandbox
unset MP_ACCESS_TOKEN MP_WEBHOOK_SECRET
```

O `make` recusa as duas se vierem na linha de comando (`make mp-sandbox MP_ACCESS_TOKEN=...`): o valor ficaria no `ps` e no histórico do shell.

O terminal imprime o link do checkout e o que fazer: abrir uma **janela anônima**, entrar no Mercado Pago só com o usuário Comprador de teste (nunca a sua conta real) e pagar com o cartão de teste da documentação (nome do titular `APRO` aprova; `OTHE`, `FUND` e `SECU` recusam). O script espera até 15 min por pagamento, consulta o Billing a cada 5 s, mostra a contagem regressiva a cada 30 s e avisa cada tentativa recusada (o pagamento encerra na recusa de número `PAGAMENTO_MAX_RECUSAS`, 3 no `kind`). São dois pagamentos seus, nos dois primeiros cenários.

O quadro com o link diz o site dele (`www.mercadopago.com.br`) antes de a espera começar. Se a página mostrar erro de conta (usuário errado, conta real logada, país diferente), dê **um** `Ctrl-C`: o script desfaz o modo real, e você não espera os 15 min para ouvir "O Mercado Pago não recebeu nenhum pagamento deste link. Você pagou?".

O `make mp-sandbox` leva cerca de 100 s de máquina (a criação da cobrança, a conciliação de cada pagamento, que o `prazos` faz a cada 30 s, e os rollouts do modo real e do desfazer), mais o tempo de você pagar duas vezes no navegador. Quando tudo passa, o fim do terminal é este (os tempos mudam):

```text
[mp-sandbox] Billing: desfazendo o modo real em 3 passos (Secret, variáveis e reinício). Não feche o terminal e não use kill -9.
[mp-sandbox] 1/3 apagando o Secret
[mp-sandbox] 2/3 tirando MP_MODE, SIMULADOR_PERMITIDO e MP_NOTIFICATION_URL dos Deployments
[mp-sandbox] 3/3 reiniciando os Deployments
[mp-sandbox] Billing de volta ao simulador
3 passed, 14 deselected in 114.44s (0:01:54)
varredura de reports/mp-sandbox: nenhum segredo
```

E a evidência fica em `reports/mp-sandbox/resumo.md`.

| Variável | Para quê | Padrão |
|---|---|---|
| `MP_ACCESS_TOKEN`, `MP_WEBHOOK_SECRET` | Credenciais de teste, lidas do ambiente do shell (`make mp-sandbox`) | ausentes |
| `E2E_MP_MANTER` | `1` deixa o Billing em modo real no fim (o Secret e as variáveis ficam no cluster), para criar OS à mão pelo Swagger e gravar o pagamento no navegador. Enquanto estiver assim, `make e2e` e `make demo` não servem: o simulador não existe em modo real, e eles pedem o overlay `kind-ci`. Para voltar ao simulador, rode `make mp-sandbox-ensaio` | desfaz |
| `E2E_MP_NOTIFICATION_URL` | URL https pública para o `MP_NOTIFICATION_URL` do Billing, se o Mercado Pago recusar a padrão. Tem de ser https, sem usuário e de host público: a conferência prévia recusa `localhost`, IP privado ou local e nome sem ponto | `https://example.com/api/v1/webhooks/mercadopago` |
| `E2E_MP_MODO` | `real` ou `ensaio`; quem define é o `make`, e sem ele os cenários `@mp_sandbox` são pulados. Se ficar definido no seu shell, `make e2e` e `make demo` param com erro, em vez de passar sem rodar nada | — |
| `KUBE_CONTEXT`, `E2E_URL` | Os mesmos do E2E da saga; o contexto tem de ser `kind-*` e o escape do E2E (`E2E_CONTEXTO_NAO_DESCARTAVEL`) não vale aqui | `kind-pytstop-p4`, `https://localhost` |

### O que o script faz e desfaz

| Etapa | O que acontece |
|---|---|
| Conferência prévia | Em segundos, antes do pytest e de qualquer mudança no cluster (detalhes abaixo). Se reprova, o `make` para ali com uma mensagem em português e o código 2, e não toca em `reports/` |
| Liga o modo real | Cria o Secret `billing-mercadopago` com `kubectl apply --server-side -f -`, o manifesto em JSON montado em memória e enviado pelo stdin; define `MP_MODE=mercadopago` e `SIMULADOR_PERMITIDO=false` em todos os Deployments do Billing, mais `MP_NOTIFICATION_URL`; reinicia e espera cada rollout. Só segue com `/billing/api/v1/saude` dizendo `mercadopago` |
| Cenários | Cada um cria os próprios dados, com códigos únicos, como no E2E da saga |
| Desfaz, sempre | Apaga o Secret e **tira** `MP_MODE`, `SIMULADOR_PERMITIDO` e `MP_NOTIFICATION_URL` dos Deployments, para valerem de novo `simulado` e `true` do ConfigMap (um valor escrito no Deployment sobrevive a um novo `make kind-deploy`), reinicia e espera cada rollout |
| Ensaio | Não cria Secret. Só garante o Billing em `simulado`, sem Secret e sem as três variáveis |

A conferência prévia olha, nesta ordem: o contexto `kind-*`, as duas credenciais no ambiente (presentes, sem espaço nem quebra de linha; a mensagem nunca mostra o valor nem o tamanho), a borda local, o overlay `kind` (orçamento de pelo menos 1 h, pagamento de pelo menos 15 min de validade e 2 recusas), os três serviços saudáveis, o modo do Billing (`simulado` ou `mercadopago`) e o token no próprio Mercado Pago (uma busca por referência que não existe, sem efeito: 401 e 403 barram, e outro 4xx vira aviso e o roteiro segue). No modo real ela diz qual `notification_url` o Billing vai usar e de onde ela veio. Ao fim imprime `[mp-sandbox] conferência ok`.

O desfazer roda com sucesso, falha, `Ctrl-C`, SIGTERM ou SIGHUP (terminal fechado). Depois do primeiro sinal nenhum outro o interrompe, e o `kubectl` roda em sessão própria, fora do alcance do `Ctrl-C` do terminal. O terminal mostra cada passo dele ("1/3 apagando o Secret", e assim por diante) e pede para não fechar a janela. Cada passo é tentado mesmo que o anterior falhe, cada rollout é esperado mesmo que outro falhe, e o erro traz os três comandos para terminar à mão.

O ensaio é também o jeito de desfazer o que uma execução deixou. Se um `E2E_MP_MANTER=1` anterior, um `kill -9` ou uma queda deixou o modo real, o Secret ou uma variável, ele desfaz tudo; se não há sobra, não reinicia nada. O desfazer não cobre `kill -9`, queda de energia nem o Mac dormindo: o Billing pode ficar em modo real. Rode `make mp-sandbox-ensaio` e confira com `curl -sk https://localhost/billing/api/v1/saude`, que deve dizer `"modo":"simulado"`.

### Relatórios

`reports/mp-sandbox/` no modo real e `reports/mp-sandbox-ensaio/` no ensaio (pastas ignoradas pelo git). O ensaio recria a pasta dele e nunca toca na do real. O `make mp-sandbox` que encontra um `reports/mp-sandbox/resumo.md` move a pasta para `reports/mp-sandbox.AAAAMMDD-HHMMSS` e não apaga nenhuma anterior; a pasta de uma execução que não chegou a escrever o `resumo.md` é descartada. Assim que uma execução passar, copie o `resumo.md` para fora de `reports/`.

| Arquivo | Conteúdo |
|---|---|
| `resumo.md` | Modo, data, cenário, resultado (`passou`, `falhou` ou `interrompido`, se você deu `Ctrl-C`), duração, `ordem_id`, `pagamento_id`, id do pagamento no Mercado Pago, as transições com a hora que o serviço registrou (histórico da OS, passos da saga e datas do pagamento), o que veio do Mercado Pago, a `notification_url` usada, a frase de que a confirmação veio da conciliação, e os prints que você tira |
| `evidencia.json` | O mesmo em JSON, sanitizado |
| `relatorio-e2e.md`, `junit.xml`, `cucumber.json`, `cenarios.json` | O relatório do E2E, como em `reports/e2e`. O `junit.xml` traz o nome da máquina: na evidência da entrega, anexe só o `resumo.md` |

A sanitização é por **lista de campos permitidos**. Do Mercado Pago entram só `id`, `status`, `transaction_amount`, `currency_id`, `date_approved`, `external_reference` e `live_mode` (nunca e-mail, nome, documento ou cartão do pagador), e do `id` da preferência, só o uuid, sem o User ID da conta vendedora que o precede. Do Billing, o pagamento sem o `checkout_url`; da saga, a etapa, o motivo e o rastro de cada passo. Antes de gravar, todo texto é varrido atrás do token, da assinatura, de qualquer segredo que o E2E registrou, de `Bearer` seguido de um token, de `TEST-` e `APP_USR-`, de padrão de e-mail (menos os usuários que o próprio E2E cria, do domínio `pytstop.dev`) e do prefixo numérico do User ID (`<números>-<uuid>`); se achar, o script recusa gravar e diz o arquivo e a linha (sem repetir o valor). Depois do pytest, `python -m e2e.varredura` varre a pasta toda e apaga o arquivo em que achar algo.

Os prints que o terminal pede são do checkout, do pagamento aprovado e do painel do vendedor de teste. Cubra e-mail, nome, User ID e CPF das contas de teste, e nunca mostre a tela de Credenciais nem a de Webhooks. Antes de commitar a evidência, rode `python -m e2e.varredura <pasta>` e `gitleaks dir <pasta>`.

Quando uma afirmação falha ou o prazo estoura, o terminal mostra, mascarado, o estado da OS e da saga, o pagamento no Billing, os pagamentos que o Mercado Pago tem para aquele `external_reference` (cada um com o `live_mode`), as filas mortas (e quantas a mais que no início do cenário: mensagem de uma execução anterior não vira causa), as últimas 40 linhas do log da `api`, do `consumidor` e do `prazos` e a causa provável. Das linhas do log só passam as que importam (aviso ou erro, resposta 4xx ou 5xx, `resultado` fora da rotina e o evento `mercadopago_request_rejected`), e delas só os 16 campos de `CAMPOS_DO_LOG`, em `e2e/apoio/diagnostico.py` (tipo, comando, resultado, tentativa, erro, código, motivo, operação, status, caminho, id do pagamento, referência, mensagem, causa, `status_http` e `causas`), cada um cortado em 160 caracteres e mascarado. O script não filtra o conteúdo desses campos: que o texto livre do Mercado Pago (`message`, `description`) não apareça é garantia do Billing da `main`, que não o registra. O evento de recusa traz sempre a operação e o HTTP, e traz o `error` do Mercado Pago (`erro_do_mp`, só se casar com `[a-z_]{1,40}`) e os códigos de `causas` (só se casarem com `[A-Za-z0-9_.-]{1,40}`) quando passam pelo filtro do Billing. A causa provável diz qual chamada foi recusada mesmo se o evento vier só com a operação e o HTTP, e a falha por divergência com o Mercado Pago (por exemplo, `live_mode` verdadeiro) vem com a dica de conferir primeiro no painel do Vendedor de teste.

Nas esperas da cobrança aberta e do pagamento, se a fila morta do Billing cresce o script reprova na hora, sem esperar o prazo: o Billing recusou de vez um comando da saga (isso só vale se a foto inicial das filas foi lida). Nos outros passos vale o prazo do passo (30 a 60 s), e o diagnóstico mostra a fila. O estorno que o Mercado Pago recusa nem passa pela fila morta: a saga vai a `falha_na_compensacao`, e o diagnóstico mostra a etapa e a falha.

### Segurança

- O token e a assinatura nunca vão em argumento de comando (`ps`), em arquivo, no `repr` de fixture, no traceback, no `junit.xml`, no `cucumber.json` nem no resumo. Entram na máscara do E2E assim que lidos, antes de qualquer conferência que possa reprovar, e a máscara central do plugin do pytest cobre também `TEST-` e `APP_USR-`. O ambiente inteiro nunca é argumento de quem pode falhar (o pytest mostra os argumentos no traceback): só as cinco chaves do sandbox são recortadas.
- Nenhum processo filho (`kubectl`, `docker`, `port-forward`) herda as duas credenciais: cada um é lançado com o ambiente do processo sem elas (`e2e/apoio/kube.py`), inclusive os da conferência prévia e os da fixture do pytest, que rodam antes de o preflight tirá-las do ambiente do próprio processo, onde elas não ficam depois de lidas. Fora a memória do processo, o token só passa pelo cabeçalho da chamada ao Mercado Pago e pelo stdin do `kubectl apply`.
- As chamadas ao Mercado Pago só leem, têm prazo de 10 s e User-Agent próprio, nunca seguem redirecionamento para outro host (o cabeçalho com o token iria junto) e verificam o TLS. O host é fixo (`api.mercadopago.com`), e o id que entra no caminho da URL é validado.
- Recusa rodar fora de um kind, sem escape, porque o token vai para um Secret do cluster.
- O freio contra um token de produção vem depois do pagamento. O Mercado Pago aceita o token de produção como o de teste, e o prefixo (`TEST-` ou `APP_USR-`) não os distingue: a conferência prévia prova que o token é aceito, não que é de teste. Só o `live_mode` verdadeiro do pagamento reprova o cenário, e a mensagem manda conferir primeiro no painel do Vendedor de teste (ela traz o id do pagamento) e, se for mesmo de produção, estornar e trocar as credenciais. O roteiro manda pagar com o comprador e o cartão de teste, que o checkout de produção recusa, então um pagamento real exigiria que você usasse um cartão real. Não conheço campo da preferência que distinga a conta de teste, e sem uma credencial não há como verificar.

### Solução de problemas

As recusas da conferência prévia começam com `[mp-sandbox] não posso seguir:`. A do `make` para credencial na linha de comando e a do pytest para o `E2E_MP_MODO` esquecido têm mensagem própria.

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| `MP_ACCESS_TOKEN não está no ambiente` | A credencial não chegou ao `make` | Leia com `read -rs` e passe só ao `make`, como no bloco de "Como rodar" |
| `MP_ACCESS_TOKEN tem espaço ou quebra de linha` | Valor colado, ou `read` sem `-r` | Leia de novo com `read -rs` |
| `MP_ACCESS_TOKEN e MP_WEBHOOK_SECRET não vão na linha do make` | Credencial escrita depois de `make mp-sandbox` | Tire-a da linha e use o bloco de "Como rodar" |
| `o Mercado Pago não aceita o MP_ACCESS_TOKEN (HTTP 401)` | Token de produção, de outra aplicação, revogado ou com espaço no fim | Use o Access Token de teste da aplicação, da mesma conta de teste |
| `serviços fora do ar pela borda` ou `o kubectl não conseguiu ler o cluster` | Cluster ou serviços fora do ar, ou `KUBE_CONTEXT` errado | Suba o cluster e os três serviços ("Como rodar") e confira o `KUBE_CONTEXT` |
| `o Billing está com os prazos do E2E (kind-ci)` | Cluster subido com `OVERLAY=kind-ci`, que é o do `make e2e` e do `make demo` | `make kind-down` e suba de novo no overlay `kind` (`make kind-up deploy` e o `implantar-servicos.sh` de "Como rodar"); trocar de overlay no mesmo cluster não desfaz o anterior |
| `E2E_MP_MODO=... está no seu shell` (no `make e2e` ou no `make demo`) | A variável ficou definida no shell | `unset E2E_MP_MODO` |
| O Mercado Pago recusou criar a cobrança (`POST /checkout/preferences` com 4xx) | Um dado da cobrança (valor, moeda, itens) ou a `notification_url`; o terminal diz o HTTP e os códigos que o Billing registrou, e qual URL foi usada | Procure os códigos na documentação do Mercado Pago e confira o valor e os itens. Para ver a linha inteira do log do Billing (a operação, o HTTP, o `error` e os códigos que ele deixou passar; o texto do Mercado Pago ele nunca registra): `kubectl --context kind-pytstop-p4 -n pytstop-billing logs deploy/billing-service-consumidor --tail=200 \| grep mercadopago_request_rejected`. Se suspeitar da URL, use outra URL https pública, por exemplo `https://example.org/api/v1/webhooks/mercadopago`: `E2E_MP_NOTIFICATION_URL=https://example.org/api/v1/webhooks/mercadopago make mp-sandbox` (junto das duas credenciais) ou, com o modo real mantido, `kubectl --context kind-pytstop-p4 -n pytstop-billing set env deployment --all MP_NOTIFICATION_URL=https://example.org/api/v1/webhooks/mercadopago` |
| O Mercado Pago recusou o pagamento | Nome do titular diferente de `APRO`, cartão errado, janela comum ou conta real logada | Janela anônima e só o usuário Comprador de teste; o cartão está no terminal |
| O painel do Mercado Pago pede código de verificação | A conta de teste é fictícia, sem e-mail de verdade | O código da tabela de contas de teste (coluna "Código de verificação") ou os 6 últimos dígitos do User ID da conta; o terminal lembra |
| O pagamento não confirma em 2 min | Conciliação parada | `kubectl --context kind-pytstop-p4 -n pytstop-billing logs deploy/billing-service-prazos` (a linha `deadlines_started` diz `conciliacao: true`) |
| `o Billing pode ter ficado em modo real` | O desfazer falhou em algum passo | Rode os comandos que a mensagem traz, ou `make mp-sandbox-ensaio` |
| `a expiração NÃO foi provada` ou `a natureza de teste do pagamento NÃO foi provada` (no `resumo.md`) | A consulta do Mercado Pago não trouxe `expires` e `expiration_date_to`, ou o `live_mode`, no formato esperado | Não reprova: o `resumo.md` registra a observação. Para a expiração, a prova indireta é o log do consumidor e a métrica `pytstop_mercadopago_requisicoes_total{operacao="cancelar_cobranca"}`; para o `live_mode`, o painel do vendedor de teste |

### O que fica fora do `make e2e`, do `make demo` e do CI

O `make e2e` pede `-m "not mp_sandbox"`, o `make demo` pede `-m demo`, e nenhum workflow cita o sandbox. Quem roda o pytest cru, sem `E2E_MP_MODO`, vê os três cenários pulados sem que o `kubectl` seja chamado, e com `E2E_MP_MODO` definido só eles rodam; `E2E_MP_MODO` definido sem nenhum cenário do sandbox selecionado é erro, e não um verde. O `make test` coleta o E2E sem cluster, e a falta de definição de um passo do feature reprova ali.

Os testes ficam em [`tests/e2e_apoio/`](tests/e2e_apoio), com 100% de linhas e ramos do código novo de [`e2e/apoio/`](e2e/apoio): um `kubectl` que grava argumentos e stdin prova que o token só passa pelo stdin e que o Secret não aparece em nenhum argumento; o desfazer roda com exceção, `KeyboardInterrupt` e falha no meio do ligar, e com processos de verdade provam que um sinal ao grupo (Ctrl-C, SIGTERM, SIGHUP) não mata o `kubectl` do desfazer e que um segundo Ctrl-C não o pula; o cliente do Mercado Pago é testado com `httpx.MockTransport` (formatos de `payments/{id}`, `payments/search` e `checkout/preferences/{id}`, erros 4xx e 5xx, redirecionamento); a espera e o prazo, com relógio falso; o `Makefile`, com um `uv` falso (a conferência antes dos relatórios, a rotação da evidência e a recusa de credencial na linha de comando); e o pytest de verdade, num subprocesso, prova a exclusão do sandbox, a conferência prévia que para antes de qualquer mudança no cluster e o relatório sem credencial.

## E2E da saga

O E2E é o BDD de ponta a ponta do desafio ([enunciado, l. 82](docs/requisitos/fase4/desafio-tech-fase-4.md)): uma OS percorre os três serviços de verdade, no kind, pela borda, e cada falha da saga é provocada e conferida. Fica neste repositório porque nenhum serviço é dono do fluxo inteiro.

A ferramenta é o `pytest-bdd` 8, com Gherkin em português (`# language: pt`). Usa o mesmo runner e as mesmas fixtures do BDD de componente de cada serviço ([ADR-041](docs/arquitetura/adr/fase4/041-estrategia-de-testes-e-qualidade.md)), e as tags do Gherkin viram markers do pytest.

### Como rodar

O E2E derruba o Billing com `kubectl scale`, cria usuários, preços, estoque e OS, e não limpa nada. **Rode só num cluster descartável**, uma execução por vez em cada cluster: duas execuções juntas se atropelam, porque a segunda religa o que a primeira acabou de derrubar. A sessão recusa um contexto que não comece por `kind-` e um nó do kind que não publique, no loopback, o host e a porta da `E2E_URL`, a borda que o E2E usa (por padrão a 443 de `https://localhost`; o guarda tira o par da própria URL, então uma `E2E_URL` para outro lugar também é recusada). O mesmo guarda roda no `make e2e` e no `make demo`. O escape é de propósito feio: `E2E_CONTEXTO_NAO_DESCARTAVEL=<o próprio contexto>`.

Precisa do cluster com a plataforma **no overlay `kind-ci`** (o orçamento vence em 72 s, a primeira recusa do provedor encerra a cobrança, o `prazos` do Billing roda a cada 5 s e o rate limit da borda é multiplicado por 10) e das `main` dos três serviços, o OS já com o `notificador`: sem ele o e-mail com o link de decisão nunca chega. A sessão confere esses valores no começo e diz o que mudar, e recusa um cluster com mensagem em alguma das três DLQs: a afirmação de DLQ vazia dos cenários compara com a contagem do início do cenário, e com a sessão exigindo DLQs vazias isso vale como zero num cluster limpo. Também precisa de `uv`, `kubectl` e da porta 443 livre no loopback. O `make e2e` roda os 14 cenários em cerca de 3 min e escreve os relatórios em `reports/e2e`; o `make demo` roda os cenários `@demo` (demonstrações 1 e 2 do vídeo) em cerca de 2 min e escreve em `reports/demo`. Com os repositórios dos serviços ao lado deste:

```bash
make kind-up deploy OVERLAY=kind-ci
scripts/ci/implantar-servicos.sh --overlay kind-ci \
  os-service=../postech-sw-arch-p4-os-service \
  billing-service=../postech-sw-arch-p4-billing-service \
  execution-service=../postech-sw-arch-p4-execution-service
scripts/ci/smoke-servicos.sh
make e2e
make demo
```

Cada alvo apaga e recria a pasta de relatórios, sai com o status do pytest e escreve o `resumo.md` mesmo com cenário reprovado. Para rodar um cenário só, use a tag dele: `uv run --group e2e pytest -c e2e/pytest.ini e2e -m caminho-feliz`. Se o pytest morrer no meio de um cenário de resiliência (a máquina dormiu, `kill -9`), basta rodar de novo: o início da sessão religa o que ficou em 0 réplicas.

| Variável | Para quê | Padrão |
|---|---|---|
| `KUBE_CONTEXT` | contexto do `kubectl` | `kind-pytstop-p4` |
| `E2E_URL` | borda do Kong; o guarda de contexto confere o host e a porta dela | `https://localhost` |
| `E2E_ADMIN_EMAIL` | e-mail do admin semeado | o `ADMIN_EMAIL` do ConfigMap do OS |
| `E2E_RELATORIOS` | pasta dos relatórios | `reports/e2e` |
| `E2E_NARRAR` | `1` imprime cada passo e, depois de cada `Então`, o status da OS (o `make demo` liga) | desligado |
| `E2E_CONTEXTO_NAO_DESCARTAVEL` | escape do guarda de contexto | ausente |

### Como o E2E enxerga o cluster

| Acesso | Para quê |
|---|---|
| Kong em `https://localhost` (443 → NodePort 30443, certificado padrão do Kong) | Todas as chamadas de negócio: `/os`, `/billing` e `/execucao`, como um cliente de fora. A verificação do certificado só se desliga para `localhost`, `127.0.0.1` e `::1`; para outro host, o cliente verifica. |
| `kubectl port-forward` de sessão para `svc/mailpit` (8025), `svc/jaeger` (16686) e `svc/execution-service` (8000) | O e-mail com o link de decisão do orçamento, o trace da saga e o `/metrics` da API da Execução, que o Kong não publica. |
| `kubectl` | A senha do admin (Secret `os-admin`), `scale` para derrubar o consumidor e a API do Billing, `rabbitmqctl list_queues` para as DLQs e `logs` da API do OS. Todo comando tem prazo. |

Os usuários nascem uma vez por sessão: o E2E entra como o admin semeado e registra um atendente e um mecânico, cada um com e-mail e senha aleatórios. O OS limita login e registro a 5 por minuto, e atrás do Kong todo cliente do kind tem o mesmo IP. Por isso o cliente HTTP espera a janela passar quando recebe 429.

**Segredos.** A senha do admin, as senhas geradas e os tokens entram numa máscara e saem como `***`, junto com o token do link de decisão e o `token=` do checkout. A máscara cobre três saídas: as mensagens do próprio E2E; um plugin do pytest, que passa a falha e as seções capturadas por ela antes do terminal, do `junit.xml` e do `cucumber.json`; e o `::add-mask::` do GitHub Actions, emitido numa linha própria e visível ao runner porque o `e2e/pytest.ini` usa `--capture=sys`. O plugin também faz o SIGTERM rodar o teardown (o `kubectl port-forward` não fica órfão).

### Dados, espera e desfazer

- **Cada cenário cria os próprios dados**: cliente com CPF válido gerado (módulo 11) e e-mail único, veículo com placa Mercosul sorteada, preço do serviço e da peça no Billing e estoque na Execução, com códigos `SRV-E2E-<execução>-<n>` e `PEC-E2E-<execução>-<n>`. Nenhum cenário lê o que outro deixou, e o cluster não precisa ser limpo entre execuções.
- **Só se espera por polling com prazo** (`esperar(condição, prazo)`, em [`e2e/apoio/espera.py`](e2e/apoio/espera.py)): nunca `sleep` fixo para "dar tempo". A condição roda ao menos uma vez e uma última no fim do prazo. O erro diz o que faltou e o último valor visto. A única espera em tempo corrido são os 20 s do consumidor parado, e mesmo ela amostra a OS a cada 2 s e reprova se a saga andar.
- **O que um cenário derruba volta no fim do próprio cenário**: `kubectl scale` registra as réplicas originais e restaura no teardown de cada cenário. A sessão tenta restaurar tudo de novo no fim, e o início da sessão religa o que uma execução anterior deixou em 0.

### O que cada tag prova

| Tag | Cenário | O que afirma | Rastreio |
|---|---|---|---|
| `@caminho-feliz` | abertura até a entrega | os 8 status em ordem; saga `concluida`; estoque reservado e depois baixado; a OS fora da fila antes do pagamento; e-mail do orçamento no Mailpit com o mesmo link da OS; trace no Jaeger (busca por `messaging.message.conversation_id` = `ordem_id`) com `os-service`, `billing-service` e `execution-service`, gravado quando duas leituras seguidas trazem o mesmo número de spans; o `X-Request-ID` devolvido pelo Kong na linha de acesso da API do OS, com o `trace_id` entre os traces da OS no Jaeger (a origem do id no Kong é provada por [`scripts/smoke.sh`](scripts/smoke.sh)) | RF-028 a RF-037, RN-027, RNF-056 |
| `@compensacao` | cliente recusa pelo link | `cancelada`, motivo `orcamento_recusado`, só `DescartarDiagnostico`, diagnóstico `DESCARTADO` na Execução | RN-024 |
| `@compensacao` | falta de peça | `ReservaDePecasFalhou`, `CancelarOrcamento` e `DescartarDiagnostico`, nenhum pagamento, estoque intacto, motivo `reserva_falhou` | RN-026 |
| `@compensacao` | pagamento recusado no simulador | reserva liberada, orçamento `CANCELADO`, pagamento `RECUSADO` sem estorno, motivo `pagamento_recusado` | RN-025 |
| `@compensacao @estorno` | cancelamento com a OS paga e na fila | 202 em `compensando`; `CancelarExecucao`, `EstornarPagamento`, `LiberarReserva`, `CancelarOrcamento`, `DescartarDiagnostico` nessa ordem; pagamento `ESTORNADO`; OS fora da fila; e-mail de cancelamento | RN-023, RN-026 |
| `@validacao` | CPF de dígito errado | `POST /clientes` responde 422 `VALOR_INVALIDO`; o acompanhamento público dá o mesmo 404 (corpo igual, fora o `id_requisicao`) para CPF inválido e para CPF inexistente. Que o inválido não chega ao banco é provado nos testes do OS (`TestConsultarAcompanhamento`, em `test_use_cases_os.py`, e `test_documento_invalido_falha_antes_do_banco`, em `test_use_cases_cliente.py`) | RF-028, RF-030 (lição da fase 3) |
| `@ponto-de-nao-retorno` | cancelamento depois do início | 409 `TRANSICAO_STATUS_INVALIDA` ("Cancelamento recusado: execução já iniciada"); a OS segue `em_execucao` | RN-029 |
| `@expiracao` | orçamento vencido (72 s no `kind-ci`) | `OrcamentoExpirado`, `cancelada`, motivo `orcamento_expirado`, só `DescartarDiagnostico` | RN-024 |
| `@resiliencia` | consumidor do Billing em 0 por 20 s | a OS fica em `em_diagnostico` durante os 20 s, segue na volta até `aguardando_aprovacao`, e nenhuma das três DLQs ganha mensagem (amostra por 8 s, porque a contagem das filas quorum atualiza a cada ~5 s) | RNF-055, RN-028 |
| `@resiliencia` | API do Billing em 0 na conclusão do diagnóstico | duas conclusões dão 503; o indicador (*gauge*) `pytstop_circuit_breaker_aberto{dependencia="billing"}` vale 1 (lido do Service da Execução; 0,5 é meia-abertura e 0, fechado); com o Billing de volta, o teste espera o circuito sair do aberto, que dura 30 s ([RFC-004, 6.1](docs/arquitetura/rfc/fase4/rfc-004-microsservicos-saga.md#61-rotas-por-serviço) e [10.3](docs/arquitetura/rfc/fase4/rfc-004-microsservicos-saga.md#103-parâmetros-e-variáveis-de-ambiente)); a conclusão passa e o indicador volta a 0 | RNF-034, RNF-055 |
| `@borda` | Swagger pelo Kong | `/os/docs`, `/billing/docs` e `/execucao/docs` abrem e o `openapi.json` declara `servers: [{url: "/<prefixo>"}]` | ADR-038 |
| `@borda` | métricas das OS pela borda | `GET /os/api/v1/ordens-de-servico/metricas` sem token responde 401; com o admin, 200 com `total`, `por_status` (os nove status, zero onde não há OS) e `tempo_medio_por_status_segundos`, o cálculo que os gauges do painel "Tempo médio por status" leem | RF-027 da fase 3, ADR-039 |

As mensagens de erro de negócio se afirmam pelo código (`TRANSICAO_STATUS_INVALIDA`) e, quando o texto aparece, sem depender de acento ou de caixa. As compensações se afirmam pela ordem dos comandos nos passos da saga (`GET /os/api/v1/sagas/{id}`, só do admin), não pelo texto livre do histórico.

### Relatórios

`reports/e2e/` (pasta ignorada pelo git):

| Arquivo | Conteúdo |
|---|---|
| `junit.xml`, `cucumber.json` | Resultado de cada cenário e passo, nos formatos nativos do `pytest-bdd`. O `junit.xml` traz o nome da máquina: na evidência da entrega, anexe o `resumo.md` |
| `resumo.md` | Uma linha por cenário: tags, resultado, duração, `ordem_id` (= `correlation_id` da saga) e `trace_id`; também vai para o `$GITHUB_STEP_SUMMARY` |
| `cenarios.json` | O `ordem_id` e o `trace_id` que cada cenário registrou |
| `trace-<trace_id>.json` | O trace do caminho feliz, como o Jaeger o serve em `/api/traces/<id>` (o Jaeger guarda em memória e perde tudo ao reiniciar) |

### Demonstrações 1 e 2 do vídeo (`make demo`)

O `make demo` reaproveita os cenários marcados `@demo` e as mesmas fixtures. A **demonstração 1** é o fluxo completo (`@bloco-1`, até 4 min). A **demonstração 2** são as falhas (`@bloco-2`, até 4 min): reserva sem saldo, cancelamento com estorno, 409 depois do início, consumidor parado e API do Billing parada. Imprime cada passo e, depois de cada `Então`, o status e a etapa da OS (depois de um `Quando` assíncrono o status ainda seria o de antes), e no fim o tempo de cada bloco:

```text
=== A OS percorre os três serviços da abertura à entrega (@bloco-1 @caminho-feliz @demo)
  Quando o atendente abre uma OS para o veículo do cliente
  Então a OS fica com status "recebida"
      -> OS 64db2c4d: status=recebida etapa=aguardando_diagnostico
```

Ficam de fora a demonstração do deploy com testes e a do monitoramento (Jaeger, Grafana e Loki), que não são do E2E.

### Painéis de negócio com série

Com todos os cenários verdes, o `make e2e` confere ainda que cada consulta de painel de negócio devolve série no Prometheus do kind ([`e2e/apoio/paineis.py`](e2e/apoio/paineis.py)): o `expr` de cada alvo dos quatro [dashboards de negócio](observabilidade/negocio.md) roda em `/api/v1/query` (com `$__range` em 1h e `$__rate_interval` em 5m), e a que volta vazia ou com erro reprova, porque um nome de métrica trocado ou um rótulo errado deixaria vazio justamente o painel que a banca pediu. A tabela sai em `reports/e2e/paineis.md` e no resumo do job; os painéis técnicos e os alertas entram nela, mas não reprovam. O E2E alimenta até as duas séries esparsas da Execução (tempo de execução por serviço e peças em falta): um cenário finaliza uma execução e outro recusa a reserva por falta de peça. `make paineis` repete só essa conferência, sem o E2E (por exemplo depois do `make demo`), em qualquer cluster com o Prometheus da plataforma.

### Testes do código auxiliar

O que o E2E tem de crítico e não precisa de cluster está em [`e2e/apoio/`](e2e/apoio) e é testado por [`tests/e2e_apoio/`](tests/e2e_apoio), um arquivo por módulo, no `make test` e no CI, com cobertura de linhas e ramos. São a espera e seu prazo, a máscara de segredos e o plugin que a aplica ao relatório, o guarda de contexto e a conferência prévia do overlay (`preflight.py`), `Credenciais`, o parser do Mailpit e do Jaeger, as métricas e as DLQs, o desfazer do `kubectl scale`, o port-forward, o cliente HTTP e o resumo. Quatorze testes rodam o pytest do E2E num subprocesso, com um `kubectl` e um `docker` falsos: a captura do `::add-mask::`, o relatório da falha sem credencial, o SIGTERM, o guarda de contexto e de borda, e as ligações do `conftest.py` (o que uma execução anterior deixou em zero é religado no começo, o que um cenário derrubou volta antes do seguinte e a sessão devolve tudo no fim, e overlay fora do `kind-ci` ou DLQ com mensagem param antes do primeiro `scale`).

O `make test` também coleta o E2E sem cluster (`pytest --collect-only` e `--generate-missing`): import quebrado, tag sem marker e step sem definição reprovam no CI, e não no primeiro `make e2e`. O `conftest.py`, os steps e o cliente dos serviços só rodam contra o cluster e ficam fora da cobertura. `ruff`, `mypy` e `bandit` cobrem tudo em `e2e/`.

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

Propriedades AMQP: `message_id` = `id`, `correlation_id`, `type` = `tipo`, `user_id` (o usuário do serviço que publica), `content_type=application/json`, `delivery_mode=2` e os headers `traceparent`/`tracestate` (W3C Trace Context), mais `x-tentativa` nas republicações. `correlation_id` é o id da OS (ordem de serviço, a instância da saga); fora da saga, o id do agregado tratado (`AnonimizarVeiculo`: `veiculo_id`). `causation_id` é o `id` da mensagem que causou esta, e evento nunca vai com `null`: a regra está na [RFC-004, seção 5.2](docs/arquitetura/rfc/fase4/rfc-004-microsservicos-saga.md#52-envelope) e na descrição do campo em `envelope.schema.json`. Os exemplos seguem a regra, e um teste confere que cada evento aponta o comando de origem previsto na RFC e que cada comando aponta um evento ou fica `null`.

Regras que os schemas impõem:

- Routing key `comando.<serviço de destino>.<ação>` ou `evento.<serviço de origem>.<fato>`, com o nome da mensagem em snake_case: `GerarOrcamento` vai em `comando.billing.gerar_orcamento`, `PecasReservadas` em `evento.execucao.pecas_reservadas`.
- Valor monetário em string decimal com duas casas e até 10 dígitos inteiros (`"820.00"`, no máximo `"9999999999.99"`) e `moeda: "BRL"`; número em ponto flutuante é rejeitado.
- Data e hora em RFC 3339 e em UTC (`Z` ou `+00:00`).
- Ids (`ordem_id`, `veiculo_id`, `orcamento_id`, `pagamento_id`, `reserva_id`, `mecanico_id`, `decidido_por`) são UUID; placa normalizada sem hífen (`ABC1234` ou `ABC1D23`).
- `codigo` de serviço e `sku` de peça nos orçamentos e nos eventos: até 50 caracteres entre letras, dígitos, `.`, `_` e `-`, começando por letra ou dígito. O `sku` do comando `ReservarPecas` é mais estrito, o formato do Billing e da Execução: letras maiúsculas e dígitos separados por hífens, até 50 caracteres (`PEC-OLEO-5W30`). `quantidade` de 1 a 1000, e cada lista com no máximo 50 itens.
- Todo `pattern` termina em `(?![\s\S])`, e não em `$`: o `$` do `re.search` do Python casa também antes de um `\n` final, e o validador dos serviços aceitaria `"2026-10-06T12:00:00Z\n"`. O `format: date-time` do FormatChecker tem o mesmo defeito, então só o fim de texto do `pattern` rejeita.
- Diagnóstico concluído, pedido de orçamento e orçamento gerado têm ao menos um item; `ReservarPecas` e `ExecucaoFinalizada` aceitam lista vazia (orçamento só de serviços).
- `prioridade` do `AgendarExecucao`: `normal` (padrão) ou `alta`; a fila de execução atende `alta` antes e, dentro da mesma prioridade, por ordem de agendamento.
- `motivo` dos cinco comandos de compensação é um código da enumeração de `pytstop_saga_compensacoes_total` (`orcamento_recusado`, `orcamento_expirado`, `geracao_falhou`, `reserva_falhou`, `pagamento_recusado`, `pagamento_expirado`, `cancelamento`, `prazo_tecnico`); o texto que o atendente escreve fica só na OS. Texto livre (até 500 caracteres) só nos eventos de falha, e nunca vai para log.
- `CancelarOrcamento` e `EstornarPagamento` vão sem `orcamento_id` ou `pagamento_id` quando o passo estava em voo; o participante localiza o recurso pelo `ordem_id`. O estorno usa no provedor a chave de idempotência `estorno-{pagamento_id}`; o `id` da mensagem só deduplica a entrega.
- `PagamentoEstornado` diz o `motivo` (`compensacao` ou `pagamento_apos_encerramento`), e `PagamentoCancelado`, o `cancelado_em`.
- `OrcamentoAprovado` e `OrcamentoRecusado` com `canal=atendente` exigem `decidido_por` (o `sub` do atendente); com `canal=link`, ele não vai.
- `link_decisao` e `checkout_url` são `http` ou `https`, sem usuário na URL, e contêm o token do link: nunca vão para log nem para span.
- Mensagens sem nome, documento nem contato do cliente; a placa só aparece no `SolicitarDiagnostico`.
- Leitor tolerante: o schema aceita campo desconhecido, em qualquer nível, e o consumidor o ignora.

Mudança de contrato começa por um PR aqui. Campo novo opcional mantém a `versao`: atualiza o schema, o exemplo e a tabela da RFC copiada no teste, e o produtor pode enviá-lo antes de os consumidores o conhecerem. Mudança incompatível vira `versao: 2` do tipo, com o consumidor implantado antes do produtor. Cada serviço copia os schemas que produz e consome, e o `asyncapi.yaml`, que traz o usuário AMQP que publica cada tipo (`userId`, de onde o consumidor tira o produtor esperado); e os valida no próprio teste de contrato.

```bash
make test
make lint
```

O `make test` roda os exemplos e os negativos gerados contra os schemas, os campos da RFC, o AsyncAPI, a routing key e a topologia. O `make lint` roda ruff, mypy strict e bandit, mais shellcheck nos scripts e actionlint nos workflows.

A cobertura de linha do `make test` mede só o arquivo de teste. O que protege os schemas é a bateria de negativos gerados de cada exemplo (campo removido, tipo errado, valor fora do domínio, texto gigante, lista vazia), que precisa ser toda rejeitada, mais os testes de fronteira: toda lista vai de 1 a 50 itens (vazia só onde a RFC deixa), cada limite de tamanho, quantidade, valor e formato tem o valor no limite aceito e o seguinte rejeitado, e a regra do `decidido_por` vale nos dois sentidos em `OrcamentoAprovado` e `OrcamentoRecusado`.

## CI

O workflow [`ci.yml`](.github/workflows/ci.yml) roda em pull request para a `main`, sob demanda e quando o CD o chama (`workflow_call`). `manifests`, `contratos` e `gitleaks` são checks obrigatórios do [ruleset da `main`](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-platform/rules/24599837), junto do `deploy-kind` do `cd.yml`; o checkout não guarda a credencial do GitHub (`persist-credentials: false`).

- `manifests`: `make lint-scripts` (shellcheck nos scripts e actionlint nos workflows, inclusive nos `run:`) e `make manifests`, ou seja, os três overlays (`kind`, `kind-ci` e `k3s`) e os três exemplos de borda validados pelo kubeconform (schemas do Kubernetes 1.35, a versão do nó do kind, e o do `KongClusterPlugin` gerado das CRDs do chart; `Secret` reprova, porque senha não entra nos manifests) e pelo `trivy config` (nenhum achado HIGH ou CRITICAL); `docker compose config` com o profile `servicos`; `promtool`, `loki -verify-config` e `promtail -check-syntax` nas configs do cluster e do compose, mais a máscara de token do Promtail (`promtail -dry-run`); a regra de alerta "Saga parada" no `promtool test rules`, com cada condição disparando sozinha; o `k8s/base/kong` igual ao que o `make kong-render` gera; a mesma tag de cada imagem em `k8s/`, no compose e na tabela de versões; e todo dashboard JSON no configMapGenerator.
- `contratos`: `uv lock --check`, `make lint` (ruff, mypy strict e bandit, mais o `lint-scripts`), `make test` (testes de contrato, de observabilidade, dos scripts de segredos, de medição do kind e de implantação e smoke dos serviços e do código auxiliar do E2E, e o `asyncapi.yaml` validado pelo `@asyncapi/cli`) e `make prova-retry` (um RabbitMQ 4.3.6 avulso no Docker do runner, com o `definitions.json`, o `permissoes.json` e o `criar-usuarios.sh` do commit, e a prova do retry como o `billing`: definitions que derrubam o boot ou permissão frouxa reprovam aqui, sem cluster).
- `gitleaks`: o histórico do commit testado (no PR, o merge do PR na `main`; `--log-opts="HEAD"`, para não varrer as branches de outros PRs), com as regras do [`.gitleaks.toml`](.gitleaks.toml), pelo binário com versão e sha256 fixados, como nos repositórios de serviço. Além das regras padrão, uma própria reprova URL AMQP com senha, e a senha de demonstração só passa no compose; o [`testa-gitleaks.sh`](scripts/ci/testa-gitleaks.sh) confere as duas coisas com um manifesto de teste e prova que senha commitada e apagada no commit seguinte ainda reprova. O workflow `gitleaks-semanal.yml` varre todas as refs (`--all`) uma vez por semana, para branch sem PR.

`make check` roda `lint`, `test`, `prova-retry` e `manifests` localmente.

O `make e2e` precisa do cluster com os três serviços e por isso não está no `make check` nem no `ci.yml`; o job `deploy-kind` ainda não o executa.

O workflow [`cd.yml`](.github/workflows/cd.yml) tem o job `deploy-kind` ([Kind no CI](#kind-no-ci-overlay-kind-ci)) e, no push na `main`, o job `ci`, que roda o `ci.yml` no commit que entrou; ali o `deploy-kind` só começa com o CI verde. Os jobs dos dois workflows rodam no runner fixo `ubuntu-24.04`: o `ubuntu-latest` passa para o Ubuntu 26.04 a partir de 19/10/2026. O sistema só muda com commit; as ferramentas que vêm no runner (kubectl, Docker, jq) mudam com a imagem semanal dele, e as que precisam de versão certa vêm pinadas: as imagens do Makefile e, no `deploy-kind`, o kind e o kubectl.

## Decisões e limites

- Kong por `helm template` do chart `kong/kong` 3.4.1 versionado em [`k8s/base/kong/kong.yaml`](k8s/base/kong/kong.yaml): o Kong Ingress Controller 3.x não publica mais os manifests all-in-one. `make kong-render` regenera a partir de [`values.yaml`](k8s/base/kong/values.yaml). O webhook de validação ficou desligado porque o chart gera o certificado dele na renderização, e versionar o resultado poria uma chave privada no repositório.
- Sem o webhook, Ingress ou plugin inválido de um serviço não falha no `kubectl apply`. Para que ele não derrube a configuração dos outros serviços (o Kong sem banco recusa a configuração inteira), o controller roda com o gate `FallbackConfiguration`: tira o objeto com erro e o que depende dele, aplica o resto e registra um evento no objeto. O `make deploy` termina com o `make kong-check`, que falha e lista o objeto recusado; o `make smoke` prova os dois lados com um plugin inválido de propósito.
- Senhas geradas no cluster pelo `make deploy`, no primeiro deploy de cada cluster ([Segredos gerados](#segredos-gerados), [ADR-042](docs/arquitetura/adr/fase4/042-cicd-e-deploy-kubernetes.md)). Os valores de demonstração ficam só no compose, marcados com `gitleaks:allow` e na allowlist do [`.gitleaks.toml`](.gitleaks.toml), que só os aceita em `compose/`; o `make manifests` reprova `Secret` nos manifests, e o gitleaks, URL AMQP com senha fora do compose.
- Pods endurecidos: todos rodam sem root, sem escalar privilégio, sem capability, com seccomp `RuntimeDefault` e raiz somente leitura (`emptyDir` com `sizeLimit` onde a imagem grava). A exceção é o Promtail, que roda como root para ler os arquivos `0640` de `/var/log/pods` por `hostPath`, ainda sem capability. Só montam token de ServiceAccount os pods que falam com a API do Kubernetes: Prometheus, Promtail, kube-state-metrics e o controller do Kong. O namespace tem Pod Security `restricted` em `warn` e `audit`; o `make smoke` mostra o contexto efetivo de cada container e que, com `enforce`, só o Promtail ficaria de fora. O `make manifests` roda `trivy config` (HIGH e CRITICAL) nos três overlays e nos exemplos de borda.
- O controller do Kong lê Ingress, Services e Secrets só dos quatro namespaces da fase 4 (`watchNamespaces`), com uma Role em cada um, em vez de ler os Secrets do cluster inteiro. Por isso o `make deploy` cria vazios os namespaces dos serviços que ainda não existem; o repositório de cada serviço continua dono do namespace dele. Ingress de outro namespace não chega ao Kong. Risco que sobra, aceito: o controller roda no pod exposto à internet (`kong-proxy`) e a Role de cada um dos quatro namespaces ainda lhe dá `list` e `watch` em todos os Secrets deles: os da plataforma (o `rabbitmq-credenciais`, com as senhas do admin do broker e dos três usuários, e o `grafana-admin`) e os dos serviços ([Segredos gerados](#segredos-gerados): a chave RSA do JWT, a `ENCRYPTION_KEY` dos dados pessoais, as senhas dos bancos e do admin semeado, o keyfile do MongoDB, a `ORCAMENTO_LINK_SECRET`, a URL do broker e, no k3s, as credenciais do Mercado Pago); quem tomasse o controle desse pod os leria. A plataforma não referencia Secret em Ingress nem em plugin, e uma saída a avaliar é tirar a regra de Secrets das Roles, se o controller subir sem ela (dívida no MEMORY).
- O admin do RabbitMQ entra no boot junto com a topologia (arquivo `admin.json` do Secret), porque com definitions no boot o broker não cria usuário nenhum e o Job de usuários precisa de alguém para falar com a API.
- `pytstop.retry` é topic, com bindings de chave exata ([ADR-036](docs/arquitetura/adr/fase4/036-mensageria-rabbitmq.md)): o RabbitMQ só aplica permissão por routing key em exchange topic, e sem ela a escrita no `pytstop.retry` deixaria qualquer serviço pôr mensagem na fila de trabalho de outro. Com a chave exata (o nome da fila de retry), o roteamento é o mesmo de um direct.
- Uma fila de retry por atraso, `<fila>.retry.1s` a `.300s` ([ADR-036](docs/arquitetura/adr/fase4/036-mensageria-rabbitmq.md)): são 21 filas no broker, e mudar um atraso é criar outra fila.
- Versões de Prometheus, Grafana e Loki iguais às da fase 3. Jaeger na última 1.x: a 2.x troca a configuração pelo formato do OpenTelemetry Collector.
- CVEs conhecidas nas imagens (trivy, HIGH e CRITICAL com correção publicada, out/2026): Prometheus v2.54.1 (96 e 6), Loki 2.9.8 (53 e 3) e kube-state-metrics v2.13.0 (44 e 1) não têm versão de correção na própria linha (o Loki 2.9.17 tem mais achados, e o Prometheus 2.55.1 tira só quatro) e ficam como estão: rodam só dentro do cluster, sem Ingress, e o acesso de fora é por port-forward ou túnel. Sair delas é trocar de linha (Prometheus 3, Loki 3, kube-state-metrics 2.17), com mudança de configuração. O Mailpit subiu para v1.31.4, sem achado HIGH. Os exporters dos bancos, nas últimas versões publicadas, têm só achados HIGH com correção fora deles (postgres_exporter v0.20.1: 12; mongodb_exporter 0.53.0: 21), todos na biblioteca padrão do Go, em `golang.org/x` e no gRPC compilados no binário, que só um release novo do exporter troca: rodam como sidecar do banco, e a NetworkPolicy de cada serviço deixa só o Prometheus chegar à porta de métricas.
- Sem persistência em Loki e Grafana (o estado do Grafana vem todo do provisioning). Têm volume o RabbitMQ e, nos overlays `kind` e `k3s`, o Prometheus: 15 dias num PVC de 2Gi, no máximo 1536MB de séries ([Retenção e prazos](observabilidade/README.md#retenção-e-prazos), [ADR-042](docs/arquitetura/adr/fase4/042-cicd-e-deploy-kubernetes.md)). No `kind-ci` e no compose o Prometheus segue num emptyDir, com 2 dias e no máximo 1 GB. Cada emptyDir tem teto (`sizeLimit`) para não encher o disco do nó, que no k3s guarda também os volumes do broker, do Prometheus e dos bancos, e o Loki apaga os logs com mais de 7 dias (compactor com retenção).
