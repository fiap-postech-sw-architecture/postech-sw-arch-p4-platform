# Contrato com os serviços

> [↑ Raiz do projeto](../README.md)

O que o repositório de cada serviço precisa ter para o CD dele subir os três no kind, e o que o `platform` entrega. No job `deploy-kind` de um serviço, a ordem é: o [`deploy-kind.sh`](../scripts/ci/deploy-kind.sh) sobe a plataforma e gera os Secrets ([Segredos gerados](segredos.md#segredos-gerados)); o [`implantar-servicos.sh`](../scripts/ci/implantar-servicos.sh) implanta os três serviços; o [`smoke-servicos.sh`](../scripts/ci/smoke-servicos.sh) confere cada namespace; e, se algo falha, o [`diagnostico.sh`](../scripts/ci/diagnostico.sh) despeja pods, eventos e logs de todos os namespaces.

## O que o `platform` entrega

| Item | Onde |
|---|---|
| Namespace do serviço, criado vazio pelo `make deploy` se ainda não existe, com a Role do Kong | [Gateway](gateway.md#gateway-como-um-serviço-publica-as-rotas) |
| Secret `rabbitmq` com a `RABBITMQ_URL` do usuário do serviço | [Segredos gerados](segredos.md#segredos-gerados) |
| As fontes do serviço, criadas só se ainda não existem: as senhas do banco, uma por papel, as chaves e a senha do admin semeado | [Segredos gerados](segredos.md#segredos-gerados) |
| Usuário no RabbitMQ, com as permissões do serviço e a topologia pronta | [Usuário e permissões no RabbitMQ](rabbitmq.md#usuário-e-permissões-no-rabbitmq) |
| Kong com os `KongClusterPlugin` (rate limit por classe e `fora-da-borda`), que o Ingress do serviço referencia por anotação, e um exemplo de borda por serviço | [Gateway](gateway.md#gateway-como-um-serviço-publica-as-rotas) e [`k8s/exemplos/`](../k8s/exemplos) |
| Métricas pelo Prometheus (pod anotado), logs pelo Promtail, traces no Jaeger e SMTP no Mailpit | [Endereços e variáveis](enderecos-e-variaveis.md#endereços-e-variáveis) |
| Versões fixas do PostgreSQL, do MongoDB e dos exporters | [Componentes e versões](componentes-e-versoes.md#componentes-e-versões) |
| Scripts do CD: `deploy-kind.sh`, `implantar-servicos.sh`, `smoke-servicos.sh`, `diagnostico.sh` e o [`medir-kind.sh`](../scripts/medir-kind.sh) | [`scripts/ci/`](../scripts/ci) |
| O gancho de deploy remoto, desligado: o [`deploy-remoto.sh`](../scripts/ci/deploy-remoto.sh), que o job `deploy-remote` do CD chama para implantar um serviço num cluster persistente pelo digest da imagem | [Nuvem opcional](operacao/nuvem-opcional.md) |

## O que cada serviço precisa ter

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
| Exemplo de borda | [`borda-os-service.yaml`](../k8s/exemplos/borda-os-service.yaml) | [`borda-billing-service.yaml`](../k8s/exemplos/borda-billing-service.yaml) | [`borda-execution-service.yaml`](../k8s/exemplos/borda-execution-service.yaml) |

Para escrever os manifests de um serviço novo, nesta ordem:

1. **Imagem e overlays.** `Dockerfile` na raiz, com os `ARG` `GIT_SHA` e `GIT_DATE`: quando o serviço entra como vizinho no CD de outro, a imagem dele sai do `docker build` do checkout, em paralelo com os outros builds. `k8s/overlays/kind-ci/kustomization.yaml`, o overlay do CD, ao lado de `kind` e `k3s`: sem ele, o `implantar-servicos.sh` falha nomeando o serviço e o commit, antes de construir qualquer imagem. A imagem do serviço leva o nome fixo `pytstop-<nome>` e `imagePullPolicy: IfNotPresent`.
   - A tag vem na implantação: o script gera `k8s/overlays/execucao/` (o overlay pedido com a imagem trocada pelo `images:` do kustomize), aplica e o apaga no fim. O diretório não pode existir no repositório e entra no `.gitignore`; se uma execução morreu no meio, apague `k8s/overlays/execucao` antes da próxima.
   - Toda outra imagem dos manifests (banco, exporter, initContainers, volumes de imagem) tem de estar na [tabela de versões](componentes-e-versoes.md#componentes-e-versões), com a mesma tag: o script confere antes de construir e para nomeando a imagem que falta.
2. **Secrets.** Nenhum `Secret` nos manifests: os do serviço vêm do `make deploy` e entram por `secretKeyRef`, com os nomes e as chaves da tabela [Segredos gerados](segredos.md#segredos-gerados). Sem o `rabbitmq` e o do banco, o script para antes do apply pedindo o `make deploy`.
3. **Banco.** StatefulSet, Service e o exporter como sidecar, no mesmo pod.
   - No PostgreSQL, o smoke entra no banco pelo nome da tabela acima: o StatefulSet tem o nome do Service do banco, então o pod é `<banco>-0`, e o contêiner do banco se chama `postgres` (o `kubectl exec -c postgres` da prova do `127.0.0.1`). Com outro nome, a etapa falha com `no answer from <banco>-0`. O controle da NetworkPolicy abre a conexão com `python`, por `kubectl exec -c api`, a partir do pod da API, então o contêiner da API se chama `api` e a imagem dela traz o `python` no `PATH`.
   - Um papel por uso ([ADR-042](arquitetura/adr/fase4/042-cicd-e-deploy-kubernetes.md)): cada processo monta a `DATABASE_URL` (ou a `MONGODB_URI`) no pod, por expansão de variável, com a senha do papel da tabela acima, e nenhum processo do serviço usa o superusuário `postgres`, que só inicializa o banco.
   - No PostgreSQL, os papéis nascem de um script de init que o serviço traz num ConfigMap montado em `/docker-entrypoint-initdb.d`: a imagem o roda uma vez, na primeira inicialização do volume, com as senhas lidas do ambiente do contêiner do banco, nunca de argumento. Se o init falhar no meio, o volume fica inicializado sem os papéis: apague o PVC do banco.
   - O script abre, antes do primeiro comando com senha, desligando todo parâmetro que grava o texto do comando (o `psql` troca `:'senha'` pelo valor antes de enviá-lo, e o servidor a recebe em claro; o mecanismo está em [Troca de senha do banco](segredos.md#troca-de-senha-do-banco)):

     ```sql
     SET log_statement = 'none';
     SET log_min_error_statement = 'panic';
     SET log_min_duration_statement = -1;
     SET log_min_duration_sample = -1;
     SET log_transaction_sample_rate = 0;
     ```

   - As tabelas nascem do Job, depois do script, e por isso o papel da aplicação ganha o DML por `ALTER DEFAULT PRIVILEGES FOR ROLE <dono>`, que cobre também a `alembic_version`, lida pelos pods para esperar a migração. Um `GRANT` sobre as tabelas existentes não alcançaria nenhuma.
   - O StatefulSet do PostgreSQL define `POSTGRES_INITDB_ARGS="--auth-host=scram-sha-256 --auth-local=scram-sha-256"` (requisito do ADR-042). A imagem oficial deixa o socket, o `127.0.0.1` e o `::1` em `trust`, e o exporter conecta por `127.0.0.1`: sem os argumentos, a senha do papel dele não seria conferida, e um exporter comprometido entraria como `postgres`. Os argumentos valem só na primeira inicialização do volume, e o `psql` dentro do contêiner passa a pedir a senha (`PGPASSWORD="$POSTGRES_PASSWORD"` e `-w`, como na [troca de senha do banco](segredos.md#troca-de-senha-do-banco)).
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
- a NetworkPolicy do banco: um controle, em que o pod da API (do próprio namespace) conecta à porta do banco, e a prova, em que o `rabbitmq-0` da plataforma não conecta. A conexão do `rabbitmq-0` tem de esgotar o prazo de 3 s, porque o kindnet (a rede do kind) descarta o pacote barrado; conexão aceita, recusada ou nome que não resolve reprovam, e o prazo esgotado só vale se o controle conectou;
- somente no OS, a saída do notificador: a API conecta ao broker em 5672, o notificador conecta ao Mailpit em 1025 e a conexão dele ao mesmo broker esgota 3 s. Esse bloqueio só aprova com o controle da API conectado; erro DNS, recusa, pod ausente e falha do `kubectl` reprovam. O pod Running usa `app: os-service-notificador`, contêiner `notificador` e Python no `PATH`. O prazo remoto adicional é 5 s e o externo é 20 s; saída parcial seguida de erro do transporte não constitui prova.

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

Os testes dos dois scripts ([`test_implantar_servicos.py`](../tests/test_implantar_servicos.py) e [`test_smoke_servicos.py`](../tests/test_smoke_servicos.py)) rodam com `docker`, `kind`, `kubectl`, `curl`, `sleep` e `date` falsos e conferem a ordem de cada namespace, os prazos, cada etapa reprovando o que deve (cada código HTTP errado, cada réplica fora do lugar), as esperas pelo tempo e o nome do serviço em toda falha.

O ensaio com os três serviços reais no kind (tempos, memória e CPU de cada pod contra o orçamento do ADR-042, e a saída do smoke) está em [`docs/operacao/ensaio-integrado.md`](operacao/ensaio-integrado.md).
