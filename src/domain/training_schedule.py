"""学習率の時間変化の組み立てと、過去に事故を起こした組み合わせの検出を行う module

ここで言う「学習率の時間変化」は、LeRobot の学習が次の 4 つで表すものを指す。

    optimizer_lr            … 立ち上げ終了後の学習率
    scheduler_warmup_steps  … 0 からそこまで上げるのに使うステップ数
    scheduler_decay_steps   … そこから下げ終わるまでのステップ数
    scheduler_decay_lr      … 下げ終わったときの学習率

**この 4 つは互いに独立ではない。** 片方だけ他の出典から持ってくると、
どの出典も認めていない組み合わせが出来上がる。移行元のリポジトリ
（PARC2026_pre）では実際にそれが起き、提出したモデルの本番スコアが
0.1409 から 0.016 へ 8.8 倍悪化した。経緯は
docs/ADR/0005-training-schedule-must-come-as-a-set.md にある。

この module は判断を代行しない。**組み合わせが実証済みでなければ伝えるだけで、
学習を止めない。** ステップ数を減らして試す使い方は正しいからである。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TrainingSchedule:
    """学習率の時間変化を 1 組として表す。

    Attributes
    ----------
    learning_rate : float
        立ち上げが終わったあとの学習率。
    warmup_steps : int
        0 から learning_rate まで上げるのに使うステップ数。
    decay_steps : int
        learning_rate から final_learning_rate まで下げるのに使うステップ数。
        **学習の総ステップ数と揃える。**
    final_learning_rate : float
        下げ終わったときの学習率。
    source : str
        この組み合わせの出典。どこから来た値なのかを人が追えるようにするためで、
        学習の挙動には影響しない。
    """

    learning_rate: float
    warmup_steps: int
    decay_steps: int
    final_learning_rate: float
    source: str


# LeRobot 公式（Hugging Face の lerobot org）が公開している smolvla_libero_plus を
# 作ったときの設定。重みの連なりは次のようになっている。
#
#     lerobot/smolvla_base            LeRobot が公開した汎用の SmolVLA
#       │                             **どう学習したかは公開されていない**
#       │                             （このリポジトリに train_config.json が無い）
#       │  LeRobot が pepijn223/libero_plus_lerobot で追加学習
#       ▼
#     lerobot/smolvla_libero_plus     その結果の重み
#                                     **この追加学習の設定が train_config.json に残る**
#
# **下の 4 つの値は、この矢印の部分（base → libero_plus）の設定である。**
# 出発点である smolvla_base 自身の学習設定ではない。smolvla_base は
# それを公開していないため、そもそも借りられない。
#
# 借りる根拠は目的が一致していることにある。この矢印は「汎用のモデルを
# libero 系のデータに寄せる」ための学習で、この script がやろうとしていることと
# 同じ向きである。
#
# **出典は重みに同梱されている train_config.json で、誰でも確認できる。**
# リビジョンで固定してあるので、後から中身が変わることはない。
#
#     https://huggingface.co/lerobot/smolvla_libero_plus/blob/7bb70aa5bc92b82c9239142775d3a173103567ff/train_config.json
#
#     curl -sL https://huggingface.co/lerobot/smolvla_libero_plus/raw/7bb70aa5bc92b82c9239142775d3a173103567ff/train_config.json \
#       | python3 -c "
#     import json, sys
#     p = json.load(sys.stdin)['policy']
#     for k in ('optimizer_lr', 'scheduler_warmup_steps',
#               'scheduler_decay_steps', 'scheduler_decay_lr'):
#         print(k, p[k])
#     "
#
# 同じ train_config.json にある、学習率以外の条件（2026-09-21 に取得して確認）:
#
#     steps 20,000 / batch_size 32 / dataset pepijn223/libero_plus_lerobot /
#     episodes None（全件）
#
# **注意: この学習は LoRA ではない。** use_peft / freeze_vision_encoder /
# train_expert_only がすべて false で、**画像を読む側まで含めた全パラメータ**を
# 学習している。この script は LoRA で使うので、**学ぶ範囲が違う組み合わせから
# 学習率だけを借りている**ことになる。借りて良いと判断した根拠は、後述の
# 「本番スコア」の出どころにある。
#
# **本番スコア 0.1409 という数字は Hugging Face には無い。** これは移行元の
# リポジトリ（PARC2026_pre）が、この重みをそのままコンペに提出して得た点数で、
# 出典は移行元の docs/reference/11_training_schedule.md である。
# **つまり「この設定で作られた重みが、実際に通用した」ところまでが確かめられている。**
PROVEN_LONG_RUN = TrainingSchedule(
    learning_rate=1e-4,
    warmup_steps=1_000,
    decay_steps=20_000,
    final_learning_rate=2.5e-6,
    source=(
        "lerobot/smolvla_libero_plus の train_config.json"
        "（revision 7bb70aa5bc92b82c9239142775d3a173103567ff。"
        "この重みの本番スコアは 0.1409）"
    ),
)

# **コンペ運営が配布したノートブックが示した組み合わせ。**
# 3,000 ステップ・バッチ 1 という短い学習のための値である。
# **こちらは Hugging Face には無い。** 出典は移行元のリポジトリ（PARC2026_pre）が
# 配布物として持っている examples/smolvla_libero_spatial_lora.ipynb である。
# そちらは LoRA を使っており、学ぶ範囲はこの script と同じである。
PROVEN_SHORT_RUN = TrainingSchedule(
    learning_rate=3e-4,
    warmup_steps=100,
    decay_steps=3_000,
    final_learning_rate=3e-5,
    source="配布ノートブック smolvla_libero_spatial_lora.ipynb",
)

PROVEN_SCHEDULES: tuple[TrainingSchedule, ...] = (PROVEN_LONG_RUN, PROVEN_SHORT_RUN)


def schedule_arguments(schedule: TrainingSchedule, total_steps: int) -> list[str]:
    """LeRobot の学習コマンドに渡す、学習率まわりの引数を組み立てる。

    Parameters
    ----------
    schedule : TrainingSchedule
        使う組み合わせ。
    total_steps : int
        学習の総ステップ数。**decay_steps はこれに合わせる。**
        組み合わせが持つ decay_steps ではなく総ステップ数を使うのは、
        ステップ数だけ変えて試すことがあるためである。

    Returns
    -------
    list[str]
        `--policy.optimizer_lr=...` のような形の引数の並び。
    """
    return [
        f"--policy.optimizer_lr={schedule.learning_rate}",
        f"--policy.scheduler_warmup_steps={schedule.warmup_steps}",
        f"--policy.scheduler_decay_steps={total_steps}",
        f"--policy.scheduler_decay_lr={schedule.final_learning_rate}",
    ]


def unproven_reason(schedule: TrainingSchedule, total_steps: int) -> str | None:
    """実証済みの組み合わせから外れているなら、その理由の文章を返す。

    外れていなければ None を返す。**判定するのは学習率の組み立てだけ**で、
    バッチ数やデータ量は見ない（どの出典にも記録が残っていないため）。

    Parameters
    ----------
    schedule : TrainingSchedule
        これから使う組み合わせ。
    total_steps : int
        学習の総ステップ数。

    Returns
    -------
    str | None
        人が読む警告の文章。実証済みならば None。
    """
    for proven in PROVEN_SCHEDULES:
        matches_rates = (
            schedule.learning_rate == proven.learning_rate
            and schedule.warmup_steps == proven.warmup_steps
            and schedule.final_learning_rate == proven.final_learning_rate
        )
        if matches_rates and total_steps <= proven.decay_steps:
            return None

    # **短い学習向けの学習率で長く回す形は、実際に事故を起こしている。**
    # そこだけは何が起きたかまで伝える。
    short = PROVEN_SHORT_RUN
    if (
        schedule.learning_rate >= short.learning_rate
        and total_steps > short.decay_steps
    ):
        return (
            f"学習率 {schedule.learning_rate:g} は {short.source} の値で、"
            f"{short.decay_steps:,} ステップを想定したものです。"
            f"いま {total_steps:,} ステップを指定しています。\n"
            "  これは本番スコアを 0.1409 から 0.016 へ落とした回と同じ組み合わせです。\n"
            f"  長く回すなら {PROVEN_LONG_RUN.source} と同じ "
            f"--learning-rate {PROVEN_LONG_RUN.learning_rate:g} "
            f"--warmup-steps {PROVEN_LONG_RUN.warmup_steps} "
            f"--final-learning-rate {PROVEN_LONG_RUN.final_learning_rate:g} "
            "に揃えてください。"
        )

    return (
        f"学習率 {schedule.learning_rate:g} / warmup {schedule.warmup_steps} / "
        f"最終 {schedule.final_learning_rate:g} / {total_steps:,} ステップという"
        "組み合わせを裏付ける出典がありません。\n"
        "  実証済みの組み合わせは次の 2 つです。\n"
        + "\n".join(
            f"    {p.learning_rate:g} / {p.warmup_steps} / {p.final_learning_rate:g} / "
            f"{p.decay_steps:,} ステップ（{p.source}）"
            for p in PROVEN_SCHEDULES
        )
    )
