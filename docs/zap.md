# ZAP baseline na borda

> [↑ Raiz do projeto](../README.md)

O OWASP ZAP em modo *baseline* (as regras olham as respostas, sem as injeções do scan ativo, mas o spider chama cada operação do `openapi.json`) roda no job `e2e` do [`cd.yml`](../.github/workflows/cd.yml), depois do E2E e no mesmo kind, contra a borda como um cliente de fora a vê: `https://localhost/<prefixo>/openapi.json` de cada serviço, pelo certificado padrão do Kong. É a varredura do [ADR-041](arquitetura/adr/fase4/041-estrategia-de-testes-e-qualidade.md), que roda aqui e não no CD de cada serviço, para não somar minutos a cada deploy. O alvo é o `openapi.json` porque o `/docs` é o HTML do Swagger e não lista rota. O scan roda sem credencial: quase toda operação protegida responde 401, e o ZAP vê os cabeçalhos dessas respostas, não o comportamento autenticado.

O [`scripts/ci/zap-baseline.sh`](../scripts/ci/zap-baseline.sh) roda um container por serviço, na rede do host (no runner, o `localhost` é a porta 443 do kind), com a imagem da [tabela de versões](componentes-e-versoes.md#componentes-e-versões) por digest e as regras de [`e2e/zap/regras.conf`](../e2e/zap/regras.conf):

```bash
zap-baseline.py -t https://localhost/os/openapi.json -c regras.conf -m 1 -I -z "-silent" \
  -r zap-os-service.html -J zap-os-service.json -w zap-os-service.md
```

- `-I`: aviso não reprova, só regra em `FAIL`. `-m 1`: o spider para em 1 minuto.
- O spider importa o `openapi.json` e chama cada operação dele uma vez, com dados de exemplo, `POST`, `PUT` e `DELETE` inclusive (de 24 a 38 URLs por serviço, quase todas com resposta 4xx). Por isso o script só roda num kind descartável, depois do E2E: ele recusa, com status 2 e antes de qualquer chamada, uma `BORDA` que não seja só esquema, host do loopback (`localhost`, `127.0.0.1`, `[::1]` ou `*.localhost`) e porta, salvo `ZAP_ALVO_DESCARTAVEL` igual à própria `BORDA`, para um alvo descartável fora dele.
- `-z "-silent"`: sem ele, o `zap-baseline.py` da imagem atualiza e instala add-ons ao iniciar (`-addonupdate -addoninstall`), e o ZAP verifica atualização; com ele, nada disso. A varredura só pede páginas ao Kong do kind.
- O ZAP aceita o certificado autoassinado do Kong. Antes de cada scan, o `curl` confere que o `openapi.json` responde sem erro HTTP (o `-f` aceita 2xx e 3xx, e um 404 ou 503 reprova o serviço sem varrer), e depois o script reprova se o ZAP avisar que não leu o alvo (o aviso `expected 200` do ZAP cobre o que o `curl` deixa passar), se faltar a linha de resumo, se o status não for 0 ou se nenhuma URL foi lida. O piso de URLs só prova que a borda respondeu (certificado aceito, Kong de pé): o spider conta também os 404 que o Kong gera sozinho. Um serviço que reprova não impede a varredura dos outros.
- O container sobe com `--init` e com o nome `zap-<serviço>-<pid>`: o processo principal da imagem ignora o SIGTERM, e sem o `--init` o `PRAZO_ZAP` não encerraria um ZAP pendurado.
- A pasta `reports/zap` (ignorada pelo git) recebe `regras.conf`, `zap-<serviço>.html`, `.json`, `.md` e `.log`. O CI a publica como o artefato `zap-baseline` (90 dias), e a tabela por serviço (FAIL, WARN, URLs lidas) mais o `.md` de cada um vão para o summary do job.

Roda no Linux do runner. Em outro arranjo, `BORDA` (`https://localhost`), `ZAP_REDE` (rede do container, `host`), `RELATORIOS` (`reports/zap` na raiz do repositório, qualquer que seja a pasta de onde o script roda; um caminho relativo passado à mão vale a partir dela) e `PRAZO_ZAP` (segundos por serviço, 300) trocam o alvo, a rede, a pasta e o prazo. O `curl` roda na máquina do script, então a `BORDA` tem de responder ali também: um Kong avulso numa rede Docker entra com a porta publicada no loopback (`-p 127.0.0.1:<porta>:8443` e `BORDA=https://localhost:<porta>`).

## O que o ZAP acusa

Nenhuma regra em `FAIL` dispara com os três serviços na `main`: no run [39458619627](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-platform/actions/runs/39458619627) (platform d703200, OS 3ce582b, Billing 76b5f9b, Execução 5b1bef4), com as regras da tabela [abaixo](#regras-e-allowlist), o ZAP leu 38 URLs do OS, 38 do Billing e 24 da Execução, com `fail=0` nos três. Ficam os avisos abaixo.

| Achado | Onde | Tratamento |
|---|---|---|
| 10035, `Strict-Transport-Security` ausente (`WARN`) | Só nos 404 que o próprio Kong gera: `/`, `/<prefixo>`, `/robots.txt` e `/sitemap.xml`, que o spider pede. Toda resposta de serviço (`openapi.json`, `saude`, JWKS) traz o cabeçalho | Fica em `WARN`: o Kong sem rota casada não executa plugin nenhum. A regra só vira `FAIL` quando o Kong mandar o cabeçalho nesses 404 (dívida no MEMORY); um achado numa resposta de serviço é defeito do serviço e se corrige nele |
| 10024, informação sensível na URL (`WARN`) | Billing: o checkout do simulador e o `aprovar` e o `recusar` dele levam o `token` na query | Por desenho do simulador do Mercado Pago ([ADR-040](arquitetura/adr/fase4/040-integracao-mercado-pago.md)), que só existe com `MP_MODE=simulado`; o Promtail mascara o `token=` antes de ele chegar ao Loki ([`make smoke`](../scripts/smoke.sh)). Fica em `WARN`, visível |
| Respostas 5xx do Billing | Um `POST /billing/api/v1/webhooks/mercadopago` sem assinatura, que o spider monta do `openapi.json` | É a resposta tratada `503 SERVICO_INDISPONIVEL` do serviço (log `http_exception_handled`, nível `warning`), não um `500` |

## Regras e allowlist

Cada regra tem uma linha em `regras.conf` (`id`, ação e motivo, separados por TAB), e a tabela abaixo é a mesma: um teste compara as duas. `FAIL` reprova o job, `WARN` aparece no relatório e no summary sem reprovar, `IGNORE` some do relatório. Regra que não está no arquivo fica em `WARN`. Regra ignorada só entra quando o relatório mostrar o achado, com o motivo na linha do arquivo e na descrição do PR, e achado real se corrige na causa (um cabeçalho de segurança no Kong, por exemplo), não aqui.

| Regra | Ação | Motivo |
|---|---|---|
| 10036 | FAIL | HTTP Server Response Header: nome e versão de produto no `Server`. Os serviços sobem sem o `server` do uvicorn e o Kong com `headers=off` ([Gateway](gateway.md#gateway-como-um-serviço-publica-as-rotas)); sem a regra, qualquer um dos dois voltaria a anunciar a versão em silêncio |
| 10037 | FAIL | X-Powered-By: o mesmo motivo |
| 10020 | FAIL | Anti-clickjacking ausente. Os serviços põem o cabeçalho em toda resposta deles, mas o ZAP só avalia esta regra em resposta HTML, e o scan só recebe JSON deles: o `PASS` dela nos runs não prova que o cabeçalho está lá. Fica em `FAIL`, sem custo, e passa a valer se um serviço servir página HTML |
| 10021 | FAIL | `X-Content-Type-Options` ausente. O ZAP avalia esta regra em resposta JSON, então ela é o guarda de cabeçalho da API: um serviço que perder o cabeçalho reprova |
| 10038 | FAIL | CSP ausente: o mesmo caso do 10020, só vale em resposta HTML |
| 10035 | WARN | `Strict-Transport-Security` ausente nos 404 que o Kong gera sozinho (ver acima) |
| 10015 | IGNORE | Diretivas de `Cache-Control`: os serviços respondem `no-store` em toda resposta, e o ZAP quer também `no-cache` e `must-revalidate`; por isso o alerta dispara em `saude`, `saude/pronto` e `openapi.json` dos três serviços. O JWKS do OS responde `public, max-age=600` de propósito (a chave pública muda pouco) |
