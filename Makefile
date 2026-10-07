# Plataforma da fase 4: cluster kind, deploy da infraestrutura compartilhada,
# stack compose e testes dos contratos de mensageria. `make` lista os alvos.

# bash pelo pipefail. Recipe com laco ou pipe abre com `set -euo pipefail`
# na propria linha: o make 3.81 do macOS ignora .SHELLFLAGS.
SHELL := bash
.DEFAULT_GOAL := help

CLUSTER ?= pytstop-p4
NAMESPACE ?= pytstop-plataforma
# Overlay do make deploy e do make smoke: kind (local), kind-ci (o do CI, sem
# Loki, Promtail e Grafana) ou k3s (make deploy OVERLAY=k3s
# KUBE_CONTEXT=<contexto do k3s>).
OVERLAY ?= kind
# Contexto explicito: o deploy nunca cai no cluster que estiver ativo no
# kubeconfig por acaso. Para outro cluster: make status KUBE_CONTEXT=<ctx>.
KUBE_CONTEXT ?= kind-$(CLUSTER)
KUBECTL := kubectl --context $(KUBE_CONTEXT)
# Rotulo que o k8s/base poe em tudo o que a plataforma cria.
SELETOR := app.kubernetes.io/part-of=pytstop-plataforma
# O Kong so le Ingress destes namespaces (watchNamespaces) e precisa da Role
# dele em cada um; o repositorio de cada servico continua dono do namespace.
NAMESPACES_SERVICOS := pytstop-os pytstop-billing pytstop-execucao

COMPOSE := docker compose -f compose/docker-compose.yml

# Versoes fixadas das ferramentas. As imagens que tambem rodam na plataforma
# (Prometheus, Loki, Promtail) tem de ser as do cluster e do compose: o
# make manifests confere (scripts/versoes.sh).
KUBERNETES_VERSION := 1.35.0
KONG_CHART_VERSION := 3.4.1
HELM_IMAGE := alpine/helm:3.22.0
YQ_IMAGE := mikefarah/yq:4.54.1
KUBECONFORM_IMAGE := ghcr.io/yannh/kubeconform:v0.8.0
PROMETHEUS_IMAGE := prom/prometheus:v2.54.1
LOKI_IMAGE := grafana/loki:2.9.8
PROMTAIL_IMAGE := grafana/promtail:3.6.11
# Broker avulso do make prova-retry, a mesma imagem do StatefulSet e do compose.
RABBITMQ_IMAGE := rabbitmq:4.3.6-management
# Mesma versao do trivy dos repositorios de servico.
TRIVY_IMAGE := aquasec/trivy:0.72.0
# Valida o asyncapi.yaml contra a especificacao AsyncAPI 3.0 (exige Node 24).
ASYNCAPI_CLI := @asyncapi/cli@6.2.0
SHELLCHECK_IMAGE := koalaman/shellcheck:v0.11.0
ACTIONLINT_IMAGE := rhysd/actionlint:1.7.12

# Schemas do Kubernetes na versao do no do kind (kind/cluster.yaml) e o do
# KongClusterPlugin gerado das CRDs do chart (make kong-render), versionado
# em k8s/base/kong/schemas: o resultado nao muda sem commit aqui. Sem
# -ignore-missing-schemas: recurso sem schema reprova. Unica excecao, as
# definicoes de CRD do Kong: o repositorio de schemas do kubeconform nao
# publica o de CustomResourceDefinition, e elas vem prontas do chart oficial
# (o apiserver as valida no make deploy). Secret reprova: as senhas nao entram
# nos manifests, o make deploy as gera no cluster (ADR-042).
KUBECONFORM := docker run --rm -i -v "$(CURDIR)/k8s/base/kong/schemas:/schemas:ro" $(KUBECONFORM_IMAGE) \
	-strict -summary -output text -kubernetes-version $(KUBERNETES_VERSION) \
	-skip CustomResourceDefinition -reject Secret -schema-location default \
	-schema-location '/schemas/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json'
# Endurecimento dos pods: nenhum achado HIGH ou CRITICAL.
TRIVY_CONFIG := docker run --rm -i --entrypoint sh $(TRIVY_IMAGE) -c \
	'cat > /tmp/manifests.yaml && trivy config --quiet --severity HIGH,CRITICAL --exit-code 1 /tmp/manifests.yaml'
KONG_RENDER := KONG_CHART_VERSION=$(KONG_CHART_VERSION) HELM_IMAGE=$(HELM_IMAGE) YQ_IMAGE=$(YQ_IMAGE) \
	NAMESPACE=$(NAMESPACE) scripts/kong-render.sh

.PHONY: help kind-up kind-down deploy kong-check smoke redrive status port-forward up down test lint lint-scripts prova-retry manifests check kong-render

help:
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-13s %s\n", $$1, $$2}'

kind-up: ## cria o cluster kind (nao faz nada se ja existir)
	@kind get clusters | grep -qx '$(CLUSTER)' || kind create cluster --name $(CLUSTER) --config kind/cluster.yaml --wait 120s

