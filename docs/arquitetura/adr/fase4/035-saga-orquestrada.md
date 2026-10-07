# Saga de atendimento orquestrada pelo OS Service

> [↑ Raiz do projeto](../../../../README.md) · [↑ Arquitetura](../../README.md)

* Status: Aceita
* Data: 2026-10-06

## Contexto e Problema

O enunciado exige "Implementar o Saga Pattern para coordenar o fluxo transacional das ordens de serviço" (l. 71), com "rollback e compensação no caso de falha em qualquer etapa" (l. 73), orquestrado ou coreografado (l. 74-76), e pede "Documentar a escolha e justificar no README" (l. 77); ver [desafio-tech-fase-4.md](../../../requisitos/fase4/desafio-tech-fase-4.md). Na [gap analysis](../../../requisitos/fase4/gap-analysis-fase-4.md), isso é o requisito funcional RF-038, a regra de negócio RN-023 (compensação em qualquer passo) e os requisitos não funcionais RNF-037 (escolha justificada) e RNF-045 (mensageria na coordenação), com as regras derivadas RN-024 a RN-028.

Este ADR aplica também RN-029: depois do início da execução, a ordem de serviço (OS) não pode ser cancelada. A "etapa" do enunciado corresponde aqui a passo (T1 a T9); etapa, neste ADR, é o estado da instância da saga.

No p3 (código da fase 3, commit `08dcffe`) não há saga: cada transação crítica é ACID local (atomicidade, consistência, isolamento e durabilidade), e a aprovação do orçamento reserva estoque e avança a OS no mesmo commit (`src/ordem_servico/aplicacao/use_cases.py:482-493`). O que serve de base é a outbox com relay, retry e fila de mensagens mortas (DLQ) do ADR-022 do p3.

Richardson, citado na Aula 02 de SAGA Pattern, recomenda a coreografia "para SAGAS simples" (p. 12), e a aula compara as duas formas. Na Aula 05, o orquestrador fica no serviço que inicia a saga (`SagaPedido` dentro do pedido-service, Fig. 12), como na Fig. 2 da Aula 05 de Estrutura de Microsserviços (Microsserviços I), em que o Pedido publica comandos e consome as respostas em `pedido-saga-reply`. O exemplo cobre só o caminho feliz: as aulas de SAGA Pattern não tratam estado persistido, prazos nem idempotência, e nenhum hands-on executa compensação.

**Quem coordena a saga da OS, com que passos e compensações, e como ela resiste a falha, reentrega e concorrência?**

## Decisão

Saga orquestrada, com o orquestrador dentro do OS Service: máquina de estados em Python sobre a outbox, sem framework (a Aula 04 mostra orquestrador escrito à mão, p. 14). Uma instância por OS, com `saga_id = ordem_id`, que também é o `correlation_id` de todas as mensagens.

São nove passos (T1 a T9) em três serviços (OS Service, Billing Service e Execution Service, do contexto Execução), com espera humana, provedor externo e seis compensações, mais a entrega (T10, OS `ENTREGUE`), local ao OS Service e fora da saga. Pelo critério da Aula 02, não é saga simples. O README do OS Service resume esta justificativa (RNF-037). O tipo de cada passo usa os termos de Richardson, referência do material: compensável, pivot (ponto sem retorno, RN-029) e reprocessável.

| Passo (dono) | Avança com | Falha de negócio | Compensação | Tipo |
|---|---|---|---|---|
| T1 abrir OS (OS Service) | OS `RECEBIDA` | nenhuma | OS `CANCELADA` | compensável |
| T2 diagnóstico (Execução) | `DiagnosticoConcluido` | nenhuma | `DescartarDiagnostico` | compensável |
| T3 orçamento (Billing) | `OrcamentoGerado` | `GeracaoDeOrcamentoFalhou` | `CancelarOrcamento` | compensável |
| T4 decisão do cliente (Billing) | `OrcamentoAprovado` | `OrcamentoRecusado`, `OrcamentoExpirado` | nenhuma | desfecho de negócio |
| T5 reserva de peças (Execução) | `PecasReservadas` | `ReservaDePecasFalhou` | `LiberarReserva` | compensável |
| T6 pagamento (Billing) | `PagamentoConfirmado` | `PagamentoRecusado`, `PagamentoExpirado` | `EstornarPagamento` | compensável |
| T7 agendamento (Execução) | `ExecucaoAgendada` | nenhuma | `CancelarExecucao` | compensável |
| T8 início da execução (Execução) | `ExecucaoIniciada` | nenhuma | nenhuma | pivot |
| T9 finalização (Execução) | `ExecucaoFinalizada`, com baixa do estoque | nenhuma | nenhuma | reprocessável |

