# language: pt
Funcionalidade: Saga de atendimento da ordem de serviço
  Como oficina com serviços independentes de OS, Billing e Execução
  Quero que a abertura, o orçamento, o pagamento e a execução de uma OS sejam coordenados pela saga
  Para que nenhuma falha deixe a OS, o pagamento ou o estoque inconsistentes

  # Cada cenário cria o próprio cliente, veículo, preços e estoque, com códigos únicos,
  # e não depende de nenhum outro. O orçamento do kind-ci vale 72 s e a primeira recusa
  # do provedor de pagamento encerra a cobrança.
  Contexto:
    Dado que os três microsserviços respondem pela borda
    E que há um atendente e um mecânico autenticados
    E que o Billing tem o preço de um serviço de "120.00" e de uma peça de "45.00"
    E que o estoque tem 10 unidades da peça
    E que o cliente tem um veículo cadastrado

  # Bloco 1 do vídeo: o fluxo completo de uma OS pelos três serviços.
  @caminho-feliz @demo @bloco-1
  Cenário: A OS percorre os três serviços da abertura à entrega
    Quando o atendente abre uma OS para o veículo do cliente
    Então a OS fica com status "recebida"
    E a Execução recebe o pedido de diagnóstico da OS
    Quando o mecânico inicia o diagnóstico
    Então a OS fica com status "em_diagnostico"
    Quando o mecânico conclui o diagnóstico com 1 serviço e 2 unidades da peça
    Então a OS fica com status "aguardando_aprovacao"
    E o orçamento da OS soma "210.00"
    E o cliente recebe o e-mail com o link de decisão do orçamento
    Quando o cliente aprova o orçamento pelo link do e-mail
    Então a OS fica com status "aguardando_pagamento"
    E o estoque da peça tem saldo de 10 com 2 reservadas
    E a OS ainda não está na fila de execução
    Quando o pagamento é aprovado no simulador do Mercado Pago
    Então a OS fica com status "aguardando_execucao"
    E a OS aparece na fila de execução
    Quando o mecânico inicia a execução
    Então a OS fica com status "em_execucao"
    Quando o mecânico finaliza a execução
    Então a OS fica com status "finalizada"
    E o estoque da peça tem saldo de 8 com 0 reservadas
    Quando o atendente registra a entrega do veículo
    Então a OS fica com status "entregue"
    E a saga terminou como "concluida"
    E o histórico da OS mostra os oito status em ordem, de "recebida" a "entregue"
    E o trace da saga no Jaeger tem spans do os-service, do billing-service e do execution-service
    E o X-Request-ID devolvido pelo Kong aparece no log da API do OS

  @compensacao
  Cenário: O cliente recusa o orçamento pelo link
    Dado uma OS com o orçamento de 1 serviço e 2 unidades da peça aguardando a decisão do cliente
    Quando o cliente recusa o orçamento pelo link do e-mail
    Então a OS fica com status "cancelada"
    E a saga terminou como "compensada" pelo motivo "orcamento_recusado"
    E as compensações enviadas foram, nesta ordem: "DescartarDiagnostico"
    E o diagnóstico da OS está "DESCARTADO"

  # Bloco 2 do vídeo: reserva sem saldo.
  @compensacao @demo @bloco-2
  Cenário: Falta de peça cancela a OS sem cobrar o cliente
    Dado que o estoque da peça passa a ter 1 unidade
    E uma OS com o orçamento de 1 serviço e 2 unidades da peça aguardando a decisão do cliente
    Quando o cliente aprova o orçamento pelo link do e-mail
    Então a OS fica com status "cancelada"
    E a saga terminou como "compensada" pelo motivo "reserva_falhou"
    E a saga registrou o evento "ReservaDePecasFalhou"
    E as compensações enviadas foram, nesta ordem: "CancelarOrcamento, DescartarDiagnostico"
    E nenhum pagamento foi solicitado para a OS
    E o orçamento no Billing está "CANCELADO"
    E o estoque da peça tem saldo de 1 com 0 reservadas

  @compensacao
  Cenário: Pagamento recusado no simulador libera a reserva e cancela o orçamento
    Dado uma OS aguardando o pagamento, com 2 unidades da peça reservadas
    Quando o pagamento é recusado no simulador do Mercado Pago
    Então a OS fica com status "cancelada"
    E a saga terminou como "compensada" pelo motivo "pagamento_recusado"
    E as compensações enviadas foram, nesta ordem: "LiberarReserva, CancelarOrcamento, DescartarDiagnostico"
    E o pagamento no Billing está "RECUSADO" e não registra estorno
    E o orçamento no Billing está "CANCELADO"
    E o estoque da peça tem saldo de 10 com 0 reservadas

  # Bloco 2 do vídeo: cancelamento com estorno.
  @compensacao @estorno @demo @bloco-2
  Cenário: Cancelamento depois do pagamento estorna o valor e devolve as peças
    Dado uma OS paga e na fila de execução
    Quando o atendente cancela a OS com o motivo "cliente desistiu"
    Então o cancelamento é aceito com a etapa "compensando"
    E a OS fica com status "cancelada"
    E a saga terminou como "compensada" pelo motivo "cancelamento"
    E as compensações enviadas foram, nesta ordem: "CancelarExecucao, EstornarPagamento, LiberarReserva, CancelarOrcamento, DescartarDiagnostico"
    E o pagamento no Billing está "ESTORNADO"
    E o estoque da peça tem saldo de 10 com 0 reservadas
    E a OS não está mais na fila de execução
    E o cliente recebe o e-mail de cancelamento

  # RF-028 e RF-030 (lição da fase 3, gap analysis): o CPF é validado pelo módulo 11
  # antes de qualquer consulta. Que ele não chega ao banco é provado nos testes do OS
  # (TestConsultarAcompanhamento, em test_use_cases_os.py, e
  # test_documento_invalido_falha_antes_do_banco, em test_use_cases_cliente.py);
  # aqui se prova a recusa e que o acompanhamento público não distingue o CPF
  # inválido do inexistente.
  @validacao
  Cenário: CPF com dígito verificador errado é recusado e o acompanhamento não o distingue de um CPF inexistente
    Quando o atendente cadastra um cliente com um CPF de dígito verificador errado
    Então a API responde 422
    E o erro tem o código "VALOR_INVALIDO"
    E o acompanhamento público dá o mesmo 404 para um CPF inválido e para um CPF inexistente

  # Bloco 2 do vídeo: o 409 depois do início da execução.
  @ponto-de-nao-retorno @demo @bloco-2
  Cenário: Depois do início da execução a OS não pode mais ser cancelada
    Dado uma OS paga e na fila de execução
    Quando o mecânico inicia a execução
    Então a OS fica com status "em_execucao"
    Quando o atendente tenta cancelar a OS
    Então a API responde 409 com o código "TRANSICAO_STATUS_INVALIDA" e a mensagem "Cancelamento recusado: execução já iniciada"
    E a OS continua com status "em_execucao"

  @expiracao
  Cenário: Orçamento sem decisão vence e a OS é cancelada
    Dado uma OS com o orçamento de 1 serviço e 2 unidades da peça aguardando a decisão do cliente
    Quando o prazo de validade do orçamento passa sem decisão do cliente
    Então a OS fica com status "cancelada"
    E a saga terminou como "compensada" pelo motivo "orcamento_expirado"
    E a saga registrou o evento "OrcamentoExpirado"
    E as compensações enviadas foram, nesta ordem: "DescartarDiagnostico"

  # Bloco 2 do vídeo: consumidor parado.
  @resiliencia @demo @bloco-2
  Cenário: Consumidor do Billing parado por 20 segundos não perde o fluxo
    Dado uma OS com o diagnóstico iniciado
    E o consumidor do Billing parado
    Quando o mecânico conclui o diagnóstico com 1 serviço e 2 unidades da peça
    Então a OS segue em "em_diagnostico", com a saga em "aguardando_orcamento", durante 20 segundos
    Quando o consumidor do Billing volta
    Então a OS fica com status "aguardando_aprovacao"
    E nenhuma mensagem nova foi parar nas filas de mensagens mortas

  # Bloco 2 do vídeo: API do Billing parada. O circuito abre com 5 falhas, cada conclusão
  # tenta 3 vezes, e fica aberto por 30 s.
  @resiliencia @demo @bloco-2
  Cenário: API do Billing parada abre o circuito e a conclusão volta com o Billing
    Dado uma OS com o diagnóstico iniciado
    E a API do Billing parada
    Quando o mecânico tenta concluir o diagnóstico duas vezes
    Então as duas respostas são 503
    E o circuito do Billing está aberto na Execução
    Quando a API do Billing volta
    E o circuito do Billing deixa de barrar
    E o mecânico conclui o diagnóstico com 1 serviço e 2 unidades da peça
    Então a OS fica com status "aguardando_aprovacao"
    E o circuito do Billing está fechado na Execução

  @borda
  Esquema do Cenário: O Swagger de cada serviço abre pelo Kong sob o prefixo do serviço
    Então o Swagger de "<prefixo>" abre pelo Kong sob o próprio prefixo

    Exemplos:
      | prefixo   |
      | /os       |
      | /billing  |
      | /execucao |

  # RF-027 da fase 3: a rota que devolve a contagem de OS por status e o tempo médio por
  # status, o mesmo cálculo dos gauges do Prometheus que os dashboards de negócio leem.
  @borda
  Cenário: As métricas das OS pela borda exigem o administrador e trazem os nove status
    Quando consulto as métricas das OS sem token
    Então a API responde 401
    Quando o administrador consulta as métricas das OS
    Então a API responde 200
    E a resposta traz o total e as OS dos nove status
