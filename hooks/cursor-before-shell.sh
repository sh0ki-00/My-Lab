#!/usr/bin/env bash
# hooks/cursor-before-shell.sh — Cursor の beforeShellExecution 接続口。
# 入力: 標準入力の JSON（command、cwd ほか）。
# 出力: {"permission":"allow|ask|deny","user_message":"...","agent_message":"..."}。常に JSON を出す（空の出力は Cursor が拒否と扱う）。
#
# 既定は ask（確認）。Cursor で ask が効かないと実機で分かったら、社長が ~/.cursor/company-guard.mode に deny と書く。
# deny の設定では、承認が要る操作をすべて拒否する。合図の語 APPROVE_GIT=1 が付いていても通さない。
# この接続口に来る命令の文字列は AI が書くので、合図で通すと AI の自己承認になる。社長は hooks の掛からない自分の端末で実行する。
# 引数 --global: Mac 全体の登録から呼ばれたとき。プロジェクト自身が同じ接続口を登録していれば、文を省いて判定だけ返す。
set -u
# shellcheck source=hooks/lib.sh
. "$(dirname "$0")/lib.sh"

GLOBAL=0; [ "${1:-}" = "--global" ] && GLOBAL=1
input="$(cat)"
cmd="$(json_get command "$input")"
root="$(project_root "$input")"

# 設定の読み方は lib.sh の guard_mode。root 所有の置き場があればそれだけを使い、壊れていれば deny に倒す。無ければ ~/.cursor を読む
guard_mode
mode="$GUARD_MODE"

if [ -z "$cmd" ]; then printf '{"permission":"allow"}\n'; exit 0; fi

export COMPANY_GUARD_PROJECT_ROOT="$root"   # 判定本体が、My-Lab の中の相対パス（hooks/ ほか）を見分けるのに使う
line="$(bash "$HOOKS_DIR/guard-core.sh" --signal deny -- "$cmd")"
decision="${line%%$'\t'*}"; reason="${line#*$'\t'}"
if [ "$decision" = "ask" ] && [ "$mode" = "deny" ]; then
  decision="deny"
  reason="$reason この Cursor では確認が効かないため拒否する。${GUARD_MODE_WHY:+$GUARD_MODE_WHY }社長が自分の端末で実行する。"
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
