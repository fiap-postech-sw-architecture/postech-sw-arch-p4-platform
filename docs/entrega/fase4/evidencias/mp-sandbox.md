# Mercado Pago na sandbox — 15/11/2026

Estado: a integração do Billing com o Mercado Pago real foi exercitada na sandbox do Checkout Pro, com credenciais de teste, contas de teste (Vendedor e Comprador, do Brasil) e o cartão de teste. Dois cenários passaram e o do estorno terminou como falha esperada, pela limitação da sandbox descrita abaixo. Nenhum dinheiro real se moveu.

Comando: `make mp-sandbox`, no kind local `kind-pytstop-p4` (overlay `kind`), em 2026-11-15, de 03:16 a 03:21 UTC. Resultado do pytest: `2 passed, 1 xfailed`; varredura de segredos da pasta: `nenhum segredo`.

O cluster rodava os commits da `main` dos quatro repositórios, conferidos pela tag de cada imagem no cluster: plataforma `94328602092f67216de9d6bfed139f328d9e35de`, OS Service `4a0cec2088984d9fa3eb8f143a550dcbbce9e617`, Billing `86599669e3ef1bdbf83444aea2b188810b51c3f6` e Execução `b3451d32465801fd74c8b17e58a9021bdfa092c5`. Os três serviços e a plataforma tinham o CD da `main` aprovado nesses commits.

| Cenário | Resultado | O que o Mercado Pago real mostrou |
|---|---|---|
| Pagamento no checkout é confirmado pela conciliação | passou (122 s) | A preferência criada pelo Billing (`POST /checkout/preferences`, 201); o pagamento `189744991570` com `approved`, R$ 210,00, `external_reference` igual ao `pagamento_id` do Billing; a OS seguiu para `aguardando_execucao` |
| Cancelar a OS depois do pagamento estorna o valor | falha esperada (116 s) | O pagamento `189745145564` aprovado; o `POST /v1/payments/{id}/refunds` do Billing voltou 401, causa 7 ("Unauthorized use of live credentials"); o Billing respondeu `EstornoDePagamentoFalhou`, e a saga parou em `falha_na_compensacao` com `estorno_recusado`, sem marcar o pagamento como estornado |
| Cancelar a OS sem pagar fecha a cobrança e expira a preferência | passou (24 s) | O `PUT /checkout/preferences/{id}` do Billing aceito; a consulta da preferência, segundos depois, com `expires` verdadeiro e `expiration_date_to` antecipado para 03:21:34 UTC, 1 minuto depois do cancelamento; saga `compensada` e pagamento `CANCELADO` |

Nos três cenários, o trace no Jaeger tem os três serviços e o span CLIENT do Billing para `api.mercadopago.com`.

## O que a execução prova

- **Integração real (RF-034).** O Billing cria a cobrança no Mercado Pago, o comprador de teste paga no checkout real e o Billing confirma o pagamento pela conciliação do processo `prazos` (`GET /v1/payments/search` a cada 30 s). A sandbox não envia webhook para pagamento de teste, e o resumo registra isso.
- **Registro e verificação do pagamento (RF-032, RF-033).** O pagamento aparece `approved` no Mercado Pago, no valor e na moeda do orçamento e com a referência do Billing; a OS avança só depois da confirmação.
- **Compensação com o provedor real (RN-023).** Na cobrança aberta, o cancelamento antecipa a expiração do checkout no Mercado Pago para 1 minuto à frente. No estorno recusado, a saga não fingiu sucesso: parou na compensação, à espera do operador, como manda a [RFC-004, seção 4.7](../../../arquitetura/rfc/fase4/rfc-004-microsservicos-saga.md#47-falha-na-compensação-e-retomada).
- **Observabilidade da chamada externa (RNF-046).** O span CLIENT Billing → Mercado Pago, que o simulador não produz, aparece nos três traces.

## O que a execução achou e o que mudou

As execuções de 14/11/2026, antes desta, acharam três pontos que o simulador não pega:

1. **`live_mode=true` em pagamento de teste.** No Checkout Pro o teste roda no ambiente de produção com contas fictícias, e o pagamento de teste vem com `live_mode=true`. A prova de que é teste passou a ser o dono do token (`GET /users/me` com a tag `test_user`), conferido antes de qualquer cobrança ([platform #55](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-platform/pull/55)).
2. **Fechar o checkout com data no instante atual.** O Mercado Pago respondia 400 `invalid_date`. O Billing passou a fechar com a expiração 1 minuto à frente ([Billing #45](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-billing-service/pull/45)), e o cenário da cobrança aberta passou a provar que o provedor aceita a expiração antecipada.
3. **Estorno pela API bloqueado na sandbox.** O Mercado Pago recusa o estorno com as credenciais de teste da aplicação e com as de produção da conta Vendedor de teste, e a conta de teste não pode ter credenciais de teste. O cenário do estorno aceita só essa recusa exata como falha esperada; qualquer outra reprova ([platform #55](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-platform/pull/55)).

O detalhe de cada ponto está em [Mercado Pago na sandbox](../../../mercado-pago-na-sandbox.md#por-que-live_modetrue-não-reprova-com-conta-de-teste).

## O que fica provado em outro lugar

O estorno completo, a compensação que falha e a retomada pelo operador estão no E2E da saga com o simulador ([BDD](bdd-resumo.md) e o [BDD de componente do OS Service](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-os-service/blob/entrega-fase-4/tests/bdd/saga_atendimento.feature)). Pela sandbox, o estorno só pode ser feito pelo painel do Mercado Pago, seguido da retomada da compensação, como descreve o [runbook da saga](../../../operacao/runbook-saga.md#2-falha-na-compensação-e-retomada).

## Arquivos

Cópias exatas da pasta `reports/mp-sandbox` da execução, depois da varredura de segredos (`python -m e2e.varredura`, de novo nesta pasta):

- [resumo.md](mercadopago-sandbox/resumo.md): cada cenário, as transições observadas, os campos permitidos do Mercado Pago e as observações;
- [evidencia.json](mercadopago-sandbox/evidencia.json): o mesmo em JSON, com o status do pagamento no Billing ao fim de cada cenário (`CONFIRMADO` no do estorno recusado);
- os traces higienizados de cada cenário: [pagamento](mercadopago-sandbox/trace-pagamento-5a50b705314ddcaf8f243b03e930b3dd.json), [estorno](mercadopago-sandbox/trace-estorno-22bb9e4a1647631a35599aa878779c27.json) e [cobrança aberta](mercadopago-sandbox/trace-cobranca-aberta-7602cffe07f1b6fdc2d4102fcdcff337.json).

O `resumo.md` anota a cobrança aberta como "preferência expirada": o roteiro aceita a data de expiração com até 5 minutos de folga de relógio, e na hora da consulta (03:20:38 UTC) ela ainda estava 56 segundos à frente. O que fica provado é a expiração antecipada, e não que o checkout já recusava pagamento naquele instante.

Do Mercado Pago entram só `id`, `status`, `transaction_amount`, `currency_id`, `date_approved`, `external_reference` e `live_mode`, e da preferência, só o uuid, sem o User ID da conta vendedora. Nenhum dado do pagador, do cartão ou das credenciais.
