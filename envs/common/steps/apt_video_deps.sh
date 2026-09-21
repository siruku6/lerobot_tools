#!/usr/bin/env bash
# 動画を**読む**処理と**書く**処理の両方に必要な FFmpeg を OS に install する script
#
# 入力: なし
# 出力: システムに FFmpeg 一式（共有ライブラリと ffmpeg コマンド）が入る
# 事後条件: libavutil が ldconfig から見え、かつ ffmpeg が H.264 を実際に符号化できる
#
# 必要な外部コマンド: apt-get（Debian / Ubuntu 系）
#
# 誰がこれを呼ぶか
# ------
#   datagen  LeRobot 形式データセットの動画を読み書きする
#   train    学習時にデータセットの動画を読む
#   io       評価で撮ったフレームを動画に固めて wandb へ送る
#
#
# 1. 読む側（torchcodec）が要求するもの
# ------
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
#
# 2. 書く側が要求するもの
# ------
# 評価のロールアウトを人が見るには、**ブラウザが再生できる形式**でなければならない。
# これは H.264 を意味する。**共有ライブラリが在ることは、符号化できることを保証しない。**
#
# 実測（eval image の opencv）:
#
#   mp4v  isOpened=True   size=188120
#   avc1  isOpened=False  Could not find encoder for codec_id=27, error: Encoder not found
#
# opencv 同梱の FFmpeg は mp4v（MPEG-4 Part 2）しか書けず、これは Chrome も
# Firefox も再生できない。**ファイルは出来るのに、プレイヤーが黙って真っ黒になる。**
# apt の ffmpeg は libx264 を持つので、この形で入れれば書ける。
#
#
# 3. なぜ事後条件で実際に符号化するのか
# ------
# 「`ffmpeg -encoders` の一覧に libx264 が出るか」では**代理の指標**にしかならない。
# NPP で同じ間違いをして、壊れた image を作った（ldconfig に名前が出ることだけを
# 見ていたため、torch と CUDA の系統が食い違ったまま build が完走した）。
# → docs/ADR/0001-torch-stack-pinning.md
#
# ここでの本当の要求は「H.264 の動画ファイルが出来ること」なので、
# **32x32 の動画を 1 本その場で符号化して、中身が在ることを確かめる。** 1 秒で終わる。
#
# なお、これは動画の読み書きに要る依存であり、シミュレーションの観測画像を
# 生成・加工する処理（apt_sim_deps.sh が担当）とは関係がない（そのためファイルを分けてある）。
set -euo pipefail
_here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$_here/../lib/log.sh"
. "$_here/../lib/guard.sh"

# torchcodec がつなぐ共有ライブラリが在るか
video_libs_present() {
    ldconfig_has libavutil
}

# ffmpeg が H.264 を**実際に**書けるか。一覧を見るのではなく、書いて確かめる。
#
# **`ffmpeg ... | grep` と書いてはいけない**（guard.sh の ldconfig_has を参照）。
# ここでは出力を捨てて終了状態とファイルの大きさだけを見るので、pipe を使わない。
h264_encodes() {
    command -v ffmpeg >/dev/null 2>&1 || return 1
    _probe="$(mktemp -d)/probe.mp4"
    ffmpeg -nostdin -loglevel error -y \
        -f lavfi -i color=c=black:s=32x32:d=0.2:r=10 \
        -c:v libx264 -pix_fmt yuv420p "$_probe" >/dev/null 2>&1 || { rm -rf "$(dirname "$_probe")"; return 1; }
    _size="$(wc -c < "$_probe" 2>/dev/null || echo 0)"
    rm -rf "$(dirname "$_probe")"
    [ "$_size" -gt 0 ]
}

step "FFmpeg（読み: torchcodec 用 / 書き: H.264 符号化用）"

# **両方を満たしているときだけ飛ばす。** 片方だけ在る状態で飛ばすと、
# 足りない側が実行時に初めて露見する。
if video_libs_present && h264_encodes; then
    skip "共有ライブラリと H.264 符号化はどちらも導入済み"
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

video_libs_present \
    || die "libavutil が見つからない" "apt のリポジトリ構成を確かめてください"

h264_encodes \
    || die "ffmpeg が H.264 を符号化できない" \
           "apt の ffmpeg は libx264 を含むはずです。最小構成の派生 image を使っている場合は" \
           "ffmpeg パッケージが別物に差し替わっていないか確かめてください"

ok "$(ldconfig -p | grep -oE 'libavutil\.so\.[0-9]+' | sort -u | tr '\n' ' ')/ H.264 符号化 OK"
