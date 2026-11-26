#!/usr/bin/env bash
# hooks/claude-pretooluse.sh — Claude Code の PreToolUse（Bash）接続口。
# 入力: 標準入力の JSON（tool_name、tool_input.command ほか）。
# 出力: 判定が ask か deny のとき hookSpecificOutput の JSON。allow のときは何も出さず、通常の権限の流れに任せる。
# 引数 --global: Mac 全体の登録から呼ばれたとき。プロジェクト自身が同じ接続口を登録していれば、理由を省いて判定だけ返す
#               （2 つの登録が重なっても、確認の文が 2 回出ないようにする。判定は厳しい方が勝つ）。
# セッションの始まりの印（tmp/.verify/sessions/<名前>.start）も置く。終わりの検証の範囲に使い、判定には使わない。
#   子のシェルで置き、失敗しても判定に響かない。
set -u
# shellcheck source=hooks/lib.sh
. "$(dirname "$0")/lib.sh"

GLOBAL=0; [ "${1:-}" = "--global" ] && GLOBAL=1
input="$(cat)"
( session_mark "$input" ) >/dev/null 2>&1 || :
tool="$(json_get tool_name "$input")"
[ "$tool" = "Bash" ] || exit 0
cmd="$(json_get tool_input.command "$input")"
[ -n "$cmd" ] || exit 0
root="$(project_root "$input")"
export COMPANY_GUARD_PROJECT_ROOT="$root"   # 判定本体が、My-Lab の中の相対パス（hooks/ ほか）を見分けるのに使う
# 判定本体が、commit 文などのファイル（-F の相対パス）を、命令の作業場所から読むのに使う。入力に cwd が無ければ空（root から読む）
COMPANY_GUARD_CWD="$(json_get cwd "$input")"; export COMPANY_GUARD_CWD

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
