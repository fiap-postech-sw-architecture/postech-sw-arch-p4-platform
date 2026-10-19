# Execuções da collection — 19/10/2026

Estado: duas provas locais, a execução no CI do PR #24 e o CD da main integrada aprovados. A collection foi integrada em `bfa8c72f1f8bf4c7af2994b73421137f00d02d64`; as provas do congelamento continuam pendentes. As duas execuções usaram Newman 6.2.3 e Node 24.18.0 contra o simulador do Billing, pela borda do kind. Não foram usados Mercado Pago real nem credenciais do provedor.

Comando, executado duas vezes com dados novos: `make newman KUBE_CONTEXT=kind-pytstop-p4-codex`.

O runner e a collection correspondem aos blobs preservados no commit local `af33b0fb724ae6dfb535c4d448127d815c138c2c`, preparado sobre a base `ec05e8793188309cde4e25d1fe369447e9da300d`. A collection tem SHA256 `8cd3122e152757aefe0202b25a1a6e6a38216631e3f080838326538b6c22fc85`. Esses identificadores distinguem o código ensaiado da base anterior; não afirmam publicação ou congelamento.

A infraestrutura do kind usava a plataforma `91d959bcba07b3a7b53653342e944ea01bdaa3c3`. Serviços: OS `b81f609a193afa669ed602d3327cb074827c25d6`, Billing `248c4071d357a867db1571081b012ff57753f834` e Execução `605a5e56b297438163cddba2a4f129b334c1699d`. A plataforma usou overlay kind, e os serviços, kind-ci; essa combinação é de ensaio.

| Execução | Duração observada | Assertions | Chamadas HTTP | Falhas |
|---|---|---|---|---|
| [Primeira](newman-fluxo-1-2026-10-19.json) | 31,17 s | 108 | 49 | 0 |
| [Segunda](newman-fluxo-2-2026-10-19.json) | 41,11 s | 104 | 49 | 0 |

A quantidade de assertions e de chamadas varia com os polls assíncronos. Cada execução criou dados novos, sem limpar o estado existente. O fluxo autenticou admin, atendente e mecânico, percorreu oito status até a entrega, confirmou pagamento de R$ 210,00 e verificou reserva e baixa do estoque: 10 disponíveis, 2 reservados e 8 livres; depois, 8 disponíveis, nenhuma reserva e 8 livres. A saga terminou concluída.

A rota de métricas devolveu 401 sem token, 403 para atendente e mecânico e 200 para admin, com nove status. Na primeira prova havia dez OS e duas entregues; na segunda, onze OS e três entregues. As provas conferem o estado real acumulado, sem exigir total global igual a um.

Os JSONs são cópias exatas dos resumos sanitizados do runner: nomes e rotas estáticos, códigos, tempos, assertions e sete provas com campos permitidos. Não incluem JWT, HMAC, credenciais, corpos de requisição/resposta, URLs resolvidas ou mensagens livres de erro. Passaram pela varredura existente e pelo gitleaks antes da preparação para publicação.

O passo integrado preserva smoke, BDD, ZAP, varredura e artefatos. A prova real do provedor e a atualização dos commits do congelamento continuam pendentes.

## Execução no CI do PR #24

O [run 39230026573](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-platform/actions/runs/39230026573), [job e2e](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-platform/actions/runs/39230026573/job/117985474670), aprovou o passo `Collection do fluxo completo (make newman)` entre `2026-10-19T09:33:48Z` e `09:34:25Z`. Comando: `make -C platform newman`. O pytest registrou um teste aprovado em 37,23 s. Newman 6.2.3 e Node 24.21.0 executaram 105 assertions, nenhuma falha e 48 chamadas HTTP, com as sete provas de negócio aprovadas. BDD, ZAP, varredura e uploads do mesmo job também passaram.

O [resumo sanitizado do CI](newman-ci-pr24-2026-10-19.json) é uma cópia exata do artefato `e2e-kind`, id 12176194955. SHA256: `f96b87d2a56f99403fec93b5c08f3ac036594c468d21535d467260bd0ab81ac5`. A collection mantém o SHA256 registrado no ensaio local. O kind do runner usou o overlay `kind-ci` e o simulador do Billing, sem credenciais do provedor.

| Checkout efetivamente exercitado | Commit |
|---|---|
| Plataforma, merge sintético do PR | `36a6469be53984f451d52c7a473a8f32bd510587` |
| OS Service | `b81f609a193afa669ed602d3327cb074827c25d6` |
| Billing Service | `248c4071d357a867db1571081b012ff57753f834` |
| Execution Service | `6e34092022bbcf00918967099976a05b4b2882b0` |

Os SHAs foram extraídos dos quatro passos de checkout, sem inferência pela main posterior. A árvore do merge sintético é `f0f952fce32020652b6cd2ccee0fc70fef15d8cb`, idêntica à ponta revisada `086fd1987338e51c8ff8052ea3a74cf6e5a22610` e à integração `bfa8c72`. Esses commits identificam a prova do PR; não são apresentados como execução do futuro congelamento.


## Execução no CD da main integrada

Em 19/10/2026, o [run 39231733886](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-platform/actions/runs/39231733886), job `e2e`, passou na main `bfa8c72f1f8bf4c7af2994b73421137f00d02d64`. O comando `make -C platform newman` teve 105 assertions, zero falhas, 48 chamadas e sete provas no simulador do Billing. O passo ocorreu entre 09:54:00 e 09:54:41 UTC. BDD, ZAP, varredura e publicação dos relatórios também passaram.

O [JSON sanitizado da main](newman-main-2026-10-19.json) preserva o conteúdo exato do artefato `e2e-kind`, com SHA256 `b37204dfe67a39412aaf850a9cc1e5cd38178e437879801f5015b4b579dfdb2c`. O ambiente foi kind descartável do runner, overlay kind-ci, sem credenciais do Mercado Pago.

| Checkout efetivamente exercitado | Commit |
|---|---|
| platform | `bfa8c72f1f8bf4c7af2994b73421137f00d02d64` |
| os-service | `a1d58315d99db6ec0ad1b101cf0083916cf24b88` |
| billing-service | `248c4071d357a867db1571081b012ff57753f834` |
| execution-service | `6e34092022bbcf00918967099976a05b4b2882b0` |

Os quatro SHAs foram extraídos dos registros dos passos de checkout. A prova é desta combinação de commits, anterior ao congelamento final; ela não certifica alterações posteriores ou pagamentos reais.
