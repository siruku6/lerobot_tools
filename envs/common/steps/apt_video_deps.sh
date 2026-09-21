#!/usr/bin/env bash
# LeRobot形式データセットの動画（カメラ画像）をデコードする処理に必要な、
# FFmpeg の共有ライブラリを OS に install する script
#
# 入力: なし
# 出力: システムに FFmpeg の共有ライブラリが入る
# 事後条件: libavutil が ldconfig から見える
#
# 必要な外部コマンド: apt-get（Debian / Ubuntu 系）
#
# LeRobot 形式のデータセットは、カメラ画像をエピソードごとに動画（mp4）として
# 圧縮して保存する（生の画像のまま保存すると容量が大きすぎるため）。
# 学習・推論時に特定フレームの画像がそのまま必要になるので、lerobot は torchcodec という
# 動画デコーダを使い、指定したフレームだけを圧縮データから生のピクセル値に復元する。
#
# **torchcodec は FFmpeg の共有ライブラリに dlopen で直接つなぐ**（pip パッケージの
# 中には .so を同梱していない）。ここから次の 2 点が導かれる。
#
#   1. システム側に libavutil / libavcodec / libavformat が無いと、
#      import の時点で落ちる（実際に起きるエラー）:
#
#        OSError: libavutil.so.59: cannot open shared object file
#
#   2. torchcodec は FFmpeg 4〜7 のどれかを順に探して見つかったものにつなぐため、
#      入れる FFmpeg のバージョンを厳密に合わせる必要はない。apt の ffmpeg を
#      入れれば、その土台に合ったバージョンが自動的に入る。
#
# なお、これは LeRobot 形式データセットの動画デコードに要る依存であり、
# シミュレーションの観測画像を生成・加工する処理（apt_sim_deps.sh が担当）とは
# 関係がない（そのためファイルを分けてある）。
set -euo pipefail
_here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$_here/../lib/log.sh"

step "FFmpeg の共有ライブラリ（torchcodec 用）"

if ldconfig -p 2>/dev/null | grep -q libavutil; then
    skip "libavutil は導入済み"
    exit 0
fi

SUDO=""
if [ "$(id -u)" != 0 ]; then
    command -v sudo >/dev/null 2>&1 || die "root でなく sudo も無い" \
        "root で流し直すか、Dockerfile のビルド時に実行してください"
    SUDO="sudo"
fi

$SUDO apt-get update -qq
$SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends ffmpeg
$SUDO rm -rf /var/lib/apt/lists/*

step "事後条件"
ldconfig -p 2>/dev/null | grep -q libavutil \
    || die "libavutil が見つからない" "apt のリポジトリ構成を確かめてください"
ok "$(ldconfig -p | grep -oE 'libavutil\.so\.[0-9]+' | sort -u | tr '\n' ' ')"
