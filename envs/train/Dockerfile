# 学習のためのイメージ
#
# Usage
# ------
#   ./datactl.sh build train
#   ./datactl.sh up train
#
# Effect
# ------
# venv を 1 つ持つコンテナが出来る。python は PATH に在る。
#
#   /opt/venv   python 3.12 / numpy 2.2.6 / lerobot[training,pi]
#
#
# 何をするためのイメージか
# ------
# LeRobot 形式のデータで学習を回す。データを作るのは datagen イメージで、
# ここはそれを使う側である。
#
# **LIBERO は入らない。** 学習はデータを読むだけで、シミュレータを動かさない。
# そのため libero-data イメージのマウントも要らない。
#
#
# なぜ datagen と分けるのか
# ------
# numpy が違う。datagen は評価と同じ 1.26.4 で揃える必要があるが、
# 学習はこれまで 2.2.6 で回してきた。役割も違う（作る側と使う側）。
# 詳しくは pyproject.toml の頭に書いてある。
#
#
# なぜ CUDA 入りのベースイメージを使わないのか
# ------
# pip の torch wheel が CUDA ランタイムを同梱している（実測 2.7GB）。
# CUDA 入りのベースを重ねても二重に持つだけになる。
# GPU の実行に要るドライバ側は nvidia-container-toolkit がホストから注入する。
#
# 唯一の例外が NPP で、これは register_npp.sh が手当てする。
FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV NVIDIA_DRIVER_CAPABILITIES=compute,utility

# ----------------------------------------------------------------------
# 時間のかかる層を先に置く
#
# docker のレイヤーキャッシュは、最初に変わった行より後ろを全部無効にする。
# 変わりやすいものほど下に置くと、作り直しの範囲が狭くなる。
# ----------------------------------------------------------------------
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# 共通の lib と step を入れる。中では /opt/scripts/{lib,steps} に揃うので、
# step 側の `../lib/log.sh` という参照はそのまま効く。
COPY envs/common/lib   /opt/scripts/lib
COPY envs/common/steps /opt/scripts/steps

# torchcodec が FFmpeg の共有ライブラリを dlopen で読む。
# 先に入れておかないと lerobot の import が落ちる。
RUN bash /opt/scripts/steps/apt_video_deps.sh

COPY envs/train/pyproject.toml /opt/env/pyproject.toml
RUN ENV_DIR=/opt/env VENV=/opt/venv UV_PY=3.12 CLEAN_UV_CACHE=1 \
    UV_EXTRA=training \
    bash /opt/scripts/steps/venv_uv.sh

# NPP の場所を動的リンカに教える。venv とは別の RUN にしている。
# 登録自体は 1 秒で終わるが、同じ RUN に入れると失敗のたびに
# venv の作り直しまで巻き添えになるためである。
RUN VENV=/opt/venv bash /opt/scripts/steps/register_npp.sh

# ----------------------------------------------------------------------
# ここから下は変わりやすい層
# ----------------------------------------------------------------------

# venv が 1 つしかないので PATH に置く。python と pip がこの venv を指す。
ENV PATH="/opt/venv/bin:${PATH}"

WORKDIR /work
CMD ["bash"]
