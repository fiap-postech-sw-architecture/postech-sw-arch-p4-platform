# PostgreSQL no OS e na Execução, MongoDB no Billing

> [↑ Raiz do projeto](../../../../README.md) · [↑ Arquitetura](../../README.md)

* Status: Aceita
* Data: 2026-10-06

## Contexto e Problema

O enunciado exige banco próprio por serviço, "sendo obrigatório" o "Uso de pelo menos um banco relacional (SQL)" e o "Uso de pelo menos um banco não relacional (NoSQL)" (l. 57-60), e proíbe que um serviço acesse "diretamente o banco de outro serviço" (l. 67); ver [desafio-tech-fase-4.md](../../../requisitos/fase4/desafio-tech-fase-4.md). Na [gap analysis](../../../requisitos/fase4/gap-analysis-fase-4.md), são os requisitos não funcionais RNF-031 (banco por serviço), RNF-032 (SQL), RNF-033 (NoSQL) e RNF-036 (nenhum acesso ao banco alheio).

O p3 (código da fase 3, commit `08dcffe`) usa um PostgreSQL 16 para tudo: escolhido no ADR-002, em StatefulSet na fase 2 (ADR-017) e em RDS na fase 3 (ADR-031). Não há NoSQL: o Redis guarda só contadores do rate limiter, sem persistência (ADR-023). O ADR-002 descartou MongoDB para o monolito, pela transação multidocumento e pelo desalinhamento com o SQLAlchemy, mas já tratava o orçamento como o dado semiestruturado do sistema, gravado em JSONB na tabela da ordem de serviço (`migrations/versions/004_orcamento_jsonb.py`).

A placa do veículo é dado pessoal no p3: a eliminação pela LGPD (Lei Geral de Proteção de Dados) a troca por um marcador, e os eventos só a carregam mascarada (`src/cliente_veiculo/dominio/events.py:12-15`).

Data Engineering não traz matriz de decisão, e os critérios estão espalhados pelas aulas. Os eixos da Aula 01 são modelo de dados, transação ACID (atomicidade, consistência, isolamento e durabilidade) com consistência rígida contra velocidade e escala, esquema rígido ou flexível e escala vertical ou horizontal. As Aulas 02 a 05 tratam de padrão de acesso e custo, e a Aula 06, de operação com banco como serviço (DBaaS). A Aula 07 trata de monitoramento centralizado e apresenta banco por serviço, com tipos diferentes por serviço, como possibilidade; a obrigação vem do enunciado.

**Que banco cada serviço usa, de forma que exista um SQL e um NoSQL e cada escolha se justifique pelo uso do serviço, e não só pela exigência?**

## Decisão

PostgreSQL 16 no OS Service (ordens de serviço, OS; base `os`) e no Execution Service (contexto Execução, base `execucao`); MongoDB 7 no Billing Service (base `billing`, replica set de um nó). Cada banco roda no cluster como StatefulSet com volume persistente (PVC, *PersistentVolumeClaim*), com credencial em Secret montado só nos pods do serviço dono: nenhum serviço conhece endereço ou senha do banco alheio (RNF-036).

| Critério | OS Service | Execution Service | Billing Service |
|---|---|---|---|
| ACID x escala (Aula 01) | transição da OS, histórico, etapa da saga e outbox num commit | reserva tudo-ou-nada com lock de linha, saldo nunca negativo | orçamento ou pagamento e outbox numa transação de documentos |
| Modelo e esquema (Aulas 01 e 02) | cliente, veículo e OS ligados por chave estrangeira; esquema estável | peça, reserva por OS, fila com posição; esquema estável | orçamento com linhas embutidas; pagamento com o resultado das consultas ao provedor |
| Padrão de acesso (Aulas 02 a 05) | por id, por status com ordenação, junção cliente-veículo-OS | lock das linhas de estoque em ordem fixa, fila ordenada | documento inteiro por id ou por `ordem_id` |
| Custo (Aulas 02 a 05) | PostgreSQL livre | PostgreSQL livre | MongoDB Community gratuito |
| Operação (Aulas 06 e 07) | mesma imagem, migrações e ferramentas do p3 | idem | motor novo, um nó, monitorado na mesma stack |

Mesmo com várias filiais, o volume de cada serviço cabe num nó; o eixo de escala horizontal não decide aqui.

### SQL no OS Service e na Execução

O OS Service grava num commit a transição da OS, a linha do histórico (só inserção, salvo a eliminação pela LGPD, que reescreve o `motivo`), a etapa da saga e o comando na outbox ([ADR-035](035-saga-orquestrada.md)); cliente, veículo e OS seguem no mesmo banco, com as chaves estrangeiras do p3.

A Execução reserva várias peças tudo-ou-nada com `SELECT ... FOR UPDATE` bloqueante, limitado por `lock_timeout`, travando os itens em ordem de `sku`, e registra uma reserva por OS, o que faz o comando repetido devolver o desfecho registrado sem reservar de novo (RN-028). É o lock pessimista do ADR-008 e da regra de negócio RN-012 do p3 sem o `NOWAIT`: com ele, quem perdesse a disputa pela última unidade receberia erro de lock em vez de `ReservaDePecasFalhou`. Os dois serviços SQL reaproveitam o SQLAlchemy imperativo (ADR-006), o Alembic e o relay com `LISTEN/NOTIFY` e `FOR UPDATE SKIP LOCKED` (ADR-022).

