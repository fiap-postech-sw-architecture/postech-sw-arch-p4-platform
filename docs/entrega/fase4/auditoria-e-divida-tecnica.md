# Auditoria pré-entrega e dívida técnica

Conferência inicial de 19/10/2026. Fontes: requisitos da fase, PRs integrados, gates locais, execução do CI e pendências registradas nos serviços. Esta versão acompanha o ensaio; a revisão final depende dos commits congelados e das evidências listadas abaixo.

## Pendências que afetam a entrega

| Item | Impacto | Responsável | Condição para fechar |
|---|---|---|---|
| CD compartilhado e chamadas dos três serviços | RNF-042 e RNF-049 exigem deploy independente por serviço | Plataforma e serviços | Workflow fixado por SHA; CI, segurança, imagem, kind e E2E verdes na `main` de cada serviço |
| Collection do fluxo completo | Duas provas locais aprovadas; publicação e integração no CI de RNF-052 ainda pendentes | Plataforma | Integrar a collection e comprovar o Newman no workflow final, incluindo as métricas administrativas do OS; [resumos locais](evidencias/newman-resumo.md) |
| Ensaio final de observabilidade | Trace com os três serviços, 600,9 s ociosos, smoke e alerta com recuperação comprovados localmente; RNF-046/RNF-056 continuam parciais | Plataforma e serviços | Preservar capturas com três dias; chamada externa e observação no modo real do Billing dependem da sandbox |
| Remanescentes de telemetria do Billing | Correções e provas locais revisadas: Host, classe da falha do coletor, deadline e smoke; integração pendente | Billing Service | Integrar a fonte revisada, confirmar o CI e atualizar a tabela de cobertura pelo novo artefato publicado |
| Evidência real do Mercado Pago | Simulador não comprova acesso à sandbox do provedor | Responsável com credenciais | Cobrança, aprovação e estorno reais, com saída sanitizada |
| Descrição de `EstornoDePagamentoFalhou.motivo` | A mensagem fixa já está no Billing; a descrição da fonte canônica e das cópias ainda precisa ser alinhada | Plataforma e serviços | Atualizar a descrição e sincronizar cópias/ORIGEM, preservando formato, versão e routing key |
| Grupo, vídeo e submissão | RNF-053/RNF-054 ainda não podem ser encerrados | Grupo | Confirmar identificação; publicar vídeo; conferir acesso do avaliador; submeter o PDF final |

## Correções integradas no Billing

