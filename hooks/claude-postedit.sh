#!/usr/bin/env bash
# hooks/claude-postedit.sh — Claude Code の PostToolUse（Edit・Write・MultiEdit・NotebookEdit）接続口。
# 直したファイルの検査を tools/check-file.sh で回す。FAIL なら終了コード 2 で結果を Claude に見せる（編集は戻さない）。
# 引数 --global: Mac 全体の登録から呼ばれたとき。プロジェクト自身が同じ接続口を登録していれば、重ねて回さない。
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

result="$(cd "$root" && bash "$tools/check-file.sh" "$file" 2>&1)"; rc=$?
log "claude postedit rc=$rc $file"
if [ "$rc" -ne 0 ]; then
  printf '%s\n' "$result" >&2
  printf 'FAIL: %s の検査が落ちた。直してから進める（tools/check-file.sh <ファイル> で再検査）。\n' "$file" >&2
  exit 2
fi
exit 0
