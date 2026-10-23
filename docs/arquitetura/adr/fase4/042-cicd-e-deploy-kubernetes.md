# CI/CD por serviço com deploy em kind

> [↑ Raiz do projeto](../../../../README.md) · [↑ Arquitetura](../../README.md)

* Status: Aceita, com a [emenda de 18/10/2026](#emenda-de-18102026)
* Data: 2026-10-06

## Contexto e Problema

O [enunciado](../../../requisitos/fase4/desafio-tech-fase-4.md) pede que cada microsserviço tenha pipeline independente de integração e entrega contínuas (CI/CD) com build, testes automatizados, verificação de qualidade e deploy automatizado em Kubernetes (l. 88-94), e repositórios protegidos, com pull request (PR) obrigatório e checagens automáticas na `main` (l. 95). O deploy automatizado volta na seção de infraestrutura (l. 100), os pipelines estão entre os entregáveis de cada repositório, ao lado do Dockerfile e dos manifestos (l. 109-110), e o vídeo mostra o deploy de pelo menos um serviço com validação de testes (l. 121). Na [gap analysis](../../../requisitos/fase4/gap-analysis-fase-4.md), são os requisitos não funcionais RNF-042, RNF-043, RNF-048 e RNF-049.

A fase 3 deixou três lições, registradas no p3 (código da fase 3, commit `08dcffe`):

- O CD do monolito disparava no push sem depender dos testes: o job `image` não tinha `needs`.
- O alvo de nuvem era o Amazon EKS do AWS Academy (ADR-030, ADR-033): credencial de cerca de 4 horas, regravada por uma pessoa nos segredos do GitHub a cada sessão do laboratório, sem OpenID Connect (OIDC) possível; sem ela, o `deploy-eks` virava no-op com aviso.
- A proteção da `main` só foi ligada em 03/09/2026, depois de um bootstrap com push direto autorizado, e a avaliação contou 29 commits diretos na aplicação e 11 na Lambda. A proteção clássica de branch também não aparece para a banca: a API do GitHub responde 404 a quem não é administrador (ADR-033 do p3, adendo h).

Na Azure, a fase 2 esbarrou nas restrições da assinatura Azure for Students (ADR-025 do p3, adendo): regiões restritas, AKS limitado às famílias de máquina virtual (VM) v5 a v7, quota zero nelas em todas as regiões permitidas e pedido de aumento negado. VM avulsa com k3s é aceita. A fase 2 já autenticava o GitHub Actions na Azure por OIDC, com credencial federada escopada a um environment e papel Contributor na assinatura (ADR-025 do p3).

Em Estrutura de Microsserviços Parte II, cada equipe tem o seu pipeline, com testes a cada commit (Aula 04), e a Aula 05 compara estratégias de deploy e liga o Rolling Update a ferramentas de atualização progressiva como o Kubernetes. Proteção de branch e ferramenta de CI/CD não aparecem no material.

**Como dar a cada serviço um pipeline próprio, com deploy em Kubernetes validado por testes, sem credencial que expire, sem pessoa no caminho e sem nenhum commit direto na `main`?**

## Decisão

### Workflows e jobs

Três workflows em cada repositório de serviço (OS Service, de ordens de serviço; Billing Service; Execution Service, do contexto Execução), com jobs de nome estável que viram checks obrigatórios; `make check` reproduz o CI na máquina local. O `platform` tem dois, nas duas últimas linhas. Esta é a lista canônica de nomes, a que a gap analysis e a [RFC-004](../../rfc/fase4/rfc-004-microsservicos-saga.md) remetem:

| Workflow | Gatilho | Jobs |
|---|---|---|
| `ci.yml` | PR; chamado pelo `cd.yml` na `main` | `lint` (ruff e import-linter), `type-check` (mypy strict), `security` (bandit), `test` (unitário, integração, contrato e BDD, *behavior-driven development*, com gate de cobertura de 95% e `diff-cover` de 90% no código novo, [ADR-041](041-estrategia-de-testes-e-qualidade.md)), `sonarqube` (depois de `test`), `build` |
| `security.yml` | PR; chamado pelo `cd.yml` na `main`; semanal | `pip-audit`, `gitleaks`, `trivy` |
| `cd.yml` | push na `main`; `workflow_dispatch` com SHAs fixos | `ci` e `security-scan` → `image` → `deploy-kind` → `deploy-remote` ou `remote-skipped` |
| `ci.yml` do `platform` | PR; chamado pelo `cd.yml` do `platform` na `main` | `manifests`, `contratos`, `gitleaks` |
| `cd.yml` do `platform` | PR, push na `main` e `workflow_dispatch`, sem filtro de caminhos, porque o `deploy-kind` é check obrigatório e tem de rodar em todo PR | `ci` (só fora de PR) → `deploy-kind` (a plataforma no `kind-ci` e o `make smoke`) e `e2e` (a plataforma e os três serviços no `kind-ci`, o smoke por namespace, o `make e2e` e o ZAP), em paralelo |

No `platform`, os checks obrigatórios do ruleset da `main` são `manifests`, `contratos` e `gitleaks`, do `ci.yml`, e `deploy-kind`, do `cd.yml`. O `e2e` do `cd.yml` ainda não é obrigatório: vira depois de alguns runs verdes na `main`, como o `deploy-kind` virou.

Os testes seguem o [ADR-041](041-estrategia-de-testes-e-qualidade.md). Os nomes de job ficam em inglês, o padrão técnico do ADR-009 do p3. A execução semanal do `security.yml` acha vulnerabilidade publicada (CVE) em dependência ou imagem base sem esperar o próximo PR. O `cd.yml` tem `concurrency` por repositório, sem cancelar a execução em curso, para que dois pushes seguidos não implantem fora de ordem. O `platform` tem pipeline próprio para a infraestrutura compartilhada, os testes ponta a ponta (E2E) e a varredura OWASP ZAP (RNF-049).

### Proteção da `main` (RNF-043)

Cada repositório nasce com `auto_init`, o único commit fora de PR, e recebe em seguida a proteção da `main`: PR obrigatório, administradores incluídos, histórico linear, conversas resolvidas, sem force push nem exclusão, só squash merge. Não se exige aprovação de revisor, mas toda thread de revisão, inclusive do Copilot, precisa ser resolvida. Os checks viram obrigatórios assim que o primeiro workflow existe, e a entrega confere que todo commit first-parent da `main` referencia um PR.

Além da proteção clássica, cada repositório tem um ruleset na `main` com PR obrigatório, os checks obrigatórios pelos nomes exatos dos jobs, histórico linear e bloqueio de force push e de exclusão. Ruleset ativo é visível a quem tem leitura no repositório, ao contrário da proteção clássica. A evidência para a banca é o link do ruleset no índice da entrega e o resumo da saída de `gh api` em [`protecao-da-main.md`](../../../entrega/fase4/evidencias/protecao-da-main.md).

### CD a cada commit na `main` (RNF-042)

O CD só começa depois que o CI daquele commit passa:

- `ci` e `security-scan`: o `cd.yml` chama o `ci.yml` e o `security.yml` como workflows reutilizáveis (`workflow_call`), e o `image` depende dos dois. O commit da `main` passa pelos mesmos checks do PR antes de virar imagem, e o CI não roda uma segunda vez no push.
- `image`: constrói a imagem uma vez e a publica no GitHub Container Registry (GHCR) com tag igual ao SHA do commit, usando o `GITHUB_TOKEN` do workflow (`packages: write`), sem token pessoal. Gera junto o SBOM, a lista de componentes da imagem, em SPDX (`--sbom=true` do BuildKit), e exporta o tar da imagem como artefato. O build usa cache de camadas do BuildKit (`type=gha`) e cache do `uv`.
- `deploy-kind`, o deploy obrigatório: cria um kind efêmero no runner com os mesmos alvos do ambiente local, pelo `scripts/ci/deploy-kind.sh` do `platform` (`make -C platform kind-up deploy` com o overlay `kind-ci`), e carrega o tar do `image` (`kind load image-archive`), de modo que o E2E testa a mesma imagem que vai ao GHCR e, se o deploy remoto estiver ligado, ao cluster remoto.

  Os dois serviços vizinhos e o `platform` entram no SHA da última execução verde do CD de cada um, consultado na API do GitHub com `branch=main` e `event=push` (o CD do `platform` roda também em PR), e não no último commit da `main`; os vizinhos são construídos desse código. Sem `cd.yml` ou sem execução verde, entra o último commit da `main` do repositório, com um aviso no run. Desde 19/10/2026 os três serviços têm CD verde na `main`, e esse caminho fica como contingência. Um `workflow_dispatch` com SHAs fixos reexecuta uma combinação. Os segredos de runtime nascem no run. Antes do E2E, um smoke por namespace confere cada serviço, e o summary nomeia o serviço que falhou. O job só fica verde se o E2E do `platform` passar ([ADR-041](041-estrategia-de-testes-e-qualidade.md)).
- `deploy-remote`, o gancho opcional e desligado: com a variável `DEPLOY_REMOTO_HABILITADO` igual a `true`, e só a partir da `main`, implanta num cluster persistente o mesmo digest que passou no kind, pelo `scripts/ci/deploy-remoto.sh` do `platform` no commit usado no kind. Com outro valor, ou sem a variável, roda no lugar dele o `remote-skipped`, que só registra o aviso, o padrão do `deploy-eks` da fase 3 (ADR-033). O estado entregue o deixa desligado ([abaixo](#deploy-remoto-opcional-e-desligado)).

A independência pedida na l. 90 está no que cada pipeline controla: build, testes, análise, imagem e deploy de cada serviço saem do seu repositório, com os seus checks, e nenhum pipeline publica ou implanta a imagem de outro. O kind é o ambiente de integração: sobe os vizinhos na última versão verde para que o E2E prove a saga com os três serviços, e uma falha ali aponta, no summary, o serviço responsável.

O `cd.yml` do `platform` tem o mesmo ambiente de integração no job `e2e`, que roda em pull request, em push na `main` e sob demanda, em paralelo com o `deploy-kind`, em 50 minutos e só com a permissão `contents: read` (os quatro repositórios são públicos). A plataforma é a do commit do run, e cada serviço entra no commit do último CD verde dele, pela mesma consulta (`branch=main`, `event=push`) e com o mesmo fallback, a `main` com aviso, enquanto o serviço não tem run verde. Os três são construídos do código, sem imagem do registry. Depois do smoke por namespace vêm o `make e2e` e o ZAP baseline na borda ([ADR-041](041-estrategia-de-testes-e-qualidade.md)), que roda mesmo com o E2E reprovado, mas não sem o smoke verde. O job varre os relatórios do E2E atrás de segredo antes de publicar os artefatos `e2e-kind` e `zap-baseline` por 90 dias, escreve minutos e memória no summary mesmo com falha e roda o diagnóstico na falha ou no cancelamento. Ele não substitui o `deploy-kind` de cada serviço: pega o que o `platform` quebra nos serviços antes do merge.

O overlay `kind-ci` é enxuto: sem Loki, Promtail e Grafana, uma réplica por Deployment e teto de 1 réplica no autoescalonamento horizontal (HPA). Orçamento de memória, com os valores do p3 onde o componente já existia e estimativas para os novos, e o maior uso medido no runner:

| Componente | Memória (requests/limits) | Origem | Medido no runner |
|---|---|---|---|
| API de cada serviço (3) | 256/512 Mi | p3 | de 76 a 106 Mi |
| relay, consumidor, `prazos` e `notificador` (9 processos) | 128/256 Mi cada | relay do p3 | de 55 a 84 Mi |
| PostgreSQL (2) | 128/512 Mi | p3 | 48 e 61 Mi, com o exporter |
| MongoDB | 256/1024 Mi | estimativa | 143 Mi, com o exporter |
| exportadores de banco (3) | 32/64 Mi cada | estimativa | no pod do banco |
| RabbitMQ | 256/1024 Mi | estimativa | 214 Mi |
| Kong (proxy e controlador) | 384/768 Mi | estimativa | 308 Mi |
| Prometheus | 192/512 Mi | p3 | 90 Mi |
| Jaeger | 128/512 Mi | p3 | 28 Mi |
| Mailpit e kube-state-metrics | 64/128 Mi cada | p3 | 18 e 14 Mi |
| Total, sem metrics-server e Jobs | cerca de 3,5/8,9 GiB | | nó do kind inteiro, com o próprio Kubernetes: working set de até 3,0 GiB e pico de 7,4 GiB no cgroup |

O Prometheus retém 15 dias, num PVC (volume persistente do Kubernetes) de 2 Gi no lugar do `emptyDir` da fase 3, nos overlays `kind` e `k3s`: o painel de volume diário de OS pede dias de histórico, e com a retenção de 2 dias do kind mostraria no máximo duas barras. O `kind-ci` segue com `emptyDir` e 2 dias, porque o runner é descartável. O limite de tamanho (`retention.size`) fica em 1536MB, três quartos do volume, porque o WAL conta nele. O volume não muda a tabela de memória.

O total estimado fica abaixo de 10 GiB no runner padrão de 16 GB, o que o GitHub dá a repositório público; os quatro repositórios da fase 4 são públicos, e o orçamento depende disso. Cada job tem `timeout-minutes`, cada etapa do deploy tem `kubectl wait --timeout`, e o `deploy-kind` mede minutos e pico de memória e os escreve no summary.

A coluna medida vem do `deploy-kind` do CD do OS Service, com os três serviços:

- O que rodou: o [run 38837346818](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-os-service/actions/runs/38837346818), de 15/10/2026, no runner `ubuntu-24.04` de 16 GB: a plataforma no `kind-ci` (`platform` em `22eb797`), os três serviços (OS Service em `e2bf48d`, Billing em `d1003a3` e Execução em `301052a`), o smoke de cada namespace e o E2E.
- Por componente: o maior uso de cada pod que o `kubectl top` mostrou nas amostras a cada 5 s; o pod do banco conta junto o exporter, sidecar dele.
- Duração das etapas: a criação do kind levou 45 s, a plataforma 50 s, os três serviços 1 min 13 s, o smoke 21 s e o E2E 3 min 25 s, 6 min 34 s no total.
- Memória do nó do kind: o nó é um container, e a memória dele é a do seu cgroup, o grupo de controle do kernel que limita e conta o que os processos do container usam. O working set, a memória em uso sem o cache de arquivos que o kernel devolve sob pressão (a conta que o kubelet usa para despejar pod), chegou a 3,0 GiB; o pico do cgroup, que conta também o cache de arquivos, a 7,4 GiB, nos 15,6 GiB do Docker do runner.
- Só a plataforma: três execuções do `deploy-kind` do `platform`, em 06/10/2026 ([1](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-platform/actions/runs/37556133536), [2](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-platform/actions/runs/37556562779) e [3](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-platform/actions/runs/37556993602)), levaram de 3 min 14 s a 3 min 31 s, com working set de até 1,5 GiB no nó (cerca de 0,5 GiB do próprio Kubernetes) e pico de 3,5 GiB no cgroup.

### Deploy remoto opcional e desligado

A fase 4 não liga nuvem: o deploy obrigatório e único é o kind efêmero do runner, e o que fica de cada execução são os relatórios do E2E, no artefato `e2e-kind`, por 90 dias. O enunciado pede deploy automatizado em Kubernetes e não cita nuvem, e a infraestrutura AWS da fase 3 já foi desmontada. Para o caso de a avaliação pedir um ambiente que fique de pé, o CD tem um gancho neutro de provedor, desligado:

- Variáveis: a `DEPLOY_REMOTO_HABILITADO` liga o job, e ela, a do contexto do kubeconfig e a do overlay (padrão `k3s`, o overlay que os manifests mantêm para um cluster persistente genérico) estão na tabela de [nuvem opcional](../../../operacao/nuvem-opcional.md#para-ligar). Nenhum dos quatro repositórios tem variável de Actions no estado entregue; as da organização só um administrador lista, e o último CD do OS Service na `main` rodou o `remote-skipped`.
- Script: `scripts/ci/deploy-remoto.sh --contexto <contexto> --overlay <overlay> --servico <serviço> --imagem <referência>@sha256:<digest>`, do `platform`. Roda a partir do checkout do serviço, recusa imagem sem digest, contexto vazio, overlay que não é um nome simples e render com objeto fora do namespace do serviço, fixa a imagem pelo digest num overlay gerado e implanta na mesma ordem e com os mesmos prazos do `implantar-servicos.sh` do kind.
- Acesso: o `cd.yml` entregue não tem segredo, `environment` nem `id-token` no `deploy-remote`; quem ligar o job põe o kubeconfig num segredo de um `environment` restrito à `main`, ou o login do provedor, no passo de acesso. Antes de qualquer coisa, o job confere que o commit do `platform` usado no kind está na `main` do `platform`.
- Receitas: EKS no AWS Academy, como na fase 3, e k3s numa VM da Azure, como na fase 2, em [nuvem opcional](../../../operacao/nuvem-opcional.md), não executadas nesta fase.

### Segredos e configuração

O CD não lê segredo do GitHub: o registry usa o `GITHUB_TOKEN` do workflow, e os segredos de runtime nascem no cluster.

| O quê | Onde e como gira |
|---|---|
| Registry (GHCR) | `GITHUB_TOKEN` do workflow |
| Acesso a um cluster remoto (kubeconfig ou credencial do provedor) | só existe se alguém ligar o deploy remoto, num segredo de `environment` restrito à `main` ([nuvem opcional](../../../operacao/nuvem-opcional.md)) |
| `MP_ACCESS_TOKEN`, `MP_WEBHOOK_SECRET` | nunca no GitHub: as credenciais de teste ficam no ambiente do shell de quem roda o `make mp-sandbox` no kind local, e num cluster remoto o Secret `billing-mercadopago` é criado no cluster pelo dono do ambiente ([ADR-040](040-integracao-mercado-pago.md)) |
| Chave RSA do JSON Web Token (JWT) e chave HMAC (código de autenticação de mensagem com hash) do link de decisão | geradas no cluster; a HMAC gira apagando o Secret, reimplantando e reiniciando o Billing, que a lê no start, a RSA em duas etapas, com a chave que entra e depois a que sai publicadas no JWKS ao lado da que assina ([ADR-039](039-autenticacao-entre-servicos.md)) |
| `ENCRYPTION_KEY`, que cifra os dados pessoais no OS Service | gerada uma vez e nunca regenerada; girá-la exige recifrar os dados e recalcular o hash do documento |
| Senhas dos bancos: no PostgreSQL de cada serviço, uma por papel (o superusuário `postgres`, que só inicializa o banco; o dono das tabelas, com DDL, que o Job de migração usa; o da aplicação, só com DML nas tabelas do dono, que os processos usam; e o do exporter, com `pg_monitor`); no MongoDB do Billing, o root, o `billing` e o `exporter`, mais o keyfile do replica set | geradas no cluster; com um papel por uso, uma injeção de SQL ou um processo comprometido do serviço não chega ao superusuário. O exporter, sidecar do pod do banco, chega ao PostgreSQL pela loopback, e a imagem oficial deixa o socket, o `127.0.0.1` e o `::1` em `trust`: sem senha, um sidecar comprometido entraria como `postgres`. Por isso os manifests do banco de cada serviço definem `POSTGRES_INITDB_ARGS="--auth-host=scram-sha-256 --auth-local=scram-sha-256"`, requisito do contrato com os serviços. O banco só aplica as senhas do Secret e esse `initdb` na primeira inicialização do volume, e os papéis do PostgreSQL nascem num script de init dos manifests do serviço; as senhas giram com `ALTER ROLE` ou `db.changeUserPassword`, com a senha pela entrada padrão do `kubectl exec` e nunca por argumento nem no log do servidor, e o restart de quem as lê ([troca de senha do banco, no README](../../../../README.md#troca-de-senha-do-banco)) |
| Senhas dos usuários do RabbitMQ, um por serviço | geradas no cluster. A senha nova vai para o Secret do broker (`rabbitmq-credenciais`): a de um usuário de serviço vale no `make deploy` seguinte, que a aplica no broker, pelo Job de usuários, e no Secret `rabbitmq` do serviço, e chega aos pods dele depois do restart; a do admin, no próximo boot do broker ([passo a passo](../../../segredos.md#troca-de-senha-do-rabbitmq)) |
| Senha do `admin`, o único usuário semeado no OS Service, e a do Grafana | geradas no cluster; o E2E lê a do `admin` no Secret e, com o token dele, cadastra pela API um atendente e um mecânico, com e-mail e senha aleatórios |
| Desenvolvimento local | `.env.example` com valores de demonstração marcados (`gitleaks:allow`) |

Um script do `platform`, o `scripts/gerar-segredos.sh`, chamado pelo `make deploy` antes do apply, trata os segredos de runtime:

- Valores: as senhas e as chaves saem do `openssl rand`, e a chave RSA, do `openssl genpkey` (2048 bits, PKCS#8); cada valor é mascarado com `::add-mask::` antes do uso, a chave PEM uma linha por vez, porque o comando vale até o fim da linha.
- Secrets de origem: cria cada um só se ele ainda não existir, ou seja, no primeiro deploy de cada cluster. O RabbitMQ lê a senha do admin (o `admin.json` das definitions) só no boot, e uma senha nova com o broker de pé deixaria sem acesso o Job que cria os usuários.
- Conferência antes de gerar: o script confere todas as fontes antes de gerar qualquer valor e para o deploy sem gravar nada em dois casos. A fonte que existe sem uma das chaves do contrato, porque o pod que a lê não subiria e o script nunca reescreve uma fonte. E a fonte que guarda estado no banco de um serviço (as senhas do banco, a `ENCRYPTION_KEY` e a senha do `admin`) e sumiu com o volume do banco de pé, porque uma senha nova não vale para o volume e uma `ENCRYPTION_KEY` nova deixaria ilegível o que já foi cifrado: o caminho é devolver o Secret. Erro ao listar os volumes também para o deploy. A chave RSA e a HMAC nascem de novo nesse caso, e apagar o Secret é como a HMAC gira.
- Secret derivado: a senha de cada usuário do RabbitMQ fica no namespace do broker, cujo Job cria os usuários, e o script a copia, em todo deploy, para o Secret `rabbitmq` do namespace do serviço, já na URL de conexão.
- URL de conexão: a chave `RABBITMQ_URL` do Secret `rabbitmq`, `amqp://<usuario>:<senha>@rabbitmq.pytstop-plataforma.svc.cluster.local:5672/%2F`, com o vhost `/` codificado como manda a especificação de URI AMQP do RabbitMQ.
- Onde roda: no kind do CI, no runner, e os valores morrem com ele; num cluster remoto, na máquina de quem roda o `make deploy` da plataforma, e os valores ficam no cluster, sem passar pelo GitHub.

A guarda de boot do p3, que recusa literal de demonstração fora do ambiente de desenvolvimento, passa a cobrir a chave RSA.

### Topologia e rede

Cada serviço tem namespace próprio (`pytstop-os`, `pytstop-billing`, `pytstop-execucao`) com o seu banco, os seus Secrets e o seu Job de migração ou de inicialização ([ADR-037](037-banco-por-servico.md)). RabbitMQ, Kong, Mailpit e a observabilidade ficam em `pytstop-plataforma`. O metrics-server, pré-requisito do HPA, fica em `kube-system`: no kind, o `platform` o instala, e o k3s já traz o seu. O cluster kind se chama `pytstop-p4`, para não colidir com o da fase 3 na máquina de quem roda as duas.

Cada namespace de serviço tem NetworkPolicy que nega toda entrada por padrão e libera só o necessário: o Kong e o Prometheus para a API, as APIs do Billing e da Execução para o conjunto de chaves públicas (JWKS) do OS Service, a API da Execução para a do Billing, o Prometheus para as portas de métricas dos processos e do exporter, e o próprio namespace para o banco. A saída fica livre, com uma exceção: o `notificador` do OS Service, o único processo com destino de terceiro configurável (o servidor SMTP) e escrita no banco inteiro do serviço, só sai para o DNS, para o PostgreSQL do namespace e para o Mailpit na porta 1025. O namespace `pytstop-plataforma` não tem NetworkPolicy: o RabbitMQ se protege pelo usuário e pelas permissões de cada serviço ([ADR-036](036-mensageria-rabbitmq.md)), e o Mailpit, sem autenticação nem regra de entrada, deixa qualquer pod do cluster ler a caixa, que guarda nome, e-mail e os links de decisão e de pagamento. O Mailpit é só da demonstração, com dados fictícios: um SMTP de verdade exigiria STARTTLS e credencial por Secret, que o `notificador` ainda não implementa. O tráfego interno segue sem TLS, risco aceito do ambiente de demonstração.

### Deploy, saúde e rollback

Rolling Update, o padrão do Deployment no Kubernetes e a estratégia que a Aula 05 liga a ele. Nos serviços SQL, o Job de migração roda antes do rollout; no Billing, o Job de inicialização.

- Saúde: a API tem liveness em `/api/v1/saude`, sem dependências, como no p3, e readiness em `/api/v1/saude/pronto`, que confere só o banco. Com o broker fora do ar, a API continua no Service, porque a outbox segura as mensagens. Relay, consumidor e `prazos`, sem HTTP de negócio, usam heartbeat em arquivo, como o relay do p3, e ficam prontos quando a conexão está estabelecida.
- Encerramento gracioso: no SIGTERM, o processo para de consumir, conclui a mensagem em curso e fecha as conexões, dentro de um `terminationGracePeriodSeconds` maior que o tempo de tratar uma mensagem.
- Convívio de versões: durante o Rolling Update, versões antiga e nova coexistem. Migrações seguem expandir e contrair, compatíveis com a versão anterior, e mensagens seguem a regra de versão do [ADR-036](036-mensageria-rabbitmq.md), com leitor tolerante e consumidor implantado antes do produtor numa mudança que quebra.
- Rollback: `kubectl rollout undo`, sem desfazer migração. E2E vermelho depois do `image` não chega ao deploy remoto, e `main` vermelha se corrige com PR de revert imediato.

## Alternativas Consideradas

* Pipeline por repositório, kind obrigatório e deploy remoto desligado
* k3s na Azure como alvo persistente, por OIDC
* EKS no AWS Academy, como na fase 3
* AKS na Azure for Students
* Argo CD (GitOps)
* Só kind

Descartado pelo enunciado: deploy manual, porque a l. 94 pede deploy automatizado.

### Pipeline por repositório, kind obrigatório e deploy remoto desligado

* Bom, porque cumpre o enunciado em cada repositório sem credencial externa: o deploy em Kubernetes acontece a cada push na `main`, validado pelo E2E dos três serviços sobre a mesma imagem que vai ao GHCR
* Bom, porque nada expira durante a avaliação e ninguém renova credencial: o deploy validado não depende de nuvem, de crédito nem de administrador da organização
* Bom, porque reaproveita o kind no runner das fases 2 e 3, e o gancho desligado deixa pronto o caminho para um cluster persistente, se a avaliação pedir
* Ruim, porque nada sobrevive ao job: a evidência é o relatório do E2E, guardado como artefato, e o vídeo mostra o kind
* Ruim, porque cada CD constrói os dois serviços vizinhos e sobe a plataforma: mais minutos por deploy e boa parte da memória do runner
* Ruim, porque o `deploy-kind` de um serviço depende da última versão verde dos vizinhos e do `platform`: uma regressão que só aparece na integração deixa vermelho o CD de quem não a causou, até o revert

### k3s na Azure como alvo persistente, por OIDC

* Bom, porque um ambiente de pé, com hostname e HTTPS, receberia o webhook real do Mercado Pago
* Bom, porque o OIDC dispensa credencial guardada, e a fase 2 já rodou k3s numa VM da mesma assinatura
* Ruim, porque depende de crédito da Azure aprovado, de uma VM a religar antes de cada gravação e de um passo humano com Terraform e credenciais federadas
* Ruim, porque as variáveis e os segredos da organização dependem de um administrador dela
* Ruim, porque o enunciado não pede nuvem: o esforço não muda o que a avaliação confere

### EKS no AWS Academy, como na fase 3

* Bom, porque é Kubernetes gerenciado
* Bom, porque já tinha Terraform e pipeline prontos na fase 3
* Ruim, porque a credencial do Learner Lab dura cerca de 4 horas e alguém precisa regravá-la a cada sessão; sem ela o deploy vira no-op, e o "automatizado" passa a depender de uma pessoa
* Ruim, porque, sem OIDC, a credencial fica em segredo do GitHub, contra a política de segredos desta fase

### AKS na Azure for Students

* Bom, porque seria Kubernetes gerenciado, com OIDC na Azure
* Ruim, porque a assinatura o bloqueia: o AKS só aceita VMs das famílias v5 a v7, com quota zero em todas as regiões permitidas, e o pedido de aumento foi negado na fase 2

### Argo CD (GitOps)

* Bom, porque o cluster puxa o estado do Git, corrige desvio e dispensa credencial de cluster no CI
* Ruim, porque não serve ao kind do runner, que morre com o job; ali o deploy por push continua necessário
* Ruim, porque o CI teria de gravar cada tag nova no estado desejado, e a `main` protegida só aceita PR
* Ruim, porque o k3s de nó único ganharia mais um componente

### Só kind

* Bom, porque atende o enunciado com custo zero e sem credencial
* Ruim, porque, se a avaliação pedir um ambiente que fique de pé, nada estaria pronto: o gancho desligado custa só um job pulado por execução

## Consequências

### Positivas

* RNF-042, RNF-043, RNF-048 e RNF-049 atendidos em cada repositório, com a proteção da `main` visível à banca pelo ruleset
* A imagem testada no kind é a mesma que vai ao GHCR e, se ligado, ao cluster remoto
* Nenhuma credencial de nuvem ou de registry guardada no GitHub, e os segredos de runtime nascem no cluster
* Zero commit direto na `main` desde a criação dos repositórios, conferível pelo histórico

### Negativas

* O caminho até o deploy validado é longo: o CI inteiro do commit, SonarQube incluído, e o E2E do kind. Por isso o trecho de CI/CD do vídeo é gravado antes e editado, com serviço e commit escolhidos no roteiro e os minutos de cada job registrados
* Nenhum ambiente fica de pé: o kind morre com o job, e ligar o deploy remoto exige um cluster e passos do dono do ambiente que não foram executados nesta fase ([nuvem opcional](../../../operacao/nuvem-opcional.md))
* O tráfego interno do cluster corre sem TLS, risco aceito do ambiente de demonstração

### Neutras

* A fase 4 não pede homologação e produção; o fluxo usa só a `main`, sem a separação por branch da fase 3
* O deploy fica no Rolling Update: Blue-Green e Canary (Aula 05) pediriam divisão de tráfego no balanceador ou numa service mesh

## Decisões Relacionadas

- [ADR-019](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p3/blob/main/docs/arquitetura/adr/fase2/019-pipeline-cicd-deploy.md): o kind efêmero no runner segue como deploy obrigatório, agora com três serviços e E2E
- [ADR-025](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p3/blob/main/docs/arquitetura/adr/fase2/025-ambiente-cloud-demonstracao.md): bloqueio do AKS e VM com k3s da fase 2, base da receita de k3s da nuvem opcional
- [ADR-030](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p3/blob/main/docs/arquitetura/adr/fase3/030-cluster-kubernetes-eks.md): o EKS da fase 3, base da receita de EKS da nuvem opcional, fora do estado entregue
- [ADR-033](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p3/blob/main/docs/arquitetura/adr/fase3/033-cicd-multi-repo.md): continuam o pipeline por repositório e o aviso quando o alvo de nuvem não está disponível; proteção tardia e credencial manual são as lições
- [ADR-036](036-mensageria-rabbitmq.md): regra de versão das mensagens no convívio de versões
- [ADR-039](039-autenticacao-entre-servicos.md): chaves do JWT e do link geradas no cluster
- [ADR-040](040-integracao-mercado-pago.md): credenciais do Mercado Pago, fora do GitHub
- [ADR-041](041-estrategia-de-testes-e-qualidade.md): jobs `test` e `sonarqube` e o E2E do `deploy-kind`

## Notas

* Material: Estrutura de Microsserviços Parte II, Aulas 04 e 05; Estrutura de Microsserviços, Aula 01 (pipeline próprio por serviço como benefício)
* Configuração da proteção conferida pela API do GitHub em 06/10/2026 nos quatro repositórios da fase 4
* Rulesets visíveis a quem tem leitura: https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets; k3s: https://docs.k3s.io/; Rolling Update: https://kubernetes.io/docs/concepts/workloads/controllers/deployment/#rolling-update-deployment

## Emenda de 18/10/2026

Decisão do grupo de 14/10/2026: a fase 4 não liga nuvem, e o deploy obrigatório e único é o kind efêmero do runner. Saíram o job `deploy-k3s` e o `k3s-skipped`, a variável `K3S_HABILITADO`, o OIDC com a Azure (a credencial federada, as variáveis `AZURE_*` e o environment `producao`) e os segredos do Mercado Pago na organização, com a dependência de um administrador dela.

Entraram o gancho desligado e neutro de provedor e as receitas de nuvem, descritos em [Deploy remoto opcional e desligado](#deploy-remoto-opcional-e-desligado); o overlay `k3s` dos manifests permanece, como alvo de um cluster persistente genérico.

## Emenda de 19/10/2026: CD reutilizável

Os quatro jobs de CD dos serviços passam a ter uma definição única no Platform, em `.github/workflows/cd-servico.yml`, com `workflow_call`. Recebem `servico` e os quatro `sha_*`; cada caller mantém os gatilhos, a concorrência e os gates locais `ci` e `security-scan`, dos quais a chamada depende. A referência do reusable é um SHA literal, trocado à mão por um PR em cada serviço depois que uma mudança do `cd-servico.yml` entra na `main` do Platform com CD verde (o Dependabot lista a dependência, mas não propõe versão, porque o Platform não publica tag nem release); o commit dos scripts Platform selecionado por `sha_platform` é independente desse pin. Os callers só migram depois da integração da definição compartilhada; os três migraram em 19/10/2026 ([OS #20](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-os-service/pull/20), [Execução #15](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-execution-service/pull/15) e [Billing #19](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-billing-service/pull/19)).

A chamada concede a união das permissões; cada job usa somente as suas. O publicador conserva actions e builders fixados, SBOM obrigatório, proveniência `mode=min` e `provenance-add-gha=false`. O artefato E2E é varrido antes do upload restrito a `reports/e2e/`, por 90 dias. O uv fica em `0.13.0` nos dois CDs. O CD próprio do Platform, inclusive seus gates E2E/ZAP, permanece independente.

O remoto continua opcional, desligado e sem credencial de provedor. O job faz checkout do próprio serviço no commit da imagem e executa o script a partir dele, depois de validar o histórico do Platform: isso evita aplicar o overlay do repositório errado. O contrato completo está no [README](../../../../README.md#cd-reutilizável-dos-serviços), e os passos para autenticação futura permanecem no [runbook](../../../operacao/nuvem-opcional.md).

> [↑ Raiz do projeto](../../../../README.md) · [↑ Arquitetura](../../README.md)
