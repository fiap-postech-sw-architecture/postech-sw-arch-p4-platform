# Observabilidade no kind local: ensaio de 19/10/2026 e dashboards de 24/10/2026

Estado: prova parcial. O fluxo local, o trace distribuído, a ociosidade e a saúde posterior foram exercitados, e os nove dashboards foram capturados em 24/10/2026, todos na mesma janela, com seis execuções do `make demo` num kind novo ([Dashboards e histórico](#dashboards-e-histórico)). A chamada HTTP ao Mercado Pago real continua pendente.

## Ambiente e commits

Kind local próprio, criado em 19/10/2026 e já removido (o nome do cluster e o do contexto estão nos comandos abaixo). A plataforma usa o overlay `kind`, com PVC do Prometheus e retenção de 15 dias. Os serviços usam `kind-ci`, com os prazos de negócio do ensaio; a combinação mantém o Grafana e a persistência locais e permite exercitar os mesmos cenários do CI.

| Repositório | Commit exercitado |
|---|---|
| Plataforma | `91d959bcba07b3a7b53653342e944ea01bdaa3c3` |
| OS Service | `b81f609a193afa669ed602d3327cb074827c25d6` |
| Billing Service | `248c4071d357a867db1571081b012ff57753f834` |
| Execution Service | `605a5e56b297438163cddba2a4f129b334c1699d` |

Esses commits identificam a execução; não constituem congelamento de entrega. A adoção do workflow de implantação pelos serviços e as correções posteriores exigem novas verificações e atualização das evidências finais. Nenhuma credencial do provedor foi usada.

## Fluxo e trace

`make e2e CLUSTER=pytstop-p4-codex` passou com 14 cenários e três cenários de sandbox não selecionados, em 194,52 s. Foram exercitados fluxo completo, compensações, expiração, resiliência e borda. O smoke dos três serviços passou antes e depois; o smoke da plataforma, destinado à borda sem serviços publicados, foi usado apenas antes da implantação dos serviços.

O trace `af146ea716424dfc2ac5b25960b8e9ae` reúne 245 spans de OS, Billing e Execução, incluindo a chamada CLIENT da Execução ao SERVER do Billing em `/api/v1/precos/validacao`, com resposta 200. A [exportação para publicação](trace-saga-2026-10-19.json) preserva o grafo, os tempos e os 245 spans; foram retirados os atributos db.statement/db.user e os metadados dos processos. O Jaeger mantém somente os últimos 250 traces, por isso a exportação foi preservada.

O simulador de pagamento trabalha dentro do Billing e não produz chamada HTTP externa. O CLIENT do Billing para o Mercado Pago, o modo real de conciliação e a respectiva observação ociosa dependem de `make mp-sandbox` com as credenciais de teste do responsável.

## Dez minutos ociosos

Janela UTC: `2026-10-19T03:31:17Z` a `2026-10-19T03:41:17.872626Z`, duração de 600,9 s. Os 28 pods mantiveram os mesmos identificadores e contadores de reinício. Os 18 grupos de alvos (`job`) examinados estavam disponíveis na coleta final; os três exporters dos bancos também indicaram disponibilidade nesse instante. A consulta do tráfego de clientes nos dez minutos retornou zero nos três serviços.

DLQs e outboxes pendentes/dead estavam vazias na coleta posterior. Houve processamento de mensagens de fundo remanescentes dos cenários; ausência de tráfego externo não significa ausência de trabalho dos processos. O coletor da saga indicou disponibilidade na coleta final.

Na janela de ociosidade, o Loki registrou 1.298 linhas do Billing, 225 da Execução e 226 do OS Service.

Uma consulta posterior por container usou um recorte de dez minutos e encontrou 1.084 linhas do MongoDB no Billing. Dessas, 40 eram mensagens de autorização esperadas do exporter sobre `shardIdentity`; não houve linhas `Connection accepted`/`Connection ended`. Os totais inicial e por container foram obtidos em instantes distintos e não são diretamente comparáveis. A consulta de logs da aplicação com nível error/critical retornou vazia.

Após a observação, `scripts/ci/smoke-servicos.sh` passou novamente e a varredura de `reports/e2e` não encontrou segredos.

## Dashboards e histórico

Os nove dashboards provisionados foram abertos no Grafana anônimo como Viewer, todos com a mesma janela fixa na URL (`from` e `to`): de 24/10/2026, 14:40:00 UTC, antes da primeira execução do `make demo`, a 16:51:00 UTC, cerca de três minutos depois do fim da última, quando os orçamentos sem decisão dela já tinham vencido. Com a janela fixa, os painéis de período usam o mesmo `$__range` e os de "agora" leem o mesmo instante, então o número que aparece em dois prints é o mesmo nos dois. As capturas são de 16:52:53 a 16:53:37 UTC, na ordem Atendimento, Orçamentos, Pagamentos, Execução, Saga, Mensageria, Serviços, Bancos e Plataforma, e estão no [Anexo A, A7](../entrega-fase-4.md#a7--dashboards-do-grafana).

O kind foi criado em 24/10/2026, às 14:36 UTC, só para estas capturas: o Prometheus começou vazio, e os dados vêm das seis execuções abaixo. A plataforma usa o overlay `kind` (com Grafana, Loki e o PVC do Prometheus) e os serviços, o `kind-ci` (o orçamento vence em 72 s), como no ensaio de 19/10: a combinação mantém o Grafana e roda os mesmos cenários do CI. A subida foi `make kind-up deploy`, `scripts/ci/implantar-servicos.sh --overlay kind-ci` com os três serviços e `scripts/ci/smoke-servicos.sh`, que passou nos três antes da primeira execução.

| Repositório | Commit (`main` de 24/10/2026) |
|---|---|
| Plataforma | `5eff2a70fd2c92f0f4aecd07bfd182b35be666a3` |
| OS Service | `9711cbfc35aa04d35a995d1ca936c91bd8e0d290` |
| Billing Service | `8fada820b5241cf4c2a2bd2902cf47a187edefa7` |
| Execution Service | `16903b6e8e08671fbbc890da3197e56eb5f67a33` |

O `make demo` rodou seis vezes, com cerca de 25 minutos entre os inícios, e passou em todas:

| Execução | Início (UTC) | Fim (UTC) | Duração | Resultado |
|---|---|---|---|---|
| 1 | 14:40:39 | 14:42:42 | 121,45 s | 6 aprovados, 11 não selecionados |
| 2 | 15:05:44 | 15:07:42 | 117,81 s | 6 aprovados, 11 não selecionados |
| 3 | 15:31:05 | 15:33:04 | 118,93 s | 6 aprovados, 11 não selecionados |
| 4 | 15:56:06 | 15:58:04 | 117,08 s | 6 aprovados, 11 não selecionados |
| 5 | 16:21:07 | 16:23:10 | 122,39 s | 6 aprovados, 11 não selecionados |
| 6 | 16:46:12 | 16:48:07 | 113,77 s | 6 aprovados, 11 não selecionados |

Início e fim são os do comando, e a duração é a da linha de resultado do pytest; os logs ficam fora do repositório. Nenhum pod reiniciou na janela, e a memória do nó do kind ficou entre 2,98 e 3,69 GiB. Os dois painéis por dia, "Volume diário de OS" (Atendimento) e "Faturamento por dia" (Pagamentos), ficam sem barra: a barra de um dia só aparece às 00:00 UTC do dia seguinte, depois da captura, e o [print do volume diário](../../../../observabilidade/README.md#evidências) pede dias fechados; as barras de 19 a 22/10 dos dois estão nos prints de 22/10 do [Atendimento](grafana-atendimento-2026-10-22.png) e dos [Pagamentos](grafana-pagamentos-2026-10-22.png), de um kind anterior. Depois da última execução, o `make paineis` achou série nas 47 consultas de painel de negócio: ele roda cada expressão como consulta instantânea, e as dos dois painéis por dia, de `[1d]`, devolvem 1 série com o total das últimas 24 h (a mesma consulta deu 36 OS e R$ 3.830,97 às 16:51 UTC), enquanto o painel, de passo de 1 d, só mostra o dia depois de fechado e por isso fica vazio.

Os prints de 22/10, de outro kind e de outra janela, mostravam o p90 de 54 s nos Orçamentos e o p95 de 4,75 s na Saga, que eram o primeiro balde dos histogramas de então (baldes novos no [Billing #30](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-billing-service/pull/30) e no [OS #32](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-os-service/pull/32), e o p90 só com 10 decisões ou mais no [platform #41](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-platform/pull/41)), e 8 estornos no OS contra 6 no Billing, perda atribuída ao consumidor do Billing derrubado antes da raspagem (a espera entrou no [platform #43](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-platform/pull/43)). Dos nove de 22/10, só o do Atendimento e o dos Pagamentos continuam no repositório, só com link no documento, pelas quatro barras do volume diário e do faturamento por dia (de 19 a 22/10); os outros números deles são dessa janela e não se comparam com os de 24/10.

### Consultas de conferência

Cada consulta rodou no Prometheus do kind como instantânea em 16:51:00 UTC, o fim da janela, com `$__range` igual à janela inteira (`7860s`), como o Grafana faz nos painéis de período.

| O que confere | Consulta | Resultado |
|---|---|---|
| p90 do tempo até a decisão (painel "Tempo até a decisão" de Orçamentos) | `histogram_quantile(0.9, sum by (le, decisao) (increase(pytstop_orcamentos_tempo_decisao_segundos_bucket[$__range]))) and on (decisao) (sum by (decisao) (increase(pytstop_orcamentos_tempo_decisao_segundos_count[$__range])) >= 10)` | aprovado: 1,78 s. Das 24 decisões, 13 caíram no balde de 0,5 a 1 s e 11 no de 1 a 2 s (`sum by (le, decisao) (increase(pytstop_orcamentos_tempo_decisao_segundos_bucket[$__range]))`); com o primeiro balde em 60 s daria 54 s |
| Média do tempo até a decisão | `sum by (decisao) (increase(pytstop_orcamentos_tempo_decisao_segundos_sum[$__range])) / sum by (decisao) (increase(pytstop_orcamentos_tempo_decisao_segundos_count[$__range]))` | aprovado: 774 ms; recusado: sem valor (nenhuma recusa) |
| p95 da duração por etapa (painel "Duração por etapa (p95)" da Saga) | `histogram_quantile(0.95, sum by (le, etapa) (increase(pytstop_saga_etapa_duracao_segundos_bucket[$__range])))` | de 47,5 ms (`aguardando_reserva` e `aguardando_agendamento`) a 111 s (`aguardando_decisao`, que inclui os orçamentos vencidos em 72 s); nenhuma etapa em 4,75 s. Os dois extremos e o p90 de 1,78 s da primeira linha são interpolação dentro do balde, não valor medido: 47,5 ms é 0,95 x 50 ms, o primeiro balde, e as saídas das duas etapas foram todas abaixo de 50 ms (médias de 26 e 27 ms); 111 s fica acima do prazo de 72 s porque o balde vai de 60 a 120 s (12 das 36 saídas estão nele, e a média da etapa é 25 s); o p90 cai no balde de 1 a 2 s, com média de 774 ms |
| `EstornarPagamento` processados pelo consumidor | `sum by (namespace) (increase(pytstop_mensagens_consumidas_total{tipo="EstornarPagamento", resultado="processada"}[$__range]))` | `pytstop-billing`: 6,13 |
| Estornos por motivo, contados no Billing (painel 4 de Pagamentos) | `sum by (motivo) (increase(pytstop_pagamentos_estornados_total[$__range]))` | `compensacao`: 6,13; `pagamento_apos_encerramento`: 0 |
| `PagamentoEstornado` publicados | `sum by (namespace) (increase(pytstop_mensagens_publicadas_total{tipo="PagamentoEstornado"}[$__range]))` | `pytstop-billing`: 6,01 |
| `PagamentoEstornado` que o OS consumiu (Estornadas, painel 3 de Pagamentos) | `sum by (namespace, resultado) (increase(pytstop_mensagens_consumidas_total{tipo="PagamentoEstornado"}[$__range]))` | `pytstop-os`, `processada`: 6,00; `duplicada`, `ignorada`, `retry` e `dlq`: 0 |

Os quatro contadores de estorno dão 6, um por execução, e o do Billing por motivo fecha com o do OS. O `increase()` estende a série de cada pod que sai antes do fim da janela meio intervalo de raspagem (7,5 s) além da última amostra, e a API e o consumidor do Billing trocam de pod a cada execução (os cenários de resiliência os param), então cada pod é uma série curta e as contagens vêm um pouco acima do inteiro: 0,5% a mais nas séries de 25 minutos e de 6% a 10% na primeira de cada processo, que tem uns dois minutos dentro da janela. Os painéis de contagem mostram sem casas decimais; os de dinheiro, não (ver Pagamentos abaixo).

### Como os números dos prints fecham

Notas de cada print do [Anexo A, A7](../entrega-fase-4.md#a7--dashboards-do-grafana). O PDF traz Atendimento, Orçamentos, Pagamentos, Execução e Serviços; Saga, Mensageria, Bancos e Plataforma ficam no repositório, com o link no documento. Cada execução do `make demo` abre 6 OS, uma por cenário: o caminho feliz até a entrega, a falta de peça, o cancelamento com estorno, o cancelamento recusado com 409 depois do início da execução e os dois de resiliência (consumidor e API do Billing parados), cujos orçamentos ficam sem decisão e vencem.

- **Atendimento.** 36 OS abertas, 6 por execução. O funil (36 diagnósticos concluídos, 36 orçamentos gerados, 24 aprovados, 18 pagamentos confirmados e 6 execuções finalizadas) lê os mesmos contadores dos Orçamentos e dos Pagamentos, no mesmo instante, e dá os mesmos números. "OS por status agora" não mostra "Entregue" nem "Cancelada": as 6 OS que finalizaram a execução já foram entregues, e por isso "Finalizada" é 0; as 6 de "Em execução" são as do cenário do 409, que termina ali de propósito, uma por execução. Desfecho: 6 sagas concluídas e 24 compensadas, 12 por orçamento expirado, 6 por falta de peça e 6 por cancelamento do atendente. O volume diário fica sem barra (as quatro de 19 a 22/10 estão no [print de 22/10](grafana-atendimento-2026-10-22.png)).
- **Orçamentos.** 36 gerados, 24 aprovados, 12 expirados e nenhum recusado, porque o `make demo` não tem o cenário da recusa; 67% é 24 de 36. O p90 dos aprovados (1,78 s) sai da distribuição, ao lado da média de 774 ms (consultas acima), e a média dos recusados fica sem valor. "Aguardando decisão agora" é 0: os orçamentos da última execução já tinham vencido no fim da janela.
- **Pagamentos.** 18 cobranças abertas, 18 pagas e 6 estornadas, nenhuma recusada nem expirada. Os 6 de "Estornos: compensacao", contados no Billing, fecham com as 6 estornadas, que o OS recebeu, e com os dois contadores de mensagem das consultas acima. Cada pagamento é de R$ 210,00 (um serviço de R$ 120,00 e duas peças de R$ 45,00): os 18 somam R$ 3.780,00 e os 6 estornos, R$ 1.260,00, e o painel mostra R$ 3.835,35, R$ 1.286,35 e R$ 2.549,00 pelo acréscimo do `increase()` descrito acima (as 6 séries da API do Billing, que conta o pagamento, e as 6 do consumidor, que conta o estorno). "Faturamento por dia" fica sem barra, como o volume diário (as quatro de 19 a 22/10 estão no [print de 22/10](grafana-pagamentos-2026-10-22.png)).
- **Execução e estoque.** As 6 OS em execução são as mesmas do Atendimento. A espera média é de 8,59 s até o diagnóstico concluído e de 202 ms na fila de execução. São 18 reservas atendidas (caminho feliz, estorno e 409, três por execução) e 6 recusadas (a falta de peça). Os códigos `SRV-E2E-<execução>-<n>` e `PEC-E2E-<execução>-<n>` de "Tempo de execução por tipo de serviço" e "Peças em falta" são os catálogos que o E2E cria em cada cenário (o serviço no Billing, a peça no estoque da Execução; [E2E da saga](../../../e2e-da-saga.md)): uma barra por execução.
- **Saga.** As 6 sagas em `em_execucao` sobem um degrau por execução em "Sagas ativas por etapa", e a mais antiga tem 2,16 h. "Iniciadas e finalizadas por hora" soma a última hora em cada ponto, então mostra 6, 12 ou 18 iniciadas conforme a hora contenha uma, duas ou três execuções. O p95 por etapa é o da tabela acima: 24 s em `aguardando_orcamento` é o consumidor do Billing parado por 20 s, e 51 s em `aguardando_diagnostico`, a API do Billing parada até o circuito fechar. Nenhum reenvio nem prazo esgotado, e o `prazos` tinha rodado havia 18 s no OS e 4 s no Billing no fim da janela.
- **Mensageria.** Seis rajadas de mensagens publicadas e consumidas, uma por execução. "Retry por nível" fica vazio ("No data"), porque não houve retry, e nenhuma mensagem foi para a DLQ; a outbox volta a zero depois de cada execução.
- **Serviços.** Requisições em seis rajadas. Os cinco picos de 5xx, da segunda execução em diante, são o cenário da API do Billing parada: o circuito da Execução abre e a conclusão do diagnóstico responde 503 duas vezes por execução até o Billing voltar. A primeira execução não deixa pico porque a série do 503 dessa rota nasce na primeira resposta, com as duas já contadas, e o `rate()` só mede o que muda entre duas raspagens. "Borda: 401, 403 e 429" fica vazio (nenhuma resposta dessas no período), e o Mercado Pago fica em zero porque o kind usa o simulador.
- **Bancos.** Exporters no ar nos três bancos e seis rajadas de transações; no fim da janela, 9,05 MiB no PostgreSQL do OS, 8,19 MiB no da Execução e 185 KiB no MongoDB do Billing, com 336 documentos.
- **Plataforma.** A mensagem pronta em `billing.comandos`, uma por execução, é a do cenário do consumidor do Billing parado por 20 s. As três DLQs ficam em zero, cada fila de trabalho com um consumidor, e os 18 alvos do Prometheus no ar.

## Alertas e recuperação

O consumidor do Billing foi pausado de `03:54:01Z` a `03:58:01Z`, com restauração automática da única réplica e rollout concluído às `03:58:06Z`. A regra provisionada `pytstop-fila-sem-consumidor` ficou em Firing para `queue=billing.comandos` às `03:56:30Z` e voltou a Normal às `03:58:30Z`. As outras duas filas ficaram normais nessa regra. As capturas de [disparo](alerta-fila-disparado-2026-10-19.png) e [recuperação](alerta-fila-recuperado-2026-10-19.png) registram a transição real. O smoke dos três serviços passou novamente após a restauração.

As falhas deliberadas dos cenários também podem produzir alertas de circuito, 5xx e compensação; esses estados não são prova de indisponibilidade espontânea. Nenhuma regra, limiar ou política de rede foi alterada para gerar o alerta.

## Saída de rede do notificador

A prova operacional confirmou a política já existente: o notificador alcança o Mailpit na porta 1025 e recebe timeout ao tentar o RabbitMQ na porta 5672. A API do OS também alcança o Mailpit: isso corresponde ao limite documentado de que somente o notificador tem política de saída, enquanto o Mailpit da demonstração não tem política de ingresso. Nenhuma proteção foi alterada para essa conferência. As conexões foram abertas sem enviar mensagens SMTP ou AMQP.

Em `2026-10-19T10:39:04Z` a `10:39:18Z`, o smoke permanente atualizado passou para os três serviços no mesmo contexto preservado. A fonte do script é `3a32e50a8ee854b93daf423f7906332189849dc5`, SHA256 `606709fd30d1294acc1c514806974403f9111c96e8a132ed9a86425c617b86a4`; os quatro commits implantados continuam sendo os da tabela deste relatório. A identidade da política `notificador-saida` foi conferida antes da execução. Isso comprova o verificador novo sobre o runtime identificado, sem atribuir aos serviços uma implantação de commits posteriores.

Comando: `KUBE_CONTEXT=kind-pytstop-p4-codex CLUSTER=pytstop-p4-codex scripts/ci/smoke-servicos.sh`. Resultado: saída 0; saúde, borda, réplicas, métricas, autenticação local dos PostgreSQL e isolamento dos bancos aprovados nos três serviços. As três etapas adicionais do OS registraram:

| Origem e destino TCP | Resultado |
|---|---|
| API do OS Service para RabbitMQ:5672 | Conexão aceita; controle positivo |
| Notificador para Mailpit:1025 | Conexão aceita |
| Notificador para o mesmo RabbitMQ:5672 | Timeout de conexão de 3 s; bloqueio aprovado com controle válido |

As sondas só abriram e fecharam conexões TCP, sem autenticação ou payload SMTP/AMQP. Recusa, erro DNS, falta de pod, falha de transporte e prazo externo não aprovam a negativa. O teste operacional não amplia a política: o acesso da API ao Mailpit permanece como limite aceito da demonstração.

## O que falta

- Executar a prova real do Mercado Pago e observar a ociosidade também nesse modo.
- Atualizar os quatro commits e as provas depois das próximas integrações; conferir o pacote e o PDF sobre as tags finais.
