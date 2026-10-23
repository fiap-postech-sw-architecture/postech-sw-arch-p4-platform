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
NEWMAN := newman@6.2.3
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

.PHONY: newman help kind-up kind-down deploy kong-check smoke redrive status port-forward up down test lint lint-scripts prova-retry manifests check kong-render e2e paineis demo mp-sandbox mp-sandbox-ensaio

help:
	@grep -E '^[a-z0-9-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-17s %s\n", $$1, $$2}'

kind-up: ## cria o cluster kind (nao faz nada se ja existir)
	@kind get clusters | grep -qx '$(CLUSTER)' || kind create cluster --name $(CLUSTER) --config kind/cluster.yaml --wait 120s

kind-down: ## remove o cluster kind
	kind delete cluster --name $(CLUSTER)

# As CRDs do Kong vao antes: no mesmo apply o servidor ainda nao conhece
# KongClusterPlugin quando chega no plugins.yaml. Server-side porque as CRDs
# passam do limite de tamanho da anotacao last-applied do apply client-side.
# Os namespaces dos servicos nascem vazios, se ainda nao existirem, para
# receber a Role do Kong, o Secret rabbitmq e as fontes de cada servico; o da
# plataforma, para receber as fontes dela. Todos antes do apply
# (scripts/gerar-segredos.sh: as fontes so se ainda nao existem, o Secret
# rabbitmq de cada servico em todo deploy). O Job
# de usuarios do RabbitMQ e imutavel: sai antes do apply e roda de novo; se
# nao terminar, o log dele vai para a saida.
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

smoke: ## borda, barra codificada, rate limiting, cabecalhos do Kong, mascara de token, RabbitMQ, fallback do Kong, alertas e pods endurecidos (status 1 se uma prova falha)
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
# O E2E so roda contra o cluster, mas a coleta e offline: import quebrado, tag
# sem marker (--strict-markers) e step sem definicao reprovam aqui, no CI, e nao
# no primeiro make e2e. O --generate-missing sai com 0 mesmo com step faltando,
# entao a saida e que decide.
test: ## testes dos contratos, da observabilidade e do codigo auxiliar do E2E, coleta do E2E, validacao do asyncapi.yaml
	uv run pytest
	@echo ">> E2E: cenarios coletados e todo step definido (sem cluster)"
	uv run pytest -c e2e/pytest.ini e2e --collect-only -q > /dev/null
	set -euo pipefail; \
	saida=$$(uv run pytest -c e2e/pytest.ini --generate-missing --feature e2e/features e2e); \
	if printf '%s' "$$saida" | grep -q 'is not defined'; then \
		printf '%s\n' "$$saida"; echo "E2E: step sem definicao" >&2; exit 1; \
	fi
	CI=true npx --yes $(ASYNCAPI_CLI) validate contratos/asyncapi.yaml

lint: ## ruff, mypy e bandit nos testes e na prova do retry, mais o lint-scripts
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy
	uv run bandit -c pyproject.toml -r contratos tests scripts e2e -q

