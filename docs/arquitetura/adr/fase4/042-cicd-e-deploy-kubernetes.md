# CI/CD por serviço com deploy em kind e k3s

> [↑ Raiz do projeto](../../../../README.md) · [↑ Arquitetura](../../README.md)

* Status: Aceita
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

Três workflows em cada repositório de serviço (OS Service, de ordens de serviço; Billing Service; Execution Service, do contexto Execução), com jobs de nome estável que viram checks obrigatórios; `make check` reproduz o CI na máquina local. Esta é a lista canônica de nomes, a que a gap analysis e a [RFC-004](../../rfc/fase4/rfc-004-microsservicos-saga.md) remetem:

| Workflow | Gatilho | Jobs |
|---|---|---|
| `ci.yml` | PR; chamado pelo `cd.yml` na `main` | `lint` (ruff e import-linter), `type-check` (mypy strict), `security` (bandit), `test` (unitário, integração, contrato e BDD, *behavior-driven development*, com gate de 90% e `diff-cover`), `sonarqube` (depois de `test`), `build` |
| `security.yml` | PR; chamado pelo `cd.yml` na `main`; semanal | `pip-audit`, `gitleaks`, `trivy` |
| `cd.yml` | push na `main`; `workflow_dispatch` com SHAs fixos | `ci` e `security-scan` → `image` → `deploy-kind` → `deploy-k3s` ou `k3s-skipped` |

Os testes seguem o [ADR-041](041-estrategia-de-testes-e-qualidade.md). Os nomes de job ficam em inglês, o padrão técnico do ADR-009 do p3. A execução semanal do `security.yml` acha vulnerabilidade publicada (CVE) em dependência ou imagem base sem esperar o próximo PR. O `cd.yml` tem `concurrency` por repositório, sem cancelar a execução em curso, para que dois pushes seguidos não implantem fora de ordem. O `platform` tem pipeline próprio para a infraestrutura compartilhada, os testes ponta a ponta (E2E) e a varredura OWASP ZAP (RNF-049).

### Proteção da `main` (RNF-043)

Cada repositório nasce com `auto_init`, o único commit fora de PR, e recebe em seguida a proteção da `main`: PR obrigatório, administradores incluídos, histórico linear, conversas resolvidas, sem force push nem exclusão, só squash merge. Não se exige aprovação de revisor, mas toda thread de revisão, inclusive do Copilot, precisa ser resolvida. Os checks viram obrigatórios assim que o primeiro workflow existe, e a entrega confere que todo commit first-parent da `main` referencia um PR.

Além da proteção clássica, cada repositório tem um ruleset na `main` com PR obrigatório, os checks obrigatórios pelos nomes exatos dos jobs, histórico linear e bloqueio de force push e de exclusão. Ruleset ativo é visível a quem tem leitura no repositório, ao contrário da proteção clássica. A evidência para a banca é o link do ruleset no índice da entrega e a saída de `gh api` versionada em `docs/entrega/fase4/evidencias/`.

### CD a cada commit na `main` (RNF-042)

O CD só começa depois que o CI daquele commit passa:

- `ci` e `security-scan`: o `cd.yml` chama o `ci.yml` e o `security.yml` como workflows reutilizáveis (`workflow_call`), e o `image` depende dos dois. O commit da `main` passa pelos mesmos checks do PR antes de virar imagem, e o CI não roda uma segunda vez no push.
- `image`: constrói a imagem uma vez e a publica no GitHub Container Registry (GHCR) com tag igual ao SHA do commit, usando o `GITHUB_TOKEN` do workflow (`packages: write`), sem token pessoal. Gera junto o SBOM, a lista de componentes da imagem, em SPDX (`--sbom=true` do BuildKit), e exporta o tar da imagem como artefato. O build usa cache de camadas do BuildKit (`type=gha`) e cache do `uv`.
- `deploy-kind`, o deploy obrigatório: cria um kind efêmero no runner com os mesmos alvos do ambiente local (`make -C platform kind-up deploy`) e carrega o tar do `image` (`kind load image-archive`), de modo que o E2E testa a mesma imagem que vai ao GHCR e ao k3s.

  Os dois serviços vizinhos e o `platform` entram no SHA da última execução verde do CD de cada um, consultado na API do GitHub, e não no último commit da `main`; os vizinhos são construídos desse código. Um `workflow_dispatch` com SHAs fixos reexecuta uma combinação. Os segredos de runtime nascem no run. Antes do E2E, um smoke por namespace confere cada serviço, e o summary nomeia o serviço que falhou. O job só fica verde se o E2E do `platform` passar ([ADR-041](041-estrategia-de-testes-e-qualidade.md)).
