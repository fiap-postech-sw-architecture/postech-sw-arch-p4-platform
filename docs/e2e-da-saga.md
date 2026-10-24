# E2E da saga

> [↑ Raiz do projeto](../README.md)

O E2E é o BDD de ponta a ponta do desafio ([enunciado, l. 82](requisitos/fase4/desafio-tech-fase-4.md)): uma OS percorre os três serviços de verdade, no kind, pela borda, e cada falha da saga é provocada e conferida. Fica neste repositório porque nenhum serviço é dono do fluxo inteiro.

A ferramenta é o `pytest-bdd` 8, com Gherkin em português (`# language: pt`). Usa o mesmo runner e as mesmas fixtures do BDD de componente de cada serviço ([ADR-041](arquitetura/adr/fase4/041-estrategia-de-testes-e-qualidade.md)), e as tags do Gherkin viram markers do pytest.

## Como rodar

O E2E derruba o Billing com `kubectl scale`, cria usuários, preços, estoque e OS, e não limpa nada. **Rode só num cluster descartável**, uma execução por vez em cada cluster: duas execuções juntas se atropelam, porque a segunda religa o que a primeira acabou de derrubar. A sessão recusa um contexto que não comece por `kind-` e um nó do kind que não publique, no loopback, o host e a porta da `E2E_URL`, a borda que o E2E usa (por padrão a 443 de `https://localhost`; o guarda tira o par da própria URL, então uma `E2E_URL` para outro lugar também é recusada). O mesmo guarda roda no `make e2e` e no `make demo`. O escape é de propósito feio: `E2E_CONTEXTO_NAO_DESCARTAVEL=<o próprio contexto>`.

Precisa do cluster com a plataforma **no overlay `kind-ci`** (o orçamento vence em 72 s, a primeira recusa do provedor encerra a cobrança, o `prazos` do Billing roda a cada 5 s e o rate limit da borda é multiplicado por 10) e das `main` dos três serviços, o OS já com o `notificador`: sem ele o e-mail com o link de decisão nunca chega. A sessão confere esses valores no começo e diz o que mudar, e recusa um cluster com mensagem em alguma das três DLQs: a afirmação de DLQ vazia dos cenários compara com a contagem do início do cenário, e com a sessão exigindo DLQs vazias isso vale como zero num cluster limpo. Também precisa de `uv`, `kubectl` e da porta 443 livre no loopback. O `make e2e` roda os 14 cenários em cerca de 3 min e escreve os relatórios em `reports/e2e`; o `make demo` roda os cenários `@demo` (demonstrações 1 e 2 do vídeo) em cerca de 2 min e escreve em `reports/demo`. Com os repositórios dos serviços ao lado deste:

```bash
make kind-up deploy OVERLAY=kind-ci
scripts/ci/implantar-servicos.sh --overlay kind-ci \
  os-service=../postech-sw-arch-p4-os-service \
  billing-service=../postech-sw-arch-p4-billing-service \
  execution-service=../postech-sw-arch-p4-execution-service
scripts/ci/smoke-servicos.sh
make e2e
make demo
```

