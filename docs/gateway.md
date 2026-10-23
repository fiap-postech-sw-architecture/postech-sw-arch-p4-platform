# Gateway: como um serviço publica as rotas

> [↑ Raiz do projeto](../README.md)

O serviço cria os próprios Ingress, no próprio namespace, com `ingressClassName: kong`, a partir do exemplo do OS ([`borda-os-service.yaml`](../k8s/exemplos/borda-os-service.yaml)) ou do Billing ([`borda-billing-service.yaml`](../k8s/exemplos/borda-billing-service.yaml), com o webhook do Mercado Pago e o checkout do simulador); a Execução, do dela ([`borda-execution-service.yaml`](../k8s/exemplos/borda-execution-service.yaml), o molde do OS sem JWKS nem rotas públicas). O `make smoke` aplica os três exemplos no kind como estão. Pela borda só saem os caminhos que o [ADR-038](arquitetura/adr/fase4/038-borda-e-comunicacao-sincrona.md) permite: `/api/v1/*`, `/docs` e `/openapi.json` de cada serviço, o JWKS (*JSON Web Key Set*, as chaves públicas do JWT) do OS e o checkout do simulador do Billing. `/metrics` e `/api/v1/admin/*` casam um Ingress anotado com o plugin `fora-da-borda`, que responde 404 sem chamar o serviço; como o Kong escolhe o caminho mais longo, esse Ingress vence o de `/api/v1`.

Com `strip-path`, o Kong tira do caminho tudo o que a regra casou e põe no lugar o `konghq.com/path` do Service de destino: `/os/api/v1/x` casa a regra `/os/api/v1` e chega ao serviço como `/api/v1` + `/x`. Por isso cada prefixo publicado tem um Service próprio, todos com os mesmos pods; o Service interno do serviço (o do `JWKS_URL` e do `BILLING_URL`) fica sem a anotação.

Barra codificada: o Kong casa as rotas por segmento e não trata `%2F` (nem `%5C`) como `/`, e o uvicorn dos serviços decodifica o `%2F` do caminho. Sem proteção, `/os/api/v1/admin%2Foutbox` passaria pelo Ingress de `/os/api/v1` em vez de cair no `fora-da-borda`, e `/os/api/v1/autenticacao%2Flogin` ficaria fora do limite de 5/min do login. O plugin global `bloqueia-barra-codificada` (um `pre-function` em [`plugins.yaml`](../k8s/base/kong/plugins.yaml)) responde 404 a todo caminho com `%2F` ou `%5C`, em maiúsculas ou minúsculas, antes de qualquer rota e de qualquer rate limit; esse 404 não gasta balde. Só o caminho conta: `%2F` na query string passa. O resto o Kong já normaliza antes de casar a rota (barras repetidas, `.` e `..` e letra codificada como `%61`), e as demais grafias que passam, como `%252F`, `;x=1` e `ADMIN`, o FastAPI trata como outro caminho. O `make smoke` prova com sondas `%2F` ao admin, ao login, ao acompanhamento e ao link de decisão do Billing, mais três grafias do caminho do admin, e sai com status 1 se alguma não responder 404.

Os plugins são `KongClusterPlugin`, que o Ingress de qualquer namespace pode usar ([`plugins.yaml`](../k8s/base/kong/plugins.yaml)). `correlation-id`, `prometheus`, `bloqueia-barra-codificada` e `rate-limiting-global` são globais e valem para toda rota sem anotação; os outros entram pela anotação `konghq.com/plugins`. O rate limiting conta por IP do cliente, com contador local no pod do Kong. O global usa um balde por IP para todas as rotas que não têm plugin de rate limiting próprio, e cada rota anotada conta num balde só dela.

| Serviço | Caminho na borda | Plugin | Limite por IP |
|---|---|---|---|
| OS | `POST /os/api/v1/autenticacao/login` | `rate-limiting-login` | 5/min |
| OS | `/os/api/v1/autenticacao/*` (refresh, logout e registrar) | `rate-limiting-sessao` | 10/min |
| OS | `/os/api/v1/publico/*` (acompanhamento) | `rate-limiting-publico` | 10/min |
| OS | `GET /os/.well-known/jwks.json` | `rate-limiting-jwks` | 60/min |
| Billing | `/billing/api/v1/publico/*` (link de decisão) | `rate-limiting-publico` | 10/min |
| Billing | `/billing/simulador/checkout/*` e `/billing/api/v1/simulador/*` | `rate-limiting-publico` | 10/min |
| Billing | `POST /billing/api/v1/webhooks/mercadopago` | `rate-limiting-webhook` | 120/min |
| todos | demais rotas de `/api/v1/*`, `/docs` e `/openapi.json` | `rate-limiting-global` (sem anotação) | 60/min |
| todos | `/metrics` e `/api/v1/admin/*` | `fora-da-borda` | sempre 404 |
| todos | qualquer caminho com `%2F` ou `%5C` | `bloqueia-barra-codificada` (global) | sempre 404 |

No overlay kind os limites são multiplicados por 10 ([`rate-limit-x10.yaml`](../k8s/overlays/kind/rate-limit-x10.yaml)), para que o E2E e a demonstração não recebam 429.

IP do cliente: o `kong-proxy` usa `externalTrafficPolicy: Local`, que entrega o pacote sem o SNAT (*source NAT*) do kube-proxy. No kind, o tráfego entra pelo mapeamento de porta do Docker, e todo cliente do host chega com o IP do gateway da rede do Docker: um balde só por limite, o que basta para a demonstração. No k3s, o ServiceLB com `externalTrafficPolicy: Local` deve entregar o IP de origem, mas isso ainda não foi conferido com dois clientes: até lá, o limite por IP no k3s é esperado, não verificado. Se um balanceador ou proxy entrar na frente da VM, configure em [`values.yaml`](../k8s/base/kong/values.yaml) `env.trusted_ips` com o CIDR exato dele e `env.real_ip_header: X-Forwarded-For` e rode `make kong-render`. Nunca use `0.0.0.0/0`: o cliente escolheria o próprio IP pelo header e escaparia do limite.

O `X-Request-ID` gerado pelo Kong é um UUID simples (`generator: uuid`), aceito como está pelo middleware de request id que os serviços herdaram da fase 3 (`[A-Za-z0-9._=-]{1,128}`); o formato `uuid#counter` seria descartado por ele. Se o cliente mandar um `X-Request-ID`, o Kong o mantém e o devolve na resposta. O FastAPI precisa de `root_path="/os"` fixo para o Swagger em `/os/docs` achar o `/os/openapi.json`; o header `X-Forwarded-Prefix` não serve, porque traz o trecho inteiro que a regra casou.

O Kong não anuncia produto nem versão: `env.headers: "off"` em [`values.yaml`](../k8s/base/kong/values.yaml) (`KONG_HEADERS=off`) tira `Server`, `Via` e todos os `X-Kong-*` das respostas, as que o Kong gera sozinho (404 de rota inexistente, o `fora-da-borda`, o 429 do rate limit) e as dos serviços, que já sobem sem o `server` do uvicorn. Sem isso o Kong 3.9.3 responde `Server: kong/3.9.3` e `Via: 1.1 kong/3.9.3`, o que o ZAP acusa ([regra 10036](zap.md#zap-baseline-na-borda)). O `make smoke` prova no cluster: pede uma rota publicada, `/os/metrics` (404 do `fora-da-borda`), uma rota que não existe (404 do Kong) e o 429 do login, e reprova se algum desses cabeçalhos aparecer. O `X-Request-ID` e os `X-RateLimit-*` continuam.
