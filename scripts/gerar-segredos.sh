#!/usr/bin/env bash
# Segredos de runtime da plataforma (make deploy, antes do apply; ADR-042).
# Gera com openssl rand as senhas do admin do RabbitMQ, dos usuarios os,
# billing e execucao e do admin do Grafana, e cria cada Secret so se ele
# ainda nao existe, ou seja, no primeiro deploy de cada cluster: o RabbitMQ le
# o admin.json so no boot, e uma senha nova com o broker de pe deixaria o Job
# rabbitmq-usuarios sem acesso a API (401) ate o proximo restart.
#
# Em cada namespace de servico (pytstop-os, pytstop-billing, pytstop-execucao)
# cria o Secret rabbitmq com a chave RABBITMQ_URL, a URL do usuario do servico
# no broker, montada com a senha do rabbitmq-credenciais: e o contrato com os
# servicos (README, "Usuario e permissoes no RabbitMQ").
#
# Nenhuma senha vai para argumento de processo, saida ou arquivo: o Secret
# chega ao kubectl pela entrada padrao. No GitHub Actions cada senha e
# registrada com ::add-mask:: antes do uso, e o log do job a mostra como ***.
set -euo pipefail

K="kubectl --context ${KUBE_CONTEXT:-kind-pytstop-p4}"
NS="${NAMESPACE:-pytstop-plataforma}"

# existe <namespace> <secret>. Erro ao falar com o cluster aborta, em vez de
# virar "nao existe" e trocar senhas que nao foram lidas.
existe() {
  local nome
  nome=$($K -n "$1" get secret "$2" --ignore-not-found -o name) || exit 1
  [ -n "$nome" ]
}

# Hexadecimal: entra na URL AMQP, no JSON e no YAML sem escape.
senha() { openssl rand -hex 24; }

mascara() {
  [ "${GITHUB_ACTIONS:-}" = true ] || return 0
  local valor
  for valor in "$@"; do echo "::add-mask::$valor"; done
}

if existe "$NS" rabbitmq-credenciais; then
  echo "secret $NS/rabbitmq-credenciais already exists: kept"
else
  admin=$(senha)
  os=$(senha)
  billing=$(senha)
  execucao=$(senha)
  mascara "$admin" "$os" "$billing" "$execucao"
  # admin.json declara o vhost / tambem: o RabbitMQ importa o diretorio de
  # definitions em ordem alfabetica, admin.json antes de definitions.json, e
  # permissao em vhost que ainda nao existe derruba o boot.
  $K create -f - >/dev/null <<YAML
apiVersion: v1
kind: Secret
metadata:
  name: rabbitmq-credenciais
  namespace: $NS
  labels:
    app: rabbitmq
    app.kubernetes.io/part-of: pytstop-plataforma
type: Opaque
stringData:
  admin-usuario: admin
  admin-senha: "$admin"
  senha-os: "$os"
  senha-billing: "$billing"
  senha-execucao: "$execucao"
  admin.json: |
    {
      "vhosts": [{"name": "/"}],
      "users": [
        {"name": "admin", "password": "$admin", "tags": ["administrator"]}
      ],
      "permissions": [
        {"user": "admin", "vhost": "/", "configure": ".*", "write": ".*", "read": ".*"}
      ]
    }
YAML
  echo "secret $NS/rabbitmq-credenciais created"
fi

for usuario in os billing execucao; do
  servico="pytstop-$usuario"
  if existe "$servico" rabbitmq; then
    echo "secret $servico/rabbitmq already exists: kept"
    continue
  fi
  # A senha que o Job rabbitmq-usuarios deu ao usuario no broker.
  senha_usuario=$($K -n "$NS" get secret rabbitmq-credenciais -o "jsonpath={.data.senha-$usuario}" | base64 -d)
  if [ -z "$senha_usuario" ]; then
    echo "secret $NS/rabbitmq-credenciais has no key senha-$usuario" >&2
    exit 1
  fi
  mascara "$senha_usuario"
  $K create -f - >/dev/null <<YAML
apiVersion: v1
kind: Secret
metadata:
  name: rabbitmq
  namespace: $servico
type: Opaque
stringData:
  RABBITMQ_URL: "amqp://$usuario:$senha_usuario@rabbitmq.$NS.svc.cluster.local:5672/"
YAML
  echo "secret $servico/rabbitmq created (RABBITMQ_URL of user $usuario)"
done

if existe "$NS" grafana-admin; then
  echo "secret $NS/grafana-admin already exists: kept"
else
  grafana=$(senha)
  mascara "$grafana"
  $K create -f - >/dev/null <<YAML
apiVersion: v1
kind: Secret
metadata:
  name: grafana-admin
  namespace: $NS
  labels:
    app: grafana
    app.kubernetes.io/part-of: pytstop-plataforma
type: Opaque
stringData:
  GF_SECURITY_ADMIN_PASSWORD: "$grafana"
YAML
  echo "secret $NS/grafana-admin created"
fi
