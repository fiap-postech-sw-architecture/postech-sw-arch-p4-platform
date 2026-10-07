# Runbook da saga de atendimento

> [↑ Raiz do projeto](../../README.md)

Vale a partir da versão do OS Service com o orquestrador da saga, implantada no kind. Antes dela não existem as rotas `/api/v1/sagas`, a tabela `sagas`, o processo `prazos`, as métricas `pytstop_saga_*` e os logs da saga, e os passos que os usam não têm o que mostrar. A fila, a DLQ, o redrive e o alerta "DLQ com mensagens" já valem.

Procedimento para os alertas "Saga parada" e "DLQ com mensagens" e para a ordem de serviço que não anda. As regras citadas estão na [RFC-004](../arquitetura/rfc/fase4/rfc-004-microsservicos-saga.md), seções 4.3, 4.5 a 4.7, 6.1, 7.2 e 9; métricas e alertas, no [ADR-043](../arquitetura/adr/fase4/043-observabilidade-distribuida.md); retry, DLQ e redrive, no [ADR-036](../arquitetura/adr/fase4/036-mensageria-rabbitmq.md).

| Sinal | Seção |
|---|---|
| Alerta "Saga parada", com instância em `falha_na_compensacao` | [1](#1-achar-a-saga-parada) e [2](#2-falha-na-compensação-e-retomada) |
| Alerta "Saga parada", com prazo técnico vencido | [1](#1-achar-a-saga-parada) e [3](#3-prazo-técnico-vencido-sem-reenvio) |
| Alerta "DLQ com mensagens" (`pytstop-dlq-com-mensagens`) | [4](#4-mensagem-na-dlq-e-redrive) |
| OS que não anda, relatada pelo atendente | [1](#1-achar-a-saga-parada) e [5](#5-o-trace-e-os-logs-pelo-correlation_id) |

## Termos

| Termo | Neste runbook |
|---|---|
| OS e OS Service | a OS é a ordem de serviço; o serviço que a guarda e orquestra a saga é sempre chamado de OS Service |
| Saga | a sequência de passos que leva a OS da abertura à finalização nos três serviços, ou desfaz o que foi feito; uma instância por OS, identificada pelo `ordem_id` |
| Etapa | o estado da instância da saga, como `aguardando_pagamento` ou `falha_na_compensacao`; não é o status da OS, embora dois nomes coincidam |
| Compensação | comando que desfaz um passo já feito, como o `EstornarPagamento`; as compensações saem uma por vez, cada uma esperando a resposta da anterior |
| Prazo técnico | quanto o OS Service espera pela resposta automática a um comando antes de reenviá-lo: 120 s por padrão, contados de quando o comando sai da outbox |
| DLQ | fila de mensagens mortas (`<fila>.dlq`), onde para a mensagem que falhou de vez |
| Redrive | devolver as mensagens de uma DLQ à fila de trabalho, depois de corrigida a causa |

A API, o banco e as métricas escrevem etapa e status em minúsculas (`falha_na_compensacao`, `cancelada`); a RFC usa os mesmos nomes em maiúsculas. Os demais termos estão no [glossário da RFC-004](../arquitetura/rfc/fase4/rfc-004-microsservicos-saga.md#glossário-e-siglas).

## Antes de começar

1. Tenha o `kubectl` com o contexto `kind-pytstop-p4` (o cluster kind `pytstop-p4`), o `jq`, o `curl` e este repositório clonado, de onde rodam os alvos do `make`.
2. Num terminal separado, rode `make port-forward` na raiz do repositório. Ele fica em primeiro plano até o Ctrl+C e abre o Grafana em `http://localhost:3000`, o Prometheus em `:9090`, o Jaeger em `:16686`, o console do RabbitMQ em `:15672` e o Mailpit em `:8025`.
3. Pegue as senhas do usuário `admin` do Grafana e do console do RabbitMQ (o acesso anônimo do Grafana é só Viewer):

   ```bash
   kubectl --context kind-pytstop-p4 -n pytstop-plataforma get secret grafana-admin -o jsonpath='{.data.GF_SECURITY_ADMIN_PASSWORD}' | base64 -d; echo
   kubectl --context kind-pytstop-p4 -n pytstop-plataforma get secret rabbitmq-credenciais -o jsonpath='{.data.admin-senha}' | base64 -d; echo
   ```

4. Defina os endereços das APIs, que respondem pela borda do kind, e entre como `admin` do OS Service. O e-mail e a senha do admin semeado estão nas chaves `ADMIN_EMAIL` e `ADMIN_PASSWORD` de um Secret do namespace `pytstop-os`, gerado pelo deploy ([ADR-042](../arquitetura/adr/fase4/042-cicd-e-deploy-kubernetes.md)). A função `segredo` acha a chave sem depender do nome do Secret, e a senha vai ao `curl` pela entrada padrão, sem aparecer na lista de processos:

   ```bash
   OS=http://localhost/os BILLING=http://localhost/billing EXECUCAO=http://localhost/execucao
   segredo() { kubectl --context kind-pytstop-p4 -n pytstop-os get secrets -o json \
     | jq -r --arg chave "$1" 'first(.items[].data[$chave] // empty) | @base64d'; }
   export ADMIN_EMAIL="$(segredo ADMIN_EMAIL)" ADMIN_SENHA="$(segredo ADMIN_PASSWORD)"
   TOKEN=$(jq -n '{email: env.ADMIN_EMAIL, senha: env.ADMIN_SENHA}' \
     | curl -s "$OS/api/v1/autenticacao/login" -H 'Content-Type: application/json' -d @- \
     | jq -r .access_token)
   ```

   Se `$TOKEN` sair `null`, rode o pipeline de novo sem o `jq -r .access_token` do fim para ver a resposta: 401 é credencial errada, e 429, o limite de tentativas. O mesmo token serve às três APIs, porque o `admin` herda os papéis `atendente` e `mecanico` ([ADR-039](../arquitetura/adr/fase4/039-autenticacao-entre-servicos.md)). Ele vale 15 minutos; depois, repita o login, que aceita 5 tentativas por minuto.

O k3s da Azure é opcional ([ADR-042](../arquitetura/adr/fase4/042-cicd-e-deploy-kubernetes.md)) e fica fora deste runbook: a API do Kubernetes dele não é exposta, e o acesso à VM é por SSH.

## 1. Achar a saga parada

"Saga parada" ([ADR-043](../arquitetura/adr/fase4/043-observabilidade-distribuida.md#alertas), regra `pytstop-saga-parada`) dispara quando uma destas condições dura 5 minutos, e cada uma vale sozinha:

- prazo técnico vencido e não tratado há mais de 60 s, duas vezes o `PRAZOS_INTERVALO_SEGUNDOS` padrão (30 s, o intervalo do `prazos`; o limiar muda junto com a variável), ou seja, `max(pytstop_saga_prazo_vencido_segundos) > 60` ([seção 3](#3-prazo-técnico-vencido-sem-reenvio));
- alguma instância em `falha_na_compensacao`, ou seja, `max(pytstop_saga_ativas{etapa="falha_na_compensacao"}) > 0` ([seção 2](#2-falha-na-compensação-e-retomada)).

### Métricas

No Prometheus (`http://localhost:9090`) ou no Explore do Grafana, entrando como `admin`. Os gauges da saga vêm do coletor da API do OS Service, e cada réplica repete o valor: agregue gauge com `max`, nunca com `sum`.

| Consulta | Leitura |
|---|---|
| `max(pytstop_saga_prazo_vencido_segundos)` | maior atraso de prazo técnico, em segundos; até cerca de 30 s é normal |
| `max by (etapa) (pytstop_saga_ativas)` | instâncias em cada etapa |
| `max by (etapa) (pytstop_saga_etapa_mais_antiga_segundos)` | idade da instância mais antiga em cada etapa; nas esperas humanas ela cresce sem problema |
| `sum by (comando) (increase(pytstop_saga_reenvios_total[1h]))` | comandos que precisaram de reenvio: participante lento |
| `sum by (comando) (increase(pytstop_saga_prazos_esgotados_total[1h]))` | comandos que esgotaram os reenvios: participante mudo |
| `sum by (motivo) (increase(pytstop_saga_compensacoes_total[1h]))` | por que as sagas compensam; `prazo_tecnico` subindo é participante sem responder |
| `rabbitmq_queue_consumers{queue="os.eventos"}` | zero: o consumidor do OS Service está fora, e o `prazos` fica em pausa |
| `sum by (queue) (rabbitmq_queue_messages{queue=~".+[.]dlq"})` | mensagem em alguma DLQ ([seção 4](#4-mensagem-na-dlq-e-redrive)) |
| `outbox_pendentes`, `outbox_dead` | comando ou evento que não saiu da outbox ([seção 3](#3-prazo-técnico-vencido-sem-reenvio)) |

### O `ordem_id`

As métricas não levam o `ordem_id`, porque os labels são fechados. Para chegar à OS, use um destes caminhos:

1. No Explore do Grafana, com o datasource Loki, `{namespace="pytstop-os"} |= "falha_na_compensacao" | json` traz as linhas do OS Service que citam essa etapa; o campo `correlation_id` de cada linha é o `ordem_id`.
2. Na mensagem parada numa DLQ, a propriedade `correlation_id` ([seção 4](#4-mensagem-na-dlq-e-redrive)).
3. No banco do OS Service, a lista completa, com uma consulta só de leitura. O comando acha o pod e o container do PostgreSQL pela imagem, sem depender do nome que o manifesto lhes der. A consulta junta cada instância à linha da outbox do envio mais recente do comando em voo (o último de `mensagem_ids`) e lista as instâncias em `falha_na_compensacao` e as com o prazo vencido há mais de 60 s, contado do `entregue_em` mais 120 s, o `SAGA_PRAZO_RESPOSTA_SEGUNDOS` padrão; se a configuração mudou, troque os dois números:

   ```bash
   kos() { kubectl --context kind-pytstop-p4 -n pytstop-os "$@"; }
   read -r PG_POD PG_CONTAINER < <(kos get pods -o json | jq -r 'first(.items[] | .metadata.name as $pod
     | .spec.containers[] | select(.image | test("(^|/)postgres:")) | "\($pod) \(.name)")')
   kos exec -i "$PG_POD" -c "$PG_CONTAINER" -- sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' <<'SQL'
   SELECT s.ordem_id, s.etapa, s.falha, s.comando_em_voo->>'tipo' AS comando, s.reenvios,
          o.entregue_em, o.entregue_em + interval '120 seconds' AS venceu_em
     FROM sagas s
     LEFT JOIN outbox o ON o.mensagem_id = (s.comando_em_voo->'mensagem_ids'->> -1)::uuid
    WHERE s.etapa = 'falha_na_compensacao'
       OR (o.status = 'entregue' AND o.entregue_em + interval '120 seconds' < now() - interval '60 seconds')
    ORDER BY o.entregue_em NULLS FIRST;
   SQL
   ```

   O comando que o relay ainda não entregou não entra na lista, porque o prazo dele não começou: o sinal é `outbox_pendentes` ([seção 3](#3-prazo-técnico-vencido-sem-reenvio)). `entregue_em` e `venceu_em` vazios são de instância sem comando em voo, como a que está em `falha_na_compensacao`. O significado das colunas está na [RFC-004, seção 7.2](../arquitetura/rfc/fase4/rfc-004-microsservicos-saga.md#72-os-service-postgresql-16).

Guarde o `ordem_id` achado:

```bash
ORDEM_ID=3c9a7e10-5b2f-4f6d-8a41-0e2d9b7c6f55   # troque pelo ordem_id achado acima
```

### A instância

```bash
curl -s "$OS/api/v1/sagas/$ORDEM_ID" -H "Authorization: Bearer $TOKEN" | jq
curl -s "$OS/api/v1/ordens-de-servico/$ORDEM_ID" -H "Authorization: Bearer $TOKEN" | jq
```

A primeira resposta mostra a etapa, o motivo da compensação, a falha, o plano restante (a primeira compensação da lista é a pendente), o comando em voo com a hora do envio, os reenvios, o prazo e os passos ([RFC-004, seção 6.1](../arquitetura/rfc/fase4/rfc-004-microsservicos-saga.md#61-rotas-por-serviço)). A segunda traz a etapa junto do status e o resumo do orçamento e do pagamento, com o `pagamento_id`. `GET $OS/api/v1/ordens-de-servico/$ORDEM_ID/historico` junta os passos da saga às mudanças de status, com o ator de cada uma.

Resultado esperado: você tem o `ordem_id`, a etapa e, em `falha_na_compensacao`, a `falha`. Siga a seção que a tabela do início indica.

## 2. Falha na compensação e retomada

A sequência parou na compensação pendente. O que já foi compensado continua compensado, o resto está como estava, e a OS mantém o status. Resposta que chega atrasada não tira a saga da falha, salvo o `ExecucaoIniciada` (passo 2): quem retoma é o operador. O estado de cada recurso depois de um estorno recusado está na [RFC-004, seção 4.7](../arquitetura/rfc/fase4/rfc-004-microsservicos-saga.md#47-falha-na-compensação-e-retomada).

1. Trate a causa conforme a `falha` da instância.
   - `estorno_recusado`: o Billing respondeu `EstornoDePagamentoFalhou` ao `EstornarPagamento`, porque o Mercado Pago recusou o estorno.
     1. Confira o pagamento no Billing, com o `pagamento_id` do resumo da OS (seção 1):

        ```bash
        PAGAMENTO_ID=b7e2c4d1-0a9f-4e3b-8c6d-5f1a2b3c4d5e   # troque pelo pagamento_id do resumo da OS
        curl -s "$BILLING/api/v1/pagamentos/$PAGAMENTO_ID" -H "Authorization: Bearer $TOKEN" | jq
        ```

     2. Com `MP_MODE=mercadopago`, faça o estorno pelo painel do Mercado Pago. Na retomada, o Billing consulta o pagamento antes de estornar, reconhece o estorno feito no painel e responde `PagamentoEstornado` sem chamar o provedor de novo ([ADR-040](../arquitetura/adr/fase4/040-integracao-mercado-pago.md)).
     3. Se o painel também recusar o estorno, não retome: veja [Quando pedir ajuda](#quando-pedir-ajuda).
   - `reenvios_esgotados`: a compensação pendente ficou sem resposta depois do envio original e de 5 reenvios, 12 minutos com os padrões. Ache por que o participante não respondeu:
     1. o consumidor dele está fora: `rabbitmq_queue_consumers{queue="billing.comandos"}` (ou `execucao.comandos`) em zero, ou zero consumidores no `make status`;
     2. o comando está na `billing.comandos.dlq` ou na `execucao.comandos.dlq`, ou a resposta na `os.eventos.dlq` ([seção 4](#4-mensagem-na-dlq-e-redrive));
     3. o erro está no log do participante, pelo `correlation_id` ([seção 5](#5-o-trace-e-os-logs-pelo-correlation_id)).

     Corrija e, se houver mensagem numa DLQ, faça o redrive antes de retomar.
2. Se a compensação pendente é o `CancelarExecucao`, confira antes se o mecânico iniciou a execução. A OS sai da fila de execução quando é iniciada ou cancelada:

   ```bash
   curl -s "$EXECUCAO/api/v1/fila?limit=100" -H "Authorization: Bearer $TOKEN" \
     | jq --arg id "$ORDEM_ID" '.items[] | select(.ordem_id == $id)'
   ```

   A fila vem em páginas de até 100 OS; com mais, use `offset`.
   - A OS ainda está na fila: a execução não começou. Retome (passo 3).
   - A OS saiu da fila e os logs da Execução, pelo `correlation_id`, mostram o início: não retome. A Execução dá `ack` no `CancelarExecucao` que chega depois do início e o ignora, sem resposta (log `command_ignored`). O `ExecucaoIniciada` devolve a saga a `em_execucao` sozinho, mesmo em `falha_na_compensacao` (corrida do pivot, [RFC-004, seção 4.5](../arquitetura/rfc/fase4/rfc-004-microsservicos-saga.md#45-contramedidas-de-isolamento)); se ele estiver na `os.eventos.dlq`, faça o redrive dela.
   - A OS saiu da fila e os logs mostram o cancelamento: retome (passo 3). A Execução responde ao novo envio com o `ExecucaoCancelada` registrado.
3. Resolvida a causa, retome:

   ```bash
   curl -s -X POST "$OS/api/v1/sagas/$ORDEM_ID/compensacao" -H "Authorization: Bearer $TOKEN" | jq
   ```

   A resposta é 202 com a etapa `compensando`: a compensação pendente sai de novo, com `id` novo, prazo novo e contador de reenvios zerado, e o plano segue até `compensada`. Fora de `falha_na_compensacao`, a resposta é 409 `TRANSICAO_STATUS_INVALIDA` ([RFC-004, seção 6.1](../arquitetura/rfc/fase4/rfc-004-microsservicos-saga.md#61-rotas-por-serviço)). O participante que já tinha feito a compensação responde com o desfecho registrado, sem repetir o efeito.

Resultado esperado: `GET $OS/api/v1/sagas/$ORDEM_ID` chega a `compensada`, com a OS `cancelada`; `falha_na_compensacao` some de `max by (etapa) (pytstop_saga_ativas)`, e o alerta resolve na avaliação seguinte, em cerca de 1 minuto. Na corrida do pivot, a saga fica em `em_execucao`, e o histórico registra "cancelamento recusado: execução já iniciada". Se a saga voltar a `falha_na_compensacao` com a mesma falha, a causa continua: veja [Quando pedir ajuda](#quando-pedir-ajuda).

## 3. Prazo técnico vencido sem reenvio

Com tudo de pé, o `prazos` reenvia o comando a cada prazo vencido, e o atraso não passa do intervalo dele (`PRAZOS_INTERVALO_SEGUNDOS`, 30 s por padrão). Atraso acima de 60 s quer dizer que o prazo não está sendo tratado. Confira as causas nesta ordem:

| Causa | Como confirmar | O que fazer |
|---|---|---|
| `prazos` do OS Service fora | `kubectl --context kind-pytstop-p4 -n pytstop-os get pods -l processo=prazos` sem pod pronto | Subir o Deployment |
| Consumidor do OS Service fora | `rabbitmq_queue_consumers{queue="os.eventos"}` em zero, ou zero consumidores em `os.eventos` no `make status`; o log do `prazos` registra a pausa | Subir o consumidor |
| RabbitMQ fora | alerta `pytstop-rabbitmq-fora`; `make status` falha | Subir o broker; a outbox guardou as mensagens |

Sem consumidor em `os.eventos` ou com o broker fora, o `prazos` não reenvia nem esgota prazo, porque a resposta pode estar esperando na fila, e a saga segue de onde estava, sem gastar reenvio ([RFC-004, seção 4.6](../arquitetura/rfc/fase4/rfc-004-microsservicos-saga.md#46-prazos)).

Comando preso na outbox não dispara "Saga parada": o prazo só começa quando o relay entrega o comando. O sinal é `outbox_pendentes` acima de zero, que o ADR-043 alerta como "Outbox parada" (regra que entra em `alertas.yaml` com as métricas dos serviços). Suba o relay ou o broker; `outbox_dead` acima de zero não se resolve aqui (veja [Quando pedir ajuda](#quando-pedir-ajuda)).

Participante lento, com o resto de pé, não para a saga: aparece em `pytstop_saga_reenvios_total` e, esgotados os reenvios, a saga compensa com `motivo=prazo_tecnico` ou, se já estava compensando, vai a `falha_na_compensacao` ([seção 2](#2-falha-na-compensação-e-retomada)).

Resultado esperado: no ciclo seguinte do `prazos`, em até 30 s, o que venceu é reenviado ou a pausa termina; `max(pytstop_saga_prazo_vencido_segundos)` volta a ficar abaixo de 30, e o alerta resolve na avaliação seguinte, em cerca de 1 minuto.

## 4. Mensagem na DLQ e redrive

### Ver a mensagem

1. `make status` lista as filas com mensagens e consumidores.
2. No console do RabbitMQ (`http://localhost:15672`, usuário `admin`), em *Queues and Streams*, abra a `<fila>.dlq` e use *Get messages* com *Ack Mode* em *Nack message requeue true*: o console mostra a mensagem e a devolve à DLQ.
3. Anote as propriedades `type` (o tipo da mensagem), `correlation_id` (o `ordem_id`; no `AnonimizarVeiculo`, o `veiculo_id`), `message_id` e `user_id` e os headers `x-tentativa` e `x-death`. O motivo da rejeição está no log do consumidor que a recusou, pelo `correlation_id` ([seção 5](#5-o-trace-e-os-logs-pelo-correlation_id)).
4. O corpo pode trazer a placa (`SolicitarDiagnostico`): não o copie para fora do cluster.

### O que a mensagem parada significa para a saga

| DLQ | Mensagem | Efeito na saga |
|---|---|---|
| `billing.comandos.dlq`, `execucao.comandos.dlq` | comando com prazo técnico: `GerarOrcamento`, `ReservarPecas`, `SolicitarPagamento`, `AgendarExecucao` e as compensações | o `prazos` reenvia com `id` novo; se a causa persistir, os reenvios também caem na DLQ e, esgotados, a saga compensa ou vai a `falha_na_compensacao` |
| `execucao.comandos.dlq` | `SolicitarDiagnostico` | sem prazo técnico, porque o diagnóstico espera um mecânico: a saga fica em `aguardando_diagnostico`, com a OS `recebida`, até o redrive ou o cancelamento ([RFC-004, seção 4.3](../arquitetura/rfc/fase4/rfc-004-microsservicos-saga.md#43-passos-compensações-e-tipos)) |
| `execucao.comandos.dlq` | `AnonimizarVeiculo` | fora da saga e sem resposta: a placa só é anonimizada na Execução depois do redrive, que precisa sair antes de a DLQ descartar a mensagem, em 7 dias |
| `os.eventos.dlq` | resposta a comando com prazo técnico | o `prazos` reenvia o comando, e o participante republica o desfecho com `id` novo; se o defeito for do OS Service, a republicação também cai na DLQ |
| `os.eventos.dlq` | evento que nenhum comando pede de novo: ações do mecânico, decisão ou expiração do orçamento, confirmação, recusa ou expiração do pagamento | nada o reenvia: a saga espera o redrive |
| `os.eventos.dlq` | evento adiantado que esgotou as tentativas | o evento anterior da mesma OS não chegou; muitas vezes está na mesma DLQ |

### Comando recusado pelo participante

O domínio do participante recusa um comando de três jeitos, e só o último chega à DLQ ([ADR-036](../arquitetura/adr/fase4/036-mensageria-rabbitmq.md#entrega-retry-e-dlq)):

1. Descompasso de estado, como o `CancelarExecucao` de execução já iniciada: o participante dá `ack` e ignora o comando, sem resposta. Aparece no log dele como `command_ignored`, com o código do motivo, e em `pytstop_mensagens_consumidas_total{resultado="ignorada"}`; a saga resolve pelo evento que já recebeu ou pelo prazo técnico. A compensação repetida não entra aqui: o participante republica o desfecho registrado, e a saga o recebe como resposta.
2. Falha de negócio com evento no contrato (`GeracaoDeOrcamentoFalhou`, `ReservaDePecasFalhou`, `EstornoDePagamentoFalhou`): o evento chega ao OS Service, e a saga compensa ou, no estorno, vai a `falha_na_compensacao`. Aparece nos passos da instância e em `pytstop_saga_compensacoes_total`.
3. Falha permanente sem evento no contrato, como o provedor recusar a criação da cobrança: a mensagem vai para a DLQ e dispara "DLQ com mensagens", e o prazo técnico compensa a saga, com `motivo=prazo_tecnico`.

### Quando fazer o redrive

O redrive move a DLQ inteira, não uma mensagem. Faça-o depois de corrigida a causa de cada mensagem dela:

- consumidor com defeito: depois da correção implantada;
- dependência fora (banco, broker, provedor): depois que ela voltou;
- `versao` nova de mensagem: depois de implantar o consumidor que a conhece;
- evento adiantado com o anterior na mesma DLQ: o redrive devolve os dois. Se o adiantado for processado antes, volta à DLQ, porque chega com as tentativas esgotadas; um segundo redrive, depois que o anterior passar, resolve;
- mensagem com `user_id` que o consumidor não aceita: pode ser forjada ([ADR-036](../arquitetura/adr/fase4/036-mensageria-rabbitmq.md#usuários-e-permissões)). Anote `type`, `message_id`, `user_id` e `correlation_id` antes do redrive e antes de a DLQ a descartar, e veja [Quando pedir ajuda](#quando-pedir-ajuda).

A mensagem que o consumidor recusa de novo volta à DLQ, e o alerta continua: a inválida para o schema, a de `versao` desconhecida e a de `user_id` que ele não aceita (nem o do produtor do tipo nem, numa cópia de retry, o do próprio consumidor).

O redrive não repete efeito, mesmo que a saga já tenha seguido: o consumidor descarta o `id` já processado, o comando repetido pela chave de negócio só republica o desfecho, o evento obsoleto é ignorado, e o comando original que chega depois da compensação encontra a lápide ([RFC-004, seção 4.5](../arquitetura/rfc/fase4/rfc-004-microsservicos-saga.md#45-contramedidas-de-isolamento)).

### Como

No kind, na raiz deste repositório:

```bash
make redrive FILA=billing.comandos   # ou execucao.comandos, os.eventos
```

O alvo cria um shovel no broker que move para a fila as mensagens que estavam na DLQ quando ele começou, imprime as contagens antes e depois e se apaga ao terminar ([`scripts/redrive.sh`](../../scripts/redrive.sh)). O shovel preserva as propriedades, inclusive `x-tentativa`: a mensagem que esgotou as tentativas volta com a contagem cheia e, se falhar de novo, retorna direto à DLQ. A DLQ guarda cada mensagem por 7 dias e depois a descarta, porque ela carrega dado pessoal.

No compose, o mesmo shovel, também na raiz deste repositório:

```bash
FILA=billing.comandos   # ou execucao.comandos, os.eventos
docker compose -f compose/docker-compose.yml exec rabbitmq rabbitmqctl -q set_parameter shovel "redrive-$FILA" \
  "{\"src-uri\": \"amqp://\", \"src-queue\": \"$FILA.dlq\", \"dest-uri\": \"amqp://\", \"dest-queue\": \"$FILA\", \"src-delete-after\": \"queue-length\"}"
```

Resultado esperado: a linha `after:` do `make redrive` mostra a `<fila>.dlq` em 0, e o alerta "DLQ com mensagens" resolve na avaliação seguinte, em cerca de 1 minuto. No compose, `make status` não existe; confira com `docker compose -f compose/docker-compose.yml exec rabbitmq rabbitmqctl -q list_queues name messages`, que atualiza a contagem das filas quorum a cada 5 s. Se a DLQ voltar a encher, veja [Quando pedir ajuda](#quando-pedir-ajuda).

## 5. O trace e os logs pelo `correlation_id`

1. No Explore do Grafana, com o datasource Loki, `{namespace=~"pytstop-.+"} | json | correlation_id="<ordem_id>"` traz os logs da OS nos três serviços. O campo `trace_id` de cada linha vira link para o trace no Jaeger (datasource em [`observabilidade/grafana/datasources.yaml`](../../observabilidade/grafana/datasources.yaml)); no Jaeger (`http://localhost:16686`), o mesmo id abre o trace pela busca por trace id.
2. No trace, que tem raiz na abertura da OS ([RFC-004, seção 9](../arquitetura/rfc/fase4/rfc-004-microsservicos-saga.md#9-observabilidade)), confira:
   - o último comando que o relay do OS Service publicou (`publish <tipo>`) e se o participante tem o `process <tipo>` dele: sem esse span, a mensagem não foi consumida (consumidor fora ou fila parada); com o span em erro, ela foi para o retry ou para a DLQ;
   - spans `process` repetidos da mesma mensagem: cada passagem pelo retry acrescenta um ao trace;
   - os reenvios do `prazos`, o cancelamento e a retomada, que entram no mesmo trace, como filhos do contexto guardado na saga, com link para o trace de quem os disparou;
   - na compensação, a ordem dos comandos: `CancelarExecucao` antes de `EstornarPagamento`, e cada resposta antes do comando seguinte.
3. O Jaeger guarda os traces em memória (cerca de 5000), e uma saga pode durar dias: depois de um reinício do pod, o trace pode não existir mais. Os logs por `correlation_id` contam a mesma história ([ADR-043](../arquitetura/adr/fase4/043-observabilidade-distribuida.md)).

Resultado esperado: você sabe em que serviço a OS parou e por quê, pelo último `publish` sem o `process` correspondente, pelo span em erro ou pelo log de rejeição, e volta à seção da causa.

## Quando pedir ajuda

Chame quem mantém o serviço afetado (repositórios na [tabela do README](../../README.md#repositórios-da-fase-4)) com o `ordem_id`, a etapa, a `falha`, o `type` e o `message_id` das mensagens na DLQ e o `trace_id`, quando:

- a retomada volta a `falha_na_compensacao` com a mesma falha, depois de corrigida a causa;
- o painel do Mercado Pago também recusa o estorno: não retome, porque o pagamento continua `CONFIRMADO` e a retomada voltaria à mesma falha (Billing Service);
- a DLQ volta a encher depois do redrive;
- `outbox_dead` está acima de zero: a linha desistiu no relay depois de cinco falhas da própria mensagem ([ADR-036](../arquitetura/adr/fase4/036-mensageria-rabbitmq.md)), e o reprocessamento é pela rota administrativa do serviço, fora da borda ([ADR-039](../arquitetura/adr/fase4/039-autenticacao-entre-servicos.md));
- há mensagem com `user_id` que o consumidor não aceita, que pode ser forjada: trate como incidente de segurança.

---

> [↑ Raiz do projeto](../../README.md)
