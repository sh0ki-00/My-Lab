#!/usr/bin/env bash
# hooks/claude-stop.sh — Claude Code の Stop 接続口。作業を終える前に検証を回す。
# FAIL なら {"decision":"block","reason":...} を返し、直すまで終われないようにする。
# 通ったら、今のファイルの一覧を tmp/.verify/last-pass.list に残す。次の Stop は、消しただけ・名前を変えただけの変更もこれで見つける。
# 上限: この hook の指示で続けた回数（stop_hook_active が true のとき）が 3 回に達したら、FAIL のままでも止めて記録に残す。
# 引数 --global: Mac 全体の登録から呼ばれたとき。プロジェクト自身が同じ接続口を登録していれば、重ねて回さない。
set -u
# shellcheck source=hooks/lib.sh
. "$(dirname "$0")/lib.sh"

LIMIT=3
GLOBAL=0; [ "${1:-}" = "--global" ] && GLOBAL=1
input="$(cat)"
sid="$(json_get session_id "$input")"; sid="${sid:-none}"
active="$(json_get stop_hook_active "$input")"
root="$(project_root "$input")"
if [ "$GLOBAL" = 1 ] && project_registers "$root" claude-stop.sh; then exit 0; fi
cmd="$(verify_cmd "$root")"
[ -n "$cmd" ] || exit 0

if [ "$active" = "true" ] && [ "$(stop_count "$sid")" -ge "$LIMIT" ]; then
  log "claude stop: 続きの指示が上限（$LIMIT 回）。FAIL のまま止める"
  stop_count "$sid" reset >/dev/null
  exit 0
fi
[ "$active" = "true" ] || stop_count "$sid" reset >/dev/null
changed_since_pass "$root" || exit 0

out="$(cd "$root" && eval "$cmd" 2>&1)"; rc=$?
log "claude stop rc=$rc ($cmd)"
if [ "$rc" -eq 0 ] || [ "$rc" -eq 3 ]; then
  [ "$rc" -eq 3 ] && log "claude stop: 回す検証の命令が無い（WARN）。止めずに伝える"
  snapshot_tree "$root"
  stop_count "$sid" reset >/dev/null
  exit 0
fi
stop_count "$sid" bump >/dev/null
summary="$(printf '%s\n' "$out" | grep -E '^(FAIL|RESULT:)' | head -20)"
[ -n "$summary" ] || summary="$(printf '%s\n' "$out" | tail -20)"
reason="作業を終える前の検証（${cmd}）が FAIL。直すのは、この依頼で自分が変えたファイルだけ。範囲外の FAIL（前から落ちている試験、触っていないファイル）は直さず、報告に書いて終える。指示されていないファイルは変えない。FAIL のあいだは「完了」と書かない。
$summary"
printf '{"decision":"block","reason":%s}\n' "$(json_str "$reason")"
exit 0
