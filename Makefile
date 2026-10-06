# Plataforma da fase 4: cluster kind, deploy da infraestrutura compartilhada,
# stack compose e testes dos contratos de mensageria. `make` lista os alvos.

# bash pelo pipefail. Recipe com laco ou pipe abre com `set -euo pipefail`
# na propria linha: o make 3.81 do macOS ignora .SHELLFLAGS.
SHELL := bash
.DEFAULT_GOAL := help

CLUSTER ?= pytstop-p4
NAMESPACE ?= pytstop-plataforma
# Contexto explicito: o deploy nunca cai no cluster que estiver ativo no
# kubeconfig por acaso. Para outro cluster: make status KUBE_CONTEXT=<ctx>.
KUBE_CONTEXT ?= kind-$(CLUSTER)
KUBECTL := kubectl --context $(KUBE_CONTEXT)
# Rotulo que o k8s/base poe em tudo o que a plataforma cria.
SELETOR := app.kubernetes.io/part-of=pytstop-plataforma

COMPOSE := docker compose -f compose/docker-compose.yml

KONG_CHART_VERSION := 3.4.1
HELM_IMAGE := alpine/helm:3.22.0
KUBECONFORM_IMAGE := ghcr.io/yannh/kubeconform:v0.8.0
# Mesma imagem do DaemonSet e do compose; o make manifests roda o pipeline nela.
PROMTAIL_IMAGE := grafana/promtail:3.6.11
# Valida o asyncapi.yaml contra a especificacao AsyncAPI 3.0 (exige Node 24).
ASYNCAPI_CLI := @asyncapi/cli@6.2.0
# KongPlugin/KongClusterPlugin sao validados pelo catalogo de CRDs da datree;
# o resto pelo schema oficial do Kubernetes. Sem -ignore-missing-schemas:
# recurso sem schema reprova. Unica excecao, as definicoes de CRD do Kong: o
# repositorio de schemas do kubeconform nao publica o de
# CustomResourceDefinition, e elas vem prontas do chart oficial (o apiserver
# as valida no make deploy).
KUBECONFORM_FLAGS := -strict -summary -output text \
	-skip CustomResourceDefinition \
	-schema-location default \
	-schema-location 'https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json'

.PHONY: help kind-up kind-down deploy kong-check smoke redrive status port-forward up down test lint manifests check kong-render

help:
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-13s %s\n", $$1, $$2}'

kind-up: ## cria o cluster kind (nao faz nada se ja existir)
	@kind get clusters | grep -qx '$(CLUSTER)' || kind create cluster --name $(CLUSTER) --config kind/cluster.yaml --wait 120s

kind-down: ## remove o cluster kind
	kind delete cluster --name $(CLUSTER)

# As CRDs do Kong vao antes: no mesmo apply o servidor ainda nao conhece
# KongPlugin quando chega no plugins.yaml. Server-side porque as CRDs passam
# do limite de tamanho da anotacao last-applied do apply client-side. O Job
# de usuarios do RabbitMQ e imutavel: sai antes do apply e roda de novo.
deploy: ## aplica k8s/overlays/kind e espera os rollouts
	$(KUBECTL) apply --server-side -f k8s/base/kong/crds.yaml
	$(KUBECTL) wait --for=condition=Established --timeout=60s -f k8s/base/kong/crds.yaml
	$(KUBECTL) -n $(NAMESPACE) delete job rabbitmq-usuarios --ignore-not-found
	$(KUBECTL) apply --server-side -k k8s/overlays/kind
	set -euo pipefail; \
	for recurso in $$($(KUBECTL) -n $(NAMESPACE) get deployment,statefulset,daemonset -l $(SELETOR) -o name); do \
		$(KUBECTL) -n $(NAMESPACE) rollout status "$$recurso" --timeout=300s; \
	done
	$(KUBECTL) -n kube-system rollout status deployment/metrics-server --timeout=180s
	$(KUBECTL) -n $(NAMESPACE) wait --for=condition=Complete job/rabbitmq-usuarios --timeout=180s
	@$(MAKE) --no-print-directory kong-check

kong-check: ## falha se o Kong recusou algum Ingress ou plugin (eventos dos ultimos 15 min)
	@KUBE_CONTEXT=$(KUBE_CONTEXT) scripts/kong-check.sh

smoke: ## borda e rate limiting no cluster implantado (exemplo de Ingress com eco)
	KUBE_CONTEXT=$(KUBE_CONTEXT) scripts/smoke.sh

redrive: ## devolve <fila>.dlq para <fila> depois de corrigida a causa (FILA=billing.comandos)
	@case "$(FILA)" in billing.comandos|execucao.comandos|os.eventos) ;; \
		*) echo "uso: make redrive FILA=billing.comandos|execucao.comandos|os.eventos"; exit 1;; esac
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
test: ## testes dos contratos de mensageria e validacao do asyncapi.yaml
	uv run pytest
	CI=true npx --yes $(ASYNCAPI_CLI) validate contratos/asyncapi.yaml

lint: ## ruff, mypy e bandit nos testes de contrato
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy
	uv run bandit -c pyproject.toml -r contratos -q

manifests: ## kustomize + kubeconform nos overlays, compose config e dashboards
	set -euo pipefail; \
	for overlay in kind k3s; do \
		echo ">> k8s/overlays/$$overlay"; \
		kubectl kustomize "k8s/overlays/$$overlay" | docker run --rm -i $(KUBECONFORM_IMAGE) $(KUBECONFORM_FLAGS) -; \
	done
	set -euo pipefail; \
	for exemplo in k8s/exemplos/*.yaml; do \
		echo ">> $$exemplo"; \
		docker run --rm -i $(KUBECONFORM_IMAGE) $(KUBECONFORM_FLAGS) - < "$$exemplo"; \
	done
	$(COMPOSE) --profile servicos config --quiet
	PROMTAIL_IMAGE=$(PROMTAIL_IMAGE) scripts/promtail-mascara.sh
	set -euo pipefail; \
	for painel in observabilidade/dashboards/*.json; do \
		jq -e '.uid and .title' "$$painel" > /dev/null; \
		grep -q "dashboards/$$(basename "$$painel")" observabilidade/kustomization.yaml \
			|| { echo "$$painel fora do configMapGenerator de observabilidade/kustomization.yaml"; exit 1; }; \
	done

check: lint test manifests ## o mesmo que o CI roda

kong-render: ## regenera k8s/base/kong/{kong,crds}.yaml a partir do chart pinado
	set -euo pipefail; \
	{ echo '# Gerado por make kong-render (chart kong/kong $(KONG_CHART_VERSION), valores em values.yaml). Nao edite.'; \
	  docker run --rm -v "$(CURDIR)/k8s/base/kong:/work" -w /work $(HELM_IMAGE) template kong kong \
		--repo https://charts.konghq.com --version $(KONG_CHART_VERSION) --namespace $(NAMESPACE) \
		--values values.yaml --skip-tests --api-versions networking.k8s.io/v1/IngressClass; \
	} > k8s/base/kong/kong.yaml
	set -euo pipefail; \
	{ echo '# Gerado por make kong-render (CRDs do chart kong/kong $(KONG_CHART_VERSION)). Nao edite.'; \
	  docker run --rm $(HELM_IMAGE) show crds kong --repo https://charts.konghq.com --version $(KONG_CHART_VERSION); \
	} > k8s/base/kong/crds.yaml
