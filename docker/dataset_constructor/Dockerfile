# Docker image
FROM nvidia/cuda:13.0.3-cudnn-devel-ubuntu24.04

ENV DEBIAN_FRONTEND=noninteractive
ENV MUJOCO_GL=egl
# https://zenn.dev/40_comeback_eng/articles/0d7f10e0ff7089
ENV PYTHONUNBUFFERED 1
ENV NVIDIA_DRIVER_CAPABILITIES=compute,utility,graphics

ARG WORKING_DIRECTORY
WORKDIR /${WORKING_DIRECTORY}

RUN ln -sf /usr/share/zoneinfo/Asia/Tokyo /etc/localtime

RUN apt update && apt install -y --no-install-recommends \
    # For development and debug (procps: `free -h`)
    cmake curl git wget net-tools vim procps zip unzip ca-certificates\
    # Necessary for pip install
    gcc g++ libc-dev \
    \
    python3.12 python3.12-venv python3-pip python3.12-dev \
    bzip2 \
    build-essential \
    ca-certificates \
    # For cv2 / grad-cam
    libopencv-dev \
    # For lerobot, training and so on.
    # mujoco / robosuite の GL 系
    libosmesa6 libosmesa6-dev \
    libgl1 libglfw3 libglew-dev \
    libegl1 \
    libsm6 libxext6 libxrender-dev \
    libglib2.0-0 \
    # LIBERO-plus の envs/env_wrapper.py が import する wand が必要とする ImageMagick の共有ライブラリ（libMagickWand）
    libmagickwand-dev \
    && apt clean && rm -rf /var/lib/apt/lists/*

# ----------------------------------------------------------------------
# Prepare uv
# https://docs.astral.sh/uv/guides/integration/docker/#installing-uv
# ----------------------------------------------------------------------
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# ----------------------------------------------------------------------
# Python virtual environment
# ----------------------------------------------------------------------
ENV UV_PROJECT_ENVIRONMENT=/opt/venv
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="${VIRTUAL_ENV}/bin:${PATH}"
RUN uv venv ${VIRTUAL_ENV}

# Prepare packages from pyproject.toml
COPY docker/dataset_constructor/pyproject.toml /${WORKING_DIRECTORY}/pyproject.toml
# COPY docker/dataset_constructor/uv.lock /${WORKING_DIRECTORY}/uv.lock
# /opt/venv に依存関係をインストール
# nvidia 関係のライブラリのインストールに時間がかかるので、待ち時間を 300 sec にしている。
ENV UV_HTTP_TIMEOUT=300
# TODO: RUN uv sync --frozen
RUN uv sync


# # Prepare packages from pyproject.toml
# # https://www.reddit.com/r/learnpython/comments/1hspt62/comment/m5sak3o/?tl=ja
# ENV UV_PROJECT_ENVIRONMENT="/usr/local/"
# RUN uv sync


# ----------------------------------------------------------------------
# LIBERO / lerobot
# ----------------------------------------------------------------------
COPY docker/dataset_constructor/setup-libero.sh /tmp/setup-libero.sh
# COPY docker/dataset_constructor/setup-lerobot.sh /tmp/setup-lerobot.sh
RUN bash /tmp/setup-libero.sh
# RUN bash /tmp/setup-lerobot.sh

# ----------------------------------------------------------------------
# Runtime
# ----------------------------------------------------------------------
ENV PIP_FIND_LINKS=/opt/wheelhouse
ENV PYTHONPATH="/opt/LIBERO-plus:/workspace:/workspace/compe"
ENV LIBERO_ROOT="/opt/LIBERO-plus"

CMD ["bash"]