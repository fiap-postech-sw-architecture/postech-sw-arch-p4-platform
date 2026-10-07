# RabbitMQ com outbox transacional e consumidor idempotente

> [↑ Raiz do projeto](../../../../README.md) · [↑ Arquitetura](../../README.md)

* Status: Aceita
* Data: 2026-10-06

## Contexto e Problema

O enunciado pede "Mensageria assíncrona (RabbitMQ, Kafka, SQS, etc.) para eventos e integração desacoplada" (l. 66) e "Mensageria para orquestração ou coreografia" (l. 101); ver [desafio-tech-fase-4.md](../../../requisitos/fase4/desafio-tech-fase-4.md). A [gap analysis](../../../requisitos/fase4/gap-analysis-fase-4.md) registra as duas exigências nos requisitos não funcionais RNF-035 e RNF-045 e deriva delas a regra de negócio RN-028 (comando ou evento reentregue não repete efeito) e o RNF-055, que reúne timeout, retry com backoff, fila de mensagens mortas (DLQ) e circuit breaker.

No p3 (código da fase 3, commit `08dcffe`), a outbox do ADR-022 grava o evento na transação do estado, e o relay entrega com `LISTEN/NOTIFY`, `FOR UPDATE SKIP LOCKED`, lease e atrasos de 1 a 256 s antes de marcar a linha como `dead` (`relay/backoff.py:17-18`). O relay só entrega e-mail, porque o broker foi adiado com gatilho de revisão. A idempotência usa o par `(outbox_id, handler)` da outbox local (`migrations/versions/003_outbox.py:72-83`), que não identifica mensagem entre serviços, e o MongoDB do Billing não tem `LISTEN/NOTIFY` nem `SKIP LOCKED`.

Em SAGA Pattern, a saga roda sobre RabbitMQ e Apache Camel (Aula 04, p. 13-15; Aula 05), mas publica dentro de `@Transactional`, sem outbox (Aula 05, p. 11), e os argumentos de dead letter e de tempo de vida (TTL) aparecem na criação de fila sem uso (Aula 05, Fig. 4).

Em Estrutura de Microsserviços (Microsserviços I), o broker executado é o Amazon SQS, via LocalStack (Aula 05), e o Apache Kafka aparece como exemplo de broker (Aula 02). A mesma disciplina apresenta a mensagem em header e body, com índice de ordenação no header, os canais point-to-point e publish-subscribe (Aula 02) e o consumidor idempotente, que usa o "ID do Evento para sabermos se já foi processado" (Aula 05). Retry com atraso e DLQ não aparecem em nenhuma aula.

**Qual broker e quais garantias de entrega sustentam comandos e eventos da saga sem perder nem repetir efeito, com dois serviços em PostgreSQL e um em MongoDB?**

## Decisão

RabbitMQ 4 como broker único entre OS Service (ordens de serviço, OS), Billing Service e Execution Service (contexto Execução), com outbox transacional no produtor e consumidor idempotente em todos os serviços. A entrega é pelo menos uma vez; com a deduplicação no consumidor, cada efeito acontece uma vez (efetivamente uma vez). A versão exata, 4.3.6, fica na tabela de versões fixadas do `platform` ([ADR-041](041-estrategia-de-testes-e-qualidade.md)).

### Topologia

Exchanges `pytstop.comandos`, `pytstop.eventos` e `pytstop.retry` (topic) e `pytstop.dlx` (direct); routing keys `comando.<servico>.<acao>` (ex.: `comando.billing.gerar_orcamento`) e `evento.<servico>.<fato>` (ex.: `evento.execucao.pecas_reservadas`). Filas quorum, duráveis:

| Fila | Exchange e binding | Consumidor |
|---|---|---|
| `billing.comandos` | `pytstop.comandos`, `comando.billing.#` | Billing |
| `execucao.comandos` | `pytstop.comandos`, `comando.execucao.#` | Execução |
| `os.eventos` | `pytstop.eventos`, `evento.billing.#` e `evento.execucao.#` | OS Service |

