#!/usr/bin/env bash
# hooks/claude-pretooluse.sh — Claude Code の PreToolUse（Bash）接続口。
# 入力: 標準入力の JSON（tool_name、tool_input.command ほか）。
# 出力: 判定が ask か deny のとき hookSpecificOutput の JSON。allow のときは何も出さず、通常の権限の流れに任せる。
# 引数 --global: Mac 全体の登録から呼ばれたとき。プロジェクト自身が同じ接続口を登録していれば、理由を省いて判定だけ返す
#               （2 つの登録が重なっても、確認の文が 2 回出ないようにする。判定は厳しい方が勝つ）。
set -u
# shellcheck source=hooks/lib.sh
. "$(dirname "$0")/lib.sh"

GLOBAL=0; [ "${1:-}" = "--global" ] && GLOBAL=1
input="$(cat)"
tool="$(json_get tool_name "$input")"
[ "$tool" = "Bash" ] || exit 0
cmd="$(json_get tool_input.command "$input")"
[ -n "$cmd" ] || exit 0
root="$(project_root "$input")"

line="$(bash "$HOOKS_DIR/guard-core.sh" --signal deny -- "$cmd")"
decision="${line%%$'\t'*}"; reason="${line#*$'\t'}"
log "claude pretooluse $decision $reason"
[ "$decision" = "allow" ] && exit 0

if [ "$GLOBAL" = 1 ] && project_registers "$root" claude-pretooluse.sh; then
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":%s}}\n' "$(json_str "$decision")"
else
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":%s,"permissionDecisionReason":%s}}\n' \
    "$(json_str "$decision")" "$(json_str "$reason")"
fi
exit 0
