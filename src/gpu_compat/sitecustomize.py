"""SmolVLA が視覚言語モデルを読み込むときの数値の型を、GPU に合わせて差し替える module

**このファイル名は python の決まりである。** python は起動時に、import できる
場所に `sitecustomize` という名前の module があれば自動で読み込む。学習は
`lerobot-train` という別のプロセスで動くため、呼び出し側から関数を差し込めない。
そこで、このディレクトリを PYTHONPATH の先頭に置くことで、lerobot が
transformers を import する前に割り込んでいる。

**なぜ差し替えが要るのか。** SmolVLA は視覚言語モデルを bfloat16（bf16）で
読み込むよう直書きしている。

    lerobot/policies/smolvla/smolvlm_with_expert.py の
    AutoModelForImageTextToText.from_pretrained(model_id, torch_dtype="bfloat16", ...)

bf16 は数値の表し方の 1 つで、**Ampere 世代以降の NVIDIA GPU が専用の回路で
速く扱える。** それより古い Turing 世代（Quadro RTX 6000 など）には専用回路が
無く、遅い経路を通るか、そもそも扱えない。**設定で変える手段は lerobot 側に
用意されていない**（policies/smolvla/configuration_smolvla.py に dtype の項目が無い）。

**書き換えではなく差し込みにした理由。** 移行元のリポジトリ（PARC2026_pre）は
上記のファイルを直接書き換えていた。この環境では 2 つの理由でそれができない。

1. lerobot は /opt/venv の中に root 所有で入っており、コンテナはホストの
   ユーザーで動いている（envs/compose.yaml の user: 指定）ので書き込めない
2. どの型が要るかは**実行する GPU で決まる**ので、image を焼く時点では決まらない

差し込みなら、書き換えずに実行のたびに判断できる。

環境変数
------
LEROBOT_TOOLS_VLM_DTYPE
    float16   … bf16 が使えても float16 で読み込む（Turing で速さを取る場合）
    bfloat16  … 常に bfloat16 で読み込む（差し替えをしない）
    auto      … GPU が bf16 を扱えるかで決める（既定）
"""

from __future__ import annotations

import os
import sys

_ENV_NAME = "LEROBOT_TOOLS_VLM_DTYPE"
_LOG_PREFIX = "[gpu_compat]"


def _requested_dtype() -> str:
    """環境変数で指定された型を返す。指定が無ければ "auto" を返す。"""
    value = os.environ.get(_ENV_NAME, "auto").strip().lower()
    if value in ("float16", "fp16", "half"):
        return "float16"
    if value in ("bfloat16", "bf16"):
        return "bfloat16"
    return "auto"


def _dtype_for_this_gpu() -> str | None:
    """この GPU で視覚言語モデルを読み込むべき型を決める。

    Returns
    -------
    str | None
        差し替える型の名前。差し替えが不要なら None。
    """
    requested = _requested_dtype()
    if requested == "bfloat16":
        return None

    try:
        import torch
    except ImportError:
        return None

    if requested == "float16":
        print(f"{_LOG_PREFIX} {_ENV_NAME}=float16 の指定により float16 で読み込みます",
              file=sys.stderr)
        return "float16"

    # auto: GPU が bf16 を扱えないときだけ差し替える
    if not torch.cuda.is_available():
        return None
    try:
        if torch.cuda.is_bf16_supported():
            return None
    except Exception:  # noqa: BLE001
        # 古い torch では GPU の無い環境で例外になる。差し替えない側に倒す
        return None

    print(f"{_LOG_PREFIX} {torch.cuda.get_device_name(0)} は bf16 を扱えないため "
          "float16 で読み込みます", file=sys.stderr)
    return "float16"


def _patch_from_pretrained(dtype_name: str) -> None:
    """transformers がモデルを読み込むときの型指定を差し替える。

    SmolVLA が渡してくる `torch_dtype="bfloat16"` を `dtype_name` に置き換える。
    transformers 5 系では引数名が `dtype` に変わっているので、両方を見る。

    Parameters
    ----------
    dtype_name : str
        置き換え先の型の名前（"float16" など）。
    """
    try:
        from transformers import AutoModelForImageTextToText
    except ImportError:
        return

    original = AutoModelForImageTextToText.from_pretrained

    def from_pretrained(*args, **kwargs):
        for keyword in ("torch_dtype", "dtype"):
            if kwargs.get(keyword) == "bfloat16":
                kwargs[keyword] = dtype_name
        return original(*args, **kwargs)

    AutoModelForImageTextToText.from_pretrained = from_pretrained


def _apply() -> None:
    """この module が読み込まれたときに 1 度だけ走る入口。"""
    dtype_name = _dtype_for_this_gpu()
    if dtype_name is None:
        return
    _patch_from_pretrained(dtype_name)


try:
    _apply()
except Exception as error:  # noqa: BLE001
    # **学習を止めない。** 差し込みに失敗しても、bf16 で読めるなら学習は進む。
    print(f"{_LOG_PREFIX} 型の差し替えに失敗しました（学習は続けます）: {error}",
          file=sys.stderr)
