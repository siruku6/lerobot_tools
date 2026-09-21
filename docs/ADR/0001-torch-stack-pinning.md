# torch / torchcodec / torchvision と CUDA index を対で固定する

## 背景

`torchcodec` はビルド上の依存を宣言していないが、内部では `torch` の ABI（バイナリ
インターフェース）へ直接リンクしている。そのため `pip` は `torch` と `torchcodec` の
バージョンが噛み合っているかを検出できない。噛み合っていない組み合わせでも
**`pip install` 自体は成功し、実行時（import 時や推論時）に初めて壊れる。**

さらに `torchcodec` は CUDA の NPP（画像・色空間変換ライブラリ）へ直接リンクしており、
GPU デコードを使わない呼び出しでも import 時に読み込まれる（詳細は
`envs/work/steps/register_npp.sh` 参照）。これも動的リンカに個別の対応
（`ldconfig` への登録）が要る。

また `torch` の wheel は CUDA のメジャーバージョンごとに別のパッケージ index
（`cu128` / `cu130` など）で配布されている。複数の用途（評価・学習）で使う index を
同じ venv に入れると、後から入れた側が cuDNN 等の共有ライブラリを上書きし、
先に入れてあった側が壊れる。

## 決定

- `TORCH_VERSION` / `TORCHCODEC_VERSION` / `TORCHVISION_VERSION` は
  **常に 3 つセットで決め、`versions.env` にしか書かない。**
  組み合わせは LeRobot が指定するバージョン（`LEROBOT_TAG`）の `uv.lock` が
  解決したものに合わせる。
- 評価用と学習用で `torch` の CUDA index を分ける（`TORCH_INDEX_EVAL` /
  `TORCH_INDEX_TRAIN`）。評価は採点イメージと同じ `cu130`、学習は LeRobot の
  `uv.lock` が解決する `cu128`。
- **同じ venv にこの 2 系統を混ぜない。**

## 影響

- **良い面**: `pip install` が通ったのに実行時にだけ壊れる（torch/torchcodec の ABI
  不一致、評価/学習の CUDA index 混在による cuDNN 上書き）という、原因の特定に
  時間がかかる種類の事故を防げる。
- **悪い面**: `TORCH_VERSION` / `TORCHCODEC_VERSION` / `TORCHVISION_VERSION` の
  3 つを常にセットで管理する必要があり、torch を単体で気軽に上げられない。
  上げるときは必ず 3 つ揃え、`LEROBOT_TAG` が指定する `uv.lock` の組み合わせと
  合っているかまで確認する手間が生じる。
