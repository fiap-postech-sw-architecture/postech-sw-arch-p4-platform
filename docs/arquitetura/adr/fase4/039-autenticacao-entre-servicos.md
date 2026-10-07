# JWT RS256 emitido pelo OS Service e validado por JWKS

> [↑ Raiz do projeto](../../../../README.md) · [↑ Arquitetura](../../README.md)

* Status: Aceita
* Data: 2026-10-06

## Contexto e Problema

O enunciado separa o sistema em serviços, "cada um com seu próprio repositório, infraestrutura e banco de dados" (l. 27), e proíbe acesso direto ao banco de outro serviço (l. 67); ver [desafio-tech-fase-4.md](../../../requisitos/fase4/desafio-tech-fase-4.md).

Autenticação não aparece como requisito novo. A separação afeta o requisito não funcional RNF-036 da [gap analysis](../../../requisitos/fase4/gap-analysis-fase-4.md), pelo qual nenhum serviço acessa o banco de outro, e os requisitos funcionais de origem são os do p3 (código da fase 3, commit `08dcffe`): RF-009 (autenticação por token), RF-012 (revogação) e RF-014 (controle de acesso por papel).

A gap analysis registra o efeito da separação nas seções 3 e 5 e no risco "Revogação de JWT" da seção 12: o JWT (JSON Web Token) do p3 é assinado com segredo compartilhado em HS256, um HMAC (código de autenticação de mensagem com hash) com SHA-256, e a revogação consulta a tabela `tokens_revogados`, que o Billing Service e o Execution Service (contexto Execução) não podem ler.

No p3, o contexto `autenticacao` emite um access token de 30 min por padrão (`src/autenticacao/interfaces/dependencies.py:39`), com `sub`, `email`, `papel`, `type`, `jti`, `iat` e `exp` (`src/autenticacao/infraestrutura/jwt_service.py:36-46`), e um refresh de uso único, revogado na troca (`src/autenticacao/interfaces/router.py:114-132`). O middleware recusa refresh no lugar de access (dívida técnica TD-029) e consulta a revogação a cada requisição (`src/autenticacao/interfaces/middleware.py:48-72`); `exigir_papel` aplica o controle por papel, com `admin` herdando `atendente` e `mecanico`. O [ADR-004](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p3/blob/main/docs/arquitetura/adr/004-autenticacao-jwt.md) já anotava que, "em cenários multi-serviço, RS256 seria mais adequado".

Na fase 3, a Lambda de CPF assinava com o mesmo `JWT_SECRET` do app, e o [ADR-028](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p3/blob/main/docs/arquitetura/adr/fase3/028-autenticacao-serverless-cpf.md) deixou o conjunto de chaves públicas (JWKS, *JSON Web Key Set*) como evolução. A Lambda sai de escopo na fase 4 e, com ela, o token de cliente: o cliente acompanha a ordem de serviço (OS) pelo acompanhamento público e decide o orçamento por link assinado.

Sobre tokens, a Aula 04 de Estrutura de Microsserviços (Microsserviços I) recomenda evitar token estático, preferir OAuth 2.0 e tokens que expiram, "normalmente entre 5 a 15 minutos", e padronizar o 401 para não dar dicas a um atacante sobre a validade da credencial; a validação de JWT no gateway só aparece num rótulo de figura (Aula 03, Fig. 1). Estrutura de Microsserviços Parte II (Microsserviços II) cita tokens OAuth 2.0/JWT para os clientes e TLS mútuo (mTLS) entre serviços (Aula 05). JWKS e autenticação entre serviços não são cobertos.

**Como Billing e Execução validam identidade e papel do usuário sem segredo compartilhado e sem consultar o OS Service a cada requisição?**

## Decisão

### Emissor único

O OS Service, dono do contexto `autenticacao` herdado do p3, é o único emissor de tokens (`/api/v1/autenticacao/login`, `refresh` e `logout`).

- Claims: `iss=pytstop-os-service`, `aud=pytstop`, `sub`, `papel`, `type` (`access` ou `refresh`), `jti`, `iat` e `exp`, de 15 min no access token. O `email` do p3 sai, porque o token agora circula entre serviços. O refresh rotativo de uso único continua, validado só pelo OS Service.
- Assinatura RS256 (RSA com SHA-256), com chave de 2048 bits. A chave privada existe só no OS Service, num Secret gerado no cluster; a pública fica em `GET /.well-known/jwks.json`, identificada por `kid`.

### Validação local

