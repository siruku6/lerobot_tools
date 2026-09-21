# src/ — 環境の上で走る処理

`envs/` が環境を作るもの、ここがその環境の中で動くものである。

```
src/
├── application/          入口。コマンドライン引数を受け、処理を組み立てて実行する
│   └── train_smolvla.py    SmolVLA を LoRA で追加学習する
└── domain/               判断のもとになる知識。入口から呼ばれるだけで、自分では何も起動しない
    └── training_schedule.py  学習率の時間変化と、過去に事故を起こした組み合わせの検出
```

## どの image で動かすか

| script | image | 起動の仕方 |
|---|---|---|
| `application/train_smolvla.py` | train | `./datactl.sh up train python /work/src/application/train_smolvla.py` |

リポジトリはコンテナの `/work` に見えている。`--dry-run` を付けると、
組み立てた `lerobot-train` のコマンドを表示して実行せずに終わる。

## 設定値の出どころ

**`train_smolvla.py` の既定値は自分で選んだものではない。** 移行元のリポジトリ
（PARC2026_pre。このリポジトリが環境構築を引き継いだ、ロボット操作のコンペ用の
リポジトリ）の `solution/train/train.py` が本番スコア 0.1409 を出したときの
組み合わせを写してある。

**学習率まわりだけは 1 組として扱う。** 別々の出典から値を混ぜると、
どの出典も認めていない組み合わせが出来る。実際にそれで本番スコアが
0.1409 から 0.016 へ落ちた記録があり、`domain/training_schedule.py` が
実行前に検出して伝える。経緯は
[../docs/ADR/0005-training-schedule-must-come-as-a-set.md](../docs/ADR/0005-training-schedule-must-come-as-a-set.md)。