- `deploy-k3s`, o alvo persistente: implanta no k3s o mesmo digest que passou no kind. Com a variável da organização `K3S_HABILITADO` diferente de `true`, roda no lugar dele o `k3s-skipped`, que só registra o aviso, o padrão do `deploy-eks` da fase 3 (ADR-033).

A independência pedida na l. 90 está no que cada pipeline controla: build, testes, análise, imagem e deploy de cada serviço saem do seu repositório, com os seus checks, e nenhum pipeline publica ou implanta a imagem de outro. O kind é o ambiente de integração: sobe os vizinhos na última versão verde para que o E2E prove a saga com os três serviços, e uma falha ali aponta, no summary, o serviço responsável.

O overlay `kind-ci` é enxuto: sem Loki, Promtail e Grafana, uma réplica por Deployment e teto de 1 réplica no autoescalonamento horizontal (HPA). Orçamento de memória, com os valores do p3 onde o componente já existia e estimativas para os novos:

| Componente | Memória (requests/limits) | Origem |
|---|---|---|
| API de cada serviço (3) | 256/512 Mi | p3 |
| relay, consumidor e `prazos` (8 processos) | 128/256 Mi cada | relay do p3 |
| PostgreSQL (2) | 128/512 Mi | p3 |
| MongoDB | 256/1024 Mi | estimativa |
| exportadores de banco (3) | 32/64 Mi cada | estimativa |
| RabbitMQ | 256/1024 Mi | estimativa |
| Kong (proxy e controlador) | 384/768 Mi | estimativa |
| Prometheus | 192/512 Mi | p3 |
| Jaeger | 128/512 Mi | p3 |
| Mailpit e kube-state-metrics | 64/128 Mi cada | p3 |
| Total, sem metrics-server e Jobs | cerca de 3,4/8,7 GiB | |

O total fica abaixo de 10 GiB no runner padrão de 16 GB. Cada job tem `timeout-minutes`, cada etapa do deploy tem `kubectl wait --timeout`, e o primeiro run mede minutos e pico de memória e os escreve no summary.

### Alvo persistente: k3s na Azure

VM sob demanda (não Spot) com k3s, de 4 vCPU e 16 GB se a quota permitir, senão de 2 vCPU e 8 GB com o perfil enxuto do `kind-ci`. O Terraform da VM e das credenciais federadas roda uma vez, no passo humano da Azure, com o state num storage account da própria assinatura; o CD não roda Terraform. A VM desliga todo dia pelo auto-shutdown nativo e é religada à mão antes de gravar evidências.