Billing e Execução conferem assinatura, `iss`, `aud`, `exp` e `type=access` com a chave do JWKS, com o algoritmo fixado em RS256 (a defesa contra troca de algoritmo do ADR-004) e tolerância de relógio (`leeway`) de 10 s. O cliente é o `PyJWKClient(uri, lifespan=600, timeout=2)` do PyJWT, com `pyjwt>=2.15.1`: cache de 10 min e timeout de 2 s, e, desde a 2.14.0, a nova busca disparada por `kid` desconhecido tem limite, o que impede forçar buscas seguidas com tokens forjados. Não há chamada ao OS Service por requisição. Com o JWKS indisponível e nenhuma chave em cache, a resposta é 503 com `Retry-After`, e não 401, porque o problema é a disponibilidade do OS Service, e não a credencial apresentada.

Falha de credencial responde 401 com a mesma mensagem nos três serviços, como recomenda a Aula 04, no envelope de erro do p3 (`{"erro": {"codigo", "mensagem", "id_requisicao"}}`): token ausente, malformado, com assinatura inválida, expirado, com `iss` ou `aud` errados, sem `papel` ou com `papel` desconhecido, com `type` diferente de `access` (um refresh no lugar do access, por exemplo) e, só no OS Service, revogado. Papel válido e insuficiente continua 403, como no p3. A Aula 04 sugere 404 para rota administrativa sem permissão, mas as rotas já aparecem no Swagger público, e um 404 não as esconderia.

### Revogação

O logout revoga o `jti` em `tokens_revogados`, que só o OS Service consulta. Em Billing e Execução, o limite é a expiração: um token revogado vale por até 15 min. Introspecção por requisição traria de volta a chamada que a validação local evita, e um evento de revogação exigiria uma lista de negação com estado em cada serviço; para uma janela de 15 min, nenhum dos dois compensa.

### Papel por rota

Esta é a matriz única de autorização; a [RFC-004](../../rfc/fase4/rfc-004-microsservicos-saga.md) e o [ADR-038](038-borda-e-comunicacao-sincrona.md) apontam para ela. `admin` herda `atendente` e `mecanico`, como no p3, e por isso a tabela mostra o papel mínimo.

| Serviço | Rota | Papel mínimo |
|---|---|---|
| todos | `GET /api/v1/saude`, `GET /api/v1/saude/pronto`, `GET /metrics` | sem token; `/metrics` fica fora da borda |
| todos | `/api/v1/admin/*` (linhas `dead` da outbox) | `admin`; fora da borda |
| OS Service | `POST /api/v1/autenticacao/login`, `GET /.well-known/jwks.json`, `POST /api/v1/publico/acompanhamento` | público |
| OS Service | `POST /api/v1/autenticacao/refresh` e `/logout` | portador do token |
| OS Service | `POST /api/v1/autenticacao/registrar` (cadastro de usuário interno) | `admin` |
| OS Service | clientes e veículos (`/api/v1/clientes`), com acesso e portabilidade dos dados pessoais | `atendente` |
| OS Service | exclusão dos dados pessoais pela LGPD (Lei Geral de Proteção de Dados) | `admin` |
| OS Service | `/api/v1/ordens-de-servico`: abrir, listar, consultar, histórico, cancelamento e entrega | `atendente` |
| OS Service | `GET /api/v1/ordens-de-servico/metricas` | `admin` |
| OS Service | `GET /api/v1/sagas/{ordem_id}` e `POST /api/v1/sagas/{ordem_id}/compensacao` | `admin` |
| Billing | leitura de `/api/v1/precos/servicos` e `/api/v1/precos/pecas` | `atendente` ou `mecanico` |
| Billing | escrita nas tabelas de preço | `admin` |
| Billing | `POST /api/v1/precos/validacao` | `mecanico` |
| Billing | `GET /api/v1/orcamentos/{id}`, `GET /api/v1/orcamentos?ordem_id=`, `POST /api/v1/orcamentos/{id}/decisao`, `GET /api/v1/pagamentos/{id}` | `atendente` |
| Billing | `GET /api/v1/publico/orcamentos/{token}` e `POST /api/v1/publico/orcamentos/{token}/decisao` | público, com o token do link |
| Billing | `POST /api/v1/webhooks/mercadopago` | público, com `x-signature` ([ADR-040](040-integracao-mercado-pago.md)) |
| Billing | rotas do simulador, só com `MP_MODE=simulado` | público, com o token do `checkout_url` |
| Execução | leitura de `/api/v1/fila` e de `/api/v1/estoque` | `atendente` ou `mecanico` |
| Execução | `/api/v1/diagnosticos` e `/api/v1/execucoes` | `mecanico`; a conclusão do diagnóstico e a finalização da execução, só o mecânico que os iniciou ou o `admin` em nome dele |
| Execução | escrita em `/api/v1/estoque` e ajuste de quantidade | `admin` |

