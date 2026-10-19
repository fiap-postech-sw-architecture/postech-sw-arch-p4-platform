# Evidências da fase 4

Este diretório reúne as provas que precisam continuar acessíveis após a expiração dos artefatos do CI e da memória do Jaeger. As capturas finais devem registrar data, ambiente e commits dos quatro repositórios. Relatórios não podem conter credenciais, documentos pessoais, tokens ou dados de cartão.

| Evidência | Estado no ensaio | Como produzir ou conferir |
|---|---|---|
| Repositórios públicos, regras da `main` e commits associados a PR | Coletor versionado; repetir no congelamento | Metadados públicos do GitHub; percorrer o primeiro pai e conferir o PR de cada commit |
| CD verde e SBOM dos três serviços na `main` final | OS com pipeline completo; Billing e Execução aguardam chamada do workflow compartilhado | Guardar serviço, SHA, URL da execução, digest da imagem e resultado de cada job |
| Cobertura por camada e quality gate | Suites locais: OS 99,62%, Billing 100%, Execução 100%; capturas finais pendentes | Tabelas geradas do XML do CI; guardar o run correspondente e os relatórios do SonarQube |
| BDD completo | [CD da plataforma 39190581574](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-platform/actions/runs/39190581574) aprovado em `91d959b` | Preservar junit, cucumber e resumo após a varredura de segredos; repetir sobre os commits finais |
| Trace da saga e correlação | Ensaio local de 19/10: `af146ea716424dfc2ac5b25960b8e9ae` contém os três serviços e CLIENT Execução → Billing; chamada Billing → Mercado Pago depende da sandbox real | Exportar trace com spans dos três serviços e chamada ao provedor; capturar Jaeger e correlação do `X-Request-ID` no Loki |
| Nove dashboards e alerta disparado | Alerta de fila disparou e recuperou; capturas locais com 1 h de dados, histórico de três dias pendente | Ambiente kind com PVC por pelo menos três dias, alimentado por `make demo` diariamente; uma captura por dashboard e uma do alerta |
| Dez minutos sem tráfego | 600,9 s reais no simulador, sem reinícios; saúde e smoke aprovados | [Relatório parcial de observabilidade](observabilidade.md); repetir também no modo real do Mercado Pago |
| Mercado Pago real: cobrança, aprovação e estorno | Ação do responsável com credenciais de teste | `make mp-sandbox`; preservar só a saída sanitizada, sem dados do pagador ou credenciais |
| Collection integrada com newman | Implementação pendente | Fluxo completo pela borda, incluindo métricas administrativas dos nove status |
| Vídeo, identificação e tags | Aguardam responsáveis e congelamento | Vídeo público ou não listado de até 15 min; identificar participantes e tags `entrega-fase-4` nos quatro repositórios |

O [ensaio local de 19/10/2026](observabilidade.md) passou em `make e2e` (14 testes aprovados, três cenários de sandbox não selecionados, 194,52 s), dez minutos ociosos e `smoke-servicos`. A regra de fila sem consumidor disparou para `billing.comandos` e recuperou depois da restauração. O simulador não chama HTTP externo: o span CLIENT do Billing para o Mercado Pago continua dependendo da prova real. As capturas atuais têm uma hora de dados; não comprovam histórico de três dias. O painel de volume diário fica sem dados antes da primeira meia-noite UTC, conforme a descrição do seu JSON. A primeira execução diária de `make demo` passou com seis cenários em 111,11 s.


## Coleta e conferência reproduzíveis

Da raiz da plataforma, com Python 3.14/uv e `gh` autenticado, grave o snapshot fora do repositório:

```bash
uv run python -m scripts.evidencias.coletar --output /tmp/github-fase4.json
uv run python -m scripts.evidencias.verificar --github /tmp/github-fase4.json
```

O coletor faz somente consultas GET. Guarda visibilidade, SHA da `main`, regras efetivas, árvore de caminhos, SHAs e PRs do primeiro pai, tag, último CD e resultados dos jobs. Não guarda autores, mensagens de commit, eventos, logs, credenciais ou dados de negócio. Falha de acesso e árvore truncada interrompem a coleta; workflow ou tag ausente ficam como lacuna. O snapshot identifica os commits da coleta; precisa ser refeito após qualquer integração antes do fechamento.

A conferência de ensaio valida os 44 IDs e os links locais/GitHub. O modo final acrescenta visibilidade pública, PR/checks obrigatórios, CD verde no HEAD, origem dos commits e tag `entrega-fase-4` no mesmo SHA em cada repositório. Exige participantes, vídeo e os relatórios sanitizados `bdd-resumo.md`, `coverage.md`, `observabilidade.md`, `mp-sandbox.md` e `newman-resumo.md` neste diretório. Esses relatórios devem trazer data, ambiente, quatro SHAs, comando e resultado, além dos links das provas. Arquivo presente não comprova seu conteúdo: a auditoria final confere as capturas, relatórios e qualidade das provas.

```bash
uv run python -m scripts.evidencias.verificar --final --github /tmp/github-fase4.json
```

Os quatro commits abaixo criaram os repositórios antes do primeiro PR. São as únicas exceções à exigência de origem por PR; o verificador só as aceita no repositório correspondente e sem pais. Todo commit posterior precisa corresponder ao merge de um PR para `main`.

| Repositório | Bootstrap sem pais |
|---|---|
| OS Service | `4ad6f3d4787fc959563c08a978f6c7d055f00937` |
| Billing Service | `68f326dfab12200f06e2b5b4765cc09428cfd349` |
| Execution Service | `b77d56467fdefb32fbc315b109ad6697c0546d14` |
| Plataforma | `16f93ce23094627e16ff5a387b86bc5251722e12` |

## Gerar o PDF

Instale `pandoc`, `weasyprint`, Node/npx e Python 3.14. A receita está versionada e usa `@mermaid-js/mermaid-cli@11.17.0`; o primeiro uso pode baixar o CLI/Chromium. Não requer skill instalada, credencial ou caminho pessoal. A paginação também depende das versões de pandoc/weasyprint e das fontes instaladas; conferir as páginas após regenerar.

```bash
scripts/build-entrega-pdf.sh --output /tmp/entrega-fase-4-ensaio.pdf
scripts/build-entrega-pdf.sh --final --github /tmp/github-fase4.json --output /tmp/entrega-fase-4.pdf
```

O destino deve ficar fora do repositório. O build confere a igualdade do Mermaid entre RFC, README e documento, renderiza a arquitetura em página própria, reescreve os links por arquivo e anexa integralmente o índice da raiz. O ensaio mantém participantes, vídeo e demais pendências visíveis. O build final usa links locais na tag; antes dele, atualize também os links explícitos dos quatro repositórios na documentação para a mesma tag. O PDF não substitui os relatórios e capturas versionados.
