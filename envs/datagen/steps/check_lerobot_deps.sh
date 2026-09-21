#!/usr/bin/env bash
# lerobot を --no-deps で入れたあと、依存の抜けが無いかを確かめる
#
# Usage
# ------
#   VENV=/opt/venv bash check_lerobot_deps.sh
#
# 入力: VENV
# 出力: なし（検査のみ）
# 事後条件: lerobot の主要な入口が import でき、numpy が上がっていない
#
#
# なぜこの検査が要るのか
# ------
# lerobot は --no-deps で入れている。numpy>=2.0.0 という宣言を解決器に
# 渡さないためだが、**同時に lerobot の依存宣言すべてが効かなくなる。**
# 足りない分は pyproject.toml に手で並べてあり、そこに抜けがあっても
# インストールは成功する。落ちるのは実行時である。
#
# 2026-09-21、gymnasium / cmake / setuptools を落としたまま気付かず、
# import の時点で ModuleNotFoundError になった。ビルドの中で捕まえる。
set -euo pipefail
_here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$_here/../lib/log.sh"

require_env VENV

step "lerobot の依存に抜けが無いか"

"$VENV/bin/python" - <<'ZZCHECK'
import sys, importlib

# **実際に import して確かめる。** 宣言の突き合わせでは、宣言そのものが
# 間違っている場合を捕まえられない。
targets = [
    ("lerobot",                                "本体"),
    ("lerobot.datasets.lerobot_dataset",       "LeRobotDataset（変換の入口）"),
    ("lerobot.datasets.dataset_tools",         "merge / split"),
]
bad = []
for mod, what in targets:
    try:
        importlib.import_module(mod)
        print(f"    OK  {mod}  （{what}）")
    except Exception as e:
        bad.append(f"{mod}: {type(e).__name__}: {e}")

import numpy
print(f"    numpy {numpy.__version__}")
if numpy.__version__ != "1.26.4":
    bad.append(f"numpy が {numpy.__version__}（1.26.4 のはず）。"
               " --no-deps が効いていないか、後から上書きされています")

if bad:
    sys.exit("[check_lerobot_deps] ERROR:\n  " + "\n  ".join(bad)
             + "\n  envs/datagen/pyproject.toml に足りない依存があります。"
               " lerobot の宣言と突き合わせてください")
ZZCHECK
ok "lerobot の入口はすべて import できる"