"Nenhuma" na coluna de falha significa que o passo não tem evento de falha de negócio. Falha técnica é tratada pelo prazo técnico nos passos com resposta automática (T3, T5, T6 até `PagamentoSolicitado` e T7) ou vai para a DLQ com alerta. É o caso do T2: `SolicitarDiagnostico` não tem resposta automática, porque o diagnóstico começa quando um mecânico o assume, e por isso `DescartarDiagnostico` entra em toda compensação.

### Pivot e ordem dos passos

O pivot é o início da execução física (T8): depois que o mecânico começa a desmontar o carro, o trabalho feito não se desfaz por mensagem. Até ali tudo compensa, inclusive o pagamento, por estorno. Antes do pivot, `POST /api/v1/ordens-de-servico/{id}/cancelamento` responde 202 com a etapa da saga e dispara a compensação; depois, responde 409. O histórico da OS registra o pedido e o desfecho.

A reserva (T5) vem antes do pagamento (T6), como na Aula 01, que reserva estoque antes de cobrar, e a OS só entra na fila de execução (T7) com pagamento confirmado (RN-027). Nesta ordem, falta de peça compensa sem estorno, e o estorno de RN-026 vale para toda compensação iniciada depois de `PagamentoConfirmado`. A OS vai a `AGUARDANDO_EXECUCAO` já no `PagamentoConfirmado`, porque o agendamento que vem depois é técnico e não tem falha de negócio.

### Compensações

Em ordem inversa, uma por vez, cada uma esperando a resposta: `CancelarExecucao` → `EstornarPagamento` → `LiberarReserva` → `CancelarOrcamento` → `DescartarDiagnostico` → OS `CANCELADA` → saga `COMPENSADA`. O plano inclui os passos concluídos e o passo em voo, cujo comando saiu e ainda não teve resposta quando chega o cancelamento ou se esgota o prazo técnico. O passo que falhou por regra de negócio fica de fora, porque o próprio participante já o encerrou.

Assim, recusa ou expiração do orçamento descarta o diagnóstico e cancela a OS, sem `CancelarOrcamento` (RN-024), e pagamento recusado ou expirado libera a reserva, cancela o orçamento, descarta o diagnóstico e cancela a OS (RN-025). A tabela de gatilhos por etapa, com cancelamento e prazo esgotado em cada uma, está na [RFC-004](../../rfc/fase4/rfc-004-microsservicos-saga.md).

Toda compensação é idempotente. Se chegar ao participante antes do comando original, ele grava uma lápide e descarta o original quando este chegar. `EstornarPagamento` compensa o T6 em qualquer estado do pagamento: cancela o que está em `SOLICITADO`, com resposta `PagamentoCancelado`, e estorna o `CONFIRMADO`, com resposta `PagamentoEstornado` ([ADR-040](040-integracao-mercado-pago.md)).

### Isolamento

A saga é ACD (atomicidade, consistência e durabilidade, sem o isolamento; Aula 01), com estados intermediários visíveis. Contramedidas:

