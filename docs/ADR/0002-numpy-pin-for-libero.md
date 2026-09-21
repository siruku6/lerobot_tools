# numpy を 1.26.4 に固定し、venv を LIBERO 側 / lerobot 側の 2 つに分ける

## 背景

numpy 2.0 では dtype の型昇格規則（NEP 50）が変わった。LIBERO / robosuite は
この規則の変更を前提にしておらず、numpy 2.x 系で動かすと、エラーにはならないまま
物理シミュレータが作る観測値（dtype）が numpy 1.x 系のときと**静かにずれる**。
インストールも実行も失敗しないため、原因が numpy のバージョンだと気付きにくい。

一方 lerobot v0.6.0 は `numpy>=2.0.0,<2.3.0` を要求する。つまり LIBERO 側
（`numpy==1.26.4` 固定）と lerobot 側は、**同じ venv には同居できない。**

## 決定

- LIBERO / mujoco / robosuite が動く venv（`/opt/venv-libero`、python 3.10）の numpy は
  **`NUMPY_VERSION=1.26.4` に固定する。** 上げない。
- LeRobot 形式のデータを触る venv（`/opt/venv-lerobot`、python 3.12）とは**分ける**。
  どちらも PATH には入れず、`$LIBERO_PYTHON` / `$LEROBOT_PYTHON` を明示して呼ぶ
  （取り違えを防ぐため）。2 つの venv は互いを知らず、受け渡しはファイルシステムで行う。

## 影響

- **良い面**: LIBERO / robosuite が想定していない dtype 昇格規則（NEP 50）の下で
  動いてしまい、評価結果がサイレントにずれるという、気付きにくい種類の事故を防げる。
- **悪い面**:
  - numpy を LIBERO / robosuite 側の対応と無関係に単体で上げられない。上げる場合は、
    LIBERO / robosuite 側が numpy 2.x の昇格規則に対応しているかを先に確認する手間が生じる。
  - venv が 2 つに分かれるため、`work` image のディスク使用量が増える
    （lerobot 側の venv だけでも 8〜13GB）。

---

## 追記（2026-09-21）: venv を分けるのではなく image を分けた

上の決定のうち「numpy を 1.26.4 に固定する」は変えていない。**分け方を変えた。**

### 何が分かったか

調べ直したところ、前提が 2 つ間違っていた。

1. **python 3.10 は LIBERO の要求ではなかった。** 採点環境がそうだから合わせていた
   だけで、LIBERO 一式（mujoco / robosuite / gym / bddl）は python 3.12 にも入り、
   import も通る（実測）。動かせないのは lerobot 側の `requires-python >= 3.12`
   のほうである。
2. **lerobot は numpy 1.26.4 でも動く。** `numpy>=2.0.0` という宣言を
   `--no-deps` で解決器に渡さなければよい。提出物は vendoring で同じことをしている。
   LeRobot 形式への変換（`create` / `add_frame` / `save_episode` / `finalize` /
   読み直し）が numpy 1.26.4 で通ることを実測した。

### 変えた決定

venv を 2 つ持つ image を作るのをやめ、**役割ごとに image を 3 つに分けた。
どの image にも venv は 1 つだけある。**

| image | python | numpy | 何をするか |
|---|---|---|---|
| `eval` | 3.10 | 1.26.4 | 採点環境の再現。評価する |
| `datagen` | 3.12 | 1.26.4 | シミュレータを回し、LeRobot 形式に変換する |
| `train` | 3.12 | 2.2.6 | LeRobot 形式のデータで学習する |

`datagen` では LIBERO 一式と lerobot が同じ venv に同居する。データ作りの 3 段
（課題定義 → シミュレータ → 形式変換）のうち、**どの段も両方を import しない**ため、
同居させても取り違えは起きない。

### なぜ変えたか

前の決定は「同居できない」ことを venv の分割で解いたが、その結果 1 つの image に
venv が 2 つ入り、**どちらが何のためにあるのかが名前から読めなくなった。**
`$LIBERO_PYTHON` / `$LEROBOT_PYTHON` の使い分けも、呼ぶ側が覚える負担だった。

image を役割で分ければ venv は 1 つで済み、`python` を PATH に置ける。
迷う余地が無くなる。

### 影響

- **良い面**: どの image も venv が 1 つなので、取り違えが起こりえない。
  採点環境の `evaluate.sh` が呼ぶ素の `python` / `pip` も、`eval` でそのまま動く。
- **悪い面**:
  - `datagen` では lerobot を `--no-deps` で入れるため、**lerobot 自身の依存宣言が
    効かない。** 迂回した分は `envs/datagen/pyproject.toml` に自分で並べて持つ。
    lerobot を上げるときは、そちらも突き合わせる必要がある
    （`av` を版指定なしで入れて import が壊れた実例がある）。
  - LIBERO 一式が `eval` と `datagen` の両方に入るため、その分ディスクを使う。
    役割の明確さを優先した結果である。
