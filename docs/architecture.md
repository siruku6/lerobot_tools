# lerobot_tools のアーキテクチャ

このリポジトリの内部構造・ディレクトリ構成・バージョンの変え方・開発時の決まりごとをまとめる。
「使ってみたい」だけなら [README.md](../README.md) で足りる。ここは**改修する側**向けの資料。

## 目次

- [1. データ層](#1-データ層)
- [2. image を 3 つに分けている理由](#2-image-を-3-つに分けている理由)
  - [2.1 なぜ eval を分けるのか](#21-なぜ-eval-を分けるのか)
  - [2.2 なぜ datagen を分けるのか](#22-なぜ-datagen-を分けるのか)
  - [2.3 なぜ train を分けるのか](#23-なぜ-train-を分けるのか)
  - [2.4 python と numpy が image ごとに違う理由](#24-python-と-numpy-が-image-ごとに違う理由)
- [3. 構成](#3-構成)
  - [3.1 image は 3 つ あって venv はそれぞれ 1 つ](#31-image-は-3-つ-あって-venv-はそれぞれ-1-つ)
- [4. バージョンを変える](#4-バージョンを変える)
- [5. 直すときの決まりごと](#5-直すときの決まりごと)

---

## 1. データ層

データ層全体の図と、共有 image に何を置くかの判断基準は
[README.md の 3. 仕組み](../README.md#3-仕組み) を参照。ここでは、そこに含めていない
実装レベルの話を補足する。

LIBERO は起動時に、アセットや bddl ファイルなど自分が読むべきパスの一覧を `config.yaml`
という設定ファイルから読む。この `config.yaml` も**データ image の中に格納してある**
（LIBERO のデフォルトである `$HOME/.libero` には書かない）。理由（`$HOME` に書くと何が
困るか）は [ADR/0003-libero-config-in-image.md](ADR/0003-libero-config-in-image.md) を参照。

## 2. image を 3 つに分けている理由

**役割ごとに 1 つずつ置いてある。どの image にも venv は 1 つしかない。**

| image | python | numpy | 何をするか |
|---|---|---|---|
| `eval` | 3.10 | 1.26.4 | 採点環境の再現。評価する |
| `datagen` | 3.12 | 1.26.4 | シミュレータを回し、LeRobot 形式に変換する |
| `train` | 3.12 | 2.2.6 | LeRobot 形式のデータで学習する |

venv が 1 つなので `python` を PATH に置いてある。どれを呼ぶか迷う余地が無い。

### 2.1 なぜ eval を分けるのか

**採点環境と同一であること自体が目的**だからである。python 3.10 / CUDA 13 の
ベース / pip での固定という条件は、速さや行儀の良さのために崩してよいものではない。
手順を変えると、再現しているものが別物になる。

`eval` には何も足さない。足した瞬間に「採点環境と同じ」と言えなくなる。

### 2.2 なぜ datagen を分けるのか

データ作りは 3 段ある。

1. `_016_make_reverse.py` 逆向きの課題定義と初期状態を作る（LIBERO）
2. `gripper_shift_sweep.py` シミュレータを回して `.npz` を書く（LIBERO）
3. `npz_to_lerobot.py` `.npz` を LeRobot 形式にする（lerobot）

1・2 は libero と robosuite しか import せず、3 は lerobot しか import しない。
**どの段も両方を要求しない**ので、1 つの venv に両方が在っても取り違えは起きない。

numpy が 1.26.4 なのは、**作ったデータを評価が読み直すから**である。numpy 2 で
dtype の昇格規則（NEP 50）が変わり、同じコードが違う値を返しうる。物理シミュレータが
作る観測にそれが混ざると、静かにずれたデータが出来上がる。

lerobot は `numpy>=2.0.0` を宣言しているので、普通に入れると numpy が上がる。
`--no-deps` で入れて宣言を解決器に渡さないことで numpy を守っている。
**迂回した分の依存は `pyproject.toml` に自分で並べてある。**

### 2.3 なぜ train を分けるのか

numpy が違う（`datagen` は評価に合わせて 1.26.4、`train` はこれまで学習に
使ってきた 2.2.6）。役割も違う（あちらは作る側、ここは使う側）。

`train` は LIBERO を使わない。データを読むだけでシミュレータを動かさないので、
libero-data image のマウントも要らない。

### 2.4 python と numpy が image ごとに違う理由

- `eval` の python 3.10 は**採点環境がそうだから**である。LIBERO の都合ではない
  （LIBERO 一式は 3.12 でも入り、import も通ることを実測した）
- `datagen` と `train` の python 3.12 は **lerobot v0.6.0 の要求**で、動かせない
- `datagen` の numpy 1.26.4 は、**作ったデータを評価が読み直すから**である。
  numpy 2 で dtype の昇格規則（NEP 50）が変わり、同じコードが違う値を返しうる
- `train` の numpy 2.2.6 は、**これまで学習に使ってきたバージョン**である

## 3. 構成

```
versions.env            データ image を決める git の ref。**python のバージョンは書かない**
envs/.env               マシンごとに違う設定と秘密情報（gitignore 済み。雛形は .env.example）
datactl.sh              入口。タグの計算と compose の呼び出しを閉じ込めてある
envs/                   **環境を作るものは全部ここ**
  compose.yaml          用途コンテナ。データ層のマウントはここ 1 箇所
  common/               **複数の image が使う**
    lib/                log.sh（docker build時の標準出力の見た目を揃える）と
                        guard.sh（処理が既に完了しているかを確認する）
    steps/              apt_sim_deps.sh / apt_video_deps.sh / register_npp.sh /
                        venv_uv.sh
  data/                 **データ専用 image だけが使う**
    Dockerfile
    steps/              LIBERO の取得、アセットの展開、設定の書き出し
  eval/                 **採点環境の再現 image だけが使う**
    Dockerfile
    requirements.txt    バージョンはここ。採点環境と同じく pip で入れる
    steps/venv.sh
  datagen/              **データを作る image だけが使う**
    Dockerfile
    base/pyproject.toml torch 系と numpy。**先に入れて、後から動かさない**
    pyproject.toml      それ以外のバージョンはここ
    steps/              lerobot を --no-deps で入れた取りこぼしを検査する
  train/                **学習 image だけが使う**
    Dockerfile
    base/pyproject.toml torch 系と numpy。**先に入れて、後から動かさない**
    pyproject.toml      それ以外のバージョンはここ
src/                    **環境の上で走る処理**（上の図を参照）
```

**環境を作るものは `envs/` の下に閉じてある。** 環境の上で走る処理は
`src/` にある（[../src/README.md](../src/README.md)）。

```
src/
  application/          入口。引数を受け、処理を組み立てて実行する
    train_smolvla.py      SmolVLA を LoRA で追加学習する
  domain/               判断のもとになる知識。自分では何も起動しない
    training_schedule.py  学習率の時間変化と、事故った組み合わせの検出
```

`envs/` の中は**どの image が使うか**で分かれている。ディレクトリ名がそのまま
使い手の名前になっていて、`train/` の下にあるものは train image でしか使わない。
複数の image が使うものだけが `common/` に置いてある。

### 3.1 image は 3 つ あって venv はそれぞれ 1 つ

| image | python | numpy | 何をするか |
|---|---|---|---|
| `eval` | 3.10 | 1.26.4 | 採点環境の再現。評価する |
| `datagen` | 3.12 | 1.26.4 | シミュレータを回し、LeRobot 形式に変換する |
| `train` | 3.12 | 2.2.6 | LeRobot 形式のデータで学習する |

**どの image にも venv は 1 つしかない。** そのため `python` を PATH に置いてある。
どれを呼ぶか迷う余地が無い。

python と numpy が image ごとに違う理由は
[2.4 python と numpy が image ごとに違う理由](#24-python-と-numpy-が-image-ごとに違う理由) に書いた。

## 4. バージョンを変える

**python のパッケージのバージョンは、それを使う image の依存定義ファイルを直す。**

| image | 直す先 |
|---|---|
| `eval` | `envs/eval/requirements.txt` |
| `datagen` | `envs/datagen/pyproject.toml` |
| `train` | `envs/train/pyproject.toml` |

`versions.env` には python のパッケージのバージョンを書かない。**バージョンは image
ごとに違う**ので、共通の場所に置くと `NUMPY_VERSION_DATAGEN` のような名前が増えていき、
どれがどこで使われるのか分からなくなる。

`versions.env` が持つのは、データ image を決める git の ref 3 つだけである。
これらは python のパッケージのバージョンではなく、pyproject では表現できない。

データ image のタグは `LIBERO_PLUS_REF` と `ASSETS_REV` から作られるので、
pin（特定のコミットハッシュにバージョンを固定すること）を変えれば別のタグになり、
古いバージョンもそのまま残る。

```bash
./datactl.sh tag          # いまのバージョンのタグ
./datactl.sh build-data   # 新しいバージョンを焼く
```

`versions.env` は**リポジトリにコミットされている**。バージョンを変えるときは、
このファイルへの変更をそのままコミットすること。

python のパッケージのバージョンは `versions.env` ではなく、各 image の依存定義ファイルに
書いてある。そのうち torch / torchvision / torchcodec / NPP の 4 つは、CUDA の系統
（`cu128` / `cu130`）まで含めて**常にセットで決めなければならない**。崩すと
インストールは成功して実行時に落ちる。理由は
[ADR/0001-torch-stack-pinning.md](ADR/0001-torch-stack-pinning.md) を参照。

## 5. 直すときの決まりごと

結合を小さく保ち、壊れたものが黙って出荷されないようにするための 6 つ。

| # | 決まり | 破るとどうなるか |
|---|---|---|
| 1 | バージョンはそれを使う image の依存定義ファイルに書く | 使う場所から離れると、どの image の話か分からなくなる |
| 2 | 同じバージョンを 2 箇所に書くのは、**食い違ったときに止まる場合だけ** | 黙って片方だけ古くなり、実行時に落ちる |
| 3 | step は自分の事後条件を検査する。**検査するのは本来の要求そのもので、代理の指標で代用しない** | 検査は通るのに実際は壊れている成果物が出る |
| 4 | step は互いを取り込まない（`lib/` を除く） | 1 工程だけ流し直せなくなる |
| 5 | Dockerfile は step を呼ぶだけ。判断を書かない | Docker が使えない環境向けに手順を書き直す羽目になる |
| 6 | Dockerfile の `COPY` は step 1 本ずつ。ディレクトリごとまとめない | 1 秒の step を直すと apt と venv の作り直しまで巻き添えになる |

規約 2 の「止まる場合」とは、たとえば `envs/datagen/base/pyproject.toml` と
`envs/datagen/pyproject.toml` の両方に `torch==2.11.0+cu130` と書いてある状態である。
食い違えば uv が依存の衝突として停止するので、黙ってずれることがない。**逆に、
検査にしか使われない値の複製は禁止する。** そちらは食い違っても誰も気付かない。

規約 3 を破った例が実際にある。NPP の登録 step が「`ldconfig` に名前が出るか」という
代理の指標を検査していたため、CUDA の系統違いを通してしまい、ビルドが完走したのに
実行時に落ちるイメージが出来た（[ADR/0001-torch-stack-pinning.md](ADR/0001-torch-stack-pinning.md)）。
いまは `import torchcodec` そのものを走らせて確かめている。

step の先頭には必ず「入力・出力・事後条件」の 3 行がある。単独で流してよいかは、それを読めば分かる。

事後条件の検査は、**依存定義ファイルの `==` 宣言と、実際に入ったバージョンを
突き合わせる**形にしてある。検査のために別の場所へバージョンを複製しなくて済む。

各 Dockerfile は「重い不変層 → 軽い可変層」の順に並べてある。
docker のレイヤーキャッシュは最初に変わった行より後ろを全部無効にするので、
**触るならなるべく下から**。規約 6 はこれを `COPY` の粒度でも守るという意味である。
共通の step をディレクトリごとまとめて `COPY` すると、最後に呼ぶ 1 秒の step を
直しただけで apt と venv まで作り直しになる（実際に 2 度払った）。