Comando vai para uma fila só (point-to-point); evento sai num exchange de tópico (publish-subscribe), e um consumidor novo entra com um binding, sem mudar o produtor. Os participantes consomem só comandos ([ADR-035](035-saga-orquestrada.md)).

Cada fila `X` tem filas auxiliares de retry e uma DLQ. As de retry são uma por atraso, `X.retry.1s`, `X.retry.5s`, `X.retry.15s`, `X.retry.60s` e `X.retry.300s`, sem consumidor e com o TTL fixo como argumento da fila (`x-message-ttl`). Cada uma recebe pelo `pytstop.retry`, com binding de chave exata igual ao próprio nome, a cópia que o consumidor republica num erro transitório; quando o TTL vence, o próprio broker a devolve a `X` pelo dead letter da fila de retry (default exchange, chave `X`, numa policy por fila de trabalho, `retry-X`, com o padrão `^X\.retry\.`). O `pytstop.retry` roteia como um direct, mas é de tópico porque o RabbitMQ só aplica permissão por routing key em exchange de tópico (seção seguinte). A `X.dlq`, ligada a `pytstop.dlx` pela chave `X`, recebe a mensagem rejeitada e a guarda por 7 dias.

A topologia tem uma fonte só: o `definitions.json` do `platform` declara exchanges, as 21 filas e os bindings, e o broker o carrega ao subir.

- Dead letter, overflow, tamanho e o TTL da DLQ vêm das `policies` do mesmo arquivo, que, ao contrário dos argumentos de fila, valem também para as filas que já existem; assim a topologia converge quando o broker reinicia.
- O TTL das filas de retry é a exceção e fica no argumento da fila: o atraso faz parte do nome dela, então mudar um atraso é criar outra fila, nunca mudar o argumento de uma que já existe. Ele também não vai para a policy da fila de trabalho (`retry-X`), que vale para as cinco filas de retry dela: com policy e argumento, a fila quorum usa o menor dos dois (ver Notas), e um `message-ttl` ali cortaria os atrasos maiores.
- Os serviços só fazem declaração passiva, que no RabbitMQ 4.3.6 também exige permissão sobre o recurso: cada serviço confere só as filas e os exchanges em que lê ou escreve e, se a fila ainda não existir, espera com backoff.

Isso evita duas falhas da declaração por serviço: o relay que publica com `mandatory` antes de o consumidor vizinho declarar a fila e acumula falhas até marcar a linha como `dead`, e a redeclaração com argumento diferente, que o broker recusa (`PRECONDITION_FAILED`). Um teste na integração contínua (CI) do `platform` confere o `definitions.json` contra o documento AsyncAPI de `contratos/`, e outro passo sobe um RabbitMQ avulso com ele e prova o retry como o usuário de um serviço. A topologia fica junto dos contratos porque é acordo entre os serviços, como os schemas; cada serviço continua dono do seu consumidor e da sua outbox.

### Usuários e permissões

Cada serviço conecta com um usuário próprio, sem permissão de `configure`:

| Usuário | Escreve em | Lê de |
|---|---|---|
| `os` | `pytstop.comandos`, só chaves `comando.*`; `pytstop.retry`, só as chaves `os.eventos.retry.1s` a `.300s` | `os.eventos` |
| `billing` | `pytstop.eventos`, só chaves `evento.billing.*`; `pytstop.retry`, só as chaves `billing.comandos.retry.1s` a `.300s` | `billing.comandos` |
| `execucao` | `pytstop.eventos`, só chaves `evento.execucao.*`; `pytstop.retry`, só as chaves `execucao.comandos.retry.1s` a `.300s` | `execucao.comandos` |

O `admin` fica para a operação (console e redrive). Os usuários são criados por um script de init a partir de Secrets, fora do `definitions.json`, com senhas geradas no deploy ([ADR-042](042-cicd-e-deploy-kubernetes.md)).

As chaves de cada usuário são permissões de tópico do broker: um serviço não publica comando ou evento de outro nem põe mensagem nas filas de retry de outra fila.

