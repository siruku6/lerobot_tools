#!/usr/bin/env bash
# データ層の入口。**版の受け渡しと env ファイルの束ね方を、ここ 1 箇所に閉じる。**
#
#   ./datactl.sh doctor       前提を調べる
#   ./datactl.sh tag          データイメージのタグを表示する
#   ./datactl.sh build-data   データイメージを焼く
#   ./datactl.sh build <用途>  用途イメージを焼く（eval / datagen / train）
#   ./datactl.sh up <用途>     用途コンテナに入る
#   ./datactl.sh mount-args   用途コンテナに渡すマウント引数を表示する
#
# 利用者が --env-file を 2 つ並べたり、タグを手で組み立てたりせずに済むように
# するためのもので、ここに処理そのものは書かない（step と Dockerfile が持つ）。
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
ROOT="$PWD"

VERSIONS="$ROOT/versions.env"

[ -f "$VERSIONS" ] || {
    echo "ERROR: versions.env がありません" >&2
    echo "       -> リポジトリの取得内容を確かめてください（versions.env はリポジトリにコミットされています）" >&2
    exit 1
}
set -a; . "$VERSIONS"; set +a

# タグは内容から決める。pin を変えれば別のタグになり、古い版も残る。
DATA_TAG="libero-data:${LIBERO_PLUS_REF:0:7}-${ASSETS_REV:0:7}"

case "${1:-}" in
tag)
    echo "$DATA_TAG"
    ;;

doctor)
    echo "=== 前提 ==="
    echo "docker:     $(docker --version 2>/dev/null || echo 'なし')"
    echo "compose:    $(docker compose version --short 2>/dev/null || echo 'なし')"
    # image mount には containerd スナップショッタが要る
    if docker info 2>/dev/null | grep -q 'io.containerd.snapshotter'; then
        echo "image マウント: 使える（containerd スナップショッタ）"
    else
        echo "image マウント: **使えない**（containerd イメージストアが無効）"
        echo "                -> /etc/docker/daemon.json に containerd-snapshotter を有効化するか、"
        echo "                   named volume へ注ぐ方式に切り替えてください"
    fi
    echo
    echo "=== データイメージ ==="
    if docker image inspect "$DATA_TAG" >/dev/null 2>&1; then
        docker images "${DATA_TAG%:*}" --format '  {{.Repository}}:{{.Tag}}  {{.Size}}'
    else
        echo "  $DATA_TAG は未ビルド  -> ./datactl build-data"
    fi
    echo
    echo "=== ディスク ==="
    df -h "$ROOT" | awk 'NR==2{print "  空き "$4" / "$2" ("$5" 使用)"}'
    ;;

build-data)
    echo "=== $DATA_TAG を焼く ==="
    docker build \
        -f "$ROOT/envs/data/Dockerfile" \
        -t "$DATA_TAG" \
        --build-arg LIBERO_PLUS_REF="$LIBERO_PLUS_REF" \
        --build-arg LIBERO_REF="$LIBERO_REF" \
        --build-arg ASSETS_REV="$ASSETS_REV" \
        --build-arg LIBERO_MOUNT="${LIBERO_MOUNT:-/opt/libero}" \
        "$ROOT"
    echo
    echo "=== 出来上がり ==="
    docker images "${DATA_TAG%:*}" --format '  {{.Repository}}:{{.Tag}}  {{.Size}}'
    echo
    echo "中間段（取得段）はもう要りません。回収するなら:"
    echo "  docker builder prune -f"
    ;;

build)
    # 用途イメージを焼く。データイメージは別（build-data）。
    PROFILE="${2:?用途を指定してください: eval / datagen / train}"
    # compose に渡すのはデータイメージのタグだけ。
    # パッケージの版は各環境の依存定義ファイルが持つので、ここを通らない。
    export LIBERO_DATA_TAG="$DATA_TAG"
    docker compose -f "$ROOT/envs/compose.yaml" --profile "$PROFILE" build "$PROFILE"
    ;;

up)
    PROFILE="${2:?用途を指定してください: eval / datagen / train}"
    shift 2 || true
    docker image inspect "$DATA_TAG" >/dev/null 2>&1 \
        || { echo "ERROR: $DATA_TAG がありません -> ./datactl build-data" >&2; exit 1; }
    # **先に作っておく。** compose に作らせると root 所有になり、
    # コンテナの中から書けてもホスト側で扱いにくくなる。
    mkdir -p "${DATA_DIR:-$ROOT/data}"
    # **タグの計算を利用者にさせない。** ここで環境へ渡す。
    LIBERO_DATA_TAG="$DATA_TAG" \
        docker compose -f "$ROOT/envs/compose.yaml" --profile "$PROFILE" \
        run --rm "$PROFILE" "$@"
    ;;

mount-args)
    # 用途コンテナへ渡す引数。docker run でも compose でも同じ形を指す。
    echo "--mount type=image,source=$DATA_TAG,target=${LIBERO_MOUNT:-/opt/libero},readonly,image-subpath=data"
    ;;

*)
    # 先頭のコメントブロック全体を使い方として出す。
    # 行数を決め打ちすると、コマンドを足したときにずれる。
    awk 'NR>1 && /^#/ {sub(/^# ?/, ""); print; next} NR>1 {exit}' "$0" 
    exit 1
    ;;
esac
