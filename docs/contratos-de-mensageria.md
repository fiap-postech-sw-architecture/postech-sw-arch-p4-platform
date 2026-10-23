# Contratos de mensageria

> [↑ Raiz do projeto](../README.md)

| Arquivo | Conteúdo |
|---|---|
| [`contratos/asyncapi.yaml`](../contratos/asyncapi.yaml) | AsyncAPI 3.0: um canal por routing key (exchange e chave), um por fila de trabalho, a operação de envio de cada mensagem e a de consumo de cada fila |
| [`contratos/schemas/envelope.schema.json`](../contratos/schemas/envelope.schema.json) | JSON Schema 2020-12 do envelope comum |
| `contratos/schemas/<Mensagem>.schema.json` | JSON Schema 2020-12 do campo `dados` de cada uma das 34 mensagens |
| `contratos/exemplos/<Mensagem>.json` | Envelope completo de exemplo; juntos contam uma saga do pedido de diagnóstico até a compensação |
| [`contratos/tests/test_contratos.py`](../contratos/tests/test_contratos.py) | Testes que amarram catálogo, AsyncAPI, schemas, exemplos e a topologia do RabbitMQ |

O catálogo e os campos de cada mensagem são os da [RFC-004, seção 5.3](arquitetura/rfc/fase4/rfc-004-microsservicos-saga.md#53-catálogo-de-comandos-e-eventos), e o teste confere campo a campo cada schema contra uma cópia dessa tabela. `AnonimizarVeiculo` (LGPD, Lei Geral de Proteção de Dados: a Execução troca a placa guardada pelo marcador `ANONIMIZADO:{veiculo_id}`) é o único comando sem evento de resposta: se falhar de vez, o sinal é a mensagem na `execucao.comandos.dlq` e o alerta "DLQ com mensagens", e ela some da DLQ em 7 dias.

Envelope de toda mensagem:

```json
{"id": "<uuid>", "tipo": "GerarOrcamento", "versao": 1, "origem": "os-service",
 "correlation_id": "<ordem_id>", "causation_id": "<id da mensagem que causou ou null>",
 "ocorrido_em": "2026-10-06T12:45:00Z", "dados": {}}
```

Propriedades AMQP: `message_id` = `id`, `correlation_id`, `type` = `tipo`, `user_id` (o usuário do serviço que publica), `content_type=application/json`, `delivery_mode=2` e os headers `traceparent`/`tracestate` (W3C Trace Context), mais `x-tentativa` nas republicações. `correlation_id` é o id da OS (ordem de serviço, a instância da saga); fora da saga, o id do agregado tratado (`AnonimizarVeiculo`: `veiculo_id`). `causation_id` é o `id` da mensagem que causou esta, e evento nunca vai com `null`: a regra está na [RFC-004, seção 5.2](arquitetura/rfc/fase4/rfc-004-microsservicos-saga.md#52-envelope) e na descrição do campo em `envelope.schema.json`. Os exemplos seguem a regra, e um teste confere que cada evento aponta o comando de origem previsto na RFC e que cada comando aponta um evento ou fica `null`.

Regras que os schemas impõem:

- Routing key `comando.<serviço de destino>.<ação>` ou `evento.<serviço de origem>.<fato>`, com o nome da mensagem em snake_case: `GerarOrcamento` vai em `comando.billing.gerar_orcamento`, `PecasReservadas` em `evento.execucao.pecas_reservadas`.
- Valor monetário em string decimal com duas casas e até 10 dígitos inteiros (`"820.00"`, no máximo `"9999999999.99"`) e `moeda: "BRL"`; número em ponto flutuante é rejeitado.
- Data e hora em RFC 3339 e em UTC (`Z` ou `+00:00`).
- Ids (`ordem_id`, `veiculo_id`, `orcamento_id`, `pagamento_id`, `reserva_id`, `mecanico_id`, `decidido_por`) são UUID; placa normalizada sem hífen (`ABC1234` ou `ABC1D23`).
- `codigo` de serviço e `sku` de peça nos orçamentos e nos eventos: até 50 caracteres entre letras, dígitos, `.`, `_` e `-`, começando por letra ou dígito. O `sku` do comando `ReservarPecas` é mais estrito, o formato do Billing e da Execução: letras maiúsculas e dígitos separados por hífens, até 50 caracteres (`PEC-OLEO-5W30`). `quantidade` de 1 a 1000, e cada lista com no máximo 50 itens.
- Todo `pattern` termina em `(?![\s\S])`, e não em `$`: o `$` do `re.search` do Python casa também antes de um `\n` final, e o validador dos serviços aceitaria `"2026-10-06T12:00:00Z\n"`. O `format: date-time` do FormatChecker tem o mesmo defeito, então só o fim de texto do `pattern` rejeita.
- Diagnóstico concluído, pedido de orçamento e orçamento gerado têm ao menos um item; `ReservarPecas` e `ExecucaoFinalizada` aceitam lista vazia (orçamento só de serviços).
- `prioridade` do `AgendarExecucao`: `normal` (padrão) ou `alta`; a fila de execução atende `alta` antes e, dentro da mesma prioridade, por ordem de agendamento.
- `motivo` dos cinco comandos de compensação é um código da enumeração de `pytstop_saga_compensacoes_total` (`orcamento_recusado`, `orcamento_expirado`, `geracao_falhou`, `reserva_falhou`, `pagamento_recusado`, `pagamento_expirado`, `cancelamento`, `prazo_tecnico`); o texto que o atendente escreve fica só na OS. Texto livre (até 500 caracteres) só nos eventos de falha, e nunca vai para log.
- `CancelarOrcamento` e `EstornarPagamento` vão sem `orcamento_id` ou `pagamento_id` quando o passo estava em voo; o participante localiza o recurso pelo `ordem_id`. O estorno usa no provedor a chave de idempotência `estorno-{pagamento_id}`; o `id` da mensagem só deduplica a entrega.
- `PagamentoEstornado` diz o `motivo` (`compensacao` ou `pagamento_apos_encerramento`), e `PagamentoCancelado`, o `cancelado_em`.
- `OrcamentoAprovado` e `OrcamentoRecusado` com `canal=atendente` exigem `decidido_por` (o `sub` do atendente); com `canal=link`, ele não vai.
- `link_decisao` e `checkout_url` são `http` ou `https`, sem usuário na URL, e contêm o token do link: nunca vão para log nem para span.
- Mensagens sem nome, documento nem contato do cliente; a placa só aparece no `SolicitarDiagnostico`.
- Leitor tolerante: o schema aceita campo desconhecido, em qualquer nível, e o consumidor o ignora.

Mudança de contrato começa por um PR aqui. Campo novo opcional mantém a `versao`: atualiza o schema, o exemplo e a tabela da RFC copiada no teste, e o produtor pode enviá-lo antes de os consumidores o conhecerem. Mudança incompatível vira `versao: 2` do tipo, com o consumidor implantado antes do produtor. Cada serviço copia os schemas que produz e consome, e o `asyncapi.yaml`, que traz o usuário AMQP que publica cada tipo (`userId`, de onde o consumidor tira o produtor esperado); e os valida no próprio teste de contrato.

```bash
make test
make lint
```

O `make test` roda os exemplos e os negativos gerados contra os schemas, os campos da RFC, o AsyncAPI, a routing key e a topologia. O `make lint` roda ruff, mypy strict e bandit, mais shellcheck nos scripts e actionlint nos workflows.

A cobertura de linha do `make test` mede só o arquivo de teste. O que protege os schemas é a bateria de negativos gerados de cada exemplo (campo removido, tipo errado, valor fora do domínio, texto gigante, lista vazia), que precisa ser toda rejeitada, mais os testes de fronteira: toda lista vai de 1 a 50 itens (vazia só onde a RFC deixa), cada limite de tamanho, quantidade, valor e formato tem o valor no limite aceito e o seguinte rejeitado, e a regra do `decidido_por` vale nos dois sentidos em `OrcamentoAprovado` e `OrcamentoRecusado`.
