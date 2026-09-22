"""評価の記録を読み、成否・映像・軌道・行動の推移として wandb に送る。

evaluate_libero.py が /outputs 以下に書いたものを読んで、人が見て判断できる形に
変える。**評価そのものは行わない**（GPU もシミュレータも要らない）。

なぜ評価と別のスクリプト・別のイメージなのか
--------------------------------------------
評価は eval イメージで動く。このイメージは採点環境と同じ顔ぶれを保つことが目的で、
wandb を入れると requests・psutil・protobuf といった共有の依存が動きうる。
そのため評価側はファイルを書くだけにして、送信は io イメージが受け持っている。

4 つの見せ方は、それぞれ違う問いに答える
----------------------------------------
    表        どれを見るべきか（並べ替え・絞り込みの入口）
    映像      何が起きたか
    3D 軌道   毎回どこで外しているか（複数エピソードを重ねられる）
    2D 推移   行動の出力がどう壊れているか（飽和・振動・把持のタイミング）

Usage
-----
    ./datactl.sh up io python /work/src/application/visualize_eval_wandb.py \
        --run-dir /outputs/eval/wiring_check --wandb-run-name wiring_check

Reads:
  - <run-dir>/run_meta.json      **何で回したか**（ポリシーの種類）
  - <run-dir>/episodes.json      エピソード一覧
  - <run-dir>/arrays/*.npz       軌道
  - <run-dir>/frames/*/*.jpg     映像のもと
  - <run-dir>/*.json             採点結果（pipeline が書いたもの）
Generates:
  - wandb の run（表・動画・点群・折れ線）
  - <--video-dir>/*.mp4          送信のために作った動画

**動画は評価の出力先には書かない。** 評価は eval イメージが root で動くため
（採点環境と同じ条件を保つため）、その出力先は root 所有になる。こちらは
ホストのユーザーで動くので書き込めない。既定では一時ディレクトリに作る。
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger("visualize_eval_wandb")

# 動画の再生速度。LIBERO の制御周波数（既定 20Hz）に合わせると実時間になる。
VIDEO_FPS = 20

# 行動ベクトル 7 次元の並び。LIBERO の OSC コントローラの入力である。
ACTION_LABELS = (
    "x", "y", "z", "roll", "pitch", "yaw", "gripper",
)


# wandb のパネル名の上限。折れ線グラフは内部で「run-<id>-<パネル名>_table」という
# 名前の成果物を作り、その名前が 128 文字を超えると送信そのものが失敗する
# （実測: LIBERO のタスク名は 1 つで 90 文字を超える）。
MAX_TASK_LABEL_LENGTH = 24


def _task_label(task_name: str, task_index: int) -> str:
    """パネル名に使う、短いタスクの呼び名を作る。

    LIBERO のタスク名は「pick_up_the_black_bowl_in_the_top_drawer_of_the_...」の
    ように長く、そのままパネル名に入れると wandb 側の名前の上限を超えて送信が失敗する。
    **順番を表す番号を先頭に置く**ので、短く切っても取り違えは起きない。
    元の名前は表（eval/episodes）の task_name 列に残る。
    """
    return f"t{task_index}_{task_name[:MAX_TASK_LABEL_LENGTH]}"


def _load_run_meta(run_dir: Path) -> dict[str, Any]:
    """評価を何で回したかを読む。

    evaluate_libero.py が書く run_meta.json には、ランダムポリシー（配線の確認用）
    かポリシーサーバーかが入っている。**この値を wandb の config に載せる**ので、
    後から run を見たときに、その数字がどちらのものか分かる。

    無い場合は unknown として扱う（古い出力を読めるようにするため）。
    """
    path = run_dir / "run_meta.json"
    if not path.exists():
        logger.warning("%s が無いため、ポリシーの種類は unknown として記録します", path)
        return {"policy_kind": "unknown"}
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="評価の記録を wandb へ送る")
    parser.add_argument("--run-dir", type=Path, required=True, help="評価の出力先")
    parser.add_argument("--wandb-run-name", default=None, help="wandb 上の run 名")
    parser.add_argument(
        "--group",
        default=None,
        help="wandb のグループ名。学習の run 名を入れると並べて見られる",
    )
    parser.add_argument(
        "--train-run-id", default=None, help="評価した重みを作った学習 run の id"
    )
    parser.add_argument(
        "--video-dir",
        type=Path,
        default=None,
        help="作った動画の置き場（既定は一時ディレクトリ）",
    )
    parser.add_argument(
        "--videos-per-task",
        type=int,
        default=2,
        help="タスクあたりに送る動画の本数（成功と失敗を 1 本ずつ優先する）",
    )
    parser.add_argument(
        "--charts-per-task",
        type=int,
        default=1,
        help="タスクあたりに送る行動推移グラフの本数",
    )
    return parser.parse_args()


def _load_episodes(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "episodes.json"
    if not path.exists():
        raise SystemExit(
            f"{path} がありません。evaluate_libero.py の出力先を指しているか確かめてください"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _load_score_document(run_dir: Path) -> dict[str, Any] | None:
    """pipeline が書いた採点結果を読む。

    ファイル名は提出 ID で決まるため決め打ちできない。episodes.json と
    自分が作ったもの以外の JSON を 1 つ拾う。
    """
    for path in sorted(run_dir.glob("*.json")):
        if path.name == "episodes.json":
            continue
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def _encode_video(frames_dir: Path, output_path: Path) -> Path | None:
    """連番の JPEG を、ブラウザが再生できる H.264 の mp4 に固める。

    wandb の動画プレイヤーは H.264 を要求する。これを満たさない形式でも
    ファイルは出来てしまい、**再生できずに黒いまま**になる。
    """
    frames = sorted(frames_dir.glob("*.jpg"))
    if not frames:
        return None
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg", "-nostdin", "-loglevel", "error", "-y",
        "-framerate", str(VIDEO_FPS),
        "-i", str(frames_dir / "%05d.jpg"),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        str(output_path),
    ]
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode != 0:
        logger.warning("動画の符号化に失敗しました（%s）: %s", frames_dir, completed.stderr.strip())
        return None
    return output_path


def _select_for_media(
    episodes: list[dict[str, Any]], limit: int
) -> list[dict[str, Any]]:
    """タスクごとに、代表として送るエピソードを選ぶ。

    **失敗を先に選ぶ。** 見たいのは大抵うまくいかなかった方であり、
    全部成功していれば結果的に成功が選ばれる。
    """
    if limit <= 0:
        return []
    failures = [e for e in episodes if not e["success"]]
    successes = [e for e in episodes if e["success"]]
    selected: list[dict[str, Any]] = []
    for pool in (failures[:1], successes[:1], failures[1:], successes[1:]):
        for episode in pool:
            if len(selected) < limit and episode not in selected:
                selected.append(episode)
    return selected


def _trajectory_point_cloud(
    arrays: dict[str, np.ndarray], success: bool
) -> np.ndarray:
    """手先の軌道と、観測に写っていた物体の位置を 1 つの点群にする。

    点の色で 2 つのことを示す。**成功は緑、失敗は赤**で、時間が進むほど明るくする。
    物体は白で、動かないので 1 点だけ置く。

    Returns
    -------
    points : np.ndarray
        (N, 6) の配列。列は x, y, z, r, g, b（色は 0-255）。
    """
    positions = arrays["ee_positions"]
    if positions.size == 0:
        return np.zeros((0, 6), dtype=np.float32)

    step_count = len(positions)
    brightness = np.linspace(60, 255, step_count, dtype=np.float32)
    colors = np.zeros((step_count, 3), dtype=np.float32)
    colors[:, 1 if success else 0] = brightness

    points = [np.hstack([positions[:, :3], colors])]

    for key, values in arrays.items():
        if not key.startswith("object__") or values.size == 0:
            continue
        first_position = np.asarray(values[0], dtype=np.float32).reshape(1, 3)
        white = np.full((1, 3), 255.0, dtype=np.float32)
        points.append(np.hstack([first_position, white]))

    return np.vstack(points).astype(np.float32)


def _log_summary(wandb_run: Any, score_document: dict[str, Any] | None) -> None:
    if score_document is None:
        return
    for track in score_document.get("tracks", []):
        prefix = f"eval/{track['track']}"
        wandb_run.summary[f"{prefix}/overall_score"] = track["overall_score"]
        for name, value in track.get("overall_metrics", {}).items():
            wandb_run.summary[f"{prefix}/{name}"] = value
        for task in track.get("tasks", []):
            wandb_run.summary[f"{prefix}/success_rate/{task['task_name']}"] = (
                task["success_rate"]
            )


def _log_episode_table(wandb_module: Any, wandb_run: Any, episodes: list[dict[str, Any]]) -> None:
    columns = [
        "episode_index", "task_label", "task_name", "success", "collided",
        "total_steps", "elapsed_time_sec", "instruction",
    ]
    table = wandb_module.Table(columns=columns)
    task_names = sorted({episode["task_name"] for episode in episodes})
    for episode in episodes:
        labelled = dict(episode)
        labelled["task_label"] = _task_label(
            episode["task_name"], task_names.index(episode["task_name"])
        )
        table.add_data(*[labelled[column] for column in columns])
    wandb_run.log({"eval/episodes": table})


def _log_media_per_task(
    wandb_module: Any,
    wandb_run: Any,
    run_dir: Path,
    video_dir: Path,
    episodes: list[dict[str, Any]],
    videos_per_task: int,
    charts_per_task: int,
) -> None:
    task_names = sorted({episode["task_name"] for episode in episodes})
    for task_index, task_name in enumerate(task_names):
        label = _task_label(task_name, task_index)
        task_episodes = [e for e in episodes if e["task_name"] == task_name]
        payload: dict[str, Any] = {}

        point_clouds = []
        for episode in task_episodes:
            arrays = dict(
                np.load(run_dir / "arrays" / f"{episode['episode_index']:04d}.npz")
            )
            point_clouds.append(_trajectory_point_cloud(arrays, episode["success"]))
        stacked = [cloud for cloud in point_clouds if cloud.size]
        if stacked:
            payload[f"eval/trajectory/{label}"] = wandb_module.Object3D(
                np.vstack(stacked)
            )

        for episode in _select_for_media(task_episodes, videos_per_task):
            frames_dir = run_dir / "frames" / f"{episode['episode_index']:04d}"
            if not frames_dir.exists():
                continue
            video_path = _encode_video(
                frames_dir, video_dir / f"{episode['episode_index']:04d}.mp4"
            )
            if video_path is None:
                continue
            outcome = "成功" if episode["success"] else "失敗"
            payload[f"eval/video/{label}/ep{episode['episode_id']}"] = (
                wandb_module.Video(str(video_path), caption=outcome, format="mp4")
            )

        for episode in _select_for_media(task_episodes, charts_per_task):
            arrays = dict(
                np.load(run_dir / "arrays" / f"{episode['episode_index']:04d}.npz")
            )
            actions = arrays["actions"]
            if actions.size == 0:
                continue
            steps = list(range(len(actions)))
            payload[f"eval/actions/{label}/ep{episode['episode_id']}"] = (
                wandb_module.plot.line_series(
                    xs=steps,
                    ys=[actions[:, i].tolist() for i in range(actions.shape[1])],
                    keys=list(ACTION_LABELS[: actions.shape[1]]),
                    title=f"{label} ep{episode['episode_id']} の行動出力",
                    xname="step",
                )
            )

        if payload:
            wandb_run.log(payload)


def main() -> None:
    args = _parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    import wandb

    run_dir: Path = args.run_dir
    episodes = _load_episodes(run_dir)
    score_document = _load_score_document(run_dir)
    meta = _load_run_meta(run_dir)

    # **評価は学習とは別の run にする。** 学習の run に相乗りすると、
    # step 軸が学習のものなので混ざる。group で並べて見る。
    wandb_run = wandb.init(
        name=args.wandb_run_name or run_dir.name,
        group=args.group,
        job_type="eval",
        config={
            "eval_run_dir": str(run_dir),
            "n_episodes": len(episodes),
            # **何で回したかを残す。** ランダムポリシー（配線の確認）と
            # ポリシーサーバー（重みの成績）を、後から区別できるようにするため。
            "policy_kind": meta.get("policy_kind", "unknown"),
            "server_url": meta.get("server_url"),
            "train_run_id": args.train_run_id,
        },
    )

    _log_summary(wandb_run, score_document)
    _log_episode_table(wandb, wandb_run, episodes)
    video_dir: Path = args.video_dir or Path(tempfile.mkdtemp(prefix="eval_videos_"))
    video_dir.mkdir(parents=True, exist_ok=True)
    _log_media_per_task(
        wandb, wandb_run, run_dir, video_dir, episodes,
        args.videos_per_task, args.charts_per_task,
    )

    logger.info("送信しました: %s", wandb_run.url)
    wandb_run.finish()


if __name__ == "__main__":
    main()
