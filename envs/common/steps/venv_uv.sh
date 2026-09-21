#!/usr/bin/env bash
# 入力: ENV_DIR（pyproject.toml のあるディレクトリ）, VENV（作る場所）
#       省略可: UV_PY（既定 3.12）, UV_EXTRA
# 出力: $VENV
# 事後条件: $VENV/bin/python が動き、pyproject.toml が == で固定した版が
#           そのとおり入っている
#
# 必要な外部コマンド: uv
#
# **どの環境を作るかは入力で決まる。** この step 自体は「uv で venv を作る」
# 以上のことを知らない。LIBERO 用か lerobot 用かは ENV_DIR が決める。
set -euo pipefail
_here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$_here/../lib/log.sh"
. "$_here/../lib/guard.sh"

require_env ENV_DIR VENV
PY="${UV_PY:-3.12}"
[ -f "$ENV_DIR/pyproject.toml" ] || die "$ENV_DIR/pyproject.toml が無い" \
    "ENV_DIR を確かめてください"

step "venv: $VENV（定義 $ENV_DIR / python $PY）"

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
export UV_PROJECT_ENVIRONMENT="$VENV"
# TODO: uv.lock をコミットして --frozen にする。今は解決を毎回走らせている。
if [ -n "${UV_EXTRA:-}" ]; then
    uv sync --project "$ENV_DIR" --extra "$UV_EXTRA"
else
    uv sync --project "$ENV_DIR"
fi

# **イメージに焼くときはキャッシュを残さない。** uv は取得した wheel を
# ~/.cache/uv に貯める。同じ RUN の中で消さないとレイヤーに数 GB 残る。
# ホストで流すときは他のプロジェクトの取得結果まで消してしまうので、
# 消すかどうかは呼ぶ側が決める（Dockerfile が CLEAN_UV_CACHE=1 を渡す）。
if [ "${CLEAN_UV_CACHE:-0}" = "1" ]; then
    uv cache clean >/dev/null 2>&1 || true
    info "uv のキャッシュを消した"
fi

step "事後条件"

# python と pip が同じ venv を指しているか。ずれていると
# pip install の行き先がベース側になる。
"$VENV/bin/python" - "$VENV" <<'ZZPIP'
import sys, pathlib, shutil
venv = pathlib.Path(sys.argv[1]).resolve()
pip = venv / "bin" / "pip"
if not pip.exists():
    sys.exit(f"[venv_uv] ERROR: {pip} が無い。uv venv に --seed が付いているか確かめてください")
print(f"    python と pip はどちらも {venv}")
ZZPIP
"$VENV/bin/python" - <<'PY'
import sys
print(f"    python {sys.version.split()[0]}")
for mod in ("numpy", "torch"):
    try:
        m = __import__(mod)
        print(f"    {mod} {m.__version__}")
    except Exception as e:
        print(f"    {mod} — import できない: {e}")
PY

# **「入ったか」と「意図した版か」は別の主張である。** 指定があれば突き合わせる。
# **pyproject.toml が == で固定した版を、実際に入ったものと突き合わせる。**
#
# 以前は EXPECT_NUMPY / EXPECT_TORCH を外から渡していたが、それは pyproject に
# 書いてある値の複製だった。同じ値が 2 箇所にあると、片方だけ直して気付かない。
# 宣言そのものを読めば複製が要らない。
"$VENV/bin/python" - "$ENV_DIR/pyproject.toml" <<'CHECK'
import sys, re, tomllib
import importlib.metadata as md

with open(sys.argv[1], "rb") as f:
    doc = tomllib.load(f)
deps = list(doc["project"].get("dependencies", []))
for extra in doc["project"].get("optional-dependencies", {}).values():
    deps += extra

pins = {}
for dep in deps:
    m = re.match(r"^([A-Za-z0-9._-]+)\s*(?:\[[^\]]*\])?\s*==\s*([^\s;,]+)", dep)
    if m:
        pins[m.group(1).lower().replace("_", "-")] = m.group(2)

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
    sys.exit("[venv_uv] ERROR: 宣言と違う版が入っている\n  " + "\n  ".join(bad)
             + "\n  解決の順番か index の指定を確かめてください")
CHECK
ok "$VENV"
