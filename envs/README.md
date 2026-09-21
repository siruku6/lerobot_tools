# envs/ — 環境を作るもの

ディレクトリ名がそのまま、それを使う image の名前になっている。
`common/` だけが複数の image から使われる。

```
envs/
├── compose.yaml         3 つの用途 image の起動定義
│
├── common/              ← data・eval・datagen・train が使う
│   ├── lib/
│   │   ├── log.sh           出力の見た目を揃える
│   │   └── guard.sh         処理が済んでいるかを確かめる
│   └── steps/
│       ├── apt_sim_deps.sh      GL / EGL / ImageMagick   （eval・datagen）
│       ├── apt_video_deps.sh    FFmpeg                   （datagen・train）
│       ├── register_npp.sh      NPP を動的リンカに登録    （datagen・train）
│       └── venv_uv.sh           uv で venv を作る         （datagen・train）
│
├── data/                → libero-data:<ref>
│   ├── Dockerfile
│   └── steps/               LIBERO の取得・アセット展開・設定の書き出し
│
├── eval/                → lerobot-tools-eval
│   ├── Dockerfile
│   ├── requirements.txt     バージョンはここ（pip）
│   └── steps/venv.sh
│
├── datagen/             → lerobot-tools-datagen
│   ├── Dockerfile
│   ├── base/
│   │   └── pyproject.toml   torch 系と numpy。先に入れて後から動かさない
│   ├── pyproject.toml       それ以外のバージョンはここ（uv）
│   └── steps/check_lerobot_deps.sh
│
└── train/               → lerobot-tools-train
    ├── Dockerfile
    ├── base/
    │   └── pyproject.toml   torch 系と numpy。先に入れて後から動かさない
    └── pyproject.toml       それ以外のバージョンはここ（uv）
```

## image ごとの違い

| | eval | datagen | train |
|---|---|---|---|
| 何をするか | 採点環境の再現。評価 | シミュレータを回し、LeRobot 形式に変換 | LeRobot 形式で学習 |
| ベース | `nvidia/cuda:13.0.3-cudnn-devel` | `python:3.12-slim` | `python:3.12-slim` |
| python | 3.10 | 3.12 | 3.12 |
| numpy | 1.26.4 | 1.26.4 | **2.2.6** |
| torch | 2.11.0+cu130 | 2.11.0+cu130 | 2.11.0+**cu128** |
| NPP | （torchcodec 無し） | `nvidia-npp`（so.13） | `nvidia-npp-cu12`（so.12） |
| 入れ方 | pip | uv | uv |
| **LIBERO** | **在り**（マウント） | **在り**（マウント） | **無し** |
| **lerobot** | 無し | **在り**（`--no-deps`） | **在り**（`[training,pi]`） |
| libero-data のマウント | する | する | **しない** |
| サイズ | 22.6GB | 12.4GB | 13.9GB |

どの image も venv は `/opt/venv` の 1 つだけで、`python` と `pip` は PATH に在る。

## バージョンが image ごとに違う理由

- **eval の python 3.10** は採点環境がそうだから。LIBERO の都合ではない
  （LIBERO 一式は 3.12 でも動くことを実測した）
- **datagen・train の python 3.12** は lerobot v0.6.0 の `requires-python >= 3.12`。動かせない
- **datagen の numpy 1.26.4** は、作ったデータを評価が読み直すから。numpy 2 で
  dtype の昇格規則（NEP 50）が変わり、同じコードが違う値を返しうる
- **train の numpy 2.2.6** は、これまで学習に使ってきたバージョン
- **NPP のパッケージ名**は torch の CUDA 系統で決まる。cu130 の torchcodec は
  `libnppicc.so.13` を要求し、それを配布しているのは接尾辞の無い `nvidia-npp` である。
  cu128 なら `.so.12` で `nvidia-npp-cu12`。**間違えるとインストールは成功して
  torchcodec の import 時に落ちる**（[../docs/ADR/0001-torch-stack-pinning.md](../docs/ADR/0001-torch-stack-pinning.md)）

lerobot は `numpy>=2.0.0` を宣言しているので、datagen では `--no-deps` で入れて
宣言を解決器に渡さない。**そのぶん lerobot の依存宣言がすべて効かなくなる**ので、
必要な依存は `datagen/pyproject.toml` に自分で並べてある。
抜けは `datagen/steps/check_lerobot_deps.sh` がビルド時に捕まえる。

## LIBERO のデータはどこに在るか

アセット 9.5GB は `libero-data` image だけが持つ。eval と datagen は、それを
読み取り専用で `/opt/libero` に重ねて使う。**コピーは起きないので、コンテナを
何本立てても実体は 1 つのまま**である。マウントの定義は `compose.yaml` の
`x-libero-data` 1 箇所にしかない。

train は LIBERO を使わないので、このマウントもしない。

## バージョンを変えるとき

python のパッケージのバージョンは、それを使う image のファイルを直す。

| image | 直す先 |
|---|---|
| eval | `eval/requirements.txt` |
| datagen | torch 系と numpy は `datagen/base/pyproject.toml`、それ以外は `datagen/pyproject.toml` |
| train | torch 系と numpy は `train/base/pyproject.toml`、それ以外は `train/pyproject.toml` |

**torch / torchvision / torchcodec / NPP の 4 つは、CUDA の系統まで含めて常にセットで
決める。** これらは `base/pyproject.toml` と `pyproject.toml` の両方に同じ `==` を
書いてある。食い違えば uv が依存の衝突として止まるので、黙ってずれることはない。

`versions.env`（リポジトリ直下）にはパッケージのバージョンを書かない。持っているのは
データ image を決める git の ref 3 つだけである。

詳しい背景は [../docs/architecture.md](../docs/architecture.md) と
[../docs/ADR/](../docs/ADR/) にある。
