## Relatório do E2E do Mercado Pago

3 cenários, 0 sem passar, 230 s no total.

| Cenário | Tags | Resultado | Duração (s) | ordem_id | trace_id |
|---|---|---|---|---|---|
| Pagamento no checkout do Mercado Pago é confirmado pela conciliação | `@mp_sandbox` `@pagamento` | passou | 121,4 | `ec0bf2a0-6a88-4e98-b077-352684b8e586` | `-` |
| Cancelar a OS depois do pagamento estorna o valor no Mercado Pago | `@estorno` `@mp_sandbox` | passou | 84,8 | `56b1e5b1-d6fb-429f-a008-f42c5592502a` | `-` |
| Cancelar a OS sem pagar fecha a cobrança e expira a preferência no Mercado Pago | `@cobranca-aberta` `@mp_sandbox` | passou | 23,4 | `1071b194-d179-485f-b759-ed69e4743584` | `-` |
