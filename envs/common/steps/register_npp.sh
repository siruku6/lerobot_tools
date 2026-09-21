#!/usr/bin/env bash
# 入力: VENV（nvidia-npp-cu12 が入っている venv）
# 出力: /etc/ld.so.conf.d/nvidia-npp.conf
# 事後条件: ldconfig -p に libnppicc.so.12 が出る
#
# 必要な外部コマンド: ldconfig（root 権限）
#
# **なぜこれが要るのか。** torchcodec 0.11.x のコアは CUDA の NPP
# （画像・色空間変換）へ直接リンクしており、GPU デコードを使わない呼び出しでも
# import 時に読み込まれる。無いと libnppicc.so.12 が見つからず落ちる。
#
# **pip install するだけでは足りない。** torch が使う CUDA ライブラリは
# torch 自身が import 時に site-packages/nvidia/*/lib を明示的に preload する
# （固定リストに載っている）ため動的リンカが見つけられるが、**NPP はその
# リストに無い。** site-packages 配下に .so を置くだけでは探索先に入らないので、
# ldconfig にディレクトリを教える。
set -euo pipefail
_here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$_here/../lib/log.sh"

require_env VENV
step "NPP を動的リンカに登録"

if ldconfig -p 2>/dev/null | grep -q libnppicc; then
    skip "libnppicc は登録済み"
    exit 0
fi

SITE="$("$VENV/bin/python" -c 'import sysconfig;print(sysconfig.get_paths()["purelib"])')"
SO="$(find "$SITE/nvidia" -name 'libnppicc.so*' -print -quit 2>/dev/null || true)"
[ -n "$SO" ] || die "libnppicc.so が $SITE/nvidia に無い" \
    "pyproject に nvidia-npp-cu12 が入っているか確かめてください"

SONAME="$(basename "$SO")"      # 版は wheel が決める。決め打ちにしない
DIR="$(dirname "$SO")"
info "見つけた: $SO"
echo "$DIR" > /etc/ld.so.conf.d/nvidia-npp.conf
ldconfig

step "事後条件"
if ! ldconfig -p | grep -q "$SONAME"; then
    # **何が起きているかを出してから死ぬ。** ここは実機でしか分からない
    echo "--- 診断 ---" >&2
    echo "conf: $(cat /etc/ld.so.conf.d/nvidia-npp.conf)" >&2
    echo "ld.so.conf の include 行: $(grep -c include /etc/ld.so.conf 2>/dev/null || echo なし)" >&2
    echo "その dir の中身:" >&2; ls -l "$DIR" >&2
    echo "ldconfig -p の nppi 行:" >&2; ldconfig -p | grep -i nppi >&2 || echo "  （無し）" >&2
    echo "ldconfig -v での当該 dir:" >&2; ldconfig -v 2>/dev/null | grep -A3 "^$DIR" >&2 || true
    die "登録後も $SONAME が見えない" "上の診断を読んでください"
fi
ok "$DIR を登録（$SONAME）"