O mecânico não tem rota de negócio no OS Service: depois do login, trabalha só nas filas da Execução.

### Link de decisão

O token do link é `orcamento_id` e `exp` assinados com HMAC-SHA256 por uma chave que só o Billing tem, com `exp` igual ao `valido_ate` do orçamento: é a primitiva do canal externo de decisão do p3 ([ADR-021](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p3/blob/main/docs/arquitetura/adr/fase2/021-aprovacao-externa-orcamento.md)). A conferência usa `compare_digest`. Token inválido, expirado ou de orçamento já decidido recebe a mesma resposta, um 404 genérico, e a decisão é única. O `{token}` é mascarado no access log, nos spans (`url.path`) e nos logs, e `link_decisao` e `checkout_url` entram na lista de campos sensíveis da limpeza de logs ([ADR-043](043-observabilidade-distribuida.md)).

### Auditoria e propagação

Decisão em nome do cliente e ação privilegiada deixam o `sub` de quem agiu. `OrcamentoAprovado` e `OrcamentoRecusado` levam `decidido_por` quando `canal=atendente`, o histórico da OS guarda o `ator` de cada transição, e cancelamento, ajuste de estoque, mudança de preço, ação do `admin` em nome do mecânico, reprocessamento de linha `dead` da outbox e retomada de compensação geram log de auditoria com `sub`, ação e alvo, como a API administrativa do p3 já fazia (`src/compartilhado/interfaces/router_admin.py:82-86`).

Na chamada síncrona de negócio, a Execução repassa ao Billing o `Authorization` do mecânico ([ADR-038](038-borda-e-comunicacao-sincrona.md)). Não existe identidade de serviço.

### Segredos

Nenhum segredo de aplicação fica no GitHub, por onde o `JWT_SECRET` do p3 passava ([ADR-033](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p3/blob/main/docs/arquitetura/adr/fase3/033-cicd-multi-repo.md), adendo d). A chave RSA e a chave HMAC do link são geradas no cluster pelo deploy, só se ausentes, em qualquer cluster; no kind do CI o cluster é novo a cada execução, e as chaves também. A chave HMAC, sem estado, gira apagando o Secret, reimplantando e reiniciando o Billing, que a lê no start; a chave RSA gira em duas etapas (consequências negativas abaixo); senhas de banco e de broker e a chave que cifra os dados pessoais seguem as regras do [ADR-042](042-cicd-e-deploy-kubernetes.md). A guarda de boot do p3 contra literal de demonstração fora do ambiente de desenvolvimento passa a cobrir também a chave RSA.

## Alternativas Consideradas

* RS256 com JWKS e emissor único
* HS256 com segredo compartilhado
* Validação centralizada no gateway (plugin JWT do Kong)
* mTLS ou service mesh
* OAuth 2.0 com provedor de identidade externo (Keycloak ou Cognito)

### RS256 com JWKS e emissor único

* Bom, porque só o OS Service tem a chave que emite token; Billing e Execução recebem apenas material público
* Bom, porque a validação é local e o papel vem no token, então o controle por papel do p3 (`exigir_papel`) roda em cada serviço sem chamada de rede
* Bom, porque JWKS com `kid` é formato padrão, e o `PyJWKClient` do PyJWT, biblioteca já usada no p3, traz cache, timeout e nova busca com limite para `kid` desconhecido
* Ruim, porque a revogação não vale fora do OS Service até o token expirar
* Ruim, porque Billing e Execução dependem do JWKS do OS Service a cada renovação do cache

### HS256 com segredo compartilhado

* Bom, porque é o que o p3 e a Lambda da fase 3 já faziam: nenhuma mudança no `JWTService`
* Ruim, porque o segredo existiria nos três serviços, e qualquer um deles emitiria token com qualquer papel: um Billing comprometido forjaria um `admin`
* Ruim, porque a rotação trocaria o mesmo valor em três deploys coordenados

### Validação centralizada no gateway (plugin JWT do Kong)

* Bom, porque concentra a validação num ponto, como o "Valida JWT" da figura da Aula 03
* Ruim, porque o plugin `jwt` confere a assinatura com a chave pública cadastrada numa credencial de consumidor e verifica `exp` e `nbf`, sem buscar JWKS: a rotação vira reconfiguração do Kong, e a documentação não menciona conferência de `aud`
* Ruim, porque os serviços continuariam lendo o `papel` para o controle por papel, e uma requisição que não passe pela borda (chamada interna, port-forward da demonstração) chegaria sem validação; o p3 manteve a validação no app atrás do gateway por esse motivo ([ADR-027](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p3/blob/main/docs/arquitetura/adr/fase3/027-api-gateway-aws.md))

