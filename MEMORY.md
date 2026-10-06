# Project Memory -- postech-sw-arch-p4-platform

<!-- last-consolidated: 2026-10-06 -->

Add-only log of project-specific learnings. New entries go to the top of each section. Never edit historical entries -- add a contradicting entry above instead.

Updated by AI agents at task end per `postech-ai-helper/ai/canonical/task-end-review.md`. The `last-consolidated` marker above is updated only when `/consolidate-memory` runs, not on every append.

## Recent decisions

- 2026-10-06 - Infra compartilhada no namespace `pytstop-plataforma`; cada servico no seu (`pytstop-os`, `pytstop-billing`, `pytstop-execucao`), criado pelo repo do servico - reforca "infraestrutura propria" do enunciado (decisao do coordenador)
- 2026-10-06 - Topologia do RabbitMQ so no `k8s/base/rabbitmq/definitions.json`, importado no boot; servicos so conferem com declaracao passiva (configure `^$`), um usuario por servico criado pelo Job/servico `rabbitmq-usuarios` com as permissoes de `permissoes.json`, retry pelo exchange `pytstop.retry`, DLQ com TTL de 7 dias (dado pessoal) - revisao de seguranca do coordenador
- 2026-10-06 - `pytstop.retry` e topic (o coordenador pediu direct) com permissao de topico por usuario (so a propria fila no retry, so os proprios `evento.<servico>.*` e `comando.*`): RabbitMQ so aplica permissao por routing key em exchange topic, e em direct qualquer servico entregaria mensagem na fila de outro
- 2026-10-06 - Filas quorum com `x-dead-letter-strategy: at-least-once` + `x-overflow: reject-publish` nas filas de trabalho e `.retry` - dead-letter da classic e at-most-once
- 2026-10-06 - Kong por `helm template` versionado (chart kong/kong 3.4.1, Kong 3.9.3, KIC 3.5.13) em `k8s/base/kong/`; plugins como KongClusterPlugin; webhook de admissao desligado (o chart gera chave privada na renderizacao)
- 2026-10-06 - Provisioning do Grafana em `observabilidade/`, fonte unica do kind/k3s (configMapGenerator) e do compose (bind mount)
- 2026-10-06 - `ci.yml` dispara em pull_request, workflow_call e workflow_dispatch (sem push, sem paths-ignore); jobs `manifests` e `contratos` - o CD de cada repo chama o CI
- 2026-10-06 - Repo criado na fase 4 com branch protection na `main` desde o commit inicial (PR obrigatorio, admins incluidos, historico linear, conversas resolvidas, squash only). Motivo: a fase 3 perdeu ponto por commits diretos na main (29 no app, 11 na lambda) - spec `postech-sw-arch-p4/docs/superpowers/specs/2026-10-06-fase-4-bootstrap-design.md`

## Discovered conventions

- 2026-10-06 - `make deploy` aplica as CRDs do Kong (server-side) antes do overlay e recria o Job `rabbitmq-usuarios` (Job e imutavel; o script e idempotente)
- 2026-10-06 - Prometheus raspa pod anotado de qualquer namespace; a porta anotada precisa estar em `ports` do container (relabel `keepequal`) e o label `app` vira o `job`
- 2026-10-06 - Dashboard JSON novo entra no configMapGenerator de `observabilidade/kustomization.yaml`; o `make manifests` reprova o que ficar de fora
- 2026-10-06 - Catalogo de mensagens: `CATALOGO` em `contratos/tests/test_contratos.py` amarra AsyncAPI, schemas, exemplos e `definitions.json`; schemas sao autocontidos e o teste garante `$defs` iguais entre eles

## Gotchas

