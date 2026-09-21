#!/usr/bin/env bash
# 評価用の venv を作る
#
# Usage
# ------
#   VENV=/opt/venv REQ=/opt/env/requirements.txt bash venv.sh
#
# 入力: VENV, REQ    省略可: EVAL_PY（既定 python3.10）
# 出力: $VENV
# 事後条件: requirements.txt が == で固定した版が、そのとおり入っている。
#           CUDA 12 系と 13 系の nvidia wheel が同居していない
#
# 必要な外部コマンド: python3.10（または EVAL_PY で指定したもの）
#
#
# なぜ uv ではなく pip なのか
# ------
# このイメージの目的は、採点環境と同じ手順を再現することである。
# 採点環境は pip の requirements.txt で入れているので、こちらも同じにする。
# uv に置き換えると速くなるが、再現しているものが別物になる。
#
#
# なぜ版をこの step に書かないのか
# ------
# 版は requirements.txt が持つ。以前は versions.env から渡していたが、
# 同じ値が 2 箇所にあると、片方だけ直して気付かない。
# この step は「requirements.txt のとおりに入れて、入ったか確かめる」だけを行う。
#
#
# なぜ CUDA 12 系と 13 系の同居を検出するのか
# ------
# cu12 と cu13 の wheel は同じパス（site-packages/nvidia/*/lib）へ展開される。
# 両方入ると後から入れたほうが cuDNN を上書きし、torch が読む cuDNN が
# 想定と違う版に化ける。pip はこれを不整合として扱わないため、
# インストールは成功して、GPU 推論だけが壊れる。
set -euo pipefail
_here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$_here/../lib/log.sh"

require_env VENV REQ
PY="${EVAL_PY:-python3.10}"
[ -f "$REQ" ] || die "$REQ が無い" "REQ の指す先を確かめてください"

step "評価用 venv（$VENV / $PY）"

if [ -x "$VENV/bin/python" ] && "$VENV/bin/python" -c "pass" 2>/dev/null; then
    skip "$VENV は既にある"
else
    command -v "$PY" >/dev/null 2>&1 \
        || die "$PY が無い" "ベースイメージに python3.10 を入れてください"
    "$PY" -m venv "$VENV"
fi

PIP="$VENV/bin/pip"
# --no-cache-dir を必ず付ける。付け忘れると pip の HTTP キャッシュが
# レイヤーに残る（移行元のイメージでは 3.1GB が焼き込まれていた）。
$PIP install --no-cache-dir -q --upgrade pip setuptools wheel

# **1 回の pip で入れる。** 分けて実行すると、後の解決は前の固定を知らないため、
# numpy 2 を要求する版の scikit-image などを選んで numpy を上書きしてしまう
# （2026-09-20 に実測。numpy が 1.26.4 から 2.2.6 に上がった）。
info "requirements.txt を 1 回の解決で入れる"
$PIP install --no-cache-dir -q --timeout 120 --retries 10 -r "$REQ"

step "事後条件"
"$VENV/bin/python" - "$REQ" <<'ZZCHECK'
import sys, re
import importlib.metadata as md

pins = {}
for line in open(sys.argv[1], encoding="utf-8"):
    line = line.split("#")[0].strip()
    if not line or line.startswith("-"):
        continue
    m = re.match(r"^([A-Za-z0-9._-]+)\s*(?:\[[^\]]*\])?\s*==\s*([^\s;,]+)", line)
    if m:
        pins[m.group(1).lower().replace("_", "-")] = m.group(2)

bad = []
for name, want in sorted(pins.items()):
    try:
        got = md.version(name)
    except md.PackageNotFoundError:
        bad.append(f"{name}: 入っていない（{want} のはず）")
        continue
    if got != want and not got.startswith(want.split("+")[0]):
        bad.append(f"{name}: {got}（{want} のはず）")

import numpy, torch
print(f"    numpy {numpy.__version__} / torch {torch.__version__}"
      f" / cudnn {torch.backends.cudnn.version()}")
print(f"    == で固定された {len(pins)} 件を照合した")

names = {d.metadata["Name"].lower() for d in md.distributions()}
cu12 = {n for n in names if n.startswith("nvidia-") and n.endswith("-cu12")}
cu13 = {n for n in names if n.startswith("nvidia-") and n.endswith("-cu13")}
if cu12 and cu13:
    bad.append(f"CUDA 12 系と 13 系の nvidia wheel が同居している"
               f"（cu12: {sorted(cu12)[:3]} / cu13: {sorted(cu13)[:3]}）。"
               " cuDNN が上書きされ GPU 推論が壊れます")

if bad:
    sys.exit("[venv] ERROR: 宣言と違う\n  " + "\n  ".join(bad))
ZZCHECK
ok "$VENV"
