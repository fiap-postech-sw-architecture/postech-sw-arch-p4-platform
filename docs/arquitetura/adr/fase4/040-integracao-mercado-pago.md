# Mercado Pago via Checkout Pro com webhook verificado e simulador para CI

> [↑ Raiz do projeto](../../../../README.md) · [↑ Arquitetura](../../README.md)

* Status: Aceita
* Data: 2026-10-06

## Contexto e Problema

O Billing Service responde por "Registro e verificação de pagamentos" e "Atualização do status da OS após pagamento" (l. 44-45; OS é a ordem de serviço), e o enunciado completa: "para a parte de pagamentos devemos nos integrar com o Mercado Pago. Acesse a documentação." (l. 47); ver [desafio-tech-fase-4.md](../../../requisitos/fase4/desafio-tech-fase-4.md).

A [gap analysis](../../../requisitos/fase4/gap-analysis-fase-4.md) traduz isso nos requisitos funcionais RF-032, RF-033 e RF-034, com as regras de negócio RN-025 (pagamento recusado ou expirado compensa a saga sem estorno, porque nada foi cobrado), RN-026 (cancelamento depois do pagamento e antes do início da execução estorna o pagamento), RN-028 (chave de idempotência nas chamadas ao provedor) e RN-029 (sem cancelamento depois do início da execução), e com o requisito não funcional RNF-055.

O p3 (código da fase 3, commit `08dcffe`) não tem pagamento: era não-objetivo do produto, e a busca por `pagamento`, `payment` e `mercado` não encontra nada (gap analysis, RF-032 e RF-034). O precedente mais próximo é o canal externo de decisão do orçamento, autenticado por HMAC (código de autenticação de mensagem com hash) a cada requisição ([ADR-021](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p3/blob/main/docs/arquitetura/adr/fase2/021-aprovacao-externa-orcamento.md)).

O pipeline de integração contínua (CI) e o kind rodam sem segredo externo e sem URL pública, e a credencial de teste depende de um passo humano: criar as contas de teste (vendedor e comprador) no painel do Mercado Pago, configurar Webhooks na aplicação e gravar `MP_ACCESS_TOKEN` e `MP_WEBHOOK_SECRET` como segredos da organização no GitHub.

Mercado Pago, webhooks e idempotência não estão no material. A prática de SAGA Pattern simula o provedor com um MockGateway, que confirma a cobrança por callback (Aula 05, Fig. 1 e 12), e a Aula 01 de Estrutura de Microsserviços põe o adaptador do provedor dentro do serviço dono (Fig. 2: o Paguei no serviço Pagamento).

**Como integrar o Billing ao Mercado Pago, com prova de que a integração real funciona, sem que o CI e os testes dependam de credencial e de URL pública?**

## Decisão

Checkout Pro, com confirmação por webhook verificado e por conciliação ativa, estado sempre lido da API do provedor e um port com dois adapters: o real e um simulador, usado no CI, no kind do CI, no compose e nos testes ponta a ponta (E2E).

### Estados do pagamento

`SOLICITADO` (preferência criada, checkout aberto), `CONFIRMADO`, `RECUSADO`, `EXPIRADO`, `CANCELADO` e `ESTORNADO`. Toda transição parte de um estado esperado e é gravada por atualização condicional no status, para que webhook, conciliação, expiração e compensação não disputem o mesmo pagamento.

### Fluxo

1. `SolicitarPagamento` cria o pagamento em `SOLICITADO`, com o valor do orçamento aprovado, e a preferência em `POST /checkout/preferences`, com os itens do orçamento, `external_reference = pagamento_id`, `notification_url` e a expiração do pagamento (`PAGAMENTO_VALIDADE_MINUTOS`, padrão 60). O `init_point` da resposta vira o `checkout_url` de `PagamentoSolicitado`.
2. O Mercado Pago notifica por webhook do tipo `payment` em `POST /api/v1/webhooks/mercadopago`. O Billing valida o `x-signature` (`ts=<ts>,v1=<hash>`): HMAC-SHA256 em hexadecimal do manifesto `id:<data.id>;request-id:<x-request-id>;ts:<ts>;` com `MP_WEBHOOK_SECRET`, comparado em tempo constante; par ausente sai do manifesto, como no validador do kit de desenvolvimento (SDK) oficial. O `data.id` vem da query string, como na documentação e no SDK.

   Não há janela sobre o `ts`: a documentação não a pede nem diz se o reenvio conserva o `ts`, e uma janela curta recusaria reenvios legítimos; a repetição não tem efeito porque o estado vem da consulta e a transição é condicional. Assinatura inválida recebe 401, e, sem `MP_WEBHOOK_SECRET` configurado, o webhook responde 503, como no p3.
