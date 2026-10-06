# Kong na borda e REST síncrono só quando a resposta é necessária na hora

> [↑ Raiz do projeto](../../../../README.md) · [↑ Arquitetura](../../README.md)

* Status: Aceita
* Data: 2026-10-06

## Contexto e Problema

O enunciado pede "APIs RESTful síncronas (quando necessário)" (l. 65) ao lado da mensageria e proíbe que um serviço acesse "diretamente o banco de outro serviço" (l. 67); ver [desafio-tech-fase-4.md](../../../requisitos/fase4/desafio-tech-fase-4.md). Na [gap analysis](../../../requisitos/fase4/gap-analysis-fase-4.md), o requisito não funcional RNF-034 limita o REST aos casos em que a resposta é necessária na hora, com timeout, retry e circuit breaker, e o RNF-055 reúne a tolerância a falhas.

A seção 5 da gap analysis registra a regra: "REST quando quem chama precisa da resposta para continuar e a operação só lê; mensagem quando a operação muda estado em outro serviço". O gateway não volta como exigência na fase 4; vem do requisito funcional RF-026 da fase 3 (API Gateway protegendo rotas sensíveis, com controle e roteamento), papel que a borda mantém.

No p3 (código da fase 3, commit `08dcffe`), REST só existe na borda: entre contextos, as chamadas são em processo, por portas Python (`src/ordem_servico/aplicacao/ports.py:88-196`), e não há cliente HTTP no código. A borda variou por ambiente: port-forward no kind e Amazon API Gateway no Amazon EKS.

O [ADR-027](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p3/blob/main/docs/arquitetura/adr/fase3/027-api-gateway-aws.md) do p3 rejeitou o Kong porque a integração com a Lambda exigiria credenciais AWS temporárias dentro do cluster e porque o Kong com banco próprio seria mais uma peça a operar num laboratório refeito a cada sessão; a fase 4 não tem Lambda nem AWS. O rate limit do p3 roda em processo, com contador num Redis ([ADR-023](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p3/blob/main/docs/arquitetura/adr/fase2/023-rate-limiter-storage-compartilhado.md)), e um Redis comum aos três serviços seria lido como banco compartilhado (gap analysis, seção 12).

Kong é o API Gateway das Aulas 03 e 04 de Estrutura de Microsserviços (Microsserviços I): autenticação, rate limit com HTTP 429, métricas e logs por política, ao custo de "mais um componente" que é "um ponto central na comunicação entre clientes e serviços" (Aula 03). Para a chamada síncrona, a Aula 02 lista os contras, "Redução de disponibilidade" e "Lentidão propagada para cliente", e o Circuit Breaker, que abre, por exemplo, com "mais de 5 falhas nos últimos 2 minutos". Para consultas, a Aula 05 recomenda API Composition e reserva a separação de comando e consulta (CQRS), com visão replicada por eventos, para quando a composição inviabilizar a operação.

**Por onde entra o tráfego externo e quando um serviço pode chamar outro por REST síncrono?**

## Decisão

### Borda

Kong como API Gateway, pelo Kong Ingress Controller em modo DB-less: a configuração vem de recursos do Kubernetes (Ingress e `KongPlugin`), sem banco próprio do Kong. O `platform` instala o Kong no kind e no k3s, e cada serviço declara o próprio Ingress no seu `k8s/`. O controlador roda com o feature gate `FallbackConfiguration`, alpha no Kong Ingress Controller 3.5: um Ingress ou plugin inválido de um serviço sai da configuração, com evento registrado no objeto, e o resto continua aplicado. Sem ele, o Kong DB-less recusaria a configuração inteira, e um Kong reiniciado subiria sem rota.

