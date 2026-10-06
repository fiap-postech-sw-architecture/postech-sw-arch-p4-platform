> Documento original transcrito do PDF fornecido pela FIAP para a fase 4 (desafio de 09/09/2026 a 17/11/2026).
> Cópia fiel: apenas quebras de linha da extração do PDF foram normalizadas; nenhum conteúdo foi alterado.
> PDF original (fonte, versionado neste diretório): [Phase4_Tech_Challenge.pdf](Phase4_Tech_Challenge.pdf).

# Tech Challenge - Fase 4

> [↑ Raiz do projeto](../../../README.md) · [↑ Requisitos](../README.md)

## Sobre o Tech Challenge

O Tech Challenge é o projeto da fase que englobará os conhecimentos obtidos em todas as disciplinas da fase. Esta é uma atividade que, em princípio, deve ser desenvolvida em grupo. Importante atentar-se ao prazo de entrega, pois trata-se de uma atividade obrigatória, uma vez que vale 90% da nota de todas as disciplinas da fase.

## Desafio

A oficina mecânica atingiu escala nacional e agora opera com múltiplas filiais. O volume de ordens de serviço, interações entre áreas (atendimento, diagnóstico, execução e cobrança), necessidade de resiliência e tolerância a falhas aumentaram consideravelmente.

Para sustentar essa operação, a aplicação precisa ser refatorada para um modelo distribuído, com microsserviços independentes e especializados. Além disso, é necessário garantir consistência entre as transações críticas (como criação de ordens de serviço, aprovações e pagamentos), aplicando o Saga Pattern para coordenar processos distribuídos com rollback seguro em caso de falhas.

## Objetivo

Refatorar a aplicação para arquitetura de microsserviços com gestão transacional distribuída e automação completa de build, testes e deploy.

## Requisitos obrigatórios

### Separação em Microsserviços

Refatore a aplicação em, no mínimo, 3 microsserviços independentes, cada um com seu próprio repositório, infraestrutura e banco de dados.

Exemplos sugeridos:

**Ordem de Serviço (OS Service)**

Responsável por gerenciar as ordens de serviço, incluindo:

- Abertura da OS;
- Atualização de status;
- Consulta de status e histórico.

**Orçamento e Pagamento (Billing Service)**

Responsável por:

- Geração e envio de orçamentos para aprovação;
- Registro e verificação de pagamentos;
- Atualização do status da OS após pagamento.

Obs.: para a parte de pagamentos devemos nos integrar com o Mercado Pago. Acesse a documentação.

**Execução e Produção**

Responsável por:

- Gerenciar a fila de execução da OS;
- Atualizar status durante diagnóstico e reparos;
- Comunicar finalização ao OS Service.

Observação: cada microsserviço deverá ter banco de dados próprio, sendo obrigatório:

- Uso de pelo menos um banco relacional (SQL);
- Uso de pelo menos um banco não relacional (NoSQL).

### Comunicação entre Microsserviços

- Definir estratégias de comunicação:
  - APIs RESTful síncronas (quando necessário).
  - Mensageria assíncrona (RabbitMQ, Kafka, SQS, etc.) para eventos e integração desacoplada.
- Nenhum serviço pode acessar diretamente o banco de outro serviço.

### Implementação do Saga Pattern

- Implementar o Saga Pattern para coordenar o fluxo transacional das ordens de serviço:
  - Exemplo: Ao abrir uma OS → gerar orçamento → aguardar aprovação → enviar para execução.
- Deve haver rollback e compensação no caso de falha em qualquer etapa.
- Pode ser aplicado via:
  - Orquestrado (com um orquestrador central).
  - Coreografado (via eventos entre serviços).
- Documentar a escolha e justificar no README.

### Testes e Qualidade

- Testes unitários em todos os microsserviços.
- Pelo menos um fluxo completo testado com BDD.
- Cobertura mínima de 80% por serviço.
- Validação de qualidade do código via SonarQube ou similar no CI.

### CI/CD Automatizado

Cada microsserviço deverá:

- Ter pipeline independente de CI/CD com:
  - Build.
  - Testes automatizados.
  - Verificação de qualidade.
  - Deploy automatizado em ambiente Kubernetes.
- Repositórios protegidos (branch main com PR obrigatório e checagens automáticas).

### Infraestrutura

- Cada microsserviço deve estar em seu próprio repositório;
- Deploy automatizado para ambiente Kubernetes;
- Mensageria para orquestração ou coreografia;
- Uso de ferramentas de monitoramento e observabilidade já implementadas na Fase 3.

## Entregáveis da Fase 4

### Repositórios Git (um para cada microsserviço):

- Código-fonte;
- Dockerfile e manifestos Kubernetes;
- Pipelines de CI/CD;
- Evidências de cobertura de testes (prints ou links no README);
- Documentação da arquitetura do serviço;
- Swagger ou collection Postman atualizada.

### Vídeo de demonstração:

- Upload no YouTube ou Vimeo (público ou não listado) de até 15 minutos;
- Demonstrando:
  - Fluxo completo de uma OS passando pelos microsserviços.
  - Execução do Saga Pattern e tratamento de falhas.
  - Deploy automatizado de pelo menos um microsserviço com validação de testes.
  - Monitoramento e rastreamento dos fluxos distribuídos.

### Documentação entregue no portal:

PDF com:

- Nome e identificação dos participantes;
- Links dos repositórios;
- Link do vídeo de até 15 minutos;
- Diagrama geral da arquitetura final com microsserviços, bancos e comunicação;
- Descrição da estratégia escolhida para o Saga Pattern (orquestração/coreografia);
- Justificativa da divisão dos microsserviços e tecnologias utilizadas.
