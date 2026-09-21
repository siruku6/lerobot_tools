# torch / torchvision / torchcodec / NPP を CUDA 系統ごと対で固定する

## 背景

`torchcodec` は LeRobot が動画の読み書きに使うライブラリである。これがビルド上の依存を
宣言していないにもかかわらず、内部では `torch` の ABI（バイナリインターフェース）へ
直接リンクしている。そのため `pip` は `torch` と `torchcodec` のバージョンが噛み合って
いるかを検出できない。噛み合っていない組み合わせでも
**`pip install` 自体は成功し、実行時（import 時や推論時）に初めて壊れる。**

`torch` の wheel は CUDA のメジャーバージョンごとに別のパッケージ index
（`cu128` / `cu130` など）で配布されている。2 系統を同じ venv に入れると、後から
入れた側が cuDNN 等の共有ライブラリを上書きし、先に入れてあった側が壊れる。

### NPP も同じ組の一員である

`torchcodec` は CUDA の NPP（画像・色空間変換ライブラリ）へも直接リンクしており、
GPU デコードを使わない呼び出しでも import 時に読み込まれる。この NPP には 2 つの罠がある。

**1 つ目。`pip install` するだけでは動的リンカが見つけられない。**
`torch` が使う CUDA ライブラリは `torch` 自身が import 時に `site-packages/nvidia/*/lib`
を明示的に preload するため見つかるが、**NPP はその preload の対象リストに無い。**
`ldconfig` にディレクトリを教える必要がある（`envs/common/steps/register_npp.sh`）。

**2 つ目。NPP のパッケージは torch と同じ CUDA 系統を選ばなければならない。**
`cu128` の `torchcodec` は `libnppicc.so.12` を、`cu130` の `torchcodec` は
`libnppicc.so.13` を要求する。そしてパッケージ名の付け方が系統で違う。

| torch の系統 | 必要な共有ライブラリ | PyPI のパッケージ名 |
|---|---|---|
| `cu128` | `libnppicc.so.12` | `nvidia-npp-cu12` |
| `cu130` | `libnppicc.so.13` | `nvidia-npp`（接尾辞が付かない） |

`nvidia-npp-cu13` という名前のパッケージも PyPI に存在するが、中身が無く
インストールに失敗する（2026-09-21 に確認）。名前から類推して選ぶと外れる。

**実際に壊れたイメージが出来た（2026-09-21）。** `datagen` イメージは torch を `cu130`
にしてあるのに `nvidia-npp-cu12` を入れていた。`pip install` は成功し、`docker build` も
完走したが、出来たイメージで `import torchcodec.decoders` すると
`libnppicc.so.13: cannot open shared object file` で落ちた。
**`register_npp.sh` の事後条件がこれを見逃した**ことが、壊れたまま出荷された原因である。
当時の事後条件は「`ldconfig -p` の出力に `libnppicc` という文字列が出るか」であり、
系統違いの `.so.12` でもこれを満たしてしまった。
**本来の要求（torchcodec が import できること）ではなく、その代理の指標を見ていた。**

## 決定

- **`torch` / `torchvision` / `torchcodec` / NPP の 4 つは常にセットで決める。**
  CUDA の系統（`cu128` / `cu130`）もこのセットに含まれる。
  組み合わせは LeRobot が指定するバージョンの `uv.lock` が解決したものに合わせる。
- **バージョンは、それを使う image の依存定義ファイルに書く**
  （`envs/datagen/base/pyproject.toml`、`envs/train/base/pyproject.toml`、
  `envs/eval/requirements.txt`）。image ごとに CUDA の系統と numpy が違うため、
  1 つのファイルに集約すると分岐が必要になり、かえって間違いやすい。
  `versions.env` に残しているのは git の commit hash だけである。
- **同じ venv に 2 つの CUDA 系統を混ぜない。** image を分けることで実現している。
- **`register_npp.sh` の事後条件は、実際に `import torchcodec.decoders` を走らせて
  確かめる。** 代理の指標（`ldconfig -p` に名前が出るか）で代用しない。
  要求される共有ライブラリの名前は `ldd` で torchcodec のコアの ELF から読み取り、
  決め打ちしない。手元にあるものと食い違っていれば、両方の名前を出して止まる。

## 影響

- **良い面**: `pip install` が通ったのに実行時にだけ壊れる（torch/torchcodec の ABI
  不一致、CUDA 系統の混在による cuDNN 上書き、NPP の系統違い）という、
  原因の特定に時間がかかる種類の事故が `docker build` の時点で止まる。
  NPP については、系統を変えたときに `register_npp.sh` を直す必要もない。
- **悪い面**: 4 つを常にセットで管理する必要があり、`torch` を単体で気軽に上げられない。
  上げるときは 4 つ揃え、NPP はパッケージ名まで変わりうることを確認する手間が生じる。
  また事後条件で `torch` を import するため、この step の実行が 1 秒から数秒に伸びる。