kind-down: ## remove o cluster kind
	kind delete cluster --name $(CLUSTER)

# As CRDs do Kong vao antes: no mesmo apply o servidor ainda nao conhece
# KongClusterPlugin quando chega no plugins.yaml. Server-side porque as CRDs
# passam do limite de tamanho da anotacao last-applied do apply client-side.
# Os namespaces dos servicos nascem vazios, se ainda nao existirem, para
# receber a Role do Kong e o Secret rabbitmq; o da plataforma, para receber os
# Secrets gerados antes do apply (scripts/gerar-segredos.sh, que so cria o que
# ainda nao existe). O Job de usuarios do RabbitMQ e imutavel: sai antes do
# apply e roda de novo; se nao terminar, o log dele vai para a saida.
deploy: ## aplica k8s/overlays/$(OVERLAY) e espera os rollouts
	$(KUBECTL) apply --server-side -f k8s/base/kong/crds.yaml
	$(KUBECTL) wait --for=condition=Established --timeout=60s -f k8s/base/kong/crds.yaml
	set -euo pipefail; \
	for ns in $(NAMESPACE) $(NAMESPACES_SERVICOS); do \
		$(KUBECTL) get namespace "$$ns" >/dev/null 2>&1 || $(KUBECTL) create namespace "$$ns"; \
	done
	KUBE_CONTEXT=$(KUBE_CONTEXT) NAMESPACE=$(NAMESPACE) scripts/gerar-segredos.sh
	$(KUBECTL) -n $(NAMESPACE) delete job rabbitmq-usuarios --ignore-not-found
	$(KUBECTL) apply --server-side -k k8s/overlays/$(OVERLAY)
	set -euo pipefail; \
	recursos=$$($(KUBECTL) -n $(NAMESPACE) get deployment,statefulset,daemonset -l $(SELETOR) -o name); \
	test -n "$$recursos" || { echo "no Deployment, StatefulSet or DaemonSet labeled $(SELETOR)"; exit 1; }; \
	for recurso in $$recursos; do \
		$(KUBECTL) -n $(NAMESPACE) rollout status "$$recurso" --timeout=300s; \
	done
	$(KUBECTL) -n kube-system rollout status deployment/metrics-server --timeout=180s
	$(KUBECTL) -n $(NAMESPACE) wait --for=condition=Complete job/rabbitmq-usuarios --timeout=180s \
		|| { $(KUBECTL) -n $(NAMESPACE) logs job/rabbitmq-usuarios --tail=30; exit 1; }
	@$(MAKE) --no-print-directory kong-check

kong-check: ## falha se o Kong recusou algum Ingress ou plugin (eventos dos ultimos 15 min)
	@KUBE_CONTEXT=$(KUBE_CONTEXT) scripts/kong-check.sh

smoke: ## borda, barra codificada, rate limiting, mascara de token, RabbitMQ, fallback do Kong, alertas e pods endurecidos (status 1 se uma prova falha)
	OVERLAY=$(OVERLAY) KUBE_CONTEXT=$(KUBE_CONTEXT) scripts/smoke.sh

redrive: ## devolve <fila>.dlq para <fila> depois de corrigida a causa (FILA=billing.comandos)
	@case "$(FILA)" in billing.comandos|execucao.comandos|os.eventos) ;; \
		*) echo "usage: make redrive FILA=billing.comandos|execucao.comandos|os.eventos"; exit 1;; esac
	@KUBE_CONTEXT=$(KUBE_CONTEXT) NAMESPACE=$(NAMESPACE) scripts/redrive.sh $(FILA)

status: ## pods, servicos, volumes e filas do RabbitMQ
	$(KUBECTL) -n $(NAMESPACE) get pods,services,ingresses,pvc
	$(KUBECTL) -n $(NAMESPACE) exec rabbitmq-0 -c rabbitmq -- rabbitmqctl -q list_queues name type messages consumers

# Port-forwards em paralelo; Ctrl+C encerra todos (o trap mata os jobs, que
# num shell nao interativo ignorariam o SIGINT).
port-forward: ## Grafana 3000, Jaeger 16686, RabbitMQ 15672, Prometheus 9090, Mailpit 8025
	@trap 'kill $$(jobs -p) 2>/dev/null' EXIT; \
	$(KUBECTL) -n $(NAMESPACE) port-forward svc/grafana 3000:3000 & \
	$(KUBECTL) -n $(NAMESPACE) port-forward svc/jaeger 16686:16686 & \
	$(KUBECTL) -n $(NAMESPACE) port-forward svc/rabbitmq 15672:15672 & \
	$(KUBECTL) -n $(NAMESPACE) port-forward svc/prometheus 9090:9090 & \
	$(KUBECTL) -n $(NAMESPACE) port-forward svc/mailpit 8025:8025 & \
	wait

up: ## sobe a stack compose (com os servicos: make up PROFILE=servicos)
	$(COMPOSE) $(if $(PROFILE),--profile $(PROFILE)) up -d --wait