3. O estado vem sempre de `GET /v1/payments/{id}`, nunca do corpo da notificação. O `external_reference` tem de apontar para um pagamento existente, com valor e moeda iguais aos registrados. `approved` leva a `CONFIRMADO` e publica `PagamentoConfirmado`. `rejected` é uma recusa, contada no campo `recusas`: o pagamento continua em `SOLICITADO`, e o cliente pode pagar de novo no mesmo checkout até a recusa de número `PAGAMENTO_MAX_RECUSAS` (padrão 3), quando o pagamento vira `RECUSADO` e publica `PagamentoRecusado`. Estados intermediários mantêm a espera. O webhook responde 200 dentro dos 22 s que o provedor espera; sem isso, ele reenvia em intervalos crescentes (15 min, 30 min, 6 h, 48 h).
4. Conciliação ativa: o processo `prazos` do Billing consulta, a cada 30 s, cada pagamento em `SOLICITADO` (`GET /v1/payments/search?external_reference=<pagamento_id>`) e aplica o mesmo caso de uso do webhook. Isso cobre notificação perdida e faz a integração real funcionar sem URL pública, inclusive num kind local com `MP_MODE=mercadopago`.
5. Expiração: o mesmo `prazos` vence pagamento e orçamento, com atualização condicional por status para não disputar com a decisão do cliente nem com o webhook, e publica `PagamentoExpirado` ou `OrcamentoExpirado`; a preferência carrega o mesmo limite. Com várias réplicas do `prazos`, a atualização condicional garante que só uma encerre cada registro.
6. Compensação: `EstornarPagamento` encerra o pagamento em qualquer estado ([ADR-035](035-saga-orquestrada.md)). Em `SOLICITADO`, cancela (`CANCELADO`), o checkout deixa de valer para o Billing, e a resposta é `PagamentoCancelado` (`evento.billing.pagamento_cancelado`). Em `CONFIRMADO`, o Billing consulta o pagamento no provedor e chama `POST /v1/payments/{id}/refunds` sem `amount` (estorno integral), com `X-Idempotency-Key: estorno-{pagamento_id}`, e publica `PagamentoEstornado` (motivo `compensacao`) ou, se o provedor recusar, `EstornoDePagamentoFalhou`, que leva a saga a `FALHA_NA_COMPENSACAO`. Se a consulta já mostrar o pagamento estornado, como depois de um estorno pelo painel numa intervenção manual, o Billing registra o estorno e publica `PagamentoEstornado` sem nova chamada. Pagamento já cancelado ou estornado republica o desfecho sem chamar o provedor (RN-028).
7. Aprovação depois do encerramento: `approved` para pagamento `CANCELADO`, `EXPIRADO` ou `RECUSADO` (o cliente pagou com o checkout ainda aberto, ou a notificação chegou depois do prazo) é estornado pelo próprio Billing, com a mesma chave, e publicado como `PagamentoEstornado` com motivo `pagamento_apos_encerramento`. A saga, em compensação ou encerrada, ignora o evento, e o caso aparece em `pytstop_pagamentos_estornados_total{motivo}` ([ADR-043](043-observabilidade-distribuida.md)).

### Dados do pagador

O Billing guarda da resposta do provedor só o que usa: id do pagamento no provedor, status e seu detalhe, valor, moeda e datas. `payer`, dados do cartão e qualquer outro dado pessoal são descartados antes de gravar e de logar. A eliminação de dados do titular (RF-015 do p3) continua no OS Service, com a anonimização da placa no Execution Service (contexto Execução, [ADR-037](037-banco-por-servico.md)), sem passo no Billing.

### Port, adapters e simulador

O port `GatewayPagamento` (criar cobrança, consultar, buscar por referência, estornar) fica na camada de aplicação do Billing.

- `MercadoPagoGateway` (httpx), coberto por teste de contrato com requisições e respostas da documentação: caminhos, headers (inclusive `X-Idempotency-Key`), corpos, códigos de status e o cálculo do `x-signature` ([ADR-041](041-estrategia-de-testes-e-qualidade.md)).
- `GatewayPagamentoSimulado`: o `checkout_url` aponta para `GET /simulador/checkout/{pagamento_id}`, e `POST /api/v1/simulador/pagamentos/{id}/aprovar` (ou `/recusar`) percorre o mesmo caso de uso de confirmação ou recusa que o webhook. A recusa no simulador conta como a do provedor, e o E2E usa `PAGAMENTO_MAX_RECUSAS=1`.

