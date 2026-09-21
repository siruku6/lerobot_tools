#!/usr/bin/env bash
# uv で venv を作り、pyproject.toml のとおりに入れる
#
# Usage
# ------
#   # 1 段目（土台）
#   ENV_DIR=/opt/env/base VENV=/opt/venv UV_PY=3.12 bash venv_uv.sh
#
#   # 2 段目（残り）
#   ENV_DIR=/opt/env VENV=/opt/venv bash venv_uv.sh
#
# 入力: ENV_DIR, VENV
#       省略可: UV_PY（既定 3.12）, UV_EXTRA, CLEAN_UV_CACHE
# 出力: $VENV
# 事後条件: $VENV/bin/python と $VENV/bin/pip が在り、
#           pyproject.toml が == で固定したバージョンがそのとおり入っている
#
# 必要な外部コマンド: uv
#
#
# なぜ uv sync ではなく uv pip install なのか
# ------
# **uv sync は manifest に無いものを消す。** 2 段に分けて入れると、
# 2 回目の sync が 1 回目に入れた torch を消してしまう（2026-09-21 に実測）。
# uv pip install は消さないので、積み重ねられる。
#
#
# なぜ 2 段に分けられるのか
# ------
# uv は「入っているバージョンが要求を満たしていれば手を出さない」（2026-09-21 に実測）。
# そのため 1 段目で入れた torch は、2 段目の解決では触られない。
#
# それでも 2 段目の pyproject.toml に同じ固定を書いてあるのは、将来
# 要求が変わったときに**黙って入れ替わるのではなく衝突で止める**ためである。
#
#
# **どの環境を作るかは入力で決まる。** この step 自体は「uv で venv を作る」
# 以上のことを知らない。datagen 用か train 用かは ENV_DIR が決める。
set -euo pipefail
_here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$_here/../lib/log.sh"

require_env ENV_DIR VENV
PY="${UV_PY:-3.12}"
PROJ="$ENV_DIR/pyproject.toml"
[ -f "$PROJ" ] || die "$PROJ が無い" "ENV_DIR の指す先を確かめてください"
command -v uv >/dev/null 2>&1 || die "uv が無い" "イメージに uv を入れてください"

step "venv（$VENV / python $PY）← $PROJ"

if [ -x "$VENV/bin/python" ] && "$VENV/bin/python" -c "pass" 2>/dev/null; then
    skip "$VENV は既にある"
else
    # **--seed を付ける。** uv が作る venv には既定で pip が入らない
    # （uv は venv の外から操作する道具なので、中に pip を置かない）。
    # 入っていないと `pip install X` が PATH 上のベース側の pip に解決され、
    # **誰も読まない場所へ静かに入る。** エラーにならないので気付けない。
    uv venv "$VENV" --python "$PY" --seed
fi

# **nvidia 系の wheel は取得に時間がかかる。** 既定の待ち時間だと落ちる。
export UV_HTTP_TIMEOUT="${UV_HTTP_TIMEOUT:-300}"

ARGS=(uv pip install --python "$VENV/bin/python" -r "$PROJ")
[ -n "${UV_EXTRA:-}" ] && ARGS+=(--extra "$UV_EXTRA")
"${ARGS[@]}"

if [ "${CLEAN_UV_CACHE:-0}" = "1" ]; then
    uv cache clean >/dev/null 2>&1 || true
fi

step "事後条件"

# python と pip が同じ venv を指しているか。ずれていると
# pip install の行き先がベース側になる。
[ -x "$VENV/bin/pip" ] || die "$VENV/bin/pip が無い" "uv venv に --seed が付いているか確かめてください"

# pyproject が == で固定したバージョンを、実際に入ったものと突き合わせる。
# **宣言そのものを読む。** 期待値を外から渡すと、同じ値が 2 箇所に現れる。
"$VENV/bin/python" - "$PROJ" <<'ZZCHECK'
import sys, re, tomllib
import importlib.metadata as md

def norm(n):
    return n.lower().replace("_", "-")

pins = {}
with open(sys.argv[1], "rb") as f:
    doc = tomllib.load(f)
deps = list(doc["project"].get("dependencies", []))
for extra in doc["project"].get("optional-dependencies", {}).values():
    deps += extra
for dep in deps:
    m = re.match(r"^([A-Za-z0-9._-]+)\s*(?:\[[^\]]*\])?\s*==\s*([^\s;,]+)", dep)
    if m:
        pins[norm(m.group(1))] = m.group(2)

if not pins:
    print("    == で固定された依存は無い")
    sys.exit(0)

bad = []
for name, want in sorted(pins.items()):
    try:
        got = md.version(name)
    except md.PackageNotFoundError:
        bad.append(f"{name}: 入っていない（{want} のはず）")
        continue
    # torch==2.11.0+cu130 のような local version は先頭一致で見る
    if got != want and not got.startswith(want.split("+")[0]):
        bad.append(f"{name}: {got}（{want} のはず）")
    else:
        print(f"    {name} {got}")

if bad:
    sys.exit("[venv_uv] ERROR: 宣言と違うバージョンが入っている\n  " + "\n  ".join(bad)
             + "\n  後から入れたものが上書きした可能性があります。"
               " base/pyproject.toml と対になっているか確かめてください")
ZZCHECK

ok "$VENV"
