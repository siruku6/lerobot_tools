#!/usr/bin/env bash
# データ層の入口。**バージョンの受け渡しと env ファイルの束ね方を、ここ 1 箇所に閉じる。**
#
#   ./datactl.sh doctor       前提を調べる
#   ./datactl.sh tag          データイメージのタグを表示する
#   ./datactl.sh build-data   データイメージを焼く
#   ./datactl.sh build <用途>  用途イメージを焼く（eval / datagen / train）
#   ./datactl.sh up <用途>     用途コンテナに入る
#                              eval / datagen / train は bash に入る
#                              jupyter は datagen image で jupyter lab を立てる
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

# **マシンごとに違う設定と秘密情報は envs/.env が持つ。** wandb の API キー、
# jupyter のポートなどが入る。環境に関する情報なので、他の環境構築物と同じ
# envs/ の下に置いてある。リポジトリにはコミットしない（gitignore 済み。
# 書き方は envs/.env.example）。無くても動くので、あるときだけ読む。
#
# **compose も同じファイルを読む。** compose は自分のあるディレクトリ（envs/）の
# .env を変数展開に使うため、置き場所がここであることには両方にとって意味がある。
# ここで読むのは、compose を介さない doctor などでも同じ値を見せるためである。
if [ -f "$ROOT/envs/.env" ]; then
    set -a; . "$ROOT/envs/.env"; set +a
fi

# タグは内容から決める。pin を変えれば別のタグになり、古いバージョンも残る。
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
        echo "  $DATA_TAG は未ビルド  -> ./datactl.sh build-data"
    fi
    echo
    echo "=== wandb（学習の記録先） ==="
    if [ -n "${WANDB_API_KEY:-}" ]; then
        # **キーそのものは出さない。** 設定できているかだけを見せる。
        echo "  WANDB_API_KEY: 設定済み（${#WANDB_API_KEY} 文字）"
    else
        echo "  WANDB_API_KEY: 未設定  -> .env に書いてください（.env.example 参照）"
    fi
    echo "  WANDB_PROJECT: ${WANDB_PROJECT:-（未設定）}"
    echo "  WANDB_ENTITY:  ${WANDB_ENTITY:-（未設定。個人アカウントなら省略可）}"
    echo "  WANDB_MODE:    ${WANDB_MODE:-online（既定）}"
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
    PROFILE="${2:?用途を指定してください: eval / datagen / train / io}"
    # jupyter は専用の image を持たない。datagen image を別のコマンドで
    # 起動するだけのサービスなので、焼く対象が違う。
    case "$PROFILE" in
    jupyter)
        echo "ERROR: jupyter は datagen image を使います -> ./datactl.sh build datagen" >&2; exit 1 ;;
    esac
    # compose に渡すのはデータイメージのタグだけ。
    # パッケージのバージョンは各環境の依存定義ファイルが持つので、ここを通らない。
    export LIBERO_DATA_TAG="$DATA_TAG"
    docker compose -f "$ROOT/envs/compose.yaml" --profile "$PROFILE" build "$PROFILE"
    ;;

up)
    PROFILE="${2:?用途を指定してください: eval / datagen / train / io / jupyter}"
    shift 2 || true
    # train は LIBERO を使わないので、データイメージも要らない。
    case "$PROFILE" in
    train|io) ;;
    *)
        docker image inspect "$DATA_TAG" >/dev/null 2>&1 \
            || { echo "ERROR: $DATA_TAG がありません -> ./datactl.sh build-data" >&2; exit 1; }
        ;;
    esac
    # **先に作っておく。** compose に作らせると root 所有になり、
    # コンテナの中から書けてもホスト側で扱いにくくなる。
    mkdir -p "${DATA_DIR:-$ROOT/data}" "${OUTPUT_DIR:-$ROOT/outputs}"
    # **--service-ports を必ず渡す。** docker compose run は既定でポートを
    # 公開しないため、これが無いと jupyter の web UI に繋がらない
    # （コンテナは起動するので、原因が分かりにくい形で失敗する）。
    # ポートを持たないサービスには何の影響も無い。
    #
    # **タグの計算を利用者にさせない。** ここで環境へ渡す。
    # **コンテナをホストのユーザーで動かす。** root で動かすと、コンテナが
    # /outputs や HF キャッシュに書いたファイルがホスト側で root 所有になり、
    # sudo が無いと消せなくなる（実際にそれで学習の出力を消せなくなった）。
    export HOST_UID="$(id -u)" HOST_GID="$(id -g)" HOST_USER="$(id -un)"
    RUN_FLAGS=(--rm --service-ports)
    # **端末が無いときは TTY を要求しない。** ログへリダイレクトして流す場合や
    # 自動実行では標準入力が端末でないため、要求したままだと
    # 「the input device is not a TTY」で即座に落ちる。
    [ -t 0 ] || RUN_FLAGS+=(-T)
    LIBERO_DATA_TAG="$DATA_TAG" \
        docker compose -f "$ROOT/envs/compose.yaml" --profile "$PROFILE" \
        run "${RUN_FLAGS[@]}" "$PROFILE" "$@"
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
