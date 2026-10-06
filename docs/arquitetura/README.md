# Arquitetura da fase 4

> [↑ Raiz do projeto](../../README.md)

O desenho integrado está na [RFC-004: PytStop em microsserviços com saga orquestrada](rfc/fase4/rfc-004-microsservicos-saga.md), com diagrama geral, divisão dos serviços, saga com as sequências de sucesso e de compensação, mensageria, APIs, dados, segurança, observabilidade e implantação. Cada escolha tem um registro de decisão de arquitetura (ADR) com o contexto, as alternativas descartadas e as consequências.

| ADR | Decisão | Status |
|---|---|---|
| [034](adr/fase4/034-decomposicao-em-microsservicos.md) | Decomposição do PytStop em três microsserviços e uma plataforma | Aceita |
| [035](adr/fase4/035-saga-orquestrada.md) | Saga de atendimento orquestrada pelo OS Service | Aceita |
| [036](adr/fase4/036-mensageria-rabbitmq.md) | RabbitMQ com outbox transacional e consumidor idempotente | Aceita |
| [037](adr/fase4/037-banco-por-servico.md) | PostgreSQL no OS e na Execução, MongoDB no Billing | Aceita |
| [038](adr/fase4/038-borda-e-comunicacao-sincrona.md) | Kong na borda e REST síncrono só quando a resposta é necessária na hora | Aceita |
| [039](adr/fase4/039-autenticacao-entre-servicos.md) | JWT RS256 emitido pelo OS Service e validado por JWKS | Aceita |
| [040](adr/fase4/040-integracao-mercado-pago.md) | Mercado Pago via Checkout Pro com webhook verificado e simulador para CI | Aceita |
| [041](adr/fase4/041-estrategia-de-testes-e-qualidade.md) | Estratégia de testes e qualidade por serviço | Aceita |
| [042](adr/fase4/042-cicd-e-deploy-kubernetes.md) | CI/CD por serviço com deploy em kind e k3s | Aceita |
| [043](adr/fase4/043-observabilidade-distribuida.md) | Stack da fase 3 reaproveitada com rastreamento da saga ponta a ponta | Aceita |

Os ADRs 000 a 033 e as RFCs 001 a 003, das fases 1 a 3, ficam no [repositório da fase 3](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p3/tree/main/docs/arquitetura); os ADRs desta fase citam os que retomam ou substituem.

A arquitetura interna de cada serviço (camadas, modelo de dados completo e fluxos) fica no repositório dele:

- [OS Service](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-os-service): ordens de serviço, clientes e veículos, autenticação e orquestração da saga
- [Billing Service](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-billing-service): preços, orçamento e pagamento com o Mercado Pago
- [Execution Service](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-execution-service): diagnóstico, estoque e fila de execução
