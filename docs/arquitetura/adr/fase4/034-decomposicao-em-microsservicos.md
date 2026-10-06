# Decomposição do PytStop em três microsserviços e uma plataforma

> [↑ Raiz do projeto](../../../../README.md) · [↑ Arquitetura](../../README.md)

* Status: Aceita
* Data: 2026-10-06

## Contexto e Problema

O enunciado da fase 4 pede "no mínimo, 3 microsserviços independentes, cada um com seu próprio repositório, infraestrutura e banco de dados" (l. 27) e sugere três (l. 31-55): o OS Service, de ordens de serviço (OS); o Billing Service, de orçamento e pagamento; e um serviço de execução e produção, que aqui se chama Execution Service e cujo contexto é Execução ([desafio-tech-fase-4.md](../../../requisitos/fase4/desafio-tech-fase-4.md)).

A [gap analysis](../../../requisitos/fase4/gap-analysis-fase-4.md) registra a exigência nos requisitos não funcionais (RNF) RNF-031 (repositório, infraestrutura e banco por serviço), RNF-044 (um repositório por serviço), RNF-036 (nenhum serviço acessa o banco de outro) e RNF-047 (código-fonte em cada repositório), além dos requisitos funcionais (RF) de cada serviço: RF-028 a RF-030 no OS Service, RF-031 a RF-034 no Billing, RF-035 a RF-037 na Execução.

O p3 (código da fase 3, commit `08dcffe`) é um monolito modular: cinco contextos delimitados (ADR-007 do p3) e a base `compartilhado` numa aplicação FastAPI (`src/main.py:157-162`) e num PostgreSQL. Os contextos se leem pela sessão SQLAlchemy compartilhada (`src/ordem_servico/infraestrutura/adapters.py`, `src/estoque/infraestrutura/adapters.py`), e dois agregados misturam dados de donos diferentes: `ItemEstoque` guarda preço e saldo na mesma linha (`migrations/versions/001_initial_schema.py:33-45`) e a OS carrega o orçamento em JSONB. O contexto Ordem de Serviço cobre "abertura, diagnóstico, orçamento, aprovação, execução, conclusão" (ADR-007 do p3), e a aprovação reserva estoque no mesmo `UnitOfWork` da OS (`src/ordem_servico/aplicacao/use_cases.py:482-493`), acoplamento que o ADR-008 do p3 já marcava para revisão numa arquitetura distribuída.

Em Estrutura de Microsserviços (Microsserviços I), a única técnica de decomposição praticada é a tabela Serviço/Operação/Integração (Aula 01, p. 5); o resultado de uma decomposição errada é o monolito distribuído, e banco compartilhado é anti-pattern (Aula 05). Estrutura de Microsserviços Parte II (Microsserviços II) apresenta a decomposição por capacidade de negócio e por subdomínio do projeto orientado a domínio (DDD) e põe a identificação de limites e a granularidade entre os maiores desafios (Aula 01), sem dar critério de granularidade.

**Como repartir os contextos e componentes do p3 em serviços independentes, sem banco compartilhado e sem criar um monolito distribuído?**

## Decisão

Três microsserviços (`os-service`, `billing-service` e `execution-service`, abreviações de `postech-sw-arch-p4-<nome>`), cada um com repositório, banco, manifestos Kubernetes e pipeline próprios, e um quarto repositório, `platform`, que não é microsserviço. Critérios de corte, nesta ordem:

1. as capacidades sugeridas pelo enunciado definem os serviços;
2. cada contexto delimitado do p3 vai inteiro para o serviço cuja capacidade sustenta, com duas exceções. O contexto Ordem de Serviço mistura três subdomínios (atendimento da OS, orçamento com a decisão do cliente, diagnóstico com a execução) e é repartido entre os três serviços. O `ItemEstoque` perde o preço para o Billing, porque preço e saldo têm donos diferentes;
3. regra que depende de transação local com lock fica num serviço só, de modo que a reserva de peças não atravessa a rede.

A tabela Serviço/Operação/Integração da Aula 01 de Microsserviços I fecha o corte: cada operação do enunciado tem um dono e cada integração fica explícita.

