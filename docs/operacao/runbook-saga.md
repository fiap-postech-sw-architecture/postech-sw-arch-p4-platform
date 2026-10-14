# Runbook da saga de atendimento

> [↑ Raiz do projeto](../../README.md)

Vale a partir da versão do OS Service com o orquestrador da saga, implantada no kind. Antes dela não existem as rotas `/api/v1/sagas`, a tabela `sagas`, o processo `prazos`, as métricas `pytstop_saga_*` e os logs da saga, e os passos que os usam não têm o que mostrar. A fila, a DLQ, o redrive e o alerta "DLQ com mensagens" já valem.

Procedimento para os alertas "Saga parada" e "DLQ com mensagens" e para a ordem de serviço que não anda. As regras citadas estão na [RFC-004](../arquitetura/rfc/fase4/rfc-004-microsservicos-saga.md), seções 4.3, 4.5 a 4.7, 6.1, 7.2 e 9; métricas e alertas, no [ADR-043](../arquitetura/adr/fase4/043-observabilidade-distribuida.md); retry, DLQ e redrive, no [ADR-036](../arquitetura/adr/fase4/036-mensageria-rabbitmq.md).

| Sinal | Seção |
|---|---|
| Alerta "Saga parada", com instância em `falha_na_compensacao` | [1](#1-achar-a-saga-parada) e [2](#2-falha-na-compensação-e-retomada) |
| Alerta "Saga parada", com prazo técnico vencido | [1](#1-achar-a-saga-parada) e [3](#3-prazo-técnico-vencido-sem-reenvio) |
| Alerta "Saga parada", com o coletor das sagas indisponível (`pytstop_saga_coletor_disponivel` em 0) | [1](#1-achar-a-saga-parada) |
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

4. Defina os endereços das APIs, que respondem pela borda do kind, e entre como `admin` do OS Service. O e-mail do admin semeado é o `ADMIN_EMAIL` do ConfigMap do serviço, e a senha está na chave `ADMIN_PASSWORD` do Secret `os-admin`, gerado pelo deploy, os dois no namespace `pytstop-os` ([Segredos gerados](../../README.md#segredos-gerados)). O ConfigMap se acha pela chave, sem depender do nome dele. A senha fica numa variável do shell, não exportada, que só o `jq` recebe, no ambiente dele, e sai do shell logo depois do login; ao `curl` ela chega pela entrada padrão, sem aparecer na lista de processos:

   ```bash
   OS=http://localhost/os BILLING=http://localhost/billing EXECUCAO=http://localhost/execucao
   ADMIN_EMAIL=$(kubectl --context kind-pytstop-p4 -n pytstop-os get configmaps -o json \
     | jq -r 'first(.items[].data.ADMIN_EMAIL // empty)')
   ADMIN_SENHA=$(kubectl --context kind-pytstop-p4 -n pytstop-os get secret os-admin \
     -o jsonpath='{.data.ADMIN_PASSWORD}' | base64 -d)
   TOKEN=$(ADMIN_EMAIL="$ADMIN_EMAIL" ADMIN_SENHA="$ADMIN_SENHA" jq -n '{email: env.ADMIN_EMAIL, senha: env.ADMIN_SENHA}' \
     | curl -s "$OS/api/v1/autenticacao/login" -H 'Content-Type: application/json' -d @- \
     | jq -r .access_token)
   unset ADMIN_SENHA
   ```

   Se `$TOKEN` sair `null`, rode o bloco de novo sem o `| jq -r .access_token` do fim e veja a resposta com `echo "$TOKEN"`: 401 é credencial errada, e 429, o limite de tentativas. O mesmo token serve às três APIs, porque o `admin` herda os papéis `atendente` e `mecanico` ([ADR-039](../arquitetura/adr/fase4/039-autenticacao-entre-servicos.md)). Ele vale 15 minutos; depois, rode o bloco de novo, e o login aceita 5 tentativas por minuto.

O k3s da Azure é opcional ([ADR-042](../arquitetura/adr/fase4/042-cicd-e-deploy-kubernetes.md)) e fica fora deste runbook: a API do Kubernetes dele não é exposta, e o acesso à VM é por SSH.

## 1. Achar a saga parada

"Saga parada" ([ADR-043](../arquitetura/adr/fase4/043-observabilidade-distribuida.md#alertas), regra `pytstop-saga-parada`) dispara quando uma destas condições dura 5 minutos, e cada uma vale sozinha:

- prazo técnico vencido e não tratado há mais de 60 s, duas vezes o `PRAZOS_INTERVALO_SEGUNDOS` padrão (30 s, o intervalo do `prazos`; o 60 é literal em `alertas.yaml` e não acompanha a variável, então quem muda o intervalo muda também o limiar e a `summary` da regra), ou seja, `max(pytstop_saga_prazo_vencido_segundos) > 60` ([seção 3](#3-prazo-técnico-vencido-sem-reenvio));
- alguma instância em `falha_na_compensacao`, ou seja, `max(pytstop_saga_ativas{etapa="falha_na_compensacao"}) > 0` ([seção 2](#2-falha-na-compensação-e-retomada));
- o coletor das sagas do OS Service indisponível, ou seja, `min(pytstop_saga_coletor_disponivel) == 0`, ou a série ausente com a API do OS Service de pé. Sem o coletor, as duas condições acima ficam sem dado e não disparariam: o alerta existe para que o coletor quebrado não deixe a saga parada sem aviso ([Coletor das sagas indisponível](#coletor-das-sagas-indisponível)).

### Métricas

No Prometheus (`http://localhost:9090`) ou no Explore do Grafana, entrando como `admin`. Os gauges da saga vêm do coletor da API do OS Service, e cada réplica repete o valor: agregue gauge com `max`, nunca com `sum`.

| Consulta | Leitura |
|---|---|
| `max(pytstop_saga_prazo_vencido_segundos)` | maior atraso de prazo técnico, em segundos; até cerca de 30 s é normal |
| `min(pytstop_saga_coletor_disponivel)` | 1: o coletor leu as sagas na última raspagem; 0: a leitura falhou em alguma réplica, e os gauges de etapa e de idade somem ([abaixo](#coletor-das-sagas-indisponível)) |
| `max by (etapa) (pytstop_saga_ativas)` | instâncias em cada etapa |
| `max by (etapa) (pytstop_saga_etapa_mais_antiga_segundos)` | idade da instância mais antiga em cada etapa; nas esperas humanas ela cresce sem problema |
| `sum by (comando) (increase(pytstop_saga_reenvios_total[1h]))` | comandos que precisaram de reenvio: participante lento |
| `sum by (comando) (increase(pytstop_saga_prazos_esgotados_total[1h]))` | comandos que esgotaram os reenvios: participante mudo |
| `sum by (motivo) (increase(pytstop_saga_compensacoes_total[1h]))` | por que as sagas compensam; `prazo_tecnico` subindo é participante sem responder |
| `rabbitmq_queue_consumers{queue="os.eventos"}` | zero: o consumidor do OS Service está fora, e o `prazos` fica em pausa |
| `sum by (queue) (rabbitmq_queue_messages{queue=~".+[.]dlq"})` | mensagem em alguma DLQ ([seção 4](#4-mensagem-na-dlq-e-redrive)) |
| `pytstop_outbox_mais_antiga_segundos`, `outbox_pendentes`, `outbox_dead` | comando ou evento que não saiu da outbox: a idade da pendente mais antiga e quantas esperam, e as que desistiram ([seção 3](#3-prazo-técnico-vencido-sem-reenvio)) |

### Coletor das sagas indisponível

O coletor lê a tabela `sagas` na hora de cada raspagem, numa conexão própria, com prazo de 2 s para a consulta e de 1 s para esperar um lock. Se a leitura falha, ele omite `pytstop_saga_ativas` e `pytstop_saga_etapa_mais_antiga_segundos`, que ficam ausentes e nunca em zero, soma uma falha em `pytstop_saga_coletor_falhas_total` e publica `pytstop_saga_coletor_disponivel` em 0. Para achar a causa:

1. `sum(increase(pytstop_saga_coletor_falhas_total[10m]))` acima de zero confirma que a falha se repete.
2. O log da API do OS Service, no Loki (`{namespace="pytstop-os"} |= "saga gauges unavailable"`), traz a linha `saga gauges unavailable` com o tipo do erro: banco fora, tabela travada por um lock, que a leitura espera por 1 s, ou consulta acima de 2 s.
3. Corrija a causa no banco. Enquanto o coletor estiver fora, as consultas de gauge desta seção não valem; a consulta ao banco do passo 3 de "O `ordem_id`" (abaixo) não depende dele.

Resultado esperado: `min(pytstop_saga_coletor_disponivel)` volta a 1 na raspagem seguinte, e o alerta resolve na avaliação seguinte.

### O `ordem_id`

As métricas não levam o `ordem_id`, porque os labels são fechados. Para chegar à OS, use um destes caminhos:

1. No Explore do Grafana, com o datasource Loki, `{namespace="pytstop-os"} |= "falha_na_compensacao" | json` traz as linhas do OS Service que citam essa etapa; o campo `correlation_id` de cada linha é o `ordem_id`.
2. Na mensagem parada numa DLQ, a propriedade `correlation_id` ([seção 4](#4-mensagem-na-dlq-e-redrive)).
3. No banco do OS Service, a lista completa, com uma consulta só de leitura. O comando acha o pod e o container do PostgreSQL pela imagem, sem depender do nome que o manifesto lhes der, e entra como `os_app` (só DML), com a senha que o container do banco já recebe do Secret em `POSTGRES_APP_PASSWORD`: o PostgreSQL do OS pede senha até no socket local (`scram-sha-256`, [Contrato com os serviços](../../README.md#o-que-cada-serviço-precisa-ter)), e ela chega ao `psql` por `PGPASSWORD`, sem passar pelo terminal nem por argumento. A consulta junta cada instância à linha da outbox do envio mais recente do comando em voo (o último de `mensagem_ids`) e lista as instâncias em `falha_na_compensacao` e as com o prazo vencido há mais de 60 s, contado do `entregue_em` mais 120 s, o `SAGA_PRAZO_RESPOSTA_SEGUNDOS` padrão; se a configuração mudou, troque os dois números:

   ```bash
   kos() { kubectl --context kind-pytstop-p4 -n pytstop-os "$@"; }
   read -r PG_POD PG_CONTAINER < <(kos get pods -o json | jq -r 'first(.items[] | .metadata.name as $pod
     | .spec.containers[] | select(.image | test("(^|/)postgres:")) | "\($pod) \(.name)")')
   kos exec -i "$PG_POD" -c "$PG_CONTAINER" -- sh -c 'PGPASSWORD="$POSTGRES_APP_PASSWORD" exec psql -w -U os_app -d "$POSTGRES_DB"' <<'SQL'
   SELECT s.ordem_id, s.etapa, s.falha, s.comando_em_voo->>'tipo' AS comando, s.reenvios,
          o.entregue_em, o.entregue_em + interval '120 seconds' AS venceu_em
     FROM sagas s
     LEFT JOIN outbox o ON o.mensagem_id = (s.comando_em_voo->'mensagem_ids'->> -1)::uuid
    WHERE s.etapa = 'falha_na_compensacao'
       OR (o.status = 'entregue' AND o.entregue_em + interval '120 seconds' < now() - interval '60 seconds')
    ORDER BY o.entregue_em NULLS FIRST;
   SQL
   ```

   O comando que o relay ainda não entregou não entra na lista, porque o prazo dele não começou: o sinal é a idade da pendente mais antiga, `pytstop_outbox_mais_antiga_segundos`, e `outbox_pendentes` mostra quantas linhas esperam ([seção 3](#3-prazo-técnico-vencido-sem-reenvio)). `entregue_em` e `venceu_em` vazios são de instância sem comando em voo, como a que está em `falha_na_compensacao`. O significado das colunas está na [RFC-004, seção 7.2](../arquitetura/rfc/fase4/rfc-004-microsservicos-saga.md#72-os-service-postgresql-16).

Guarde o `ordem_id` achado, no lugar do UUID de exemplo:

```bash
ORDEM_ID=3c9a7e10-5b2f-4f6d-8a41-0e2d9b7c6f55
```

### A instância

```bash
curl -s "$OS/api/v1/sagas/$ORDEM_ID" -H "Authorization: Bearer $TOKEN" | jq
curl -s "$OS/api/v1/ordens-de-servico/$ORDEM_ID" -H "Authorization: Bearer $TOKEN" | jq
```

A primeira resposta mostra a etapa, o motivo da compensação, a falha, o plano restante (a primeira compensação da lista é a pendente), o comando em voo com a hora do envio, os reenvios, o prazo e os passos ([RFC-004, seção 6.1](../arquitetura/rfc/fase4/rfc-004-microsservicos-saga.md#61-rotas-por-serviço)). A segunda traz a etapa junto do status e o resumo do orçamento e do pagamento, com o `pagamento_id`. `GET $OS/api/v1/ordens-de-servico/$ORDEM_ID/historico` devolve duas listas: `mudancas`, as transições de status, e `passos`, os registros da saga, com o ator de cada uma.

Resultado esperado: você tem o `ordem_id`, a etapa e, em `falha_na_compensacao`, a `falha`. Siga a seção que a tabela do início indica.

## 2. Falha na compensação e retomada

A sequência parou na compensação pendente. O que já foi compensado continua compensado, o resto está como estava, e a OS mantém o status. Resposta que chega atrasada não tira a saga da falha, salvo o `ExecucaoIniciada` (passo 2): quem retoma é o operador. O estado de cada recurso depois de um estorno recusado está na [RFC-004, seção 4.7](../arquitetura/rfc/fase4/rfc-004-microsservicos-saga.md#47-falha-na-compensação-e-retomada).

1. Trate a causa conforme a `falha` da instância.
   - `estorno_recusado`: o Billing respondeu `EstornoDePagamentoFalhou` ao `EstornarPagamento`, porque o Mercado Pago recusou o estorno.
     1. Confira o pagamento no Billing, com o `pagamento_id` do resumo da OS (seção 1) no lugar do UUID de exemplo:

        ```bash
        PAGAMENTO_ID=b7e2c4d1-0a9f-4e3b-8c6d-5f1a2b3c4d5e
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

Resultado esperado: `GET $OS/api/v1/sagas/$ORDEM_ID` chega a `compensada`, com a OS `cancelada`; `falha_na_compensacao` some de `max by (etapa) (pytstop_saga_ativas)`, e o alerta resolve na avaliação seguinte, em cerca de 1 minuto. Na corrida do pivot, a saga fica em `em_execucao`, e o registro dela para a volta leva o gatilho `cancelamento_recusado`, que se vê em `passos` no histórico da OS. Se a saga voltar a `falha_na_compensacao` com a mesma falha, a causa continua: veja [Quando pedir ajuda](#quando-pedir-ajuda).

## 3. Prazo técnico vencido sem reenvio

Com tudo de pé, o `prazos` reenvia o comando a cada prazo vencido, e o atraso não passa do intervalo dele (`PRAZOS_INTERVALO_SEGUNDOS`, 30 s por padrão). Atraso acima de 60 s quer dizer que o prazo não está sendo tratado. Confira as causas nesta ordem:

| Causa | Como confirmar | O que fazer |
|---|---|---|
| `prazos` do OS Service fora | `kubectl --context kind-pytstop-p4 -n pytstop-os get pods -l processo=prazos` sem pod pronto | Subir o Deployment |
| Consumidor do OS Service fora | `rabbitmq_queue_consumers{queue="os.eventos"}` em zero, ou zero consumidores em `os.eventos` no `make status`; o log do `prazos` registra a pausa | Subir o consumidor |
| RabbitMQ fora | alerta `pytstop-rabbitmq-fora`; `make status` falha | Subir o broker; a outbox guardou as mensagens |

Sem consumidor em `os.eventos` ou com o broker fora, o `prazos` não reenvia nem esgota prazo, porque a resposta pode estar esperando na fila, e a saga segue de onde estava, sem gastar reenvio ([RFC-004, seção 4.6](../arquitetura/rfc/fase4/rfc-004-microsservicos-saga.md#46-prazos)).

Comando preso na outbox não dispara "Saga parada": o prazo só começa quando o relay entrega o comando. O sinal é a idade da linha pendente mais antiga, `pytstop_outbox_mais_antiga_segundos`, que o ADR-043 alerta como "Outbox parada" quando passa de 300 s por 5 minutos (regra que entra em `alertas.yaml` com as métricas dos serviços); `outbox_pendentes` acima de zero só diz que há linhas esperando o relay, o que é normal com tráfego. Suba o relay ou o broker; `outbox_dead` acima de zero não se resolve aqui (veja [Quando pedir ajuda](#quando-pedir-ajuda)).

Participante lento, com o resto de pé, não para a saga: aparece em `pytstop_saga_reenvios_total` e, esgotados os reenvios, a saga compensa com `motivo=prazo_tecnico` ou, se já estava compensando, vai a `falha_na_compensacao` ([seção 2](#2-falha-na-compensação-e-retomada)).

Resultado esperado: no ciclo seguinte do `prazos`, em até 30 s, o que venceu é reenviado ou a pausa termina; `max(pytstop_saga_prazo_vencido_segundos)` volta a ficar abaixo de 30, e o alerta resolve na avaliação seguinte, em cerca de 1 minuto.

## 4. Mensagem na DLQ e redrive

### Ver a mensagem

1. `make status` lista as filas com mensagens e consumidores.
2. No console do RabbitMQ (`http://localhost:15672`, usuário `admin`), em *Queues and Streams*, abra a `<fila>.dlq` e use *Get messages* com *Ack Mode* em *Nack message requeue true*: o console mostra a mensagem e a devolve à DLQ.
3. Anote as propriedades `type` (o tipo da mensagem), `correlation_id` (o `ordem_id`; no `AnonimizarVeiculo`, o `veiculo_id`), `message_id` e `user_id` e os headers `x-tentativa` e `x-death`. O motivo da rejeição está no log do consumidor que a recusou, pelo `correlation_id` ([seção 5](#5-o-trace-e-os-logs-pelo-correlation_id)).
4. O corpo pode trazer a placa e a descrição do problema (`SolicitarDiagnostico`) ou texto livre com nome e endereço (`observacoes` do `DiagnosticoConcluido`, na `os.eventos.dlq`): não o copie para fora do cluster. A DLQ guarda a mensagem por 7 dias, e só a expiração a apaga.

### O que a mensagem parada significa para a saga

| DLQ | Mensagem | Efeito na saga |
|---|---|---|
| `billing.comandos.dlq`, `execucao.comandos.dlq` | comando com prazo técnico: `GerarOrcamento`, `ReservarPecas`, `SolicitarPagamento`, `AgendarExecucao` e as compensações | o `prazos` reenvia com `id` novo; se a causa persistir, os reenvios também caem na DLQ e, esgotados, a saga compensa ou vai a `falha_na_compensacao` |
| `execucao.comandos.dlq` | `SolicitarDiagnostico` | sem prazo técnico, porque o diagnóstico espera um mecânico: a saga fica em `aguardando_diagnostico`, com a OS `recebida`, até o redrive ou o cancelamento ([RFC-004, seção 4.3](../arquitetura/rfc/fase4/rfc-004-microsservicos-saga.md#43-passos-compensações-e-tipos)) |
| `execucao.comandos.dlq` | `AnonimizarVeiculo` | fora da saga e sem resposta: a placa e os textos livres só são anonimizados na Execução se o comando for reenviado, e só ele, nunca pelo redrive da fila; deixá-lo expirar perde a eliminação, e o `DELETE` repetido do OS Service não o reemite ([AnonimizarVeiculo parado](#anonimizarveiculo-parado-na-execucaocomandosdlq)) |
| `os.eventos.dlq` | resposta a comando com prazo técnico | o `prazos` reenvia o comando, e o participante republica o desfecho com `id` novo; se o defeito for do OS Service, a republicação também cai na DLQ |
| `os.eventos.dlq` | evento que nenhum comando pede de novo: ações do mecânico, decisão ou expiração do orçamento, confirmação, recusa ou expiração do pagamento | nada o reenvia: a saga espera o redrive |
| `os.eventos.dlq` | evento adiantado que esgotou as tentativas | o evento anterior da mesma OS não chegou; muitas vezes está na mesma DLQ |

### Motivos de recusa no consumidor do OS Service

O motivo de cada recusa sai em código no log `message rejected to dlq` do consumidor e no status de erro do span do consumo. Três pedem uma decisão antes do redrive, porque ele devolve a fila inteira e a mensagem que o consumidor recusar de novo volta à DLQ:

| Motivo | O que é | O que fazer |
|---|---|---|
| `sem_tratador_nesta_versao` | falha de negócio (por exemplo `OrcamentoRecusado` ou `ReservaDePecasFalhou`) ou resposta de compensação (por exemplo `ExecucaoCancelada`) que uma réplica de versão anterior à das compensações recebeu: consumi-la sem tratador perderia o evento, e por isso ela foi para a DLQ | implante a versão com as compensações em todas as réplicas e só então faça o redrive de `os.eventos`; antes disso a versão antiga a recusa de novo e os 7 dias da DLQ recomeçam |
| `ordem_encerrada` | evento do fluxo para uma OS `cancelada` ou `entregue` com a saga ainda viva, estado que o cancelamento pela API não produz (alguém alterou a OS por fora do serviço) | o redrive não resolve, a mensagem volta à DLQ: corrija o estado da OS ou chame quem mantém o OS Service ([Quando pedir ajuda](#quando-pedir-ajuda)) |
| `transicao_invalida` | a OS ou a saga recusam o fato, por exemplo `PagamentoSolicitado` com a OS fora de `aguardando_pagamento` | estado e evento não combinam: chame quem mantém o OS Service com o `ordem_id` e o `message_id`; o redrive só adianta se o estado mudar |

### Comando recusado pelo participante

O domínio do participante recusa um comando de três jeitos, e só o último chega à DLQ ([ADR-036](../arquitetura/adr/fase4/036-mensageria-rabbitmq.md#entrega-retry-e-dlq)):

1. Descompasso de estado, como o `CancelarExecucao` de execução já iniciada: o participante dá `ack` e ignora o comando, sem resposta. Aparece no log dele como `command_ignored`, com o código do motivo, e em `pytstop_mensagens_consumidas_total{resultado="ignorada"}`; a saga resolve pelo evento que já recebeu ou pelo prazo técnico. A compensação repetida não entra aqui: o participante republica o desfecho registrado, e a saga o recebe como resposta.
2. Falha de negócio com evento no contrato (`GeracaoDeOrcamentoFalhou`, `ReservaDePecasFalhou`, `EstornoDePagamentoFalhou`): o evento chega ao OS Service, e a saga compensa ou, no estorno, vai a `falha_na_compensacao`. Aparece nos passos da instância e em `pytstop_saga_compensacoes_total`.
3. Falha permanente sem evento no contrato, como o provedor recusar a criação da cobrança: a mensagem vai para a DLQ e dispara "DLQ com mensagens", e o prazo técnico compensa a saga, com `motivo=prazo_tecnico`. Provedor fora do ar não é recusa: o comando volta pelas filas de retry ([ADR-040](../arquitetura/adr/fase4/040-integracao-mercado-pago.md)).

### `AnonimizarVeiculo` parado na `execucao.comandos.dlq`

O comando leva só o `veiculo_id` (o `correlation_id` da mensagem): não tem dado pessoal. O dado pessoal está nas outras mensagens da mesma DLQ, como o `SolicitarDiagnostico` com a placa e a descrição do problema. Por isso os dois caminhos óbvios estão errados: o redrive da fila inteira recriaria a placa na Execução, e deixar o comando expirar perderia a eliminação, porque o `DELETE` do OS Service repetido não reemite o comando e nenhum alerta acusa depois que a mensagem some. O procedimento reenvia só esse comando:

1. Anote o `correlation_id` da mensagem, que é o `veiculo_id`, e ache a causa da recusa no log `message rejected to dlq` do consumidor da Execução, por esse id ([seção 5](#5-o-trace-e-os-logs-pelo-correlation_id)). Corrija-a antes: sem isso o reenvio volta para a DLQ.
2. Não rode `make redrive FILA=execucao.comandos`.
3. Reenvie só o comando, com o script do OS Service (`scripts/reenviar_anonimizacao.py`, na `main` do [OS Service](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-os-service)). Ele grava o comando de novo na outbox do OS, e o relay o publica como o usuário `os`, o único produtor que a Execução aceita para esse tipo: o console do RabbitMQ não serve, porque publicar como `admin` com `user_id` `os` volta 406. Troque o `VEICULO_ID` pelo da mensagem; a senha do banco já está no ambiente do pod:

   ```bash
   VEICULO_ID=3277db7e-8283-4dd9-89e7-df3eeacb8710
   perl -e 'alarm shift; exec @ARGV' 60 kubectl --context kind-pytstop-p4 -n pytstop-os exec deploy/os-service-consumidor -- python scripts/reenviar_anonimizacao.py "$VEICULO_ID"
   ```

   O script sai com 0 e imprime `AnonimizarVeiculo do veiculo <id> gravado na outbox`, ou sai com 1, sem enviar nada, se o veículo não existe ou o OS Service ainda não o anonimizou (o comando de um veículo vivo apagaria a placa dele na Execução).
4. Confira a placa na Execução: a do retrato do veículo tem de ser `ANONIMIZADO:` e o `veiculo_id`, e a descrição do problema e as observações do diagnóstico, `[removido na eliminacao de dados pessoais]`. A consulta é de leitura e entra como `execucao_app`; o `veiculo_id` chega como `$0` do `sh` do container:

   ```bash
   kex() { kubectl --context kind-pytstop-p4 -n pytstop-execucao "$@"; }
   kex exec -i statefulset/execucao-postgres -c postgres -- sh -c 'PGPASSWORD="$POSTGRES_APP_PASSWORD" PGOPTIONS="-c lock_timeout=2s -c statement_timeout=10s" exec psql -w -U execucao_app -d "$POSTGRES_DB" -v veiculo_id="$0"' "$VEICULO_ID" <<'SQL'
   SELECT 'diagnostico' AS registro, ordem_id, veiculo->>'placa' AS placa, descricao_problema, observacoes
     FROM diagnosticos WHERE veiculo->>'veiculo_id' = :'veiculo_id'
   UNION ALL
   SELECT 'execucao', ordem_id, veiculo->>'placa', NULL, NULL
     FROM execucoes WHERE veiculo->>'veiculo_id' = :'veiculo_id';
   SQL
   ```

   Uma linha com a placa original (`ABC1D23`, por exemplo) quer dizer que a Execução ainda não consumiu o comando: veja o log do consumidor dela e a DLQ de novo.
5. A cópia original do comando continua na DLQ, e o alerta "DLQ com mensagens" fica até ela expirar, em 7 dias. Silencie esse alerta no Grafana (Alerting, Silences) por 7 dias, só para `queue=execucao.comandos.dlq`, e confira a fila no `make status` antes de encerrar o incidente. A placa do `SolicitarDiagnostico` que estiver nessa DLQ também some pela expiração, e só por ela.
6. Se o comando já expirou sem reenvio, o titular continua com a placa e os textos livres na Execução, e o mesmo script o reenvia: o veículo já está anonimizado no OS Service.

### Quando fazer o redrive

O redrive move a DLQ inteira, não uma mensagem. Faça-o depois de corrigida a causa de cada mensagem dela:

- consumidor com defeito: depois da correção implantada;
- dependência fora (banco, broker, provedor): depois que ela voltou;
- `versao` nova de mensagem: depois de implantar o consumidor que a conhece;
- `sem_tratador_nesta_versao` na `os.eventos.dlq`: depois de implantar a versão do OS Service com as compensações, em todas as réplicas. O comando `make redrive FILA=os.eventos` não filtra por motivo: as mensagens dos outros motivos voltam juntas e, se falharem de novo, caem outra vez na DLQ. Se a implantação conviveu com réplicas antigas, repita o redrive no fim dela. A `os.eventos.dlq` expira em 7 dias, e sem o redrive o evento se perde;
- evento adiantado com o anterior na mesma DLQ: o redrive devolve os dois. Se o adiantado for processado antes, volta à DLQ, porque chega com as tentativas esgotadas; um segundo redrive, depois que o anterior passar, resolve;
- `execucao.comandos.dlq` depois de uma eliminação de dados do cliente: não faça o redrive da fila, que devolveria o `SolicitarDiagnostico` com a placa e a descrição do problema originais e os recriaria na Execução depois da anonimização. Se o `AnonimizarVeiculo` está nessa DLQ, também não o deixe expirar: reenvie só ele, como em [AnonimizarVeiculo parado](#anonimizarveiculo-parado-na-execucaocomandosdlq);
- mensagem com `user_id` que o consumidor não aceita: pode ser forjada ([ADR-036](../arquitetura/adr/fase4/036-mensageria-rabbitmq.md#usuários-e-permissões)). Anote `type`, `message_id`, `user_id` e `correlation_id` antes do redrive e antes de a DLQ a descartar, e veja [Quando pedir ajuda](#quando-pedir-ajuda).

A mensagem que o consumidor recusa de novo volta à DLQ, e o alerta continua: a inválida para o schema, a de `versao` desconhecida e a de `user_id` que ele não aceita (nem o do produtor do tipo nem, numa cópia de retry, o do próprio consumidor).

O redrive não repete efeito, mesmo que a saga já tenha seguido: o consumidor descarta o `id` já processado, o comando repetido pela chave de negócio só republica o desfecho, o evento obsoleto é ignorado, e o comando original que chega depois da compensação encontra a lápide ([RFC-004, seção 4.5](../arquitetura/rfc/fase4/rfc-004-microsservicos-saga.md#45-contramedidas-de-isolamento)).

### Como

No kind, na raiz deste repositório, com a fila da DLQ em vez de `billing.comandos`, que pode ser `execucao.comandos` ou `os.eventos`:

```bash
make redrive FILA=billing.comandos
```

O alvo cria um shovel no broker que move para a fila as mensagens que estavam na DLQ quando ele começou, imprime as contagens antes e depois e se apaga ao terminar ([`scripts/redrive.sh`](../../scripts/redrive.sh)). O shovel preserva as propriedades, inclusive `x-tentativa`: a mensagem que esgotou as tentativas volta com a contagem cheia e, se falhar de novo, retorna direto à DLQ. A DLQ guarda cada mensagem por 7 dias e depois a descarta, porque ela carrega dado pessoal.

No compose, o mesmo shovel, também na raiz deste repositório e com a mesma troca de fila:

```bash
FILA=billing.comandos
docker compose -f compose/docker-compose.yml exec rabbitmq rabbitmqctl -q set_parameter shovel "redrive-$FILA" \
  "{\"src-uri\": \"amqp://\", \"src-queue\": \"$FILA.dlq\", \"dest-uri\": \"amqp://\", \"dest-queue\": \"$FILA\", \"src-delete-after\": \"queue-length\"}"
```

Resultado esperado: a linha `after:` do `make redrive` mostra a `<fila>.dlq` em 0, e o alerta "DLQ com mensagens" resolve na avaliação seguinte, em cerca de 1 minuto. No compose, `make status` não serve, porque lê o cluster kind; confira com `docker compose -f compose/docker-compose.yml exec rabbitmq rabbitmqctl -q list_queues name messages`, que atualiza a contagem das filas quorum a cada 5 s. Se a DLQ voltar a encher, veja [Quando pedir ajuda](#quando-pedir-ajuda).

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
- `outbox_dead` está acima de zero: a linha desistiu no relay depois de cinco falhas da própria mensagem ([ADR-036](../arquitetura/adr/fase4/036-mensageria-rabbitmq.md)), e não há rota administrativa para reprocessá-la nesta fase ([ADR-039](../arquitetura/adr/fase4/039-autenticacao-entre-servicos.md)): o reprocessamento é uma atualização no banco do serviço, feita por quem o mantém;
- há mensagem com `user_id` que o consumidor não aceita, que pode ser forjada: trate como incidente de segurança.

---

> [↑ Raiz do projeto](../../README.md)