Em cada PostgreSQL, a soma dos pools de conexão dos processos, com o número máximo de réplicas do autoescalonamento horizontal (HPA), fica abaixo do `max_connections`, com os valores fixados no overlay de cada ambiente. No OS Service são quatro processos (api, consumidor, relay e `prazos`); na Execução, três, sem o `prazos`. O p3 fazia essa conta só para a API: (5 + 10) × 5 = 75 contra 100 (`k8s/configmap.yaml:33-42`).

### Retrato do veículo na Execução

A Execução guarda placa, marca, modelo e ano do veículo, recebidos em `SolicitarDiagnostico` junto com o `veiculo_id`, porque o mecânico precisa achar o carro no pátio. Nome, documento e contato do cliente não saem do OS Service. É uma exceção à política do p3 de só publicar a placa mascarada, e a eliminação pela LGPD passa a cobri-la: ao anonimizar um cliente, o OS Service envia `AnonimizarVeiculo {veiculo_id}` (`comando.execucao.anonimizar_veiculo`) para cada veículo dele, e a Execução troca a placa pelo marcador do p3, `ANONIMIZADO:{veiculo_id}` (`src/cliente_veiculo/dominio/placa_anonimizada.py`). A retenção das mensagens que levam a placa fica no [ADR-036](036-mensageria-rabbitmq.md).

### Documento no Billing

- O orçamento é lido e gravado inteiro: linhas, total, moeda, validade e estado, um por OS nesta fase. É o exemplo da Aula 02 (p. 8), uma fatura com array de itens, e é o que o p3 já guardava em JSONB.
- O pagamento guarda o resultado das consultas ao provedor, cujo formato muda entre Mercado Pago e simulador, só com os campos permitidos: dados do pagador e do cartão são descartados antes de gravar ([ADR-040](040-integracao-mercado-pago.md)). Embutido no documento, o resultado não pede uma tabela por formato.
- A tabela de preços de serviços e de peças é consultada por código do serviço ou pelo `sku` (código de estoque da peça).
- A transação de que o Billing precisa não cruza contextos: orçamento ou pagamento, mensagem na outbox e registro de mensagem processada. O MongoDB só oferece transação multidocumento em replica set ou cluster shardado; daí o replica set de um nó, também no compose e no kind. A Aula 02 cita a transação desde a versão 4.0, sem ligá-la ao replica set.
- Dinheiro em `Decimal128`, nunca `double`: o `Dinheiro` (Decimal) é convertido na borda do repositório; nas mensagens, o valor segue como string decimal ([ADR-036](036-mensageria-rabbitmq.md)).
- Outbox no MongoDB: coleção `outbox` gravada na transação do efeito. Sem `LISTEN/NOTIFY` nem `SKIP LOCKED`, o relay faz polling e reivindica um documento por vez com atualização condicional atômica e lease.
- Inicialização: o Billing não usa Alembic, e o equivalente do Job de migração dos serviços SQL é o Job `billing-init`, idempotente, que roda antes do rollout. Ele faz o `rs.initiate` do replica set de um nó, cria os índices e aplica o validador `$jsonSchema` no nível `moderate`, só com mudanças aditivas, para que pods antigos e novos convivam durante o Rolling Update. A readiness do Billing espera o primário eleito.

### Onde roda

A fase 4 não pede banco gerenciado, e o deploy obrigatório acontece em kind na integração contínua, sem credencial externa; o banco no cluster repete o padrão do ADR-017. Banco gerenciado continua sendo o alvo de produção: RDS for PostgreSQL, como no ADR-031 da fase 3, e MongoDB Atlas (Aula 02) para o Billing.

## Alternativas Consideradas

* PostgreSQL no OS e na Execução, MongoDB no Billing
* PostgreSQL nos três serviços
* DynamoDB no Billing
* Redis como banco do Billing
* Cassandra no Billing
* Neo4j em algum serviço
* MongoDB também na Execução

### PostgreSQL no OS e na Execução, MongoDB no Billing

* Bom, porque cada banco atende o padrão de uso do serviço, e o NoSQL fica onde o dado já era documento
* Ruim, porque o time passa a operar dois motores, e o MongoDB é novo para ele

### PostgreSQL nos três serviços

* Bom, porque reaproveitaria persistência, migrações, relay e JSONB do p3 sem motor novo
* Bom, porque haveria um motor só para operar, monitorar e copiar
* Ruim, porque não atende RNF-033: JSONB guarda documento, mas o banco continua relacional

### DynamoDB no Billing