`MP_MODE` escolhe o adapter, é obrigatório e não tem padrão. O boot recusa `simulado` com `ENVIRONMENT=production`, salvo `SIMULADOR_PERMITIDO=true` explícito no overlay. As rotas do simulador só existem em modo simulado, exigem o token HMAC do `pagamento_id` que vai no `checkout_url` e têm rate limit ([ADR-038](038-borda-e-comunicacao-sincrona.md)), e `GET /api/v1/saude` informa o modo. `MP_MODE=mercadopago` exige `MP_ACCESS_TOKEN` e `MP_WEBHOOK_SECRET`, segredos da organização com acesso só para o repositório do Billing; a chave do `x-signature` só existe depois de configurar Webhooks na aplicação (Suas integrações).

### Prova da integração real

A evidência de RF-034 depende das credenciais de teste. A execução na sandbox roda num kind local com `MP_MODE=mercadopago`, confirmada pela conciliação, ou no k3s, que tem hostname e certificado para receber o webhook ([ADR-042](042-cicd-e-deploy-kubernetes.md)). Preferência criada, pagamento aprovado e estorno ficam versionados em `docs/entrega/fase4/evidencias/`. CI, kind do CI e E2E continuam no simulador.

### Resiliência

O envelope do [ADR-038](038-borda-e-comunicacao-sincrona.md), com timeout, circuit breaker para o Mercado Pago e retry com jitter só em operação idempotente: as consultas e o estorno com chave. A criação da preferência não tem chave de idempotência documentada e não é repetida pelo cliente HTTP; se falhar, o comando volta pela fila de retry ([ADR-036](036-mensageria-rabbitmq.md)). As chamadas alimentam `pytstop_mercadopago_requisicoes_total{operacao,resultado}` e `pytstop_circuit_breaker_aberto{dependencia}` ([ADR-043](043-observabilidade-distribuida.md)).

## Alternativas Consideradas

* Checkout Pro com webhook verificado, conciliação e simulador
* Checkout Transparente (Orders API) com Pix direto
* Checkout Pro só com consulta periódica, sem webhook

Descartados pelo enunciado: usar só o simulador e trocar de provedor, porque a l. 47 exige a integração com o Mercado Pago.

### Checkout Pro com webhook verificado, conciliação e simulador

* Bom, porque o pagador conclui na página do Mercado Pago, com cartão, Pix ou saldo, e o PytStop não toca em dado de cartão
* Bom, porque CI e E2E percorrem o mesmo caso de uso de confirmação com ou sem credencial, e o adapter real fica coberto por teste de contrato
* Bom, porque a conciliação cobre webhook perdido e permite a prova real sem URL pública
* Ruim, porque são duas vias de confirmação para manter e testar, e a conciliação faz uma consulta por pagamento em `SOLICITADO` a cada 30 s
* Ruim, porque o simulador pode divergir do provedor em detalhes que só a sandbox mostra

### Checkout Transparente (Orders API) com Pix direto

* Bom, porque o pagamento acontece na API do Billing, sem redirecionamento, e o QR Code do Pix vem na resposta
* Ruim, porque a documentação deixa a interface de pagamento com o integrador, e esta fase não tem interface (a demonstração usa Swagger, Postman e scripts)
* Ruim, porque cartão exige tokenização no cliente, e só Pix reduz os meios de pagamento; a confirmação continua dependendo de notificação ou consulta

### Checkout Pro só com consulta periódica, sem webhook

* Bom, porque funciona sem URL pública e dispensa a verificação de assinatura
* Ruim, porque a confirmação espera o ciclo de consulta, e a notificação, que o Mercado Pago documenta como caminho principal, fica sem uso
* Ruim, porque a verificação do `x-signature`, que protege a rota pública, deixaria de ser exercitada

## Consequências

### Positivas

* RF-032 a RF-034 atendidos com a API real, coberta por teste de contrato e provada na sandbox, e com CI e E2E independentes de credencial
* Notificação forjada não muda estado: sem assinatura válida o webhook recusa, e com ela o estado vem da consulta à API
* Estorno idempotente (RN-026, RN-028): a reentrega do comando e a aprovação tardia não estornam duas vezes
* Cancelamento com o checkout aberto encerra o pagamento, e a aprovação que chega depois é estornada sem intervenção manual
* O Billing não guarda dado pessoal do pagador

