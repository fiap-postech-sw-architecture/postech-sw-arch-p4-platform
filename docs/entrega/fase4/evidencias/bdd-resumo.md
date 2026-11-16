# BDD integrado — 15/11/2026

O [CD da main da plataforma, run 43755645721](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-platform/actions/runs/43755645721), job `e2e`, executou `make -C platform e2e` em kind descartável do runner, overlay kind-ci e Billing simulado, com os quatro commits da entrega. As 14 execuções selecionadas (11 cenários e um esquema com 3 exemplos) passaram em 207,14 s, valor lido na linha final do pytest no log do job; os três cenários de sandbox real ficaram fora dessa seleção. O resumo do artefato informa 205 s somados. O passo do workflow ocorreu entre 20:11:31 e 20:15:09 UTC, incluindo o trabalho do alvo. É o run do A5 do documento de entrega.

| Checkout efetivamente exercitado | Commit |
|---|---|
| platform | `e720b433bc48f240574e62e1a00fdc57bf3c280f` |
| os-service | `4a0cec2088984d9fa3eb8f143a550dcbbce9e617` |
| billing-service | `5adb362992571d503264d2d172a5f6710444b8a5` |
| execution-service | `b3451d32465801fd74c8b17e58a9021bdfa092c5` |

| Cenário | Tags | Resultado | Duração (s) |
|---|---|---|---:|
| A OS percorre os três serviços da abertura à entrega | `@bloco-1` `@caminho-feliz` `@demo` | passou | 17,2 |
| O cliente recusa o orçamento pelo link | `@compensacao` | passou | 3,3 |
| Falta de peça cancela a OS sem cobrar o cliente | `@bloco-2` `@compensacao` `@demo` | passou | 3,8 |
| Pagamento recusado no simulador libera a reserva e cancela o orçamento | `@compensacao` | passou | 5,4 |
| Cancelamento depois do pagamento estorna o valor e devolve as peças | `@bloco-2` `@compensacao` `@demo` `@estorno` | passou | 7,2 |
| CPF com dígito verificador errado é recusado e o acompanhamento não o distingue de um CPF inexistente | `@validacao` | passou | 0,2 |
| Depois do início da execução a OS não pode mais ser cancelada | `@bloco-2` `@demo` `@ponto-de-nao-retorno` | passou | 6,0 |
| Orçamento sem decisão vence e a OS é cancelada | `@expiracao` | passou | 76,3 |
| Consumidor do Billing parado por 20 segundos não perde o fluxo | `@bloco-2` `@demo` `@resiliencia` | passou | 48,8 |
| API do Billing parada abre o circuito e a conclusão volta com o Billing | `@bloco-2` `@demo` `@resiliencia` | passou | 36,8 |
| O Swagger de cada serviço abre pelo Kong sob o prefixo do serviço [/os] | `@borda` | passou | 0,1 |
| O Swagger de cada serviço abre pelo Kong sob o prefixo do serviço [/billing] | `@borda` | passou | 0,2 |
| O Swagger de cada serviço abre pelo Kong sob o prefixo do serviço [/execucao] | `@borda` | passou | 0,1 |
| As métricas das OS pela borda exigem o administrador e trazem os nove status | `@borda` | passou | 0,1 |

Esta tabela foi projetada do `resumo.md` do artefato `e2e-kind`, removendo identificadores de ordens e traces. Smoke, Newman, ZAP e varredura também passaram nesse run. Os commits dos três serviços são os da tag `entrega-fase-4`; a tag do `platform` aponta para o commit que publicou o documento de entrega, que só muda documentos em relação ao `e720b43`. O mesmo BDD passou no `deploy-kind` do CD de cada serviço, com os mesmos quatro commits ([registro de evidências](README.md#cd-nos-commits-da-entrega)). A integração real com o Mercado Pago está em [Mercado Pago na sandbox](mp-sandbox.md).