- Acesso sem segredo: o `deploy-k3s` autentica na Azure por OIDC, com credencial federada de subject `repo:<org>/<repo>:environment:producao`. O environment `producao` só aceita a `main`, só esse job tem `id-token: write`, e o papel na Azure é o mínimo no resource group da VM. A API do Kubernetes não fica exposta: o job aplica os manifestos por `az vm run-command`.
- Pré-checagem: antes de implantar, o job confere o estado de energia da VM e o login; VM desligada ou login recusado, como com o crédito esgotado, terminam verdes com aviso.
- Imagem sem token pessoal: o job faz o pull da imagem no nó, também por `az vm run-command`, com o token de curta duração do próprio job, e os pods usam `imagePullPolicy: IfNotPresent`. Com um nó só, HPA e religamento da VM reusam a imagem já gravada no disco do containerd.
- Exposição: hostname do rótulo DNS do IP público da Azure, certificado Let's Encrypt emitido pelo cert-manager para o Kong e Network Security Group (NSG) só com 80 e 443 abertos, mais a porta 22 restrita aos IPs do grupo. Grafana, Jaeger, Prometheus, Mailpit e o console do RabbitMQ ficam acessíveis só por túnel SSH, e o ambiente tem só dados fictícios. Com hostname e HTTPS, o webhook real do Mercado Pago chega ao k3s ([ADR-040](040-integracao-mercado-pago.md)).

### Segredos e configuração

Nenhum segredo de aplicação fica no GitHub, e o inevitável fica na organização, nunca por repositório.