No CI quem roda isto é o job `e2e` do `cd.yml`, num kind do runner ([CI](ci-cd.md#job-e2e-a-saga-e-a-borda-com-os-três-serviços)). Cada alvo apaga e recria a pasta de relatórios, sai com o status do pytest e escreve o `resumo.md` mesmo com cenário reprovado. Para rodar um cenário só, use a tag dele: `uv run --group e2e pytest -c e2e/pytest.ini e2e -m caminho-feliz`. Se o pytest morrer no meio de um cenário de resiliência (a máquina dormiu, `kill -9`), basta rodar de novo: o início da sessão religa o que ficou em 0 réplicas.

| Variável | Para quê | Padrão |
|---|---|---|
| `KUBE_CONTEXT` | contexto do `kubectl` | `kind-pytstop-p4` |
| `E2E_URL` | borda do Kong; o guarda de contexto confere o host e a porta dela | `https://localhost` |
| `E2E_ADMIN_EMAIL` | e-mail do admin semeado | o `ADMIN_EMAIL` do ConfigMap do OS |
| `E2E_RELATORIOS` | pasta dos relatórios | `reports/e2e` |
| `E2E_NARRAR` | `1` imprime cada passo e, depois de cada `Então`, o status da OS (o `make demo` liga) | desligado |
| `E2E_CONTEXTO_NAO_DESCARTAVEL` | escape do guarda de contexto | ausente |

## Como o E2E enxerga o cluster

| Acesso | Para quê |
|---|---|
| Kong em `https://localhost` (443 → NodePort 30443, certificado padrão do Kong) | Todas as chamadas de negócio: `/os`, `/billing` e `/execucao`, como um cliente de fora. A verificação do certificado só se desliga para `localhost`, `127.0.0.1` e `::1`; para outro host, o cliente verifica. |
| `kubectl port-forward` de sessão para `svc/mailpit` (8025), `svc/jaeger` (16686) e `svc/execution-service` (8000) | O e-mail com o link de decisão do orçamento, o trace da saga e o `/metrics` da API da Execução, que o Kong não publica. |
| `kubectl` | A senha do admin (Secret `os-admin`), `scale` para derrubar o consumidor e a API do Billing, `rabbitmqctl list_queues` para as DLQs, `logs` da API do OS e, pelo proxy do apiserver (`get --raw`), a API do Prometheus. Todo comando tem prazo. |

Os usuários nascem uma vez por sessão: o E2E entra como o admin semeado e registra um atendente e um mecânico, cada um com e-mail e senha aleatórios. O OS limita login e registro a 5 por minuto, e atrás do Kong todo cliente do kind tem o mesmo IP. Por isso o cliente HTTP espera a janela passar quando recebe 429.

**Segredos.** A senha do admin, as senhas geradas e os tokens entram numa máscara e saem como `***`, junto com o token do link de decisão e o `token=` do checkout. A máscara cobre três saídas: as mensagens do próprio E2E; um plugin do pytest, que passa a falha e as seções capturadas por ela antes do terminal, do `junit.xml` e do `cucumber.json`; e o `::add-mask::` do GitHub Actions, emitido numa linha própria e visível ao runner porque o `e2e/pytest.ini` usa `--capture=sys`. O plugin também faz o SIGTERM rodar o teardown (o `kubectl port-forward` não fica órfão).

## Dados, espera e desfazer

- **Cada cenário cria os próprios dados**: cliente com CPF válido gerado (módulo 11) e e-mail único, veículo com placa Mercosul sorteada, preço do serviço e da peça no Billing e estoque na Execução, com códigos `SRV-E2E-<execução>-<n>` e `PEC-E2E-<execução>-<n>`. Nenhum cenário lê o que outro deixou, e o cluster não precisa ser limpo entre execuções.
- **Só se espera por polling com prazo** (`esperar(condição, prazo)`, em [`e2e/apoio/espera.py`](../e2e/apoio/espera.py)): nunca `sleep` fixo para "dar tempo". A condição roda ao menos uma vez e uma última no fim do prazo. O erro diz o que faltou e o último valor visto. A única espera em tempo corrido são os 20 s do consumidor parado, e mesmo ela amostra a OS a cada 2 s e reprova se a saga andar.
- **O consumidor do Billing só cai depois de uma raspagem do Prometheus.** O contador de um pod mora na memória dele e o Prometheus raspa a cada 15 s: o pod derrubado antes da raspagem seguinte leva o que contou desde a última. No `make demo`, o cenário do consumidor parado vem dois cenários depois do cancelamento com estorno (`@estorno`; o do 409 fica no meio) e derrubava o pod 8 a 9 s depois do estorno. A causa provável de o painel Pagamentos mostrar 6 estornos do Billing contra 8 do OS é o contador do pod derrubado ter perdido o incremento desse estorno; é inferência pelos tempos, ainda não medida ([registro](entrega/fase4/evidencias/observabilidade.md#como-os-números-dos-prints-fecham)). O passo agora pergunta o `time()` ao Prometheus do kind e espera, de 1 em 1 s e por até 60 s, que todo pod do consumidor tenha uma raspagem com sucesso (`up` 1) de instante posterior: de 0 a uns 15 s, sem `sleep` fixo, e pelo relógio do Prometheus, não pelo de quem roda o E2E. O `timestamp()` só devolve o instante da raspagem quando recebe o seletor sozinho (de uma expressão, como `timestamp(up == 1)`, devolve o da própria consulta e a espera passaria na hora), e por isso a consulta, `min(timestamp(up{...}) * up{...})`, está provada no promtool (`tests/alertas.promtool.yml`). Se o prazo estoura, a mensagem diz o que o Prometheus mostrava. A API do Billing parada não espera: antes de cair o cenário só cadastra preço, tráfego que só aparece nos painéis técnicos.
- **O que um cenário derruba volta no fim do próprio cenário**: `kubectl scale` registra as réplicas originais e restaura no teardown de cada cenário. A sessão tenta restaurar tudo de novo no fim, e o início da sessão religa o que uma execução anterior deixou em 0.

## O que cada tag prova

| Tag | Cenário | O que afirma | Rastreio |
|---|---|---|---|
| `@caminho-feliz` | abertura até a entrega | os 8 status em ordem; saga `concluida`; estoque reservado e depois baixado; a OS fora da fila antes do pagamento; e-mail do orçamento no Mailpit com o mesmo link da OS; trace no Jaeger (busca por `messaging.message.conversation_id` = `ordem_id`) com `os-service`, `billing-service` e `execution-service`, gravado quando duas leituras seguidas trazem o mesmo número de spans; o `X-Request-ID` devolvido pelo Kong na linha de acesso da API do OS, com o `trace_id` entre os traces da OS no Jaeger (a origem do id no Kong é provada por [`scripts/smoke.sh`](../scripts/smoke.sh)) | RF-028 a RF-037, RN-027, RNF-056 |
| `@compensacao` | cliente recusa pelo link | `cancelada`, motivo `orcamento_recusado`, só `DescartarDiagnostico`, diagnóstico `DESCARTADO` na Execução | RN-024 |
| `@compensacao` | falta de peça | `ReservaDePecasFalhou`, `CancelarOrcamento` e `DescartarDiagnostico`, nenhum pagamento, estoque intacto, motivo `reserva_falhou` | RN-026 |
| `@compensacao` | pagamento recusado no simulador | reserva liberada, orçamento `CANCELADO`, pagamento `RECUSADO` sem estorno, motivo `pagamento_recusado` | RN-025 |
| `@compensacao @estorno` | cancelamento com a OS paga e na fila | 202 em `compensando`; `CancelarExecucao`, `EstornarPagamento`, `LiberarReserva`, `CancelarOrcamento`, `DescartarDiagnostico` nessa ordem; pagamento `ESTORNADO`; OS fora da fila; e-mail de cancelamento | RN-023, RN-026 |
| `@validacao` | CPF de dígito errado | `POST /clientes` responde 422 `VALOR_INVALIDO`; o acompanhamento público dá o mesmo 404 (corpo igual, fora o `id_requisicao`) para CPF inválido e para CPF inexistente. Que o inválido não chega ao banco é provado nos testes do OS (`TestConsultarAcompanhamento`, em `test_use_cases_os.py`, e `test_documento_invalido_falha_antes_do_banco`, em `test_use_cases_cliente.py`) | RF-028, RF-030 (lição da fase 3) |
| `@ponto-de-nao-retorno` | cancelamento depois do início | 409 `TRANSICAO_STATUS_INVALIDA` ("Cancelamento recusado: execução já iniciada"); a OS segue `em_execucao` | RN-029 |
| `@expiracao` | orçamento vencido (72 s no `kind-ci`) | `OrcamentoExpirado`, `cancelada`, motivo `orcamento_expirado`, só `DescartarDiagnostico` | RN-024 |
| `@resiliencia` | consumidor do Billing em 0 por 20 s | o pod só cai depois de uma raspagem do Prometheus, para o contador de estornos dele não perder o que contou desde a última (no `make demo`, o estorno do cenário `@estorno`, dois cenários antes); a OS fica em `em_diagnostico` durante os 20 s, segue na volta até `aguardando_aprovacao`, e nenhuma das três DLQs ganha mensagem (amostra por 8 s, porque a contagem das filas quorum atualiza a cada ~5 s) | RNF-055, RN-028 |
| `@resiliencia` | API do Billing em 0 na conclusão do diagnóstico | duas conclusões dão 503; o indicador (*gauge*) `pytstop_circuit_breaker_aberto{dependencia="billing"}` vale 1 (lido do Service da Execução; 0,5 é meia-abertura e 0, fechado); com o Billing de volta, o teste espera o circuito sair do aberto, que dura 30 s ([RFC-004, 6.1](arquitetura/rfc/fase4/rfc-004-microsservicos-saga.md#61-rotas-por-serviço) e [10.3](arquitetura/rfc/fase4/rfc-004-microsservicos-saga.md#103-parâmetros-e-variáveis-de-ambiente)); a conclusão passa e o indicador volta a 0 | RNF-034, RNF-055 |
| `@borda` | Swagger pelo Kong | `/os/docs`, `/billing/docs` e `/execucao/docs` abrem e o `openapi.json` declara `servers: [{url: "/<prefixo>"}]` | ADR-038 |
| `@borda` | métricas das OS pela borda | `GET /os/api/v1/ordens-de-servico/metricas` sem token responde 401; com o admin, 200 com `total`, `por_status` (os nove status, zero onde não há OS) e `tempo_medio_por_status_segundos`, o cálculo que os gauges do painel "Tempo médio por status" leem | RF-027 da fase 3, ADR-039 |

As mensagens de erro de negócio se afirmam pelo código (`TRANSICAO_STATUS_INVALIDA`) e, quando o texto aparece, sem depender de acento ou de caixa. As compensações se afirmam pela ordem dos comandos nos passos da saga (`GET /os/api/v1/sagas/{id}`, só do admin), não pelo texto livre do histórico.

## Relatórios

`reports/e2e/` (pasta ignorada pelo git):

| Arquivo | Conteúdo |
|---|---|
| `junit.xml`, `cucumber.json` | Resultado de cada cenário e passo, nos formatos nativos do `pytest-bdd`. O `junit.xml` traz o nome da máquina: na evidência da entrega, anexe o `resumo.md` |
| `resumo.md` | Uma linha por cenário: tags, resultado, duração, `ordem_id` (= `correlation_id` da saga) e `trace_id`; também vai para o `$GITHUB_STEP_SUMMARY` |
| `cenarios.json` | O `ordem_id` e o `trace_id` que cada cenário registrou |
| `trace-<trace_id>.json` | O trace do caminho feliz, como o Jaeger o serve em `/api/traces/<id>` (o Jaeger guarda em memória e perde tudo ao reiniciar) |

## Demonstrações 1 e 2 do vídeo (`make demo`)

O `make demo` reaproveita os cenários marcados `@demo` e as mesmas fixtures. A **demonstração 1** é o fluxo completo (`@bloco-1`, até 4 min). A **demonstração 2** são as falhas (`@bloco-2`, até 4 min): reserva sem saldo, cancelamento com estorno, 409 depois do início, consumidor parado e API do Billing parada. Imprime cada passo e, depois de cada `Então`, o status e a etapa da OS (depois de um `Quando` assíncrono o status ainda seria o de antes), e no fim o tempo de cada bloco:

```text
=== A OS percorre os três serviços da abertura à entrega (@bloco-1 @caminho-feliz @demo)
  Quando o atendente abre uma OS para o veículo do cliente
  Então a OS fica com status "recebida"
      -> OS 64db2c4d: status=recebida etapa=aguardando_diagnostico
```

Ficam de fora a demonstração do deploy com testes e a do monitoramento (Jaeger, Grafana e Loki), que não são do E2E.

## Painéis de negócio com série

Com todos os cenários verdes, o `make e2e` confere ainda que cada consulta de painel de negócio devolve série no Prometheus do kind ([`e2e/apoio/paineis.py`](../e2e/apoio/paineis.py)): o `expr` de cada alvo dos quatro [dashboards de negócio](../observabilidade/negocio.md) roda em `/api/v1/query` (com `$__range` em 1h e `$__rate_interval` em 5m), e a que volta vazia ou com erro reprova, porque um nome de métrica trocado ou um rótulo errado deixaria vazio justamente o painel que a banca pediu. O p90 de Orçamentos só aparece com 10 decisões ou mais, e o E2E decide menos que isso: o gate roda essa consulta com o limiar em 1 (prova a métrica e o rótulo), e o limiar de 10 está provado no promtool (`tests/alertas.promtool.yml`). A tabela sai em `reports/e2e/paineis.md` e no resumo do job; os painéis técnicos e os alertas entram nela, mas não reprovam. O E2E alimenta até as duas séries esparsas da Execução (tempo de execução por serviço e peças em falta): um cenário finaliza uma execução e outro recusa a reserva por falta de peça. `make paineis` repete só essa conferência, sem o E2E (por exemplo depois do `make demo`), em qualquer cluster com o Prometheus da plataforma.

## Testes do código auxiliar

O que o E2E tem de crítico e não precisa de cluster está em [`e2e/apoio/`](../e2e/apoio) e é testado por [`tests/e2e_apoio/`](../tests/e2e_apoio), um arquivo por módulo, no `make test` e no CI, com cobertura de linhas e ramos. São a espera e seu prazo, a máscara de segredos e o plugin que a aplica ao relatório, o guarda de contexto e a conferência prévia do overlay (`preflight.py`), `Credenciais`, o parser do Mailpit e do Jaeger, a higienização do trace do sandbox (lista de permissão, URL reduzida, nome do arquivo, linha do resumo nos dois modos e o trace não encontrado), as métricas e as DLQs, o desfazer do `kubectl scale`, a espera da raspagem do Prometheus (contra um Prometheus falso que raspa a cada 15 s), o port-forward, o cliente HTTP e o resumo. Dezessete testes rodam o pytest do E2E num subprocesso. Nove são de `test_sessao.py`: a captura do `::add-mask::` (2), o relatório da falha sem credencial (2), o SIGTERM (1) e o guarda de contexto e de borda (4, com um `kubectl` falso). Oito são de `test_conftest.py`, as ligações do `conftest.py` com um `kubectl` e um `docker` falsos: o que um cenário derrubou volta antes do seguinte, a sessão devolve tudo no fim, o que uma execução anterior deixou em zero é religado no começo, overlay fora do `kind-ci` e DLQ com mensagem param antes do primeiro `scale`, o desfecho da chamada de cada cenário chega ao resumo do sandbox, e o passo do consumidor parado só derruba o pod depois de o Prometheus raspá-lo e reprova, sem derrubá-lo, se ele não raspa (2 testes).

O `make test` também coleta o E2E sem cluster (`pytest --collect-only` e `--generate-missing`): import quebrado, tag sem marker e step sem definição reprovam no CI, e não no primeiro `make e2e`. O `conftest.py`, os steps e o cliente dos serviços só rodam contra o cluster e ficam fora da cobertura. `ruff`, `mypy` e `bandit` cobrem tudo em `e2e/`.