- Rotas `/os`, `/billing` e `/execucao`, uma por serviço (OS Service, de ordens de serviço, OS; Billing Service; Execution Service, do contexto Execução). O Kong remove o prefixo, e cada serviço continua com `/api/v1/...`.
- O Ingress expõe só o necessário: `/api/v1/*` de cada serviço, `/docs` e `/openapi.json` (o Swagger é entregável, l. 113) e dois caminhos públicos fora de `/api/v1`, o conjunto de chaves públicas do OS Service (JWKS, `/.well-known/jwks.json`) e a página de checkout do simulador do Billing (`/simulador/checkout/*`, só com `MP_MODE=simulado`). `/metrics` e `/api/v1/admin/*` ficam fora da borda, barrados pelo plugin `request-termination`; o Prometheus raspa os pods direto ([ADR-043](043-observabilidade-distribuida.md)).
- Plugin `correlation-id` com o header `X-Request-ID`, o mesmo que os logs do p3 usam, e `generator: uuid`. O gerador padrão do plugin, `uuid#counter`, produz um valor com `#`, que o middleware do p3 descarta por não casar com `[A-Za-z0-9._=-]{1,128}` (`src/compartilhado/interfaces/middleware.py:39`), e o ID da borda se perderia.
- Plugin `prometheus`, com as métricas da borda, e plugin `rate-limiting`, descrito abaixo.
- O Kong não valida o token JWT (JSON Web Token): cada serviço o valida, e a matriz de papel por rota fica no [ADR-039](039-autenticacao-entre-servicos.md).
- O compartilhamento entre origens (CORS) não se aplica: a fase não tem interface web, e os serviços não liberam nenhuma origem, como no p3.

### Rate limit

Por IP do cliente, com `policy: local`. O `kong-proxy` usa `externalTrafficPolicy: Local`, que entrega o pacote sem a tradução do endereço de origem (SNAT) feita pelo kube-proxy: no k3s, o IP real do cliente chega ao Kong. No kind, o tráfego entra pelo mapeamento de porta do Docker, e todo cliente do host chega com o IP da bridge, num balde só por limite, o que basta para a demonstração. Se um balanceador ou proxy entrar na frente da máquina virtual do k3s, `trusted_ips` com o CIDR exato dele e `real_ip_header` passam a ler o IP do header. Onde a rota já existia no p3, vale o limite dele:

| Rota | Limite por IP | Origem do valor |
|---|---|---|
| `POST /api/v1/autenticacao/login` | 5/min | p3 |
| `POST /api/v1/autenticacao/refresh` e `/logout` | 10/min | p3 |
| `POST /api/v1/publico/acompanhamento` | 10/min | p3 |
| link de decisão (`/api/v1/publico/orcamentos/{token}`) | 10/min | canal externo de decisão do p3 |
| rotas do simulador | 10/min | o mesmo do link |
| `GET /.well-known/jwks.json` | 60/min | limite global; quem valida guarda a chave em cache |
| `POST /api/v1/webhooks/mercadopago` | 120/min, em balde próprio | folga para as rajadas e os reenvios do provedor |
| demais rotas | 60/min | limite global do p3 |

Nos overlays do kind, local e `kind-ci`, os limites são multiplicados por 10, para que os testes ponta a ponta (E2E) e a demonstração não recebam 429 ([ADR-042](042-cicd-e-deploy-kubernetes.md)).

### Chamada síncrona de negócio

Há uma só entre serviços: na conclusão do diagnóstico, a Execução chama o Billing em `POST /api/v1/precos/validacao {servicos[], pecas[]} -> {invalidos[]}`.

- Antes da chamada, a Execução valida o estado local: diagnóstico em andamento, mecânico dono, itens e quantidades e peças com `sku` (código de estoque) cadastrado no estoque. Só o que passa localmente vai ao Billing, o custo-gradiente que o p3 aplica ao validar o status antes de reservar (`src/ordem_servico/aplicacao/use_cases.py:484-486`).
- Timeout de 2 s e 2 retries com jitter, só em timeout, erro de rede e 502, 503 ou 504 do Billing; o retry é seguro porque a validação não muda estado.
- Circuit breaker: abre com 5 falhas e fica aberto por 30 s; depois deixa passar chamadas de teste (semiaberto, Aula 02). Com o circuito aberto, ou com 5xx e timeout depois dos retries, a conclusão responde 503 com mensagem acionável e não grava nada; o mecânico tenta de novo.
- Um 4xx do Billing vira 502 na Execução, sem retry, porque repetir a chamada não muda a resposta; a conclusão também não grava nada.
- O `Authorization` do mecânico é propagado, e o Billing autoriza a rota pela matriz do ADR-039 (mecânico e admin); o `traceparent` segue pela instrumentação do httpx.

