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
# docker build do <dir>, com o commit como tag e GIT_SHA (os builds rodam em
# paralelo); com --tar, vem do arquivo do docker save, com a ref de --imagem.
# Cada imagem entra no kind por kind load. O overlay da execucao,
# <dir>/k8s/overlays/execucao, parte do <overlay> do servico e troca a imagem;
# o script o apaga no fim. Em cada namespace, na ordem: apaga os Jobs de
# inicializacao (Job e imutavel), apply server-side, espera o banco
# (StatefulSet), o Job (log dele no erro) e cada Deployment. Os namespaces
# vao em paralelo, e a saida de cada um leva o nome do servico. Antes de
# tudo, cada servico so pode usar, alem da propria imagem, as imagens da tabela
# de versoes do README deste repositorio (banco, exporter, initContainers).
set -euo pipefail

raiz=$(cd "$(dirname "$0")/../.." && pwd)
CLUSTER="${CLUSTER:-pytstop-p4}"
K="kubectl --context ${KUBE_CONTEXT:-kind-$CLUSTER}"
INICIALIZACAO=app.kubernetes.io/component=inicializacao
# Gerado dentro do repositorio do servico: o kustomize so le resources por
# caminho relativo.
EXECUCAO=k8s/overlays/execucao

uso() {
  echo "usage: implantar-servicos.sh --overlay <overlay> [--tar <service>=<file> --imagem <service>=<ref>]... <service>=<dir>..." >&2
  exit 2
}

# namespace <servico>
namespace() {
  case "$1" in
    os-service) echo pytstop-os ;;
    billing-service) echo pytstop-billing ;;
    execution-service) echo pytstop-execucao ;;
    *) return 1 ;;
  esac
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

# As imagens permitidas: a coluna "Versao" da tabela "Componentes e versoes" do
# README. So ela vale, porque o resto do README cita entre crases nomes que nao
# sao imagem, como o papel `postgres` do banco.
versoes=$(awk -F'|' '/^[|] Componente [|] Vers/ { t = 1 } t && !/^[|]/ { t = 0 } t { print $3 }' "$raiz/README.md")

# Por servico, no mesmo indice: nome, namespace, diretorio, commit, tar e a
# ref da imagem.
nomes=()
nss=()
dirs=()
shas=()
tars_de=()
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
  fora=$(sed -n 's/^ *image: *"\{0,1\}\([^" ]*\)"\{0,1\} *$/\1/p' <<< "$manifests" | sort -u \
    | while read -r imagem; do
      # O "(" antes do padrao: sem ele, o bash 3.2 do macOS fecha o $( no ")".
      case "$imagem" in ("pytstop-$servico" | "pytstop-$servico:"*) continue ;; esac
      grep -qF "\`$imagem\`" <<< "$versoes" || echo "$imagem"
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
  else
    ref="pytstop-$servico:$sha"
  fi
  nomes+=("$servico")
  nss+=("$ns")
  dirs+=("$dir")
  shas+=("$sha")
  tars_de+=("$tar")
  refs+=("$ref")
done
for par in ${tars[@]+"${tars[@]}"} ${refs_dadas[@]+"${refs_dadas[@]}"}; do
  case " ${nomes[*]} " in *" ${par%%=*} "*) ;; *) echo "${par%%=*}: --tar or --imagem for a service that is not being deployed" >&2; exit 2 ;; esac
done
n=${#nomes[@]}

TMP=$(mktemp -d)
gerados=()
limpa() {
  rm -rf "$TMP"
  local dir
  for dir in ${gerados[@]+"${gerados[@]}"}; do rm -rf "$dir"; done
}
trap limpa EXIT

# Builds em paralelo, cada um com o proprio log; o log de quem falha vai para
# a saida.
pids=()
for ((i = 0; i < n; i++)); do
  [ -z "${tars_de[i]}" ] || continue
  echo "${nomes[i]}: docker build of ${refs[i]} from ${dirs[i]}"
  docker build --build-arg GIT_SHA="${shas[i]}" --build-arg GIT_DATE="$(git -C "${dirs[i]}" log -1 --format=%cI)" \
    -t "${refs[i]}" "${dirs[i]}" > "$TMP/build-$i.log" 2>&1 &
  pids[i]=$!
done
falharam=""
for ((i = 0; i < n; i++)); do
  [ -n "${pids[i]:-}" ] || continue
  if ! wait "${pids[i]}"; then
    tail -n 50 "$TMP/build-$i.log" >&2
    falharam+=" ${nomes[i]} (commit ${shas[i]})"
  fi
done
[ -z "$falharam" ] || { echo "docker build failed:$falharam" >&2; exit 1; }

for ((i = 0; i < n; i++)); do
  if [ -n "${tars_de[i]}" ]; then
    kind load image-archive "${tars_de[i]}" --name "$CLUSTER"
  else
    kind load docker-image "${refs[i]}" --name "$CLUSTER"
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

# implanta <namespace> <dir do overlay>: a ordem do namespace. Cada lista vem
# antes do laco: erro do cluster dentro do $( ) do for passaria calado.
implanta() {
  local ns=$1 recurso recursos jobs
  $K -n "$ns" delete job -l "$INICIALIZACAO" --ignore-not-found --timeout=60s || return
  $K apply --server-side -k "$2" || return
  recursos=$($K -n "$ns" get statefulset -o name) || return
  for recurso in $recursos; do
    $K -n "$ns" rollout status "$recurso" --timeout=180s || return
  done
  jobs=$($K -n "$ns" get job -l "$INICIALIZACAO" -o name) || return
  if [ -z "$jobs" ]; then
    echo "no Job labeled $INICIALIZACAO in $ns" >&2
    return 1
  fi
  for recurso in $jobs; do
    if ! $K -n "$ns" wait --for=condition=Complete "$recurso" --timeout=300s; then
      $K -n "$ns" logs "$recurso" --all-containers --tail=50 >&2 || true
      return 1
    fi
  done
  recursos=$($K -n "$ns" get deployment -o name) || return
  for recurso in $recursos; do
    $K -n "$ns" rollout status "$recurso" --timeout=300s || return
  done
}

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
