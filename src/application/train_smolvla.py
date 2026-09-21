#!/usr/bin/env python3
"""SmolVLA の追加学習を、実証済みの設定で回すための script

「追加学習」は、公開済みの学習済みモデル（ここでは SmolVLA）を出発点に、
自分のデータでさらに学習することを指す。ここでは LoRA を使う。LoRA は
元の重みを固定したまま小さな差分行列だけを学習する方法で、出力される
チェックポイントは数 MB から数十 MB に収まる。

**設定値は移行元のリポジトリ（PARC2026_pre）の solution/train/train.py から
持ってきたもので、そこで本番スコア 0.1409 を出した組み合わせである。**
自分で選び直したものではない。持ってこなかったもの（エピソードの選別など）は
下の「持ってきていないもの」に書いてある。

使い方
------
    # まず数十ステップだけ回して、通ることと 1 ステップの所要を見る
    ./datactl.sh up train python /work/src/application/train_smolvla.py --smoke-test

    # 本番
    ./datactl.sh up train python /work/src/application/train_smolvla.py \
        --run-name smolvla_lora_v1 --dataset-repo-id <自分のデータセット>

    # 手元にあるデータセットで回す（Hugging Face から取得しない）
    ./datactl.sh up train python /work/src/application/train_smolvla.py \
        --run-name smolvla_lora_v1 \
        --dataset-root /datasets/<データセットのディレクトリ名>

    # 素の SmolVLA から始める（libero 系の学習を経ていない重み）
    ./datactl.sh up train python /work/src/application/train_smolvla.py \
        --base-model lerobot/smolvla_base --base-revision <コミットハッシュ>

    # 中断した学習を続ける
    ./datactl.sh up train python /work/src/application/train_smolvla.py \
        --run-name smolvla_lora_v1 --resume

持ってきていないもの
------
移行元にはあるが、この script には入れていない機能がある。必要になった時点で
移植する。いま入れていないのは、使う予定が立っていないためである。

    エピソードの選別   … タスクごとの本数指定、特定タスクの強調、
                         明るさによる分散選択、holdout の除外
    重みの混ぜ合わせ   … 学習前と学習後の重みを比率で足す（WiSE-FT）
    LoRA の当て先の拡張 … VLM 側まで広げる指定

**LoRA の当て先を広げるときは注意が要る。** 移行元では、視覚エンコーダまで
当て先にすると 20GB の GPU で OutOfMemory になった。当て先の数ではなく
逆伝播の経路が理由で、視覚を当て先にすると言語の層も勾配の経路に入り、
中間結果を全部持ち続けることになる。

Reads:
  - なし（データセットと出発点の重みは Hugging Face から取得する）
Generates:
  - <出力先>/checkpoints/<ステップ数>/  … LoRA のアダプタと学習状態
  - <出力先>/wandb/                    … wandb の作業ファイル
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from domain.training_schedule import (  # noqa: E402
    PROVEN_LONG_RUN,
    TrainingSchedule,
    schedule_arguments,
    unproven_reason,
)

# 出発点の重み。**素の SmolVLA ではなく、libero 系のデータで一度学習済みの
# 重みから始める。** LeRobot 公式が smolvla_base を
# pepijn223/libero_plus_lerobot で追加学習したもので、移行元のリポジトリが
# これをそのまま提出して本番スコア 0.1409 を得ている。
#
# **リビジョンも固定する。** Hugging Face のリポジトリは後から更新されうるので、
# 固定しないと同じコマンドが別の重みから始まりうる。
DEFAULT_BASE_MODEL = "lerobot/smolvla_libero_plus"
DEFAULT_BASE_REVISION = "7bb70aa5bc92b82c9239142775d3a173103567ff"

# 素の SmolVLA。libero 系の学習を経ていない汎用の重みで、別のデータで
# 学習を始めるときの出発点になる。--base-model に渡して使う。
# **こちらはリビジョンを固定していない**（固定すべき値を特定していないため、
# 使うときは --base-revision も一緒に渡すこと）。
GENERAL_BASE_MODEL = "lerobot/smolvla_base"

# SmolVLA が内部で使う視覚言語モデル。**出発点の重みと揃えないと読めない。**
VLM_MODEL_NAME = "HuggingFaceTB/SmolVLM2-500M-Video-Instruct"

# コンテナの中で書き込める場所。compose.yaml がホスト側のディレクトリを
# ここに bind mount している（envs/.env の OUTPUT_DIR）。
DEFAULT_OUTPUT_ROOT = Path(os.environ.get("OUTPUT_ROOT", "/outputs/train"))

SMOKE_TEST_STEPS = 100

# 視覚言語モデルを読み込む数値の型を、GPU に合わせて差し替えるための差し込み先。
# **python は起動時に sitecustomize という名前の module を自動で読み込む。**
# 学習は別のプロセス（lerobot-train）で動くので、関数を直接差し込めない。
# そのため、このディレクトリを PYTHONPATH の先頭に足して割り込ませる。
# 詳細は gpu_compat/sitecustomize.py の冒頭。
GPU_COMPAT_DIR = Path(__file__).resolve().parents[1] / "gpu_compat"


def _parse_args() -> argparse.Namespace:
    """コマンドライン引数を解析する。"""
    parser = argparse.ArgumentParser(
        description="SmolVLA を LoRA で追加学習する",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--run-name", type=str, default="smolvla_lora",
                        help="出力先のディレクトリ名と、wandb の run 名になる")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT,
                        help="出力先の親ディレクトリ")
    parser.add_argument("--dataset-repo-id", type=str,
                        default="siruku6/reverse_lerobot_v2",
                        help="学習に使う LeRobot 形式データセットの Hugging Face 上の名前")
    parser.add_argument("--dataset-revision", type=str, default="main",
                        help="データセットのリビジョン。**バージョンのタグ"
                             "（v3.0 など）が打たれていないリポジトリでは main を渡す**。"
                             "--dataset-root を渡したときは使われない")
    parser.add_argument("--dataset-root", type=Path, default=None,
                        help="手元にあるデータセットのディレクトリ。**渡すと "
                             "Hugging Face から取得せず、そこを直接読む。** "
                             "コンテナでは /datasets 以下に読み取り専用で"
                             "見えている（envs/.env の DATASETS_DIR）")
    parser.add_argument("--base-model", type=str, default=DEFAULT_BASE_MODEL,
                        help=f"出発点の重み。libero 系を経ていない汎用の重みから"
                             f"始めるなら {GENERAL_BASE_MODEL} を渡す")
    parser.add_argument("--base-revision", type=str, default=DEFAULT_BASE_REVISION,
                        help="出発点の重みのリビジョン。**--base-model を変えたら"
                             "こちらも変えること**（既定値は既定の重みのものである）")

    parser.add_argument("--steps", type=int, default=PROVEN_LONG_RUN.decay_steps,
                        help="学習の総ステップ数")
    parser.add_argument("--batch-size", type=int, default=32,
                        help="バッチ数。移行元が本番スコアを出したときの値")
    parser.add_argument("--learning-rate", type=float,
                        default=PROVEN_LONG_RUN.learning_rate)
    parser.add_argument("--warmup-steps", type=int,
                        default=PROVEN_LONG_RUN.warmup_steps)
    parser.add_argument("--final-learning-rate", type=float,
                        default=PROVEN_LONG_RUN.final_learning_rate)

    parser.add_argument("--lora-r", type=int, default=16,
                        help="LoRA の差分行列の大きさ。大きいほど学習する量が増える")
    parser.add_argument("--lora-alpha", type=int, default=16,
                        help="LoRA の効き幅。効き方は lora_alpha / r で決まる")

    parser.add_argument("--num-workers", type=int, default=2,
                        help="データを読み込む並列数")
    parser.add_argument("--save-freq", type=int, default=500,
                        help="何ステップごとにチェックポイントを書くか")
    parser.add_argument("--log-freq", type=int, default=100,
                        help="何ステップごとに記録するか。**総ステップ数より"
                             "大きいと 1 件も記録されない**")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--video-backend", type=str, default="torchcodec",
                        help="動画の読み出しに使う実装")
    parser.add_argument("--vlm-dtype", type=str, default="auto",
                        choices=("auto", "float16", "bfloat16"),
                        help="視覚言語モデルを読み込む数値の型。"
                             "auto は GPU が bf16 を扱えるかで決める。"
                             "**Turing 世代の GPU では bf16 に専用回路が無いため、"
                             "float16 を明示すると速くなることがある**")

    parser.add_argument("--wandb-project", type=str,
                        default=os.environ.get("WANDB_PROJECT", ""),
                        help="wandb のプロジェクト名。空なら記録しない")
    parser.add_argument("--wandb-entity", type=str,
                        default=os.environ.get("WANDB_ENTITY", ""),
                        help="wandb のチーム名。個人アカウントなら空でよい")
    parser.add_argument("--upload-checkpoints", action="store_true",
                        help="チェックポイントを wandb の artifact として送る。"
                             "**既定では送らない**（重みは 1 つ数 GB になりうる）")

    parser.add_argument("--smoke-test", action="store_true",
                        help=f"{SMOKE_TEST_STEPS} ステップだけ回して、"
                             "通ることと 1 ステップの所要を見る")
    parser.add_argument("--resume", action="store_true",
                        help="同じ --run-name の学習を、最後のチェックポイントから続ける")
    parser.add_argument("--dry-run", action="store_true",
                        help="組み立てたコマンドを表示して終わる")
    parser.add_argument("extra", nargs="*",
                        help="lerobot-train へそのまま渡す追加の引数。"
                             "**同じ設定を 2 度渡すと後ろが勝つ**ので、ここで上書きできる")
    return parser.parse_args()


def _report_gpu(vlm_dtype: str) -> None:
    """どの GPU で回すのか、視覚言語モデルをどの型で読むのかを表示する。

    型の差し替えそのものは gpu_compat/sitecustomize.py が学習プロセスの中で行う。
    ここでは、これから何が起きるかを人に見せるだけである。

    Parameters
    ----------
    vlm_dtype : str
        --vlm-dtype に渡された値（"auto" / "float16" / "bfloat16"）。
    """
    try:
        import torch
    except ImportError:
        print("[train_smolvla] torch が無いため GPU の確認を飛ばします")
        return

    if not torch.cuda.is_available():
        print("[train_smolvla] GPU が見えません")
        return

    device_name = torch.cuda.get_device_name(0)
    capability = torch.cuda.get_device_capability(0)
    bf16_ok = torch.cuda.is_bf16_supported()
    print(f"[train_smolvla] GPU: {device_name}"
          f"（compute capability {capability[0]}.{capability[1]}"
          f" / bf16 {'使える' if bf16_ok else '使えない'}）")

    if vlm_dtype == "auto":
        chosen = "bfloat16" if bf16_ok else "float16"
        note = "" if bf16_ok else "（bf16 が使えないため差し替えます）"
    else:
        chosen = vlm_dtype
        note = "（--vlm-dtype の指定）"
    print(f"[train_smolvla]   視覚言語モデルの型: {chosen}{note}")

    # **Turing 世代（compute capability 7.x）は bf16 に専用回路を持たない。**
    # is_bf16_supported() は True を返すが、遅い経路を通る。
    if bf16_ok and capability[0] == 7 and chosen == "bfloat16":
        print("[train_smolvla]   **この GPU は bf16 に専用回路がありません。**"
              " --vlm-dtype float16 のほうが速い可能性があります。")


def _find_last_checkpoint(output_dir: Path) -> Path | None:
    """続きから学習するためのチェックポイントを探す。

    Parameters
    ----------
    output_dir : Path
        学習の出力先。

    Returns
    -------
    Path | None
        見つかったチェックポイントのディレクトリ。無ければ None。
    """
    last = output_dir / "checkpoints" / "last"
    if last.exists():
        return last.resolve()

    checkpoints = output_dir / "checkpoints"
    if not checkpoints.is_dir():
        return None
    numbered = sorted(p for p in checkpoints.iterdir() if p.name.isdigit())
    return numbered[-1] if numbered else None


def _resume_command(output_dir: Path, checkpoint: Path) -> list[str]:
    """中断した学習を続けるための引数を組み立てる。

    **--policy.* や --steps を重ねて渡さない。** チェックポイントに残っている
    train_config.json をそのまま読ませることで、学習率の時間変化が途中から
    別物になるのを防いでいる。

    Parameters
    ----------
    output_dir : Path
        学習の出力先。
    checkpoint : Path
        続きの起点にするチェックポイントのディレクトリ。

    Returns
    -------
    list[str]
        lerobot-train に渡すコマンド。
    """
    return [
        "lerobot-train",
        f"--config_path={checkpoint / 'pretrained_model' / 'train_config.json'}",
        "--resume=true",
        f"--output_dir={output_dir}",
    ]


def _wandb_arguments(args: argparse.Namespace) -> list[str]:
    """学習の記録を wandb へ送るための引数を組み立てる。

    **lerobot は enable と project の両方が揃ったときだけ送る**
    （lerobot/scripts/lerobot_train.py の `if cfg.wandb.enable and cfg.wandb.project`）。
    そのため project が空なら記録そのものを切る。
    """
    if not args.wandb_project:
        print("[train_smolvla] wandb のプロジェクト名が空なので記録しません"
              "（envs/.env の WANDB_PROJECT を設定してください）")
        return ["--wandb.enable=false"]

    arguments = [
        "--wandb.enable=true",
        f"--wandb.project={args.wandb_project}",
        f"--wandb.disable_artifact={'false' if args.upload_checkpoints else 'true'}",
    ]
    if args.wandb_entity:
        arguments.append(f"--wandb.entity={args.wandb_entity}")
    return arguments


def _train_command(args: argparse.Namespace, output_dir: Path) -> list[str]:
    """最初から学習するための引数を組み立てる。

    Parameters
    ----------
    args : argparse.Namespace
        解析済みの引数。
    output_dir : Path
        学習の出力先。

    Returns
    -------
    list[str]
        lerobot-train に渡すコマンド。
    """
    schedule = TrainingSchedule(
        learning_rate=args.learning_rate,
        warmup_steps=args.warmup_steps,
        decay_steps=args.steps,
        final_learning_rate=args.final_learning_rate,
        source="この実行で指定された値",
    )

    command = [
        "lerobot-train",
        f"--policy.path={args.base_model}",
        # **リビジョンは専用の引数で渡す。** `repo@revision` のような書き方は
        # 受け付けられず、リポジトリ名の一部として扱われて取得に失敗する。
        # LeRobot はこの値を huggingface_hub の revision としてそのまま使う
        # （lerobot/policies/factory.py の make_policy）。
        *([f"--policy.pretrained_revision={args.base_revision}"]
          if args.base_revision else []),
        f"--policy.vlm_model_name={VLM_MODEL_NAME}",
        "--policy.device=cuda",
        # **Hugging Face へは送らない。** push_to_hub の既定は true で、
        # そのままでは repo_id を要求されて起動できない。
        "--policy.push_to_hub=false",
        "--policy.repo_id=null",
        # **入出力の定義を空にする。** こうすると LeRobot が学習データの列名から
        # 引き直すので、カメラ名が出発点の重みと違っていても対応付けが要らない。
        # これを渡さないと observation.images.camera1 のような名前を要求され、
        # --rename_map で 1 つずつ対応させることになる。
        "--policy.input_features=null",
        "--policy.output_features=null",
        "--policy.empty_cameras=0",
        # LoRA を使う場合、この 2 つを切り替えても学習される重みは変わらない
        # （LoRA の当て先に視覚と VLM 本体が 1 つも含まれないため）。
        # それでも出発点の設定と揃えておく。
        "--policy.freeze_vision_encoder=true",
        "--policy.train_expert_only=true",
        *schedule_arguments(schedule, args.steps),
        f"--dataset.repo_id={args.dataset_repo_id}",
        # **手元のディレクトリを読むときは revision を渡さない。**
        # revision は Hugging Face から取るときしか見られない値で、
        # 渡すと LeRobot がバージョンのタグを探して落ちることがある。
        *([f"--dataset.root={args.dataset_root}"]
          if args.dataset_root is not None
          else [f"--dataset.revision={args.dataset_revision}"]),
        # **画像の正規化に ImageNet の統計を使わない。** 出発点の重みが
        # そうなっているので、揃えないと入力の分布がずれる。
        "--dataset.use_imagenet_stats=false",
        f"--dataset.video_backend={args.video_backend}",
        f"--output_dir={output_dir}",
        f"--job_name={args.run_name}",
        f"--steps={args.steps}",
        f"--batch_size={args.batch_size}",
        f"--num_workers={args.num_workers}",
        f"--persistent_workers={'true' if args.num_workers > 0 else 'false'}",
        # 学習中の評価はしない。評価は eval image の役目である。
        "--env_eval_freq=0",
        "--eval_steps=0",
        f"--seed={args.seed}",
        "--save_checkpoint=true",
        f"--save_freq={args.save_freq}",
        "--save_checkpoint_to_hub=false",
        f"--log_freq={args.log_freq}",
        "--peft.method_type=LORA",
        f"--peft.r={args.lora_r}",
        f"--peft.lora_alpha={args.lora_alpha}",
        *_wandb_arguments(args),
    ]
    # **最後に置く。** 同じ設定を 2 度渡すと後ろが勝つので、ここで上書きできる。
    return command + list(args.extra)


def _check_schedule(args: argparse.Namespace) -> None:
    """学習率の組み立てが実証済みでなければ伝える。**止めはしない。**"""
    schedule = TrainingSchedule(
        learning_rate=args.learning_rate,
        warmup_steps=args.warmup_steps,
        decay_steps=args.steps,
        final_learning_rate=args.final_learning_rate,
        source="この実行で指定された値",
    )
    reason = unproven_reason(schedule, args.steps)
    if reason is None:
        return
    print(f"[train_smolvla] **注意: {reason}")
    print("[train_smolvla]   経緯は docs/ADR/"
          "0005-training-schedule-must-come-as-a-set.md にあります。")


def _print_run_header(args: argparse.Namespace, output_dir: Path) -> None:
    """これから何を回すのかを、実行の前に一覧で出す。"""
    print("=== これから回す学習 ===")
    print(f"  出発点の重み    : {args.base_model}")
    print(f"  そのリビジョン  : {args.base_revision or '（固定しない）'}")
    if args.dataset_root is not None:
        print(f"  データセット    : {args.dataset_root}（手元のディレクトリ）")
    else:
        print(f"  データセット    : {args.dataset_repo_id}@{args.dataset_revision}")
    print(f"  ステップ数      : {args.steps:,}  （バッチ {args.batch_size}）")
    print(f"  引き出すコマ数  : {args.steps * args.batch_size:,}")
    print(f"  学習率          : {args.learning_rate:g}"
          f" → {args.final_learning_rate:g}（warmup {args.warmup_steps}）")
    print(f"  LoRA            : r={args.lora_r} alpha={args.lora_alpha}")
    print(f"  出力先          : {output_dir}")
    print()


def main() -> None:
    args = _parse_args()
    if args.smoke_test:
        args.steps = SMOKE_TEST_STEPS
        args.save_freq = SMOKE_TEST_STEPS
        args.log_freq = max(1, SMOKE_TEST_STEPS // 10)
        print(f"[train_smolvla] 試運転: {SMOKE_TEST_STEPS} ステップだけ回します")

    output_dir: Path = (args.output_root / args.run_name).resolve()

    _report_gpu(args.vlm_dtype)

    if args.resume:
        checkpoint = _find_last_checkpoint(output_dir)
        if checkpoint is None:
            sys.exit(f"[train_smolvla] {output_dir} に続きから始められる"
                     "チェックポイントがありません")
        print(f"[train_smolvla] {checkpoint} から続けます")
        command = _resume_command(output_dir, checkpoint)
    else:
        if output_dir.exists():
            sys.exit(
                f"[train_smolvla] 出力先が既にあります: {output_dir}\n"
                "  --run-name を変える / そのディレクトリを消す / "
                "--resume で続ける のいずれかにしてください"
            )
        _check_schedule(args)
        _print_run_header(args, output_dir)
        command = _train_command(args, output_dir)

    print("=== 実行するコマンド ===")
    print(" ".join(command))
    print()
    if args.dry_run:
        return

    # **学習プロセスの python に gpu_compat を読み込ませる。**
    # sitecustomize は起動時に自動で import されるので、lerobot が transformers を
    # import する前に型の差し替えが効く。PYTHONPATH の先頭に置く。
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(GPU_COMPAT_DIR), *([environment["PYTHONPATH"]] if environment.get("PYTHONPATH") else [])]
    )
    environment["LEROBOT_TOOLS_VLM_DTYPE"] = args.vlm_dtype

    completed = subprocess.run(command, check=False, env=environment)
    sys.exit(completed.returncode)


if __name__ == "__main__":
    main()