down: ## derruba a stack compose (os volumes ficam; docker compose down -v apaga)
	$(COMPOSE) --profile servicos down

# CI=true desliga a telemetria anonima do @asyncapi/cli.
test: ## testes dos contratos e da observabilidade, validacao do asyncapi.yaml
	uv run pytest
	CI=true npx --yes $(ASYNCAPI_CLI) validate contratos/asyncapi.yaml

lint: ## ruff, mypy e bandit nos testes e na prova do retry
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy
	uv run bandit -c pyproject.toml -r contratos tests scripts -q

# Pelas imagens pinadas, como no CI, onde rodam no job manifests. O actionlint
# passa o shellcheck tambem nos run: dos workflows.
lint: lint-scripts
lint-scripts: ## shellcheck nos scripts e actionlint nos workflows
	docker run --rm -v "$(CURDIR):/repo:ro" -w /repo $(SHELLCHECK_IMAGE) scripts/*.sh scripts/ci/*.sh k8s/base/rabbitmq/*.sh
	docker run --rm -v "$(CURDIR):/repo:ro" -w /repo $(ACTIONLINT_IMAGE)

prova-retry: ## prova do retry num RabbitMQ avulso com as definitions e as permissoes daqui (Docker e uv)
	RABBITMQ_IMAGE=$(RABBITMQ_IMAGE) scripts/prova-retry-avulso.sh

manifests: ## kubeconform, trivy, configs de Prometheus/Loki/Promtail, regra de saga parada, render do Kong, versoes, dashboards
	set -euo pipefail; \
	for overlay in kind kind-ci k3s; do \
		echo ">> kubeconform and trivy: k8s/overlays/$$overlay"; \
		kubectl kustomize "k8s/overlays/$$overlay" | $(KUBECONFORM) -; \
		kubectl kustomize "k8s/overlays/$$overlay" | $(TRIVY_CONFIG); \
	done
	set -euo pipefail; \
	for exemplo in k8s/exemplos/*.yaml; do \
		echo ">> kubeconform and trivy: $$exemplo"; \
		$(KUBECONFORM) - < "$$exemplo"; \
		$(TRIVY_CONFIG) < "$$exemplo"; \
	done
	$(COMPOSE) --profile servicos config --quiet
	@echo ">> Prometheus, Loki and Promtail configs (cluster and compose)"
	set -euo pipefail; \
	for config in k8s/base/observabilidade/config/prometheus.yml compose/prometheus.yml; do \
		docker run --rm -i --entrypoint sh $(PROMETHEUS_IMAGE) -c \
			'cat > /tmp/prometheus.yml && promtool check config --syntax-only /tmp/prometheus.yml' < "$$config"; \
	done; \
	docker run --rm -i --entrypoint sh $(LOKI_IMAGE) -c \
		'cat > /tmp/loki.yaml && loki -config.file=/tmp/loki.yaml -verify-config' < k8s/base/observabilidade/config/loki.yaml; \
	for config in k8s/base/observabilidade/config/promtail.yaml compose/promtail.yml; do \
		docker run --rm -i --entrypoint sh $(PROMTAIL_IMAGE) -c \
			'cat > /tmp/promtail.yaml && promtail -check-syntax -config.file=/tmp/promtail.yaml' < "$$config"; \
	done
	PROMTAIL_IMAGE=$(PROMTAIL_IMAGE) scripts/promtail-mascara.sh
	@echo ">> alert rule pytstop-saga-parada: each condition fires alone (promtool test rules)"
	PROMETHEUS_IMAGE=$(PROMETHEUS_IMAGE) YQ_IMAGE=$(YQ_IMAGE) scripts/alerta-saga-parada.sh
	@echo ">> k8s/base/kong matches make kong-render"
	set -euo pipefail; \
	render=$$(mktemp -d); trap 'rm -rf "$$render"' EXIT; \
	$(KONG_RENDER) "$$render"; \
	diff -u k8s/base/kong/kong.yaml "$$render/kong.yaml"; \
	diff -u k8s/base/kong/crds.yaml "$$render/crds.yaml"; \
	diff -u k8s/base/kong/schemas/kongclusterplugin_v1.json "$$render/schemas/kongclusterplugin_v1.json"
	KUBERNETES_VERSION=$(KUBERNETES_VERSION) scripts/versoes.sh $(PROMETHEUS_IMAGE) $(LOKI_IMAGE) $(PROMTAIL_IMAGE) $(RABBITMQ_IMAGE)
	set -euo pipefail; \
	for painel in observabilidade/dashboards/*.json; do \
		jq -e '.uid and .title' "$$painel" > /dev/null; \
		grep -q "dashboards/$$(basename "$$painel")" observabilidade/kustomization.yaml \
			|| { echo "$$painel missing from the configMapGenerator in observabilidade/kustomization.yaml"; exit 1; }; \
	done

check: lint test prova-retry manifests ## o mesmo que o CI roda

kong-render: ## regenera k8s/base/kong (kong.yaml, crds.yaml e o schema do plugin) do chart pinado
	$(KONG_RENDER) k8s/base/kong
