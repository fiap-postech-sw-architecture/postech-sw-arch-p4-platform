#!/usr/bin/env bash
# Segredos de runtime da plataforma e dos servicos (make deploy, antes do
# apply; ADR-042).
#
# Fontes da plataforma: rabbitmq-credenciais (senhas do admin do RabbitMQ e
# dos usuarios os, billing e execucao, mais o admin.json) e grafana-admin. O
# script gera as senhas com openssl rand e cria cada fonte so se ela ainda nao
# existe, ou seja, no primeiro deploy de cada cluster: o RabbitMQ le o
# admin.json so no boot, e uma senha de admin nova com o broker de pe deixaria
# o Job rabbitmq-usuarios sem acesso a API (401) ate o proximo restart.
#
# Fontes dos servicos, no namespace de cada um (README, "Segredos gerados"):
# senhas dos bancos, chave RSA do JWT, ENCRYPTION_KEY, senha do admin semeado,
# chave HMAC do link de decisao e as credenciais e o keyfile do MongoDB.
# Tambem so se ainda nao existem: o banco aplica a senha so na primeira
# inicializacao do volume, e uma ENCRYPTION_KEY nova deixaria ilegivel o que
# ja foi cifrado. Pelo mesmo motivo, a que guarda estado no banco nao nasce
# de novo se o volume dele ja existe. Nenhuma tem derivado: a URL do banco se
# monta no pod, por expansao de variavel.
#
# Derivado: o Secret rabbitmq de cada namespace de servico (pytstop-os,
# pytstop-billing, pytstop-execucao), com a chave RABBITMQ_URL, a URL do
# usuario do servico no broker. E o contrato com os servicos (README, "Usuario
# e permissoes no RabbitMQ") e e regravado a cada deploy com a senha da fonte,
# a mesma que o Job rabbitmq-usuarios aplica no broker: trocar a senha na
# fonte vale no deploy seguinte (README, "Troca de senha do RabbitMQ").
#
# Nenhuma senha ou chave vai para argumento de processo, para a saida ou para
# o repositorio: o Secret chega ao kubectl pela entrada padrao. No GitHub
# Actions cada valor e registrado com ::add-mask:: antes do uso (a chave PEM,
# uma linha por vez), e o log do job o mostra como ***.
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

# ausente <namespace> <secret>: status 0 se a fonte ainda nao existe; se ja
# existe, avisa que ela fica como esta.
ausente() {
  if existe "$1" "$2"; then
    echo "secret $1/$2 already exists: kept"
    return 1
  fi
}

# cria <namespace> <secret> [<app>]: cria a fonte com as chaves do stringData
# que chegam pela entrada padrao, indentadas em dois espacos. Com <app>, leva os
# rotulos app e part-of da plataforma, como os manifests dela. As fontes dos
# servicos vao sem rotulo: o part-of de um servico marca o que os manifests
# dele aplicam, e estas o servico so le.
cria() {
  {
    printf 'apiVersion: v1\nkind: Secret\nmetadata:\n  name: %s\n  namespace: %s\n' "$2" "$1"
    [ -z "${3:-}" ] || printf '  labels:\n    app: %s\n    app.kubernetes.io/part-of: pytstop-plataforma\n' "$3"
    printf 'type: Opaque\nstringData:\n'
    cat
  } | $K create -f - >/dev/null
  echo "secret $1/$2 created"
}

# sem_volume <namespace> <secret>: a fonte que falta guarda estado no banco do
# servico (a senha do volume, o hash da senha do admin, o que a ENCRYPTION_KEY
# cifrou). Com o volume do banco de pe, um valor novo nao valeria para ele, e
# a ENCRYPTION_KEY nova perderia os dados cifrados: para em vez de gerar.
sem_volume() {
  local volumes
  volumes=$($K -n "$1" get pvc -o name)
  [ -z "$volumes" ] && return
  echo "secret $1/$2 is missing but $1 already has a database volume:" \
    "restore the secret, or delete the volume to start the database from scratch" >&2
  exit 1
}

if ausente "$NS" rabbitmq-credenciais; then
  admin=$(senha)
  os=$(senha)
  billing=$(senha)
  execucao=$(senha)
  mascara "$admin" "$os" "$billing" "$execucao"
  # admin.json declara o vhost / tambem: o RabbitMQ importa o diretorio de
  # definitions em ordem alfabetica, admin.json antes de definitions.json, e
  # permissao em vhost que ainda nao existe derruba o boot.
  cria "$NS" rabbitmq-credenciais rabbitmq <<YAML
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
fi

