# Mercado Pago na sandbox

> [↑ Raiz do projeto](../README.md)

Prova que o Billing cria uma cobrança no Mercado Pago, confirma o pagamento e estorna, com as credenciais de teste do Mercado Pago e sem mover dinheiro ([ADR-040](arquitetura/adr/fase4/040-integracao-mercado-pago.md), RF-032 a RF-034). O CI, o `make e2e` e o `make demo` ficam no simulador do Billing; esta prova roda à mão, num kind local, com dois alvos:

| Alvo | O que faz | Credencial |
|---|---|---|
| `make mp-sandbox-ensaio` | O mesmo roteiro, com o simulador do Billing no lugar do comprador. Prova o fluxo, o formato da evidência e o desfazer, e não fala com o Mercado Pago | nenhuma |
| `make mp-sandbox` | O roteiro de verdade: o Billing em modo `mercadopago`, o link do checkout impresso no terminal e o pagamento feito por você no navegador | `MP_ACCESS_TOKEN` e `MP_WEBHOOK_SECRET` no ambiente do shell |

## O que prova e o que não prova

| Cenário | O que afirma |
|---|---|
| Pagamento no checkout | O pagamento nasce `SOLICITADO` com `provedor=mercadopago`; depois que o comprador de teste paga, o Billing o confirma (conciliação do `prazos`) e a OS chega a `aguardando_execucao`. No Mercado Pago, `GET /v1/payments/{id}` mostra `approved`, no valor e na moeda do orçamento, com o `external_reference` igual ao `pagamento_id` do Billing e `live_mode` falso. Se a resposta não trouxer `live_mode`, o cenário passa e o `resumo.md` registra que a natureza de teste do pagamento não foi provada pela consulta |
| Cancelamento depois do pagamento | Segunda OS, paga do mesmo jeito e cancelada antes da execução: saga `compensada` (`CancelarExecucao`, `EstornarPagamento`, `LiberarReserva`, `CancelarOrcamento`, `DescartarDiagnostico`), pagamento `ESTORNADO` no Billing e `refunded` no Mercado Pago |
| Cancelamento sem pagar | Terceira OS, levada ao checkout e cancelada: pagamento `CANCELADO` no Billing e, no Mercado Pago, `GET /checkout/preferences/{id}` com `expires` verdadeiro e `expiration_date_to` vencido (com até 5 min de folga de relógio). Prova que a preferência consta como expirada; não prova que o checkout recusaria um pagamento depois disso. Se a resposta não trouxer esses dois campos, o cenário passa e o `resumo.md` registra que a expiração não foi provada pela consulta |

