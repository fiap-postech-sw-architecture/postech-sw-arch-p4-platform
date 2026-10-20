# Auditoria pré-entrega e dívida técnica

Revisão de 20/10/2026. Fontes: requisitos da fase, PRs integrados, gates locais, execuções do CI e pendências registradas nos serviços. Esta auditoria acompanha a versão preliminar do pacote; a revisão final depende dos commits congelados e das evidências listadas abaixo.

## Pendências que afetam a entrega

| Item | Situação | Quem fecha | Condição para fechar |
|---|---|---|---|
| Collection do fluxo completo | Duas provas locais e [execução no CI do platform #24](evidencias/newman-resumo.md#execução-no-ci-do-platform-24) aprovadas; CD da `main` aprovado; prova do congelamento pendente | Plataforma | Preservar a collection e comprovar o run sobre os commits finais, incluindo as métricas administrativas do OS; [fontes e resumos](evidencias/newman-resumo.md) |
| Ensaio final de observabilidade | Trace com os três serviços, 600,9 s sem tráfego, smoke e alerta com recuperação comprovados localmente; RNF-046/RNF-056 continuam parciais | Plataforma e serviços | Preservar capturas com três dias; chamada externa e observação no modo real do Billing dependem da sandbox |
| Evidência real do Mercado Pago | Simulador não comprova acesso à sandbox do provedor | Integrante com as credenciais da sandbox | Cobrança, aprovação e estorno reais, com saída sanitizada |
| Grupo, vídeo e submissão | RNF-053/RNF-054 ainda não podem ser encerrados | Grupo | Confirmar identificação; publicar vídeo; conferir acesso do avaliador; submeter o PDF final |

## Itens resolvidos

| Item | Como fechou |
|---|---|
| CD compartilhado dos três serviços | Definição no [platform #22](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-platform/pull/22), no commit `3f7cca2eb555a038b0d2780058ef0e692f93ee8a`. Chamadas no [OS #20](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-os-service/pull/20), na [Execução #15](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-execution-service/pull/15) e no [Billing #19](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-billing-service/pull/19), com CD da `main` aprovado nos três ([provas](evidencias/README.md#cd-compartilhado-dos-serviços)) |
| Telemetria do Billing | Host do chamador, classe da falha do coletor, prazo e smoke integrados no [Billing #18](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-billing-service/pull/18) |
| Itens transversais do Billing | Boot sem a telemetria automática do FastAPI, mensagem fixa na recusa, OpenAPI da saúde e do webhook, 503 com o MongoDB fora e prazo de 2 s na API, integrados no [Billing #17](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-billing-service/pull/17) |
| Descrição de `EstornoDePagamentoFalhou.motivo` | Mensagem fixa na fonte canônica pelo [platform #23](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-platform/pull/23); o `contratos/ORIGEM` dos três serviços aponta para o commit `15dd827b95a95d2dd717414fb5104ac9768b32ac` |

## Ensaio de observabilidade

Em 19/10/2026, o E2E local passou com 14 testes e três cenários de sandbox não selecionados, seguido de `smoke-servicos` aprovado. O trace `af146ea716424dfc2ac5b25960b8e9ae` contém os três serviços e o CLIENT Execução → Billing. O simulador não produz chamada HTTP externa; o CLIENT Billing → Mercado Pago permanece pendente da sandbox real.

O dashboard de bancos usa apenas as séries disponíveis no exporter, sem as `mongodb_ss_*`. A janela real de 600,9 s terminou sem reinícios, com 18 grupos de alvos disponíveis e três bancos acessíveis. O alerta controlado de fila disparou e recuperou, e o smoke posterior passou. O [relatório parcial](evidencias/observabilidade.md) preserva os commits, timestamps, trace e capturas do alerta. Capturas com uma hora de dados ainda não encerram a prova de três dias. O volume diário antes da primeira meia-noite UTC segue a limitação descrita no JSON.

## Dívida aceita e acompanhada

| Item | Limite atual | Quando revisar |
|---|---|---|
| Detalhe do cliente devolve o CPF/CNPJ completo aos papéis atendente e admin | Comportamento herdado; a decisão de minimização cabe ao grupo. Listagem usa valor mascarado e rotas de dados pessoais têm auditoria | Antes de mudar o contrato público; atualizar API, OpenAPI e collection juntos |
| Consultas dos coletores da Execução sem índice por data | Medidas registradas cabem no prazo de 2 s com o volume ensaiado; série indisponível não vira zero | Quando o crescimento aproximar as consultas do prazo ou o volume superar o medido |
| DNS do driver PostgreSQL não entra no prazo de conexão | A coleta HTTP termina no prazo, mas a thread pode aguardar resolução do nome | Se o DNS do cluster apresentar travamento; medir antes de introduzir resolução paralela |
| Método HTTP como rótulo aberto no Billing e na Execução | Métodos inesperados podem criar novas séries | Fechar vocabulário quando revisar o coletor; preservar GET/POST/PUT/PATCH/DELETE/HEAD/OPTIONS |
| OpenAPI do OS Service omite alguns erros HTTP | Login e operações de cliente podem devolver erros não declarados; o envelope permanece uniforme | Completar `responses` na origem e regenerar os dois contratos |
| Mutação de retenção da Execução | Falta caso entre 30 e 31 dias para separar a retenção correta de 30 dias | Próximo ajuste de retenção; usar um registro de 30,5 dias |
| Mutação de arredondamento de `Retry-After` no Billing | Testes usam espera inteira e não separam `ceil` de `floor` | Acrescentar espera fracionária e mutante correspondente |
| Digest do OWASP ZAP atualizado manualmente | Imagem fixada por digest; digest indisponível reprova o job | Atualização deliberada com scan e prova do script |
| Deploy remoto opcional | Não integra o ambiente kind entregue; requer acesso ao cluster e checkout do próprio serviço no job | Ao habilitar o gancho remoto; provar contexto, overlay e imagem por digest |
| Redrive manual depois de erasure | O runbook proíbe o procedimento, mas o script não conhece a remoção dos dados nem tem trava automática | Antes de automatizar redrive ou rever esse procedimento; preservar a proibição atual |
| Mailpit da demonstração | Sem autenticação ou política de ingresso; só o notificador tem restrição de saída, e as APIs podem alcançá-lo | Antes de usar dados reais ou expor esse ambiente; SMTP real exige STARTTLS e credenciais em Secret, conforme ADR-042 |
| Atualizações automáticas do Platform | Não há catálogo Dependabot no repositório; os pins atuais são atualizados deliberadamente | Quando ampliar a automação de dependências; manter verificação e revisão dos pins atuais |
| Import-linter do OS Service | A aplicação de dois contextos captura `sqlalchemy.exc.IntegrityError`, e faltam os contratos que o Billing e a Execução têm (domínio e aplicação sem framework; `compartilhado` sem contexto) | Na próxima mudança da aplicação do OS Service; mapear o erro para a exceção de domínio e copiar os dois contratos |
| Camada `interfaces` com ORM no Billing e na Execução | Routers e `comandos.py` montam repositórios concretos e leem tabelas ORM para retomar o trace | Ao mexer nos handlers de comando; montar tudo em `dependencies.py` ou no caso de uso |
| Grafia dos estados | O OS Service grava e expõe estados em minúsculas; Billing e Execução, em maiúsculas | Antes de mudar o contrato público das APIs; normalizar com versão nova |
| Tradução do contrato fora da infraestrutura | A RFC-004 põe a ACL na infraestrutura; o código traduz em `interfaces/comandos.py`, e o orquestrador consome a linguagem publicada sem tradução | Na próxima revisão da RFC-004, seção 3.1 |
| Base `compartilhado` copiada e divergente | OS e Execução guardam conceitos de domínio (CPF, placa, veículo) na base, e `IntegrationEvent` e o sufixo das exceções divergem entre os serviços | Ao alinhar a base técnica entre os três repositórios |
| Três estilos de evento | Evento de domínio acoplado ao contrato no Billing, fato de aplicação na Execução e evento de domínio mais comando de saga no OS Service | Ao criar o próximo evento de integração; registrar a regra no ADR-036 |
| Imports do contexto vizinho na borda | Adapters, routers e o coletor leem constantes e enums do domínio vizinho no mesmo serviço; o núcleo não importa | Quando o import-linter ganhar contrato para a borda |
| Funções e classes longas | Onze funções acima de 50 linhas no OS Service e três no Billing; agregados com máquina de estados acima de 300 linhas | Ao mexer nesses módulos; começar por `registrar_error_handlers` e `criar_app` |
| `Any` nos payloads JSON | Uso sem comentário em `dict[str, Any]` de payload nos três serviços | Na próxima mudança de payload; um alias `Json` por serviço |

Dívida aceita não dispensa o gate nem vale como prova. A revisão final deve confirmar se algum item ganhou impacto maior com as últimas alterações.

## Provas disponíveis

CD da `main` aprovado nos quatro repositórios:

- OS Service: [run 39357871773](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-os-service/actions/runs/39357871773), em `ffcc2c1`.
- Billing: [run 39358245264](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-billing-service/actions/runs/39358245264), em `f99e164`.
- Execução: [run 39357862805](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-execution-service/actions/runs/39357862805), em `a1ede85`.
- Plataforma: [run 39418143511](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-platform/actions/runs/39418143511), em `e74e41c`.

Cada CD de serviço roda os testes com o gate de cobertura de 95%, o SonarQube, a imagem, o kind e o E2E. A cobertura por camada está no [registro de cobertura](evidencias/coverage.md). Cada alteração posterior exige os mesmos gates e a atualização deste registro antes do congelamento.

## Origem dos repositórios

Todo commit da `main` entrou por pull request, exceto o commit inicial de cada repositório, criado pelo GitHub junto com ele. A [proteção da `main`](evidencias/protecao-da-main.md) traz o ruleset de cada repositório e a contagem de commits, e o [registro de evidências](evidencias/README.md#coleta-e-conferência-reproduzíveis) lista os quatro commits iniciais. O congelamento repete a conferência.
