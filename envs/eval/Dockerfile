# 採点環境を再現するためのイメージ
#
# Usage
# ------
#   ./datactl.sh build eval
#   ./datactl.sh up eval
#
# Effect
# ------
# 採点環境と同じ顔ぶれの venv を 1 つ持つコンテナが出来る。
#
#   /opt/venv   python 3.10 / numpy 1.26.4 / torch 2.11.0+cu130
#
# LIBERO のデータ（アセット 9.5GB）はこのイメージに入らない。libero-data
# イメージを読み取り専用で重ねて使う（envs/compose.yaml を参照）。
#
# 評価のコード（evaluate.py や pipeline/）もこのイメージに入らない。
# このイメージが提供するのは環境だけで、コードはマウントして持ち込む。
#
#
# なぜ work と分けるのか
# ------
# 採点環境と同一であること自体が、このイメージの目的だからである。
# python 3.10 / CUDA 13 ベース / pip での固定 / numpy 1.26.4 という条件は、
# work 側（python 3.12 / numpy 2.x / uv）と両立しない。
#
# 速さや行儀の良さを理由に手順を変えると、再現しているものが別物になる。
#
#
# なぜ CUDA 入りのベースイメージを使うのか
# ------
# work 側では、pip の torch wheel が CUDA を同梱するので CUDA 入りのベースは
# 要らないと書いた。ここではその判断を採らない。採点環境がこのベースを
# 使っているためである。技術的な必然ではなく、一致させることが目的である。
FROM nvidia/cuda:13.0.3-cudnn-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV MUJOCO_GL=egl
ENV NVIDIA_DRIVER_CAPABILITIES=compute,utility,graphics

# ----------------------------------------------------------------------
# 時間のかかる層を先に置く
# ----------------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.10 python3.10-venv python3.10-dev python3-pip \
        build-essential cmake git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 共通の lib と step、このイメージ専用の step を、同じ場所へ重ねて入れる。
# 中では /opt/scripts/steps と /opt/scripts/lib に揃うので、
# step 側の `../lib/log.sh` という参照はそのまま効く。
# 共通の lib と step、このイメージ専用の step を、同じ場所へ重ねて入れる。
# apt_sim_deps.sh は common 側に在る（datagen も使うため）。
# **step は 1 本ずつ COPY する（ディレクトリごとまとめない）。**
# docker のレイヤーキャッシュは、COPY した内容が変わるとその行より後ろを
# 全部無効にする。まとめて COPY すると、最後に呼ぶ 1 秒の step を 1 文字
# 直しただけで apt と venv の作り直し（20 分以上）まで巻き添えになる。
# 実際にそれで 2 度払った。新しい step を足したときに COPY を書き忘れると
# ビルドが exit 127 で落ちるので、黙って間違った成果物が出ることはない。
COPY envs/common/lib /opt/scripts/lib
COPY envs/common/steps/apt_sim_deps.sh /opt/scripts/steps/
COPY envs/eval/steps /opt/scripts/steps
RUN bash /opt/scripts/steps/apt_sim_deps.sh

COPY envs/eval/requirements.txt /opt/env/requirements.txt
RUN VENV=/opt/venv REQ=/opt/env/requirements.txt \
    bash /opt/scripts/steps/venv.sh

# ----------------------------------------------------------------------
# ここから下は変わりやすい層
# ----------------------------------------------------------------------

# venv が 1 つしかないので PATH に置く。python と pip がこの venv を指す。
# 採点環境の evaluate.sh が素の `python` と `pip` を呼ぶため、
# ここを揃えておかないとその手順が動かない。
ENV PATH="/opt/venv/bin:${PATH}"

# LIBERO の設定は libero-data イメージに焼いたものを使う。
# LIBERO_CONFIG_PATH があるので $HOME には何も書かれない。
ENV LIBERO_CONFIG_PATH=/opt/libero/config
ENV LIBERO_ROOT=/opt/libero/LIBERO-plus
ENV PYTHONPATH=/opt/libero/LIBERO-plus

WORKDIR /work
CMD ["bash"]
