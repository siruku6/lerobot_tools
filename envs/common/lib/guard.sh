# ある処理が既に正しく完了しているかを、確認するための関数群
#
# Usage
# ------
#   . "$(dirname "$0")/../lib/guard.sh"
#
# Effect
# ------
# guard.sh を実行すると、呼び出し側のスクリプトから
# count_files() / have_files() / have_all() / git_head_is() / clone_pinned() などの
# 関数を呼べるようになる
#
# これらの関数は、特定の処理の実行結果が期待通りかを確認するために用いられたり、
# ある処理を実行する前に、既にその処理が完了しているかを確認するために用いられる。


# count_files <dir> → 直下のファイル又はディレクトリ数（dir そのものが無ければ 0）を返す
count_files() {
    [ -d "$1" ] || { echo 0; return; }
    find "$1" -mindepth 1 -maxdepth 1 | wc -l | tr -d ' '
}

# have_files <dir> <最小個数> → 満たしていれば 0 を返す
have_files() {
    [ "$(count_files "$1")" -ge "$2" ]
}

# have_all <path...> → 指定したファイル/ディレクトリが全部存在すれば 0 を返す
have_all() {
    for _p in "$@"; do [ -e "$_p" ] || return 1; done
    return 0
}

# git_head_is <root_dir> <commit> → そのリポジトリの HEAD が指定された commit なら 0 を返す
git_head_is() {
    [ -d "$1/.git" ] || return 1
    [ "$(git -C "$1" rev-parse HEAD 2>/dev/null)" = "$2" ]
}

# clone_pinned <root_dir> <url> <commit>
# 指定されたリポジトリを commit hash 指定で depth 1 で取得する。
# **git clone --depth 1 は ref (branch 名など) しか受け付けない**ため、
# commit hash を直接指定して clone するために、 `git init` + `git fetch` で取得する
clone_pinned() {
    _dir="$1"; _url="$2"; _ref="$3"
    if git_head_is "$_dir" "$_ref"; then
        skip "$_dir は既に $_ref"
        return 0
    fi
    [ -e "$_dir" ] && die "$_dir は、指定された commit hash ではありません" \
        "$_dir を削除してからこの step のスクリプトを実行し直すか、指定した commit hash（$_ref）が正しいか確かめてください"
    git init -q "$_dir"
    git -C "$_dir" remote add origin "$_url"
    git -C "$_dir" fetch -q --depth 1 origin "$_ref"
    git -C "$_dir" checkout -q FETCH_HEAD
    ok "$_dir を $_ref で取得"
}

# ldconfig_has <名前> → 動的リンカが探せる共有ライブラリにその名前があれば 0 を返す
#
# **`ldconfig -p | grep -q <名前>` と書いてはいけない。** grep -q は最初の一致で即座に
# 終了するため、まだ出力を書いている途中の ldconfig が SIGPIPE で死に、set -o pipefail の
# 下では**登録されているのに「無い」と判定される。** 実際に docker build を落とした。
# → docs/ADR/0004-no-early-exit-grep-under-pipefail.md
# 出力を変数に受けてから照合すればパイプが無くなり、この競合は起きない。
ldconfig_has() {
    _ld="$(ldconfig -p 2>/dev/null || true)"
    case "$_ld" in (*"$1"*) return 0 ;; (*) return 1 ;; esac
}
