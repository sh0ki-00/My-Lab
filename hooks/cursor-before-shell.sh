#!/usr/bin/env bash
# hooks/cursor-before-shell.sh — Cursor の beforeShellExecution 接続口。
# 入力: 標準入力の JSON（command、cwd ほか）。
# 出力: {"permission":"allow|ask|deny","user_message":"...","agent_message":"..."}。常に JSON を出す（空の出力は Cursor が拒否と扱う）。
#
# 既定は ask（確認）。Cursor で ask が効かないと実機で分かったら、社長が ~/.cursor/company-guard.mode に deny と書く。
# deny の設定では、承認が要る操作はすべて拒否し、先頭に社長の合図 APPROVE_GIT=1 が付いたコマンドだけを通す。
# 引数 --global: Mac 全体の登録から呼ばれたとき。プロジェクト自身が同じ接続口を登録していれば、文を省いて判定だけ返す。
set -u
# shellcheck source=hooks/lib.sh
. "$(dirname "$0")/lib.sh"

GLOBAL=0; [ "${1:-}" = "--global" ] && GLOBAL=1
input="$(cat)"
cmd="$(json_get command "$input")"
root="$(project_root "$input")"

mode="${COMPANY_GUARD_CURSOR_MODE:-}"
[ -n "$mode" ] || mode="$(tr -d '[:space:]' < "$HOME/.cursor/company-guard.mode" 2>/dev/null || true)"
[ "$mode" = "deny" ] || mode="ask"
signal="deny"; [ "$mode" = "deny" ] && signal="honor"

if [ -z "$cmd" ]; then printf '{"permission":"allow"}\n'; exit 0; fi

line="$(bash "$HOOKS_DIR/guard-core.sh" --signal "$signal" -- "$cmd")"
decision="${line%%$'\t'*}"; reason="${line#*$'\t'}"
if [ "$decision" = "ask" ] && [ "$mode" = "deny" ]; then
  decision="deny"
  reason="$reason この Cursor では確認が効かないため拒否する。社長が先頭に APPROVE_GIT=1 を付けて実行する。"
fi
log "cursor before-shell $decision $reason"

if [ "$GLOBAL" = 1 ] && project_registers "$root" cursor-before-shell.sh; then
  printf '{"permission":%s}\n' "$(json_str "$decision")"
  exit 0
fi
case "$decision" in
  allow) agent="$reason" ;;
  ask)   agent="$reason 社長の承認を待つ。拒否されたら、成果物のパスを報告して止まる。" ;;
  *)     agent="$reason 止まって、成果物のパスと止まった理由を社長に報告する。" ;;
esac
printf '{"permission":%s,"user_message":%s,"agent_message":%s}\n' \
  "$(json_str "$decision")" "$(json_str "$reason")" "$(json_str "$agent")"
exit 0