- Pessimistic view (Aula 03): o estorno só sai depois de `ExecucaoCancelada`, para que nenhum mecânico comece o reparo de OS com pagamento já devolvido.
- Reread value com lock otimista (Aula 03; Optimistic Offline Lock na Aula 02 de Estrutura de Microsserviços Parte II): cada evento é tratado numa transação que relê OS e instância e grava conferindo a versão. Contra o lost update da aula (aprovar pedido já cancelado), `OrcamentoAprovado` ou `PagamentoConfirmado` posterior a um cancelamento encontra a saga em `COMPENSANDO` ou `COMPENSADA` e é ignorado com log, e o plano de compensação cancela o orçamento e devolve o pagamento. A mesma conferência serializa réplicas que recebam eventos da mesma saga.
- Semantic lock: os estados `AGUARDANDO_*` da OS e da instância marcam passo em curso, e a `MaquinaDeStatus` do p3 (allow-list) recusa o que não cabe na etapa, como entregar OS em `AGUARDANDO_PAGAMENTO`. Não está nas aulas; vem do livro de Richardson, referência do material.

### Estado persistido e eventos fora de ordem

A `Saga` é um process manager da camada de aplicação do OS Service, persistido como agregado próprio na tabela `sagas`, no PostgreSQL da outbox ([ADR-037](037-banco-por-servico.md)). OS e saga mudam na mesma transação: etapa e status não podem divergir, e mudança de etapa e comando seguinte entram no mesmo commit. Etapas: uma `AGUARDANDO_*` por espera (de `AGUARDANDO_DIAGNOSTICO` a `AGUARDANDO_INICIO`), `EM_EXECUCAO`, `CONCLUIDA`, `COMPENSANDO`, `COMPENSADA` e `FALHA_NA_COMPENSACAO`. Etapa e status da OS são campos diferentes, alguns com o mesmo nome; o mapa entre os dois está na RFC-004.

Evento que não corresponde à etapa atual tem dois tratamentos. Evento de passo já passado, ou que chega com a saga em compensação ou encerrada, é ignorado com log. Evento de passo à frente, como um `ExecucaoIniciada` que ultrapassou o `ExecucaoAgendada` no retry ou entre consumidores concorrentes, é erro transitório: volta pelas filas de retry até a saga alcançá-lo e, esgotadas as tentativas, vai para a DLQ com alerta. A exceção é a corrida do pivot: se `ExecucaoIniciada` chega com só `CancelarExecucao` pendente, nada foi desfeito, e a saga volta a `EM_EXECUCAO`, com "cancelamento recusado: execução já iniciada" no histórico. Reentrega não repete efeito (RN-028, [ADR-036](036-mensageria-rabbitmq.md)).

### Prazos

Espera humana com validade expira no dono do dado: o processo `prazos` do Billing ([ADR-040](040-integracao-mercado-pago.md)) vence o orçamento (`ORCAMENTO_VALIDADE_HORAS`, padrão 72) e o pagamento (`PAGAMENTO_VALIDADE_MINUTOS`, padrão 60) e publica `OrcamentoExpirado` ou `PagamentoExpirado`. Diagnóstico e execução dependem do mecânico, sem prazo automático.

Espera técnica tem prazo no orquestrador: sem resposta em `SAGA_PRAZO_RESPOSTA_SEGUNDOS` (padrão 120), o processo `prazos` do OS Service reenvia o comando, até 5 reenvios, e então inicia a compensação, que inclui o passo em voo. Compensação sem resposta segue a mesma regra. O contador de reenvios é por passo e volta a zero a cada comando novo, inclusive no primeiro de `COMPENSANDO`. Prazos e limites são variáveis de ambiente, listadas na RFC-004; o perfil de demonstração usa valores curtos.

### Falha na compensação

Com 5 reenvios sem resposta, ou com `EstornoDePagamentoFalhou`, a saga vai para `FALHA_NA_COMPENSACAO`, a sequência para e o alerta de saga parada dispara ([ADR-043](043-observabilidade-distribuida.md)). O que já foi compensado continua compensado e o resto fica como estava. No estorno recusado, por exemplo, a execução já saiu da fila, mas pagamento, reserva, orçamento e diagnóstico seguem ativos, e a OS mantém o status anterior, com a etapa visível na consulta da OS.

A intervenção manual segue o runbook `docs/operacao/runbook-saga.md` do `platform`. O operador resolve a causa (no estorno recusado, faz o estorno pelo painel do Mercado Pago) e retoma com `POST /api/v1/sagas/{ordem_id}/compensacao`, restrito a `admin`, que reenvia a compensação pendente e segue o plano. Mensagem parada numa DLQ volta à fila pelo redrive descrito no mesmo runbook ([ADR-036](036-mensageria-rabbitmq.md)).

