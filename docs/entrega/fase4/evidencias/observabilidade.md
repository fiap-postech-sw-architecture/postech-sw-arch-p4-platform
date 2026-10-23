# Ensaio local de observabilidade — 19/10/2026

Estado: prova parcial. O fluxo local, o trace distribuído, a ociosidade e a saúde posterior foram exercitados, e os nove dashboards foram capturados em 22/10/2026 (23/10 UTC), com o Prometheus guardando dados desde 19/10 ([Dashboards e histórico](#dashboards-e-histórico)). A chamada HTTP ao Mercado Pago real continua pendente.

## Ambiente e commits

Cluster próprio `pytstop-p4-codex`, contexto `kind-pytstop-p4-codex`, criado em 19/10/2026. A plataforma usa o overlay `kind`, com PVC do Prometheus e retenção de 15 dias. Os serviços usam `kind-ci`, com os prazos de negócio do ensaio; a combinação mantém o Grafana e a persistência locais e permite exercitar os mesmos cenários do CI.

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

Os nove dashboards provisionados foram abertos no Grafana anônimo como Viewer. As consultas de negócio produziram séries no Prometheus. Em 19/10, os painéis de volume diário e faturamento diário ainda não tinham barra, porque dependem da primeira meia-noite UTC depois do início da coleta, conforme as descrições deles.

`make demo CLUSTER=pytstop-p4-codex` passou em 19/10: seis cenários, 11 não selecionados, 111,11 s; blocos 1 e 2 em 19 s e 92 s. Os relatórios também passaram pela varredura. Esse é o primeiro dia real; não foram criadas amostras retroativas nem alterados timestamps.

O cluster e o PVC do Prometheus ficaram no ar até a captura, e o `make demo` rodou sete vezes entre 19 e 23/10:

| Dia (UTC) | Início | Fim | Duração | Resultado |
|---|---|---|---|---|
| 19/10/2026 | 03:50:58 | 03:52:50 | 111,11 s | 6 aprovados, 11 não selecionados |
| 20/10/2026 | 00:03:11 | 00:05:05 | 113,54 s | 6 aprovados, 11 não selecionados |
| 20/10/2026 | 12:02:54 | 12:04:47 | 112,27 s | 6 aprovados, 11 não selecionados |
| 21/10/2026 | 00:14:26 | 00:16:15 | 108,62 s | 6 aprovados, 11 não selecionados |
| 22/10/2026 | 00:11:35 | 00:13:27 | 111,08 s | 6 aprovados, 11 não selecionados |
| 22/10/2026 | 12:02:33 | 12:04:25 | 110,79 s | 6 aprovados, 11 não selecionados |
| 23/10/2026 | 00:08:31 | 00:10:21 | 109,89 s | 6 aprovados, 11 não selecionados |

Início e fim são a criação e a última escrita do log de cada execução, que guarda a saída do pytest; a duração é a da linha de resultado do pytest, e início mais duração dá o fim com diferença de até 2 s. Os logs ficam fora do repositório. A forma das execuções está nos prints: no painel "Iniciadas e finalizadas por hora" da Saga, cada execução é um pico de 6 OS iniciadas, por volta de 00:00 UTC em 20, 21, 22 e 23/10 e de 12:00 UTC em 20 e 22/10; o pico de 19/10, de 17 OS, inclui o E2E da subida do cluster e a primeira execução.

Os nove dashboards foram capturados em 23/10/2026, a partir das 00:10 UTC (22/10, 21:10 em Brasília), logo depois da última execução, e estão no [Anexo B, B7](../entrega-fase-4.md#b7--dashboards-do-grafana). O Prometheus tem dados desde 19/10, 03:16 UTC, com lacunas de quando o computador dormiu e de um reinício dos pods em 21/10, por volta de 01:45 UTC, por falta de memória da VM do Docker. O painel de volume diário tem quatro barras (19 a 22/10). Atendimento, Orçamentos, Pagamentos, Execução e Saga mostram de 19/10, 00:00 UTC, até a captura; Mensageria, Serviços, Bancos e Plataforma, de 00:03:31 a 00:12:21 UTC de 23/10, em volta da última execução, porque numa janela de quatro dias a rajada de dois minutos fica achatada.

### Como os números dos prints fecham

Notas de cada print do [Anexo B, B7](../entrega-fase-4.md#b7--dashboards-do-grafana). O PDF traz Atendimento, Orçamentos, Pagamentos, Execução e Serviços; Saga, Mensageria, Bancos e Plataforma ficam no repositório, com o link no documento.

- **Atendimento.** As quatro barras do volume diário somam 47 OS, de dias fechados: 19/10 inclui o E2E da subida do cluster, e 20/10 e 22/10 têm duas execuções do `make demo` cada uma. As 6 OS do `make demo` de 23/10 estão só no funil (53). "OS por status agora" mostra só as OS que ainda não terminaram, sem "Entregue" nem "Cancelada": as 10 que finalizaram a execução já foram entregues, e por isso "Finalizada" é 0. As 8 OS em "Em execução" são as do cenário do 409, que termina ali de propósito (o cancelamento depois do início da execução responde 409): uma por execução do `make demo` (sete) e a do E2E de 19/10.
- **Orçamentos.** O Atendimento foi capturado 6 s antes, às 00:10:38 UTC, e a última OS do `make demo` mudou de estado entre as duas capturas: lá o funil tem 52 orçamentos gerados e uma OS em diagnóstico; aqui, 53 gerados e 2 esperando a decisão. A taxa de aprovação de 69% é 35 de 51, entre aprovados, recusados e expirados.
- **Pagamentos.** O total das quatro barras de "Faturamento por dia" (R$ 4.880,91) é menor que o bruto (R$ 5.481,47) porque a barra de um dia só aparece depois da meia-noite UTC que o fecha: o que o `make demo` pagou em 23/10 está no bruto e ainda não tem barra.
- **Execução e estoque.** As 8 OS em execução são as mesmas do Atendimento.
- **Saga.** As sagas em `em_execucao` são as mesmas 8 OS do cenário do 409: "Sagas ativas por etapa" sobe de 2 em 19/10 (o E2E e a primeira execução) a 8 em seis degraus, um por execução do `make demo` de 20 a 23/10, e a mais antiga, de 19/10, tem 3,86 dias. O processo `prazos` rodou há 12 s no OS e há 8 s no Billing, no instante da captura.
- **Mensageria.** A janela é de 23/10, de 00:03:31 a 00:12:21 UTC, com o JSON da `main` ([platform #34](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-platform/pull/34)). "Retry por nível" aparece vazio ("No data") porque não houve retry no período.
- **Serviços.** O pico de 5xx e a queda da taxa de sucesso, por volta de 00:10 UTC, são do cenário da API do Billing parada: o circuito abre e a conclusão do diagnóstico responde 503 até o Billing voltar. O Mercado Pago fica em zero porque o kind usa o simulador.
- **Bancos.** Mesma janela da Mensageria; os tamanhos são 9,32 MiB no OS, 8,43 MiB na Execução e 272 KiB no Billing.
- **Plataforma.** Mesma janela; a mensagem pronta em `billing.comandos`, por volta de 00:09:30 UTC, é a do cenário do consumidor do Billing parado por 20 s.

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