# Pelas imagens pinadas, como no CI, onde rodam no job manifests. O actionlint
# passa o shellcheck tambem nos run: dos workflows.
lint: lint-scripts
lint-scripts: ## shellcheck nos scripts e actionlint nos workflows
	docker run --rm -v "$(CURDIR):/repo:ro" -w /repo $(SHELLCHECK_IMAGE) scripts/*.sh scripts/ci/*.sh k8s/base/rabbitmq/*.sh
	docker run --rm -v "$(CURDIR):/repo:ro" -w /repo $(ACTIONLINT_IMAGE)

prova-retry: ## prova do retry num RabbitMQ avulso com as definitions e as permissoes daqui (Docker e uv)
	RABBITMQ_IMAGE=$(RABBITMQ_IMAGE) scripts/prova-retry-avulso.sh

manifests: ## kubeconform, trivy, configs de Prometheus/Loki/Promtail, consultas e alertas no promtool, render do Kong, versoes, dashboards
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
	@echo ">> panel and alert queries (promtool check rules) and alert rules (promtool test rules)"
	PROMETHEUS_IMAGE=$(PROMETHEUS_IMAGE) YQ_IMAGE=$(YQ_IMAGE) scripts/alertas-promtool.sh
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

# O E2E derruba o Billing, cria usuarios e nao limpa: so num kind descartavel.
# O mesmo guarda roda no inicio da sessao (e2e/apoio/contexto.py); aqui ele
# falha antes de o uv subir. Escape: E2E_CONTEXTO_NAO_DESCARTAVEL=<o contexto>.
GUARDA_DE_CONTEXTO := case "$(KUBE_CONTEXT)" in kind-*) ;; *) \
	[ "$${E2E_CONTEXTO_NAO_DESCARTAVEL:-}" = "$(KUBE_CONTEXT)" ] || { \
	echo "contexto $(KUBE_CONTEXT) nao e um kind descartavel: o E2E derruba o Billing e nao limpa; para rodar assim mesmo exporte E2E_CONTEXTO_NAO_DESCARTAVEL=$(KUBE_CONTEXT)" >&2; exit 2; };; esac

# E2E BDD da saga contra o kind com a plataforma e os tres servicos de pe
# (docs/e2e-da-saga.md). Os relatorios ficam em reports/e2e; o resumo.md sai
# mesmo com cenario reprovado, e o status do make e o do pytest. Com todos os
# cenarios verdes, o make confere ainda que cada consulta de painel de negocio
# devolve serie no Prometheus do kind (e2e/apoio/paineis.py, paineis.md): painel
# vazio reprova, e assim o E2E pega nome de metrica trocado em painel.
e2e: ## E2E BDD da saga contra o kind com os tres servicos, e cada painel de negocio com serie (relatorios em reports/e2e)
	$(GUARDA_DE_CONTEXTO)
	rm -rf reports/e2e && mkdir -p reports/e2e
	set -uo pipefail; \
	KUBE_CONTEXT=$(KUBE_CONTEXT) uv run --group e2e pytest -c e2e/pytest.ini e2e -m "not mp_sandbox" \
		--junitxml=reports/e2e/junit.xml --cucumberjson=reports/e2e/cucumber.json; \
	status=$$?; \
	uv run --group e2e python -m e2e.resumo reports/e2e || true; \
	if [ $$status -eq 0 ]; then \
		KUBE_CONTEXT=$(KUBE_CONTEXT) uv run --group e2e python -m e2e.paineis reports/e2e || status=$$?; \
	fi; \
	exit $$status

# Collection do caminho feliz: reaproveita as fixtures, sem coleta pelo BDD.
newman: ## collection do fluxo completo pelo Newman fixado (kind descartavel; simulador)
	@test -z "$${E2E_MP_MODO:-}" -a -z "$${E2E_CONTEXTO_NAO_DESCARTAVEL:-}" || { echo "Newman exige kind local, sem sandbox nem escape" >&2; exit 2; }
	$(GUARDA_DE_CONTEXTO)
	rm -rf reports/e2e/newman && mkdir -p reports/e2e/newman
	set -uo pipefail; \
	KUBE_CONTEXT=$(KUBE_CONTEXT) E2E_MP_MODO= NEWMAN=$(NEWMAN) uv run --group e2e pytest -c e2e/pytest.ini e2e/newman.py \
		--junitxml=reports/e2e/newman/junit.xml; \
	status=$$?; \
	uv run --group e2e python -m e2e.varredura reports/e2e/newman || status=$$?; \
	exit $$status

# Cada consulta de painel de negocio no Prometheus do kind, sem rodar o E2E (por
# exemplo depois do make demo): reprova se um painel vier sem serie. So le.
paineis: ## cada consulta de painel de negocio com serie no Prometheus do kind, sem rodar o E2E (reports/paineis)
	mkdir -p reports/paineis
	KUBE_CONTEXT=$(KUBE_CONTEXT) uv run --group e2e python -m e2e.paineis reports/paineis

# Roteiro do video: bloco 1 (fluxo completo) e bloco 2 (falhas), com o status da
# OS impresso depois de cada Entao. Reusa os cenarios marcados @demo do E2E.
demo: ## roda os blocos 1 e 2 do video (cenarios @demo) imprimindo o status da OS depois de cada Entao
	$(GUARDA_DE_CONTEXTO)
	rm -rf reports/demo && mkdir -p reports/demo
	set -uo pipefail; \
	E2E_NARRAR=1 E2E_RELATORIOS=reports/demo KUBE_CONTEXT=$(KUBE_CONTEXT) \
		uv run --group e2e pytest -c e2e/pytest.ini e2e -m demo -s -q \
		--junitxml=reports/demo/junit.xml --cucumberjson=reports/demo/cucumber.json; \
	status=$$?; \
	uv run --group e2e python -m e2e.resumo reports/demo || true; \
	exit $$status

# Sandbox do Mercado Pago (docs/mercado-pago-na-sandbox.md). O real grava o Access
# Token num Secret do cluster: so kind, e sem o escape do E2E. As credenciais vem do
# ambiente do shell (read -rs), nunca da linha de comando, e as duas pastas de
# relatorios sao separadas para o ensaio nao apagar a evidencia do real. O -x
# para no primeiro cenario que reprova: o seguinte pediria outro pagamento seu.
# Na linha do make o token ficaria no argv (ps) e no historico do shell: so por
# ambiente, sem export (MP_ACCESS_TOKEN="$MP_ACCESS_TOKEN" make mp-sandbox).
ifneq ($(filter mp-sandbox mp-sandbox-ensaio,$(MAKECMDGOALS)),)
ifneq ($(filter command line,$(origin MP_ACCESS_TOKEN) $(origin MP_WEBHOOK_SECRET)),)
$(error MP_ACCESS_TOKEN e MP_WEBHOOK_SECRET não vão na linha do make: aparecem no ps e no histórico do shell. Leia com read -rs e passe só ao make: MP_ACCESS_TOKEN="$$MP_ACCESS_TOKEN" MP_WEBHOOK_SECRET="$$MP_WEBHOOK_SECRET" make mp-sandbox)
endif
endif

GUARDA_DE_KIND := case "$(KUBE_CONTEXT)" in kind-*) ;; *) \
	echo "contexto $(KUBE_CONTEXT) não é um kind: o sandbox grava o Access Token num Secret do cluster, e o escape do E2E não vale aqui" >&2; exit 2;; esac
# A conferencia roda ANTES do pytest e da pasta de relatorios: se reprova (cluster fora do
# ar, credencial esquecida), le-se so a mensagem, e a evidencia de uma execucao boa fica.
CONFERIR_SANDBOX := KUBE_CONTEXT=$(KUBE_CONTEXT) uv run --group e2e python -m e2e.conferir_sandbox
# Uma execucao boa (com resumo.md) vai para uma pasta com data e hora, e nada anterior e
# apagado. O que sobrou de uma execucao que nao chegou a escrever o resumo.md vai embora.
GIRAR_EVIDENCIA := if [ -f reports/mp-sandbox/resumo.md ]; then \
	mv reports/mp-sandbox "reports/mp-sandbox.$$(date +%Y%m%d-%H%M%S)"; \
	else rm -rf reports/mp-sandbox; fi

mp-sandbox: ## Mercado Pago na sandbox (modo real): cria a OS, imprime o link, espera voce pagar, estorna e desfaz (reports/mp-sandbox)
	$(GUARDA_DE_KIND)
	$(CONFERIR_SANDBOX) real
	$(GIRAR_EVIDENCIA)
	mkdir -p reports/mp-sandbox
	set -uo pipefail; \
	E2E_MP_MODO=real E2E_NARRAR=1 E2E_RELATORIOS=reports/mp-sandbox KUBE_CONTEXT=$(KUBE_CONTEXT) \
		uv run --group e2e pytest -c e2e/pytest.ini e2e -m mp_sandbox -s -q -x \
		--junitxml=reports/mp-sandbox/junit.xml --cucumberjson=reports/mp-sandbox/cucumber.json; \
	status=$$?; \
	uv run --group e2e python -m e2e.resumo reports/mp-sandbox relatorio-e2e.md "Relatório do E2E do Mercado Pago" || true; \
	uv run --group e2e python -m e2e.varredura reports/mp-sandbox || status=1; \
	exit $$status

mp-sandbox-ensaio: ## ensaio do mp-sandbox sem credencial: o simulador do Billing paga no seu lugar (reports/mp-sandbox-ensaio)
	$(GUARDA_DE_KIND)
	$(CONFERIR_SANDBOX) ensaio
	rm -rf reports/mp-sandbox-ensaio && mkdir -p reports/mp-sandbox-ensaio
	set -uo pipefail; \
	E2E_MP_MODO=ensaio E2E_NARRAR=1 E2E_RELATORIOS=reports/mp-sandbox-ensaio KUBE_CONTEXT=$(KUBE_CONTEXT) \
		uv run --group e2e pytest -c e2e/pytest.ini e2e -m mp_sandbox -s -q -x \
		--junitxml=reports/mp-sandbox-ensaio/junit.xml --cucumberjson=reports/mp-sandbox-ensaio/cucumber.json; \
	status=$$?; \
	uv run --group e2e python -m e2e.resumo reports/mp-sandbox-ensaio relatorio-e2e.md "Relatório do E2E do Mercado Pago (ensaio)" || true; \
	uv run --group e2e python -m e2e.varredura reports/mp-sandbox-ensaio || status=1; \
	exit $$status

kong-render: ## regenera k8s/base/kong (kong.yaml, crds.yaml e o schema do plugin) do chart pinado
	$(KONG_RENDER) k8s/base/kong
