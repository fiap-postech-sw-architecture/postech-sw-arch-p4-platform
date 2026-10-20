# Roteiro do vídeo da fase 4

Duração prevista: 14 minutos. Gravar sobre os quatro commits congelados e mostrar serviço e SHA no trecho de CI/CD. Usar dados sintéticos. Credenciais, documentos pessoais, chaves, tokens e telas sensíveis não entram na gravação.

| Tempo | Demonstração | O que mostrar | Requisitos |
|---|---|---|---|
| 00:00–00:30 | Apresentação | Integrantes confirmados, quatro repositórios e diagrama com bancos separados | RNF-031, RNF-032, RNF-033, RNF-044 |
| 00:30–04:30 | Fluxo completo, `make demo` bloco 1 | Abertura; diagnóstico; orçamento/e-mail; aprovação; reserva; pagamento; fila; execução; finalização; entrega; oito status do histórico. Mostrar a validação de CPF inválido | RF-028 a RF-038; RN-027; RNF-052 |
| 04:30–08:30 | Saga e falhas, bloco 2 | Reserva sem saldo; cancelamento pago com estorno; 409 após início; consumidor parado e recuperação sem DLQ; API do Billing fora com 503 e circuito aberto | RN-023 a RN-029; RNF-037; RNF-055 |
| 08:30–11:00 | Pipeline de um serviço | PR/checks obrigatórios; testes e cobertura; SonarQube; build; digest; deploy kind; smoke e E2E na mesma execução | RNF-038 a RNF-043; RNF-048 a RNF-050 |
| 11:00–14:00 | Observabilidade e encerramento | Trace dos três serviços e chamada ao provedor; correlação no Loki; latência p95, erro 5xx e sucesso; volume diário de OS e tempo médio por status; alerta e runbook; índice | RNF-046; RNF-053; RNF-054; RNF-056 |

Identificar quando o pagamento usa o simulador. O trecho da sandbox real deve usar a prova que o integrante com as credenciais criou no Mercado Pago; uma simulação não comprova aprovação real.

Antes da gravação, conferir `make demo`, a collection integrada, o trace e as capturas com os mesmos commits. Gravar o pipeline antes e condensar a espera na edição, preservando a ordem das etapas e o resultado completo.

Após editar: duração inferior a 15 minutos, comandos e painéis legíveis, ausência de segredos e link acessível. Inserir o link no documento e no índice, criar as tags finais e regenerar o PDF.
