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
# senhas dos bancos (no PostgreSQL, uma por papel), chave RSA do JWT,
# ENCRYPTION_KEY, senha do admin semeado, chave HMAC do link de decisao e as
# credenciais e o keyfile do MongoDB.
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

# Hexadecimal: entra na URL AMQP, no JSON e no YAML sem escape.
senha() { openssl rand -hex 24; }

mascara() {
  [ "${GITHUB_ACTIONS:-}" = true ] || return 0
  local valor
  for valor in "$@"; do echo "::add-mask::$valor"; done
}

# As fontes que ainda nao existem, "<namespace>/<secret>" entre espacos.
faltam=" "

# confere <namespace> <secret> <chave>...: anota em faltam a fonte que ainda
# nao existe. A que existe com todas as chaves fica como esta; sem uma delas, o
# script para, porque nunca reescreve uma fonte e o pod que a le nao subiria.
# Erro ao falar com o cluster aborta, em vez de virar "nao existe" e trocar
# senhas que nao foram lidas.
confere() {
  local ns=$1 nome=$2 atual chave
  shift 2
  atual=$($K -n "$ns" get secret "$nome" --ignore-not-found \
    -o "go-template={{.metadata.name}}:{{range \$chave, \$valor := .data}} {{\$chave}}{{end}}") || exit 1
  if [ -z "$atual" ]; then
    faltam="$faltam$ns/$nome "
    return 0
  fi
  for chave in "$@"; do
    case "$atual " in
      *" $chave "*) ;;
      *)
        echo "secret $ns/$nome has no key $chave: add it in the format of the README" \
          "(Segredos gerados); the script never rewrites a source that exists" >&2
        exit 1
        ;;
    esac
  done
  echo "secret $ns/$nome already exists: kept"
}

# falta <namespace> <secret>: status 0 se a conferencia anotou a fonte.
falta() {
  case "$faltam" in
    *" $1/$2 "*) return 0 ;;
  esac
  return 1
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

# sem_volume <namespace> <secret>: a fonte que falta e guarda estado no banco
# do servico (a senha do volume, o hash da senha do admin, o que a
# ENCRYPTION_KEY cifrou) nao nasce de novo com o volume do banco de pe: um
# valor novo nao valeria para ele, e a ENCRYPTION_KEY nova perderia os dados
# cifrados. Erro ao listar os volumes tambem para o script, em vez de virar
# "sem volume".
sem_volume() {
  falta "$1" "$2" || return 0
  local volumes
  volumes=$($K -n "$1" get pvc -o name) || exit 1
  [ -n "$volumes" ] || return 0
  echo "secret $1/$2 is missing but $1 has database volumes (${volumes//$'\n'/ }):" \
    "restore the secret (README, Segredos gerados). Deleting the volumes destroys the" \
    "database; only on a demo cluster: $K -n $1 delete pvc --all" >&2
  exit 1
}

# Todas as fontes conferidas antes de gerar qualquer valor: a que existe sem
# uma das chaves e a do banco que falta com o volume de pe param o script sem
# gravar nada.
confere "$NS" rabbitmq-credenciais admin-usuario admin-senha senha-os senha-billing \
  senha-execucao admin.json
confere "$NS" grafana-admin GF_SECURITY_ADMIN_PASSWORD
for banco in os execucao; do
  confere "pytstop-$banco" "$banco-postgres" POSTGRES_PASSWORD POSTGRES_OWNER_PASSWORD \
    POSTGRES_APP_PASSWORD POSTGRES_EXPORTER_PASSWORD
  sem_volume "pytstop-$banco" "$banco-postgres"
done
confere pytstop-os os-jwt JWT_PRIVATE_KEY JWT_PREVIOUS_PUBLIC_KEY
confere pytstop-os os-cripto ENCRYPTION_KEY
sem_volume pytstop-os os-cripto
confere pytstop-os os-admin ADMIN_PASSWORD
sem_volume pytstop-os os-admin
confere pytstop-billing billing-mongo MONGO_INITDB_ROOT_PASSWORD MONGO_BILLING_PASSWORD \
  MONGO_EXPORTER_PASSWORD MONGO_KEYFILE
sem_volume pytstop-billing billing-mongo
confere pytstop-billing billing-link ORCAMENTO_LINK_SECRET

if falta "$NS" rabbitmq-credenciais; then
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

if falta "$NS" grafana-admin; then
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
  if falta "pytstop-$banco" "$banco-postgres"; then
    # Uma senha por papel: o superusuario postgres, que so inicializa o banco;
    # o dono (DDL, Job de migracao); o da aplicacao (so DML, os processos do
    # servico); e o do exporter (pg_monitor). Os papeis nascem no script de
    # init do banco, nos manifests do servico.
    superusuario=$(senha)
    dono=$(senha)
    aplicacao=$(senha)
    monitor=$(senha)
    mascara "$superusuario" "$dono" "$aplicacao" "$monitor"
    cria "pytstop-$banco" "$banco-postgres" <<YAML
  POSTGRES_PASSWORD: "$superusuario"
  POSTGRES_OWNER_PASSWORD: "$dono"
  POSTGRES_APP_PASSWORD: "$aplicacao"
  POSTGRES_EXPORTER_PASSWORD: "$monitor"
YAML
  fi
done

if falta pytstop-os os-jwt; then
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

if falta pytstop-os os-cripto; then
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
if falta pytstop-os os-admin; then
  admin_os=$(senha)
  mascara "$admin_os"
  cria pytstop-os os-admin <<YAML
  ADMIN_PASSWORD: "$admin_os"
YAML
fi

if falta pytstop-billing billing-mongo; then
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

if falta pytstop-billing billing-link; then
  # 32 bytes aleatorios em 64 caracteres hexadecimais: o boot do Billing
  # exige ao menos 32 bytes.
  link=$(openssl rand -hex 32)
  mascara "$link"
  cria pytstop-billing billing-link <<YAML
  ORCAMENTO_LINK_SECRET: "$link"
YAML
fi
