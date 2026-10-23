# Collection do fluxo completo (`make newman`)

> [↑ Raiz do projeto](../README.md)

A [collection Postman v2.1](api/fluxo-completo.postman_collection.json) usa Node 24 e o Newman fixado em `6.2.3`. Depois da implantação e do smoke dos serviços descritos em [Como rodar](e2e-da-saga.md#como-rodar), execute, uma sessão por cluster:

```bash
make newman KUBE_CONTEXT=kind-pytstop-p4
```

O alvo seleciona [`e2e/newman.py`](../e2e/newman.py) explicitamente, com as fixtures e a conferência prévia do E2E: kind local, borda no loopback, DLQs vazias e configuração dos serviços `kind-ci` (orçamento de 72 s, primeira recusa encerra a cobrança e ciclo do `prazos` de 5 s). Exige Billing em modo `simulado` antes de ler a senha do admin do Secret. Recusa `E2E_MP_MODO` e `E2E_CONTEXTO_NAO_DESCARTAVEL` definidos. Cria usuários, preços, estoque, cliente/veículo sintéticos e uma OS novos; os dados permanecem no laboratório. O BDD continua em `make e2e`, com sua seleção própria.

Os 45 itens autenticam admin, atendente e mecânico e percorrem abertura, diagnóstico, orçamento de R$ 210, aprovação pelo link do e-mail, reserva, checkout simulado, pagamento, execução e entrega. As chamadas de negócio passam pelo Kong; o Mailpit fornece somente o e-mail. Confere o histórico exato dos oito status, estoque 10/2/8 → 8/0/8 (disponível/reservado/livre), pagamento confirmado, saga concluída e `GET /os/api/v1/ordens-de-servico/metricas`: 401 sem token, 403 para atendente/mecânico e 200 para admin com os nove status. Não exige total global igual a um. Polling tem limite por etapa e global; só o 429 de autenticação permite nova tentativa, com prazo.

O alvo recria apenas `reports/e2e/newman/`, preservando o relatório BDD. `resumo.json` e `resumo.md` guardam nomes/rotas estáticos, códigos HTTP, tempos, assertions e sete provas de negócio com campos permitidos; `junit.xml` guarda o resultado do pytest. JWT, senhas, documentos, links assinados, corpos livres e erros do runtime não entram nos resumos. O ambiente e o JSON bruto do Newman ficam em temporário privado e são removidos; timeout/interrupção encerram também os filhos da consulta de versão. Máscara e varredura precedem a gravação, e a varredura final reprova o alvo se encontrar segredo. A prova é do simulador do Billing; não certifica pagamento, webhook ou estorno no Mercado Pago real.

Ensaio local em 19/10/2026: Node 24.18.0, Newman 6.2.3, plataforma `kind` com PVC e serviços `kind-ci`, nas fontes abaixo. Duas execuções com dados novos passaram em 31,17 s e 41,11 s, cada uma com 49 chamadas, 108 e 104 assertions, zero falhas e varredura limpa. Ambas comprovaram os sete resultados acima; métricas globais passaram de 10 para 11 OS e de 2 para 3 entregues. O workflow define `make newman` no job `e2e`, depois da tentativa do BDD e antes do ZAP: Node 24, prazo de 12 minutos, smoke verde e job não cancelado. Uma falha do Newman reprova o job; seus relatórios entram na varredura e no artefato `e2e-kind`. O passo passou no [CI do PR #24](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-platform/actions/runs/39230026573): 105 assertions, zero falhas e 48 chamadas, com [quatro fontes e resumo sanitizado](entrega/fase4/evidencias/newman-resumo.md#execução-no-ci-do-platform-24). O run do PR usa seu merge sintético; o [CD da main integrada](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-platform/actions/runs/39231733886) também passou. A prova sobre os commits do congelamento continua pendente.

| Fonte do ensaio | Revisão |
|---|---|
| Plataforma, base local | `ec05e8793188309cde4e25d1fe369447e9da300d`; collection SHA256 `8cd3122e152757aefe0202b25a1a6e6a38216631e3f080838326538b6c22fc85` |
| OS | `b81f609a193afa669ed602d3327cb074827c25d6` |
| Billing | `248c4071d357a867db1571081b012ff57753f834` |
| Execução | `605a5e56b297438163cddba2a4f129b334c1699d` |
