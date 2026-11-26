#!/usr/bin/env bash
# hooks/cursor-after-edit.sh — Cursor の afterFileEdit 接続口。
# 直したファイルの検査を tools/check-file.sh で回し、結果を tmp/.verify/last-edit.txt に残す。
# Cursor はこの hook の出力を読まないので、FAIL は stop の接続口が「続きの指示」として伝える。終了コードは常に 0。
# 検査の前に、直したファイルをセッションの記録（tmp/.verify/sessions/<会話の名前>.files）に足す。終わりの検証が、その会話の文書だけを見るため。
#   記録は子のシェルで書き、失敗しても検査に響かない。
# 引数 --global: Mac 全体の登録から呼ばれたとき。プロジェクト自身が同じ接続口を登録していれば、重ねて回さない。
set -u
# shellcheck source=hooks/lib.sh
. "$(dirname "$0")/lib.sh"

GLOBAL=0; [ "${1:-}" = "--global" ] && GLOBAL=1
input="$(cat)"
file="$(json_get file_path "$input")"
[ -n "$file" ] && [ -f "$file" ] || exit 0
root="$(project_root "$input")"
case "$file" in "$root"/*) ;; *) exit 0 ;; esac   # プロジェクトの外のファイルは検査しない
if [ "$GLOBAL" = 1 ] && project_registers "$root" cursor-after-edit.sh; then exit 0; fi
tools="$(tools_dir "$root")"
[ -n "$tools" ] || exit 0
( session_add "$input" "$file" ) >/dev/null 2>&1 || :

result="$(cd "$root" && bash "$tools/check-file.sh" "$file" 2>&1)"; rc=$?
mkdir -p "$LAB_ROOT/tmp/.verify" 2>/dev/null || true
{
  printf '%s %s rc=%s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$file" "$rc"
  printf '%s\n' "$result"
} > "$LAB_ROOT/tmp/.verify/last-edit.txt" 2>/dev/null || true
log "cursor after-edit rc=$rc $file"
exit 0
