# データを作るためのイメージ
#
# Usage
# ------
#   ./datactl.sh build datagen
#   ./datactl.sh up datagen
#
# Effect
# ------
# venv を 1 つ持つコンテナが出来る。python は PATH に在る。
#
#   /opt/venv   python 3.12 / numpy 1.26.4 / LIBERO 一式 ＋ lerobot
#
# LIBERO のデータ（アセット 9.5GB）はこのイメージに入らない。libero-data
# イメージを読み取り専用で重ねて使う（envs/compose.yaml を参照）。
#
#
# 何をするためのイメージか
# ------
# データ作りの 3 段すべてをここで回す。
#
#   1. 逆向きの課題定義と初期状態を作る（LIBERO）
#   2. シミュレータを回して .npz を書く（LIBERO）
#   3. .npz を LeRobot 形式にする（lerobot）
#
# 1 つの venv で足りる理由と、numpy / python のバージョンを選んだ理由は
# pyproject.toml の頭に書いてある。
#
#
# なぜ venv を PATH に置くのか
# ------
# このイメージには venv が 1 つしかないので、python がどれを指すか迷わない。
# eval も同じ理由で 1 つだが、あちらは採点環境の手順に合わせて pip で入れる。
FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV MUJOCO_GL=egl
ENV NVIDIA_DRIVER_CAPABILITIES=compute,utility,graphics

# ----------------------------------------------------------------------
# 時間のかかる層を先に置く
#
# docker のレイヤーキャッシュは、最初に変わった行より後ろを全部無効にする。
# 変わりやすいものほど下に置くと、作り直しの範囲が狭くなる。
# ----------------------------------------------------------------------
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# 共通の lib と step を入れる。中では /opt/scripts/{lib,steps} に揃うので、
# step 側の `../lib/log.sh` という参照はそのまま効く。
#
# **step は 1 本ずつ COPY する（ディレクトリごとまとめない）。**
# docker のレイヤーキャッシュは、COPY した内容が変わるとその行より後ろを
# 全部無効にする。まとめて COPY すると、最後に呼ぶ 1 秒の step を 1 文字
# 直しただけで apt と venv の作り直し（20 分以上）まで巻き添えになる。
# 実際にそれで 2 度払った。新しい step を足したときに COPY を書き忘れると
# ビルドが exit 127 で落ちるので、黙って間違った成果物が出ることはない。
COPY envs/common/lib /opt/scripts/lib

# シミュレータの描画に要る共有ライブラリ（GL / EGL / ImageMagick）
COPY envs/common/steps/apt_sim_deps.sh /opt/scripts/steps/
RUN bash /opt/scripts/steps/apt_sim_deps.sh

# torchcodec が FFmpeg の共有ライブラリを dlopen で読む。
# 先に入れておかないと lerobot の import が落ちる。
COPY envs/common/steps/apt_video_deps.sh /opt/scripts/steps/
RUN bash /opt/scripts/steps/apt_video_deps.sh

# **1 段目: 土台（torch 系と numpy）。**
# 下の pyproject.toml を直してもこの層は生き残る。COPY の位置が
# キャッシュの境目になるため、変わりにくいものを先に置いている。
COPY envs/common/steps/venv_uv.sh /opt/scripts/steps/
COPY envs/datagen/base/pyproject.toml /opt/env/base/pyproject.toml
RUN ENV_DIR=/opt/env/base VENV=/opt/venv UV_PY=3.12 CLEAN_UV_CACHE=1 \
    bash /opt/scripts/steps/venv_uv.sh

# **2 段目: 残り。** こちらの pyproject.toml にも torch と numpy の固定を
# 書いてあるので、この解決は 1 段目のバージョンを動かせない。
COPY envs/datagen/pyproject.toml /opt/env/pyproject.toml
RUN ENV_DIR=/opt/env VENV=/opt/venv CLEAN_UV_CACHE=1 \
    bash /opt/scripts/steps/venv_uv.sh

# **lerobot だけ --no-deps で後から入れる。**
# lerobot は numpy>=2.0.0 を宣言しており、普通に入れると numpy が上がる。
# 宣言を解決器に渡さないことで numpy 1.26.4 を守る。迂回した依存は
# pyproject.toml 側に自分で並べてある（そちらの注記を参照）。
# **uv pip を使う。** uv venv が作る venv には pip が入っていない
# （uv は venv の外から操作する道具なので、中に pip を置かない）。
RUN uv pip install --python /opt/venv/bin/python --no-cache --no-deps "lerobot==0.6.0"

# **--no-deps は lerobot の依存宣言をすべて無効にする。** 足りない分は
# pyproject.toml に並べてあるが、抜けていてもインストールは成功し、
# 落ちるのは実行時である。ここで捕まえる。
COPY envs/datagen/steps /opt/scripts/steps
RUN VENV=/opt/venv bash /opt/scripts/steps/check_lerobot_deps.sh

# NPP の場所を動的リンカに教える。venv とは別の RUN にしている。
# 登録自体は 1 秒で終わるが、同じ RUN に入れると失敗のたびに
# venv の作り直しまで巻き添えになるためである。
COPY envs/common/steps/register_npp.sh /opt/scripts/steps/
RUN VENV=/opt/venv bash /opt/scripts/steps/register_npp.sh

# ----------------------------------------------------------------------
# ここから下は変わりやすい層
# ----------------------------------------------------------------------

# venv が 1 つしかないので PATH に置く。python と pip がこの venv を指す。
ENV PATH="/opt/venv/bin:${PATH}"

# LIBERO の設定は libero-data イメージに焼いたものを使う。
# LIBERO_CONFIG_PATH があるので $HOME には何も書かれない。
ENV LIBERO_CONFIG_PATH=/opt/libero/config
ENV LIBERO_ROOT=/opt/libero/LIBERO-plus
ENV PYTHONPATH=/opt/libero/LIBERO-plus

WORKDIR /work
CMD ["bash"]