### Contras da orquestração na Aula 02

A Aula 02 aponta dois contras (p. 10). O primeiro é o orquestrador acumular regra de negócio; aqui ele só conhece ordem, compensações e prazos, e preço, validade, verificação do pagamento e saldo ficam nos participantes, que respondem a comandos sem conhecer a saga. O segundo, que a Aula 05 repete (p. 18), é o ponto único de falha: o consumidor roda em réplicas e o estado fica no banco, então, se um pod cai, a mensagem sem confirmação volta à fila e outra réplica segue do ponto gravado.

## Alternativas Consideradas

* Orquestração no OS Service, com máquina de estados própria
* Coreografia por eventos
* Orquestrador como quarto serviço
* Vencimento das esperas humanas no orquestrador
* Pivot no pagamento, com estorno fora da saga
* Motor de workflow (Temporal, Camunda, AWS Step Functions)
* Apache Camel, como nas aulas

### Orquestração no OS Service, com máquina de estados própria

* Bom, porque o fluxo inteiro, com prazos e compensações, fica num lugar só, testável sem broker
* Bom, porque etapa da saga e status da OS mudam na mesma transação local
* Ruim, porque o OS Service vira dependência de todas as sagas e ganha um processo a mais (`prazos`)

### Coreografia por eventos

* Bom, porque dispensa coordenador: cada serviço reage a eventos e publica os seus, com acoplamento fraco (Aula 02)
* Bom, porque é a forma implementada primeiro na Aula 05 de SAGA Pattern e ilustrada na Fig. 1 da Aula 05 de Microsserviços I
* Ruim, porque nove passos ficariam espalhados em três serviços, sem um lugar que diga em que etapa a OS está
* Ruim, porque prazos, ordem das compensações e pivot exigiriam que cada serviço assinasse eventos dos outros dois, com risco de ciclo (Aula 02, p. 7-8)

### Orquestrador como quarto serviço

* Bom, porque o OS Service ficaria menor
* Bom, porque o orquestrador escalaria sozinho
* Ruim, porque status da OS e etapa da saga ficariam em bancos diferentes, e mantê-los coerentes pediria outra saga
* Ruim, porque soma repositório, banco, pipeline e deploy sem capacidade de negócio nova, e, nos exemplos do material, o orquestrador fica no serviço que inicia a saga (SAGA Pattern, Aula 05, Fig. 12; Microsserviços I, Aula 05, Fig. 2)

### Vencimento das esperas humanas no orquestrador

O `prazos` do OS Service venceria também orçamento e pagamento e mandaria o Billing encerrá-los.

* Bom, porque todos os prazos ficariam num processo só, com uma métrica e uma regra de alerta
* Ruim, porque a validade é dado do Billing, que a conhece desde a geração (`valido_ate` do orçamento, expiração da preferência no Mercado Pago): com o vencimento em outro serviço, uma aprovação que chega ao Billing enquanto o comando de expiração viaja produziria desfechos contraditórios e mais um caso de compensação
* Ruim, porque o Billing teria de receber e conferir um comando de expiração, quando uma atualização condicional local já resolve

### Pivot no pagamento, com estorno fora da saga

* Bom, porque nenhuma compensação dependeria de o Mercado Pago aceitar um estorno
* Ruim, porque o trecho entre pagar e começar o reparo, em que a oficina ainda pode desistir, ficaria sem compensação automática, e o estorno viraria trabalho manual
* Ruim, porque a Aula 01 compensa com registro reverso o registro contábil posterior à cobrança (p. 10), e o exemplo de Step Functions da Aula 02 tem o ramo `RefundCustomer` (Fig. 6)

### Motor de workflow (Temporal, Camunda, AWS Step Functions)

