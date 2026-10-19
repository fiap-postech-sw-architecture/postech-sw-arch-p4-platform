# Duas execuções locais da collection — 19/10/2026

Estado: prova local aprovada, integração no CI pendente. As duas execuções usaram Newman 6.2.3 e Node 24.18.0 contra o simulador do Billing, pela borda do kind. Não foram usados Mercado Pago real nem credenciais do provedor.

Comando, executado duas vezes com dados novos: `make newman KUBE_CONTEXT=kind-pytstop-p4-codex`.

O runner e a collection correspondem aos blobs preservados no commit local `af33b0fb724ae6dfb535c4d448127d815c138c2c`, preparado sobre a base `ec05e8793188309cde4e25d1fe369447e9da300d`. A collection tem SHA256 `8cd3122e152757aefe0202b25a1a6e6a38216631e3f080838326538b6c22fc85`. Esses identificadores distinguem o código ensaiado da base anterior; não afirmam publicação ou congelamento.

A infraestrutura do kind usava a plataforma `91d959bcba07b3a7b53653342e944ea01bdaa3c3`. Serviços: OS `b81f609a193afa669ed602d3327cb074827c25d6`, Billing `248c4071d357a867db1571081b012ff57753f834` e Execução `605a5e56b297438163cddba2a4f129b334c1699d`. A plataforma usou overlay kind, e os serviços, kind-ci; essa combinação é de ensaio.

| Execução | Duração observada | Assertions | Chamadas HTTP | Falhas |
|---|---|---|---|---|
| [Primeira](newman-fluxo-1-2026-10-19.json) | 31,17 s | 108 | 49 | 0 |
| [Segunda](newman-fluxo-2-2026-10-19.json) | 41,11 s | 104 | 49 | 0 |

A quantidade de assertions varia com os polls assíncronos. Cada execução criou dados novos, sem limpar o estado existente. O fluxo autenticou admin, atendente e mecânico, percorreu oito status até a entrega, confirmou pagamento de R$ 210,00 e verificou reserva e baixa do estoque: 10 disponíveis, 2 reservados e 8 livres; depois, 8 disponíveis, nenhuma reserva e 8 livres. A saga terminou concluída.

A rota de métricas devolveu 401 sem token, 403 para atendente e mecânico e 200 para admin, com nove status. Na primeira prova havia dez OS e duas entregues; na segunda, onze OS e três entregues. As provas conferem o estado real acumulado, sem exigir total global igual a um.

Os JSONs são cópias exatas dos resumos sanitizados do runner: nomes e rotas estáticos, códigos, tempos, assertions e sete provas com campos permitidos. Não incluem JWT, HMAC, credenciais, corpos de requisição/resposta, URLs resolvidas ou mensagens livres de erro. Passaram pela varredura existente e pelo gitleaks antes da preparação para publicação.

A integração do Newman no workflow deve preservar smoke, BDD, ZAP e varredura. Sua execução na HEAD publicada continua pendente, assim como a prova real do provedor e a atualização dos commits finais.
