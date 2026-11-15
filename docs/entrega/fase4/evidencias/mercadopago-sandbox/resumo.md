# Evidência do Mercado Pago na sandbox

- Modo: **real (credenciais de teste do Mercado Pago)**
- Data: 2026-11-15 03:20 UTC
- Cluster: `kind-pytstop-p4`
- `notification_url`: `https://example.com/api/v1/webhooks/mercadopago` (a notificação não foi exercitada: a sandbox não envia webhook)

> A sandbox do Mercado Pago não envia webhook (notificação) para pagamento de teste. A confirmação do pagamento veio da conciliação do processo `prazos` do Billing, que consulta `GET /v1/payments/search?external_reference=` a cada 30 s, e não de um webhook.

| Cenário | Resultado | Duração (s) | `ordem_id` | `pagamento_id` | Pagamento no Mercado Pago |
|---|---|---|---|---|---|
| Pagamento no checkout do Mercado Pago é confirmado pela conciliação | passou | 122 | `ec0bf2a0-6a88-4e98-b077-352684b8e586` | `d8f25ffb-ed82-4423-adf3-76767020124a` | `189744991570` |
| Cancelar a OS depois do pagamento estorna o valor no Mercado Pago | falha esperada (limitação da sandbox) | 116 | `56b1e5b1-d6fb-429f-a008-f42c5592502a` | `d06b67fd-4af3-4876-b55d-b388f3ef50d0` | `189745145564` |
| Cancelar a OS sem pagar fecha a cobrança e expira a preferência no Mercado Pago | passou | 24 | `1071b194-d179-485f-b759-ed69e4743584` | `7f0cd0d9-0348-40d3-8104-f5aa62e905b5` | `-` |

## Pagamento no checkout do Mercado Pago é confirmado pela conciliação

- Resultado: **passou**, em 122 s
- `ordem_id`: `ec0bf2a0-6a88-4e98-b077-352684b8e586`
- `pagamento_id` (Billing): `d8f25ffb-ed82-4423-adf3-76767020124a`
- Id do pagamento no Mercado Pago: `189744991570`

Transições observadas (hora UTC, do serviço que registrou):

| Hora | O que aconteceu |
|---|---|
| 03:17:03 | OS: (abertura) -> recebida (atendimento) |
| 03:17:03 | saga: abertura, envia SolicitarDiagnostico |
| 03:17:04 | saga: DiagnosticoIniciado |
| 03:17:04 | OS: recebida -> em_diagnostico (execucao) |
| 03:17:04 | saga: DiagnosticoConcluido, envia GerarOrcamento |
| 03:17:05 | saga: OrcamentoGerado |
| 03:17:05 | OS: em_diagnostico -> aguardando_aprovacao (billing) |
| 03:17:06 | saga: OrcamentoAprovado, envia ReservarPecas |
| 03:17:06 | saga: PecasReservadas, envia SolicitarPagamento |
| 03:17:06 | OS: aguardando_aprovacao -> aguardando_pagamento (execucao) |
| 03:17:06 | Billing: cobrança criada (SOLICITADO) |
| 03:17:08 | saga: PagamentoSolicitado |
| 03:17:13 | script: cobrança criada no provedor; link do checkout pronto |
| 03:17:13 | script: link impresso; esperando o comprador de teste |
| 03:18:03 | Billing: pagamento CONFIRMADO |
| 03:18:04 | saga: PagamentoConfirmado, envia AgendarExecucao |
| 03:18:04 | OS: aguardando_pagamento -> aguardando_execucao (billing) |
| 03:18:04 | saga: ExecucaoAgendada |
| 03:18:07 | script: Billing mostra o pagamento CONFIRMADO |
| 03:18:08 | script: Mercado Pago: approved, live_mode=True |

- Trace no Jaeger: `5a50b705314ddcaf8f243b03e930b3dd`, arquivo `trace-pagamento-5a50b705314ddcaf8f243b03e930b3dd.json`; serviços: billing-service, execution-service, os-service; span CLIENT do Billing para api.mercadopago.com: sim

Do Mercado Pago (só estes campos):