| Serviço | Operação | Integração |
|---|---|---|
| `os-service` | abrir OS (RF-028); atualizar status pelas respostas da saga (RF-029); consultar status e histórico (RF-030) e o tempo médio por status (RF-008 da fase 1); clientes e veículos; notificar o cliente por e-mail; usuários internos e emissão do token JWT (JSON Web Token); orquestrar a saga ([ADR-035](035-saga-orquestrada.md)) | comandos e eventos com Billing e Execução pelo RabbitMQ ([ADR-036](036-mensageria-rabbitmq.md)); conjunto de chaves públicas (JWKS) servido aos outros dois ([ADR-039](039-autenticacao-entre-servicos.md)) |
| `billing-service` | tabela de preços de serviços e peças; gerar o orçamento e o link de decisão (RF-031); registrar a decisão do cliente; registrar, verificar e estornar pagamento (RF-032); publicar o pagamento que muda o status da OS (RF-033) | Mercado Pago (RF-034, [ADR-040](040-integracao-mercado-pago.md)); validação de preços pedida pela Execução |
| `execution-service` | filas de diagnóstico e de execução (RF-035); apontar diagnóstico e reparo (RF-036); reservar, liberar e baixar peças; comunicar a finalização (RF-037) | validação de preços no Billing, a única chamada síncrona de negócio entre serviços ([ADR-038](038-borda-e-comunicacao-sincrona.md)); eventos para o OS Service |

O enunciado põe o envio do orçamento no Billing (l. 43). O desvio é deliberado: o Billing gera o orçamento e o link de decisão, e o e-mail sai do OS Service, dono do contato, quando ele recebe `OrcamentoGerado`. Assim, nome, documento e contato do cliente não saem do OS Service. O RF-008 da fase 1 também fica no OS Service: `GET /api/v1/ordens-de-servico/metricas` calcula o tempo médio em cada status a partir do histórico, e o dashboard Negócio mostra o mesmo número ([ADR-043](043-observabilidade-distribuida.md)).

Os componentes do p3 são recortados do commit `08dcffe` por `git archive`, sem histórico; o OS Service leva também a correção `fc06263`, a normalização ASCII de CPF e CNPJ do pull request #32 do p3. A proveniência fica registrada no pull request do recorte e no README de cada serviço. Destino de cada componente:

| Componente do p3 | Destino |
|---|---|
| `cliente_veiculo`, `autenticacao`, núcleo de `ordem_servico` (agregado, máquina de status, notificação) | `os-service`, que ganha histórico de status e orquestrador |
| `catalogo_servicos`; orçamento e decisão externa (hoje em `ordem_servico`) | `billing-service`: tabela de preços e orçamento como documento |
| `estoque`; itens da OS | `execution-service`: saldo, reserva, liberação e baixa; itens apontados no diagnóstico. O preço da peça vai para o Billing |
| `compartilhado`, `relay/` | cópia em cada serviço; o relay passa a publicar no RabbitMQ |
| `ui/` (NiceGUI) | fora do escopo: a demonstração usa Swagger, Postman e scripts |
| Lambda de autenticação por CPF da fase 3 | não migra: lê a tabela `clientes` direto, o que RNF-036 proíbe |

Peça existe em dois contextos com modelos diferentes, ligados pelo `sku` (código de estoque da peça): preço comercial no Billing, quantidade física na Execução. O p3 identifica a peça só pelo `id` da linha de `itens_estoque`; o `sku` é a chave de negócio nova comum aos dois, e peça nova é cadastrada nos dois pelo administrador. Tabela de preços e estoque não viram serviços próprios: o preço entra no orçamento e na validação do diagnóstico, que o Billing já atende, e o saldo muda só em passos da Execução. Separá-los transformaria passos locais da saga em chamadas de rede.

A base técnica (`Entity`, `AggregateRoot`, `ValueObject`, `Dinheiro`, `UnitOfWork`, outbox, logging, métricas) é copiada em cada serviço com seus testes, sem pacote compartilhado. Cada serviço leva só o que usa: criptografia de dados pessoais no OS Service, assinatura HMAC (código de autenticação de mensagem com hash) no Billing, unidade de trabalho e outbox em SQLAlchemy nos serviços PostgreSQL.

