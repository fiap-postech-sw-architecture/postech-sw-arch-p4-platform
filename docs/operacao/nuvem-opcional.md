# Nuvem opcional: o deploy remoto desligado

> [↑ Raiz do projeto](../../README.md)

Nada deste documento faz parte do estado entregue da fase 4. O deploy automatizado da fase é o kind efêmero do runner: o job `deploy-kind` do CD de cada serviço sobe a plataforma e os três serviços num cluster que some com o job e valida o deploy com o smoke de cada namespace e o E2E da saga ([ADR-042](../arquitetura/adr/fase4/042-cicd-e-deploy-kubernetes.md)). O enunciado pede deploy automatizado em Kubernetes e não cita nuvem, e a infraestrutura AWS da fase 3 já foi desmontada.

Para o caso de a avaliação pedir um ambiente que fique de pé, o CD tem um gancho neutro de provedor, desligado: o job `deploy-remote`, que chama o [`scripts/ci/deploy-remoto.sh`](../../scripts/ci/deploy-remoto.sh) deste repositório. Este documento diz o que o gancho faz, o que o dono do ambiente teria de criar para ligá-lo e traz duas receitas de cluster. As receitas não foram executadas nesta fase, e cada uma abre com esse aviso.

## Estado entregue

Conferido em 18/10/2026:

- Na `main` dos serviços, só o OS Service tem `cd.yml`; o Billing e a Execução têm `ci.yml` e `security.yml`.
- Nenhum dos quatro repositórios da fase 4 tem variável de Actions. As da organização só um administrador lista.
- No último CD do OS Service na `main` ([run 38837346818](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-os-service/actions/runs/38837346818), 15/10/2026), o `deploy-remote` ficou de fora e o `remote-skipped` passou: `DEPLOY_REMOTO_HABILITADO` não era `true` em nível nenhum.
- O job `deploy-remote` do `cd.yml` do OS Service não declara segredo, `environment` nem `id-token`, e o arquivo não tem credencial de provedor.

## O que o gancho faz

O job `deploy-remote` do `cd.yml` do OS Service (`e2bf48d`):

1. Roda depois do `image` e do `deploy-kind`, só na `main` e só com a variável `DEPLOY_REMOTO_HABILITADO` igual a `true`. Com outro valor, ou sem a variável, roda no lugar dele o `remote-skipped`, que só registra um aviso no run.
2. Tem 20 minutos e só as permissões `contents: read` e `packages: read`.
3. Confere que o commit do platform usado no kind está na `main` do platform (`compare main...<sha>`, só `identical` ou `behind`) e faz o checkout dele em `platform/`.
4. Tem um passo "Acesso ao cluster remoto (a configurar)", que hoje só avisa: é onde entra o kubeconfig ou o login do provedor.
5. Chama `platform/scripts/ci/deploy-remoto.sh --contexto "$DEPLOY_REMOTO_CONTEXTO" --overlay "$DEPLOY_REMOTO_OVERLAY" --servico os-service --imagem <referência>:<commit>@sha256:<digest>`, com o overlay `k3s` se a variável do overlay não existir, e com a mesma imagem, pelo digest, que passou no kind.

O `deploy-remoto.sh` roda a partir do checkout do serviço e não guarda credencial nem chama nuvem: usa o contexto que o kubeconfig de quem roda já tem.

