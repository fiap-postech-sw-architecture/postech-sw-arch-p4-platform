# Evidências da fase 4

Este diretório guarda as provas que se perderiam com a expiração dos artefatos do CI e com o descarte dos traces, que o Jaeger mantém só em memória. As capturas finais devem registrar data, ambiente e commits dos quatro repositórios. Relatórios não podem conter credenciais, documentos pessoais, tokens ou dados de cartão.

| Evidência | Estado na versão preliminar | Como produzir ou conferir |
|---|---|---|
| Repositórios públicos, regras da `main` e commits associados a PR | [Proteção da `main` conferida em 20/10/2026](protecao-da-main.md); coletor versionado; repetir no congelamento | Metadados públicos do GitHub; percorrer o primeiro pai e conferir o PR de cada commit |
| CD verde e SBOM dos três serviços na `main` final | [Três serviços com o CD compartilhado aprovado na `main`](#cd-compartilhado-dos-serviços); repetir no congelamento | Guardar serviço, SHA, URL da execução, digest da imagem e resultado de cada job |
| Cobertura por camada e quality gate | [XMLs publicados e tabelas por camada](coverage.md): OS Service 99,62%, Billing 100%, Execução 100%, um run por serviço; repetir no congelamento | Tabelas geradas do XML do CI; guardar o run correspondente e o [resumo do SonarQube](coverage.md#sonarqube) |
| BDD completo | [14 cenários no CD da `main`](bdd-resumo.md), run 39231733886 aprovado em `bfa8c72` | Preservar junit, cucumber e resumo após a varredura de segredos; repetir sobre os commits finais |
| Trace da saga e correlação | Ensaio local de 19/10: `af146ea716424dfc2ac5b25960b8e9ae` contém os três serviços e o span CLIENT da chamada Execução → Billing; a chamada Billing → Mercado Pago depende da sandbox real; [capturas do Jaeger](#capturas-de-tela) de 20/10 | Copiar o `trace-<cenário>-<trace_id>.json` que o `make mp-sandbox` já salva higienizado (README da plataforma, "O trace da saga"); o JSON exportado do Jaeger não é higienizado. Capturar o Jaeger e a correlação do `X-Request-ID` no Loki |
| Nove dashboards e alerta disparado | Alerta de fila disparou e recuperou; capturas locais com 1 h de dados, histórico de três dias pendente | Ambiente kind com PVC por pelo menos três dias, alimentado por `make demo` diariamente; uma captura por dashboard e uma do alerta |
| Dez minutos sem tráfego | Janela medida de 600,9 s com o simulador, sem reinícios; saúde e smoke aprovados | [Relatório parcial de observabilidade](observabilidade.md); repetir também no modo real do Mercado Pago |
| Mercado Pago real: cobrança, aprovação e estorno | Ação do integrante com as credenciais de teste | `make mp-sandbox`; preservar só o `resumo.md` e os `trace-*.json`, já higienizados, sem dados do pagador ou credenciais |
| Collection integrada com Newman | [Duas provas locais e CI do platform #24 aprovados](newman-resumo.md); CD da `main` aprovado; prova do congelamento pendente | Fluxo completo pela borda, incluindo métricas administrativas dos nove status; repetir no workflow sobre os commits finais |
| Vídeo, identificação e tags | Aguardam o grupo e o congelamento | Vídeo público ou não listado de até 15 min; identificar os participantes; criar a tag `entrega-fase-4` nos quatro repositórios |

O [relatório do ensaio local de 19/10/2026](observabilidade.md) reúne os resultados e as limitações de cada etapa. O painel de volume diário fica sem dados antes da primeira meia-noite UTC, conforme a descrição do seu JSON. A primeira execução diária de `make demo` passou com seis cenários em 111,11 s.

## Capturas de tela

O [Anexo B do documento de entrega](../entrega-fase-4.md#anexo-b--evidências-visuais) mostra as imagens abaixo, uma por item, com legenda e fonte. As novas têm 1400 px de largura. Nenhuma mostra dado pessoal, credencial ou token. As do GitHub são das páginas públicas, sem login. O Jaeger e o Swagger vêm do kind `pytstop-p4-codex`, que roda os commits do ensaio de 19/10 (OS `b81f609`, Billing `248c407` e Execução `605a5e5`). O kind só recebeu leituras: `kubectl port-forward` do `svc/jaeger` (porta 16686) e GET pelo Kong em `https://localhost`, com o certificado autoassinado. O print do caminho feliz vem de um Jaeger 1.76.0 avulso, em Docker, que recebeu o JSON pela aba Upload e foi removido em seguida. Os prints foram feitos com Chrome sem interface, pelo Playwright.

| Arquivo | O que mostra | Fonte |
|---|---|---|
| [cd-os-service-main-2026-10-20.png](cd-os-service-main-2026-10-20.png) | CD da `main` do OS Service com todos os jobs verdes e o `remote-skipped` | [run 39449191933](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-os-service/actions/runs/39449191933), `3ce582b` |
| [cd-billing-service-main-2026-10-20.png](cd-billing-service-main-2026-10-20.png) | O mesmo para o Billing Service | [run 39449241713](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-billing-service/actions/runs/39449241713), `76b5f9b` |
| [cd-execution-service-main-2026-10-20.png](cd-execution-service-main-2026-10-20.png) | O mesmo para o Execution Service | [run 39449216419](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-execution-service/actions/runs/39449216419), `5b1bef4` |
| [cd-platform-main-2026-10-20.png](cd-platform-main-2026-10-20.png) | CD da `main` do platform com o CI, o `deploy-kind` e o `e2e` verdes | [run 39449167465](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-platform/actions/runs/39449167465), `a12502e` |
| [cd-platform-e2e-passos-2026-10-20.png](cd-platform-e2e-passos-2026-10-20.png) | Passos do job `e2e`: smoke, E2E, Newman e ZAP aprovados | [job do mesmo run](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-platform/actions/runs/39449167465/job/118731446687) |
| [cd-platform-newman-2026-10-20.png](cd-platform-newman-2026-10-20.png) | Resumo do Newman: assertions, falhas, requisições e provas de negócio | Artefato `e2e-kind`, `newman/resumo.json`, do mesmo run |
| [cd-platform-zap-2026-10-20.png](cd-platform-zap-2026-10-20.png) | Resumo do ZAP baseline por serviço: FAIL, WARN, PASS, URLs lidas e alertas | Artefato `zap-baseline`, `zap-<serviço>.log` e `.json`, do mesmo run |
| [jaeger-busca-saga-2026-10-20.png](jaeger-busca-saga-2026-10-20.png) | Busca no Jaeger com três traces da saga, cada um com spans dos três serviços | Jaeger 1.76.0 do kind, 20/10/2026, 09:03 (Brasília) |
| [jaeger-trace-saga-2026-10-20.png](jaeger-trace-saga-2026-10-20.png) | Linha do tempo do trace `bfe21ce701ea69d6afc008a870d2ce21`: 339 spans, 3 serviços, 7,63 s | Mesma busca |
| [jaeger-upload-caminho-feliz-2026-10-20.png](jaeger-upload-caminho-feliz-2026-10-20.png) | Trace do caminho feliz de 19/10 (245 spans, 3 serviços) aberto pela aba Upload | [trace-saga-2026-10-19.json](trace-saga-2026-10-19.json) num Jaeger 1.76.0 avulso, em Docker |
| [swagger-os-service-2026-10-20.png](swagger-os-service-2026-10-20.png) | Swagger do OS Service pela borda, em `/os/docs` | Kong do kind, 20/10/2026 |
| [swagger-billing-service-2026-10-20.png](swagger-billing-service-2026-10-20.png) | Swagger do Billing Service, em `/billing/docs` | Kong do kind, 20/10/2026 |
| [swagger-execution-service-2026-10-20.png](swagger-execution-service-2026-10-20.png) | Swagger do Execution Service, em `/execucao/docs` | Kong do kind, 20/10/2026 |
| [alerta-fila-disparado-2026-10-19.png](alerta-fila-disparado-2026-10-19.png) | Alerta de fila sem consumidor em Firing para `billing.comandos` | Grafana do kind, [relatório do ensaio](observabilidade.md#alertas-e-recuperação) |
| [alerta-fila-recuperado-2026-10-19.png](alerta-fila-recuperado-2026-10-19.png) | O mesmo alerta de volta a Normal | Grafana do kind, mesmo relatório |

Os resumos do Newman e do ZAP são páginas montadas com os números dos arquivos do artefato; nenhum valor é digitado à mão. O log do passo no GitHub exige login, e o do Newman só traz o resultado do pytest. O Jaeger do kind guarda os traces só na memória e descarta os mais antigos: o trace do caminho feliz de 19/10 (245 spans) já saiu, e a exportação publicada é a do [trace-saga-2026-10-19.json](trace-saga-2026-10-19.json). Os nove dashboards do Grafana entram na seção B6 do Anexo B do documento depois da captura de 22/10/2026, com três dias de histórico.

## CD compartilhado dos serviços

Provas de 19 e 20/10/2026, anteriores ao congelamento. Os três CDs abaixo concluíram CI, segurança, SonarQube, publicação da imagem, SBOM, implantação no kind efêmero do runner, smoke por namespace e BDD. O job `remote-skipped` passou e `deploy-remote` ficou desligado, porque o deploy entregue é o kind ([ADR-042](../../../arquitetura/adr/fase4/042-cicd-e-deploy-kubernetes.md)). Os jobs de implantação verificaram o arquivo da imagem do próprio serviço e seu digest; as imagens dos outros dois serviços foram construídas dos checkouts registrados.

| Serviço | Primeiro CD compartilhado da main | Commit do serviço | Digest publicado | SBOM SPDX |
|---|---|---|---|---|
| OS Service | [run 39233375064](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-os-service/actions/runs/39233375064) | `5e4ed2a1c2d74bdc65cc207c3f5a208b4ea672ca` | `sha256:525ca3071034c1951b1d1066acf4a5ed3dc20f1e06651d15260b142a500f67b1` | 171 pacotes; SHA256 `aeb4c6d2a20c795eeee3e847b85865ea4fc27d35477494e112341cbef4bb5073` |
| Billing Service | [run 39355822794](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-billing-service/actions/runs/39355822794) | `735a0c23c16f584c02b2f6a77138549eb0a11ac5` | `sha256:3530f8c72f605a22f457d92b2a2c0f7994fa8c50a16311fda0e739c5e123054b` | 147 pacotes, contados no log do job `cd / image` |
| Execution Service | [run 39237570013](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-execution-service/actions/runs/39237570013) | `c33824f801280a115e07e64b93185a64e9f700c1` | `sha256:1dd539769c77f5e901e7372976aed19594c1a740bc73e528c4ea2a81618ac05f` | 162 pacotes; SHA256 `c313ec97f936481105d170db894da79cde41d1b51e96c0d00d52e1300db32c24` |

Os quatro checkouts de cada implantação foram conferidos no `git log -1 --format=%H` dos passos de checkout, na ordem do workflow fixado em `3f7cca2eb555a038b0d2780058ef0e692f93ee8a`:

| CD | Plataforma | OS Service | Billing | Execução |
|---|---|---|---|---|
| OS Service | `bfa8c72f1f8bf4c7af2994b73421137f00d02d64` | `5e4ed2a1c2d74bdc65cc207c3f5a208b4ea672ca` | `248c4071d357a867db1571081b012ff57753f834` | `6e34092022bbcf00918967099976a05b4b2882b0` |
| Execução | `bfa8c72f1f8bf4c7af2994b73421137f00d02d64` | `5e4ed2a1c2d74bdc65cc207c3f5a208b4ea672ca` | `248c4071d357a867db1571081b012ff57753f834` | `c33824f801280a115e07e64b93185a64e9f700c1` |
| Billing | `ef969e2f8aead8968849c55c985afc57984792ca` | `c3d6e6738265151dd0cb32ce1f8af180272aa1a7` | `735a0c23c16f584c02b2f6a77138549eb0a11ac5` | `ee29a7c91f3c30d7ee5a7937104b06e4029e0f0c` |

As imagens publicadas são `ghcr.io/fiap-postech-sw-architecture/pytstop-<serviço>:<commit>` (`os-service`, `billing-service` e `execution-service`), com os commits da primeira tabela. Os SBOMs do OS Service e da Execução vieram dos artefatos `sbom-os-service` e `sbom-execution-service`; as contagens e os hashes foram conferidos no JSON baixado. O do Billing está no artefato `sbom-billing-service` do run, e a contagem saiu do log. No CD do Billing, o E2E passou com 14 cenários, e os 3 da sandbox ficaram fora da seleção.

Para conferir: `gh run view <run> --repo <organização/repositório> --json headSha,status,conclusion,jobs`; para preservar o SBOM, `gh run download <run> --repo <organização/repositório> --name sbom-<serviço> --dir <destino>`. Alterações posteriores e o congelamento exigem novas provas.

## Coleta e conferência reproduzíveis

Da raiz da plataforma, com Python 3.14/uv e `gh` autenticado, grave o snapshot fora do repositório:

```bash
uv run python -m scripts.evidencias.coletar --output /tmp/github-fase4.json
uv run python -m scripts.evidencias.verificar --github /tmp/github-fase4.json
```

O coletor faz somente consultas GET. Guarda visibilidade, SHA da `main`, regras efetivas, árvore de caminhos, SHAs e PRs do primeiro pai, tag, último CD e resultados dos jobs. Não guarda autores, mensagens de commit, eventos, logs, credenciais ou dados de negócio. Falha de acesso e árvore truncada interrompem a coleta; workflow ou tag ausente ficam como lacuna. O snapshot vale só para os commits coletados; qualquer integração antes do fechamento exige nova coleta.

A conferência padrão valida os 44 IDs de requisito e os links locais e do GitHub. O modo final acrescenta visibilidade pública, PR/checks obrigatórios, CD verde no HEAD, origem dos commits e tag `entrega-fase-4` no mesmo SHA em cada repositório. Exige participantes, vídeo e os relatórios higienizados `bdd-resumo.md`, `coverage.md`, `observabilidade.md`, `mp-sandbox.md` e `newman-resumo.md` neste diretório. Esses relatórios devem trazer data, ambiente, quatro SHAs, comando e resultado, além dos links das provas. O modo final também reprova o documento de entrega, o índice e a matriz enquanto tiverem texto preliminar, como "versão preliminar", "pendente", "aguarda" ou "em coleta" (a lista está em `scripts/evidencias/verificar.py`). Arquivo presente não comprova seu conteúdo: a auditoria final confere as capturas, relatórios e qualidade das provas.

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

Instale `pandoc`, `weasyprint`, Node/npx e Python 3.14. O script usa o `@mermaid-js/mermaid-cli@11.17.0`, lê somente arquivos versionados e não exige credenciais; no primeiro uso, pode baixar o CLI e o Chromium. A paginação depende das versões do pandoc e do weasyprint e das fontes instaladas; confira as páginas depois de regenerar.

```bash
scripts/build-entrega-pdf.sh --output /tmp/entrega-fase-4-ensaio.pdf
scripts/build-entrega-pdf.sh --final --github /tmp/github-fase4.json --output /tmp/entrega-fase-4.pdf
```

O PDF deve ficar fora do repositório. O build abre com a capa ABNT das fases anteriores (com o logo e os participantes da seção 1), põe o sumário logo depois dela e numera as páginas no rodapé, sem número na capa. Confere que todo diagrama Mermaid do documento é cópia de um da RFC-004, e o geral também do README; os diagramas largos vão para página paisagem própria, os altos ficam no texto, e a legenda traz a seção da RFC. Converte os links relativos em links do GitHub, embute as imagens do Anexo B (`pdfimages -list` no PDF mostra uma por figura, uma por diagrama e o logo) e anexa o índice inteiro como Anexo C. A versão preliminar mantém o vídeo e as demais pendências visíveis. No build final, os links relativos apontam para a tag; antes dele, troque para a mesma tag também os links explícitos dos quatro repositórios na documentação.