O `platform` guarda o cluster (kind na integração contínua e k3s opcional), o RabbitMQ, o gateway, a observabilidade, os testes ponta a ponta (E2E) em BDD (*behavior-driven development*) e a arquitetura global (gap analysis, ADRs e [RFC-004](../../rfc/fase4/rfc-004-microsservicos-saga.md), que traz o mapa de contextos com o padrão de cada relação). Sem domínio, API nem banco, não é microsserviço nem conta para RNF-031; é repositório à parte para que nenhum serviço carregue a infraestrutura dos outros nem o teste que atravessa os três. Cada repositório de serviço se basta para o que o enunciado pede dele.

Nenhum serviço acessa o banco de outro (RNF-036): banco e credencial exclusivos, Secret montado só nos pods do dono, dado alheio só por mensagem ou pela chamada síncrona de negócio. A busca do JWKS no OS Service é a segunda dependência HTTP entre serviços, de infraestrutura e não de dados ([ADR-038](038-borda-e-comunicacao-sincrona.md)).

## Alternativas Consideradas

* Três serviços pelas capacidades do enunciado, mais a plataforma
* Quatro ou mais serviços, com tabela de preços e estoque separados
* Serviço próprio de clientes e identidade
* Três serviços, com o estoque no Billing
* Pacote compartilhado para a base técnica

Descartado pelo enunciado: o monolito modular com bancos separados, que teria um repositório e um pipeline só (l. 27 e 99; RNF-031 e RNF-044).

### Três serviços pelas capacidades do enunciado, mais a plataforma

* Bom, porque cada RF tem um único serviço dono e a tabela de operações fecha sem operação órfã
* Bom, porque a reserva de peças continua transação local com lock pessimista, agora na Execução
* Ruim, porque o OS Service acumula OS, clientes, autenticação e orquestração e fica maior que os outros dois

### Quatro ou mais serviços, com tabela de preços e estoque separados

A Fig. 2 da Aula 01 de Microsserviços I separa quase cada módulo do monolito, inclusive Estoque e Precificação.

* Bom, porque nenhum agregado do p3 seria dividido
* Bom, porque preço e estoque seriam publicados e escalados sozinhos
* Ruim, porque orçamento, validação do diagnóstico, reserva e baixa passariam a chamar outro serviço no meio da saga: mais saltos de rede e pontos de falha nos mesmos passos, o sintoma de monolito distribuído da Aula 01
* Ruim, porque cada serviço a mais cobra repositório, banco, pipeline, cobertura e deploy sem capacidade nova no enunciado

### Serviço próprio de clientes e identidade

Clientes, veículos, usuários e emissão de token num quarto serviço, fora do OS Service.

* Bom, porque o OS Service ficaria só com a OS e a saga, e a emissão de token não cairia junto com ele
* Bom, porque cadastro e autenticação mudam em ritmo diferente do fluxo da OS
* Ruim, porque toda abertura de OS validaria cliente e veículo por chamada síncrona, ou manteria cópia deles por evento, e o e-mail de cada etapa dependeria do contato guardado em outro serviço
* Ruim, porque a eliminação de dados pessoais da LGPD (Lei Geral de Proteção de Dados), hoje local, passaria a envolver mais um serviço, sem capacidade nova pedida pelo enunciado

### Três serviços, com o estoque no Billing

* Bom, porque preço e saldo da peça ficariam juntos, com um cadastro só
* Ruim, porque reserva, liberação e baixa acontecem no fluxo da oficina; no Billing, cada movimento de saldo viraria comando entre serviços
* Ruim, porque o estoque precisa de lock de linha e saldo nunca negativo (ADR-008 do p3), o que puxaria o Billing para o SQL e tiraria o banco de documentos do único serviço cujo dado já era documento ([ADR-037](037-banco-por-servico.md))

### Pacote compartilhado para a base técnica

Biblioteca versionada consumida pelos três serviços, a forma usual do padrão chassis que a Aula 05 de Microsserviços II nomeia.

* Bom, porque uma correção na base valeria para os três de uma vez
* Ruim, porque toda mudança na base exigiria publicar versão e atualizar três repositórios em ordem, o acoplamento de publicação que a separação elimina
* Ruim, porque a persistência não seria comum: o Billing precisa de unidade de trabalho e outbox para MongoDB

