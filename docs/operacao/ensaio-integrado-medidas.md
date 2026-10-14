# Medidas cruas do ensaio integrado

> [↑ Registro do ensaio integrado](ensaio-integrado.md)

Saídas guardadas do ensaio de 14/10/2026 (horário de Brasília), sem Secret e sem dado pessoal, que sustentam as tabelas do [registro do ensaio](ensaio-integrado.md). O comando de cada uma está em [Como cada número foi coletado](ensaio-integrado.md#como-cada-número-foi-coletado). Os blocos vêm dos arquivos de saída dos scripts do ensaio, com duas edições: o prefixo de hora de cada linha foi tirado onde a hora não importa, e do `implantar-servicos.sh` ficaram só as linhas de build, carga, rollout e Job. As provas avulsas do fim vêm de comandos cuja saída não foi gravada em arquivo.

## Primeira execução: overlay `kind-ci`, os três serviços de uma vez

### `medir-kind.sh resumo`

```text
### Deploy on kind: minutes and memory

| Stage | Duration |
|---|---|
| kind-up | 0 min 26 s |
| deploy | 1 min 34 s |
| smoke-plataforma | 1 min 46 s |
| servicos | 1 min 27 s |
| smoke-servicos | 0 min 21 s |
| estavel | 1 min 32 s |
| total | 7 min 06 s |

| Memory of the kind node (pytstop-p4-control-plane) | MiB |
|---|---|
| cgroup peak (memory.peak, file cache included) | 5476 |
| highest sampled working set (83 samples, every 5 s) | 3164 |
| memory of the Docker host | 13947 |

| Pod (without the smoke echo servers) | Highest sampled memory (MiB, kubectl top) |
|---|---|
| pytstop-plataforma/kong-595d54b968-lzxz9 | 306 |
| kube-system/kube-apiserver-pytstop-p4-control-plane | 281 |
| pytstop-plataforma/rabbitmq-0 | 201 |
| pytstop-billing/billing-mongo-0 | 108 |
| pytstop-os/os-service-api-6f4f758f57-d6qrk | 101 |
| pytstop-plataforma/prometheus-5b658db7df-pqv4h | 83 |
| pytstop-execucao/execution-service-api-5ddbc76cb4-qtt9d | 82 |
| pytstop-os/os-service-relay-76fcf855f4-9dvwc | 74 |
| pytstop-os/os-service-consumidor-ccd4cff98-z7hgx | 74 |
| kube-system/kube-controller-manager-pytstop-p4-control-plane | 67 |
| pytstop-billing/billing-service-api-5f7ff8b584-q7ffh | 66 |
| pytstop-execucao/execution-service-consumidor-7fb477f4fb-4br8d | 62 |
| pytstop-execucao/execution-service-relay-6946688fb-ldj2l | 60 |
| pytstop-billing/billing-service-consumidor-6776d58849-gtptf | 53 |
| pytstop-billing/billing-service-prazos-64f44889b-5rtk6 | 49 |
| pytstop-billing/billing-service-relay-5785cdfdb4-fp7jb | 48 |
| kube-system/etcd-pytstop-p4-control-plane | 46 |
| pytstop-os/os-postgres-0 | 44 |
| pytstop-execucao/execucao-postgres-0 | 44 |
| kube-system/kube-scheduler-pytstop-p4-control-plane | 24 |
| kube-system/metrics-server-84df6786fb-7v29w | 21 |
| kube-system/kube-proxy-49mjw | 15 |
| kube-system/kindnet-9gbrj | 14 |
| kube-system/coredns-7d764666f9-dl7t5 | 14 |
| kube-system/coredns-7d764666f9-dkhv6 | 14 |
| pytstop-plataforma/kube-state-metrics-7cc5cb686-k5bw8 | 12 |
| pytstop-plataforma/jaeger-78657fdd59-64xt5 | 9 |
| local-path-storage/local-path-provisioner-67b8995b4b-4dm2m | 9 |
| pytstop-plataforma/mailpit-5f9f5c554-9zc74 | 5 |
```

### Tempo acumulado ao fim de cada etapa (segundos desde o início)

```text
kind-up-fim 26s
deploy-fim 120s
smoke-plataforma-fim 226s
implantar-fim 313s
smoke-servicos-fim 334s
estavel-fim 426s
```

### `implantar-servicos.sh`: build, carga, rollout e Jobs (com hora)

```text
00:25:34 os-service: docker build of pytstop-os-service:fda0672bc10750f76dc252ce4d3c68862eefcbf4 from /private/tmp/claude-501/-Users-jbamaral-git-fiap-postech-sw-architecture/6bf7c38d-7948-425c-aa16-91ada45d4484/scratchpad/svc/os-service
00:25:34 billing-service: docker build of pytstop-billing-service:0fed78b5e24694402ed71b79f9a9238e1c471e66 from /private/tmp/claude-501/-Users-jbamaral-git-fiap-postech-sw-architecture/6bf7c38d-7948-425c-aa16-91ada45d4484/scratchpad/svc/billing-service
00:25:34 execution-service: docker build of pytstop-execution-service:0c34ed75443f0824d14a80dbf20600d2774471ba from /private/tmp/claude-501/-Users-jbamaral-git-fiap-postech-sw-architecture/6bf7c38d-7948-425c-aa16-91ada45d4484/scratchpad/svc/execution-service
00:25:47 Image: "pytstop-os-service:fda0672bc10750f76dc252ce4d3c68862eefcbf4" with ID "sha256:77d015b351ba503a257f9f7d8ee49ab39d54c85161bfb8c3787985a347663708" not yet present on node "pytstop-p4-control-plane", loading...
00:25:50 os-service: k8s/overlays/execucao = kind-ci with image pytstop-os-service:fda0672bc10750f76dc252ce4d3c68862eefcbf4
00:25:50 Image: "pytstop-billing-service:0fed78b5e24694402ed71b79f9a9238e1c471e66" with ID "sha256:c2dc64c951a317d77f78a22e31ac0d6726bd5c58e68632258b5dbcf5becbc5e6" not yet present on node "pytstop-p4-control-plane", loading...
00:25:52 billing-service: k8s/overlays/execucao = kind-ci with image pytstop-billing-service:0fed78b5e24694402ed71b79f9a9238e1c471e66
00:25:52 Image: "pytstop-execution-service:0c34ed75443f0824d14a80dbf20600d2774471ba" with ID "sha256:9dcc2ebf1545c5600911e1b6089dc2d7620edfc020081705572dd35fb2a6070b" not yet present on node "pytstop-p4-control-plane", loading...
00:25:55 execution-service: k8s/overlays/execucao = kind-ci with image pytstop-execution-service:0c34ed75443f0824d14a80dbf20600d2774471ba
00:26:42 [execution-service] partitioned roll out complete: 1 new pods have been updated...
00:26:42 [execution-service] waiting for job.batch/execucao-migracao (up to 300s)
00:26:45 [billing-service] partitioned roll out complete: 1 new pods have been updated...
00:26:45 [billing-service] waiting for job.batch/billing-inicializacao (up to 300s)
00:26:47 [os-service] partitioned roll out complete: 1 new pods have been updated...
00:26:47 [os-service] waiting for job.batch/os-migracao (up to 300s)
00:26:48 [execution-service] deployment "execution-service-api" successfully rolled out
00:26:48 [execution-service] deployment "execution-service-consumidor" successfully rolled out
00:26:48 [execution-service] deployment "execution-service-relay" successfully rolled out
00:26:54 [billing-service] deployment "billing-service-api" successfully rolled out
00:26:54 [os-service] deployment "os-service-api" successfully rolled out
00:26:54 [os-service] deployment "os-service-consumidor" successfully rolled out
00:26:55 [os-service] deployment "os-service-relay" successfully rolled out
00:26:55 [billing-service] deployment "billing-service-consumidor" successfully rolled out
00:27:00 [billing-service] deployment "billing-service-prazos" successfully rolled out
00:27:00 [billing-service] deployment "billing-service-relay" successfully rolled out
00:27:00 deployed: os-service billing-service execution-service
```

### `smoke-servicos.sh` (a versão de `aaca05c`; as três linhas `Defaulted container` são a saída que o `-c api` eliminou)

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
Defaulted container "api" out of: api, aguarda-migracao (init)
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
Defaulted container "api" out of: api, aguarda-banco (init)
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
Defaulted container "api" out of: api, aguarda-migracao (init)
execution-service  execution-service-api pod -> execucao-postgres.pytstop-execucao.svc.cluster.local:5432 ok: connected (the namespace itself reaches the database)
execution-service  rabbitmq-0 -> execucao-postgres.pytstop-execucao.svc.cluster.local:5432 ok: blocked (connection timed out)
services smoke OK: os-service billing-service execution-service
```

### `kubectl top pod -A`, 90 s depois do smoke dos serviços

```text
NAMESPACE            NAME                                               CPU(cores)   MEMORY(bytes)   
kube-system          coredns-7d764666f9-dkhv6                           2m           14Mi            
kube-system          coredns-7d764666f9-dl7t5                           2m           14Mi            
kube-system          etcd-pytstop-p4-control-plane                      12m          46Mi            
kube-system          kindnet-9gbrj                                      1m           14Mi            
kube-system          kube-apiserver-pytstop-p4-control-plane            59m          279Mi           
kube-system          kube-controller-manager-pytstop-p4-control-plane   8m           67Mi            
kube-system          kube-proxy-49mjw                                   1m           14Mi            
kube-system          kube-scheduler-pytstop-p4-control-plane            5m           24Mi            
kube-system          metrics-server-84df6786fb-7v29w                    3m           21Mi            
local-path-storage   local-path-provisioner-67b8995b4b-4dm2m            3m           8Mi             
pytstop-billing      billing-mongo-0                                    46m          108Mi           
pytstop-billing      billing-service-api-5f7ff8b584-q7ffh               4m           66Mi            
pytstop-billing      billing-service-consumidor-6776d58849-gtptf        4m           53Mi            
pytstop-billing      billing-service-prazos-64f44889b-5rtk6             4m           49Mi            
pytstop-billing      billing-service-relay-5785cdfdb4-fp7jb             5m           48Mi            
pytstop-execucao     execucao-postgres-0                                8m           43Mi            
pytstop-execucao     execution-service-api-5ddbc76cb4-qtt9d             3m           82Mi            
pytstop-execucao     execution-service-consumidor-7fb477f4fb-4br8d      4m           62Mi            
pytstop-execucao     execution-service-relay-6946688fb-ldj2l            4m           60Mi            
pytstop-os           os-postgres-0                                      12m          44Mi            
pytstop-os           os-service-api-6f4f758f57-d6qrk                    5m           101Mi           
pytstop-os           os-service-consumidor-ccd4cff98-z7hgx              4m           74Mi            
pytstop-os           os-service-relay-76fcf855f4-9dvwc                  6m           74Mi            
pytstop-plataforma   jaeger-78657fdd59-64xt5                            2m           9Mi             
pytstop-plataforma   kong-595d54b968-lzxz9                              5m           306Mi           
pytstop-plataforma   kube-state-metrics-7cc5cb686-k5bw8                 1m           11Mi            
pytstop-plataforma   mailpit-5f9f5c554-9zc74                            1m           5Mi             
pytstop-plataforma   prometheus-5b658db7df-pqv4h                        5m           83Mi            
pytstop-plataforma   rabbitmq-0                                         30m          129Mi           
```

### `kubectl top pod -A --containers`

```text
NAMESPACE            POD                                                NAME                      CPU(cores)   MEMORY(bytes)   
kube-system          coredns-7d764666f9-dkhv6                           coredns                   2m           14Mi            
kube-system          coredns-7d764666f9-dl7t5                           coredns                   2m           14Mi            
kube-system          etcd-pytstop-p4-control-plane                      etcd                      12m          46Mi            
kube-system          kindnet-9gbrj                                      kindnet-cni               1m           14Mi            
kube-system          kube-apiserver-pytstop-p4-control-plane            kube-apiserver            59m          279Mi           
kube-system          kube-controller-manager-pytstop-p4-control-plane   kube-controller-manager   8m           67Mi            
kube-system          kube-proxy-49mjw                                   kube-proxy                1m           14Mi            
kube-system          kube-scheduler-pytstop-p4-control-plane            kube-scheduler            5m           24Mi            
kube-system          metrics-server-84df6786fb-7v29w                    metrics-server            3m           21Mi            
local-path-storage   local-path-provisioner-67b8995b4b-4dm2m            local-path-provisioner    3m           8Mi             
pytstop-billing      billing-mongo-0                                    exporter                  2m           12Mi            
pytstop-billing      billing-mongo-0                                    mongo                     44m          96Mi            
pytstop-billing      billing-service-api-5f7ff8b584-q7ffh               api                       4m           66Mi            
pytstop-billing      billing-service-consumidor-6776d58849-gtptf        consumidor                4m           53Mi            
pytstop-billing      billing-service-prazos-64f44889b-5rtk6             prazos                    4m           49Mi            
pytstop-billing      billing-service-relay-5785cdfdb4-fp7jb             relay                     5m           48Mi            
pytstop-execucao     execucao-postgres-0                                exporter                  1m           7Mi             
pytstop-execucao     execucao-postgres-0                                postgres                  8m           36Mi            
pytstop-execucao     execution-service-api-5ddbc76cb4-qtt9d             api                       3m           82Mi            
pytstop-execucao     execution-service-consumidor-7fb477f4fb-4br8d      consumidor                4m           62Mi            
pytstop-execucao     execution-service-relay-6946688fb-ldj2l            relay                     4m           60Mi            
pytstop-os           os-postgres-0                                      exporter                  3m           6Mi             
pytstop-os           os-postgres-0                                      postgres                  10m          37Mi            
pytstop-os           os-service-api-6f4f758f57-d6qrk                    api                       5m           101Mi           
pytstop-os           os-service-consumidor-ccd4cff98-z7hgx              consumidor                4m           74Mi            
pytstop-os           os-service-relay-76fcf855f4-9dvwc                  relay                     6m           74Mi            
pytstop-plataforma   jaeger-78657fdd59-64xt5                            jaeger                    2m           9Mi             
pytstop-plataforma   kong-595d54b968-lzxz9                              ingress-controller        2m           34Mi            
pytstop-plataforma   kong-595d54b968-lzxz9                              proxy                     4m           271Mi           
pytstop-plataforma   kube-state-metrics-7cc5cb686-k5bw8                 kube-state-metrics        1m           11Mi            
pytstop-plataforma   mailpit-5f9f5c554-9zc74                            mailpit                   1m           5Mi             
pytstop-plataforma   prometheus-5b658db7df-pqv4h                        prometheus                5m           83Mi            
pytstop-plataforma   rabbitmq-0                                         rabbitmq                  30m          129Mi           
```

### `kubectl top node`

```text
NAME                       CPU(cores)   CPU(%)   MEMORY(bytes)   MEMORY(%)   
pytstop-p4-control-plane   299m         3%       3147Mi          22%         
```

### Requests e limits por container (pods de serviço e da plataforma)

```text
NS                   POD                                                CONT                       CPUREQ     CPULIM      MEMREQ        MEMLIM
kube-system          coredns-7d764666f9-dkhv6                           coredns                    100m       <none>      70Mi          170Mi
kube-system          coredns-7d764666f9-dl7t5                           coredns                    100m       <none>      70Mi          170Mi
kube-system          etcd-pytstop-p4-control-plane                      etcd                       100m       <none>      100Mi         <none>
kube-system          kindnet-9gbrj                                      kindnet-cni                100m       100m        50Mi          50Mi
kube-system          kube-apiserver-pytstop-p4-control-plane            kube-apiserver             250m       <none>      <none>        <none>
kube-system          kube-controller-manager-pytstop-p4-control-plane   kube-controller-manager    200m       <none>      <none>        <none>
kube-system          kube-proxy-49mjw                                   kube-proxy                 <none>     <none>      <none>        <none>
kube-system          kube-scheduler-pytstop-p4-control-plane            kube-scheduler             100m       <none>      <none>        <none>
kube-system          metrics-server-84df6786fb-7v29w                    metrics-server             100m       <none>      200Mi         <none>
local-path-storage   local-path-provisioner-67b8995b4b-4dm2m            local-path-provisioner     <none>     <none>      <none>        <none>
pytstop-billing      billing-inicializacao-45gsw                        seed                       50m        500m        128Mi         256Mi
pytstop-billing      billing-mongo-0                                    mongo,exporter             100m,10m   500m,100m   256Mi,32Mi    1Gi,64Mi
pytstop-billing      billing-service-api-5f7ff8b584-q7ffh               api                        100m       500m        256Mi         512Mi
pytstop-billing      billing-service-consumidor-6776d58849-gtptf        consumidor                 50m        250m        128Mi         256Mi
pytstop-billing      billing-service-prazos-64f44889b-5rtk6             prazos                     50m        250m        128Mi         256Mi
pytstop-billing      billing-service-relay-5785cdfdb4-fp7jb             relay                      50m        250m        128Mi         256Mi
pytstop-execucao     execucao-migracao-zqt27                            migracao                   50m        500m        128Mi         256Mi
pytstop-execucao     execucao-postgres-0                                postgres,exporter          100m,10m   500m,100m   128Mi,32Mi    512Mi,64Mi
pytstop-execucao     execution-service-api-5ddbc76cb4-qtt9d             api                        100m       500m        256Mi         512Mi
pytstop-execucao     execution-service-consumidor-7fb477f4fb-4br8d      consumidor                 50m        250m        128Mi         256Mi
pytstop-execucao     execution-service-relay-6946688fb-ldj2l            relay                      50m        250m        128Mi         256Mi
pytstop-os           os-migracao-hb8fp                                  migracao                   50m        500m        128Mi         256Mi
pytstop-os           os-postgres-0                                      postgres,exporter          100m,10m   500m,100m   128Mi,32Mi    512Mi,64Mi
pytstop-os           os-service-api-6f4f758f57-d6qrk                    api                        100m       500m        256Mi         512Mi
pytstop-os           os-service-consumidor-ccd4cff98-z7hgx              consumidor                 50m        250m        128Mi         256Mi
pytstop-os           os-service-relay-76fcf855f4-9dvwc                  relay                      50m        250m        128Mi         256Mi
pytstop-plataforma   jaeger-78657fdd59-64xt5                            jaeger                     50m        250m        128Mi         512Mi
pytstop-plataforma   kong-595d54b968-lzxz9                              ingress-controller,proxy   50m,100m   250m,1      128Mi,256Mi   256Mi,512Mi
pytstop-plataforma   kube-state-metrics-7cc5cb686-k5bw8                 kube-state-metrics         20m        100m        64Mi          128Mi
pytstop-plataforma   mailpit-5f9f5c554-9zc74                            mailpit                    25m        100m        64Mi          128Mi
pytstop-plataforma   prometheus-5b658db7df-pqv4h                        prometheus                 50m        250m        192Mi         512Mi
pytstop-plataforma   rabbitmq-0                                         rabbitmq                   100m       1           256Mi         1Gi
pytstop-plataforma   rabbitmq-usuarios-lknsm                            criar-usuarios             50m        250m        64Mi          128Mi
```

### Memória do nó: `memory.peak`, `memory.current`, `anon`, `file`, `inactive_file` e `active_file`, em bytes (nessa ordem)

```text
5742931968
5575188480
anon 2179297280
file 3076501504
inactive_file 2409152512
active_file 597766144
```

### HPA

```text
NAMESPACE          NAME                    REFERENCE                          TARGETS       MINPODS   MAXPODS   REPLICAS   AGE
pytstop-billing    billing-service-api     Deployment/billing-service-api     cpu: 4%/70%   1         1         1          2m56s
pytstop-execucao   execution-service-api   Deployment/execution-service-api   cpu: 3%/70%   1         1         1          2m56s
pytstop-os         os-service-api          Deployment/os-service-api          cpu: 5%/70%   1         1         1          2m56s
```

### Reinícios por pod (todos os namespaces)

```text
kube-system/coredns-7d764666f9-dkhv6 restarts=0 phase=Running
kube-system/coredns-7d764666f9-dl7t5 restarts=0 phase=Running
kube-system/etcd-pytstop-p4-control-plane restarts=0 phase=Running
kube-system/kindnet-9gbrj restarts=0 phase=Running
kube-system/kube-apiserver-pytstop-p4-control-plane restarts=0 phase=Running
kube-system/kube-controller-manager-pytstop-p4-control-plane restarts=0 phase=Running
kube-system/kube-proxy-49mjw restarts=0 phase=Running
kube-system/kube-scheduler-pytstop-p4-control-plane restarts=0 phase=Running
kube-system/metrics-server-84df6786fb-7v29w restarts=0 phase=Running
local-path-storage/local-path-provisioner-67b8995b4b-4dm2m restarts=0 phase=Running
pytstop-billing/billing-inicializacao-45gsw restarts=0 phase=Succeeded
pytstop-billing/billing-mongo-0 restarts=0 phase=Running
pytstop-billing/billing-service-api-5f7ff8b584-q7ffh restarts=0 phase=Running
pytstop-billing/billing-service-consumidor-6776d58849-gtptf restarts=0 phase=Running
pytstop-billing/billing-service-prazos-64f44889b-5rtk6 restarts=0 phase=Running
pytstop-billing/billing-service-relay-5785cdfdb4-fp7jb restarts=0 phase=Running
pytstop-execucao/execucao-migracao-zqt27 restarts=0 phase=Succeeded
pytstop-execucao/execucao-postgres-0 restarts=0 phase=Running
pytstop-execucao/execution-service-api-5ddbc76cb4-qtt9d restarts=0 phase=Running
pytstop-execucao/execution-service-consumidor-7fb477f4fb-4br8d restarts=0 phase=Running
pytstop-execucao/execution-service-relay-6946688fb-ldj2l restarts=0 phase=Running
pytstop-os/os-migracao-hb8fp restarts=0 phase=Succeeded
pytstop-os/os-postgres-0 restarts=0 phase=Running
pytstop-os/os-service-api-6f4f758f57-d6qrk restarts=0 phase=Running
pytstop-os/os-service-consumidor-ccd4cff98-z7hgx restarts=0 phase=Running
pytstop-os/os-service-relay-76fcf855f4-9dvwc restarts=0 phase=Running
pytstop-plataforma/jaeger-78657fdd59-64xt5 restarts=0 phase=Running
pytstop-plataforma/kong-595d54b968-lzxz9 restarts=0 phase=Running
pytstop-plataforma/kube-state-metrics-7cc5cb686-k5bw8 restarts=0 phase=Running
pytstop-plataforma/mailpit-5f9f5c554-9zc74 restarts=0 phase=Running
pytstop-plataforma/prometheus-5b658db7df-pqv4h restarts=0 phase=Running
pytstop-plataforma/rabbitmq-0 restarts=0 phase=Running
pytstop-plataforma/rabbitmq-usuarios-lknsm restarts=0 phase=Succeeded
```

### Segundo `make deploy`, segundo `implantar-servicos.sh` e segundo `smoke-servicos.sh` sobre o mesmo cluster

```text
00:30:07 == make deploy (2o) 00:30:07
00:30:24 make deploy rc=0 em 17s
00:30:24 secrets: iguais (      12 Secrets)
00:30:24 == implantar-servicos (2o) 00:30:24
00:30:37 implantar rc=0 em 13s
00:30:37 == smoke-servicos (2o) 00:30:37
00:30:48 smoke-servicos rc=0 em 11s
00:30:48 FIM2
```

## Segunda execução: overlay `kind`, um `make kind-deploy` por serviço

### `medir-kind.sh resumo`

```text
### Deploy on kind: minutes and memory

| Stage | Duration |
|---|---|
| kind-up | 0 min 26 s |
| deploy | 1 min 45 s |
| smoke-plataforma | 2 min 14 s |
| kind-deploy-os-service | 0 min 34 s |
| kind-deploy-billing-service | 0 min 46 s |
| kind-deploy-execution-service | 0 min 17 s |
| smoke-servicos | 0 min 21 s |
| estavel | 1 min 31 s |
| total | 7 min 54 s |

| Memory of the kind node (pytstop-p4-control-plane) | MiB |
|---|---|
| cgroup peak (memory.peak, file cache included) | 6738 |
| highest sampled working set (92 samples, every 5 s) | 3447 |
| memory of the Docker host | 13947 |

| Pod (without the smoke echo servers) | Highest sampled memory (MiB, kubectl top) |
|---|---|
| pytstop-plataforma/kong-595d54b968-66mp5 | 305 |
| kube-system/kube-apiserver-pytstop-p4-control-plane | 282 |
| pytstop-billing/billing-mongo-0 | 194 |
| pytstop-plataforma/rabbitmq-0 | 145 |
| pytstop-os/os-service-api-6f4f758f57-c82vd | 101 |
| pytstop-plataforma/prometheus-5b658db7df-zr999 | 87 |
| pytstop-execucao/execution-service-api-5ddbc76cb4-wb8tq | 82 |
| pytstop-os/os-service-relay-76fcf855f4-flw2p | 74 |
| pytstop-os/os-service-consumidor-ccd4cff98-7sndh | 74 |
| kube-system/kube-controller-manager-pytstop-p4-control-plane | 67 |
| pytstop-execucao/execution-service-relay-6946688fb-hfkdd | 66 |
| pytstop-billing/billing-service-api-65fd4bf888-lfp4g | 66 |
| pytstop-execucao/execution-service-consumidor-7fb477f4fb-88fw4 | 62 |
| pytstop-plataforma/loki-5dfc44c98c-t6qmz | 57 |
| pytstop-billing/billing-service-consumidor-779cd4569-2knhc | 53 |
| pytstop-billing/billing-service-relay-6c7cfcd656-94772 | 52 |
| pytstop-plataforma/grafana-56c84c569b-px9d2 | 51 |
| pytstop-billing/billing-service-prazos-844fcb544d-79jwp | 49 |
| kube-system/etcd-pytstop-p4-control-plane | 46 |
| pytstop-os/os-postgres-0 | 45 |
| pytstop-execucao/execucao-postgres-0 | 42 |
| pytstop-plataforma/promtail-qtcfm | 37 |
| kube-system/metrics-server-84df6786fb-gpzlr | 22 |
| kube-system/kube-scheduler-pytstop-p4-control-plane | 22 |
| kube-system/kube-proxy-2szzh | 15 |
| kube-system/kindnet-bhqzs | 14 |
| kube-system/coredns-7d764666f9-z8mm9 | 13 |
| kube-system/coredns-7d764666f9-pqzjr | 13 |
| pytstop-plataforma/kube-state-metrics-7cc5cb686-t99rk | 12 |
| pytstop-plataforma/jaeger-78657fdd59-kdw9m | 8 |
| local-path-storage/local-path-provisioner-67b8995b4b-5z6qq | 8 |
| pytstop-plataforma/mailpit-5f9f5c554-nxpjf | 6 |
```

### Tempo acumulado ao fim de cada etapa (segundos desde o início)

```text
kind-up-fim 26s
deploy-fim 131s
smoke-plataforma-fim 265s
kind-deploy-os-service-fim 299s
kind-deploy-billing-service-fim 345s
kind-deploy-execution-service-fim 362s
smoke-servicos-fim 383s
estavel-fim 474s
```

### `make kind-deploy` do OS Service (com hora)

```text
00:43:10 os-service: docker build of pytstop-os-service:fda0672bc10750f76dc252ce4d3c68862eefcbf4 from /private/tmp/claude-501/-Users-jbamaral-git-fiap-postech-sw-architecture/6bf7c38d-7948-425c-aa16-91ada45d4484/scratchpad/svc/os-service
00:43:12 Image: "pytstop-os-service:fda0672bc10750f76dc252ce4d3c68862eefcbf4" with ID "sha256:f3cbbb180b46e6b2ffb82d7b64322c0920735b2d1d0386d36d6d8993abfb5dea" not yet present on node "pytstop-p4-control-plane", loading...
00:43:15 os-service: k8s/overlays/execucao = kind with image pytstop-os-service:fda0672bc10750f76dc252ce4d3c68862eefcbf4
00:43:37 [os-service] partitioned roll out complete: 1 new pods have been updated...
00:43:37 [os-service] waiting for job.batch/os-migracao (up to 300s)
00:43:44 [os-service] deployment "os-service-api" successfully rolled out
00:43:44 [os-service] deployment "os-service-consumidor" successfully rolled out
00:43:44 [os-service] deployment "os-service-relay" successfully rolled out
00:43:44 deployed: os-service
```

### `make kind-deploy` do Billing Service (com hora)

```text
00:43:44 billing-service: docker build of pytstop-billing-service:0fed78b5e24694402ed71b79f9a9238e1c471e66 from /private/tmp/claude-501/-Users-jbamaral-git-fiap-postech-sw-architecture/6bf7c38d-7948-425c-aa16-91ada45d4484/scratchpad/svc/billing-service
00:43:46 Image: "pytstop-billing-service:0fed78b5e24694402ed71b79f9a9238e1c471e66" with ID "sha256:45ce0219d033aade82bf16c531d7ce1694e4032ed090d349689bb63d4762a15c" not yet present on node "pytstop-p4-control-plane", loading...
00:43:47 billing-service: k8s/overlays/execucao = kind with image pytstop-billing-service:0fed78b5e24694402ed71b79f9a9238e1c471e66
00:44:17 [billing-service] partitioned roll out complete: 1 new pods have been updated...
00:44:17 [billing-service] waiting for job.batch/billing-inicializacao (up to 300s)
00:44:30 [billing-service] deployment "billing-service-api" successfully rolled out
00:44:30 [billing-service] deployment "billing-service-consumidor" successfully rolled out
00:44:30 [billing-service] deployment "billing-service-prazos" successfully rolled out
00:44:30 [billing-service] deployment "billing-service-relay" successfully rolled out
00:44:30 deployed: billing-service
```

### `make kind-deploy` do Execution Service (com hora)

```text
00:44:30 execution-service: docker build of pytstop-execution-service:0c34ed75443f0824d14a80dbf20600d2774471ba from /private/tmp/claude-501/-Users-jbamaral-git-fiap-postech-sw-architecture/6bf7c38d-7948-425c-aa16-91ada45d4484/scratchpad/svc/execution-service
00:44:32 Image: "pytstop-execution-service:0c34ed75443f0824d14a80dbf20600d2774471ba" with ID "sha256:5ca7f414688f5de3f92edb844d797d3b9930f883eb174ee196b39c185d3eaa65" not yet present on node "pytstop-p4-control-plane", loading...
00:44:34 execution-service: k8s/overlays/execucao = kind with image pytstop-execution-service:0c34ed75443f0824d14a80dbf20600d2774471ba
00:44:40 [execution-service] partitioned roll out complete: 1 new pods have been updated...
00:44:40 [execution-service] waiting for job.batch/execucao-migracao (up to 300s)
00:44:47 [execution-service] deployment "execution-service-api" successfully rolled out
00:44:47 [execution-service] deployment "execution-service-consumidor" successfully rolled out
00:44:47 [execution-service] deployment "execution-service-relay" successfully rolled out
00:44:47 deployed: execution-service
```

### `smoke-servicos.sh` (a versão de `aaca05c`)

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
Defaulted container "api" out of: api, aguarda-migracao (init)
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
Defaulted container "api" out of: api, aguarda-banco (init)
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
Defaulted container "api" out of: api, aguarda-migracao (init)
execution-service  execution-service-api pod -> execucao-postgres.pytstop-execucao.svc.cluster.local:5432 ok: connected (the namespace itself reaches the database)
execution-service  rabbitmq-0 -> execucao-postgres.pytstop-execucao.svc.cluster.local:5432 ok: blocked (connection timed out)
services smoke OK: os-service billing-service execution-service
```

### Maior CPU (m) e maior memória (MiB) de cada pod nas amostras de 5 s do `kubectl top`: pod, CPU, memória (os pods `os-service-api-...`, `billing-service-api-...` e `execution-service-api-...` do namespace `pytstop-plataforma` são os servidores de eco do `make smoke`)

```text
pytstop-plataforma/rabbitmq-0 237 145
kube-system/kube-apiserver-pytstop-p4-control-plane 95 282
pytstop-plataforma/grafana-56c84c569b-px9d2 91 51
pytstop-billing/billing-mongo-0 71 194
pytstop-os/os-service-api-6f4f758f57-c82vd 67 101
pytstop-execucao/execucao-postgres-0 44 42
pytstop-billing/billing-service-api-65fd4bf888-lfp4g 41 66
pytstop-os/os-service-consumidor-ccd4cff98-7sndh 40 74
kube-system/etcd-pytstop-p4-control-plane 38 46
pytstop-execucao/execution-service-api-5ddbc76cb4-wb8tq 35 82
pytstop-os/os-service-relay-76fcf855f4-flw2p 34 74
pytstop-billing/billing-service-consumidor-779cd4569-2knhc 31 53
pytstop-execucao/execution-service-consumidor-7fb477f4fb-88fw4 31 62
pytstop-billing/billing-service-prazos-844fcb544d-79jwp 30 49
pytstop-billing/billing-service-relay-6c7cfcd656-94772 30 52
pytstop-plataforma/kong-595d54b968-66mp5 26 305
pytstop-plataforma/promtail-qtcfm 23 37
kube-system/kube-controller-manager-pytstop-p4-control-plane 22 67
pytstop-os/os-postgres-0 15 45
kube-system/kube-scheduler-pytstop-p4-control-plane 12 22
pytstop-plataforma/prometheus-5b658db7df-zr999 12 87
pytstop-plataforma/loki-5dfc44c98c-t6qmz 11 57
pytstop-plataforma/os-service-api-8585f46d75-mc4kj 11 19
kube-system/kindnet-bhqzs 10 14
kube-system/coredns-7d764666f9-z8mm9 9 13
kube-system/coredns-7d764666f9-pqzjr 8 13
pytstop-execucao/execution-service-relay-6946688fb-hfkdd 8 66
kube-system/metrics-server-84df6786fb-gpzlr 6 22
pytstop-plataforma/billing-service-api-b48f48b4d-tjmlx 6 19
pytstop-plataforma/rabbitmq-usuarios-fmwpf 6 0
pytstop-plataforma/execution-service-api-7b78cf97f9-99nmm 5 19
pytstop-plataforma/kube-state-metrics-7cc5cb686-t99rk 5 12
kube-system/kube-proxy-2szzh 4 15
pytstop-plataforma/mailpit-5f9f5c554-nxpjf 3 6
local-path-storage/local-path-provisioner-67b8995b4b-5z6qq 2 8
pytstop-plataforma/jaeger-78657fdd59-kdw9m 2 8
```

### `kubectl top pod -A`, 90 s depois do smoke dos serviços

```text
NAMESPACE            NAME                                               CPU(cores)   MEMORY(bytes)   
kube-system          coredns-7d764666f9-pqzjr                           2m           13Mi            
kube-system          coredns-7d764666f9-z8mm9                           1m           13Mi            
kube-system          etcd-pytstop-p4-control-plane                      14m          46Mi            
kube-system          kindnet-bhqzs                                      2m           13Mi            
kube-system          kube-apiserver-pytstop-p4-control-plane            37m          282Mi           
kube-system          kube-controller-manager-pytstop-p4-control-plane   9m           66Mi            
kube-system          kube-proxy-2szzh                                   1m           15Mi            
kube-system          kube-scheduler-pytstop-p4-control-plane            4m           22Mi            
kube-system          metrics-server-84df6786fb-gpzlr                    3m           22Mi            
local-path-storage   local-path-provisioner-67b8995b4b-5z6qq            1m           8Mi             
pytstop-billing      billing-mongo-0                                    60m          194Mi           
pytstop-billing      billing-service-api-65fd4bf888-lfp4g               4m           66Mi            
pytstop-billing      billing-service-consumidor-779cd4569-2knhc         6m           53Mi            
pytstop-billing      billing-service-prazos-844fcb544d-79jwp            6m           49Mi            
pytstop-billing      billing-service-relay-6c7cfcd656-94772             6m           48Mi            
pytstop-execucao     execucao-postgres-0                                9m           41Mi            
pytstop-execucao     execution-service-api-5ddbc76cb4-wb8tq             3m           82Mi            
pytstop-execucao     execution-service-consumidor-7fb477f4fb-88fw4      4m           62Mi            
pytstop-execucao     execution-service-relay-6946688fb-hfkdd            4m           60Mi            
pytstop-os           os-postgres-0                                      8m           45Mi            
pytstop-os           os-service-api-6f4f758f57-c82vd                    4m           101Mi           
pytstop-os           os-service-consumidor-ccd4cff98-7sndh              4m           74Mi            
pytstop-os           os-service-relay-76fcf855f4-flw2p                  3m           74Mi            
pytstop-plataforma   grafana-56c84c569b-px9d2                           2m           48Mi            
pytstop-plataforma   jaeger-78657fdd59-kdw9m                            1m           8Mi             
pytstop-plataforma   kong-595d54b968-66mp5                              5m           305Mi           
pytstop-plataforma   kube-state-metrics-7cc5cb686-t99rk                 1m           12Mi            
pytstop-plataforma   loki-5dfc44c98c-t6qmz                              5m           57Mi            
pytstop-plataforma   mailpit-5f9f5c554-nxpjf                            1m           6Mi             
pytstop-plataforma   prometheus-5b658db7df-zr999                        5m           87Mi            
pytstop-plataforma   promtail-qtcfm                                     11m          37Mi            
pytstop-plataforma   rabbitmq-0                                         63m          125Mi           
```

### `kubectl top node`

```text
NAME                       CPU(cores)   CPU(%)   MEMORY(bytes)   MEMORY(%)   
pytstop-p4-control-plane   351m         4%       3362Mi          24%         
```

### Memória do nó: `memory.peak` e `memory.current`, em bytes

```text
7065632768
6436966400
```

### HPA

```text
NAMESPACE          NAME                    REFERENCE                          TARGETS       MINPODS   MAXPODS   REPLICAS   AGE
pytstop-billing    billing-service-api     Deployment/billing-service-api     cpu: 4%/70%   1         2         1          2m51s
pytstop-execucao   execution-service-api   Deployment/execution-service-api   cpu: 3%/70%   1         2         1          2m4s
pytstop-os         os-service-api          Deployment/os-service-api          cpu: 4%/70%   1         2         1          3m23s
```

### Regras de alerta do Grafana

```text
rule: Kong fora do ar ou sem alvo de métricas (2min) [inactive, ok]
rule: DLQ com mensagens [inactive, ok]
rule: RabbitMQ com alarme de memória ou disco [inactive, ok]
rule: Gateway com mais de 1% de 5xx (5min) [inactive, ok]
rule: Alvo de métricas fora do ar (2min) [inactive, ok]
rule: RabbitMQ fora do ar ou sem alvo de métricas (2min) [inactive, ok]
rule: CPU de pod acima de 80% do limite (10min) [inactive, ok]
rule: Saga parada [inactive, ok]
```

### Linhas de log no Loki, janela de 10 min

```text
loki pytstop-os linhas em 10 min: 214
loki pytstop-billing linhas em 10 min: 1428
loki pytstop-execucao linhas em 10 min: 162
```

### Broker reiniciado com os serviços de pé

```text
antes: billing.comandos=1 execucao.comandos=1 os.eventos=1 
pod "rabbitmq-0" deleted from pytstop-plataforma namespace
pod apagado; esperando ficar pronto
pod/rabbitmq-0 condition met
rabbitmq-0 pronto apos 13s
consumidores de volta apos 30s: billing.comandos=1 execucao.comandos=1 os.eventos=1 
ATENCAO: pytstop-billing billing-mongo-0 2/2 Running 0
ATENCAO: pytstop-billing billing-service-consumidor-779cd4569-2knhc 0/1 Running 0
ATENCAO: pytstop-billing billing-service-relay-6c7cfcd656-94772 0/1 Running 0
ATENCAO: pytstop-execucao execucao-postgres-0 2/2 Running 0
ATENCAO: pytstop-os os-postgres-0 2/2 Running 0
restarts dos pods dos servicos:
total 0
FIM-BROKER
```

## Medida adicional: notificador (`feat/notificacao-e-lgpd`, commit `8eec08f`)

### `implantar-servicos.sh` e `smoke-servicos.sh os-service` (com hora)

```text
00:31:54 == implantar OS de c4 (8eec08f) 00:31:54
00:32:12 implantar rc=0
00:32:12 [os-service] partitioned roll out complete: 1 new pods have been updated...
00:32:12 [os-service] waiting for job.batch/os-migracao (up to 300s)
00:32:12 [os-service] Waiting for deployment "os-service-api" rollout to finish: 1 old replicas are pending termination...
00:32:12 [os-service] Waiting for deployment "os-service-api" rollout to finish: 1 old replicas are pending termination...
00:32:12 [os-service] deployment "os-service-api" successfully rolled out
00:32:12 [os-service] deployment "os-service-consumidor" successfully rolled out
00:32:12 [os-service] deployment "os-service-notificador" successfully rolled out
00:32:12 [os-service] deployment "os-service-relay" successfully rolled out
00:32:12 deployed: os-service
00:32:28 smoke rc=0
00:32:28 os-service         initialization Job         ok: os-migracao=true
00:32:28 os-service         rollouts                   ok: 5 ready
00:32:28 os-service         GET /os/api/v1/saude       ok: 200
00:32:28 os-service         GET /os/metrics            ok: 404
00:32:28 os-service         GET /os/api/v1/admin/outbox ok: 404
00:32:28 os-service         GET /os/docs               ok: 200
00:32:28 os-service         GET /os/openapi.json       ok: 200
00:32:28 os-service         up = 1 in Prometheus       ok: 5 pods
00:32:28 os-service         pg_up = 1 in Prometheus    ok: os-postgres-0
00:32:28 os-service         os-postgres-0 127.0.0.1 asks for a password ok: postgres on 127.0.0.1 without a password was refused
00:32:28 os-service         os-service-api pod -> os-postgres.pytstop-os.svc.cluster.local:5432 ok: connected (the namespace itself reaches the database)
00:32:28 os-service         rabbitmq-0 -> os-postgres.pytstop-os.svc.cluster.local:5432 ok: blocked (connection timed out)
00:32:28 services smoke OK: os-service
00:33:59 FIM-EXTRA
```

### `kubectl top pod -A` do namespace `pytstop-os` e `kubectl top node`, 90 s depois do smoke

```text
NAMESPACE            NAME                                               CPU(cores)   MEMORY(bytes)   
pytstop-os           os-postgres-0                                      15m          49Mi            
pytstop-os           os-service-api-5585d84465-4dtq4                    7m           101Mi           
pytstop-os           os-service-consumidor-8747dc65b-2nxd4              5m           74Mi            
pytstop-os           os-service-notificador-7dc9549c5d-m7qfc            4m           63Mi            
pytstop-os           os-service-relay-67f8f94f46-cm2cs                  5m           74Mi            

NAME                       CPU(cores)   CPU(%)   MEMORY(bytes)   MEMORY(%)   
pytstop-p4-control-plane   411m         5%       3242Mi          23%         
```

## Medida adicional: prazos (`feat/saga-prazos`, commit `84f89cd`)

### `implantar-servicos.sh` e `smoke-servicos.sh os-service` (com hora)

```text
00:35:13 == implantar OS de c3 (84f89cd) 00:35:13
00:35:40 implantar rc=0
00:35:40 [os-service] Waiting for 1 pods to be ready...
00:35:40 [os-service] partitioned roll out complete: 1 new pods have been updated...
00:35:40 [os-service] waiting for job.batch/os-migracao (up to 300s)
00:35:40 [os-service] Waiting for deployment "os-service-api" rollout to finish: 0 of 1 updated replicas are available...
00:35:40 [os-service] deployment "os-service-api" successfully rolled out
00:35:40 [os-service] deployment "os-service-consumidor" successfully rolled out
00:35:40 [os-service] deployment "os-service-prazos" successfully rolled out
00:35:40 [os-service] deployment "os-service-relay" successfully rolled out
00:35:40 deployed: os-service
00:36:01 smoke rc=0
00:36:01 os-service         initialization Job         ok: os-migracao=true
00:36:01 os-service         rollouts                   ok: 5 ready
00:36:01 os-service         GET /os/api/v1/saude       ok: 200
00:36:01 os-service         GET /os/metrics            ok: 404
00:36:01 os-service         GET /os/api/v1/admin/outbox ok: 404
00:36:01 os-service         GET /os/docs               ok: 200
00:36:01 os-service         GET /os/openapi.json       ok: 200
00:36:01 os-service         up = 1 in Prometheus       ok: 5 pods
00:36:01 os-service         pg_up = 1 in Prometheus    ok: os-postgres-0
00:36:01 os-service         os-postgres-0 127.0.0.1 asks for a password ok: postgres on 127.0.0.1 without a password was refused
00:36:01 os-service         os-service-api pod -> os-postgres.pytstop-os.svc.cluster.local:5432 ok: connected (the namespace itself reaches the database)
00:36:01 os-service         rabbitmq-0 -> os-postgres.pytstop-os.svc.cluster.local:5432 ok: blocked (connection timed out)
00:36:01 services smoke OK: os-service
00:37:31 FIM-EXTRA
```

### `kubectl top pod -A` do namespace `pytstop-os` e `kubectl top node`, 90 s depois do smoke

```text
NAMESPACE            NAME                                               CPU(cores)   MEMORY(bytes)   
pytstop-os           os-postgres-0                                      11m          47Mi            
pytstop-os           os-service-api-857f97d848-hh4vl                    4m           101Mi           
pytstop-os           os-service-consumidor-64ddcb75bf-kjcfs             4m           74Mi            
pytstop-os           os-service-prazos-6598c6f59-bj46f                  5m           72Mi            
pytstop-os           os-service-relay-c9dcff5f9-tfcqh                   3m           74Mi            

NAME                       CPU(cores)   CPU(%)   MEMORY(bytes)   MEMORY(%)   
pytstop-p4-control-plane   263m         3%       3377Mi          24%         
```

## Provas avulsas

Saídas de comandos avulsos, reformatadas em linhas curtas, nos dois clusters (a mesma em ambos).

Swagger, pela borda (`curl -k https://localhost/<prefixo>/docs` e `.../openapi.json`):

```text
/os/docs        url: '/os/openapi.json'
/billing/docs   url: '/billing/openapi.json'
/execucao/docs  url: '/execucao/openapi.json'
/os/openapi.json        servers: [{"url":"/os"}]        21 paths   PytStop OS Service 0.4.0
/billing/openapi.json   servers: [{"url":"/billing"}]   17 paths   PytStop Billing Service 0.1.0
/execucao/openapi.json  servers: [{"url":"/execucao"}]  11 paths   PytStop Execution Service 0.1.0
```

Login do admin semeado e chamadas autenticadas pela borda (a senha vem do Secret `os-admin`, entra no `curl` por `jq -n ... | curl --data-binary @-` e não é impressa; o token também não):

```text
login: 200
/os/api/v1/clientes -> 200
/billing/api/v1/precos/servicos -> 200
/execucao/api/v1/estoque -> 200
/execucao/api/v1/fila -> 200
/billing/api/v1/precos/servicos sem token -> 401
/os/.well-known/jwks.json -> 200
```

Conexões entre namespaces, `python -c "socket.create_connection(...)"` com prazo de 3 s, por `kubectl exec -c api`:

```text
execucao-api -> billing-service:8000   connected
execucao-api -> os-service:8000        connected
billing-api  -> execution-service:8000 TimeoutError
os-api       -> billing-service:8000   TimeoutError
os-api       -> execucao-postgres:5432 TimeoutError
```

Filas do RabbitMQ com os serviços de pé (`rabbitmqctl list_queues name consumers`, só as filas de trabalho): `billing.comandos`, `execucao.comandos` e `os.eventos` com 1 consumidor cada; as três DLQs com 0 mensagens.

Serviços que o Jaeger listou depois das chamadas pela borda (`/api/services`): `os-service` e `jaeger-all-in-one`.
