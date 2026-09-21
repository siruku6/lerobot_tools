# 外部サービスとやり取りするためのイメージ
#
# Usage
# ------
#   ./datactl.sh build io
#   ./datactl.sh up io
#
# Effect
# ------
# venv を 1 つ持つコンテナが出来る。python は PATH に在る。
#
#   /opt/venv   python 3.12 / wandb / huggingface_hub / numpy / Pillow
#
#
# 何をするためのイメージか
# ------
# **学習も評価もしない。外との受け渡しだけをする。** 評価が /outputs に書いた
# 軌道とフレームを wandb へ送る、HuggingFace からデータや重みを取る、といった
# 処理を受け持つ。どういう顔ぶれで、なぜ分けてあるかは pyproject.toml の頭に書いた。
#
# GPU を要求しない（compose.yaml の io サービスに deploy: *gpu が無い）。
#
#
# なぜ FFmpeg を入れるのか
# ------
# 評価が撮ったフレームを、**ブラウザが再生できる形式**の動画に固めるため。
# wandb の動画プレイヤーは H.264 を要求し、これを満たさないファイルは
# 再生できずに黒いままになる。apt_video_deps.sh が ffmpeg を入れ、
# H.264 を実際に符号化できることまで確かめる。
#
# **datagen / train と同じ step から入れている。** 動画を書くイメージが複数
# あるので、出所を 1 つに揃えてある（wheel 同梱の ffmpeg を使うと別系統になる）。
FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# 共通の lib と step を入れる。中では /opt/scripts/{lib,steps} に揃うので、
# step 側の `../lib/log.sh` という参照はそのまま効く。
# **step は 1 本ずつ COPY する（ディレクトリごとまとめない）。**
# まとめて COPY すると、1 本直しただけで後ろの層が全部作り直しになる。
COPY envs/common/lib /opt/scripts/lib

# 動画を書くために要る。**venv より先に置く。** apt は変わりにくく、
# pyproject.toml は変わりやすいので、この順なら pyproject を直しても
# apt の層は生き残る。
COPY envs/common/steps/apt_video_deps.sh /opt/scripts/steps/
RUN bash /opt/scripts/steps/apt_video_deps.sh

# **段を分けない。** train や datagen は torch 系を土台として切り離しているが、
# ここに入るのは純粋な python パッケージだけで、後から入れるものに
# 差し替えられて困るものが無い。
COPY envs/common/steps/venv_uv.sh /opt/scripts/steps/
COPY envs/io/pyproject.toml /opt/env/pyproject.toml
RUN ENV_DIR=/opt/env VENV=/opt/venv UV_PY=3.12 CLEAN_UV_CACHE=1 \
    bash /opt/scripts/steps/venv_uv.sh

# ----------------------------------------------------------------------
# ここから下は変わりやすい層
# ----------------------------------------------------------------------

# venv が 1 つしかないので PATH に置く。python と pip がこの venv を指す。
ENV PATH="/opt/venv/bin:${PATH}"

WORKDIR /work
CMD ["bash"]
