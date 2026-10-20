# Evidências da fase 4

Este diretório reúne as provas que precisam continuar acessíveis após a expiração dos artefatos do CI e da memória do Jaeger. As capturas finais devem registrar data, ambiente e commits dos quatro repositórios. Relatórios não podem conter credenciais, documentos pessoais, tokens ou dados de cartão.

| Evidência | Estado no ensaio | Como produzir ou conferir |
|---|---|---|
| Repositórios públicos, regras da `main` e commits associados a PR | [Proteção da `main` conferida em 20/10/2026](protecao-da-main.md); coletor versionado; repetir no congelamento | Metadados públicos do GitHub; percorrer o primeiro pai e conferir o PR de cada commit |
| CD verde e SBOM dos três serviços na `main` final | [Três serviços com o CD compartilhado aprovado na `main`](#cd-compartilhado-dos-serviços); repetir no congelamento | Guardar serviço, SHA, URL da execução, digest da imagem e resultado de cada job |
| Cobertura por camada e quality gate | [XMLs publicados e tabelas por camada](coverage.md): OS 99,62%, Billing 100%, Execução 100%, um run por serviço; repetir no congelamento | Tabelas geradas do XML do CI; guardar o run correspondente e o [resumo do SonarQube](coverage.md#sonarqube) |
| BDD completo | [14 cenários no CD da main](bdd-resumo.md), run 39231733886 aprovado em `bfa8c72` | Preservar junit, cucumber e resumo após a varredura de segredos; repetir sobre os commits finais |
| Trace da saga e correlação | Ensaio local de 19/10: `af146ea716424dfc2ac5b25960b8e9ae` contém os três serviços e CLIENT Execução → Billing; chamada Billing → Mercado Pago depende da sandbox real | Copiar o `trace-<cenário>-<trace_id>.json` que o `make mp-sandbox` salva já higienizado (README da plataforma, "O trace da saga"), em vez de exportar o JSON do Jaeger, que não é higienizado; capturar Jaeger e correlação do `X-Request-ID` no Loki |
| Nove dashboards e alerta disparado | Alerta de fila disparou e recuperou; capturas locais com 1 h de dados, histórico de três dias pendente | Ambiente kind com PVC por pelo menos três dias, alimentado por `make demo` diariamente; uma captura por dashboard e uma do alerta |
| Dez minutos sem tráfego | 600,9 s reais no simulador, sem reinícios; saúde e smoke aprovados | [Relatório parcial de observabilidade](observabilidade.md); repetir também no modo real do Mercado Pago |
| Mercado Pago real: cobrança, aprovação e estorno | Ação do responsável com credenciais de teste | `make mp-sandbox`; preservar só o `resumo.md` e os `trace-*.json`, já higienizados, sem dados do pagador ou credenciais |
| Collection integrada com newman | [Duas provas locais e CI do platform #24 aprovados](newman-resumo.md); CD da main aprovado; prova do congelamento pendente | Fluxo completo pela borda, incluindo métricas administrativas dos nove status; repetir no workflow sobre os commits finais |
| Vídeo, identificação e tags | Aguardam responsáveis e congelamento | Vídeo público ou não listado de até 15 min; identificar participantes e tags `entrega-fase-4` nos quatro repositórios |

O [relatório do ensaio local de 19/10/2026](observabilidade.md) reúne os resultados e as limitações de cada etapa. O painel de volume diário fica sem dados antes da primeira meia-noite UTC, conforme a descrição do seu JSON. A primeira execução diária de `make demo` passou com seis cenários em 111,11 s.


## CD compartilhado dos serviços

Provas de 19 e 20/10/2026, anteriores ao congelamento. Os três CDs abaixo concluíram CI, segurança, SonarQube, publicação da imagem, SBOM, implantação no kind efêmero do runner, smoke por namespace e BDD. O job `remote-skipped` passou e `deploy-remote` ficou desligado, porque o deploy entregue é o kind ([ADR-042](../../../arquitetura/adr/fase4/042-cicd-e-deploy-kubernetes.md)). Os jobs de implantação verificaram o arquivo da imagem do próprio serviço e seu digest; os vizinhos foram construídos dos checkouts registrados.

| Serviço | Primeiro CD compartilhado da main | Commit do serviço | Digest publicado | SBOM SPDX |
|---|---|---|---|---|
| OS Service | [run 39233375064](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-os-service/actions/runs/39233375064) | `5e4ed2a1c2d74bdc65cc207c3f5a208b4ea672ca` | `sha256:525ca3071034c1951b1d1066acf4a5ed3dc20f1e06651d15260b142a500f67b1` | 171 pacotes; SHA256 `aeb4c6d2a20c795eeee3e847b85865ea4fc27d35477494e112341cbef4bb5073` |
| Billing Service | [run 39355822794](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-billing-service/actions/runs/39355822794) | `735a0c23c16f584c02b2f6a77138549eb0a11ac5` | `sha256:3530f8c72f605a22f457d92b2a2c0f7994fa8c50a16311fda0e739c5e123054b` | 147 pacotes, contados no log do job `cd / image` |
| Execution Service | [run 39237570013](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-execution-service/actions/runs/39237570013) | `c33824f801280a115e07e64b93185a64e9f700c1` | `sha256:1dd539769c77f5e901e7372976aed19594c1a740bc73e528c4ea2a81618ac05f` | 162 pacotes; SHA256 `c313ec97f936481105d170db894da79cde41d1b51e96c0d00d52e1300db32c24` |

Os quatro checkouts de cada implantação foram conferidos no `git log -1 --format=%H` dos passos de checkout, na ordem do workflow fixado em `3f7cca2eb555a038b0d2780058ef0e692f93ee8a`:

| CD | Plataforma | OS | Billing | Execução |
|---|---|---|---|---|
| OS | `bfa8c72f1f8bf4c7af2994b73421137f00d02d64` | `5e4ed2a1c2d74bdc65cc207c3f5a208b4ea672ca` | `248c4071d357a867db1571081b012ff57753f834` | `6e34092022bbcf00918967099976a05b4b2882b0` |
| Execução | `bfa8c72f1f8bf4c7af2994b73421137f00d02d64` | `5e4ed2a1c2d74bdc65cc207c3f5a208b4ea672ca` | `248c4071d357a867db1571081b012ff57753f834` | `c33824f801280a115e07e64b93185a64e9f700c1` |
| Billing | `ef969e2f8aead8968849c55c985afc57984792ca` | `c3d6e6738265151dd0cb32ce1f8af180272aa1a7` | `735a0c23c16f584c02b2f6a77138549eb0a11ac5` | `ee29a7c91f3c30d7ee5a7937104b06e4029e0f0c` |

As imagens publicadas são `ghcr.io/fiap-postech-sw-architecture/pytstop-<serviço>:<commit>` (`os-service`, `billing-service` e `execution-service`), com os commits da primeira tabela. Os SBOMs do OS e da Execução vieram dos artefatos `sbom-os-service` e `sbom-execution-service`; as contagens e os hashes foram conferidos no JSON baixado. O do Billing está no artefato `sbom-billing-service` do run, e a contagem saiu do log. No CD do Billing, o E2E passou com 14 cenários, e os 3 da sandbox ficaram fora da seleção. Os resultados são do kind de cada runner e não alteram os commits do ensaio local de observabilidade.

Para conferir: `gh run view <run> --repo <organização/repositório> --json headSha,status,conclusion,jobs`; para preservar o SBOM, `gh run download <run> --repo <organização/repositório> --name sbom-<serviço> --dir <destino>`. Alterações posteriores e o congelamento exigem novas provas.

## Coleta e conferência reproduzíveis

Da raiz da plataforma, com Python 3.14/uv e `gh` autenticado, grave o snapshot fora do repositório:

```bash
uv run python -m scripts.evidencias.coletar --output /tmp/github-fase4.json
uv run python -m scripts.evidencias.verificar --github /tmp/github-fase4.json
```

O coletor faz somente consultas GET. Guarda visibilidade, SHA da `main`, regras efetivas, árvore de caminhos, SHAs e PRs do primeiro pai, tag, último CD e resultados dos jobs. Não guarda autores, mensagens de commit, eventos, logs, credenciais ou dados de negócio. Falha de acesso e árvore truncada interrompem a coleta; workflow ou tag ausente ficam como lacuna. O snapshot identifica os commits da coleta; precisa ser refeito após qualquer integração antes do fechamento.

A conferência de ensaio valida os 44 IDs e os links locais/GitHub. O modo final acrescenta visibilidade pública, PR/checks obrigatórios, CD verde no HEAD, origem dos commits e tag `entrega-fase-4` no mesmo SHA em cada repositório. Exige participantes, vídeo e os relatórios higienizados `bdd-resumo.md`, `coverage.md`, `observabilidade.md`, `mp-sandbox.md` e `newman-resumo.md` neste diretório. Esses relatórios devem trazer data, ambiente, quatro SHAs, comando e resultado, além dos links das provas. O modo final também reprova o documento de entrega, o índice e a matriz enquanto tiverem texto preliminar, como "versão preliminar", "pendente", "aguarda" ou "em coleta" (a lista está em `scripts/evidencias/verificar.py`). Arquivo presente não comprova seu conteúdo: a auditoria final confere as capturas, relatórios e qualidade das provas.

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

Instale `pandoc`, `weasyprint`, Node/npx e Python 3.14. A receita está versionada e usa `@mermaid-js/mermaid-cli@11.17.0`; o primeiro uso pode baixar o CLI/Chromium. A receita utiliza somente os arquivos versionados e não exige credenciais. A paginação também depende das versões de pandoc/weasyprint e das fontes instaladas; conferir as páginas após regenerar.

```bash
scripts/build-entrega-pdf.sh --output /tmp/entrega-fase-4-ensaio.pdf
scripts/build-entrega-pdf.sh --final --github /tmp/github-fase4.json --output /tmp/entrega-fase-4.pdf
```

O destino deve ficar fora do repositório. O build confere a igualdade do Mermaid entre RFC, README e documento, renderiza a arquitetura em página própria, reescreve os links por arquivo e anexa integralmente o índice da raiz. O ensaio mantém participantes, vídeo e demais pendências visíveis. O build final usa links locais na tag; antes dele, atualize também os links explícitos dos quatro repositórios na documentação para a mesma tag. O PDF não substitui os relatórios e capturas versionados.