**Não prova o webhook.** Segundo a documentação do Mercado Pago ([Checkout Pro, notificações](https://www.mercadopago.com.br/developers/pt/docs/checkout-pro-preferences/payment-notifications); consultada em 18/10/2026), pagamentos de teste não enviam notificações; a página só trata do `x-signature` nos webhooks do painel e não diz se a notificação da `notification_url` o traz; a execução real na sandbox ainda não foi feita. No modo real, o Billing recebe uma `notification_url` pública (`https://example.com/api/v1/webhooks/mercadopago`, ou a de `E2E_MP_NOTIFICATION_URL`) só para o Mercado Pago aceitar criar a cobrança: a do kind (`https://localhost/billing/...`) não é alcançável de fora, e a documentação manda não usá-la. A confirmação vem da conciliação do processo `prazos` do Billing (`GET /v1/payments/search?external_reference=` a cada 30 s), e o `resumo.md` diz isso e qual URL o Mercado Pago recebeu. O `MP_WEBHOOK_SECRET` é exigido porque o Billing não sobe em modo real sem ele, mas nenhuma notificação o exercita. Também não prova pagamento em produção, e o formato real das respostas do Mercado Pago só aparece no primeiro uso com credencial (o ensaio usa o simulador).

## Como rodar

Precisa do cluster no overlay `kind` (o padrão do `make deploy`; o `kind-ci` expira o orçamento em 72 s, curto demais para abrir o link e pagar) com a plataforma e os três serviços, `uv` e `kubectl`. Com os repositórios dos serviços ao lado deste:

```bash
make kind-up deploy
scripts/ci/implantar-servicos.sh --overlay kind \
  os-service=../postech-sw-arch-p4-os-service \
  billing-service=../postech-sw-arch-p4-billing-service \
  execution-service=../postech-sw-arch-p4-execution-service
make mp-sandbox-ensaio
```

O ensaio leva cerca de meio minuto num kind sem outra carga e termina com `3 passed, 14 deselected` (e o tempo) e `varredura de reports/mp-sandbox-ensaio: nenhum segredo`, e deixa `reports/mp-sandbox-ensaio/resumo.md`. O Billing continua em `simulado` (`curl -sk https://localhost/billing/api/v1/saude` diz `"modo":"simulado"`), e o Secret `billing-mercadopago` não existe.

Se um ensaio foi interrompido ou reprovado, apague o cluster e suba outro (`make kind-down` e o bloco acima de novo) antes do `make mp-sandbox`: um pagamento `SOLICITADO` que sobrou dele seria conciliado no Mercado Pago de verdade. A conferência prévia avisa disso, mas não tem como conferir.

Para o modo real você precisa de quatro coisas do painel do Mercado Pago (os nomes dos menus vêm da documentação consultada em 14/10/2026; se o painel estiver diferente, siga o que ele mostrar):

1. uma aplicação do tipo Checkout Pro, em [Mercado Pago Developers](https://www.mercadopago.com.br/developers/panel/app), Suas integrações;
2. duas contas de teste do Brasil (o Billing cobra em BRL, e o checkout de outro país não paga nessa moeda), uma Vendedor e outra Comprador, na página da aplicação, Contas de teste (anote usuário e senha de cada uma; elas não podem ser apagadas);
3. o Access Token de teste, em Suas integrações, Dados da integração, Testes, Credenciais de teste (entre com a sua conta real para ver essa tela; o prefixo pode ser `TEST-` ou `APP_USR-`);
4. a assinatura secreta do webhook, em Webhooks, Configurar notificações: em Modo produtivo, informe uma URL HTTPS pública qualquer (por exemplo `https://example.com/api/v1/webhooks/mercadopago`), marque o evento Pagamentos e salve; a chave aparece depois de salvar. Segundo a documentação do Mercado Pago (veja "Não prova o webhook", acima), os pagamentos de teste não enviam notificações; a URL só precisa ser pública, não precisa receber nada.

As duas credenciais ficam só no ambiente do shell, sem `export`. Cada `read` espera você colar o valor e teclar Enter; o `make` recebe as duas por atribuição na própria linha, e o `unset` as tira do shell no fim:

```bash
printf 'Access Token de teste: '; read -rs MP_ACCESS_TOKEN; echo
printf 'Assinatura secreta do webhook: '; read -rs MP_WEBHOOK_SECRET; echo
MP_ACCESS_TOKEN="$MP_ACCESS_TOKEN" MP_WEBHOOK_SECRET="$MP_WEBHOOK_SECRET" make mp-sandbox
unset MP_ACCESS_TOKEN MP_WEBHOOK_SECRET
```

O `make` recusa as duas se vierem na linha de comando (`make mp-sandbox MP_ACCESS_TOKEN=...`): o valor ficaria no `ps` e no histórico do shell.

O terminal imprime o link do checkout e o que fazer: abrir uma **janela anônima**, entrar no Mercado Pago só com o usuário Comprador de teste (nunca a sua conta real) e pagar com o cartão de teste da documentação (nome do titular `APRO` aprova; `OTHE`, `FUND` e `SECU` recusam). O script espera até 15 min por pagamento, consulta o Billing a cada 5 s, mostra a contagem regressiva a cada 30 s e avisa cada tentativa recusada (o pagamento encerra na recusa de número `PAGAMENTO_MAX_RECUSAS`, 3 no `kind`). São dois pagamentos seus, nos dois primeiros cenários.

O quadro com o link diz o site dele (`www.mercadopago.com.br`) antes de a espera começar. Se a página mostrar erro de conta (usuário errado, conta real logada, país diferente), dê **um** `Ctrl-C`: o script desfaz o modo real, e você não espera os 15 min para ouvir "O Mercado Pago não recebeu nenhum pagamento deste link. Você pagou?".

O `make mp-sandbox` leva cerca de 100 s de máquina (a criação da cobrança, a conciliação de cada pagamento, que o `prazos` faz a cada 30 s, e os rollouts do modo real e do desfazer), mais o tempo de você pagar duas vezes no navegador. Quando tudo passa, o fim do terminal é este (os tempos mudam):

```text
[mp-sandbox] Billing: desfazendo o modo real em 3 passos (Secret, variáveis e reinício). Não feche o terminal e não use kill -9.
[mp-sandbox] 1/3 apagando o Secret
[mp-sandbox] 2/3 tirando MP_MODE, SIMULADOR_PERMITIDO e MP_NOTIFICATION_URL dos Deployments
[mp-sandbox] 3/3 reiniciando os Deployments
[mp-sandbox] Billing de volta ao simulador
3 passed, 14 deselected in 114.44s (0:01:54)
varredura de reports/mp-sandbox: nenhum segredo
```

E a evidência fica em `reports/mp-sandbox/resumo.md`.

| Variável | Para quê | Padrão |
|---|---|---|
| `MP_ACCESS_TOKEN`, `MP_WEBHOOK_SECRET` | Credenciais de teste, lidas do ambiente do shell (`make mp-sandbox`) | ausentes |
| `E2E_MP_MANTER` | `1` deixa o Billing em modo real no fim (o Secret e as variáveis ficam no cluster), para criar OS à mão pelo Swagger e gravar o pagamento no navegador. Enquanto estiver assim, `make e2e` e `make demo` não servem: o simulador não existe em modo real, e eles pedem o overlay `kind-ci`. Para voltar ao simulador, rode `make mp-sandbox-ensaio` | desfaz |
| `E2E_MP_NOTIFICATION_URL` | URL https pública para o `MP_NOTIFICATION_URL` do Billing, se o Mercado Pago recusar a padrão. Tem de ser https, sem usuário e de host público: a conferência prévia recusa `localhost`, IP privado ou local e nome sem ponto | `https://example.com/api/v1/webhooks/mercadopago` |
| `E2E_MP_MODO` | `real` ou `ensaio`; quem define é o `make`, e sem ele os cenários `@mp_sandbox` são pulados. Se ficar definido no seu shell, `make e2e` e `make demo` param com erro, em vez de passar sem rodar nada | — |
| `KUBE_CONTEXT`, `E2E_URL` | Os mesmos do E2E da saga; o contexto tem de ser `kind-*` e o escape do E2E (`E2E_CONTEXTO_NAO_DESCARTAVEL`) não vale aqui | `kind-pytstop-p4`, `https://localhost` |

## O que o script faz e desfaz

| Etapa | O que acontece |
|---|---|
| Conferência prévia | Em segundos, antes do pytest e de qualquer mudança no cluster (detalhes abaixo). Se reprova, o `make` para ali com uma mensagem em português e o código 2, e não toca em `reports/` |
| Liga o modo real | Cria o Secret `billing-mercadopago` com `kubectl apply --server-side -f -`, o manifesto em JSON montado em memória e enviado pelo stdin; define `MP_MODE=mercadopago` e `SIMULADOR_PERMITIDO=false` em todos os Deployments do Billing, mais `MP_NOTIFICATION_URL`; reinicia e espera cada rollout. Só segue com `/billing/api/v1/saude` dizendo `mercadopago` |
| Cenários | Cada um cria os próprios dados, com códigos únicos, como no E2E da saga, e no fim guarda o trace da OS ([O trace da saga](#o-trace-da-saga)) |
| Desfaz, sempre | Apaga o Secret e **tira** `MP_MODE`, `SIMULADOR_PERMITIDO` e `MP_NOTIFICATION_URL` dos Deployments, para valerem de novo `simulado` e `true` do ConfigMap (um valor escrito no Deployment sobrevive a um novo `make kind-deploy`), reinicia e espera cada rollout |
| Ensaio | Não cria Secret. Só garante o Billing em `simulado`, sem Secret e sem as três variáveis |

A conferência prévia olha, nesta ordem: o contexto `kind-*`, as duas credenciais no ambiente (presentes, sem espaço nem quebra de linha; a mensagem nunca mostra o valor nem o tamanho), a borda local, o overlay `kind` (orçamento de pelo menos 1 h, pagamento de pelo menos 15 min de validade e 2 recusas), os três serviços saudáveis, o modo do Billing (`simulado` ou `mercadopago`) e o token no próprio Mercado Pago (uma busca por referência que não existe, sem efeito: 401 e 403 barram, e outro 4xx vira aviso e o roteiro segue). No modo real ela diz qual `notification_url` o Billing vai usar e de onde ela veio. Ao fim imprime `[mp-sandbox] conferência ok`.

O desfazer roda com sucesso, falha, `Ctrl-C`, SIGTERM ou SIGHUP (terminal fechado). Depois do primeiro sinal nenhum outro o interrompe, e o `kubectl` roda em sessão própria, fora do alcance do `Ctrl-C` do terminal. O terminal mostra cada passo dele ("1/3 apagando o Secret", e assim por diante) e pede para não fechar a janela. Cada passo é tentado mesmo que o anterior falhe, cada rollout é esperado mesmo que outro falhe, e o erro traz os três comandos para terminar à mão.

O ensaio é também o jeito de desfazer o que uma execução deixou. Se um `E2E_MP_MANTER=1` anterior, um `kill -9` ou uma queda deixou o modo real, o Secret ou uma variável, ele desfaz tudo; se não há sobra, não reinicia nada. O desfazer não cobre `kill -9`, queda de energia nem o Mac dormindo: o Billing pode ficar em modo real. Rode `make mp-sandbox-ensaio` e confira com `curl -sk https://localhost/billing/api/v1/saude`, que deve dizer `"modo":"simulado"`.

## Relatórios

`reports/mp-sandbox/` no modo real e `reports/mp-sandbox-ensaio/` no ensaio (pastas ignoradas pelo git). O ensaio recria a pasta dele e nunca toca na do real. O `make mp-sandbox` que encontra um `reports/mp-sandbox/resumo.md` move a pasta para `reports/mp-sandbox.AAAAMMDD-HHMMSS` e não apaga nenhuma anterior; a pasta de uma execução que não chegou a escrever o `resumo.md` é descartada. Assim que uma execução passar, copie o `resumo.md` e os `trace-*.json` para fora de `reports/`.

| Arquivo | Conteúdo |
|---|---|
| `resumo.md` | Modo, data, cenário, resultado (`passou`, `falhou` ou `interrompido`, se você deu `Ctrl-C`), duração, `ordem_id`, `pagamento_id`, id do pagamento no Mercado Pago, as transições com a hora que o serviço registrou (histórico da OS, passos da saga e datas do pagamento), o que veio do Mercado Pago, a `notification_url` usada, a frase de que a confirmação veio da conciliação, uma linha com o trace de cada cenário e os prints que você tira |
| `evidencia.json` | O mesmo em JSON, higienizado |
| `trace-<cenário>-<trace_id>.json` | O trace da OS de cada cenário no Jaeger, higienizado e no formato do upload do Jaeger (`<cenário>` é `pagamento`, `estorno` ou `cobranca-aberta`, e o `<trace_id>` é hexadecimal). Detalhes em [O trace da saga](#o-trace-da-saga) |
| `relatorio-e2e.md`, `junit.xml`, `cucumber.json`, `cenarios.json` | O relatório do E2E, como em `reports/e2e`. O `junit.xml` traz o nome da máquina: na evidência da entrega, anexe só o `resumo.md` e os `trace-*.json` |

A higienização é por **lista de campos permitidos**. Do Mercado Pago entram só `id`, `status`, `transaction_amount`, `currency_id`, `date_approved`, `external_reference` e `live_mode` (nunca e-mail, nome, documento ou cartão do pagador), e do `id` da preferência, só o uuid, sem o User ID da conta vendedora que o precede. Do Billing, o pagamento sem o `checkout_url`; da saga, a etapa, o motivo e o rastro de cada passo. Antes de gravar, todo texto é varrido atrás do token, da assinatura, de qualquer segredo que o E2E registrou, de `Bearer` seguido de um token, de `TEST-` e `APP_USR-`, de padrão de e-mail (menos os usuários que o próprio E2E cria, do domínio `pytstop.dev`) e do prefixo numérico do User ID (`<números>-<uuid>`); se achar, o script recusa gravar e diz o arquivo e a linha (sem repetir o valor). Depois do pytest, `python -m e2e.varredura` varre a pasta toda e apaga o arquivo em que achar algo.

Os prints que o terminal pede são do checkout, do pagamento aprovado e do painel do vendedor de teste. Cubra e-mail, nome, User ID e CPF das contas de teste, e nunca mostre a tela de Credenciais nem a de Webhooks. Antes de commitar a evidência, rode `python -m e2e.varredura <pasta>` e `gitleaks dir <pasta>`.

Quando uma afirmação falha ou o prazo estoura, o terminal mostra, mascarado, o estado da OS e da saga, o pagamento no Billing, os pagamentos que o Mercado Pago tem para aquele `external_reference` (cada um com o `live_mode`), as filas mortas (e quantas a mais que no início do cenário: mensagem de uma execução anterior não vira causa), as últimas 40 linhas do log da `api`, do `consumidor` e do `prazos` e a causa provável. Das linhas do log só passam as que importam (aviso ou erro, resposta 4xx ou 5xx, `resultado` fora da rotina e o evento `mercadopago_request_rejected`), e delas só os 16 campos de `CAMPOS_DO_LOG`, em `e2e/apoio/diagnostico.py` (tipo, comando, resultado, tentativa, erro, código, motivo, operação, status, caminho, id do pagamento, referência, mensagem, causa, `status_http` e `causas`), cada um cortado em 160 caracteres e mascarado. O script não filtra o conteúdo desses campos: que o texto livre do Mercado Pago (`message`, `description`) não apareça é garantia do Billing da `main`, que não o registra. O evento de recusa traz sempre a operação e o HTTP, e traz o `error` do Mercado Pago (`erro_do_mp`, só se casar com `[a-z_]{1,40}`) e os códigos de `causas` (só se casarem com `[A-Za-z0-9_.-]{1,40}`) quando passam pelo filtro do Billing. A causa provável diz qual chamada foi recusada mesmo se o evento vier só com a operação e o HTTP, e a falha por divergência com o Mercado Pago (por exemplo, `live_mode` verdadeiro) vem com a dica de conferir primeiro no painel do Vendedor de teste.

Nas esperas da cobrança aberta e do pagamento, se a fila morta do Billing cresce o script reprova na hora, sem esperar o prazo: o Billing recusou de vez um comando da saga (isso só vale se a foto inicial das filas foi lida). Nos outros passos vale o prazo do passo (30 a 60 s), e o diagnóstico mostra a fila. O estorno que o Mercado Pago recusa nem passa pela fila morta: a saga vai a `falha_na_compensacao`, e o diagnóstico mostra a etapa e a falha.

## O trace da saga

O Jaeger do kind guarda os traces só na memória e perde todos quando reinicia, e o trace com a chamada do Billing ao Mercado Pago só existe enquanto o `make mp-sandbox` roda. Por isso, no fim de cada cenário, o script lê o trace da OS no Jaeger (pelo port-forward que o `make` abre para ele) e o guarda em `trace-<cenário>-<trace_id>.json`, ao lado do `resumo.md`, no `make mp-sandbox` e no `make mp-sandbox-ensaio`.

Vale o trace que duas leituras seguidas, de 3 em 3 s, trazem com o mesmo `trace_id` e o mesmo número de spans, e o script espera até 30 s por ele (em geral, uns 3 s por cenário). Se mais de um trace da OS tem a chamada do Billing ao Mercado Pago, fica o de mais spans; sem nenhum, o das três peças (`os-service`, `billing-service` e `execution-service`) com mais spans; sem nenhum dos dois, o de mais spans, mesmo que falte um serviço. O script só dá o trace por pronto quando ele tem a chamada (no modo real) ou as três peças (no ensaio); se os 30 s acabam antes, fica o melhor que se viu, e a linha do resumo avisa que faltou a chamada ou diz quais serviços faltaram (`trace parcial: faltam ...`).

O `resumo.md` ganha uma linha por trace, na seção do cenário: o `trace_id`, o arquivo, os serviços presentes (e os que faltam, se o trace for parcial) e se há span CLIENT do Billing para `api.mercadopago.com`. No modo real deve haver. No ensaio não há, porque o simulador não chama ninguém, e a linha diz "modo simulador: sem chamada externa". Trace que não aparece em 30 s, ou Jaeger que não responde, não reprova o cenário, porque o pagamento é a prova principal: a linha diz "trace não encontrado" e o motivo (o nome do erro, nunca a mensagem). O cenário interrompido por `Ctrl-C` nem procura o trace: o desfazer do modo real vem antes, e o port-forward do Jaeger caiu com o `Ctrl-C`. Se o `Ctrl-C` chega durante a espera de até 30 s, ela para na hora, o desfazer segue e a linha do resumo diz "trace não procurado (interrompido)".

O arquivo é um JSON novo, montado por lista de permissão em [`e2e/apoio/trace_higienizado.py`](../e2e/apoio/trace_higienizado.py). Tem a forma `{"data": [trace]}`, que o upload do Jaeger lê, com `traceID` no trace; em cada span, `traceID`, `spanID`, `operationName`, `references`, `startTime`, `duration`, `processID` e as tags de uma lista fechada; de cada processo, só o `serviceName`. Não existem na saída `logs`, `warnings`, as tags dos processos (host, IP, pod), `db.statement`, o `messaging.message.conversation_id` (o `ordem_id`) nem qualquer outra tag fora da lista:

| Tag | Valor que passa |
|---|---|
| `span.kind` | `client`, `server`, `producer`, `consumer` ou `internal` |
| `http.method`, `http.request.method` | o verbo (`GET`, `POST`...) |
| `http.status_code`, `http.response.status_code` | número de 100 a 599 |
| `http.route` | o caminho do modelo da rota, com `{id}` no lugar do que parece id |
| `http.url`, `url.full` | esquema, host e caminho (veja abaixo) |
| `server.address` | só `api.mercadopago.com` (igualdade exata) |
| `otel.status_code` | `OK`, `ERROR` ou `UNSET` |
| `error` | só `true` |
| `messaging.system` | `rabbitmq` |
| `messaging.operation`, `messaging.operation.type` | `publish`, `send`, `receive`, `process`, `deliver`, `create` ou `settle` |
| `db.system` | `postgresql` ou `mongodb` |
| `messaging.destination.name` | nome de exchange ou fila (`pytstop.comandos`, `billing.comandos.retry.15s`): palavras em minúsculas separadas por ponto e o atraso do retry |

Valor de tag da lista que não tem a forma da tabela sai junto com a tag. Onde o vocabulário é fechado (`span.kind`, o verbo HTTP, `server.address`, `otel.status_code`, `messaging.system`, `messaging.operation`, `messaging.operation.type`, `db.system`, o host da URL e o nome do serviço), só passa o que a lista cita: o processo de um serviço que não é `os-service`, `billing-service` ou `execution-service` sai com os spans dele, e a chave do processo tem de ser `p` e um número. Onde não há vocabulário fechado (segmento de caminho, modelo de rota, nome de fila e nome do span), só a forma é conferida: dígito, `@`, query, fragmento e símbolo fora de `.`, `_`, `:` e `-` não passam, mas palavras em letras passam, mesmo que formem um nome de pessoa (`joao.silva` num nome de fila, por exemplo). Essa etapa é a segunda barreira: os serviços já redigem o dado na origem (a URL sai pelo template da rota, o resto vira `REDACTED` e o comando do banco não é gravado).

`http.url` e `url.full` saem reduzidos a esquema (`http` ou `https`), host e caminho, sem usuário, senha, query nem fragmento. O host só fica se for o do Mercado Pago ou o de um dos três serviços, pelo nome curto ou pelo do cluster (`billing-service.pytstop-billing.svc.cluster.local`), com a porta, se houver; outro host (um IP de pod, o nome de uma máquina) vira `REDACTED`, e a porta sai com ele. Cada segmento do caminho que não é uma palavra da rota (`ordens-de-servico`), a versão (`v1`) ou um modelo (`{pagamento_id}`) vira `{id}`: número, uuid, token, placa, CPF, e-mail e qualquer coisa com maiúscula ou dígito. O nome do span tem regra própria: passa com até quatro palavras ou caminhos, inclusive com maiúscula (`publish PagamentoConfirmado`, `POST /api/v1/ordens-de-servico`, e também `Joao da Silva` ou `DELETE FROM users`); mais de quatro palavras, dígito ou símbolo fora de `.`, `_`, `:`, `-` e `/` vira `(operacao omitida)`. Antes de gravar, o texto de cada arquivo passa pela mesma varredura de segredos do `resumo.md`. Achado num trace descarta só aquele arquivo, porque o pagamento é a prova principal, e a linha do resumo diz "trace não gravado (descartado pela varredura de segredos)"; achado no `resumo.md` ou no `evidencia.json` recusa gravar a pasta toda.

Para abrir um trace no Jaeger: tela de busca (Search), aba "Upload" (nas versões antigas do Jaeger, "JSON File"), arraste o arquivo. O navegador lê o arquivo sem consultar o servidor, então serve o Jaeger da plataforma (`make port-forward`, porta 16686) ou o do compose (`make up`), mesmo depois de o cluster ser apagado. As referências a spans de outros traces ficam no arquivo, mas esses traces não. Conferido em 19/10/2026 na interface do `jaegertracing/all-in-one:1.76.0`: o trace de 245 spans da entrega (`docs/entrega/fase4/evidencias/trace-saga-2026-10-19.json`), passado pela higienização, abre inteiro, com a linha do tempo, os três serviços e o filtro de spans.

## Segurança

- O token e a assinatura nunca vão em argumento de comando (`ps`), em arquivo, no `repr` de fixture, no traceback, no `junit.xml`, no `cucumber.json` nem no resumo. Entram na máscara do E2E assim que lidos, antes de qualquer conferência que possa reprovar, e a máscara central do plugin do pytest cobre também `TEST-` e `APP_USR-`. O ambiente inteiro nunca é argumento de quem pode falhar (o pytest mostra os argumentos no traceback): só as cinco chaves do sandbox são recortadas.
- Nenhum processo filho (`kubectl`, `docker`, `port-forward`) herda as duas credenciais: cada um é lançado com o ambiente do processo sem elas (`e2e/apoio/kube.py`), inclusive os da conferência prévia e os da fixture do pytest, que rodam antes de o preflight tirá-las do ambiente do próprio processo, onde elas não ficam depois de lidas. Fora a memória do processo, o token só passa pelo cabeçalho da chamada ao Mercado Pago e pelo stdin do `kubectl apply`.
- As chamadas ao Mercado Pago só leem, têm prazo de 10 s e User-Agent próprio, nunca seguem redirecionamento para outro host (o cabeçalho com o token iria junto) e verificam o TLS. O host é fixo (`api.mercadopago.com`), e o id que entra no caminho da URL é validado.
- Recusa rodar fora de um kind, sem escape, porque o token vai para um Secret do cluster.
- O freio contra um token de produção vem depois do pagamento. O Mercado Pago aceita o token de produção como o de teste, e o prefixo (`TEST-` ou `APP_USR-`) não os distingue: a conferência prévia prova que o token é aceito, não que é de teste. Só o `live_mode` verdadeiro do pagamento reprova o cenário, e a mensagem manda conferir primeiro no painel do Vendedor de teste (ela traz o id do pagamento) e, se for mesmo de produção, estornar e trocar as credenciais. O roteiro manda pagar com o comprador e o cartão de teste, que o checkout de produção recusa, então um pagamento real exigiria que você usasse um cartão real. Não conheço campo da preferência que distinga a conta de teste, e sem uma credencial não há como verificar.

## Solução de problemas

As recusas da conferência prévia começam com `[mp-sandbox] não posso seguir:`. A do `make` para credencial na linha de comando e a do pytest para o `E2E_MP_MODO` esquecido têm mensagem própria.

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| `MP_ACCESS_TOKEN não está no ambiente` | A credencial não chegou ao `make` | Leia com `read -rs` e passe só ao `make`, como no bloco de "Como rodar" |
| `MP_ACCESS_TOKEN tem espaço ou quebra de linha` | Valor colado, ou `read` sem `-r` | Leia de novo com `read -rs` |
| `MP_ACCESS_TOKEN e MP_WEBHOOK_SECRET não vão na linha do make` | Credencial escrita depois de `make mp-sandbox` | Tire-a da linha e use o bloco de "Como rodar" |
| `o Mercado Pago não aceita o MP_ACCESS_TOKEN (HTTP 401)` | Token de produção, de outra aplicação, revogado ou com espaço no fim | Use o Access Token de teste da aplicação, da mesma conta de teste |
| `serviços fora do ar pela borda` ou `o kubectl não conseguiu ler o cluster` | Cluster ou serviços fora do ar, ou `KUBE_CONTEXT` errado | Suba o cluster e os três serviços ("Como rodar") e confira o `KUBE_CONTEXT` |
| `o Billing está com os prazos do E2E (kind-ci)` | Cluster subido com `OVERLAY=kind-ci`, que é o do `make e2e` e do `make demo` | `make kind-down` e suba de novo no overlay `kind` (`make kind-up deploy` e o `implantar-servicos.sh` de "Como rodar"); trocar de overlay no mesmo cluster não desfaz o anterior |
| `E2E_MP_MODO=... está no seu shell` (no `make e2e` ou no `make demo`) | A variável ficou definida no shell | `unset E2E_MP_MODO` |
| O Mercado Pago recusou criar a cobrança (`POST /checkout/preferences` com 4xx) | Um dado da cobrança (valor, moeda, itens) ou a `notification_url`; o terminal diz o HTTP e os códigos que o Billing registrou, e qual URL foi usada | Procure os códigos na documentação do Mercado Pago e confira o valor e os itens. Para ver a linha inteira do log do Billing (a operação, o HTTP, o `error` e os códigos que ele deixou passar; o texto do Mercado Pago ele nunca registra): `kubectl --context kind-pytstop-p4 -n pytstop-billing logs deploy/billing-service-consumidor --tail=200 \| grep mercadopago_request_rejected`. Se suspeitar da URL, use outra URL https pública, por exemplo `https://example.org/api/v1/webhooks/mercadopago`: `E2E_MP_NOTIFICATION_URL=https://example.org/api/v1/webhooks/mercadopago make mp-sandbox` (junto das duas credenciais) ou, com o modo real mantido, `kubectl --context kind-pytstop-p4 -n pytstop-billing set env deployment --all MP_NOTIFICATION_URL=https://example.org/api/v1/webhooks/mercadopago` |
| O Mercado Pago recusou o pagamento | Nome do titular diferente de `APRO`, cartão errado, janela comum ou conta real logada | Janela anônima e só o usuário Comprador de teste; o cartão está no terminal |
| O painel do Mercado Pago pede código de verificação | A conta de teste é fictícia, sem e-mail de verdade | O código da tabela de contas de teste (coluna "Código de verificação") ou os 6 últimos dígitos do User ID da conta; o terminal lembra |
| O pagamento não confirma em 2 min | Conciliação parada | `kubectl --context kind-pytstop-p4 -n pytstop-billing logs deploy/billing-service-prazos` (a linha `deadlines_started` diz `conciliacao: true`) |
| `o Billing pode ter ficado em modo real` | O desfazer falhou em algum passo | Rode os comandos que a mensagem traz, ou `make mp-sandbox-ensaio` |
| `a expiração NÃO foi provada` ou `a natureza de teste do pagamento NÃO foi provada` (no `resumo.md`) | A consulta do Mercado Pago não trouxe `expires` e `expiration_date_to`, ou o `live_mode`, no formato esperado | Não reprova: o `resumo.md` registra a observação. Para a expiração, a prova indireta é o log do consumidor e a métrica `pytstop_mercadopago_requisicoes_total{operacao="cancelar_cobranca"}`; para o `live_mode`, o painel do vendedor de teste |
| `trace não encontrado` (no `resumo.md`) | Em 30 s o Jaeger não trouxe nenhum trace da OS que valesse: não respondeu pelo port-forward (o motivo traz o nome do erro), os spans ainda não tinham chegado ou ele reiniciou (guarda tudo na memória) | O trace ainda pode ser visto no Jaeger (`make port-forward`, busca pela tag `messaging.message.conversation_id` com o `ordem_id` do `resumo.md`) e capturado em print. Não baixe o JSON do Jaeger para a evidência: ele não é higienizado |
| `trace não gravado (descartado pela varredura de segredos)` (no `resumo.md`) | A varredura achou segredo no texto do trace | O resto da evidência foi gravado. Não procure o arquivo: ele não existe. Veja o trace no Jaeger e capture em print, e avise o time, porque algum serviço deixou dado sensível passar |

## O que fica fora do `make e2e`, do `make demo` e do CI

O `make e2e` pede `-m "not mp_sandbox"`, o `make demo` pede `-m demo`, e nenhum workflow cita o sandbox. Quem roda o pytest cru, sem `E2E_MP_MODO`, vê os três cenários pulados sem que o `kubectl` seja chamado, e com `E2E_MP_MODO` definido só eles rodam; `E2E_MP_MODO` definido sem nenhum cenário do sandbox selecionado é erro, e não um verde. O `make test` coleta o E2E sem cluster, e a falta de definição de um passo do feature reprova ali.

Os testes ficam em [`tests/e2e_apoio/`](../tests/e2e_apoio), com 100% de linhas e ramos do código novo de [`e2e/apoio/`](../e2e/apoio): um `kubectl` que grava argumentos e stdin prova que o token só passa pelo stdin e que o Secret não aparece em nenhum argumento; o desfazer roda com exceção, `KeyboardInterrupt` e falha no meio do ligar, e com processos de verdade provam que um sinal ao grupo (Ctrl-C, SIGTERM, SIGHUP) não mata o `kubectl` do desfazer e que um segundo Ctrl-C não o pula; o cliente do Mercado Pago é testado com `httpx.MockTransport` (formatos de `payments/{id}`, `payments/search` e `checkout/preferences/{id}`, erros 4xx e 5xx, redirecionamento); a espera e o prazo, com relógio falso; o `Makefile`, com um `uv` falso (a conferência antes dos relatórios, a rotação da evidência e a recusa de credencial na linha de comando); e o pytest de verdade, num subprocesso, prova a exclusão do sandbox, a conferência prévia que para antes de qualquer mudança no cluster e o relatório sem credencial.
