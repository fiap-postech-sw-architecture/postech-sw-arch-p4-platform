#!/usr/bin/env bash
# Implanta os servicos no kind, depois da plataforma (scripts/ci/deploy-kind.sh,
# que tambem gera os Secrets deles): o CD de cada servico chama este script
# com os tres repositorios, o proprio pela imagem do job image e os vizinhos
# construidos do codigo (README, "Contrato com os servicos").
#
#   scripts/ci/implantar-servicos.sh --overlay <overlay>
#     [--tar <servico>=<arquivo> --imagem <servico>=<ref>]... <servico>=<dir>...
#
# <servico> e os-service, billing-service ou execution-service, e <dir>, o
# checkout do repositorio dele. Sem --tar, a imagem pytstop-<servico> sai do
# docker build do <dir>, com o commit como tag (<commit>-sujo-<hash> se a
# arvore tem mudanca nao commitada) e GIT_SHA (os builds rodam em paralelo);
# com --tar, vem do arquivo do docker save, e --imagem e a ref que ele gravou.
# Cada imagem entra no kind por kind load. O overlay da execucao,
# <dir>/k8s/overlays/execucao, parte do <overlay> do servico e troca a imagem;
# o script o apaga no fim. Em cada namespace, na ordem: confere os Secrets da
# plataforma, apaga os Jobs de inicializacao (Job e imutavel), apply
# server-side, espera o banco (StatefulSet), o Job (log dele no erro) e cada
# Deployment. Os namespaces vao em paralelo, e a saida de cada um leva o nome
# do servico. Antes de tudo, cada servico so pode usar, alem da propria imagem,
# as imagens da tabela de versoes do README deste repositorio (banco, exporter,
# initContainers).
#
# Tudo o que pode pendurar roda com prazo, e o que passa dele reprova o servico
# em vez de consumir o timeout do job do CD (variaveis de ambiente, em segundos):
# PRAZO_BUILD (docker build, 900), PRAZO_CARGA (kind load, 300) e PRAZO_KUBECTL
# (cada chamada ao cluster, 120; nas esperas, somado ao tempo delas). As esperas
# de readiness: ESPERA_BANCO (180), ESPERA_JOB (300) e ESPERA_DEPLOYMENT (300).
set -euo pipefail

raiz=$(cd "$(dirname "$0")/../.." && pwd)
CLUSTER="${CLUSTER:-pytstop-p4}"
CONTEXTO="${KUBE_CONTEXT:-kind-$CLUSTER}"
PRAZO_BUILD="${PRAZO_BUILD:-900}"
PRAZO_CARGA="${PRAZO_CARGA:-300}"
# kubectl com prazo, a ordem de cada namespace e os prazos do cluster, comuns
# ao deploy-remoto.sh.
# shellcheck source=scripts/ci/implantacao.sh
. "$raiz/scripts/ci/implantacao.sh"

uso() {
  echo "usage: implantar-servicos.sh --overlay <overlay> [--tar <service>=<file> --imagem <service>=<ref>]... <service>=<dir>..." >&2
  exit 2
}

# motivo <status> <segundos>: por que o comando falhou.
motivo() {
  case "$1" in 124 | 142) echo "exceeded ${2}s" ;; *) echo "failed" ;; esac
}

# valor <servico> <par>...: o valor do par "<servico>=<valor>", vazio se nao ha.
valor() {
  local servico=$1 par
  shift
  for par in "$@"; do
    if [ "${par%%=*}" = "$servico" ]; then
      echo "${par#*=}"
      return
    fi
  done
}

overlay=""
tars=()
refs_dadas=()
pares=()
while [ "$#" -gt 0 ]; do
  case "$1" in
    --overlay | --tar | --imagem)
      [ "$#" -ge 2 ] || uso
      case "$1" in
        --overlay) overlay=$2 ;;
        --tar) tars+=("$2") ;;
        --imagem) refs_dadas+=("$2") ;;
      esac
      shift 2
      ;;
    -*) uso ;;
    *=*)
      pares+=("$1")
      shift
      ;;
    *) uso ;;
  esac
done
[ -n "$overlay" ] && [ "${#pares[@]}" -gt 0 ] || uso

TMP=$(mktemp -d "${TMPDIR:-/tmp}/implantar-servicos.XXXXXX")
gerados=()
limpa() {
  rm -rf "$TMP"
  local dir
  for dir in ${gerados[@]+"${gerados[@]}"}; do rm -rf "$dir"; done
}
trap limpa EXIT

