#!/usr/bin/env bash
# hooks/cursor-stop.sh — Cursor の stop 接続口。作業を終える前に検証を回す。
# FAIL なら {"followup_message":"..."} を返し、Cursor が続きの指示として送る。
# 通ったら、今のファイルの一覧を tmp/.verify/last-pass.list に残す。次の stop は、消しただけ・名前を変えただけの変更もこれで見つける。
# 上限: loop_count（この hook が続きの指示を出した回数）が 3 に達したら、FAIL のままでも止めて記録に残す。
# 引数 --global: Mac 全体の登録から呼ばれたとき。プロジェクト自身が同じ接続口を登録していれば、重ねて回さない。
set -u
# shellcheck source=hooks/lib.sh
. "$(dirname "$0")/lib.sh"

LIMIT=3
GLOBAL=0; [ "${1:-}" = "--global" ] && GLOBAL=1
input="$(cat)"
status="$(json_get status "$input")"
loop="$(json_get loop_count "$input")"; loop="${loop:-0}"
root="$(project_root "$input")"

done_quiet() { printf '{}\n'; exit 0; }

[ "$status" = "completed" ] || done_quiet
if [ "$GLOBAL" = 1 ] && project_registers "$root" cursor-stop.sh; then done_quiet; fi
if [ "$loop" -ge "$LIMIT" ] 2>/dev/null; then
  log "cursor stop: 続きの指示が上限（$LIMIT 回）。FAIL のまま止める"
  done_quiet
fi
cmd="$(verify_cmd "$root")"
[ -n "$cmd" ] || done_quiet
changed_since_pass "$root" || done_quiet

out="$(cd "$root" && eval "$cmd" 2>&1)"; rc=$?
log "cursor stop rc=$rc ($cmd)"
[ "$rc" -eq 3 ] && log "cursor stop: 回す検証の命令が無い（WARN）。止めずに伝える"
if [ "$rc" -eq 0 ] || [ "$rc" -eq 3 ]; then snapshot_tree "$root"; done_quiet; fi
summary="$(printf '%s\n' "$out" | grep -E '^(FAIL|RESULT:)' | head -20)"
[ -n "$summary" ] || summary="$(printf '%s\n' "$out" | tail -20)"
msg="作業を終える前の検証（${cmd}）が FAIL です。直すのは、この依頼で自分が変えたファイルだけです。範囲外の FAIL（前から落ちている試験、触っていないファイル）は直さず、報告に書いて終えてください。指示されていないファイルは変えません。FAIL のあいだは「完了」と書きません。
$summary"
printf '{"followup_message":%s}\n' "$(json_str "$msg")"
exit 0