- Recusa, sem tocar no cluster, argumento faltando, repetido ou vazio (com `--context` vazio o kubectl usaria o contexto atual do kubeconfig, qualquer que fosse o cluster), serviço que não seja `os-service`, `billing-service` ou `execution-service`, overlay que não seja um nome simples (letras, dígitos, `_` e `-`: o nome vai para o YAML e para o caminho do overlay gerado), imagem sem `@sha256:` com 64 dígitos hexadecimais e imagem que não seja a `pytstop-<serviço>`.
- Gera `k8s/overlays/execucao` no checkout do serviço: o overlay pedido com a imagem fixada pelo digest (a tag sai), o mesmo diretório que o `implantar-servicos.sh` gera no kind e que os serviços já ignoram no git. Renderiza esse overlay antes de tocar no cluster, com o prazo de uma chamada ao kubectl, e para se a imagem do serviço não aparece nele (no checkout de outro repositório, como o do platform, que também tem overlay `k3s`, o apply implantaria outros manifests) ou se ele tem objeto fora do namespace do serviço: só passam os objetos desse namespace e o Namespace dele, porque o apply, com a credencial de administrador, aplicaria qualquer um.
- Implanta no namespace do serviço na ordem do [Contrato com os serviços](../../README.md#contrato-com-os-serviços): confere os Secrets da plataforma (ausentes, pede o `make deploy`; ilegíveis, mostra o erro do kubectl e lembra que a credencial do cluster pode ter vencido), apaga os Jobs de inicialização, aplica com `apply --server-side` e espera o banco, o Job e cada Deployment, com os prazos do `implantar-servicos.sh` (`PRAZO_KUBECTL`, `ESPERA_BANCO`, `ESPERA_JOB` e `ESPERA_DEPLOYMENT`). As funções são as mesmas dos dois scripts, em [`scripts/ci/implantacao.sh`](../../scripts/ci/implantacao.sh).
- Apaga o overlay gerado no fim, também na falha.

O [`tests/test_deploy_remoto.py`](../../tests/test_deploy_remoto.py) prova esse comportamento com um `kubectl` falso, para os três serviços, e confere as duas guardas da renderização com o `kubectl kustomize` de verdade.

## Para ligar

O dono do ambiente, nesta ordem:

1. Sobe um cluster (uma das receitas abaixo) e implanta a plataforma nele uma vez, da própria máquina, com o contexto do cluster no kubeconfig: `make deploy OVERLAY=k3s KUBE_CONTEXT=<contexto>` ([k3s, no README](../../README.md#k3s-vm-na-azure)). É o `make deploy` que cria os namespaces dos serviços e os Secrets deles; sem os Secrets, o `deploy-remoto.sh` para pedindo o `make deploy`.
2. Cria as variáveis da tabela abaixo no repositório de cada serviço que vai implantar (ou na organização) e os segredos no `environment` do job, em cada repositório: não existe `environment` de organização.
3. No job `deploy-remote`, declara o `environment` que guarda o segredo e troca o passo "Acesso ao cluster remoto (a configurar)" pelo acesso real. O passo pronto para um kubeconfig está no [README do OS Service](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p4-os-service#deploy-remoto-opcional), seção "Deploy remoto (opcional)".
4. Acrescenta ao job o checkout do próprio serviço, no commit do run, e roda o script de dentro dele: hoje o job só faz o checkout do platform, e o script para dizendo que não achou o overlay. O checkout do serviço vai antes do checkout do platform, ou num `path:` próprio, com `working-directory:` nele e o script chamado como `../platform/scripts/ci/deploy-remoto.sh`: um checkout na raiz depois do platform apaga o `platform/`.
5. Relaxa de propósito o teste do OS Service que proíbe segredo, `environment` e `id-token` no `deploy-remote` (`test_deploy_remote_nao_tem_segredo_nem_credencial_de_provedor`): ele guarda o estado desligado.

| Nome | Tipo | Onde | Para quê |
|---|---|---|---|
| `DEPLOY_REMOTO_HABILITADO` | variável | repositório ou organização | `true` liga o `deploy-remote`; outro valor, ou a falta dela, roda o `remote-skipped` |
| `DEPLOY_REMOTO_CONTEXTO` | variável | repositório ou organização | nome do contexto no kubeconfig (`kubectl config get-contexts` lista); sem ela o job reprova nomeando-a |
| `DEPLOY_REMOTO_OVERLAY` | variável | repositório ou organização | overlay dos manifests do serviço; sem ela, `k3s` |
| `KUBECONFIG_REMOTO` | segredo | `environment` com as branches de deploy restritas à `main` (por exemplo, `cluster-remoto`) | o kubeconfig do cluster (receita do k3s). Um segredo de repositório não serve: qualquer workflow de qualquer branch o lê |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN` | segredos | o mesmo `environment` | a sessão do AWS Academy (receita do EKS), regravada a cada sessão do laboratório |

**Credencial do CI.** As duas receitas abaixo dão ao runner a credencial de administrador do cluster (no k3s, o `k3s.yaml`, com o certificado de cliente do `system:admin`; no EKS, a `LabRole`, que criou o cluster): é o atalho delas, e quem o usa aceita que o segredo do `environment` abre o cluster inteiro. O caminho recomendado é uma ServiceAccount só do CD, com uma Role em cada namespace de serviço para o que os manifests dele aplicam, os Secrets da plataforma lidos pelo nome, os Jobs apagados, os rollouts e os logs, mais `get` e `patch` no Namespace do serviço, que o overlay inclui e é objeto de cluster, e um token de validade curta. O certificado de cliente do k3s vence em um ano (o k3s o renova no start quando faltam menos de 90 dias), e o kubeconfig do segredo tem de ser regravado antes disso.

As credenciais do Mercado Pago não entram no GitHub em nenhum caso (seção [O que o gancho não faz](#o-que-o-gancho-não-faz)).

### Como chamar o script à mão

A imagem é a referência e o digest que o job `image` do CD escreve no summary do run (tabela "Image", linhas "Reference" e "Digest"), juntos com `@`: `ghcr.io/fiap-postech-sw-architecture/pytstop-os-service:<commit>@sha256:<digest>`. Com ela em `IMAGEM` e o contexto do cluster no kubeconfig, a partir do checkout do serviço, com o platform clonado ao lado:

```bash
../postech-sw-arch-p4-platform/scripts/ci/deploy-remoto.sh --contexto k3s-pytstop --overlay k3s --servico os-service --imagem "$IMAGEM"
```

No lugar de `k3s-pytstop`, use o nome do contexto do cluster no seu kubeconfig. O cluster puxa a imagem do GHCR: só o pacote do OS Service é público (o do Billing e o da Execução respondem 403 ao pull anônimo), e outro serviço precisa de pacote público ou de um `imagePullSecret` no namespace dele. A imagem do CD é só `linux/amd64`: um nó arm64, como o do kind num Mac com Apple Silicon, não a puxa (`no match for platform in manifest`).

Contra o kind local (contexto `kind-pytstop-p4`, depois do `make kind-up` e do `make deploy OVERLAY=kind-ci` no platform), o script rodou em 18/10/2026 a partir do checkout do OS Service em `e2bf48d`, com o overlay `kind-ci`, num Mac com Apple Silicon. Com a imagem do último CD verde do OS Service pelo digest, passou pelas guardas, pelos Secrets, pelo apply e pelo banco e parou no Job de migração, que não puxou a imagem `linux/amd64`, e apagou o overlay gerado. Com o mesmo commit construído para arm64, carregado no nó e fixado pelo digest, o Job e os cinco Deployments do OS Service subiram, e uma segunda execução com o mesmo digest também passou. Contra um cluster remoto, o script não foi executado nesta fase.

## Receita 1: EKS no AWS Academy, como na fase 3

Receita não executada nesta fase. Vem do repositório [postech-sw-arch-p3-infra-k8s](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p3-infra-k8s) (commit `a75430a`) e do job `deploy-eks` do CD da fase 3 ([ADR-030](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p3/blob/main/docs/arquitetura/adr/fase3/030-cluster-kubernetes-eks.md)).

1. **Cluster.** O Terraform daquele repositório cria um EKS 1.34 em `us-east-1`, com um node group de dois `t3.medium` (até três) e a `LabRole` do laboratório nos papéis, porque o IAM do Learner Lab não deixa criar papel. Com a sessão do laboratório ativa e as credenciais na cadeia padrão da AWS CLI: `make plan`, `make apply` (de 10 a 15 minutos) e `make kubeconfig`, que funde o cluster no kubeconfig (o mesmo que `aws eks update-kubeconfig --name pytstop-p3 --region us-east-1`). O state remoto fica num bucket S3 da conta do laboratório da fase 3: outra conta exige trocar o backend e, para não confundir com a fase 3, o nome do cluster.
2. **Overlay.** A fase 4 não tem overlay de EKS. O `k3s` do platform fixa a StorageClass `local-path`, que o EKS não tem, e conta com o ServiceLB do k3s para publicar o Kong; no EKS, o Service `LoadBalancer` do Kong cria um balanceador da AWS. Um overlay próprio (StorageClass e exposição do Kong) teria de ser escrito no platform e em cada serviço.
3. **Acesso no CD.** Sem OpenID Connect no Learner Lab, o passo de acesso do `deploy-remote` usa os três segredos da sessão com a action `aws-actions/configure-aws-credentials` e roda o mesmo `aws eks update-kubeconfig`, como o `deploy-eks` da fase 3. O nome do contexto que esse comando grava (`kubectl config current-context` mostra) vai em `DEPLOY_REMOTO_CONTEXTO`.
4. **Limites.** A sessão do laboratório dura cerca de 4 horas, e alguém tem de regravar os segredos a cada uma; sem isso, o `deploy-remote` reprova no acesso. É o motivo de o ADR-042 ter descartado o EKS como alvo. O budget do Learner Lab é pequeno e esgotá-lo encerra a conta: `make destroy` ao fim da janela, porque o End Lab não para a cobrança do control plane.

## Receita 2: k3s numa VM da Azure

Receita não executada nesta fase. Vem da fase 2, que rodou o k3s numa VM da assinatura Azure for Students ([ADR-025 da fase 2, adendo](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p3/blob/main/docs/arquitetura/adr/fase2/025-ambiente-cloud-demonstracao.md); Terraform em `infra/azure-vm/` do repositório [postech-sw-arch-p2](https://github.com/fiap-postech-sw-architecture/postech-sw-arch-p2), commit `e96beea`).

1. **VM.** A assinatura de estudante restringe as regiões e bloqueia o AKS, mas aceita VM avulsa. O Terraform da fase 2 abre a 22 e a 6443 só ao IP do operador e as portas da demonstração dela (8080, 8000, 16686 e 9090) a qualquer origem: na fase 4 nada escuta nessas quatro, e o Network Security Group fica só com 80 e 443 abertas, mais a 22 restrita a quem administra (e a 6443 do passo 5). A fase 2 usou uma `Standard_D2s_v3` (2 vCPU e 8 GB). Para a fase 4, o orçamento de memória do ADR-042 (cerca de 3,5 GiB de requests e 8,9 GiB de limits) pede 16 GB se a quota permitir; com 8 GB, o perfil enxuto do `kind-ci`.
2. **k3s.** A fase 2 o instalou no primeiro boot, por cloud-init, com `curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="--disable traefik --tls-san <IP público>" sh -`; para a fase 4, com a versão fixada na do Kubernetes contra a qual o `make manifests` valida os manifests, `INSTALL_K3S_VERSION=v1.35.0+k3s1` ao lado do `INSTALL_K3S_EXEC` (sem ela, o script instala a última estável). O `--disable traefik` é o que o overlay `k3s` do platform pressupõe: o Service `kong-proxy` fica `LoadBalancer`, e o ServiceLB do k3s publica as portas 80 e 443 da VM no Kong. O `--tls-san` põe o IP público no certificado da API.
3. **Hostname e certificado.** Para receber o webhook do Mercado Pago, o Kong precisa de um hostname (o rótulo DNS do IP público da Azure serve) e de um certificado para ele (do Let's Encrypt, por exemplo pelo cert-manager), que nem o overlay `k3s` nem esta receita trazem; sem eles, a conciliação a cada 30 s confirma o pagamento, como no kind.
4. **Kubeconfig.** A fase 2 copiou o `/etc/rancher/k3s/k3s.yaml` da VM por SSH, trocando `127.0.0.1` pelo IP público. É esse arquivo que vai no segredo `KUBECONFIG_REMOTO`, e o nome do contexto dele, em `DEPLOY_REMOTO_CONTEXTO`.
5. **Acesso no CD.** O runner do GitHub precisa alcançar a API do k3s (porta 6443), protegida só pelo certificado de cliente do kubeconfig. Os runners hospedados saem de faixas de IP amplas, que o GitHub publica na API `meta`, então restringir a porta a eles no Network Security Group não é prático: abrir a 6443 expõe a API do cluster à internet, risco que o dono do ambiente tem de aceitar. A alternativa é não ligar o `deploy-remote` e rodar o `deploy-remoto.sh` da própria máquina, por um túnel SSH até a VM.
6. **Custo.** Com preços consultados pela fase 2 em julho de 2026, a `D2s_v3` custava cerca de US$ 14 por mês como Spot e US$ 70 sob demanda, mais o IP público. A fase 2 a religava com `az vm start`.

## O que o gancho não faz

- **Billing com URL pública e Mercado Pago real.** O ConfigMap do Billing na `main` (`d6d2776`) traz `BILLING_PUBLIC_URL=https://localhost/billing`, `MP_MODE=simulado` e `SIMULADOR_PERMITIDO=true`, e o overlay `k3s` dele não os troca. Num cluster com hostname público, o dono do ambiente cria no cluster o Secret `billing-mercadopago`, com `MP_ACCESS_TOKEN` e `MP_WEBHOOK_SECRET`, e troca as três variáveis nos Deployments do Billing, nunca por segredo do GitHub. Variável trocada por `kubectl set env` fica no Deployment depois do `apply --server-side` seguinte (provado num Deployment avulso no kind); a troca num cluster remoto não foi executada nesta fase.
- **Smoke e E2E.** O `smoke-servicos.sh` e o `make e2e` foram escritos para o kind: o E2E recusa contexto que não comece por `kind-`, e a prova de NetworkPolicy do smoke conta com o descarte de pacote do kindnet. Num cluster remoto, nenhum dos dois foi executado.
- **Plataforma.** O `deploy-remoto.sh` implanta um serviço; a plataforma entra pelo `make deploy` do passo 1 de [Para ligar](#para-ligar), da máquina do dono do ambiente.

> [↑ Raiz do projeto](../../README.md)