# As imagens permitidas: as da tabela "Componentes e versoes" do README.
versoes=$("$raiz/scripts/ci/imagens-do-readme.sh")

# tag_de <dir> <commit>: a tag da imagem construida do checkout. Arvore limpa, o
# commit; com mudanca ou arquivo novo fora do .gitignore, <commit>-sujo-<12
# primeiros caracteres do hash da arvore de trabalho>, de modo que um segundo
# deploy local depois de editar o codigo muda a tag (e reinicia os Deployments),
# e o mesmo codigo sujo repete a tag. O hash sai de um indice temporario, sem
# mexer no indice do checkout. Quem chama a le dentro de um $( ) e de um ||, onde
# o set -e nao vale: cada comando que falha devolve o status com o return, ou a
# tag sairia do hash da arvore vazia, igual para qualquer codigo.
tag_de() {
  local estado indice arvore
  estado=$(git -C "$1" status --porcelain) || return
  if [ -z "$estado" ]; then
    echo "$2"
    return
  fi
  indice=$(mktemp -d "$TMP/indice.XXXXXX")
  GIT_INDEX_FILE="$indice/index" git -C "$1" add -A || return
  arvore=$(GIT_INDEX_FILE="$indice/index" git -C "$1" write-tree) || return
  echo "$2-sujo-${arvore:0:12}"
}

# Por servico, no mesmo indice: nome, namespace, diretorio, commit, tar, a tag
# da imagem construida e a ref da imagem.
nomes=()
nss=()
dirs=()
shas=()
tars_de=()
tags=()
refs=()
for par in "${pares[@]}"; do
  servico=${par%%=*}
  dir=${par#*=}
  ns=$(namespace "$servico") || { echo "unknown service $servico (os-service, billing-service or execution-service)" >&2; exit 2; }
  case " ${nomes[*]:-} " in *" $servico "*) echo "$servico given twice" >&2; exit 2 ;; esac
  sha=$(git -C "$dir" rev-parse HEAD 2>/dev/null) || { echo "$servico: $dir is not a git checkout" >&2; exit 1; }
  if [ ! -f "$dir/k8s/overlays/$overlay/kustomization.yaml" ]; then
    echo "$servico (commit $sha) has no k8s/overlays/$overlay/kustomization.yaml" >&2
    exit 1
  fi
  if [ -e "$dir/$EXECUCAO" ]; then
    echo "$servico (commit $sha): $EXECUCAO already exists; this script generates and deletes it" >&2
    exit 1
  fi
  manifests=$(kubectl kustomize "$dir/k8s/overlays/$overlay") \
    || { echo "$servico (commit $sha): kubectl kustomize k8s/overlays/$overlay failed" >&2; exit 1; }
  fora=$("$raiz/scripts/ci/imagens-dos-manifests.sh" <<< "$manifests" | sort -u \
    | while read -r imagem; do
      # O "(" antes do padrao: sem ele, o bash 3.2 do macOS fecha o $( no ")".
      case "$imagem" in ("pytstop-$servico" | "pytstop-$servico:"*) continue ;; esac
      grep -qxF "$imagem" <<< "$versoes" || echo "$imagem"
    done)
  if [ -n "$fora" ]; then
    echo "$servico (commit $sha): images outside the versions table of the platform README: $(tr '\n' ' ' <<< "$fora" | sed 's/ *$//')" >&2
    exit 1
  fi
  tar=$(valor "$servico" ${tars[@]+"${tars[@]}"})
  ref=$(valor "$servico" ${refs_dadas[@]+"${refs_dadas[@]}"})
  if [ -n "$tar$ref" ]; then
    # --tar e --imagem vao juntos: a ref e a que o docker save gravou no
    # arquivo, <nome>:<tag>, com a tag depois da ultima barra (o registry
    # pode ter porta).
    if [ -z "$tar" ] || [ -z "$ref" ]; then
      echo "$servico: --tar and --imagem go together" >&2
      exit 2
    fi
    [ -f "$tar" ] || { echo "$servico: $tar not found" >&2; exit 1; }
    if [[ "$ref" == *@* || ! "$ref" =~ :[^:/]+$ ]]; then
      echo "$servico: --imagem needs <name>:<tag>, got $ref" >&2
      exit 2
    fi
    # O kind load carrega a ref que o docker save gravou no arquivo; com outra
    # em --imagem, o Deployment tentaria puxar do registry e o erro viria como
    # timeout do rollout, minutos depois.
    gravadas=$(tar -xOf "$tar" manifest.json index.json 2>/dev/null || true)
    grep -qF "\"$ref\"" <<< "$gravadas" \
      || { echo "$servico (commit $sha): $tar does not hold the image $ref (--imagem must be the ref docker save wrote)" >&2; exit 1; }
    tag=""
  else
    tag=$(tag_de "$dir" "$sha") || { echo "$servico (commit $sha): could not hash the working tree of $dir" >&2; exit 1; }
    [ "$tag" = "$sha" ] || echo "$servico (commit $sha): uncommitted changes in $dir; image tag $tag" >&2
    ref="pytstop-$servico:$tag"
  fi
  nomes+=("$servico")
  nss+=("$ns")
  dirs+=("$dir")
  shas+=("$sha")
  tars_de+=("$tar")
  tags+=("$tag")
  refs+=("$ref")
