# Segredos gerados

> [↑ Raiz do projeto](../README.md)

Nenhuma senha ou chave fica nos manifests. O `make deploy` roda o [`gerar-segredos.sh`](../scripts/gerar-segredos.sh) antes do apply, e ele cuida de dois tipos de Secret: a fonte, criada só se ainda não existe, ou seja, no primeiro deploy de cada cluster, e o derivado, regravado em todo deploy a partir da fonte. Os Secrets dos serviços nascem no namespace de cada um, que o `make deploy` cria vazio se ainda não existe, e o serviço não os declara nos manifests dele: só os lê, por `secretKeyRef`. Os comandos de troca usam o contexto do kind; no k3s, troque o `--context`.

| Secret | Namespace | Chaves (formato) | Quem lê | Quando o script grava | Como girar |
|---|---|---|---|---|---|
| `rabbitmq-credenciais` (fonte) | `pytstop-plataforma` | `admin-usuario` (`admin`), `admin-senha`, `senha-os`, `senha-billing` e `senha-execucao` (48 hexadecimais cada) e o `admin.json` que o broker importa no boot | RabbitMQ e Job `rabbitmq-usuarios` | Só se ainda não existe | [Troca de senha do RabbitMQ](#troca-de-senha-do-rabbitmq) |
| `grafana-admin` (fonte) | `pytstop-plataforma` | `GF_SECURITY_ADMIN_PASSWORD` (48 hexadecimais) | Grafana (no `kind-ci`, sem Grafana, fica sem uso) | Só se ainda não existe | Apagar o Secret, `make deploy` e `rollout restart deployment/grafana` no `pytstop-plataforma`: sem volume, o Grafana cria o admin com a senha do Secret a cada start |
| `rabbitmq` (derivado) | `pytstop-os`, `pytstop-billing` e `pytstop-execucao` | `RABBITMQ_URL` do usuário do serviço, com a senha do `rabbitmq-credenciais` ([contrato com os serviços](rabbitmq.md#usuário-e-permissões-no-rabbitmq)) | relay, consumidor e `prazos` | Em todo deploy, com a senha que está na fonte | Segue a fonte: a senha trocada no `rabbitmq-credenciais` chega aqui no `make deploy` seguinte |
| `os-postgres` (fonte) | `pytstop-os` | Uma senha por papel, 48 hexadecimais cada: `POSTGRES_PASSWORD` (superusuário `postgres`), `POSTGRES_OWNER_PASSWORD` (`os`, dono das tabelas: DDL, *data definition language*, criar e alterar tabelas), `POSTGRES_APP_PASSWORD` (`os_app`: só DML, *data manipulation language*: SELECT, INSERT, UPDATE e DELETE, nas tabelas do dono) e `POSTGRES_EXPORTER_PASSWORD` (`os_exporter`: `pg_monitor`) | PostgreSQL, que cria os papéis na primeira inicialização do volume (script de init nos manifests do serviço); `os`: Job de migração; `os_app`: API, relay, consumidor, `prazos` e `notificador`; `os_exporter`: exporter | Só se ainda não existe | Com janela, pelos passos de [Troca de senha do banco](#troca-de-senha-do-banco): a senha nova no Secret, o `ALTER ROLE` do papel, como `postgres`, sem a senha em argumento nem no log do servidor, e o restart de quem usa o papel: `os_app`, os Deployments do serviço; `os_exporter`, o StatefulSet do banco, porque o exporter é sidecar dele e o banco reinicia junto; `os`, o Job, que a relê no deploy seguinte do serviço; `postgres`, o StatefulSet do banco, que lê a senha dele só no start (sem o restart, a próxima troca não autentica). Até o restart, conexão nova com a senha antiga é recusada |
| `execucao-postgres` (fonte) | `pytstop-execucao` | Uma senha por papel, 48 hexadecimais cada: `POSTGRES_PASSWORD` (superusuário `postgres`), `POSTGRES_OWNER_PASSWORD` (`execucao`, dono das tabelas: DDL), `POSTGRES_APP_PASSWORD` (`execucao_app`: só DML nas tabelas do dono) e `POSTGRES_EXPORTER_PASSWORD` (`execucao_exporter`: `pg_monitor`) | PostgreSQL, que cria os papéis na primeira inicialização do volume (script de init nos manifests do serviço); `execucao`: Job de migração; `execucao_app`: API, relay e consumidor; `execucao_exporter`: exporter | Só se ainda não existe | Como a do `os-postgres`, com o namespace `pytstop-execucao`, o StatefulSet `execucao-postgres` e os papéis `execucao`, `execucao_app` e `execucao_exporter` |
| `os-jwt` (fonte) | `pytstop-os` | `JWT_PRIVATE_KEY` (RSA de 2048 bits em PEM PKCS#8) e `JWT_PREVIOUS_PUBLIC_KEY` (vazia; durante a rotação, recebe a chave pública que entra, na etapa 1, ou a que sai, na etapa 2, só publicada no JWKS) | API do OS Service | Só se ainda não existe | Sem derrubar sessão, pelas etapas da [rotação da chave](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-os-service#rotação-da-chave) do OS Service ([ADR-039](arquitetura/adr/fase4/039-autenticacao-entre-servicos.md)): as chaves de cada etapa no Secret e o `rollout restart` da API do OS. Apagar o Secret, rodar o `make deploy` e reiniciar a API é a troca de emergência, que derruba as sessões |
| `os-cripto` (fonte) | `pytstop-os` | `ENCRYPTION_KEY` (chave Fernet: 32 bytes em base64 url-safe, 44 caracteres) | API e relay do OS Service | Só se ainda não existe; nunca é regenerada | Não gira sem migração: a chave nova exige recifrar os dados pessoais e recalcular o hash do documento ([ADR-042](arquitetura/adr/fase4/042-cicd-e-deploy-kubernetes.md)) |
| `os-admin` (fonte) | `pytstop-os` | `ADMIN_PASSWORD` (48 hexadecimais), a senha do admin | Job de migração do OS Service (semente) e E2E | Só se ainda não existe | Não gira pelo Secret: a semente só cria o admin que ainda não existe, e o OS Service não tem troca de senha; o Secret guarda a senha da primeira semente |
| `billing-mongo` (fonte) | `pytstop-billing` | `MONGO_INITDB_ROOT_PASSWORD` (root), `MONGO_BILLING_PASSWORD` (`billing`) e `MONGO_EXPORTER_PASSWORD` (`exporter`), 48 hexadecimais cada, e `MONGO_KEYFILE` (756 bytes em base64, 1.008 caracteres numa linha) | mongod (o root, no primeiro boot, e o keyfile), Job de inicialização, processos do serviço e exporter | Só se ainda não existe | Senhas, com janela, pelos passos de [Troca de senha do banco](#troca-de-senha-do-banco): a senha nova no Secret, o `changeUserPassword` no banco do usuário (`billing` no banco `billing`, o `exporter` e o root em `admin`), como root, sem a senha em argumento, e o restart de quem usa o usuário: `billing`, os Deployments do Billing; `exporter`, o StatefulSet do banco; o root, o Job, que a relê no deploy seguinte do serviço, e o StatefulSet do banco, para a variável `MONGO_INITDB_ROOT_PASSWORD` do contêiner voltar a ser a do Secret (a troca seguinte autentica o root pela senha do Secret, e não pela variável). Keyfile, com o banco fora durante o restart: o valor novo no Secret e `rollout restart statefulset/billing-mongo`; o replica set tem um membro só, e nenhum outro precisa da chave antiga |
| `billing-link` (fonte) | `pytstop-billing` | `ORCAMENTO_LINK_SECRET` (64 hexadecimais), a chave HMAC do link de decisão e do checkout do simulador | API e consumidor do Billing | Só se ainda não existe | Apagar o Secret, `make deploy` e o `rollout restart` dos Deployments do Billing, a API e o consumidor juntos: os links e checkouts já enviados deixam de valer (o orçamento que aguarda decisão fica sem link até vencer, e o atendente ainda decide por ele), e até o fim do restart um link pode abrir numa réplica e dar 404 em outra |

Os valores saem do `openssl`: as senhas são 24 bytes do `openssl rand` em hexadecimal (48 caracteres, que entram em URL, JSON e YAML sem escape), e a chave RSA vem do `openssl genpkey`. O restart que cada troca pede é o `rollout restart` do Deployment ou do StatefulSet no namespace do serviço (`kubectl --context kind-pytstop-p4 -n pytstop-billing rollout restart deployment` reinicia todos os Deployments do Billing), porque o pod lê o Secret só no start.

As fontes ficam como estão nos deploys seguintes porque o valor de cada uma já está gravado em outro lugar: no broker, que lê o `admin.json` só no boot (uma senha de admin nova com o broker de pé deixaria o Job `rabbitmq-usuarios` sem acesso à API, 401, até o próximo restart); no volume do banco, onde o PostgreSQL e o MongoDB aplicam as senhas do Secret só na primeira inicialização; nos tokens emitidos, que uma chave RSA nova invalidaria; e nos dados cifrados, que uma `ENCRYPTION_KEY` nova deixaria ilegíveis. Antes de gerar qualquer valor, o script confere todas as fontes e para sem gravar nada em dois casos. Uma fonte que existe sem uma das chaves da tabela, editada à mão ou criada antes de a chave entrar no contrato, volta a valer com a chave acrescentada à mão, no formato da tabela (uma senha nova de papel do PostgreSQL pede também o `CREATE ROLE` no banco; num cluster de demonstração, recriar o cluster é mais curto). E, se uma fonte que guarda estado no banco do serviço (`os-postgres`, `execucao-postgres`, `os-cripto`, `os-admin` ou `billing-mongo`) some com o volume do banco de pé, o caminho é devolver o Secret ou, num cluster de demonstração, apagar o namespace do serviço, que leva o banco junto, e implantar de novo a plataforma e o serviço (apagar só o volume não basta: o Kubernetes não o apaga enquanto o pod do banco o usa, e o StatefulSet cria outro, vazio); erro ao listar os volumes também para o script.

O derivado é regravado em todo deploy, com a mesma senha que o Job aplica no broker, e assim uma senha trocada na fonte chega ao serviço no deploy seguinte. Antes de gravá-lo, o script confere que a senha da fonte tem só letras e dígitos, porque ela entra crua na URL, e para com erro, sem mostrar a senha, se não tiver. Os bancos não têm derivado: a URL de conexão se monta no pod, por expansão de variável (`$(POSTGRES_APP_PASSWORD)` dentro da `DATABASE_URL` dos processos), e o `kubectl describe` do pod mostra o molde, não a senha.

No PostgreSQL, os papéis separados só mantêm o superusuário fora do alcance de um sidecar comprometido se o banco pedir senha também na loopback. O exporter é sidecar do pod do banco e chega a ele por ela, e a imagem oficial do `postgres` deixa o socket, o `127.0.0.1` e o `::1` em `trust`: num contêiner avulso do `postgres:16.15`, `psql -h 127.0.0.1 -U postgres` entra como superusuário sem senha. Por isso o StatefulSet do banco de cada serviço define `POSTGRES_INITDB_ARGS="--auth-host=scram-sha-256 --auth-local=scram-sha-256"`, requisito do contrato com os serviços. Com ele, a loopback e o socket pedem senha (a do exporter não abre o `postgres`) e o entrypoint da imagem ainda roda o script de init dos papéis. Como as senhas, ele vale só na primeira inicialização do volume: num volume que nasceu sem ele, o `pg_hba.conf` continua em `trust`.

O admin é o único usuário semeado no OS Service: o Job de migração o cria com o `ADMIN_EMAIL` do ConfigMap do serviço e a senha do `os-admin`, e atendente e mecânico são cadastrados pela API, com o token do admin. O `billing-mercadopago` (`MP_ACCESS_TOKEN` e `MP_WEBHOOK_SECRET`) não sai do script de segredos: são as credenciais do Mercado Pago. Nunca vão para o GitHub ([ADR-042](arquitetura/adr/fase4/042-cicd-e-deploy-kubernetes.md)): no kind local são as credenciais de teste, que ficam só no ambiente do shell de quem roda a prova, e num cluster remoto o dono do ambiente cria o Secret no cluster ([Nuvem opcional](operacao/nuvem-opcional.md#o-que-o-gancho-não-faz)). O `make mp-sandbox` cria o Secret pelo stdin (nunca em argumento nem em arquivo), liga o modo real e o desfaz no fim ([Mercado Pago na sandbox](mercado-pago-na-sandbox.md#mercado-pago-na-sandbox)). Sem ele, o Billing usa o simulador, que assina o checkout com a mesma `ORCAMENTO_LINK_SECRET`, num domínio próprio: o token do link não abre o checkout, e o do checkout não abre o link.

Nenhuma senha ou chave passa por argumento de processo, por variável exportada, pela saída ou pelo repositório: os Secrets chegam ao `kubectl` pela entrada padrão, o script desliga o trace do bash, e no GitHub Actions cada valor, gerado ou lido da fonte, é registrado com `::add-mask::` antes do uso, então o log do job o mostra como `***`. A chave PEM é registrada uma linha por vez, porque o comando vale até o fim da linha: com ela inteira, o resto da chave sairia em claro no log. O derivado é gravado por apply server-side, que não guarda o Secret inteiro, com a senha em claro, na anotação `last-applied-configuration`. No kind do CI os valores morrem com o runner, e o job `deploy-kind` roda o script uma segunda vez e confere que nenhum Secret mudou. O [`test_gerar_segredos.py`](../tests/test_gerar_segredos.py) roda o script contra um `kubectl` falso e confere, entre outros casos, as linhas das fontes dos serviços desta tabela contra o que ele cria: nome, namespace, chaves, formato e quando o script grava.

## Troca de senha do RabbitMQ

A senha nova tem só letras e dígitos, porque entra crua na URL; a do `openssl rand -hex 24` serve. Os comandos usam o contexto do kind (no k3s, troque o `--context`), e a senha vai do shell ao `jq` por variável de ambiente, não por argumento.

Usuário de serviço (`os`, `billing` ou `execucao`; o exemplo troca a do `billing`):

1. Grave a senha nova na chave `senha-billing` do `rabbitmq-credenciais`:

   ```bash
   senha=$(openssl rand -hex 24)
   kubectl --context kind-pytstop-p4 -n pytstop-plataforma get secret rabbitmq-credenciais -o json \
     | SENHA="$senha" jq '.data["senha-billing"] = (env.SENHA | @base64)' \
     | kubectl --context kind-pytstop-p4 replace -f -
   ```

2. `make deploy`: o Job `rabbitmq-usuarios` aplica a senha no broker, e o `gerar-segredos.sh` regrava com ela a `RABBITMQ_URL` do Secret `rabbitmq` do `pytstop-billing`.
3. Reinicie os Deployments do serviço, que leem a variável só no start: `kubectl --context kind-pytstop-p4 -n pytstop-billing rollout restart deployment`.

Admin:

1. Grave a senha nova em `admin-senha` e dentro do `admin.json`, que mantém o formato `"password": "<senha>"` (o `make smoke` lê a senha do arquivo montado no pod por esse padrão):

   ```bash
   senha=$(openssl rand -hex 24)
   kubectl --context kind-pytstop-p4 -n pytstop-plataforma get secret rabbitmq-credenciais -o json \
     | SENHA="$senha" jq '.data["admin-senha"] = (env.SENHA | @base64)
         | .data["admin.json"] = (.data["admin.json"] | @base64d
             | sub("\"password\": \"[^\"]*\""; "\"password\": \"\(env.SENHA)\"") | @base64)' \
     | kubectl --context kind-pytstop-p4 replace -f -
   ```

2. Reinicie o broker, que aplica o `admin.json` só no boot, e espere: `kubectl --context kind-pytstop-p4 -n pytstop-plataforma rollout restart statefulset/rabbitmq` e, em seguida, `rollout status statefulset/rabbitmq`.
3. `make deploy`: o Job `rabbitmq-usuarios` volta a falar com a API, agora com a senha nova.

Um cluster criado antes das senhas geradas ainda tem as de demonstração, que têm hífen: o `make deploy` para na conferência da senha, e `make kind-down kind-up deploy` recria o cluster com senhas geradas.

## Troca de senha do banco

A senha nova vai do shell ao pod pela entrada padrão do `kubectl exec -i`, e o `psql` ou o `mongosh` a lê da variável de ambiente `SENHA_NOVA`, nunca de um argumento: o argumento de um `kubectl exec` fica no `ps` da máquina e na URL do pedido ao apiserver, que o log de auditoria, quando ligado, registra, e o de um `psql -c "ALTER ROLE … PASSWORD '<senha>'"` ainda vai para o log do servidor se o comando falhar. O `printf` do bash e do zsh é interno ao shell, então a senha também não aparece no `ps`. Os comandos usam o contexto do kind (no k3s, troque o `--context`) e supõem os nomes que os manifests dos serviços devem ter: o StatefulSet `os-postgres` com o contêiner `postgres`, e o `billing-mongo` com o `mongo`.

PostgreSQL (o exemplo troca a do `os_app`; para outro papel, troque a chave do Secret e o nome do papel). Grave a senha nova no Secret antes de aplicá-la no banco, para que o valor não fique só numa variável do shell:

```bash
senha=$(openssl rand -hex 24)
kubectl --context kind-pytstop-p4 -n pytstop-os get secret os-postgres -o json \
  | SENHA="$senha" jq '.data["POSTGRES_APP_PASSWORD"] = (env.SENHA | @base64)' \
  | kubectl --context kind-pytstop-p4 replace -f -
```

Aplique no banco, como `postgres`: o contêiner do banco já tem a senha dele em `POSTGRES_PASSWORD`, e o `-w` impede o `psql` de pedir senha de conexão, que sem terminal ele leria do próprio script. A saída esperada é cinco `SET` e um `ALTER ROLE`:

```bash
{ printf '%s\n' "$senha"; cat <<'SQL'
SET log_statement = 'none';
SET log_min_error_statement = 'panic';
SET log_min_duration_statement = -1;
SET log_min_duration_sample = -1;
SET log_transaction_sample_rate = 0;
\getenv senha SENHA_NOVA
ALTER ROLE os_app PASSWORD :'senha';
SQL
} | kubectl --context kind-pytstop-p4 -n pytstop-os exec -i statefulset/os-postgres -c postgres -- \
    sh -c 'read -r SENHA_NOVA && [ -n "$SENHA_NOVA" ] && export SENHA_NOVA && PGPASSWORD=$POSTGRES_PASSWORD exec psql -w -U postgres -v ON_ERROR_STOP=1'
```

O `psql` troca `:'senha'` pelo valor antes de enviar o comando (o `psql -c` do 16 não faz essa troca), então o servidor recebe a senha em claro. Os cinco `SET`, que valem só para a sessão, a tiram do log do servidor: sem eles, um `log_statement` em `all` ou `ddl` registra o comando, um comando que falha registra a linha `STATEMENT` com a senha, e `log_min_duration_statement`, `log_min_duration_sample` ou `log_transaction_sample_rate` ligados registram o texto do comando pela duração ou por amostragem. A regra é desligar todo parâmetro que grava o texto do comando. Por fim, reinicie quem usa o papel, como diz a coluna "Como girar" da tabela; para o `os_app`, `kubectl --context kind-pytstop-p4 -n pytstop-os rollout restart deployment`.

MongoDB. O `replica-set.js` do Billing cria o `billing` no banco `billing` (`authSource=billing`), e o `exporter` e o root ficam em `admin`: a troca vai no banco do usuário, e no banco errado o `mongosh` responde `User billing@admin not found`. Os três seguem os mesmos passos, e a tabela diz o que muda; o exemplo é o do `billing`:

| Credencial | Chave do Secret `billing-mongo` | Usuário | Banco | O que reiniciar depois |
|---|---|---|---|---|
| `billing` | `MONGO_BILLING_PASSWORD` | `billing` | `billing` | os Deployments do Billing |
| `exporter` | `MONGO_EXPORTER_PASSWORD` | `exporter` | `admin` | o StatefulSet do banco, porque o exporter é sidecar dele |
| root | `MONGO_INITDB_ROOT_PASSWORD` | `root` | `admin` | o StatefulSet do banco; o Job relê a senha no deploy seguinte |

Leia primeiro a senha do root que o banco tem agora, a do Secret, e só então gere a senha nova e grave-a. O root autentica com a senha do Secret, e não com a variável do contêiner, que só acompanha o Secret no restart: se o restart de uma troca anterior do root foi pulado, a variável guarda uma senha que o banco já não aceita.

```bash
chave=MONGO_BILLING_PASSWORD usuario=billing banco=billing
senha_root=$(kubectl --context kind-pytstop-p4 -n pytstop-billing get secret billing-mongo -o json \
  | jq -r '.data.MONGO_INITDB_ROOT_PASSWORD | @base64d')
senha=$(openssl rand -hex 24)
kubectl --context kind-pytstop-p4 -n pytstop-billing get secret billing-mongo -o json \
  | VALOR="$senha" jq --arg chave "$chave" '.data[$chave] = (env.VALOR | @base64)' \
  | kubectl --context kind-pytstop-p4 replace -f -
```

Aplique no banco, como root. As duas senhas vão nas duas primeiras linhas da entrada, e o `sh` do contêiner as lê para `SENHA_NOVA` e `SENHA_ROOT`:

```bash
{ printf '%s\n%s\n' "$senha" "$senha_root"; cat <<JS
db.getSiblingDB("admin").auth(process.env.MONGO_INITDB_ROOT_USERNAME, process.env.SENHA_ROOT)
db.getSiblingDB("$banco").changeUserPassword("$usuario", process.env.SENHA_NOVA)
print("senha de $usuario trocada")
JS
} | kubectl --context kind-pytstop-p4 -n pytstop-billing exec -i statefulset/billing-mongo -c mongo -- \
    sh -c 'read -r SENHA_NOVA && read -r SENHA_ROOT && [ -n "$SENHA_NOVA" ] && [ -n "$SENHA_ROOT" ] && export SENHA_NOVA SENHA_ROOT && exec mongosh --quiet --norc --file /dev/stdin'
```

O `mongosh` lê o script como arquivo (`--file /dev/stdin`) e não da entrada interativa, que sai com 0 mesmo quando a autenticação falha. Deu certo quando o comando sai com 0 e imprime `senha de billing trocada`; se a autenticação ou a troca falhar, ele imprime o erro do MongoDB (`MongoServerError: Authentication failed.` ou `User billing@admin not found`) e sai com código diferente de zero. Se o passo falhar, repita-o com a mesma senha: o Secret já tem a nova, e reiniciar os pods com o Secret diferente do banco os deixa sem acesso. Se a sessão do shell acabou entre o Secret e o banco, leia a senha nova do Secret em vez de gerar outra (`senha=$(kubectl --context kind-pytstop-p4 -n pytstop-billing get secret billing-mongo -o json | jq -r --arg chave "$chave" '.data[$chave] | @base64d')`). Na troca do root, `$senha_root` é a única cópia da senha anterior depois de gravar o Secret, então não feche a sessão antes de o passo dar certo; se já a perdeu, a variável `MONGO_INITDB_ROOT_PASSWORD` do contêiner do banco ainda guarda a anterior, enquanto o banco não reiniciou. Quando der certo, limpe as senhas do shell com `unset senha senha_root`. O restart de quem usa o usuário vem da coluna da tabela e da coluna "Como girar" dos segredos. O [`docs/troca-de-senhas-e-chaves.md` do Billing](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-billing-service/blob/main/docs/troca-de-senhas-e-chaves.md) traz o procedimento de cada credencial do serviço.
