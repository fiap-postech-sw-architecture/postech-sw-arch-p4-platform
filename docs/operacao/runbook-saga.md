# Runbook da saga de atendimento

> [↑ Raiz do projeto](../../README.md)

Procedimento para os alertas "Saga parada" e "DLQ com mensagens" (DLQ, fila de mensagens mortas) e para a ordem de serviço (OS) que não anda. A saga é orquestrada pelo OS Service ([ADR-035](../arquitetura/adr/fase4/035-saga-orquestrada.md)); as regras citadas aqui estão na [RFC-004](../arquitetura/rfc/fase4/rfc-004-microsservicos-saga.md), seções 4.4 a 4.7, 5.2 e 6.1; métricas e alertas, no [ADR-043](../arquitetura/adr/fase4/043-observabilidade-distribuida.md); retry, DLQ e redrive, no [ADR-036](../arquitetura/adr/fase4/036-mensageria-rabbitmq.md).

| Sinal | Seção |
|---|---|
| Alerta "Saga parada" com instância em `FALHA_NA_COMPENSACAO` | [1](#1-achar-a-saga-parada) e [2](#2-falha-na-compensação-e-retomada) |
| Alerta "Saga parada" por prazo técnico vencido | [1](#1-achar-a-saga-parada) e [3](#3-prazo-técnico-vencido-sem-reenvio) |
| Alerta "DLQ com mensagens" (`pytstop-dlq-com-mensagens`; "Mensagem em DLQ" no ADR-043) | [4](#4-mensagem-na-dlq-e-redrive) |
| OS que não anda, relatada pelo atendente | [1](#1-achar-a-saga-parada) e [5](#5-o-trace-e-os-logs-pelo-correlation_id) |

## Antes de começar

| Para | Como |
|---|---|
| Grafana, Prometheus, Jaeger e console do RabbitMQ | `make port-forward` na raiz deste repositório: Grafana em `http://localhost:3000`, Prometheus em `:9090`, Jaeger em `:16686` e RabbitMQ em `:15672`, com as credenciais da seção [Kubernetes local (kind)](../../README.md#kubernetes-local-kind) do README. No k3s, painéis e consoles só abrem por túnel SSH ([ADR-042](../arquitetura/adr/fase4/042-cicd-e-deploy-kubernetes.md)) |
| APIs dos serviços | pela borda: `http://localhost/os/...` no kind e o hostname público no k3s |
| Outro cluster | `KUBE_CONTEXT=<contexto>` em todo alvo do `make`, como em `make status KUBE_CONTEXT=<contexto>` |

As rotas da saga exigem o papel `admin` do OS Service. Com o e-mail e a senha dele (o Secret do serviço, [ADR-042](../arquitetura/adr/fase4/042-cicd-e-deploy-kubernetes.md)):

```bash
BASE=http://localhost/os   # no k3s, https://<hostname>/os
TOKEN=$(jq -n --arg email "$ADMIN_EMAIL" --arg senha "$ADMIN_SENHA" '{$email, $senha}' \
  | curl -s "$BASE/api/v1/autenticacao/login" -H 'Content-Type: application/json' -d @- \
  | jq -r .access_token)
```

## 1. Achar a saga parada

"Saga parada" ([ADR-043](../arquitetura/adr/fase4/043-observabilidade-distribuida.md#alertas)) dispara quando uma destas condições dura 5 minutos:

- `max(pytstop_saga_prazo_vencido_segundos)` acima de 60: alguma instância está com o prazo técnico vencido há mais de dois ciclos do `prazos`, sem reenvio ([seção 3](#3-prazo-técnico-vencido-sem-reenvio));
- `max(pytstop_saga_ativas{etapa="falha_na_compensacao"})` acima de 0: alguma compensação parou ([seção 2](#2-falha-na-compensação-e-retomada)).

As regras da saga entram em [`observabilidade/grafana/alertas.yaml`](../../observabilidade/grafana/alertas.yaml) com as métricas do OS Service; até lá, as mesmas consultas no Prometheus dão o sinal.

### Métricas

No Prometheus, ou no Explore do Grafana como `admin` (o acesso anônimo é só Viewer). Os gauges vêm do coletor da API do OS, e cada réplica repete o valor: agregue com `max`, nunca com `sum`.

| Consulta | Leitura |
|---|---|
| `max(pytstop_saga_prazo_vencido_segundos)` | maior atraso de prazo técnico, em segundos; até cerca de 30 s (o intervalo do `prazos`) é normal |
| `max by (etapa) (pytstop_saga_ativas)` | instâncias por etapa; `falha_na_compensacao` acima de zero pede a [seção 2](#2-falha-na-compensação-e-retomada) |
| `max by (etapa) (pytstop_saga_etapa_mais_antiga_segundos)` | idade da instância mais antiga em cada etapa; nas esperas humanas ela cresce sem problema (o orçamento vale até 72 h) |
| `sum by (comando) (increase(pytstop_saga_reenvios_total[1h]))` | participante lento: o comando precisou de reenvio |
| `sum by (comando) (increase(pytstop_saga_prazos_esgotados_total[1h]))` | participante mudo: o comando esgotou os reenvios |
| `sum by (motivo) (increase(pytstop_saga_compensacoes_total[1h]))` | por que as sagas compensam; `prazo_tecnico` subindo é participante sem responder |
| `rabbitmq_queue_consumers{queue="os.eventos"}` | zero: o consumidor do OS está fora, e o `prazos` fica em pausa |
| `sum by (queue) (rabbitmq_queue_messages{queue=~".+[.]dlq"})` | mensagem em alguma DLQ ([seção 4](#4-mensagem-na-dlq-e-redrive)) |
| `outbox_pendentes`, `outbox_dead` | comando ou evento que não saiu da outbox |

### O `ordem_id`

As métricas não levam `ordem_id` (os labels são fechados). Para chegar à OS:

- no Loki, pelo Explore do Grafana, `{namespace="pytstop-os"} |= "falha_na_compensacao" | json` traz as linhas do OS que citam essa etapa, e o campo `correlation_id` de cada linha é o `ordem_id`;
- na mensagem parada numa DLQ, a propriedade `correlation_id` ([seção 4](#4-mensagem-na-dlq-e-redrive));
- a lista completa sai do banco do OS, com uma consulta só de leitura pelo `psql` do PostgreSQL do namespace `pytstop-os`:

```sql
SELECT ordem_id, etapa, falha, comando_em_voo->>'tipo' AS comando, reenvios, prazo_resposta_em
  FROM sagas
 WHERE etapa = 'falha_na_compensacao' OR prazo_resposta_em < now() - interval '60 seconds'
 ORDER BY prazo_resposta_em NULLS FIRST;
```

### A instância

```bash
curl -s "$BASE/api/v1/sagas/$ORDEM_ID" -H "Authorization: Bearer $TOKEN" | jq
```

Mostra a etapa, o motivo da compensação, a falha, o plano restante (a primeira compensação da lista é a pendente), o comando em voo e a hora do envio, os reenvios, o prazo e os passos ([RFC-004, seção 4.7](../arquitetura/rfc/fase4/rfc-004-microsservicos-saga.md#47-falha-na-compensação-e-retomada)). `GET /api/v1/ordens-de-servico/{id}` traz a etapa junto do status, e `GET /api/v1/ordens-de-servico/{id}/historico` junta os passos da saga às mudanças de status, com o ator de cada uma.

## 2. Falha na compensação e retomada

A sequência parou na compensação pendente: o que já foi compensado continua compensado, o resto está como estava, e a OS mantém o status. O estado de cada recurso depois de um estorno recusado, como exemplo, está na [RFC-004, seção 4.7](../arquitetura/rfc/fase4/rfc-004-microsservicos-saga.md#47-falha-na-compensação-e-retomada). Resposta que chega atrasada não tira a saga da falha: quem retoma é o operador.

| `falha` | O que aconteceu | O que fazer antes de retomar |
|---|---|---|
| `estorno_recusado` | O Billing respondeu `EstornoDePagamentoFalhou` ao `EstornarPagamento`: o Mercado Pago recusou o estorno | Conferir o pagamento no Billing (`GET /api/v1/pagamentos/{id}`) e, com `MP_MODE=mercadopago`, estornar pelo painel do Mercado Pago. Na retomada, o Billing consulta o pagamento antes de estornar, reconhece o estorno feito no painel e responde `PagamentoEstornado` sem chamar o provedor de novo ([ADR-040](../arquitetura/adr/fase4/040-integracao-mercado-pago.md)) |
| `reenvios_esgotados` | A compensação pendente ficou sem resposta depois do envio original e de 5 reenvios (12 minutos com os padrões) | Achar por que o participante não respondeu: consumidor dele fora (`rabbitmq_queue_consumers` da fila de comandos), o comando na `billing.comandos.dlq` ou na `execucao.comandos.dlq`, a resposta na `os.eventos.dlq` ([seção 4](#4-mensagem-na-dlq-e-redrive)) ou o erro no log do participante pelo `correlation_id` ([seção 5](#5-o-trace-e-os-logs-pelo-correlation_id)). Corrigir e, se houver mensagem numa DLQ, fazer o redrive |

Com `CancelarExecucao` como compensação pendente, confira antes se o mecânico já iniciou a execução: a OS sai da fila de execução (`GET /api/v1/fila` da Execução) quando é iniciada ou cancelada, e os logs da Execução pelo `correlation_id` dizem qual dos dois. Se foi iniciada, não retome: a Execução não cancela execução iniciada, e a retomada nunca concluiria. O `ExecucaoIniciada` devolve a saga a `EM_EXECUCAO` sozinho, mesmo em `FALHA_NA_COMPENSACAO` (corrida do pivot, [RFC-004, seção 4.5](../arquitetura/rfc/fase4/rfc-004-microsservicos-saga.md#45-contramedidas-de-isolamento)); se ele estiver na `os.eventos.dlq`, faça o redrive dela.

Resolvida a causa, retome:

```bash
curl -s -X POST "$BASE/api/v1/sagas/$ORDEM_ID/compensacao" -H "Authorization: Bearer $TOKEN" | jq
```

A resposta é 202 com a etapa `COMPENSANDO`: a compensação pendente sai de novo, com `id` novo, prazo novo e contador de reenvios zerado, e o plano segue até `COMPENSADA`. Fora de `FALHA_NA_COMPENSACAO`, a resposta é 409 `TRANSICAO_STATUS_INVALIDA` ([RFC-004, seção 6.1](../arquitetura/rfc/fase4/rfc-004-microsservicos-saga.md#61-rotas-por-serviço)). O participante que já tinha feito a compensação responde ao reenvio com o desfecho registrado, sem repetir o efeito.

Para conferir, `GET /api/v1/sagas/{ordem_id}` deve chegar a `COMPENSADA`, com a OS `CANCELADA`, e `falha_na_compensacao` sai de `max by (etapa) (pytstop_saga_ativas)`. Se a saga voltar à falha, a causa continua lá.

## 3. Prazo técnico vencido sem reenvio

Com tudo de pé, o `prazos` reenvia o comando a cada prazo vencido, e o atraso não passa do intervalo dele. Atraso acima de 60 s quer dizer que o prazo não está sendo tratado:

| Causa | Como confirmar | O que fazer |
|---|---|---|
| `prazos` do OS fora | `kubectl -n pytstop-os get pods -l processo=prazos` sem pod pronto | Subir o Deployment: o ciclo seguinte reenvia o que venceu |
| Consumidor do OS fora | `rabbitmq_queue_consumers{queue="os.eventos"}` em zero, ou `make status` com zero consumidores em `os.eventos`; o log do `prazos` registra a pausa | Subir o consumidor. Sem consumidor em `os.eventos`, o `prazos` não reenvia nem esgota prazo, e a saga segue de onde estava sem gastar reenvio ([RFC-004, seção 4.6](../arquitetura/rfc/fase4/rfc-004-microsservicos-saga.md#46-prazos)) |
| RabbitMQ fora | alerta `pytstop-rabbitmq-fora`; `make status` falha | Subir o broker: a outbox guardou as mensagens, e a pausa vale também aqui |
| Comando que não saiu da outbox | `outbox_pendentes` do OS acima de zero, com o relay ou o broker fora (alerta "Outbox parada" do ADR-043) | Subir o relay ou o broker. Enquanto o comando não sai, o `prazos` não o reenvia: o prazo de resposta conta a partir da entrega |

Participante lento, com o resto de pé, não para a saga: aparece em `pytstop_saga_reenvios_total` e, esgotados os reenvios, a saga compensa com `motivo=prazo_tecnico` ou, se já estava compensando, vai a `FALHA_NA_COMPENSACAO` ([seção 2](#2-falha-na-compensação-e-retomada)).

## 4. Mensagem na DLQ e redrive

### Ver a mensagem

`make status` lista as filas com mensagens e consumidores. No console do RabbitMQ (`http://localhost:15672`, usuário `admin`), em *Queues and Streams*, abra a `<fila>.dlq` e use *Get messages* com *Ack Mode* em *Nack message requeue true*, que mostra a mensagem e a devolve à DLQ. Interessam as propriedades `type` (o tipo da mensagem), `correlation_id` (o `ordem_id`; no `AnonimizarVeiculo`, o `veiculo_id`), `message_id` e `user_id` e os headers `x-tentativa` e `x-death`. O motivo da rejeição está no log do consumidor que a recusou, pelo `correlation_id` ([seção 5](#5-o-trace-e-os-logs-pelo-correlation_id)). O corpo pode trazer a placa (`SolicitarDiagnostico`): não o copie para fora do cluster.

### O que a mensagem parada significa para a saga

| DLQ | Mensagem | Efeito |
|---|---|---|
| `billing.comandos.dlq`, `execucao.comandos.dlq` | comando com prazo técnico: `GerarOrcamento`, `ReservarPecas`, `SolicitarPagamento`, `AgendarExecucao` e as compensações | O `prazos` reenvia com `id` novo. Se a causa persistir, os reenvios também caem na DLQ e, esgotados, a saga compensa ou, numa compensação, vai a `FALHA_NA_COMPENSACAO` |
| `execucao.comandos.dlq` | `SolicitarDiagnostico` | Sem prazo técnico, porque o T2 não tem resposta automática: a saga fica em `AGUARDANDO_DIAGNOSTICO`, com a OS `RECEBIDA`, até o redrive ou o cancelamento ([RFC-004, seção 4.3](../arquitetura/rfc/fase4/rfc-004-microsservicos-saga.md#43-passos-compensações-e-tipos)) |
| `execucao.comandos.dlq` | `AnonimizarVeiculo` | Fora da saga e sem resposta: a placa só é anonimizada na Execução depois do redrive, que precisa sair antes de a mensagem expirar da DLQ, em 7 dias |
| `os.eventos.dlq` | resposta a comando com prazo técnico | O `prazos` reenvia o comando, e o participante republica o desfecho com `id` novo; se o defeito for do OS, a republicação também cai na DLQ |
| `os.eventos.dlq` | evento que nenhum comando pede de novo: ações do mecânico no diagnóstico e na execução, decisão ou expiração do orçamento, confirmação, recusa ou expiração do pagamento | Nada o reenvia: a saga espera até o redrive |
| `os.eventos.dlq` | evento adiantado que esgotou as tentativas | O evento anterior da mesma OS não chegou; muitas vezes está na mesma DLQ |

### Quando fazer

Só depois de corrigir a causa: consumidor com defeito corrigido e implantado, dependência de volta (banco, broker, provedor), ou consumidor que conhece uma `versao` nova implantado antes do produtor. Com um evento adiantado e o anterior na mesma DLQ, o redrive devolve os dois; se o adiantado for processado antes, ele volta à DLQ, porque chega com as tentativas esgotadas, e um segundo redrive, depois que o anterior passar, resolve.

O redrive move a DLQ inteira, não uma mensagem. A que o consumidor recusa de novo volta à DLQ, e o alerta continua: mensagem inválida para o schema, comando que já não tem efeito, como `CancelarExecucao` de execução iniciada, e mensagem com `user_id` que o consumidor não aceita (nem o do produtor do tipo nem, numa cópia de retry, o do próprio consumidor). Esta última pode ser forjada ([ADR-036](../arquitetura/adr/fase4/036-mensageria-rabbitmq.md#usuários-e-permissões)): antes do redrive, e antes de a DLQ a descartar, anote `type`, `message_id`, `user_id` e `correlation_id` para a investigação.

O redrive não repete efeito, mesmo que a saga já tenha seguido: o consumidor descarta o `id` já processado, o comando repetido pela chave de negócio só republica o desfecho, o evento obsoleto é ignorado, e o comando original que chega depois da compensação encontra a lápide ([RFC-004, seção 4.5](../arquitetura/rfc/fase4/rfc-004-microsservicos-saga.md#45-contramedidas-de-isolamento)).

### Como

```bash
make redrive FILA=billing.comandos   # ou execucao.comandos, os.eventos; no k3s, KUBE_CONTEXT=<contexto>
```

O alvo cria um shovel no broker que move para a fila as mensagens que estavam na DLQ quando ele começou, imprime as contagens antes e depois e se apaga ao terminar ([`scripts/redrive.sh`](../../scripts/redrive.sh)). O shovel preserva as propriedades, inclusive `x-tentativa`: a mensagem que esgotou as tentativas volta com a contagem cheia e, se falhar de novo, retorna direto à DLQ. A DLQ guarda cada mensagem por 7 dias e depois a descarta, porque ela carrega dado pessoal. No compose, o mesmo comando do shovel roda por `docker compose exec` ([README, filas e redrive](../../README.md#filas-exchanges-e-argumentos)).

## 5. O trace e os logs pelo `correlation_id`

1. No Explore do Grafana, `{namespace=~"pytstop-.+"} | json | correlation_id="<ordem_id>"` no Loki traz os logs da OS nos três serviços. O campo `trace_id` de cada linha vira link para o trace no Jaeger (datasource em [`observabilidade/grafana/datasources.yaml`](../../observabilidade/grafana/datasources.yaml)); no Jaeger (`http://localhost:16686`), o mesmo id abre o trace pela busca por trace id.
2. No trace, que tem raiz na abertura da OS ([RFC-004, seção 9](../arquitetura/rfc/fase4/rfc-004-microsservicos-saga.md#9-observabilidade)), confira:
   - o último comando que o relay do OS publicou (`publish <tipo>`) e se o participante tem o `process <tipo>` dele: sem esse span, a mensagem não foi consumida (consumidor fora ou fila parada); com o span em erro, ela foi para o retry ou para a DLQ;
   - spans `process` repetidos da mesma mensagem: cada passagem pelo retry acrescenta um ao trace;
   - os reenvios do `prazos`, o cancelamento e a retomada, que entram no mesmo trace, como filhos do contexto guardado na saga, com link para o trace de quem os disparou;
   - na compensação, a ordem dos comandos: `CancelarExecucao` antes de `EstornarPagamento`, e cada resposta antes do comando seguinte.
3. O Jaeger guarda os traces em memória (cerca de 5000), e uma saga pode durar dias: depois de um reinício do pod, o trace pode não existir mais. Os logs por `correlation_id` contam a mesma história ([ADR-043](../arquitetura/adr/fase4/043-observabilidade-distribuida.md)).

---

> [↑ Raiz do projeto](../../README.md)
