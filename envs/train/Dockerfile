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
# **step は 1 本ずつ COPY する（ディレクトリごとまとめない）。**
# docker のレイヤーキャッシュは、COPY した内容が変わるとその行より後ろを
# 全部無効にする。まとめて COPY すると、最後に呼ぶ 1 秒の step を 1 文字
# 直しただけで apt と venv の作り直し（20 分以上）まで巻き添えになる。
# 実際にそれで 2 度払った。新しい step を足したときに COPY を書き忘れると
# ビルドが exit 127 で落ちるので、黙って間違った成果物が出ることはない。
COPY envs/common/lib /opt/scripts/lib

# torchcodec が FFmpeg の共有ライブラリを dlopen で読む。
# 先に入れておかないと lerobot の import が落ちる。
COPY envs/common/steps/apt_video_deps.sh /opt/scripts/steps/
RUN bash /opt/scripts/steps/apt_video_deps.sh

# **1 段目: 土台（torch 系と numpy）。**
# 下の pyproject.toml を直してもこの層は生き残る。COPY の位置が
# キャッシュの境目になるため、変わりにくいものを先に置いている。
COPY envs/common/steps/venv_uv.sh /opt/scripts/steps/
COPY envs/train/base/pyproject.toml /opt/env/base/pyproject.toml
RUN ENV_DIR=/opt/env/base VENV=/opt/venv UV_PY=3.12 CLEAN_UV_CACHE=1 \
    bash /opt/scripts/steps/venv_uv.sh

# **2 段目: 残り。** こちらの pyproject.toml にも torch と numpy の固定を
# 書いてあるので、この解決は 1 段目のバージョンを動かせない（base と対にすること）。
COPY envs/train/pyproject.toml /opt/env/pyproject.toml
RUN ENV_DIR=/opt/env VENV=/opt/venv CLEAN_UV_CACHE=1 \
    bash /opt/scripts/steps/venv_uv.sh

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

WORKDIR /work
CMD ["bash"]