* Bom, porque é NoSQL gerenciado de baixa latência (Aulas 03 e 06), sem servidor para operar
* Ruim, porque só existe na AWS, cuja conta acadêmica tem credencial de 4 horas; a integração contínua e o kind precisam rodar sem segredo externo
* Ruim, porque consultas além da chave são limitadas (Aula 03): orçamentos por `ordem_id` e pagamentos por referência do provedor pediriam um índice secundário planejado para cada uma

### Redis como banco do Billing

* Bom, porque o p3 já o usa
* Bom, porque é a opção de menor latência
* Ruim, porque a Aula 03 o apresenta como cache, sessões e contadores, com persistência em disco opcional e sem discutir durabilidade; pagamento é registro financeiro que não pode sumir num reinício
* Ruim, porque consulta por campo exigiria índices mantidos pela aplicação; no p3 ele guarda só contadores efêmeros (ADR-023)

### Cassandra no Billing

* Bom, porque escala de forma linear, sem ponto único de falha (Aula 04)
* Ruim, porque foi feito para grande volume e consulta analítica, com modelagem por consulta e operação especializada (Aula 04, p. 8-10); o Billing grava transações de negócio, não fluxo analítico
* Ruim, porque o material não apresenta transação no Cassandra, e orçamento e outbox precisam ser gravados juntos

### Neo4j em algum serviço

* Bom, porque cobriria o NoSQL e exercitaria a disciplina Banco de dados em Grafos
* Ruim, porque seria um banco a mais só para marcar o requisito: o domínio não tem caso de grafo, histórico da OS e OS de um veículo são consultas de um salto, e a Fig. 7 da Aula 01 de Grafos mostra relacional e grafo empatados até 2 saltos, com ganho só acima de 5 saltos e milhares de conexões

### MongoDB também na Execução

* Bom, porque checklists de diagnóstico podem variar por tipo de serviço, e o MongoDB já estaria na stack
* Ruim, porque reservar várias peças tudo-ou-nada com saldo nunca negativo é o caso do lock de linha do ADR-008; em documentos, cada reserva pediria transação multidocumento sem ganho
* Ruim, porque o código, as migrações e os testes do contexto `estoque` do p3 não migrariam como estão, e RNF-033 já está atendido no Billing

## Consequências

### Positivas

* Cada banco se justifica pelo uso do serviço (RNF-031 a RNF-033 e RNF-036)
* Os serviços SQL reaproveitam a persistência, as migrações e o relay do p3
* O Billing grava estado e mensagem de forma atômica, com dinheiro exato e sem dado pessoal do pagador
* Os mesmos bancos rodam no compose, no kind e no k3s

### Negativas

* Dois motores para operar, monitorar e fazer backup
* Replica set de um nó habilita a transação, não dá alta disponibilidade; banco no cluster fica sem backup automático, como no ADR-017
* O relay do Billing é outra implementação (polling, sem aviso do banco), com mais latência de publicação e código próprio para testar
* Sem junção entre bancos: tela que junte OS, orçamento e execução depende de eventos ou de composição por API
* A placa sai do OS Service: a eliminação pela LGPD depende de um comando à Execução, e com a Execução fora do ar a anonimização espera o comando ser consumido
* Processo novo ou teto maior de réplicas obriga a refazer a conta de conexões de cada PostgreSQL

### Neutras

* O validador em `moderate` confere os documentos novos e os que já eram válidos, não os antigos fora do schema; mudança que não seja aditiva pede migração explícita dos documentos

## Decisões Relacionadas

- [ADR-002](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p3/blob/main/docs/arquitetura/adr/002-banco-postgresql.md): PostgreSQL 16, mantido nos serviços SQL; o MongoDB descartado ali volta só no Billing
- [ADR-008](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p3/blob/main/docs/arquitetura/adr/008-bloqueio-pessimista-estoque.md): lock pessimista que mantém a Execução no SQL
- [ADR-017](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p3/blob/main/docs/arquitetura/adr/fase2/017-provisionamento-banco.md): banco como StatefulSet no cluster, padrão repetido aqui
- [ADR-031](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p3/blob/main/docs/arquitetura/adr/fase3/031-banco-gerenciado-rds.md): banco gerenciado, alvo de produção
- [ADR-035](035-saga-orquestrada.md): estado da saga no PostgreSQL do OS Service
- [ADR-036](036-mensageria-rabbitmq.md): outbox, consumidor idempotente e retenção das mensagens
- [ADR-040](040-integracao-mercado-pago.md): campos do provedor que o Billing guarda
- [ADR-042](042-cicd-e-deploy-kubernetes.md): Jobs de migração e de inicialização antes do rollout

## Notas

* Data Engineering, Aulas 01 a 07; Banco de dados em Grafos, Aula 01 (seção de performance e Fig. 7)
* Tabelas, coleções e índices de cada serviço: [RFC-004](../../rfc/fase4/rfc-004-microsservicos-saga.md)
* MongoDB: transações em replica set ou cluster shardado (https://www.mongodb.com/docs/manual/core/transactions/) e `Decimal128` para dinheiro (https://www.mongodb.com/docs/manual/tutorial/model-monetary-data/)

> [↑ Raiz do projeto](../../../../README.md) · [↑ Arquitetura](../../README.md)