A chamada fica síncrona, apesar dos contras da Aula 02, por três motivos. O mecânico precisa saber na hora que um código de serviço ou peça não existe, para corrigir antes de o diagnóstico sair. A falha é visível (503) e recuperável, porque nada fica pela metade. E a autoridade continua no Billing: `GerarOrcamento` falha com `GeracaoDeOrcamentoFalhou{codigos_invalidos}` se a tabela mudar entre a validação e o orçamento ([ADR-035](035-saga-orquestrada.md)), e a validação só antecipa o erro para o mecânico.

### Dependência do JWKS

Billing e Execução buscam o JWKS no OS Service para validar tokens, com cache de 10 min e timeout de 2 s ([ADR-039](039-autenticacao-entre-servicos.md)). Não é chamada de negócio, mas é a segunda dependência HTTP entre serviços: com o OS Service fora do ar além do cache, os dois respondem 503 nas rotas autenticadas.

### Consultas e Mercado Pago

Status e histórico são leitura local do OS Service, que recebe os fatos por evento; `GET /api/v1/ordens-de-servico/{id}` já traz o resumo de orçamento, pagamento e etapa da saga (RF-030). API Composition só entra se surgir uma tela que junte os três serviços; CQRS fica fora, pela regra da Aula 05.

O Mercado Pago é dependência externa do Billing, com o mesmo envelope (timeout, retry só em operação idempotente, circuit breaker), detalhado no [ADR-040](040-integracao-mercado-pago.md).

## Alternativas Consideradas

* Kong DB-less na borda e uma chamada síncrona de negócio protegida
* ingress-nginx ou Traefik puros
* BFF dedicado
* Visão replicada de preços na Execução
* gRPC entre serviços

### Kong DB-less na borda e uma chamada síncrona de negócio protegida

* Bom, porque é o gateway das Aulas 03 e 04, aqui como controlador de Ingress: rotas e plugins viram manifestos versionados
* Bom, porque correlação, rate limit e métricas saem de plugins, sem código nos serviços, e o rate limit na borda dispensa um Redis comum
* Bom, porque os motivos que afastaram o Kong na fase 3 não valem mais: não há Lambda nem AWS, e o modo DB-less dispensa o banco do Kong
* Ruim, porque são dois contêineres a mais (proxy e controlador) e um ponto central que, fora do ar, corta o tráfego externo (Aula 03)
* Ruim, porque a conclusão do diagnóstico passa a depender do Billing no ar

### ingress-nginx ou Traefik puros

* Bom, porque são controladores de Ingress comuns, e o Traefik já vem instalado no k3s
* Ruim, porque o ingress-nginx foi aposentado pelo Kubernetes: manutenção só até março de 2026, sem correção de segurança depois
* Ruim, porque o Traefik não aparece no material (o mesmo motivo da rejeição no ADR-027) e não vem no kind
* Ruim, porque correlação, rate limit e métricas seriam montados com anotações e middlewares de cada controlador, em vez das políticas de gateway da Aula 03

### BFF dedicado

Um *backend for frontend*, o padrão da Aula 03 para agregar e formatar dados para uma interface.

* Bom, porque concentraria a composição de dados de uma tela fora dos serviços de domínio
* Ruim, porque a fase não tem interface própria (a UI NiceGUI ficou fora de escopo; a demonstração usa Swagger, Postman e scripts): seria um quarto serviço sem cliente
* Ruim, porque a consulta que o enunciado pede, status e histórico, já é local no OS Service

### Visão replicada de preços na Execução

* Bom, porque elimina a chamada síncrona de negócio: a validação fica local e funciona com o Billing fora do ar, como no hands-on da Aula 05
* Ruim, porque a Execução passaria a consumir eventos de outro participante, contra a orquestração pura ([ADR-036](036-mensageria-rabbitmq.md)), e o Billing publicaria eventos de preço que não estão no catálogo
* Ruim, porque exige carga inicial e cargas delta (Aula 05) e pode estar defasada justo quando o admin acaba de cadastrar uma peça nos dois serviços, recusando um código válido
* Ruim, porque a própria Aula 05 reserva esse caminho para quando a composição inviabilizar a operação, e aqui há uma chamada só

