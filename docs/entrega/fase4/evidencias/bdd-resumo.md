# BDD integrado — 19/10/2026

O [CD da main da plataforma, run 39231733886](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-platform/actions/runs/39231733886), job `e2e`, executou `make -C platform e2e` em kind descartável do runner, overlay kind-ci e Billing simulado. Os 14 cenários selecionados passaram; os três cenários de sandbox real ficaram fora dessa seleção. O resumo do artefato informa 200 s somados. O passo do workflow ocorreu entre 09:50:28 e 09:54:00 UTC, incluindo o trabalho do alvo.

| Checkout efetivamente exercitado | Commit |
|---|---|
| platform | `bfa8c72f1f8bf4c7af2994b73421137f00d02d64` |
| os-service | `a1d58315d99db6ec0ad1b101cf0083916cf24b88` |
| billing-service | `248c4071d357a867db1571081b012ff57753f834` |
| execution-service | `6e34092022bbcf00918967099976a05b4b2882b0` |

| Cenário | Tags | Resultado | Duração (s) |
|---|---|---|---:|
| A OS percorre os três serviços da abertura à entrega | `@bloco-1` `@caminho-feliz` `@demo` | passou | 20,1 |
| O cliente recusa o orçamento pelo link | `@compensacao` | passou | 3,5 |
| Falta de peça cancela a OS sem cobrar o cliente | `@bloco-2` `@compensacao` `@demo` | passou | 3,8 |
| Pagamento recusado no simulador libera a reserva e cancela o orçamento | `@compensacao` | passou | 7,1 |
| Cancelamento depois do pagamento estorna o valor e devolve as peças | `@bloco-2` `@compensacao` `@demo` `@estorno` | passou | 7,1 |
| CPF com dígito verificador errado é recusado e o acompanhamento não o distingue de um CPF inexistente | `@validacao` | passou | 0,1 |
| Depois do início da execução a OS não pode mais ser cancelada | `@bloco-2` `@demo` `@ponto-de-nao-retorno` | passou | 5,5 |
| Orçamento sem decisão vence e a OS é cancelada | `@expiracao` | passou | 74,8 |
| Consumidor do Billing parado por 20 segundos não perde o fluxo | `@bloco-2` `@demo` `@resiliencia` | passou | 41,5 |
| API do Billing parada abre o circuito e a conclusão volta com o Billing | `@bloco-2` `@demo` `@resiliencia` | passou | 36,2 |
| O Swagger de cada serviço abre pelo Kong sob o prefixo do serviço [/os] | `@borda` | passou | 0,1 |
| O Swagger de cada serviço abre pelo Kong sob o prefixo do serviço [/billing] | `@borda` | passou | 0,2 |
| O Swagger de cada serviço abre pelo Kong sob o prefixo do serviço [/execucao] | `@borda` | passou | 0,1 |
| As métricas das OS pela borda exigem o administrador e trazem os nove status | `@borda` | passou | 0,1 |

Esta tabela foi projetada do `resumo.md` do artefato `e2e-kind`, removendo identificadores de ordens e traces. Smoke, Newman, ZAP e varredura também passaram nesse run. O resultado comprova a combinação de fontes acima; o congelamento final exige nova conferência. A integração real com o Mercado Pago continua dependendo da sandbox do responsável.