O publicador preenche a propriedade `user_id` do AMQP (*Advanced Message Queuing Protocol*), que o broker confere contra o usuário da conexão; nenhum usuário de serviço tem a tag `impersonator`, que liberaria outro valor. Como defesa em profundidade, o consumidor confere o `user_id` contra o produtor que o catálogo de mensagens associa ao `tipo` (`GerarOrcamento` vem do `os`, `PagamentoConfirmado` do `billing`); a routing key não serve para isso, porque na cópia de retry ela é o nome da fila de retry. Divergência é erro permanente e vai para a DLQ.

A cópia de retry sai com o usuário do consumidor que a republica, porque o broker exige o da conexão; numa mensagem com `x-tentativa` maior que zero, o consumidor aceita o próprio usuário, já que a conferência do produtor foi feita na primeira entrega. Com isso, a credencial de um serviço não basta para publicar comando ou evento de outro, como um `PagamentoConfirmado` fora do Billing.

### Envelope

Corpo JSON:

```json
{"id": "uuid", "tipo": "GerarOrcamento", "versao": 1, "origem": "os-service",
 "correlation_id": "<ordem_id>", "causation_id": "<id da mensagem que causou|null>",
 "ocorrido_em": "2026-10-06T12:00:00Z", "dados": {}}
```

As propriedades AMQP são `message_id` (= `id`), `correlation_id`, `type` (= `tipo`), `user_id`, `content_type=application/json` e `delivery_mode=2`, com os headers `traceparent`/`tracestate` (W3C) e `x-tentativa`. O `correlation_id` é o `ordem_id`, que também identifica a saga. Valor monetário vai como string decimal (`"350.00"`) com `moeda: "BRL"`, nunca float. O `traceparent` é capturado quando a outbox é gravada, para o relay publicar no contexto da requisição de origem (RNF-056, [ADR-043](043-observabilidade-distribuida.md)).

### Entrega, retry e DLQ