for usuario in os billing execucao; do
  servico="pytstop-$usuario"
  # A senha que o Job rabbitmq-usuarios aplica ao usuario no broker.
  senha_usuario=$($K -n "$NS" get secret rabbitmq-credenciais -o "jsonpath={.data.senha-$usuario}" | base64 -d)
  if [ -z "$senha_usuario" ]; then
    echo "secret $NS/rabbitmq-credenciais has no key senha-$usuario" >&2
    exit 1
  fi
  mascara "$senha_usuario"
  # Vai crua na URL e no YAML, entao so letras e digitos. A de demonstracao,
  # de um cluster criado antes das senhas geradas, tem hifen e para aqui.
  if ! [[ "$senha_usuario" =~ ^[A-Za-z0-9]+$ ]]; then
    echo "secret $NS/rabbitmq-credenciais: senha-$usuario must have only letters and digits (A-Z, a-z, 0-9)." \
      "Change it as in the README (Troca de senha do RabbitMQ); a kind cluster created with the demo" \
      "passwords is recreated with make kind-down kind-up deploy" >&2
    exit 1
  fi
  # Server-side: o apply client-side guardaria o Secret inteiro, senha em
  # claro, na anotacao last-applied-configuration. --force-conflicts porque o
  # script e o dono da chave, mesmo que outro processo a tenha gravado antes.
  $K apply --server-side --force-conflicts --field-manager=gerar-segredos -f - >/dev/null <<YAML
apiVersion: v1
kind: Secret
metadata:
  name: rabbitmq
  namespace: $servico
type: Opaque
stringData:
  RABBITMQ_URL: "amqp://$usuario:$senha_usuario@rabbitmq.$NS.svc.cluster.local:5672/%2F"
YAML
  echo "secret $servico/rabbitmq applied (RABBITMQ_URL of user $usuario)"
done

if ausente "$NS" grafana-admin; then
  grafana=$(senha)
  mascara "$grafana"
  cria "$NS" grafana-admin grafana <<YAML
  GF_SECURITY_ADMIN_PASSWORD: "$grafana"
YAML
fi

# Fontes dos servicos. O billing-mercadopago (MP_ACCESS_TOKEN e
# MP_WEBHOOK_SECRET) nao sai daqui: sao credenciais do provedor, e o simulador
# assina o checkout com o ORCAMENTO_LINK_SECRET.
for banco in os execucao; do
  if ausente "pytstop-$banco" "$banco-postgres"; then
    sem_volume "pytstop-$banco" "$banco-postgres"
    postgres=$(senha)
    mascara "$postgres"
    cria "pytstop-$banco" "$banco-postgres" <<YAML
  POSTGRES_PASSWORD: "$postgres"
YAML
  fi
done

if ausente pytstop-os os-jwt; then
  # PKCS#8. Os pontos que o genpkey escreve no stderr sao so o progresso.
  pem=$(openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048)
  # O runner mascara uma linha por vez.
  while IFS= read -r linha; do mascara "$linha"; done <<<"$pem"
  pem_indentado=${pem//$'\n'/$'\n'    }
  # A chave anterior fica vazia; so recebe a publica durante a rotacao.
  cria pytstop-os os-jwt <<YAML
  JWT_PRIVATE_KEY: |
    $pem_indentado
  JWT_PREVIOUS_PUBLIC_KEY: ""
YAML
fi

if ausente pytstop-os os-cripto; then
  sem_volume pytstop-os os-cripto
  # Chave Fernet: 32 bytes em base64 url-safe, com o "=" do fim (44
  # caracteres). Nunca regenerada (ADR-042).
  fernet=$(openssl rand -base64 32 | tr '+/' '-_')
  mascara "$fernet"
  cria pytstop-os os-cripto <<YAML
  ENCRYPTION_KEY: "$fernet"
YAML
fi

# O admin e o unico usuario semeado; atendente e mecanico se cadastram pela
# API, com o token dele.
if ausente pytstop-os os-admin; then
  sem_volume pytstop-os os-admin
  admin_os=$(senha)
  mascara "$admin_os"
  cria pytstop-os os-admin <<YAML
  ADMIN_PASSWORD: "$admin_os"
YAML
fi

if ausente pytstop-billing billing-mongo; then
  sem_volume pytstop-billing billing-mongo
  root=$(senha)
  billing_mongo=$(senha)
  exporter=$(senha)
  # Keyfile do replica set: 756 bytes em base64 numa linha so, 1008
  # caracteres (o mongod aceita ate 1024).
  keyfile=$(openssl rand -base64 756 | tr -d '\n')
  mascara "$root" "$billing_mongo" "$exporter" "$keyfile"
  cria pytstop-billing billing-mongo <<YAML
  MONGO_INITDB_ROOT_PASSWORD: "$root"
  MONGO_BILLING_PASSWORD: "$billing_mongo"
  MONGO_EXPORTER_PASSWORD: "$exporter"
  MONGO_KEYFILE: "$keyfile"
YAML
fi

if ausente pytstop-billing billing-link; then
  # 32 bytes aleatorios em 64 caracteres hexadecimais: o boot do Billing
  # exige ao menos 32 bytes.
  link=$(openssl rand -hex 32)
  mascara "$link"
  cria pytstop-billing billing-link <<YAML
  ORCAMENTO_LINK_SECRET: "$link"
YAML
fi