## Consequências

### Positivas

* Cada requisito funcional tem um serviço dono, rastreável da tabela de operações ao repositório
* As transações que exigem ACID (atomicidade, consistência, isolamento e durabilidade) continuam locais: OS, cliente e veículo no OS Service; reserva com lock na Execução
* Os três serviços nascem do código testado do p3, sem reescrita do domínio

### Negativas

* Duplicação deliberada: o p3 tem cerca de 2,5 mil linhas em `src/compartilhado/` e 1,4 mil em `relay/`; uma correção na base vai para até três repositórios, e as cópias podem divergir. A divergência que quebra a integração, o formato das mensagens, é pega pelo teste de contrato com os schemas do `platform` ([ADR-036](036-mensageria-rabbitmq.md))
* O OS Service concentra OS, clientes, autenticação e orquestração: fora do ar, ele para a abertura de OS e a emissão de token, e, vencido o cache do JWKS, Billing e Execução deixam de aceitar requisições autenticadas ([ADR-039](039-autenticacao-entre-servicos.md))
* Peça cadastrada só num lado é recusada na conclusão do diagnóstico, antes da aprovação do cliente: código sem preço pelo Billing, `sku` fora do estoque pela própria Execução ([ADR-038](038-borda-e-comunicacao-sincrona.md)); o administrador corrige o cadastro que falta
* O orçamento complementar (RF-016 da fase 1 e regra de negócio RN-015 do p3) sai do escopo. Com o pagamento integral antecipado e o pivot (ponto sem retorno, RN-029) no início da execução, um complementar seria uma segunda cobrança sobre OS já paga; serviço extra achado na execução vira OS nova, com saga e pagamento próprios
* Cluster e broker compartilhados podem ser lidos como infraestrutura comum; cada repositório declara como código namespace, manifestos e pipeline, e o `platform` hospeda só o cluster e o middleware. Os Secrets não são versionados: o deploy os gera ([ADR-042](042-cicd-e-deploy-kubernetes.md))

### Neutras

* O cliente final deixa de ter login: acompanha a OS pelo acompanhamento público do OS Service e decide o orçamento pelo link assinado do Billing, e as rotas `/minhas-ordens`, que dependiam do token da Lambda, saem

## Decisões Relacionadas

- [ADR-007](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p3/blob/main/docs/arquitetura/adr/007-organizacao-contextos-delimitados.md): os cinco contextos, unidade de corte, e o contexto Ordem de Serviço que agora se reparte
- [ADR-008](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p3/blob/main/docs/arquitetura/adr/008-bloqueio-pessimista-estoque.md): reserva com lock pessimista, que fica inteira na Execução
- [ADR-022](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p3/blob/main/docs/arquitetura/adr/fase2/022-transactional-outbox-relay.md): outbox e relay, copiados em cada serviço
- [ADR-028](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p3/blob/main/docs/arquitetura/adr/fase3/028-autenticacao-serverless-cpf.md): Lambda de CPF da fase 3, que não migra
- [ADR-035](035-saga-orquestrada.md): orquestrador hospedado no OS Service
- [ADR-036](036-mensageria-rabbitmq.md): mensagens entre os serviços e seus contratos
- [ADR-037](037-banco-por-servico.md): banco de cada serviço
- [ADR-038](038-borda-e-comunicacao-sincrona.md): borda e a única chamada síncrona de negócio
- [ADR-039](039-autenticacao-entre-servicos.md): emissão de token no OS Service e validação nos outros dois

## Notas

* Material: Estrutura de Microsserviços, Aulas 01 (tabela de serviços, desafios da decomposição, Fig. 2) e 05 (banco por serviço); Estrutura de Microsserviços Parte II, Aulas 01 (capacidade de negócio, subdomínio, granularidade) e 05 (padrão chassis)
* Richardson, citado na bibliografia de Microsserviços II, Aula 01: https://microservices.io/patterns/decomposition/decompose-by-business-capability.html
* Rastreabilidade por componente e tabela do p3: gap analysis, seções 3 a 5

> [↑ Raiz do projeto](../../../../README.md) · [↑ Arquitetura](../../README.md)