### gRPC entre serviços

* Bom, porque traz contrato tipado (protobuf) e HTTP/2
* Bom, porque cliente e servidor nascem do mesmo arquivo `.proto`
* Ruim, porque o material só o mostra num rótulo de figura, sem texto (Aula 03, Fig. 2)
* Ruim, porque o enunciado pede Swagger ou Postman por serviço: seria um segundo tipo de contrato para uma única chamada, cujo desempenho não é problema

## Consequências

### Positivas

* RNF-034 atendido com uma chamada síncrona de negócio justificada; RNF-055 com timeout, retry, circuit breaker e 503 explícito
* Entrada única, com `X-Request-ID` desde a borda, rate limit por IP do cliente em todas as rotas e métricas de borda no Prometheus
* `/metrics` e a API administrativa da outbox não ficam expostas na borda
* A consulta de status e histórico não depende de outro serviço: com Billing ou Execução fora do ar, o OS Service continua respondendo

### Negativas

* A conclusão do diagnóstico exige Billing e Execução no ar ao mesmo tempo, a redução de disponibilidade da Aula 02; com o Billing lento, o mecânico espera até três chamadas de 2 s antes de o circuito abrir
* Em DB-less, o `rate-limiting` só tem as políticas `local` e `redis`, porque a `cluster` guarda contadores no datastore do Kong; sem Redis, o limite vale por réplica do proxy, exato com uma réplica e frouxo se o Kong escalar, o problema que o ADR-023 resolveu com Redis
* A validação de token em Billing e Execução depende do OS Service no ar a cada renovação do cache do JWKS
* O k3s instala o Traefik por padrão: é preciso desativá-lo (`--disable=traefik`) ou apontar a classe de Ingress para o Kong
* Caminho novo fora de `/api/v1` exige mudar o Ingress do serviço, e a lista do que a borda expõe acompanha cada serviço (Aula 03: toda alteração nos serviços se reflete no gateway)

### Neutras

* Com o prefixo removido na borda, o Swagger de cada serviço precisa conhecer o prefixo externo (`root_path` do FastAPI); o E2E confere que `/{serviço}/docs` abre pela borda ([ADR-041](041-estrategia-de-testes-e-qualidade.md))

## Decisões Relacionadas

- [ADR-027](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p3/blob/main/docs/arquitetura/adr/fase3/027-api-gateway-aws.md): gateway da fase 3; o motivo da rejeição do Kong deixa de existir
- [ADR-023](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p3/blob/main/docs/arquitetura/adr/fase2/023-rate-limiter-storage-compartilhado.md): rate limit com Redis, cujo papel passa para a borda
- [ADR-036](036-mensageria-rabbitmq.md): tudo que muda estado em outro serviço vai por mensagem
- [ADR-039](039-autenticacao-entre-servicos.md): validação do JWT, JWKS e matriz de papel por rota
- [ADR-040](040-integracao-mercado-pago.md): o Mercado Pago sob o mesmo envelope de resiliência
- [ADR-042](042-cicd-e-deploy-kubernetes.md): instalação do Kong e overlays do kind e do k3s
- [ADR-043](043-observabilidade-distribuida.md): métricas de borda e de circuit breaker

## Notas

* Material: Estrutura de Microsserviços, Aulas 02 (p. 14-15), 03, 04 e 05
* Os valores de timeout, retry e circuit breaker vêm da Aula 02; a disciplina Resiliência em Microsserviços não tinha sido liberada até 06/10/2026
* Kong: plugins `correlation-id` (https://developer.konghq.com/plugins/correlation-id/) e `rate-limiting` (https://developer.konghq.com/plugins/rate-limiting/); Kong Ingress Controller (https://developer.konghq.com/kubernetes-ingress-controller/)
* Aposentadoria do ingress-nginx: https://kubernetes.io/blog/2025/11/11/ingress-nginx-retirement/; Traefik no k3s: https://docs.k3s.io/networking/networking-services; FastAPI atrás de proxy com prefixo: https://fastapi.tiangolo.com/advanced/behind-a-proxy/

> [↑ Raiz do projeto](../../../../README.md) · [↑ Arquitetura](../../README.md)