| O quê | Onde e como gira |
|---|---|
| Credencial da Azure | OIDC: token de curta duração por run, nada a girar |
| Registry (GHCR) | `GITHUB_TOKEN` do workflow |
| `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, `K3S_HABILITADO` | variáveis da organização, visíveis só aos repositórios da fase 4 |
| `MP_ACCESS_TOKEN`, `MP_WEBHOOK_SECRET` | segredos da organização, visíveis só ao Billing e lidos só pelo `deploy-k3s` |
| Chave RSA do JSON Web Token (JWT) e chave HMAC (código de autenticação de mensagem com hash) do link de decisão | geradas no cluster; a HMAC gira apagando o Secret e reimplantando, a RSA em duas etapas, com a chave anterior publicada no JWKS ([ADR-039](039-autenticacao-entre-servicos.md)) |
| `ENCRYPTION_KEY`, que cifra os dados pessoais no OS Service | gerada uma vez e nunca regenerada; girá-la exige recifrar os dados e recalcular o hash do documento |
| Senhas dos bancos e dos usuários do RabbitMQ, um por serviço | geradas no cluster; giram com `ALTER ROLE` e `rabbitmqctl change_password`, porque banco e broker só aplicam a senha do Secret na primeira inicialização do volume |
| Senhas dos usuários semeados (`admin`, `atendente`, `mecanico`) e do Grafana | geradas no cluster; o E2E lê as dos usuários no Secret |
| Desenvolvimento local | `.env.example` com valores de demonstração marcados (`gitleaks:allow`) |

Um script do `platform` gera os valores com `openssl rand`, mascara cada um com `::add-mask::` e cria cada Secret só se ele ainda não existir, nos namespaces que o usam; a senha de cada usuário do RabbitMQ vai para o namespace do serviço e para o do broker, cujo init cria os usuários. No kind do CI, o script roda no runner, e os valores morrem com ele; no k3s, roda na própria VM pelo `az vm run-command`, e os valores não passam pelo GitHub. A guarda de boot do p3, que recusa literal de demonstração fora do ambiente de desenvolvimento, passa a cobrir a chave RSA.

### Topologia e rede

Cada serviço tem namespace próprio (`pytstop-os`, `pytstop-billing`, `pytstop-execucao`) com o seu banco, os seus Secrets e o seu Job de migração ou de inicialização ([ADR-037](037-banco-por-servico.md)). RabbitMQ, Kong, Mailpit e a observabilidade ficam em `pytstop-plataforma`. O metrics-server, pré-requisito do HPA, fica em `kube-system`: no kind, o `platform` o instala, e o k3s já traz o seu. O cluster kind se chama `pytstop-p4`, para não colidir com o da fase 3 na máquina de quem roda as duas.

Cada namespace tem NetworkPolicy que nega toda entrada por padrão e libera só o necessário: Kong para os serviços, cada serviço para o próprio banco, Prometheus para as portas de métricas, Execução para o Billing, Billing e Execução para o conjunto de chaves públicas (JWKS) do OS Service, os serviços para o RabbitMQ e o Jaeger, e o OS Service para o Mailpit. O tráfego interno segue sem TLS, risco aceito do ambiente de demonstração.

### Deploy, saúde e rollback

Rolling Update, o padrão do Deployment no Kubernetes e a estratégia que a Aula 05 liga a ele. Nos serviços SQL, o Job de migração roda antes do rollout; no Billing, o Job de inicialização.

- Saúde: a API tem liveness em `/api/v1/saude`, sem dependências, como no p3, e readiness em `/api/v1/saude/pronto`, que confere só o banco. Com o broker fora do ar, a API continua no Service, porque a outbox segura as mensagens. Relay, consumidor e `prazos`, sem HTTP de negócio, usam heartbeat em arquivo, como o relay do p3, e ficam prontos quando a conexão está estabelecida.
- Encerramento gracioso: no SIGTERM, o processo para de consumir, conclui a mensagem em curso e fecha as conexões, dentro de um `terminationGracePeriodSeconds` maior que o tempo de tratar uma mensagem.
- Convívio de versões: durante o Rolling Update, versões antiga e nova coexistem. Migrações seguem expandir e contrair, compatíveis com a versão anterior, e mensagens seguem a regra de versão do [ADR-036](036-mensageria-rabbitmq.md), com leitor tolerante e consumidor implantado antes do produtor numa mudança que quebra.
- Rollback: `kubectl rollout undo`, sem desfazer migração. E2E vermelho depois do `image` não chega ao k3s, e `main` vermelha se corrige com PR de revert imediato.

## Alternativas Consideradas

* Pipeline por repositório, kind obrigatório e k3s opcional via OIDC
* EKS no AWS Academy, como na fase 3
* AKS na Azure for Students
* Argo CD (GitOps)
* Só kind

Descartado pelo enunciado: deploy manual, porque a l. 94 pede deploy automatizado.

### Pipeline por repositório, kind obrigatório e k3s opcional via OIDC

* Bom, porque cumpre o enunciado em cada repositório sem credencial externa: o deploy em Kubernetes acontece a cada push na `main`, validado pelo E2E dos três serviços sobre a mesma imagem que vai ao k3s
* Bom, porque no alvo persistente nada expira durante a avaliação e ninguém renova credencial
* Bom, porque reaproveita o kind no runner das fases 2 e 3 e a VM com k3s da fase 2
* Ruim, porque cada CD constrói os dois serviços vizinhos e sobe a plataforma: mais minutos por deploy e boa parte da memória do runner
* Ruim, porque o `deploy-kind` de um serviço depende da última versão verde dos vizinhos e do `platform`: uma regressão que só aparece na integração deixa vermelho o CD de quem não a causou, até o revert

### EKS no AWS Academy, como na fase 3

* Bom, porque é Kubernetes gerenciado
* Bom, porque já tinha Terraform e pipeline prontos na fase 3
* Ruim, porque a credencial do Learner Lab dura cerca de 4 horas e alguém precisa regravá-la a cada sessão; sem ela o deploy vira no-op, e o "automatizado" passa a depender de uma pessoa
* Ruim, porque, sem OIDC, a credencial fica em segredo do GitHub, contra a política de segredos desta fase

### AKS na Azure for Students

* Bom, porque seria Kubernetes gerenciado na mesma assinatura, com o mesmo OIDC
* Ruim, porque a assinatura o bloqueia: o AKS só aceita VMs das famílias v5 a v7, com quota zero em todas as regiões permitidas, e o pedido de aumento foi negado na fase 2

### Argo CD (GitOps)

* Bom, porque o cluster puxa o estado do Git, corrige desvio e dispensa credencial de cluster no CI
* Ruim, porque não serve ao kind do runner, que morre com o job; ali o deploy por push continua necessário
* Ruim, porque o CI teria de gravar cada tag nova no estado desejado, e a `main` protegida só aceita PR
* Ruim, porque o k3s de nó único ganharia mais um componente

### Só kind

* Bom, porque atende o enunciado com custo zero e sem credencial, e é o plano se o crédito Azure não for aprovado
* Ruim, porque nada sobrevive ao job: evidências e vídeo dependeriam do kind na máquina de um integrante, com a stack inteira disputando memória local

## Consequências

### Positivas

* RNF-042, RNF-043, RNF-048 e RNF-049 atendidos em cada repositório, com a proteção da `main` visível à banca pelo ruleset
* A imagem testada no kind é a mesma que vai ao GHCR e ao k3s
* Nenhuma credencial de nuvem ou de registry guardada, e, no k3s, os segredos de runtime nascem na VM
* Zero commit direto na `main` desde a criação dos repositórios, conferível pelo histórico

### Negativas

* O caminho até o k3s é longo: o CI inteiro do commit, SonarQube incluído, e o E2E do kind antes do deploy. Por isso o trecho de CI/CD do vídeo é gravado antes e editado, com serviço e commit escolhidos no roteiro e os minutos de cada job registrados
* O k3s é um nó só, sem alta disponibilidade, depende de crédito Azure aprovado e fica fora do ar enquanto a VM está desligada
* Variáveis e segredos da organização dependem de um administrador da organização
* Segredo da organização fica ao alcance de qualquer workflow do repositório do Billing, inclusive de um PR que altere um workflow; o risco é aceito porque as credenciais do Mercado Pago são de sandbox e são revogadas ao fim da avaliação
* O tráfego interno do cluster corre sem TLS, risco aceito do ambiente de demonstração

### Neutras

* A fase 4 não pede homologação e produção; o fluxo usa só a `main`, sem a separação por branch da fase 3
* O deploy fica no Rolling Update: Blue-Green e Canary (Aula 05) pediriam divisão de tráfego no balanceador ou numa service mesh

## Decisões Relacionadas

- [ADR-019](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p3/blob/main/docs/arquitetura/adr/fase2/019-pipeline-cicd-deploy.md): o kind efêmero no runner segue como deploy obrigatório, agora com três serviços e E2E
- [ADR-025](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p3/blob/main/docs/arquitetura/adr/fase2/025-ambiente-cloud-demonstracao.md): bloqueio do AKS, VM com k3s e OIDC da fase 2
- [ADR-030](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p3/blob/main/docs/arquitetura/adr/fase3/030-cluster-kubernetes-eks.md): substituído pelo k3s na Azure
- [ADR-033](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p3/blob/main/docs/arquitetura/adr/fase3/033-cicd-multi-repo.md): continuam o pipeline por repositório e o aviso quando o alvo de nuvem não está disponível; proteção tardia e credencial manual são as lições
- [ADR-036](036-mensageria-rabbitmq.md): regra de versão das mensagens no convívio de versões
- [ADR-039](039-autenticacao-entre-servicos.md): chaves do JWT e do link geradas no cluster
- [ADR-040](040-integracao-mercado-pago.md): segredos do Mercado Pago e webhook real no k3s
- [ADR-041](041-estrategia-de-testes-e-qualidade.md): jobs `test` e `sonarqube` e o E2E do `deploy-kind`

## Notas

* Material: Estrutura de Microsserviços Parte II, Aulas 04 e 05; Estrutura de Microsserviços, Aula 01 (pipeline próprio por serviço como benefício)
* Configuração da proteção conferida pela API do GitHub em 06/10/2026 nos quatro repositórios da fase 4
* Rulesets visíveis a quem tem leitura: https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets; OIDC entre GitHub Actions e Azure: https://learn.microsoft.com/en-us/azure/developer/github/connect-from-azure-openid-connect; k3s: https://docs.k3s.io/; Rolling Update: https://kubernetes.io/docs/concepts/workloads/controllers/deployment/#rolling-update-deployment

> [↑ Raiz do projeto](../../../../README.md) · [↑ Arquitetura](../../README.md)