- `id`: `189744991570`
- `status`: `approved`
- `transaction_amount`: `210`
- `currency_id`: `BRL`
- `date_approved`: `2026-11-14T23:17:44.000-04:00`
- `external_reference`: `d8f25ffb-ed82-4423-adf3-76767020124a`
- `live_mode`: `True`

Observações:

- o Mercado Pago marcou o pagamento com `live_mode=true`, o esperado no Checkout Pro: o teste roda no ambiente de produção com contas fictícias, e o Access Token de teste é a credencial da conta Vendedor de teste. A natureza de teste foi provada pelo dono do token (`GET /users/me` com a tag `test_user`), conferido antes do pagamento


## Cancelar a OS depois do pagamento estorna o valor no Mercado Pago

- Resultado: **falha esperada (limitação da sandbox)**, em 116 s
- `ordem_id`: `56b1e5b1-d6fb-429f-a008-f42c5592502a`
- `pagamento_id` (Billing): `d06b67fd-4af3-4876-b55d-b388f3ef50d0`
- Id do pagamento no Mercado Pago: `189745145564`

Transições observadas (hora UTC, do serviço que registrou):

| Hora | O que aconteceu |
|---|---|
| 03:18:21 | OS: (abertura) -> recebida (atendimento) |
| 03:18:21 | saga: abertura, envia SolicitarDiagnostico |
| 03:18:22 | saga: DiagnosticoIniciado |
| 03:18:22 | OS: recebida -> em_diagnostico (execucao) |
| 03:18:23 | saga: DiagnosticoConcluido, envia GerarOrcamento |
| 03:18:24 | saga: OrcamentoGerado |
| 03:18:24 | OS: em_diagnostico -> aguardando_aprovacao (billing) |
| 03:18:25 | saga: OrcamentoAprovado, envia ReservarPecas |
| 03:18:25 | saga: PecasReservadas, envia SolicitarPagamento |
| 03:18:25 | OS: aguardando_aprovacao -> aguardando_pagamento (execucao) |
| 03:18:25 | Billing: cobrança criada (SOLICITADO) |
| 03:18:26 | saga: PagamentoSolicitado |
| 03:18:33 | script: cobrança criada no provedor; link do checkout pronto |
| 03:18:33 | script: link impresso; esperando o comprador de teste |
| 03:19:35 | Billing: pagamento CONFIRMADO |
| 03:19:35 | saga: PagamentoConfirmado, envia AgendarExecucao |
| 03:19:35 | OS: aguardando_pagamento -> aguardando_execucao (billing) |
| 03:19:35 | saga: ExecucaoAgendada |
| 03:19:39 | script: Billing mostra o pagamento CONFIRMADO |
| 03:19:40 | script: Mercado Pago: approved, live_mode=True |
| 03:19:40 | saga: cancelamento_solicitado, envia CancelarExecucao |
| 03:19:40 | saga: ExecucaoCancelada, envia EstornarPagamento |
| 03:19:43 | saga: EstornoDePagamentoFalhou |

- Trace no Jaeger: `22bb9e4a1647631a35599aa878779c27`, arquivo `trace-estorno-22bb9e4a1647631a35599aa878779c27.json`; serviços: billing-service, execution-service, os-service; span CLIENT do Billing para api.mercadopago.com: sim

Do Mercado Pago (só estes campos):

- `id`: `189745145564`
- `status`: `approved`
- `transaction_amount`: `210`
- `currency_id`: `BRL`
- `date_approved`: `2026-11-14T23:19:19.000-04:00`
- `external_reference`: `d06b67fd-4af3-4876-b55d-b388f3ef50d0`
- `live_mode`: `True`

Observações:

- o Mercado Pago marcou o pagamento com `live_mode=true`, o esperado no Checkout Pro: o teste roda no ambiente de produção com contas fictícias, e o Access Token de teste é a credencial da conta Vendedor de teste. A natureza de teste foi provada pelo dono do token (`GET /users/me` com a tag `test_user`), conferido antes do pagamento
- o Mercado Pago recusou o estorno pela API com 401, causa 7 ("Unauthorized use of live credentials"): a sandbox do Checkout Pro não aceita estorno pela API nem com as credenciais de teste da aplicação nem com as de produção da conta Vendedor de teste, e a conta de teste não pode ter credenciais de teste. O Billing pediu o estorno de verdade e, recusado, respondeu `EstornoDePagamentoFalhou`; a saga parou em `falha_na_compensacao` com `estorno_recusado`, sem marcar o pagamento como estornado. O estorno completo e a retomada da compensação estão provados no E2E com o simulador


