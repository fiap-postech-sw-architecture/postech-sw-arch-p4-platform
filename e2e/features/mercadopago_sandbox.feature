# language: pt
Funcionalidade: Mercado Pago na sandbox
  Como dono do projeto
  Quero ver o Billing cobrar, conciliar e estornar no Mercado Pago com credenciais de teste
  Para ter a evidência da integração real (ADR-040, RF-034) sem mover dinheiro de verdade

  # Só roda por make mp-sandbox (modo real: quem paga é você, no navegador, com o comprador
  # de teste) e make mp-sandbox-ensaio (o simulador do Billing paga no seu lugar). Fica fora
  # do make e2e, do make demo e do CI: o CI não tem token. A sandbox não envia webhook, então
  # o pagamento é confirmado pela conciliação do processo prazos.
  Contexto:
    Dado que o Billing está no modo de pagamento desta execução
    E que os três microsserviços respondem pela borda
    E que há um atendente e um mecânico autenticados
    E que o Billing tem o preço de um serviço de "120.00" e de uma peça de "45.00"
    E que o estoque tem 10 unidades da peça
    E que o cliente tem um veículo cadastrado

  @mp_sandbox @pagamento
  Cenário: Pagamento no checkout do Mercado Pago é confirmado pela conciliação
    Dado uma OS aguardando o pagamento no checkout do Mercado Pago
    Quando o comprador de teste paga o link do checkout
    Então o Billing confirma o pagamento
    E a OS fica com status "aguardando_execucao"
    E o Mercado Pago informa o pagamento como aprovado, no valor do orçamento

  @mp_sandbox @estorno
  Cenário: Cancelar a OS depois do pagamento estorna o valor no Mercado Pago
    Dado uma OS paga no Mercado Pago e na fila de execução
    Quando o atendente cancela a OS com o motivo "teste da sandbox"
    Então a saga terminou como "compensada" pelo motivo "cancelamento"
    E as compensações enviadas foram, nesta ordem: "CancelarExecucao, EstornarPagamento, LiberarReserva, CancelarOrcamento, DescartarDiagnostico"
    E o pagamento no Billing está "ESTORNADO"
    E o Mercado Pago informa o pagamento como estornado

  @mp_sandbox @cobranca-aberta
  Cenário: Cancelar a OS sem pagar fecha a cobrança e expira a preferência no Mercado Pago
    Dado uma OS aguardando o pagamento no checkout do Mercado Pago
    Quando o atendente cancela a OS com o motivo "teste da sandbox"
    Então a saga terminou como "compensada" pelo motivo "cancelamento"
    E as compensações enviadas foram, nesta ordem: "EstornarPagamento, LiberarReserva, CancelarOrcamento, DescartarDiagnostico"
    E o pagamento no Billing está "CANCELADO"
    E o Mercado Pago informa a preferência do checkout como expirada