- Retry: erro transitório gera uma cópia, publicada no `pytstop.retry` sem `expiration`, com `x-tentativa` incrementado e confirmação do broker antes do `ack` da original.
  - A routing key é a da fila de retry do atraso daquela tentativa: `x-tentativa` de 1 a 5 vai para `X.retry.1s`, `.5s`, `.15s`, `.60s` e `.300s`. A fila é uma por atraso porque TTL só vence na cabeça da fila ([Uma fila de retry com TTL por mensagem](#uma-fila-de-retry-com-ttl-por-mensagem)); com o mesmo TTL em toda a fila, a ordem de chegada é a de expiração.
  - Se o processo cair entre publicar a cópia e dar `ack` na original, a mensagem chega duas vezes, sem se perder, e a idempotência absorve a repetição.
  - Esgotadas as cinco tentativas, `reject` sem requeue leva a mensagem para `X.dlq`; erro permanente (validação, schema, `user_id` divergente, `versao` desconhecida) vai direto.
  - O limite de entregas da fila quorum (`x-delivery-limit`, padrão 20 desde o RabbitMQ 4.0) desvia para a DLQ a mensagem que derruba o consumidor antes do `reject`.
- Outbox no PostgreSQL (OS Service e Execução): o relay do p3 continua, com `pg_notify` e polling de segurança, `FOR UPDATE SKIP LOCKED`, lease, fencing e as métricas do ADR-024. A linha de mensagem só vira entregue depois do publisher confirm, e a publicação usa `mandatory`, para que mensagem sem fila de destino volte como erro em vez de ser confirmada e descartada. Queda do broker não conta como falha da linha: sem conexão, o relay não reivindica linhas e reconecta com backoff de até 30 s; só a falha da própria mensagem (sem confirmação ou devolvida pelo `mandatory`) conta, com os atrasos do p3 até `dead`.
- E-mail ao cliente: no OS Service, a outbox tem também linhas com destino `email`, que o relay entrega pelo SMTP, como no p3, separadas da mensageria. Uma falha de SMTP retenta só aquela linha e não trava a saga.
- Outbox no MongoDB (Billing): coleção `outbox` gravada na mesma transação multidocumento do efeito (replica set de um nó, [ADR-037](037-banco-por-servico.md)); o relay faz polling e reivindica cada documento com claim atômico (`find_one_and_update` de pendente para em entrega, com lease), sob a mesma regra de confirmação.
- Consumidor idempotente: `mensagens_processadas` (chave = `id` da mensagem) é gravada na transação local do efeito. Evento repetido recebe `ack` sem efeito. Comando repetido, pelo mesmo `id` ou pela chave de negócio (RN-028: uma reserva por OS, uma cobrança por orçamento), como no reenvio do orquestrador com `id` novo, publica de novo a resposta registrada, para que a saga não espere por uma resposta que já saiu.
- Retenção: linhas entregues da outbox são apagadas depois de 7 dias, e `mensagens_processadas`, depois de 30 dias, muito além da janela de reenvio e de retry; a DLQ guarda por 7 dias. As mensagens à Execução levam a placa do veículo ([ADR-037](037-banco-por-servico.md)), e a retenção limita por quanto tempo ela fica fora do OS Service.
- Redrive: `make -C platform redrive FILA=<fila>` devolve as mensagens de `X.dlq` para `X`, com o usuário `admin`. O runbook `docs/operacao/runbook-saga.md` do `platform` descreve o diagnóstico antes do redrive.
- Ordem: o relay do PostgreSQL publica em ordem por OS, porque herda do p3 o head-of-line por agregado: uma linha em backoff segura as seguintes do mesmo agregado, e `dead` não bloqueia (`relay/processador.py:13-16`). O consumo não preserva essa ordem, porque retry e consumidores concorrentes podem inverter mensagens da mesma OS. Decide a etapa da saga: evento obsoleto é ignorado, e evento adiantado volta pela retry até a saga alcançá-lo ([ADR-035](035-saga-orquestrada.md)).
- Contratos e versões: documento AsyncAPI (padrão citado na Aula 04 de Microsserviços I) e um JSON Schema por mensagem em `platform/contratos/`. Cada serviço copia os schemas que produz e consome e os valida em teste de contrato no CI, que também confere a cópia contra a origem ([ADR-041](041-estrategia-de-testes-e-qualidade.md)). O campo `versao` segue a regra de convívio de versões da Aula 04: mudança aditiva (campo opcional novo) mantém a `versao`, e o consumidor lê de forma tolerante, com `additionalProperties` permitido; mudança que quebra exige `versao` nova, com o consumidor implantado antes do produtor; `versao` desconhecida é erro permanente e vai para a DLQ.

## Alternativas Consideradas

* RabbitMQ com outbox e consumidor idempotente
* Apache Kafka
* Amazon SQS e SNS (LocalStack no cluster)
* Redis Streams
* Ordem por fila com consumidor único ativo
* Ordem por OS com consistent hash
* Uma fila de retry com TTL por mensagem
* Uma policy por fila de retry
* Exchange de atraso do plugin `rabbitmq_delayed_message_exchange`
* Retry nativo da fila quorum (RabbitMQ 4.3)

Descartado pelo enunciado: REST síncrono entre todos os serviços, porque a l. 101 pede mensageria para a orquestração.

### RabbitMQ com outbox e consumidor idempotente

* Bom, porque é o broker da prática de SAGA Pattern e um dos três que o enunciado nomeia
* Bom, porque tópico, dead letter, TTL por fila, publisher confirms e `user_id` validado são nativos: retry com atraso, DLQ e conferência do produtor saem de configuração
* Ruim, porque é mais um componente com estado e, com um nó, sem replicação: a fila quorum dá garantias de dead letter, não alta disponibilidade
* Ruim, porque o efetivamente uma vez depende de disciplina em todo handler, custo já assumido no ADR-022

### Apache Kafka

* Bom, porque é o exemplo de broker de Microsserviços I (Aula 02)
* Bom, porque retém o log para reprocessamento e garante ordem por partição (chave = `ordem_id`)
* Ruim, porque não tem retry com atraso nem DLQ nativos: viram tópicos por convenção e código no consumidor
* Ruim, porque comando point-to-point vira tópico com grupo de consumidores, e o broker em JVM (máquina virtual Java) costuma pedir mais memória num kind já carregado (gap analysis, seção 12)

### Amazon SQS e SNS (LocalStack no cluster)

* Bom, porque é o único broker executado em Microsserviços I (Aula 05), com DLQ por redrive policy e atraso nativos
* Ruim, porque no kind e no k3s seria um emulador no papel de produção; o SQS real exigiria conta AWS, e a do Academy expira em 4 h e pede uma pessoa a cada sessão
* Ruim, porque evento para vários consumidores pede SNS com uma fila por assinante, e o roteamento por chave fica mais pobre que o exchange de tópico

### Redis Streams

* Bom, porque é leve, tem grupos de consumidores com reentrega de pendentes, e Data Engineering cita filas de mensagens e pub/sub entre os usos do Redis (Aula 03)
* Ruim, porque roteamento, DLQ e atraso seriam código próprio
* Ruim, porque a durabilidade depende da persistência configurada, que o material não discute
* Ruim, porque um Redis comum aos três serviços seria lido como banco compartilhado (gap analysis, seção 12)

### Ordem por fila com consumidor único ativo

O *single active consumer* do RabbitMQ (`x-single-active-consumer`, aceito em filas quorum) entrega a fila a um consumidor por vez, na ordem de chegada.

* Bom, porque a ordem de consumo passaria a ser a de publicação, sem tratamento na saga
* Ruim, porque cada fila teria um consumidor ativo só, e as outras réplicas ficariam em espera: o consumo deixaria de escalar
* Ruim, porque o retry continuaria a inverter mensagens: a cópia que espera numa fila de retry volta depois das que chegaram em seguida

### Ordem por OS com consistent hash

O exchange `x-consistent-hash`, de um plugin que acompanha o RabbitMQ, espalha as mensagens por várias filas pelo hash de uma propriedade, como o `correlation_id` (o `ordem_id`), com um consumidor por fila.

* Bom, porque as mensagens de uma OS iriam sempre para a mesma fila, em ordem, e OS diferentes seguiriam em paralelo
* Ruim, porque o número de filas fixa o paralelismo, e a documentação do plugin diz que, depois de um reinício do nó, a mesma chave pode passar a outra fila
* Ruim, porque o retry quebraria a ordem do mesmo jeito, e a saga ainda teria de tratar evento fora da etapa

### Uma fila de retry com TTL por mensagem

Uma `X.retry` por fila de trabalho, com o atraso no `expiration` de cada cópia.

* Bom, porque são 9 filas em vez de 21, e mudar um atraso é mudar o consumidor, sem tocar na topologia
* Ruim, porque TTL por mensagem só vence quando a mensagem chega à cabeça da fila: no RabbitMQ 4.3.6, uma cópia de 1 s publicada atrás de uma de 8 s só voltou aos 8 s. Com os atrasos de 1 a 300 s, a primeira retentativa de uma mensagem que chegasse atrás de uma cópia de 300 s esperaria até 300 s, e o prazo técnico da saga (120 s) venceria já depois da primeira falha; com as filas por atraso, só a quinta espera passa dos 120 s (ver Neutras)

### Uma policy por fila de retry

Cada fila de retry teria a própria policy, com o dead letter da fila de trabalho e o `message-ttl` do atraso, no lugar da `retry-X` comum às cinco e do TTL no argumento (só uma policy vale por fila).

* Bom, porque o TTL seguiria a regra das outras filas: fica na policy, que a importação regrava a cada boot, e nada depende de argumento imutável
* Ruim, porque seriam 15 policies em vez de 3, cada uma repetindo o dead letter da fila de trabalho, e o atraso continuaria no nome da fila: mudar o `message-ttl` de `X.retry.5s` deixaria o nome errado, então mudar um atraso ainda seria criar outra fila, com binding e permissão, e a policy não pouparia nada

### Exchange de atraso do plugin `rabbitmq_delayed_message_exchange`

O plugin cria um tipo de exchange que segura cada mensagem pelo tempo do header `x-delay` antes de rotear.

* Bom, porque o atraso iria em cada cópia, sem uma fila por atraso e sem head-of-line
* Ruim, porque o repositório do plugin está arquivado, e o README dele diz que o Team RabbitMQ não o mantém mais e que ele depende do Mnesia, que saiu do RabbitMQ no ciclo do 4.3.0; a última versão publicada é a 4.2.0, e ele não vem na imagem oficial do broker (ver Notas)
* Ruim, porque, pelo mesmo README, a mensagem em espera fica numa tabela Mnesia com uma réplica em disco só no nó atual, fora da fila quorum (perder o nó ou desligar o plugin perde as cópias que esperam), e o exchange não aceita `mandatory`, que o consumidor usa para só dar `ack` na original depois de saber que a cópia tem fila de destino

### Retry nativo da fila quorum (RabbitMQ 4.3)

A partir do 4.3, a fila quorum pode segurar a mensagem devolvida pelo consumidor antes da nova entrega (*delayed retry*), por `min(delayed-retry-min × delivery-count, delayed-retry-max)`.

* Bom, porque dispensaria as filas de retry e o exchange `pytstop.retry`: o consumidor só devolveria a mensagem à fila
* Ruim, porque o atraso cresce em linha reta (1, 2, 3 s com mínimo de 1 s), não nos degraus de 1 a 300 s
* Ruim, porque, com o AMQP 0-9-1 do pika, só o `basic_reject` com requeue incrementa o `delivery-count`; com o `basic_nack` a espera fica no mínimo e a mensagem volta para sempre, sem chegar ao limite de entregas (conferido no 4.3.6). A contagem de tentativas sairia do header `x-tentativa`, que o consumidor controla, para um contador que depende de qual chamada ele usa

## Consequências

### Positivas

* Mensageria sem escrita dupla em banco e broker nos três serviços, inclusive no que usa MongoDB (RNF-035 e RNF-045)
* RN-028 garantida pela deduplicação e pelas chaves de negócio: reentrega, reenvio e retry não repetem reserva, cobrança, estorno nem transição, e comando repetido devolve a resposta registrada
* A credencial de um serviço não publica em nome de outro: permissão por usuário e por routing key no broker e `user_id` conferido no consumo
* Mensagem esgotada para na DLQ e dispara alerta ([ADR-043](043-observabilidade-distribuida.md)); `correlation_id` e `traceparent` reúnem a saga num trace e numa busca de log

### Negativas

* São 21 filas em vez de 9, e cada atraso vira nome de fila, binding e chave na permissão de tópico: mudar um atraso é criar a fila nova, ajustar a permissão e os consumidores e apagar a antiga nos brokers que já existem, porque a importação do boot não apaga fila
* O atraso não viaja na cópia, e o teste de integração de um serviço não o encurta pelo consumidor: para não esperar até 300 s, o teste carrega no RabbitMQ dele uma cópia do `definitions.json` com `x-message-ttl` menor nas filas de retry (mesmos nomes, bindings e policies)
* Duas implementações de outbox (PostgreSQL e MongoDB) para manter e testar
* Uma queda longa do RabbitMQ não perde mensagem, mas para as sagas: as linhas se acumulam na outbox até o broker voltar, e o alerta de outbox parada dispara ([ADR-043](043-observabilidade-distribuida.md))
* Cada handler classifica o erro: transitório mal classificado vai para a DLQ, permanente mal classificado gasta cinco tentativas
* Fila ou binding novo exige pull request (PR) no `platform`, coordenado com o serviço que vai usá-lo, e cada usuário do broker é mais uma credencial para gerar e girar
* A cópia dos schemas em cada serviço fica atrás da origem até alguém atualizá-la; o CI acusa a cópia alterada, mas não a desatualizada

### Neutras

* As quatro primeiras esperas de retry somam 81 s, dentro do prazo de resposta da saga (`SAGA_PRAZO_RESPOSTA_SEGUNDOS`, padrão 120 s); com a quinta, de 300 s, a soma chega a 381 s, e o orquestrador pode reenviar um comando ainda em retry, ao que o participante responde de novo com o desfecho registrado

## Decisões Relacionadas

- [ADR-022](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p3/blob/main/docs/arquitetura/adr/fase2/022-transactional-outbox-relay.md): outbox e relay reaproveitados; o gatilho de revisão se cumpre aqui
- [ADR-024](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p3/blob/main/docs/arquitetura/adr/fase2/024-metricas-prometheus.md): métricas do relay, mantidas em cada serviço
- [ADR-035](035-saga-orquestrada.md): orquestrador e tratamento de evento por etapa
- [ADR-037](037-banco-por-servico.md): bancos onde vivem outbox e `mensagens_processadas`, e a placa na Execução
- [ADR-041](041-estrategia-de-testes-e-qualidade.md): testes de contrato e de idempotência, versões fixadas
- [ADR-042](042-cicd-e-deploy-kubernetes.md): geração das senhas dos usuários do broker
- [ADR-043](043-observabilidade-distribuida.md): `traceparent`, métricas de mensageria e alertas
- [RFC-004](../../rfc/fase4/rfc-004-microsservicos-saga.md): catálogo completo de comandos e eventos

## Notas

* Material: SAGA Pattern, Aulas 04 (p. 13-15) e 05 (p. 11, Fig. 4); Estrutura de Microsserviços, Aulas 02, 04 e 05; Data Engineering, Aula 03
* O retry segue a política do relay do p3 (cinco tentativas com atraso crescente), com degraus próprios, de 1 a 300 s; a disciplina Resiliência em Microsserviços não tinha sido liberada até 06/10/2026
* TTL e policies, segundo a documentação do RabbitMQ: a fila quorum põe a mensagem expirada no dead letter quando ela chega à cabeça da fila (https://www.rabbitmq.com/docs/ttl#message-ttl-dead-lettering), e, entre argumento do cliente e policy de usuário, prevalece o argumento (https://www.rabbitmq.com/docs/policies#operator-policy-conflicts). Delayed retry da fila quorum: https://www.rabbitmq.com/docs/quorum-queues#delayed-retry
* TTL e policies no código e no broker 4.3.6: para `message-ttl`, a fila quorum usa o menor dos dois (`gather_policy_config` em https://github.com/rabbitmq/rabbitmq-server/blob/v4.3.6/deps/rabbit/src/rabbit_quorum_queue.erl), e o broker confirmou: argumento de 5 s com policy de 3 s expirou em 3,1 s, e argumento de 1 s com policy de 3 s, em 1,0 s
* Plugin `rabbitmq_delayed_message_exchange`: README do repositório oficial, arquivado (https://github.com/rabbitmq/rabbitmq-delayed-message-exchange, seções "This Project is No Longer Maintained" e "Limitations"); remoção do Mnesia no 4.3.0: https://github.com/rabbitmq/rabbitmq-server/pull/15542. A imagem `rabbitmq:4.3.6-management` traz o `rabbitmq_consistent_hash_exchange` e não traz este plugin (`rabbitmq-plugins list`)
* RabbitMQ: TTL (https://www.rabbitmq.com/docs/ttl), filas quorum (https://www.rabbitmq.com/docs/quorum-queues), confirmações (https://www.rabbitmq.com/docs/confirms), `user_id` validado (https://www.rabbitmq.com/docs/validated-user-id), single active consumer (https://www.rabbitmq.com/docs/consumers) e consistent hash (https://github.com/rabbitmq/rabbitmq-server/tree/main/deps/rabbitmq_consistent_hash_exchange)
* AsyncAPI: https://www.asyncapi.com/docs/reference/specification/latest; W3C Trace Context: https://www.w3.org/TR/trace-context/

> [↑ Raiz do projeto](../../../../README.md) · [↑ Arquitetura](../../README.md)