### mTLS ou service mesh

* Bom, porque autentica serviço com serviço e cifra o tráfego interno
* Bom, porque o Istio é o hands-on da Aula 05 de Microsserviços II
* Ruim, porque identifica a carga de trabalho, não o usuário: o papel do mecânico continuaria exigindo token
* Ruim, porque sidecars em todos os pods pesam no kind, e a malha se justificaria só por uma chamada síncrona de negócio e pela busca do JWKS

### OAuth 2.0 com provedor de identidade externo (Keycloak ou Cognito)

* Bom, porque é o padrão que a Aula 04 recomenda
* Bom, porque JWKS, revogação, introspecção e login único vêm prontos
* Ruim, porque o Keycloak é mais um serviço com banco próprio no cluster, e usuários, login, refresh e logout do p3, com seus testes, teriam de migrar para ele
* Ruim, porque o Cognito prende a autenticação à AWS, fora dos alvos da fase (kind e k3s na Azure), e já foi descartado no ADR-028; o ADR-004 recusou provedor externo pelo custo desproporcional

## Consequências

### Positivas

* Nenhum segredo compartilhado entre serviços: comprometer Billing ou Execução não permite emitir token
* Validação sem chamada ao OS Service por requisição, que continua funcionando com ele fora do ar enquanto o cache valer
* A chave privada nunca passa pelo GitHub; no kind, cada execução da integração contínua gera uma nova
* Expiração de 15 min, dentro da faixa da Aula 04, limita o uso de um token roubado
* Decisão em nome do cliente e ação privilegiada têm autor registrado

### Negativas

* Token revogado no logout continua aceito por Billing e Execução por até 15 min
* Com o OS Service fora do ar por mais tempo que o cache, Billing e Execução respondem 503 nas rotas autenticadas até ele voltar
* Girar a chave RSA pede duas etapas: primeiro o JWKS publica a chave nova ao lado da atual (`JWT_PREVIOUS_PUBLIC_KEY` guarda a chave que entra), depois a nova passa a assinar e a variável guarda a que sai, até os tokens antigos vencerem; com várias réplicas, trocar de uma vez faria um pod antigo recusar os tokens de um pod novo durante o rollout
* Com `aud` único, um token vale nos três serviços, o que a propagação exige, mas amplia o alcance de um token roubado durante os 15 min
* O tráfego interno, inclusive o `Authorization` propagado e a busca do JWKS, corre sem TLS dentro do cluster: risco aceito do ambiente de demonstração, limitado pela NetworkPolicy do [ADR-042](042-cicd-e-deploy-kubernetes.md)
* O 401 uniforme torna o diagnóstico menos direto para quem chama; o motivo da recusa fica no log, ligado ao identificador da requisição (`id_requisicao` na resposta, `request_id` no log)

### Neutras

* Token expirado há menos de 10 s ainda é aceito, folga para a diferença de relógio entre pods

## Decisões Relacionadas

- [ADR-004](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p3/blob/main/docs/arquitetura/adr/004-autenticacao-jwt.md): JWT, revogação por `jti` e refresh rotativo; a ressalva sobre RS256
- [ADR-028](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p3/blob/main/docs/arquitetura/adr/fase3/028-autenticacao-serverless-cpf.md): HS256 compartilhado com a Lambda e JWKS deixado como evolução
- [ADR-021](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p3/blob/main/docs/arquitetura/adr/fase2/021-aprovacao-externa-orcamento.md): HMAC no canal externo de decisão, reaproveitado no link do Billing
- [ADR-038](038-borda-e-comunicacao-sincrona.md): a chamada que propaga o token; o Kong não valida JWT
- [ADR-040](040-integracao-mercado-pago.md): verificação do webhook por `x-signature`
- [ADR-042](042-cicd-e-deploy-kubernetes.md): geração dos Secrets no deploy e NetworkPolicy
- [ADR-043](043-observabilidade-distribuida.md): limpeza de logs e métricas de falha do JWKS

## Notas

* Material: Estrutura de Microsserviços, Aulas 03 e 04; Estrutura de Microsserviços Parte II, Aula 05
* JSON Web Key (RFC 7517): https://www.rfc-editor.org/rfc/rfc7517; JWT (RFC 7519): https://www.rfc-editor.org/rfc/rfc7519; plugin JWT do Kong: https://developer.konghq.com/plugins/jwt/; histórico de versões do PyJWT: https://pyjwt.readthedocs.io/en/latest/changelog.html

> [↑ Raiz do projeto](../../../../README.md) · [↑ Arquitetura](../../README.md)
