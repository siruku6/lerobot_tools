#!/usr/bin/env bash
# シミュレーションの観測画像を生成・加工する処理に必要な共有ライブラリをOSに install するための script
# 各共有ライブラリは mujoco/robosuiteの描画、LIBERO-plusのモーションブラー処理で用いる
#
# 入力: なし（APT_EXTRA で足せる）
# 出力: システムに共有ライブラリが入る
# 事後条件: libMagickWand が ldconfig から見える
#
# 必要な外部コマンド: apt-get（Debian / Ubuntu 系）
#
# pip では入らない、共有ライブラリの実体だけをここで入れる。何のために要るかは次の2つ。
#
#   - libmagickwand-dev: LIBERO-plus の摂動評価が使う「モーションブラー」処理に要る。
#     LIBERO-plus の envs/env_wrapper.py が `wand`（ImageMagick への ctypes
#     バインディング）経由で ImageMagick の MagickMotionBlurImage を直接呼んでいる。
#     `wand` 自体は pip で入るが、その実体である ImageMagick の共有ライブラリは
#     pip では入らない。
#
#   - libgl1 / libegl1 / libglib2.0-0 ほかの GL 系:
#     mujoco / robosuite がシミュレーションの観測画像（カメラ映像）を描画するために
#     使う OpenGL 関連ライブラリ。mujoco はどの描画バックエンド（EGL / OSMesa / GLFW
#     など）を使うかを実行時に **dlopen で決める**ため、コードを読むだけ（import の
#     静的解析）では、どのライブラリが実際に必要かが分からない。
#
# **GL 系は全部入れる。絞り込まないと決めた**（利用者の判断。2026-09-21）。
# 顔ぶれは移行元（PARC2026_pre / b_PARC2026_final の setup.sh）から丸ごと引き継いで
# おり、1 つずつ外して確かめる作業はしていない。この image の目的が採点環境との
# 一致であるため、採点側に在るものを落とすと「ローカルで通って本番で落ちる」向きの
# 食い違いを作るからである。
set -euo pipefail
_here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$_here/../lib/log.sh"
. "$_here/../lib/guard.sh"

step "シミュレータ用のシステム依存"

if ldconfig_has libMagickWand; then
    skip "libMagickWand は導入済み"
    exit 0
fi

SUDO=""
if [ "$(id -u)" != 0 ]; then
    command -v sudo >/dev/null 2>&1 || die "root でなく sudo も無い" \
        "root で流し直すか、Dockerfile のビルド時に実行してください"
    SUDO="sudo"
fi

$SUDO apt-get update -qq
# shellcheck disable=SC2086
$SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends \
    `# LIBERO-plus のモーションブラー処理（上の説明参照）に要る。` \
    libmagickwand-dev \
    `# mujoco / robosuite の描画（GL 系）に要る。` \
    libgl1 libegl1 libglib2.0-0 \
    libosmesa6 libosmesa6-dev `# MUJOCO_GL=osmesa を選んだ場合の描画バックエンド` \
    libglfw3 libglew-dev      `# GLFW バックエンドと GL 拡張の解決` \
    libsm6 libxext6 libxrender1 `# X11 系。headless でない opencv が入った場合の保険` \
    ${APT_EXTRA:-}
$SUDO rm -rf /var/lib/apt/lists/*

step "事後条件"
ldconfig_has libMagickWand \
    || die "libMagickWand が見つからない" "apt のリポジトリ構成を確かめてください"
ok "$(ldconfig -p | grep -c . ) 個の共有ライブラリが登録済み"
