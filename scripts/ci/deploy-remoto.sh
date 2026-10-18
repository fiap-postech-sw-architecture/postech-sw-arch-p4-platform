#!/usr/bin/env bash
# Deploy de um servico num cluster persistente: o gancho opcional e desligado
# do CD (job deploy-remote, ADR-042; receitas e como ligar em
# docs/operacao/nuvem-opcional.md). Neutro de provedor: nao guarda credencial
# nem chama nuvem; usa o contexto que o kubeconfig de quem roda ja tem. Roda a
# partir do checkout do servico:
#
#   deploy-remoto.sh --contexto <contexto> --overlay <overlay> \
#     --servico <servico> --imagem <ref>@sha256:<digest>
#
# <servico> e os-service, billing-service ou execution-service, e a imagem, a
# pytstop-<servico> de um registry, com ou sem tag antes do digest (o job image
# do CD passa <ref>:<commit>@sha256:<digest>). Gera k8s/overlays/execucao, o
# <overlay> do servico com a imagem fixada pelo digest (a tag sai), implanta no
# namespace do servico na ordem do implantar-servicos.sh (Secrets da
# plataforma, Jobs de inicializacao apagados, apply server-side, banco, Job e
# cada Deployment, tudo com prazo) e apaga o overlay gerado no fim. A
# plataforma ja tem de estar no cluster: o make deploy dela cria o namespace e
# os Secrets. Os prazos sao os do implantar-servicos.sh (PRAZO_KUBECTL,
# ESPERA_BANCO, ESPERA_JOB e ESPERA_DEPLOYMENT, em scripts/ci/implantacao.sh).
set -euo pipefail

raiz=$(cd "$(dirname "$0")/../.." && pwd)
# shellcheck source=scripts/ci/implantacao.sh
. "$raiz/scripts/ci/implantacao.sh"

uso() {
  echo "usage: deploy-remoto.sh --contexto <context> --overlay <overlay> --servico <service> --imagem <ref>@sha256:<digest>" >&2
  exit 2
}

contexto="" overlay="" servico="" imagem="" vistos=" "
while [ "$#" -gt 0 ]; do
  case "$1" in
    --contexto | --overlay | --servico | --imagem)
      [ "$#" -ge 2 ] || uso
      case "$vistos" in *" $1 "*) echo "$1 given twice" >&2; exit 2 ;; esac
      vistos+="$1 "
      # Vazio nao vale: com --context "" o kubectl usaria o contexto atual do
      # kubeconfig, qualquer que fosse o cluster.
      [ -n "$2" ] || { echo "$1 is empty" >&2; exit 2; }
      case "$1" in
        --contexto) contexto=$2 ;;
        --overlay) overlay=$2 ;;
        --servico) servico=$2 ;;
        --imagem) imagem=$2 ;;
      esac
      shift 2
      ;;
    *) uso ;;
  esac
done
[ -n "$contexto" ] && [ -n "$overlay" ] && [ -n "$servico" ] && [ -n "$imagem" ] || uso
CONTEXTO=$contexto

ns=$(namespace "$servico") || { echo "unknown service $servico (os-service, billing-service or execution-service)" >&2; exit 2; }
# O overlay vai para o YAML e para o caminho do overlay gerado: so um nome de
# diretorio, sem "#", quebra de linha ou "..", que mudariam o YAML ou sairiam
# de k8s/overlays.
[[ "$overlay" =~ ^[A-Za-z0-9][A-Za-z0-9_-]*$ ]] || { echo "--overlay needs a plain overlay name (letters, digits, _ and -), got $overlay" >&2; exit 2; }
# So os caracteres de uma referencia de imagem: o nome vai para o YAML do
# overlay gerado.
padrao='^([A-Za-z0-9._/:-]+)@(sha256:[0-9a-f]{64})$'
[[ "$imagem" =~ $padrao ]] || { echo "--imagem needs <ref>@sha256:<64 lowercase hex digits>, got $imagem" >&2; exit 2; }
nome=${BASH_REMATCH[1]}
digest=${BASH_REMATCH[2]}
# A tag, se veio, e o que esta depois do ultimo ":" fora do host (o registry
# pode ter porta).
if [[ "$nome" =~ :[^:/]+$ ]]; then nome=${nome%:*}; fi
case "$nome" in
  "pytstop-$servico" | */"pytstop-$servico") ;;
  *) echo "--imagem $imagem is not an image of $servico (pytstop-$servico)" >&2; exit 2 ;;
esac

if [ ! -f "k8s/overlays/$overlay/kustomization.yaml" ]; then
  echo "$servico: no k8s/overlays/$overlay/kustomization.yaml in $PWD (run from the checkout of $servico)" >&2
  exit 1
fi
if [ -e "$EXECUCAO" ]; then
  echo "$servico: $EXECUCAO already exists in $PWD; this script generates and deletes it" >&2
  exit 1
fi
mkdir "$EXECUCAO"
trap 'rm -rf "$EXECUCAO"' EXIT
cat > "$EXECUCAO/kustomization.yaml" <<YAML
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ../$overlay
images:
  - name: pytstop-$servico
    newName: $nome
    digest: $digest
YAML
echo "$servico: $EXECUCAO = $overlay with image $nome@$digest"
# Antes de tocar no cluster, o overlay tem de renderizar com a imagem trocada:
# no checkout de outro repositorio (o do platform tambem tem um overlay k3s), a
# troca nao casa nada, e o apply implantaria os manifests dele.
renderizado=$(prazo "$PRAZO_KUBECTL" kubectl kustomize "$EXECUCAO") \
  || { echo "$servico: kubectl kustomize $EXECUCAO failed or exceeded ${PRAZO_KUBECTL}s" >&2; exit 1; }
grep -qF "image: $nome@$digest" <<< "$renderizado" \
  || { echo "$servico: k8s/overlays/$overlay in $PWD does not use the image pytstop-$servico (run from the checkout of $servico)" >&2; exit 1; }

if ! implanta "$ns" "$PWD/$EXECUCAO"; then
  echo "deploy failed: $servico ($nome@$digest) in context $contexto" >&2
  exit 1
fi
echo "deployed: $servico ($nome@$digest) in context $contexto"
