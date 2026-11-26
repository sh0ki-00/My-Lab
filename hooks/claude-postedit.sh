#!/usr/bin/env bash
# hooks/claude-postedit.sh — Claude Code の PostToolUse（Edit・Write・MultiEdit・NotebookEdit）hooks。
# 直したファイルの検査を tools/check-file.sh で回す。FAIL なら終了コード 2 で結果を Claude に見せる（編集は戻さない）。
# 検査の前に、直したファイルをセッションの記録（tmp/.verify/sessions/<名前>.files）に足す。終わりの検証が、そのセッションの文書だけを見るため。
#   記録は子のシェルで書き、失敗しても検査と終了コードに響かない。
# 引数 --global: Mac 全体の登録から呼ばれたとき。プロジェクト自身が同じ hooks を登録していれば、重ねて回さない。
set -u
# shellcheck source=hooks/lib.sh
. "$(dirname "$0")/lib.sh"

GLOBAL=0; [ "${1:-}" = "--global" ] && GLOBAL=1
input="$(cat)"
tool="$(json_get tool_name "$input")"
case "$tool" in Edit|Write|MultiEdit|NotebookEdit) ;; *) exit 0 ;; esac
file="$(json_get tool_input.file_path "$input")"
[ -n "$file" ] && [ -f "$file" ] || exit 0
root="$(project_root "$input")"
case "$file" in "$root"/*) ;; *) exit 0 ;; esac   # プロジェクトの外のファイル（記憶や他のリポジトリ）は検査しない
if [ "$GLOBAL" = 1 ] && project_registers "$root" claude-postedit.sh; then exit 0; fi
tools="$(tools_dir "$root")"
[ -n "$tools" ] || exit 0
( session_add "$input" "$file" ) >/dev/null 2>&1 || :

result="$(cd "$root" && bash "$tools/check-file.sh" "$file" 2>&1)"; rc=$?
log "claude postedit rc=$rc $file"
if [ "$rc" -ne 0 ]; then
  printf '%s\n' "$result" >&2
  printf 'FAIL: %s の検査が落ちた。直してから進める（tools/check-file.sh <ファイル> で再検査）。\n' "$file" >&2
  exit 2
fi
exit 0