O [PR #17](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-billing-service/pull/17), integrado em `248c4071d357a867db1571081b012ff57753f834`, encerrou os cinco itens transversais do Billing:

- Boot: bloqueio explícito da configuração automática de telemetria do FastAPI, provado também no smoke real.
- Recusa e legado: mensagem fixa no histórico, evento e HTTP; leitura protegida do histórico antigo sem regravar documentos.
- OpenAPI: descrição pública da saúde e query `type` do webhook, preservando precedência e assinatura.
- Mongo indisponível: HTTP 503 com mensagem fixa nas falhas de conexão/operação previstas; erros de programação continuam 500.
- Prazo da API: cliente e transações HTTP limitados a 2 s; workers mantêm seus prazos.

Nove checks aprovados e nenhuma thread pendente na integração. O gate final registrou 1.657 testes, cobertura e diff-cover de 100%, smoke real e nove mutantes detectados. O alinhamento descritivo do contrato continua na tabela de pendências; esses resultados não comprovam a sandbox real do provedor.

## Ensaio de observabilidade

Em 19/10/2026, o E2E local passou com 14 testes e três cenários de sandbox não selecionados, seguido de `smoke-servicos` aprovado. O trace `af146ea716424dfc2ac5b25960b8e9ae` contém os três serviços e o CLIENT Execução → Billing. O simulador não produz chamada HTTP externa; o CLIENT Billing → Mercado Pago permanece pendente da sandbox real.

A auditoria do dashboard de bancos confirmou consultas restritas às séries disponíveis no exporter; ele não usa `mongodb_ss_*`. A dívida anterior sobre essas consultas foi encerrada. A janela real de 600,9 s terminou sem reinícios, com 18 grupos de alvos disponíveis e três bancos acessíveis. O alerta controlado de fila disparou e recuperou, e o smoke posterior passou. O [relatório parcial](evidencias/observabilidade.md) preserva os commits, timestamps, trace e capturas do alerta. Capturas com uma hora de dados ainda não encerram a prova de três dias. O volume diário antes da primeira meia-noite UTC segue a limitação descrita no JSON.

## Dívida aceita e acompanhada

| Item | Limite atual | Quando revisar |
|---|---|---|
| Detalhe do cliente retorna CPF/CNPJ completo a atendente e admin | Comportamento herdado; decisão de minimização ainda cabe ao responsável. Listagem usa valor mascarado e rotas de dados pessoais têm auditoria | Antes de mudar o contrato público; atualizar API, OpenAPI e collection juntos |
| Consultas dos coletores da Execução sem índice por data | Medidas registradas cabem no prazo de 2 s com o volume ensaiado; série indisponível não vira zero | Quando o crescimento aproximar as consultas do prazo ou o volume superar o medido |
| DNS do driver PostgreSQL não entra no prazo de conexão | A coleta HTTP termina no prazo, mas a thread pode aguardar resolução do nome | Se o DNS do cluster apresentar travamento; medir antes de introduzir resolução paralela |
| Método HTTP como rótulo aberto no Billing e na Execução | Métodos inesperados podem criar novas séries | Fechar vocabulário quando revisar o coletor; preservar GET/POST/PUT/PATCH/DELETE/HEAD/OPTIONS |
| OpenAPI do OS omite alguns erros HTTP | Login e operações de cliente podem devolver erros não declarados; o envelope permanece uniforme | Completar `responses` na origem e regenerar os dois contratos |
| Mutação de retenção da Execução | Falta caso entre 30 e 31 dias para separar a retenção correta de 30 dias | Próximo ajuste de retenção; usar um registro de 30,5 dias |
| Mutação de arredondamento de `Retry-After` no Billing | Testes usam espera inteira e não separam `ceil` de `floor` | Acrescentar espera fracionária e mutante correspondente |
| Digest do OWASP ZAP atualizado manualmente | Imagem fixada por digest; digest indisponível reprova o job | Atualização deliberada com scan e prova do script |
| Deploy remoto opcional | Não integra o ambiente kind entregue; requer acesso ao cluster e checkout do próprio serviço no job | Ao habilitar o gancho remoto; provar contexto, overlay e imagem por digest |
| Redrive manual depois de erasure | O runbook proíbe o procedimento, mas o script não conhece a remoção dos dados nem tem trava automática | Antes de automatizar redrive ou rever esse procedimento; preservar a proibição atual |
| Mailpit da demonstração | Sem autenticação ou política de ingresso; só o notificador tem restrição de saída, e as APIs podem alcançá-lo | Antes de usar dados reais ou expor esse ambiente; SMTP real exige STARTTLS e credenciais em Secret, conforme ADR-042 |
| Atualizações automáticas do Platform | Não há catálogo Dependabot no repositório; os pins atuais são atualizados deliberadamente | Quando ampliar a automação de dependências; manter verificação e revisão dos pins atuais |
| Consolidação de `MEMORY.md` | Histórico preservado; consolidação exige aprovação específica | Após decisão do responsável; não bloqueia execução ou contrato |

Uma dívida aceita não dispensa o gate nem autoriza declarar uma prova inexistente. A revisão final deve confirmar se algum item ganhou impacto maior com as últimas alterações.

## Provas disponíveis

- OS: 10.398 testes aprovados, cobertura de 99,62% na árvore integrada por #17; gates estáticos e de documentação aprovados.
- Billing: 1.657 testes aprovados, cobertura e diff-cover de 100% na árvore integrada por #17 (`248c407`); nove checks, smoke real e nove mutantes aprovados. OpenAPI e collection regenerados pelo comando oficial.
- Execução: 1.468 testes aprovados e cobertura de 100% na árvore integrada por #9.
- Plataforma: 2.539 testes aprovados e cobertura de 100% na árvore integrada por #20; CD [39190581574](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-platform/actions/runs/39190581574) aprovado em `91d959b`.

As correções posteriores de observabilidade do Billing passaram localmente com 1.696 testes, cobertura e diff-cover de 100%, nove mutantes detectados, manifests e smoke dos quatro processos aprovados. As revisões independentes de segurança, aderência, qualidade e README estão encerradas. Esses resultados locais não substituem o CI publicado da fonte integrada; a tabela final de cobertura continua pendente desse artefato.

Esses resultados identificam a base do ensaio. Cada alteração posterior exige os gates correspondentes e atualização deste registro antes do congelamento.


## Origem dos repositórios

O percurso completo do primeiro pai da `main` tem uma exceção anterior ao primeiro PR em cada repositório: o commit de criação, sem pais. Os quatro SHAs e o critério exato estão no [registro de evidências](evidencias/README.md#coleta-e-conferência-reproduzíveis). Eles permanecem visíveis na coleta; nenhuma alteração posterior recebe essa dispensa. A proteção de `main` e os checks efetivos são conferidos novamente no congelamento.
