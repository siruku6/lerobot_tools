# Docker での環境構築

流れを以下に記載する

## 1. Python 環境の準備

- docker コンテナの build (CPU のみの環境)

    ```bash
    $ cd docker/local/
    $ cp .env.example .env

    $ docker compose build
    ```


## 2. Docker 環境へのアクセス

- 以下のコマンドで、 docker コンテナ内に入ることが可能です

    ```bash
    $ docker compose up -d
    $ docker compose exec uv_env bash
    ```

## 3. jupyter へのアクセス

- ローカルマシンで `docker compose up` した場合は、 `localhost:{JUPYTER_PORT}` から jupyter へアクセス可能です
- JUPYTER_PORT は `.env` ファイルに設定されているポート番号です
- password 欄には `demo` と入力すれば利用可能です

## 4. コードの動作に必要なファイルの準備

- `pyproject.toml` をアプリのルートディレクトリにおいてください

    ```bash
    # ルートディレクトリで実行
    cp docker/local/pyproject.toml ./
    ```

- `src/` ディレクトリや `data/` ディレクトリと同階層に `pyproject.toml` が配置されていれば問題ありません。
