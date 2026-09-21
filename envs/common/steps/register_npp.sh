#!/usr/bin/env bash
# 動画のデコードに使う共有ライブラリの置き場所を、OS の動的リンカに教えるための script
# 具体的には torchcodec が要求する NPP（CUDA の画像・色空間変換ライブラリ）を登録する
#
# 入力: VENV（torchcodec と NPP の wheel が入っている venv の絶対パス）
# 出力: /etc/ld.so.conf.d/nvidia-npp.conf
# 事後条件: $VENV の python で torchcodec が import できる
#
# 必要な外部コマンド: ldconfig, ldd（ldconfig は root 権限が要る）
#
# **なぜこれが要るのか。** torchcodec 0.11.x のコアは NPP へ直接リンクしており、
# GPU デコードを使わない呼び出しでも import 時に読み込まれる。無いと落ちる。
#
# **pip install するだけでは足りない。** torch が使う CUDA ライブラリは
# torch 自身が import 時に site-packages/nvidia/*/lib を明示的に preload する
# （固定リストに載っている）ため動的リンカが見つけられるが、**NPP はその
# リストに無い。** site-packages 配下に .so を置くだけでは探索先に入らないので、
# ldconfig にディレクトリを教える。
#
# **事後条件を「ldconfig に libnppicc が出ているか」にしてはいけない。**
# それは代理の指標であって、本来の要求ではない。torchcodec は torch と同じ
# CUDA 系統で作られた torchcodec が要り、cu130 なら libnppicc.so.13、cu128 なら .so.12 を
# 要求する。系統違いの NPP が入っていると、登録自体は成功して
# 「libnppicc がある」と見えるのに torchcodec の import は落ちる。
# 実際にそれで壊れたイメージが出来た（docs/ADR/0001-torch-stack-pinning.md 参照）。
# そのためこの script は import そのものを検査する。
set -euo pipefail
_here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$_here/../lib/log.sh"

require_env VENV
step "NPP を動的リンカに登録"

PY="$VENV/bin/python"
[ -x "$PY" ] || die "$PY が無い" "VENV の指定が正しいか、venv が作られているか確かめてください"

# torchcodec が import できるか。これがこの step の目的そのものである
torchcodec_loads() {
    "$PY" -c 'import torchcodec.decoders' >/dev/null 2>&1
}

if torchcodec_loads; then
    skip "torchcodec は既に import できる"
    exit 0
fi

SITE="$("$PY" -c 'import sysconfig;print(sysconfig.get_paths()["purelib"])')"
[ -d "$SITE/torchcodec" ] || die "torchcodec が $SITE に入っていない" \
    "この step は torchcodec のためだけに在る。依存定義ファイルに torchcodec があるか確かめてください"

# **要求されるバージョンを決め打ちしない。** torchcodec のコアの ELF から読む。
# こうしておけば、torch の CUDA 系統を変えたときにこの script を直す必要がない。
NEED="$(ldd "$SITE"/torchcodec/libtorchcodec_core*.so 2>/dev/null \
        | grep -oE 'libnppicc\.so\.[0-9]+' | sort -u | head -1)"
[ -n "$NEED" ] || die "torchcodec のコアが要求する libnppicc を ELF から読めなかった" \
    "torchcodec のバージョンが変わって NPP に依存しなくなったのなら、この step は不要になります"
info "torchcodec が要求: $NEED"

SO="$(find "$SITE/nvidia" -name "$NEED" -print -quit 2>/dev/null || true)"
if [ -z "$SO" ]; then
    HAVE="$(find "$SITE/nvidia" -name 'libnppicc.so.*' -printf '%f ' 2>/dev/null || true)"
    die "torchcodec は $NEED を要求しているが、$SITE/nvidia にあるのは「${HAVE:-無し}」" \
        "NPP の CUDA 系統が torch と合っていません。依存定義ファイルに書く NPP の
       パッケージ名を、torch の系統に合わせてください。cu12 系なら nvidia-npp-cu12、
       cu13 系なら接尾辞の無い nvidia-npp です"
fi

DIR="$(dirname "$SO")"
info "見つけた: $SO"
echo "$DIR" > /etc/ld.so.conf.d/nvidia-npp.conf
ldconfig

step "事後条件"
if ! torchcodec_loads; then
    # **何が起きているかを出してから死ぬ。** ここは実機でしか分からない
    echo "--- 診断 ---" >&2
    echo "conf: $(cat /etc/ld.so.conf.d/nvidia-npp.conf)" >&2
    echo "その dir の中身:" >&2; ls -l "$DIR" >&2
    echo "ldconfig -p の nppi 行:" >&2; ldconfig -p | grep -i nppi >&2 || echo "  （無し）" >&2
    echo "torchcodec の import エラー:" >&2
    "$PY" -c 'import torchcodec.decoders' 2>&1 | tail -40 >&2 || true
    die "登録しても torchcodec が import できない" "上の診断を読んでください"
fi
ok "$DIR を登録（$NEED）。torchcodec が import できる"
