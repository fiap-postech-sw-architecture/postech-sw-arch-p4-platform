# Ensaio integrado no kind: plataforma e os três serviços

> [↑ Raiz do projeto](../../README.md)

Registro do ensaio de 14/10/2026: a plataforma e os três serviços **reais** (a `main` de cada repositório) no mesmo cluster kind, com os scripts de implantação e de smoke do [Contrato com os serviços](../../README.md#contrato-com-os-serviços), e a memória e a CPU de cada pod medidas contra o orçamento do [ADR-042](../arquitetura/adr/fase4/042-cicd-e-deploy-kubernetes.md). Na época do ensaio, o OS Service ainda não tinha os processos `prazos` e `notificador` na `main`; a medida deles, feita com as branches então abertas, está em [Medida adicional](#medida-adicional-prazos-e-notificador-do-os-service). Os dois já entraram na `main` do OS Service (b310889 e 593471d): o que mudou nos repositórios desde o ensaio está em [Depois do ensaio](#depois-do-ensaio).

## Termos

| Termo | Neste registro |
|---|---|
| `kind-ci` e `kind` | Os dois overlays da plataforma. O `kind-ci` é o do CD: sem Loki, Promtail e Grafana, com uma réplica por Deployment. O `kind` é o de quem desenvolve, com os três |
| Working set | A memória que o kubelet conta para despejar um pod: o uso total menos o cache de arquivos inativo |
| `memory.peak` | O maior uso do cgroup do nó desde que ele existe, com o cache de arquivos que o kernel devolve sob pressão |
| HPA | O autoescalonamento horizontal da API (1 a 1 no `kind-ci` e 1 a 2 no `kind`) |
| DLQ | A fila de mensagens mortas de cada fila de trabalho do RabbitMQ |
| JWKS | As chaves públicas do OS Service, com que o Billing e a Execução validam o token |
| Smoke | As provas rápidas depois do deploy: o `make smoke` da plataforma e o `smoke-servicos.sh` dos serviços |

## Resultado

- Os três serviços subiram na primeira tentativa, nos dois overlays (`kind-ci` e `kind`): 13 pods prontos (10 processos e 3 bancos), 3 Jobs de inicialização completos, nenhum reinício de container.
- O `make smoke` da plataforma passou antes dos serviços (nos dois overlays) e o [`smoke-servicos.sh`](../../scripts/ci/smoke-servicos.sh) passou nos três namespaces: 35 etapas `ok`, nenhuma `FAILED`, incluindo `pg_up` e `mongodb_up` em 1 lidos do Prometheus, o Swagger sob o prefixo de cada serviço e a NetworkPolicy barrando o `rabbitmq-0` em cada banco. É o smoke de `aaca05c`; o que mudou desde então está em [Depois do ensaio](#depois-do-ensaio).
- Memória, uso contra reserva: os 13 pods usam 0,84 GiB em repouso (0,94 GiB somando os maiores valores amostrados), contra 2,2 GiB de requests. O nó do kind inteiro (control plane, plataforma e serviços) fica em 3,1 GiB de working set no `kind-ci`, com pico de cgroup de 5,35 GiB, nos 16 GB do runner. Contra os 3,3 a 3,4 GiB de requests do orçamento a folga é de só 6% a 9%, mas essa conta compara o uso do nó, que inclui o control plane e o metrics-server (fora do orçamento), com a reserva dos pods; a conclusão se apoia nos pods e no limite do runner.
- CPU: o nó usou 0,3 CPU em repouso, e nenhum pod de serviço passou de 20% dos limits de CPU nas amostras de 5 s (o maior foi o consumidor do OS, com 40m de 250m).
- Só um defeito apareceu, no próprio `platform`: o ruído `Defaulted container` do `kubectl exec` na saída do smoke, corrigido no PR #12. As observações sobre os serviços, com a situação de cada uma em 14/10, estão em [Observações do ensaio](#observações-do-ensaio-situação-em-1410).
- Fora do ensaio: nenhuma saga, mensagem de negócio, carga, e-mail ou chamada ao Mercado Pago rodou. O ensaio provou que tudo sobe, conecta e aparece na borda, no Prometheus e na NetworkPolicy; o fluxo de negócio é assunto do teste de ponta a ponta do `platform` #13, ainda aberto.

## Depois do ensaio

O ensaio rodou na madrugada de 14/10/2026 (horário de Brasília), com a plataforma em `aaca05c` e os serviços nos commits da tabela de [Ambiente e versões](#ambiente-e-versões). Desde então a `main` de vários repositórios andou; a tabela diz o que isso muda neste registro.

| Mudança depois do ensaio | Efeito neste registro |
|---|---|
| `platform` #11 (`11480bb`): smoke, runbook, ADRs, RFC e contratos | A saída do smoke citada é a de `aaca05c`. Desde o #11, as linhas de `/metrics` e de `/api/v1/admin/outbox` saem `ok: 404 (Kong, not published)` e `ok: 404 (Kong fora-da-borda)`, e só passam se o corpo da resposta for o do Kong. O #11 também trocou a regra de alerta "Saga parada" (duas condições novas). Nenhuma das duas mudanças foi exercitada com os serviços reais neste ensaio |
| OS Service #9 (`b310889`, `notificador`) e #10 (`593471d`, `prazos`) | Já estão na `main` do OS Service. A [medida adicional](#medida-adicional-prazos-e-notificador-do-os-service) foi feita com as branches e vale como estimativa até ser repetida sobre a `main` |
| Billing #6 (`264da4e`) e Execution #6 (`d04fd81`) | Corrigem o aviso de telemetria do FastAPI nas duas APIs; o Billing #6 também corta o volume de log do `mongod` e adota os nomes de variável do `make kind-deploy` que a Execução já usava. Detalhe em [Observações do ensaio](#observações-do-ensaio-situação-em-1410) |
| OS Service #11 (aberto) | Unifica os nomes das variáveis do `make kind-deploy` no OS (`PLATFORM` vira alias de `PLATFORM_DIR`) |
| `platform` #13 (aberto) | Traz o teste de ponta a ponta da saga (ADR-041); até o merge, nenhum teste de saga roda contra o kind |

Antes de fechar a fase, o ensaio deve ser repetido sobre as `main` de hoje: `smoke-servicos.sh` nos três serviços (com a prova nova do corte pelo Kong) e as regras de alerta com serviços de pé.

## Ambiente e versões

| Item | Valor |
|---|---|
| Máquina | macOS em Apple Silicon (arm64), Docker 29.2.1 no Colima com 8 CPU e 13,6 GiB de memória, dividido com outros containers |
| kind e kubectl | kind 0.32.0 (o CD fixa a 0.31.0) e kubectl 1.36.2 (o CD fixa a 1.35.9); nó `kindest/node:v1.35.0` do [`kind/cluster.yaml`](../../kind/cluster.yaml), Kubernetes 1.35.0 |
| Plataforma | `main` do `platform` em `aaca05c` |
| OS Service | `main` em `fda0672` |
| Billing Service | `main` em `0fed78b` |
| Execution Service | `main` em `0c34ed7` |
| Imagens de terceiros | as da [tabela de versões](../../README.md#componentes-e-versões): `postgres:16.15`, `mongo:7.0.43`, `prometheuscommunity/postgres-exporter:v0.20.1`, `percona/mongodb_exporter:0.53.0`, `rabbitmq:4.3.6-management`, `kong:3.9.3`, entre outras |
| Imagens dos serviços | `docker build` do checkout de cada `main`, com o commit como tag (`pytstop-<serviço>:<commit>`), 357 a 437 MB cada (`docker images`, em [Provas avulsas](ensaio-integrado-medidas.md#provas-avulsas)) |

Os números abaixo vêm de uma máquina arm64 com as imagens de terceiros e as camadas do `docker build` já em cache. O runner do CD é amd64, com 4 vCPU e 16 GB, e puxa as imagens a cada job. Por isso:

- os tempos valem como ordem de grandeza: o `kind-up` local (26 s) foi menor que o do runner (39 a 46 s, no ADR-042) e o `make deploy` da plataforma, maior (1 min 34 s contra 50 a 54 s);
- a memória não depende do cache de imagens e deve ficar próxima, mas só o primeiro `deploy-kind` completo dos serviços no runner a confirma (a medição que o ADR-042 pede).

## Comandos usados

Cada execução foi um script único, porque o amostrador do `medir-kind.sh` para quando o shell que marcou a primeira etapa termina, e ele tem de viver até o resumo. Os comandos abaixo supõem os quatro repositórios lado a lado, com o `platform` como diretório atual. No ensaio, os serviços foram construídos de checkouts limpos da `main` de cada um (nos commits da tabela de [Ambiente e versões](#ambiente-e-versões)), e não dos clones de trabalho.

Primeira execução, com o overlay do CD (`kind-ci`) e os três serviços de uma vez:

```bash
export MEDICAO=$(mktemp -d)
scripts/medir-kind.sh etapa kind-up
make kind-up
scripts/medir-kind.sh etapa deploy
make deploy OVERLAY=kind-ci
scripts/medir-kind.sh etapa smoke-plataforma
make smoke OVERLAY=kind-ci
scripts/medir-kind.sh etapa servicos
scripts/ci/implantar-servicos.sh --overlay kind-ci os-service=../postech-sw-arch-p4-os-service billing-service=../postech-sw-arch-p4-billing-service execution-service=../postech-sw-arch-p4-execution-service
scripts/medir-kind.sh etapa smoke-servicos
scripts/ci/smoke-servicos.sh
scripts/medir-kind.sh etapa estavel
sleep 90
kubectl --context kind-pytstop-p4 top pod -A --containers
kubectl --context kind-pytstop-p4 top node
scripts/medir-kind.sh resumo
```

Segunda execução, o caminho de quem desenvolve: overlay `kind` (com Loki, Promtail e Grafana) e o `make kind-deploy` de cada serviço, um por vez. No ensaio, o OS Service ainda chamava a variável do diretório do `platform` de `PLATFORM`; com o OS Service #11 passa a valer `PLATFORM_DIR` nos três, e `PLATFORM` segue como alias.

```bash
export MEDICAO=$(mktemp -d)
scripts/medir-kind.sh etapa kind-up
make kind-up
scripts/medir-kind.sh etapa deploy
make deploy
scripts/medir-kind.sh etapa smoke-plataforma
make smoke
scripts/medir-kind.sh etapa kind-deploy-os-service
make -C ../postech-sw-arch-p4-os-service kind-deploy PLATFORM=$PWD
scripts/medir-kind.sh etapa kind-deploy-billing-service
make -C ../postech-sw-arch-p4-billing-service kind-deploy PLATFORM_DIR=$PWD
scripts/medir-kind.sh etapa kind-deploy-execution-service
make -C ../postech-sw-arch-p4-execution-service kind-deploy PLATFORM_DIR=$PWD
scripts/medir-kind.sh etapa smoke-servicos
scripts/ci/smoke-servicos.sh
scripts/medir-kind.sh etapa estavel
sleep 90
kubectl --context kind-pytstop-p4 top pod -A --containers
kubectl --context kind-pytstop-p4 top node
scripts/medir-kind.sh resumo
```

O `make smoke` roda antes dos serviços porque recusa um cluster que já tem Ingress de serviço (`pytstop-os already has Ingresses: the smoke would reuse its paths`; confirmado no ensaio com os serviços de pé).

### Como cada número foi coletado

O `medir-kind.sh` guarda só a memória de cada pod. A CPU de pico, a divisão por container e a composição da memória do nó vieram de comandos avulsos, listados aqui. As saídas estão em [Medidas cruas do ensaio](ensaio-integrado-medidas.md); nas que vieram de comandos avulsos, a saída foi colada do terminal e não foi gravada em arquivo (marcadas assim em [Provas avulsas](ensaio-integrado-medidas.md#provas-avulsas)).

| Número | De onde veio |
|---|---|
| Duração das etapas, working set do nó (amostra a cada 5 s), `memory.peak` do cgroup do nó e maior memória por pod | `medir-kind.sh resumo`, nas duas execuções |
| Memória e CPU em repouso, por pod e por container (como `postgres 37` e `exporter 6`) | `kubectl top pod -A --containers` e `kubectl top node`, lidos 90 s depois do smoke dos serviços; a divisão por container é da primeira execução |
| Pico de CPU por pod, e a memória da mesma amostra | O laço de amostragem abaixo, na segunda execução, de `kind-up` ao resumo; o `kubectl top` dá a média de uma janela de cerca de 15 s, então picos mais curtos não aparecem |
| Composição do working set do nó | O `docker exec` da `memory.stat` abaixo, na primeira execução |
| Requests e limits | `kubectl get pods -A -o custom-columns=...`, abaixo |
| Duração dos Jobs | `status.completionTime` menos `status.startTime` de `kubectl get job -A -o json`, na segunda execução; saída colada do terminal |
| Tempos dentro do `implantar-servicos.sh` | Carimbo de hora em cada linha da saída do script |

O laço de amostragem do pico de CPU, rodando em segundo plano durante a segunda execução, e a conta do maior valor por pod:

```bash
while true; do kubectl --context kind-pytstop-p4 top pod -A --no-headers | awk -v d=$(date +%s) '{print d, $1 "/" $2, $3 + 0, $4 + 0}' >> amostras.txt; sleep 5; done
awk '{ if ($3 > cpu[$2]) cpu[$2] = $3; if ($4 > mem[$2]) mem[$2] = $4 } END { for (p in cpu) printf "%s %d %d\n", p, cpu[p], mem[p] }' amostras.txt | sort -k2,2nr
```

A composição do working set do nó e os requests e limits de cada container:

```bash
docker exec pytstop-p4-control-plane sh -c 'cat /sys/fs/cgroup/memory.peak /sys/fs/cgroup/memory.current; grep -E "^(anon|file|inactive_file|active_file) " /sys/fs/cgroup/memory.stat'
kubectl --context kind-pytstop-p4 get pods -A -o custom-columns='NS:.metadata.namespace,POD:.metadata.name,CONT:.spec.containers[*].name,CPUREQ:.spec.containers[*].resources.requests.cpu,CPULIM:.spec.containers[*].resources.limits.cpu,MEMREQ:.spec.containers[*].resources.requests.memory,MEMLIM:.spec.containers[*].resources.limits.memory'
```

## O que subiu

Estado depois do `smoke-servicos.sh`, na primeira execução (`kind-ci`):

| Namespace | Pods prontos | Job de inicialização |
|---|---|---|
| `pytstop-os` | `os-service-api`, `os-service-relay`, `os-service-consumidor`, `os-postgres-0` (postgres e exporter) | `os-migracao` completo |
| `pytstop-billing` | `billing-service-api`, `-relay`, `-consumidor`, `-prazos`, `billing-mongo-0` (mongo e exporter) | `billing-inicializacao` completo |
| `pytstop-execucao` | `execution-service-api`, `-relay`, `-consumidor`, `execucao-postgres-0` (postgres e exporter) | `execucao-migracao` completo |
| `pytstop-plataforma` | Kong, RabbitMQ, Prometheus, Jaeger, Mailpit, kube-state-metrics (mais Loki, Promtail e Grafana no overlay `kind`) | `rabbitmq-usuarios` completo |

HPA da API: 1 a 1 no `kind-ci` e 1 a 2 no `kind`, como no [ADR-042](../arquitetura/adr/fase4/042-cicd-e-deploy-kubernetes.md). No RabbitMQ, as filas `os.eventos`, `billing.comandos` e `execucao.comandos` tinham um consumidor cada, e as três DLQs estavam vazias.

Saída do `smoke-servicos.sh` na primeira execução, na versão de `aaca05c`. O bloco omite as três linhas `Defaulted container "api" out of: ...` que o `kubectl exec` escrevia então (a saída completa está em [Medidas cruas](ensaio-integrado-medidas.md)). Desde o `platform` #11, as linhas de `/metrics` e de `/api/v1/admin/outbox` saem `ok: 404 (Kong, not published)` e `ok: 404 (Kong fora-da-borda)`, porque o smoke passou a conferir também o corpo da resposta; as demais linhas não mudaram.

```text
os-service         initialization Job         ok: os-migracao=true
os-service         rollouts                   ok: 4 ready
os-service         GET /os/api/v1/saude       ok: 200
os-service         GET /os/metrics            ok: 404
os-service         GET /os/api/v1/admin/outbox ok: 404
os-service         GET /os/docs               ok: 200
os-service         GET /os/openapi.json       ok: 200
os-service         up = 1 in Prometheus       ok: 4 pods
os-service         pg_up = 1 in Prometheus    ok: os-postgres-0
os-service         os-postgres-0 127.0.0.1 asks for a password ok: postgres on 127.0.0.1 without a password was refused
os-service         os-service-api pod -> os-postgres.pytstop-os.svc.cluster.local:5432 ok: connected (the namespace itself reaches the database)
os-service         rabbitmq-0 -> os-postgres.pytstop-os.svc.cluster.local:5432 ok: blocked (connection timed out)
billing-service    initialization Job         ok: billing-inicializacao=true
billing-service    rollouts                   ok: 5 ready
billing-service    GET /billing/api/v1/saude  ok: 200
billing-service    GET /billing/metrics       ok: 404
billing-service    GET /billing/api/v1/admin/outbox ok: 404
billing-service    GET /billing/docs          ok: 200
billing-service    GET /billing/openapi.json  ok: 200
billing-service    up = 1 in Prometheus       ok: 5 pods
billing-service    mongodb_up = 1 in Prometheus ok: billing-mongo-0
billing-service    billing-service-api pod -> billing-mongo.pytstop-billing.svc.cluster.local:27017 ok: connected (the namespace itself reaches the database)
billing-service    rabbitmq-0 -> billing-mongo.pytstop-billing.svc.cluster.local:27017 ok: blocked (connection timed out)
execution-service  initialization Job         ok: execucao-migracao=true
execution-service  rollouts                   ok: 4 ready
execution-service  GET /execucao/api/v1/saude ok: 200
execution-service  GET /execucao/metrics      ok: 404
execution-service  GET /execucao/api/v1/admin/outbox ok: 404
execution-service  GET /execucao/docs         ok: 200
execution-service  GET /execucao/openapi.json ok: 200
execution-service  up = 1 in Prometheus       ok: 4 pods
execution-service  pg_up = 1 in Prometheus    ok: execucao-postgres-0
execution-service  execucao-postgres-0 127.0.0.1 asks for a password ok: postgres on 127.0.0.1 without a password was refused
execution-service  execution-service-api pod -> execucao-postgres.pytstop-execucao.svc.cluster.local:5432 ok: connected (the namespace itself reaches the database)
execution-service  rabbitmq-0 -> execucao-postgres.pytstop-execucao.svc.cluster.local:5432 ok: blocked (connection timed out)
services smoke OK: os-service billing-service execution-service
```

A segunda execução (overlay `kind`) produziu a mesma tabela, com os mesmos 35 `ok`. O `make smoke` da plataforma terminou com `smoke OK: every check held` nos dois overlays (no `kind-ci`, com duas famílias de provas puladas por design: Loki e Promtail, e Grafana); as linhas finais estão em [Provas avulsas](ensaio-integrado-medidas.md#provas-avulsas). No overlay `kind`, as oito regras de alerta do Grafana ficaram `inactive` e `ok` com os serviços de pé, e o Loki recebeu os logs dos três namespaces.

### Provas além do smoke

Feitas com comandos avulsos depois do smoke; as saídas estão em [Medidas cruas](ensaio-integrado-medidas.md#provas-avulsas).

| Prova | Resultado |
|---|---|
| Swagger sob o prefixo | `/os/docs`, `/billing/docs` e `/execucao/docs` apontam para `/<prefixo>/openapi.json`, e o `openapi.json` de cada um declara `servers: [{url: "/<prefixo>"}]` (o `--root-path` chegou ao uvicorn) |
| Login e JWKS entre namespaces | `POST /os/api/v1/autenticacao/login` do admin semeado devolve 200; o token é aceito pela listagem de clientes do OS, de preços do Billing e de estoque da Execução (200 nas três), e a chamada ao Billing sem token dá 401. O Billing e a Execução validam o token contra o JWKS do OS pela NetworkPolicy |
| NetworkPolicy entre serviços | da Execução para o Billing (validação de preços) e para o OS (JWKS): conecta; do Billing para a Execução, do OS para o Billing e do OS para o banco da Execução: esgota o prazo de 3 s |
| Segundo `make deploy` com os serviços de pé | 17 s; os 12 Secrets `Opaque` dos quatro namespaces ficam com o mesmo conteúdo (comparação por hash, sem imprimir valor); `kong-check` limpo (linha final em [Provas avulsas](ensaio-integrado-medidas.md#provas-avulsas)) |
| Segundo `implantar-servicos.sh` (mesmo commit) | 13 s: os Jobs são apagados e recriados, as migrações e a semente repetem sem erro, os Deployments seguem como estavam (mesma tag, mesmo template); o smoke dos serviços passa em 11 s |
| Broker reiniciado com os serviços de pé | `kubectl delete pod rabbitmq-0`: o broker volta em 13 s, os três consumidores voltam em 30 s, o relay do Billing registra `broker_unavailable` e depois `broker_connected`, e nenhum pod de serviço reinicia |
| Alvos do Prometheus | nenhum alvo ativo fora de `up` (a consulta por `health != up` voltou vazia); 4 pods no OS, 5 no Billing e 4 na Execução em `up = 1`, na primeira execução; saída colada do terminal |
| Traces | depois de chamadas pela borda, o Jaeger listou `os-service`; Billing e Execução não apareceram, porque as APIs deles não exportam spans (ver [Observações do ensaio](#observações-do-ensaio-situação-em-1410)) e nenhuma mensagem circulou pelos relays e consumidores. O teste de ponta a ponta da saga (ADR-041), que exercitaria os três traces, ainda não existe na `main`: está no `platform` #13, aberto |

## Tempos

Medidos pelo [`medir-kind.sh`](../../scripts/medir-kind.sh) e pelo carimbo de hora de cada saída.

| Etapa | `kind-ci`, os três de uma vez | `kind`, um `make kind-deploy` por serviço |
|---|---|---|
| `make kind-up` | 26 s | 26 s |
| `make deploy` da plataforma | 1 min 34 s | 1 min 45 s |
| `make smoke` da plataforma | 1 min 46 s | 2 min 14 s |
| Serviços | 1 min 27 s | OS 34 s, Billing 46 s, Execução 17 s (sequenciais) |
| `smoke-servicos.sh` | 21 s | 21 s |
| Espera de 90 s e fotografia do estado estável | 1 min 32 s | 1 min 31 s |
| Total | 7 min 06 s | 7 min 54 s |

Dentro do `implantar-servicos.sh` da primeira execução (1 min 27 s):

- os três `docker build`, em paralelo: 13 s, com as camadas em cache;
- o `kind load` das três imagens: 8 s;
- do `apply` ao último Deployment pronto: 65 s;
- o StatefulSet do banco ficou pronto 47 s (Execução), 50 s (Billing) e 52 s (OS) depois do `apply`;
- os Jobs, medidos na segunda execução (saída colada do terminal, em [Provas avulsas](ensaio-integrado-medidas.md#provas-avulsas)), duraram 12 s (`execucao-migracao`), 28 s (`os-migracao`) e 36 s (`billing-inicializacao`, que também inicia o replica set);
- os Deployments esperam o Job pelo `aguarda-migracao` (OS e Execução) e pelo `aguarda-banco` (Billing).

Para comparar, o [ADR-042](../arquitetura/adr/fase4/042-cicd-e-deploy-kubernetes.md) mediu no runner, só com a plataforma, 39 a 46 s de `kind-up`, 50 a 54 s de deploy e 1 min 40 s a 1 min 47 s de smoke; aqui foram 26 s, 1 min 34 s e 1 min 46 s. O deploy local ficou mais lento que o do runner porque a máquina dividia o Docker com outros containers.

## Memória e CPU

### O nó

| | `kind-ci` | `kind` |
|---|---|---|
| Working set do nó, maior valor amostrado a cada 5 s | 3.164 MiB | 3.447 MiB |
| `kubectl top node` em repouso | 3.147 MiB (22%), 299 m | 3.362 MiB (24%), 351 m |
| `memory.peak` do cgroup do nó (conta o cache de arquivos, que o kernel devolve sob pressão) | 5.476 MiB | 6.738 MiB |

Para comparar, o ADR-042 mediu, só com a plataforma e no runner, working set de até 1,5 GiB e pico de 3,5 GiB no cgroup. Aqui, com os três serviços e em arm64 local, o working set subiu 1,6 GiB (para 3,1) e o pico, 1,9 GiB (para 5,35). Os 13 pods dos serviços somam 0,84 GiB, a plataforma 0,53 GiB e o control plane cerca de 0,5 GiB, no `kubectl top`: 1,9 GiB no total. O resto do working set do nó, cerca de 1,1 GiB, não é de pod; a `memory.stat` do nó, lida na primeira execução, divide o working set assim:

| Parcela da `memory.stat` do nó (90 s depois do smoke dos serviços) | MiB |
|---|---|
| `memory.current` | 5.317 |
| menos `inactive_file`, o cache que o kubelet não conta | 2.298 |
| igual ao working set | 3.019 |
| dele, `anon` (memória anônima: pods, containerd, kubelet) | 2.078 |
| dele, `active_file` (cache de arquivos usado há pouco) | 570 |
| dele, outros (kernel, slab, memória compartilhada) | 371 |

A memória anônima do nó passa em cerca de 170 MiB a soma dos pods (conta aproximada, porque o `kubectl top` dos pods inclui parte do cache), o que cabe aos processos do nó fora deles, como o containerd e o kubelet; o cache ativo e o restante respondem pelo resto. O ensaio não mediu o cache por consumidor, então não diz quanto dele é das imagens e dos dados dos bancos. No momento da leitura, o `memory.current` de 5,2 GiB tinha 2,2 GiB de cache inativo, que o kernel devolve sob pressão; o pico de 5,35 GiB não foi decomposto. Nos 16 GB do `ubuntu-24.04` o nó cabe com folga nos dois overlays, mas a comparação com o ADR mistura arm64 local e amd64 do runner.

### Por pod

Memória: o maior valor do `kubectl top` entre as amostras das duas execuções (`kind-ci` e `kind`), mais o valor em repouso 90 s depois do último rollout. CPU: o valor em repouso da primeira execução e o pico das amostras de 5 s da segunda (o `kubectl top` usa a média de uma janela de 15 s, então picos mais curtos não aparecem). Requests e limits são os dos manifests.

| Pod | CPU req/lim | Memória req/lim | CPU repouso | CPU pico | Memória repouso | Memória pico |
|---|---|---|---|---|---|---|
| `os-service-api` | 100m/500m | 256/512 Mi | 5m | 67m | 101 MiB | 101 MiB |
| `os-service-relay` | 50m/250m | 128/256 Mi | 6m | 34m | 74 MiB | 74 MiB |
| `os-service-consumidor` | 50m/250m | 128/256 Mi | 4m | 40m | 74 MiB | 74 MiB |
| `os-postgres-0` (postgres 37 + exporter 6) | 110m/600m | 160/576 Mi | 12m | 15m | 44 MiB | 45 MiB |
| `billing-service-api` | 100m/500m | 256/512 Mi | 4m | 41m | 66 MiB | 66 MiB |
| `billing-service-relay` | 50m/250m | 128/256 Mi | 5m | 30m | 48 MiB | 52 MiB |
| `billing-service-consumidor` | 50m/250m | 128/256 Mi | 4m | 31m | 53 MiB | 53 MiB |
| `billing-service-prazos` | 50m/250m | 128/256 Mi | 4m | 30m | 49 MiB | 49 MiB |
| `billing-mongo-0` (mongo 96 + exporter 12) | 110m/600m | 288/1088 Mi | 46m | 71m | 108 MiB | 194 MiB |
| `execution-service-api` | 100m/500m | 256/512 Mi | 3m | 35m | 82 MiB | 82 MiB |
| `execution-service-relay` | 50m/250m | 128/256 Mi | 4m | 8m | 60 MiB | 66 MiB |
| `execution-service-consumidor` | 50m/250m | 128/256 Mi | 4m | 31m | 62 MiB | 62 MiB |
| `execucao-postgres-0` (postgres 36 + exporter 7) | 110m/600m | 160/576 Mi | 8m | 44m | 43 MiB | 44 MiB |
| Kong (proxy e controlador) | | 384/768 Mi no ADR | 5m | 26m | 306 MiB | 306 MiB |
| RabbitMQ | | 256/1024 Mi no ADR | 30m | 237m | 129 MiB | 201 MiB |
| Prometheus | | 192/512 Mi no ADR | 5m | 12m | 83 MiB | 87 MiB |
| Jaeger | | 128/512 Mi no ADR | 2m | 2m | 9 MiB | 9 MiB |
| Mailpit | | 64/128 Mi no ADR | 1m | 3m | 5 MiB | 6 MiB |
| kube-state-metrics | | 64/128 Mi no ADR | 1m | 5m | 11 MiB | 12 MiB |
| Loki, Promtail e Grafana (só no `kind`) | | | 5m, 11m, 2m | 11m, 23m, 91m | 57, 37 e 48 MiB | 57, 37 e 51 MiB |
| Control plane do kind (apiserver, etcd, controller-manager, scheduler, coredns, kube-proxy, kindnet, metrics-server) | | | 95m no pico do apiserver | | cerca de 500 MiB, 279 MiB só no apiserver | |

O `kubectl top` arredonda cada linha, então o total do pod pode diferir em 1 MiB da soma dos containers (`os-postgres-0`: 37 + 6, e 44 no pod).

O pico de CPU do RabbitMQ (237m) é do `make smoke` da plataforma, que apaga o pod do broker e o vê subir de novo; o pico do MongoDB (71m) e dos Jobs vem do arranque. Nenhuma API passou de 67m e nenhum processo de 40m, contra limits de 500m e 250m; o MongoDB chegou a 71m e o PostgreSQL a 44m (limits de 500m).

### Contra o orçamento do ADR-042

O orçamento do ADR-042 é só de memória, com requests e limits por componente; a coluna "Medido" traz o maior valor amostrado nas duas execuções.

| Componente | Orçamento (requests/limits) | Medido (maior valor) | Cabe |
|---|---|---|---|
| API de cada serviço (3) | 256/512 Mi | 66 a 101 MiB | sim, com 61% a 74% de folga nos requests |
| relay, consumidor e `prazos` (7 processos na `main`) | 128/256 Mi cada | 49 a 74 MiB | sim |
| PostgreSQL (2), com o exporter | 128/512 Mi (+ 32/64 Mi do exporter) | 44 a 45 MiB | sim |
| MongoDB, com o exporter | 256/1024 Mi (+ 32/64 Mi do exporter) | 194 MiB no pico (108 em repouso) | sim |
| exporters de banco (3) | 32/64 Mi cada | 6 a 12 MiB | sim |
| Os 13 pods de serviço, somados | 2.272 Mi / 5.568 Mi (os 7 processos da `main`) | 962 MiB somando os maiores valores (864 em repouso) | sim |
| Plataforma no `kind-ci`, somada | 1.088 Mi / 3.072 Mi (+ 200 Mi do metrics-server) | 543 MiB em repouso (Kong 306, RabbitMQ 129 a 201, Prometheus 83) | sim |
| Nó inteiro: serviços e plataforma | 3,3 GiB de requests e 8,4 GiB de limits com 7 processos (o ADR estima 3,4/8,7 GiB e conta 8 processos) | 3,1 GiB de working set, com control plane e metrics-server | sim, com 6% a 9% de folga na conta uso do nó contra requests; o que sustenta a conclusão são os pods (962 MiB contra 2.272 Mi) e os 16 GB do runner |

CPU: o ADR-042 não orça CPU. Os valores da tabela de pods são os requests e limits dos manifests dos serviços: 50m/250m por processo, 100m/500m por API e 110m/600m por banco com o exporter. Os requests somados são 980m nos serviços e 395m na plataforma do `kind-ci` (1,4 CPU), mais cerca de 1 CPU do control plane; o nó usou 0,3 CPU em repouso. Dos requests de cada pod de serviço, o uso em repouso foi de 3% a 12%, exceto o MongoDB, com 42% (46m de 110m). Nas amostras de 5 s, o pico foi de 16% a 80% nos processos, 35% a 67% nas APIs e 14% a 65% nos bancos, e de no máximo 16% dos limits.

## Medida adicional: `prazos` e `notificador` do OS Service

Na época do ensaio (14/10), os dois processos estavam em branches abertas do OS Service, cada uma com o seu `k8s/`: o `notificador` na `feat/notificacao-e-lgpd` e o `prazos`, na `feat/saga-prazos`. As duas entraram depois na `main` do OS Service, por squash: o `notificador` como `b310889` (PR #9) e o `prazos` como `593471d` (PR #10); os commits da medida (`8eec08f` e `84f89cd`) deixaram de existir como commits da `main`. **Repita a medida sobre a `main` do OS Service antes de usar esses números no ADR-042.**

Cada branch foi implantada, sozinha, sobre o cluster `kind-ci` do ensaio, com a imagem construída do commit dela e o `smoke-servicos.sh os-service` verde nas duas. A de e-mail foi implantada sobre o banco do OS da `main`; a dos prazos, sobre um namespace `pytstop-os` recriado, para não misturar as migrações das duas branches, que partem da mesma `main`.

| Processo | Branch na época | Commit medido | Hoje na `main` do OS | Memória | CPU | Requests/limits | Nó (working set) |
|---|---|---|---|---|---|---|---|
| `os-service-notificador` | `feat/notificacao-e-lgpd` | `8eec08f` | `b310889` (#9) | 63 MiB | 4m | 50m/250m, 128/256 Mi | 3.242 MiB (era 3.147) |
| `os-service-prazos` | `feat/saga-prazos` | `84f89cd` | `593471d` (#10) | 72 MiB | 5m | 50m/250m, 128/256 Mi | 3.377 MiB (namespace recriado) |

- Os dois cabem nos 128/256 Mi dos manifests: juntos acrescentaram cerca de 135 MiB e 9m ao nó.
- O ADR-042 tem linha para o `prazos` e não tem para o `notificador`, que é o 9º processo (relay e consumidor de cada serviço, mais o `prazos` do OS e o do Billing): com ele, os requests e limits passam de 3.488/8.896 Mi para 3.616/9.152 Mi (3,5/8,9 GiB), ainda abaixo dos 10 GiB do ADR. A linha entra no PR que alinha o ADR-042 aos serviços (pendência registrada no `MEMORY.md`).
- O `prazos` do OS (commit `84f89cd`) logou, uma vez, `os.eventos has no consumer` e `saga deadlines paused: the os.eventos consumer is away` no arranque, porque o consumidor do OS ainda não tinha conectado (o namespace acabava de ser recriado). Não repetiu: o consumidor passou a ter 1 e os ciclos seguintes seguiram sem aviso (o log está em [Medidas cruas](ensaio-integrado-medidas.md#log-do-prazos-commit-84f89cd-lido-90-s-depois-do-smoke)). Na `main` do OS de 14/10 (`593471d`), o aviso de pausa é `saga deadlines paused` com `motivo=sem_consumidor`.

## O que precisou de correção

Nada impediu os serviços de subir. O único ponto que pediu mudança no `platform` foi ruído, não falha:

| Item | Onde | Situação |
|---|---|---|
| O `smoke-servicos.sh` deixava o `kubectl exec` escrever `Defaulted container "api" out of: api, aguarda-migracao (init)` (ou `aguarda-banco`, no Billing) na saída e no log do CD a cada serviço, porque a sonda de controle da NetworkPolicy não nomeava o container | `platform` | Corrigido no PR #12: `kubectl exec -c api`, o teste lê cada `exec` pelas flags, e o README registra que o container da API se chama `api` |

Nenhum script, manifesto da plataforma ou documento precisou de outra correção para os serviços subirem.

## Observações do ensaio (situação em 14/10)

Nenhuma impediu o deploy nem o smoke. A coluna "Observação no ensaio" descreve o que o ensaio viu nos commits `fda0672` (OS), `0fed78b` (Billing) e `0c34ed7` (Execução), com os números da época; a coluna "Situação em 14/10" diz o que mudou nas `main` desde então.

| Serviço | Observação no ensaio | Evidência | Situação em 14/10 |
|---|---|---|---|
| Billing e Execução (API) | O FastAPI 0.142.2 tenta configurar telemetria sozinho, porque o ConfigMap define `OTEL_EXPORTER_OTLP_ENDPOINT`, e avisa na partida de cada API que falta o extra: `level: warning`, `logger: fastapi`, `FastAPI automatic telemetry configuration failed: Automatic OpenTelemetry export requires fastapi[opentelemetry] or fastapi[standard]. Install the extra, configure providers yourself, or pass telemetry={'auto_configure': False} to FastAPI().` O OS (FastAPI 0.141.1) não escreve o aviso | `kubectl -n pytstop-billing logs deploy/billing-service-api` e o mesmo em `pytstop-execucao` | Corrigido: Billing #6 (`264da4e`) e Execution #6 (`d04fd81`) passam `telemetry={"auto_configure": False}` ao `FastAPI()` |
| Billing (MongoDB) | O `mongod` escreve linhas de conexão e de autenticação a cada coleta de 15 s do exporter, e o exporter tenta `find` em `admin.system.version` (`{_id: "shardIdentity"}`) com o papel `clusterMonitor`, que não lê essa coleção: `Checking authorization failed ... not authorized on admin to execute command { find: "system.version" ...`, `s: I`. O exporter segue com `mongodb_up 1`. Na segunda execução, o `billing-mongo-0` gerou 1.393 linhas em 10 min (contagem por pod colada do terminal, em [Provas avulsas](ensaio-integrado-medidas.md#provas-avulsas)), e o Loki guardou, em janelas de 10 min, 1.428 linhas do namespace do Billing, 214 do OS e 162 da Execução (todos os pods de cada namespace) | `kubectl -n pytstop-billing logs billing-mongo-0 -c mongo --since=10m \| wc -l` | Corrigido em parte pelo Billing #6: `--quiet` no `mongod` tira as linhas `Connection accepted` e `Connection ended`, e `--mongodb.global-conn-pool` no exporter usa um pool de conexões em vez de abrir e autenticar uma por coleta. Sobra uma linha `Checking authorization failed` por coleta, que o manifesto registra como esperada (o exporter pergunta por `shardIdentity`; não é falha de autorização real), e o papel do exporter continua só com `clusterMonitor` |
| OS, Billing e Execução (Makefile) | O `make kind-deploy` de cada serviço usava um nome diferente para o diretório do `platform` (`PLATFORM` no OS, `PLATFORM_DIR` no Billing e na Execução) e para o overlay (`OVERLAY` no Billing, `KIND_OVERLAY` na Execução, fixo `kind` no OS). Funcionava, só não era igual | `grep -n kind-deploy -A3 Makefile` nos três | Billing #6 adota `PLATFORM_DIR` e `KIND_OVERLAY` (`OVERLAY` segue como alias), a Execução já usava os dois, e o OS Service #11 (aberto) faz o mesmo (`PLATFORM` vira alias). Com os três merges, os nomes são iguais |
| Billing e Execução (spans das APIs) | Depois de chamadas pela borda, o Jaeger listou só `os-service` (e o próprio `jaeger-all-in-one`): as APIs do Billing e da Execução não exportam spans, e o [ADR-043](../arquitetura/adr/fase4/043-observabilidade-distribuida.md) prevê OpenTelemetry nos três serviços, instrumentando o FastAPI | `kubectl get --raw "/api/v1/namespaces/pytstop-plataforma/services/jaeger:16686/proxy/api/services"` | Pendente. O comentário do Billing #6 diz que a API não instala o SDK e que quem exporta, por gRPC, são o relay, o consumidor e o `prazos`. No ensaio nenhuma mensagem circulou, então nem esses apareceram |

Linhas de log que parecem erro e são esperadas no kind: `payment_simulator_enabled_in_production` (warning do Billing, porque o overlay liga o simulador de pagamento de propósito), `Error loading config ... postgres_exporter.yml: no such file or directory` (o `postgres_exporter` procura um arquivo opcional; o `pg_up` fica em 1) e `waiting for mongod ... (MongoNetworkError)` no initContainer do Job do Billing, enquanto o `mongod` sobe.

## Como repetir

1. Confira que nenhum outro cluster usa a máquina: `kind get clusters`, `docker ps` e `lsof -nP -iTCP:443 -sTCP:LISTEN` (o kind publica o Kong em `127.0.0.1:443`).
2. Clone os três serviços ao lado do `platform` e ponha cada um no commit que quer ensaiar. Para repetir o ensaio sobre as `main` de hoje, use o topo da `main` de cada repositório.
3. Cole os comandos da primeira execução de [Comandos usados](#comandos-usados) num script único (o `export MEDICAO` já está no bloco), rode-o e termine com `make kind-down`. As imagens `pytstop-<serviço>:<commit>` ficam no Docker local: apague as suas com `docker rmi`.
4. No CD, o mesmo roteiro roda no job `deploy-kind` de cada serviço (`--tar` no lugar do `docker build` para o próprio serviço), e a coluna "Medido no runner" do ADR-042 se preenche com o primeiro run verde.
