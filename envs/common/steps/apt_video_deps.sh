#!/usr/bin/env bash
# 入力: なし
# 出力: システムに FFmpeg の共有ライブラリが入る
# 事後条件: libavutil が ldconfig から見える
#
# 必要な外部コマンド: apt-get（Debian / Ubuntu 系）
#
# **torchcodec は FFmpeg の共有ライブラリに dlopen で繋ぐ。**
# pip の torchcodec には .so が同梱されておらず、システム側の libavutil /
# libavcodec / libavformat が要る。無いと import の時点で落ちる:
#
#   OSError: libavutil.so.59: cannot open shared object file
#
# torchcodec は FFmpeg 4〜7 のどれかを順に探すので、版は合わせなくてよい。
# apt の ffmpeg を入れれば、その土台に合った版が入る。
#
# **lerobot 側の依存であり、LIBERO 側とは関係がない**（apt_sim_deps.sh と分けてある）。
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
