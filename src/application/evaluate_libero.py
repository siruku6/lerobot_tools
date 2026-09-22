"""LIBERO のタスクでポリシーを評価し、採点結果に加えて軌道と映像を書き出す。

移行元リポジトリ（PARC2026_pre）の評価パイプラインをそのまま動かし、
**採点の過程で捨てられてしまう情報を、捨てられる前に横から受け取って保存する。**

何のためにこれが要るか
----------------------
評価パイプラインはエピソードごとに手先位置・関節角・行動・報酬を集めているが、
最終的にファイルへ書くのはタスク単位の集計だけである（成功率や jerk などの指標）。
そのため「どのエピソードが失敗したのか」「どこで外したのか」が後から分からない。

ここで保存したものを envs/io の可視化スクリプトが読み、wandb へ送る。

採点処理そのものには手を触れない
--------------------------------
**pipeline/ は /reference に読み取り専用でマウントされた原本をそのまま import する。**
採点のコードをこちらへ写すと、採点環境との間で内容が少しずつずれていき、
「手元では通るのに本番では違う」という形の食い違いを生む。

そのためエピソードの取り出しは、RolloutExecutor.evaluate_tasks を包む
5 行の継ぎ目だけで行う（_install_result_capture を参照）。

Usage
-----
    # ランダムポリシーで配線を確かめる
    ./datactl.sh up eval /opt/venv/bin/python /work/src/application/evaluate_libero.py \
        --dry-run --run-name wiring_check --tasks <task> --n-episodes 2 --max-steps 60

    # 学習した重みを載せたポリシーサーバーを評価する
    ./datactl.sh up eval /opt/venv/bin/python /work/src/application/evaluate_libero.py \
        --server-url http://policy:8000 --run-name smolvla_lora_10k

Reads:
  - /reference/pipeline/（評価パイプラインの原本）
  - /reference/compe/t1/T1_TASKS.csv（libero_t1 の課題定義。pipeline が読む）
Generates:
  - <出力先>/run_meta.json         **何で回したか**（ポリシーの種類・本数・打ち切り）
  - <出力先>/<submission_id>.json  採点結果（pipeline 自身が書く）
  - <出力先>/episodes.json         エピソード一覧（成否・ステップ数・衝突）
  - <出力先>/arrays/<番号>.npz     軌道（手先位置・姿勢・関節角・行動・報酬・物体位置）
  - <出力先>/frames/<番号>/*.jpg   2 台のカメラを横に並べたフレーム
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import numpy as np

DEFAULT_OUTPUT_ROOT = Path("/outputs/eval")

# 記録するカメラ。**この順で横に並べる。**
CAMERA_NAMES: tuple[str, ...] = ("agentview_image", "robot0_eye_in_hand_image")

# JPEG の品質。実測で 128x128 の 1 フレームが 5.1KiB（生の 1/9）になる。
JPEG_QUALITY = 92

logger = logging.getLogger("evaluate_libero")


@dataclass
class RecordedEpisode:
    """1 エピソードのうち、評価パイプラインが保存しないもの。

    軌道そのもの（手先位置など）は評価パイプライン側が集めているので、ここには
    持たない。**ここに入るのは、ポリシーに渡された観測からしか取れないもの**である。
    """

    instruction: str
    seed: int | None
    frame_count: int = 0
    object_positions: dict[str, list[np.ndarray]] = field(default_factory=dict)


class RecordingPolicy:
    """ポリシーを包み、観測が通り過ぎるたびに映像と物体位置を書き留める。

    評価パイプラインはポリシーに観測をそのまま渡すので、**ここを通せば
    シミュレータを再度動かさずに映像が手に入る**（観測にカメラ画像が入っている）。

    エピソードの切れ目は reset() で分かる（評価パイプラインが 1 エピソードにつき
    1 回だけ呼ぶ）。
    """

    def __init__(
        self,
        inner_policy: Any,
        frames_root: Path | None,
        jpeg_quality: int = JPEG_QUALITY,
    ) -> None:
        self._inner_policy = inner_policy
        self._frames_root = frames_root
        self._jpeg_quality = jpeg_quality
        self.episodes: list[RecordedEpisode] = []

    def reset(self, instruction: str = "", seed: int | None = None) -> None:
        self.episodes.append(RecordedEpisode(instruction=instruction, seed=seed))
        self._inner_policy.reset(instruction=instruction, seed=seed)

    def get_action(self, obs: dict[str, np.ndarray]) -> np.ndarray:
        if self.episodes:
            self._record(obs)
        return self._inner_policy.get_action(obs)

    def _record(self, obs: dict[str, np.ndarray]) -> None:
        episode = self.episodes[-1]
        self._record_object_positions(episode, obs)
        if self._frames_root is not None:
            self._write_frame(episode, obs)
        episode.frame_count += 1

    def _record_object_positions(
        self, episode: RecordedEpisode, obs: dict[str, np.ndarray]
    ) -> None:
        """観測に入っている物体の位置を控える。

        軌道だけを 3 次元にプロットしても、**何を掴もうとしていたのかが無いと
        読めない。** 目標物の位置を一緒に描くために保存する。
        """
        for key, value in obs.items():
            if not key.endswith("_pos") or key.startswith("robot0"):
                continue
            if key.endswith("_to_robot0_eef_pos"):
                continue
            episode.object_positions.setdefault(key[: -len("_pos")], []).append(
                np.asarray(value, dtype=np.float32).copy()
            )

    def _write_frame(self, episode: RecordedEpisode, obs: dict[str, np.ndarray]) -> None:
        import cv2

        panels = [
            _to_viewable(np.asarray(obs[name]))
            for name in CAMERA_NAMES
            if name in obs
        ]
        if not panels:
            return
        combined = np.hstack(panels)
        episode_dir = self._frames_root / f"{len(self.episodes) - 1:04d}"
        episode_dir.mkdir(parents=True, exist_ok=True)
        path = episode_dir / f"{episode.frame_count:05d}.jpg"
        # cv2 は BGR 順で受け取るので、RGB を入れ替えてから渡す。
        cv2.imwrite(
            str(path),
            combined[:, :, ::-1],
            [cv2.IMWRITE_JPEG_QUALITY, self._jpeg_quality],
        )


def _to_viewable(image: np.ndarray) -> np.ndarray:
    """シミュレータが返した画像を、ポリシーが見ているのと同じ向きに直す。

    **180 度回す（上下と左右の両方を反転する）。** 上下だけ反転しても人の目には
    正しい向きに見えるが、**左右が鏡になる**ため、ポリシーが見ている絵とは
    別物になる。それでは映像を見て失敗の原因を判断できない。

    この 180 度という値は 2 つの出所が一致している。
      - 学習データの作り手: PARC2026_pre の scripted_demo.py:1264 が
        `agentview_image[::-1, ::-1]` を保存している
      - 推論時の前処理: LeRobot の LiberoProcessorStep が
        `torch.flip(img, dims=[2, 3])`（高さと幅の両方）を掛ける
    """
    return np.ascontiguousarray(image[::-1, ::-1])


class RandomPolicy:
    """配線の確認に使う、観測を見ないポリシー。

    評価パイプライン側にも同じものがあるが、あちらは CLI の中に閉じていて
    import できる形になっていないため、ここに置いている。
    """

    def __init__(self, action_dim: int = 7) -> None:
        self.action_dim = action_dim

    def get_action(self, obs: dict[str, np.ndarray]) -> np.ndarray:
        return np.random.uniform(-1, 1, size=self.action_dim).astype(np.float32)

    def reset(self, instruction: str = "", seed: int | None = None) -> None:
        if seed is not None:
            np.random.seed(seed)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="LIBERO の評価を回し、軌道と映像を書き出す"
    )
    parser.add_argument("--run-name", required=True, help="出力先の名前")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help=f"出力先の親ディレクトリ（既定 {DEFAULT_OUTPUT_ROOT}）",
    )
    parser.add_argument("--server-url", default=None, help="ポリシーサーバーの URL")
    parser.add_argument(
        "--dry-run", action="store_true", help="ランダムポリシーで配線だけ確かめる"
    )
    parser.add_argument("--benchmark", default="libero_t1", help="ベンチマーク名")
    parser.add_argument("--tasks", nargs="+", default=None, help="タスク名を指定する")
    parser.add_argument("--max-tasks", type=int, default=None, help="タスク数の上限")
    parser.add_argument("--n-episodes", type=int, default=20, help="タスクあたりの本数")
    parser.add_argument("--max-steps", type=int, default=300, help="1 本の最大ステップ")
    parser.add_argument("--seed", type=int, default=42, help="乱数シード")
    parser.add_argument("--timeout", type=float, default=30.0, help="推論のタイムアウト（秒）")
    parser.add_argument(
        "--no-frames", action="store_true", help="映像を保存しない（軌道だけ記録する）"
    )
    return parser.parse_args()


def _build_eval_config(args: argparse.Namespace, output_dir: Path) -> Any:
    """コマンドライン引数を、評価パイプラインの設定に移し替える。"""
    from pipeline.config import EvalConfig

    config = EvalConfig(
        n_eval_episodes=args.n_episodes,
        max_steps_per_episode=args.max_steps,
        seed=args.seed,
    )
    config.output_dir = output_dir
    config.benchmark_name = args.benchmark
    if args.max_tasks is not None:
        config.max_tasks = args.max_tasks
    if args.tasks:
        config.task_ids = args.tasks
    return config


def _build_policy(args: argparse.Namespace) -> tuple[Any, str, str]:
    """評価対象のポリシーと、結果ファイルに付ける名前・ポリシーの種類を決める。

    Returns
    -------
    policy : Any
        get_action / reset を持つオブジェクト。
    submission_id : str
        採点結果の JSON のファイル名になる。
    policy_kind : str
        "random"（配線確認用の乱数）か "server"（ポリシーサーバー）。
        **この値は記録に残す。** 乱数で回した結果を、学習した重みの成績だと
        取り違えられないようにするためである（実際にその取り違えが起きた）。
    """
    if args.dry_run:
        logger.info("ランダムポリシーで実行します（配線の確認。**重みは一切使いません**）")
        return RandomPolicy(), "dry_run", "random"

    if not args.server_url:
        raise SystemExit("--dry-run か --server-url のどちらかを指定してください")

    from pipeline.remote_policy import RemotePolicyClient

    logger.info("ポリシーサーバーに接続します: %s", args.server_url)
    client = RemotePolicyClient(server_url=args.server_url, timeout_sec=args.timeout)
    client.wait_for_server()
    return client, args.run_name, "server"


def _install_result_capture(pipeline: Any) -> list[Any]:
    """評価結果が捨てられる前に受け取るための継ぎ目を差し込む。

    評価パイプラインは、エピソードごとの結果（軌道つき）を採点に渡した後は
    保持しない。**採点の流れには一切触れず**、通り過ぎる戻り値を控えるだけにする。

    Returns
    -------
    captured : list
        評価が終わった後に TaskResult が順番どおり入るリスト。
    """
    captured: list[Any] = []
    original_evaluate_tasks: Callable[..., list[Any]] = pipeline.executor.evaluate_tasks

    def evaluate_tasks_and_capture(*args: Any, **kwargs: Any) -> list[Any]:
        task_results = original_evaluate_tasks(*args, **kwargs)
        captured.extend(task_results)
        return task_results

    pipeline.executor.evaluate_tasks = evaluate_tasks_and_capture
    return captured


def _stack(values: list[np.ndarray]) -> np.ndarray:
    if not values:
        return np.zeros((0,), dtype=np.float32)
    return np.asarray(values, dtype=np.float32)


def _write_records(
    output_dir: Path,
    task_results: list[Any],
    recorded_episodes: list[RecordedEpisode],
) -> None:
    """エピソード単位の軌道とメタデータをディスクへ書く。

    評価パイプラインが集めた軌道（task_results 側）と、観測からしか取れないもの
    （recorded_episodes 側）を突き合わせる。**どちらも評価した順に並んでいる**ので、
    先頭から順に対応する。数が合わなければ、対応が崩れているので止める。
    """
    arrays_dir = output_dir / "arrays"
    arrays_dir.mkdir(parents=True, exist_ok=True)

    flat_episodes = [
        (task_result, episode)
        for task_result in task_results
        for episode in task_result.episodes
    ]
    if len(flat_episodes) != len(recorded_episodes):
        raise RuntimeError(
            "エピソードの数が食い違っています: "
            f"採点側 {len(flat_episodes)} / 記録側 {len(recorded_episodes)}。"
            " ポリシーの包み方か、評価の流れが変わった可能性があります"
        )

    index: list[dict[str, Any]] = []
    for episode_index, ((task_result, episode), recorded) in enumerate(
        zip(flat_episodes, recorded_episodes)
    ):
        arrays: dict[str, np.ndarray] = {
            "ee_positions": _stack(episode.ee_positions),
            "ee_orientations": _stack(episode.ee_orientations),
            "joint_positions": _stack(episode.joint_positions),
            "gripper_qpos": _stack(episode.gripper_qpos),
            "actions": _stack(episode.actions),
            "rewards": np.asarray(episode.rewards, dtype=np.float32),
        }
        for name, positions in recorded.object_positions.items():
            arrays[f"object__{name}"] = _stack(positions)
        np.savez_compressed(arrays_dir / f"{episode_index:04d}.npz", **arrays)

        index.append(
            {
                "episode_index": episode_index,
                "task_name": task_result.task_info.name,
                "instruction": recorded.instruction,
                "episode_id": episode.episode_id,
                "success": bool(episode.success),
                "collided": bool(episode.collided),
                "total_steps": int(episode.total_steps),
                "elapsed_time_sec": float(episode.elapsed_time_sec),
                "frame_count": recorded.frame_count,
                "seed": recorded.seed,
            }
        )

    (output_dir / "episodes.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info(
        "記録を書き出しました: %d エピソード -> %s", len(index), output_dir
    )


def _make_host_writable(output_dir: Path, output_root: Path) -> None:
    """出力一式を、コンテナの外からも消せる権限にする。

    **eval イメージは root で動く**（採点環境と同じ条件を保つため）。そのまま
    書くと、ホスト側では root 所有のファイルが残り、sudo 無しでは消せなくなる。
    実際に学習の出力でそれが起きて、消すために root のコンテナを立てる羽目になった。

    所有者は変えられない（変えるには特権が要る）ので、**誰でも書ける権限にして
    後始末できるようにする**。評価の出力は作り直せるものなので、この扱いでよい。
    """
    if os.geteuid() != 0:
        return
    writable_for_all = stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO
    # **親ディレクトリも開ける。** ディレクトリの中身を消すには、その
    # ディレクトリ自身ではなく**親**への書き込み権限が要る。出力先だけを
    # 開けても、ホスト側からはその出力先を消せない（実際にそうなった）。
    for path in [output_root, output_dir, *output_dir.rglob("*")]:
        try:
            os.chmod(path, writable_for_all)
        except OSError:
            logger.debug("権限を変えられませんでした: %s", path)


def _print_summary(result: Any, output_dir: Path) -> None:
    print("\n" + "=" * 60)
    print(f"提出ID: {result.submission_id}")
    print(f"合計時間: {result.total_elapsed_sec:.1f}秒")
    for track_score in result.track_scores:
        print(f"\n  {track_score.track.value}: 総合スコア {track_score.overall_score:.3f}")
        for task_score in track_score.task_scores:
            print(f"    {task_score.task_name}: {task_score.success_rate:.1%}")
    print(f"\n記録: {output_dir}")
    print("=" * 60)


def main() -> None:
    args = _parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    from pipeline.config import Track
    from pipeline.pipeline import EvaluationPipeline

    output_dir: Path = args.output_root / args.run_name
    output_dir.mkdir(parents=True, exist_ok=True)

    inner_policy, submission_id, policy_kind = _build_policy(args)
    recording_policy = RecordingPolicy(
        inner_policy=inner_policy,
        frames_root=None if args.no_frames else output_dir / "frames",
    )

    pipeline = EvaluationPipeline(eval_config=_build_eval_config(args, output_dir))
    captured_task_results = _install_result_capture(pipeline)

    # 採点側は提出物の検証を飛ばすときも置き場を要求するので、空の入れ物を渡す。
    submission_dir = output_dir / "_submission"
    submission_dir.mkdir(parents=True, exist_ok=True)

    result = pipeline.run(
        submission_dir=submission_dir,
        policy=recording_policy,
        tracks=[Track.TRACK1],
        submission_id=submission_id,
        benchmark_override=args.benchmark,
        skip_validation=True,
    )

    (output_dir / "run_meta.json").write_text(
        json.dumps(
            {
                "policy_kind": policy_kind,
                "server_url": args.server_url,
                "submission_id": submission_id,
                "benchmark": args.benchmark,
                "n_episodes": args.n_episodes,
                "max_steps": args.max_steps,
                "seed": args.seed,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    _write_records(output_dir, captured_task_results, recording_policy.episodes)
    _make_host_writable(output_dir, args.output_root)
    _print_summary(result, output_dir)


if __name__ == "__main__":
    main()