- 2026-10-06 - rabbitmqadmin 2.35 (da imagem do RabbitMQ) nao tem comando de permissao de topico: permissoes num JSON importado com `rabbitmqadmin definitions import` depois de declarar os usuarios
- 2026-10-06 - RabbitMQ com definitions no boot nao cria o usuario de `RABBITMQ_DEFAULT_USER` (log "Will not seed default virtual host and user"): o admin vem no `admin.json` do diretorio de definitions
- 2026-10-06 - RabbitMQ importa o diretorio de definitions em ordem alfabetica e aborta o boot se uma permissao cita vhost que ainda nao existe: `admin.json` declara o vhost `/`
- 2026-10-06 - Volume inteiro de ConfigMap/Secret como diretorio de definitions faz o RabbitMQ ler `..data`/`..<timestamp>` e falhar com eisdir (sobe vazio): montar arquivo a arquivo com subPath
- 2026-10-06 - `definitions.skip_if_unchanged` grava o hash mesmo quando a importacao falha e o boot seguinte sobe vazio: nao usar
- 2026-10-06 - Probe exec ou healthcheck do RabbitMQ como root antes do boot cria `.erlang.cookie` de root e o broker nao sobe (eacces): rodar como uid 999
- 2026-10-06 - RabbitMQ calcula o limite de memoria sobre a RAM do host, nao do cgroup: `vm_memory_high_watermark.absolute` acoplado ao limite do container
- 2026-10-06 - Fila quorum no RabbitMQ 4: `nack`/`reject` com requeue nao conta no delivery-limit (volta para sempre); so queda sem ack conta (20 e vai para a DLQ). TTL por mensagem so vence na cabeca da fila (ambos testados no kind)
- 2026-10-06 - StatefulSet com pod que nunca fica Ready nao e trocado quando o template muda (forced rollback): apagar o pod
- 2026-10-06 - colima nao compartilha `/private/tmp` com a VM: bind mount de la vira diretorio vazio; usar caminho sob `$HOME`
- 2026-10-06 - make 3.81 do macOS ignora `.SHELLFLAGS`: recipe com laco ou pipe abre com `set -euo pipefail` na propria linha
- 2026-10-06 - Promtail 2.9 nao conversa com o Docker 29 (cliente na API 1.42, minimo 1.44): Promtail 3.6
- 2026-10-06 - `docker compose up --wait` trata container que saiu com 0 como falha: servico de init fica parado com healthcheck
- 2026-10-06 - kubeconform: o repositorio de schemas nao tem `CustomResourceDefinition` (`-skip CustomResourceDefinition`); KongPlugin/KongClusterPlugin pelo catalogo da datree
- 2026-10-06 - KIC 3.x nao publica manifests all-in-one; o `helm template` so gera a IngressClass com `--api-versions networking.k8s.io/v1/IngressClass`
- 2026-10-06 - KongPlugin e namespaced e Ingress de outro namespace nao o enxerga: KongClusterPlugin
- 2026-10-06 - `strip-path` do Kong tira o caminho casado inteiro: rota publica com prefixo proprio usa Service extra com `konghq.com/path`
- 2026-10-06 - Grafana 11.1: `/api/datasources/uid/jaeger/health` responde 500 (plugin so de frontend); testar pelo proxy `/api/datasources/proxy/uid/jaeger/api/services`
- 2026-10-06 - ruff 0.16 formata blocos python dentro de Markdown: `ruff format --check .` pega snippet do README
- 2026-10-06 - Cluster kind da fase 4 e `pytstop-p4`: `pytstop` e o do `make cd-local` da fase 3 na mesma maquina
- 2026-10-06 - PyJWT 2.13.x acumulou 27 advisories em out/2026: comecar em `pyjwt>=2.15.1` e `anyio>=4.15.1`. PyJWT 2.15 exige base64url valido na assinatura mesmo com `verify_signature=False` (JWT falso de teste precisa de segmento valido)

## Tech debt / TODO

- 2026-10-06 - MEDIUM - Senhas de demonstracao versionadas (RabbitMQ, Grafana), iguais no kind e no k3s - gerar no deploy (onda D)
- 2026-10-06 - LOW - Retry com TTL por mensagem numa fila so tem head-of-line (300s segura 1s) - fila de retry por atraso se o volume crescer
- 2026-10-06 - LOW - Promtail em fim de vida desde 02/03/2026 - migrar para Grafana Alloy; Jaeger 1.x e Grafana 11.1 herdados da fase 3
- 2026-10-06 - LOW - Profile `servicos` do compose sobe so a API de cada servico - incluir relay e consumidor quando as imagens tiverem os comandos

## Review lessons

- 2026-10-06 - Exemplo de Ingress do README com strip-path num caminho mais longo que o prefixo do servico apagava o `/api/v1` - a revisao nao pegou; exemplo de manifest em doc so entra depois de aplicado no kind