done
for par in ${tars[@]+"${tars[@]}"} ${refs_dadas[@]+"${refs_dadas[@]}"}; do
  case " ${nomes[*]} " in *" ${par%%=*} "*) ;; *) echo "${par%%=*}: --tar or --imagem for a service that is not being deployed" >&2; exit 2 ;; esac
done
n=${#nomes[@]}

# Builds em paralelo, cada um com o proprio log; o log de quem falha vai para
# a saida.
pids=()
for ((i = 0; i < n; i++)); do
  [ -z "${tars_de[i]}" ] || continue
  echo "${nomes[i]}: docker build of ${refs[i]} from ${dirs[i]}"
  prazo "$PRAZO_BUILD" docker build --build-arg GIT_SHA="${tags[i]}" --build-arg GIT_DATE="$(git -C "${dirs[i]}" log -1 --format=%cI)" \
    -t "${refs[i]}" "${dirs[i]}" > "$TMP/build-$i.log" 2>&1 &
  pids[i]=$!
done
falharam=""
for ((i = 0; i < n; i++)); do
  [ -n "${pids[i]:-}" ] || continue
  status=0
  wait "${pids[i]}" || status=$?
  if [ "$status" != 0 ]; then
    tail -n 50 "$TMP/build-$i.log" >&2
    echo "${nomes[i]} (commit ${shas[i]}): docker build of ${refs[i]} $(motivo "$status" "$PRAZO_BUILD")" >&2
    falharam+=" ${nomes[i]} (commit ${shas[i]})"
  fi
done
[ -z "$falharam" ] || { echo "docker build failed:$falharam" >&2; exit 1; }

for ((i = 0; i < n; i++)); do
  status=0
  if [ -n "${tars_de[i]}" ]; then
    prazo "$PRAZO_CARGA" kind load image-archive "${tars_de[i]}" --name "$CLUSTER" || status=$?
  else
    prazo "$PRAZO_CARGA" kind load docker-image "${refs[i]}" --name "$CLUSTER" || status=$?
  fi
  if [ "$status" != 0 ]; then
    echo "${nomes[i]} (commit ${shas[i]}): kind load of ${refs[i]} $(motivo "$status" "$PRAZO_CARGA")" >&2
    exit 1
  fi
  mkdir "${dirs[i]}/$EXECUCAO"
  gerados+=("${dirs[i]}/$EXECUCAO")
  # Aspas na tag: um commit so de digitos viraria numero no YAML.
  cat > "${dirs[i]}/$EXECUCAO/kustomization.yaml" <<YAML
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ../$overlay
images:
  - name: pytstop-${nomes[i]}
    newName: ${refs[i]%:*}
    newTag: "${refs[i]##*:}"
YAML
  echo "${nomes[i]}: $EXECUCAO = $overlay with image ${refs[i]}"
done

# prefixa <servico>: cada linha da entrada com o nome do servico na frente.
prefixa() {
  local linha
  while IFS= read -r linha; do printf '[%s] %s\n' "$1" "$linha"; done
}

pids=()
for ((i = 0; i < n; i++)); do
  # Com o pipefail, o wait do pipeline devolve o status do implanta.
  implanta "${nss[i]}" "${dirs[i]}/$EXECUCAO" 2>&1 | prefixa "${nomes[i]}" &
  pids[i]=$!
done
falharam=""
for ((i = 0; i < n; i++)); do
  wait "${pids[i]}" || falharam+=" ${nomes[i]} (commit ${shas[i]})"
done
if [ -n "$falharam" ]; then
  echo "deploy failed:$falharam" >&2
  exit 1
fi
echo "deployed: ${nomes[*]}"