* Bom, porque estado durável, temporizadores, retentativas e visualização vêm prontos; Step Functions aparece na Aula 02 com ramo de estorno
* Ruim, porque Temporal e Camunda não aparecem no material e exigem servidor e banco próprios no cluster, um componente crítico a mais no kind e no k3s
* Ruim, porque Step Functions prende a saga à AWS, cuja conta acadêmica tem credencial de 4 horas, incompatível com o deploy em kind na integração contínua sem segredo externo
* Ruim, porque estado durável, retry e prazos saem baratos sobre o que o PytStop já tem: transação local, outbox e relay com retry e DLQ

### Apache Camel, como nas aulas

* Bom, porque é o orquestrador do hands-on (SAGA Pattern, Aula 05: Camel 4.1.0 com RabbitMQ)
* Ruim, porque é Java, e os três serviços são Python 3.14: o orquestrador viraria um processo à parte na máquina virtual Java
* Ruim, porque as rotas do exemplo não guardam estado, roteiam por trecho do corpo JSON e só cobrem o caminho feliz; estado, prazos e compensações teriam de ser construídos do mesmo jeito

## Consequências

### Positivas

* RF-038 e RN-023 a RN-029 ficam na máquina de estados do OS Service, com teste por transição e cenário BDD (*behavior-driven development*) por compensação ([ADR-041](041-estrategia-de-testes-e-qualidade.md))
* Nenhum comando enviado fica sem compensação: cancelamento e prazo esgotado incluem o passo em voo
* `GET /api/v1/sagas/{ordem_id}` e o histórico da OS mostram a etapa de cada saga, e o `correlation_id` amarra mensagens, logs e traces
* O pagamento continua compensável até o início do reparo, e o estorno aparece na demonstração

### Negativas

* Com todos os pods do consumidor fora, as sagas param; o estado não se perde, o processamento retoma na volta, e o alerta de saga parada dispara
* Consistência eventual: a OS pode mostrar `AGUARDANDO_APROVACAO` com o orçamento já vencido no Billing, até o evento chegar
* Compensação sequencial: cancelar depois do pagamento custa várias idas e voltas pelo broker e depende de o Mercado Pago aceitar o estorno
* `FALHA_NA_COMPENSACAO` deixa recursos parcialmente compensados até a intervenção manual
* Evento adiantado passa pelas filas de retry até a saga alcançá-lo, e, se o evento anterior parar na DLQ, ele também acaba lá

### Neutras

* Etapa e status da OS convivem com nomes iguais em parte (`AGUARDANDO_PAGAMENTO`, `EM_EXECUCAO`); logs e métricas da saga usam o rótulo `etapa` para distinguir

## Decisões Relacionadas

- [ADR-008](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p3/blob/main/docs/arquitetura/adr/008-bloqueio-pessimista-estoque.md): reserva com lock pessimista, agora o passo T5
- [ADR-022](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p3/blob/main/docs/arquitetura/adr/fase2/022-transactional-outbox-relay.md): outbox e relay, que gravam etapa e comando juntos
- [ADR-034](034-decomposicao-em-microsservicos.md): orquestrador hospedado no OS Service
- [ADR-036](036-mensageria-rabbitmq.md): RabbitMQ, retry, DLQ, redrive e consumidor idempotente
- [ADR-040](040-integracao-mercado-pago.md): pagamento, estorno e prazos do Billing
- [ADR-043](043-observabilidade-distribuida.md): métricas e alertas da saga
- [RFC-004](../../rfc/fase4/rfc-004-microsservicos-saga.md): catálogo de mensagens, tabela de gatilhos e diagramas de sequência

## Notas

* SAGA Pattern: Aulas 01 (transações compensatórias, p. 10), 02 (p. 6-12, Fig. 6), 03 (pessimistic view, reread value), 04 (p. 14) e 05 (p. 14-19, Fig. 12); Estrutura de Microsserviços, Aula 05 (Fig. 1 e 2); Estrutura de Microsserviços Parte II, Aula 02
* Richardson, Microservices Patterns (Manning, 2018), cap. 4: transações compensáveis, pivot e reprocessáveis; semantic lock. Padrão: https://microservices.io/patterns/data/saga.html

> [↑ Raiz do projeto](../../../../README.md) · [↑ Arquitetura](../../README.md)
