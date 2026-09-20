# docker build 実行時の「標準出力の見た目」を統一するための関数群
#    - stepスクリプト: envs/scripts/steps/*.sh
#
# Usage
# ------
#   . "$(dirname "$0")/../lib/log.sh"
#
# Effect
# ------
# log.sh を実行すると、呼び出し側のスクリプトから step() / info() / ok() / die() などの
# 関数を呼べるようになる


# _log_tag: ログ各行の先頭につける識別子。LOG_TAG環境変数があればそれを使い、
# 無ければ呼び出し元スクリプトのファイル名（拡張子.shを除いたもの）を使う。
_log_tag="${LOG_TAG:-$(basename "${0%.sh}")}"


# 1. 工程の区切りを示す見出しを1行出す
step() { printf '\n=== [%s] %s ===\n' "$_log_tag" "$*"; }

# 2. 処理の途中経過を1行出す
info() { printf '[%s]   %s\n' "$_log_tag" "$*"; }

# 3. 処理が完了を伝える出力
ok()   { printf '[%s]   OK   %s\n' "$_log_tag" "$*"; }

# 4. 事後条件が既に満たされていたため、何もせず飛ばしたことを1行で伝える
skip() { printf '[%s]   SKIP %s（事後条件を満たしている）\n' "$_log_tag" "$*"; }

# 5. エラー発生時に「エラー内容」と「対処すべきこと」を出力する
die() {
    printf '\n[%s] ERROR: %s\n' "$_log_tag" "${1:-}" >&2
    [ $# -gt 1 ] && printf '[%s]        -> %s\n' "$_log_tag" "$2" >&2
    exit 1
}

# 6. 処理に必要な環境変数が空でないことを確かめる。stepの冒頭で使う。
#    例: require_env DATA_ROOT なら、$DATA_ROOT が空でないことを確認し、
#        空ならエラーで止める。
require_env() {
    for _v in "$@"; do
        eval "_val=\${$_v:-}"
        [ -n "$_val" ] || die "環境変数 $_v が設定されていません" \
            "versions.env を読み込むか、--build-arg $_v=... を渡してください"
    done
}