## Cancelar a OS sem pagar fecha a cobrança e expira a preferência no Mercado Pago

- Resultado: **passou**, em 24 s
- `ordem_id`: `1071b194-d179-485f-b759-ed69e4743584`
- `pagamento_id` (Billing): `7f0cd0d9-0348-40d3-8104-f5aa62e905b5`
- Id do pagamento no Mercado Pago: -

Transições observadas (hora UTC, do serviço que registrou):

| Hora | O que aconteceu |
|---|---|
| 03:20:21 | OS: (abertura) -> recebida (atendimento) |
| 03:20:21 | saga: abertura, envia SolicitarDiagnostico |
| 03:20:22 | saga: DiagnosticoIniciado |
| 03:20:22 | OS: recebida -> em_diagnostico (execucao) |
| 03:20:23 | saga: DiagnosticoConcluido, envia GerarOrcamento |
| 03:20:24 | saga: OrcamentoGerado |
| 03:20:24 | OS: em_diagnostico -> aguardando_aprovacao (billing) |
| 03:20:25 | saga: OrcamentoAprovado, envia ReservarPecas |
| 03:20:25 | saga: PecasReservadas, envia SolicitarPagamento |
| 03:20:25 | OS: aguardando_aprovacao -> aguardando_pagamento (execucao) |
| 03:20:26 | Billing: cobrança criada (SOLICITADO) |
| 03:20:27 | saga: PagamentoSolicitado |
| 03:20:34 | script: cobrança criada no provedor; link do checkout pronto |
| 03:20:34 | saga: cancelamento_solicitado, envia EstornarPagamento |
| 03:20:35 | Billing: cobrança encerrada |
| 03:20:36 | saga: PagamentoCancelado, envia LiberarReserva |
| 03:20:36 | saga: ReservaLiberada, envia CancelarOrcamento |
| 03:20:37 | saga: OrcamentoCancelado, envia DescartarDiagnostico |
| 03:20:37 | saga: DiagnosticoDescartado |
| 03:20:37 | OS: aguardando_pagamento -> cancelada (saga) |
| 03:20:38 | script: Mercado Pago mostra a preferência expirada |

- Trace no Jaeger: `7602cffe07f1b6fdc2d4102fcdcff337`, arquivo `trace-cobranca-aberta-7602cffe07f1b6fdc2d4102fcdcff337.json`; serviços: billing-service, execution-service, os-service; span CLIENT do Billing para api.mercadopago.com: sim

Preferência do checkout no Mercado Pago:

- `id`: `432f13a6-e7c8-4ce9-89e3-54fa77c9c349`
- `expires`: `True`
- `expiration_date_to`: `2026-11-15T03:21:34.697000+00:00`


## Prints que você tira (o script não tira)

1. O checkout do Mercado Pago aberto na janela anônima, com o valor da cobrança (antes de pagar).
2. A tela de pagamento aprovado do Mercado Pago (cenários 1 e 2).
3. O terminal com o pagamento CONFIRMADO e a OS em `aguardando_execucao`.
4. No painel do Mercado Pago, na conta do Vendedor de teste: o pagamento aprovado e, depois do cancelamento, o estorno.
5. O trace de um cenário aberto no Jaeger (Search, aba "Upload", arraste o `trace-*.json`), com o span CLIENT do Billing para `api.mercadopago.com`.
6. O `resumo.md` desta pasta (já sem token nem dado do pagador).
7. Cuidado com os prints: cubra e-mail, nome, User ID e CPF das contas de teste, e nunca mostre a tela de Credenciais nem a de Webhooks.
8. Cuidado com os arquivos: anexe só o `resumo.md`, os `trace-*.json` e os prints, nunca o `junit.xml` (leva o nome da máquina), o `cucumber.json`, o `cenarios.json` nem a pasta inteira; antes de commitar, rode `python -m e2e.varredura <pasta>` e `gitleaks dir <pasta>`.