### Negativas

* A sandbox exige contas de teste e o passo humano; sem as credenciais, não há evidência de RF-034
* O webhook exige URL HTTPS pública, e a documentação recusa `localhost`: no kind, a confirmação real chega pela conciliação, com até 30 s de atraso. README e vídeo precisam dizer o que é sandbox e o que é simulado
* O teste de contrato prova aderência à documentação, não ao comportamento da API no dia. A documentação, por exemplo, não diz se a notificação enviada à `notification_url` da preferência leva `x-signature`; se não levar, o webhook a recusa, a conciliação confirma o pagamento, e a saída é cadastrar a URL no painel de Webhooks
* A criação da preferência não é idempotente: um timeout pode deixar uma preferência órfã no provedor, que ninguém usa porque o link dela nunca é publicado (`PagamentoSolicitado` só sai na transação que dá certo)
* A validade padrão de 60 min fica abaixo do que a documentação recomenda para meios offline e Pix (pelo menos 3 dias), e a documentação prevê até 2 h úteis de compensação bancária, conforme o meio: um pagamento feito no prazo pode ser aprovado depois da expiração local e cai no estorno do passo 7. Restringir a preferência a meios de aprovação imediata ou alongar a validade reduz a janela, e o próprio Mercado Pago estorna o que for pago depois da `date_of_expiration` da preferência

### Neutras

* Trocar o simulador pelo adapter real é configuração (`MP_MODE` e credenciais), não código, o mesmo padrão do ADR-018 do p3
* Uma notificação barrada pelo rate limit só volta 15 min depois, no reenvio do provedor; por isso a rota do webhook tem balde próprio na borda ([ADR-038](038-borda-e-comunicacao-sincrona.md))

## Decisões Relacionadas

- [ADR-021](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p3/blob/main/docs/arquitetura/adr/fase2/021-aprovacao-externa-orcamento.md): assinatura HMAC por requisição num canal externo, o mesmo princípio do `x-signature`
- [ADR-018](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p3/blob/main/docs/arquitetura/adr/fase2/018-notificacao-email.md): adapter escolhido por configuração, com servidor falso (Mailpit) na demonstração, o precedente do simulador
- [ADR-035](035-saga-orquestrada.md): pagamento compensável por estorno, antes do pivot (ponto sem retorno, RN-029) no início da execução
- [ADR-036](036-mensageria-rabbitmq.md): comandos, eventos e fila de retry do Billing
- [ADR-038](038-borda-e-comunicacao-sincrona.md): rota do webhook na borda e envelope de resiliência
- [ADR-039](039-autenticacao-entre-servicos.md): tokens HMAC e política de segredos
- [ADR-041](041-estrategia-de-testes-e-qualidade.md): teste de contrato do adapter e cenários de pagamento
- [ADR-042](042-cicd-e-deploy-kubernetes.md): segredos da organização e exposição do k3s

## Notas

* Documentação oficial do Mercado Pago consultada em 06/10/2026: Checkout Pro (https://www.mercadopago.com.br/developers/pt/docs/checkout-pro/landing); notificações e `x-signature` (https://www.mercadopago.com.br/developers/pt/docs/checkout-pro-preferences/payment-notifications); obter pagamento (https://www.mercadopago.com.br/developers/pt/reference/online-payments/checkout-pro-preferences/get-payment/get); buscar pagamentos (https://www.mercadopago.com.br/developers/pt/reference/online-payments/checkout-pro-preferences/search-payments/get); reembolso (https://www.mercadopago.com.br/developers/pt/reference/online-payments/checkout-pro-preferences/create-refund/post); data de expiração (https://www.mercadopago.com.br/developers/pt/docs/checkout-pro-preferences/additional-settings/expiration-date); contas de teste (https://www.mercadopago.com.br/developers/pt/docs/checkout-pro-preferences/test-accounts)
* Validador do `x-signature` no SDK oficial, sem janela de `ts` por padrão (`tolerance_seconds=None`): https://github.com/mercadopago/sdk-python/blob/master/mercadopago/webhook/validator.py
* Material: SAGA Pattern, Aula 05; Estrutura de Microsserviços, Aula 01

> [↑ Raiz do projeto](../../../../README.md) · [↑ Arquitetura](../../README.md)
