#!/usr/bin/env bash
# hooks/cursor-stop.sh — Cursor の stop の hook。返答の言い換えを書き直させ、作業を終える前に検証を回す。
# 1. 返答の言い換えの印（cursor-after-response.sh が $LAB_ROOT/tmp/.verify/terms-<会話の名前> に書く）があれば、検証より先に
#    {"followup_message":"..."} で書き直させる。印は読んだら消す（古い印を次の依頼に持ち越さない）。
# 2. 検証は lib.sh の end_verify で回す。移した先は、そのセッション（会話）が書いた文書だけを渡す。
#    移した先でも My-Lab でも、何も書いていない会話では回さない。
#    FAIL なら {"followup_message":"..."} を返し、Cursor が続きの指示として送る。
#    通ったら、今のファイルの一覧を tmp/.verify/last-pass.list に残す。次の stop は、消しただけ・名前を変えただけの変更もこれで見つける。
# 上限: loop_count（この hook が続きの指示を出した回数。書き直しと検証の両方）が 3 に達したら、FAIL や語が残っていても止めて記録に残す。
#   Cursor の stop の出力には、利用者の画面に出す欄が無い（followup_message は AI への続きの指示）。そのため、上限で語が残ったことは
#   記録（tmp/.verify/hooks.log）に書くだけで、画面には出せない。改善提案書 12 章の 7（超えたら画面に通知）は、Cursor では満たせない。
# 14 日より古いセッションの記録（tmp/.verify/sessions/）は、ここで消す。
# 引数 --global: Mac 全体の登録から呼ばれたとき。プロジェクト自身が同じ hooks を登録していれば、重ねて回さない。
set -u
# shellcheck source=hooks/lib.sh
. "$(dirname "$0")/lib.sh"

LIMIT=3
GLOBAL=0; [ "${1:-}" = "--global" ] && GLOBAL=1
input="$(cat)"
status="$(json_get status "$input")"
loop="$(json_get loop_count "$input")"; loop="${loop:-0}"
root="$(project_root "$input")"
name="$(session_name "$input")"

done_quiet() { printf '{}\n'; exit 0; }
followup() { printf '{"followup_message":%s}\n' "$(json_str "$1")"; exit 0; }

if [ "$GLOBAL" = 1 ] && project_registers "$root" cursor-stop.sh; then done_quiet; fi
# 返答の言い換えの印は、どの終わり方でも読んで消す
mark="$(terms_mark "$name")"; hits=""
if [ -f "$mark" ]; then hits="$(cat "$mark" 2>/dev/null)"; rm -f "$mark" 2>/dev/null; fi
[ "$status" = "completed" ] || done_quiet
if [ "$loop" -ge "$LIMIT" ] 2>/dev/null; then
  [ -n "$hits" ] && log "cursor stop: 返答の言い換え（$(terms_join "$hits" 1)）が残ったまま、続きの指示が上限（$LIMIT 回）"
  log "cursor stop: 続きの指示が上限（$LIMIT 回）。FAIL のまま止める"
  done_quiet
fi

# 1. 返答の言い換え。検証より先に書き直させる
if [ -n "$hits" ]; then
  words="$(terms_join "$hits" 1)"; repls="$(terms_join "$hits" 2)"
  log "cursor stop: 返答に現場の語の言い換え（${words}）。書き直させる"
  followup "返答に${words}がありました。git の語は言い換えません。${repls}に直して、返答を書き直してください。"
fi

# 2. 作業の終わりの検証
( session_prune "$root" ) >/dev/null 2>&1 || :
if end_verify "$root" "$name"; then
  if [ "$END_RAN" = 1 ]; then
    log "cursor stop rc=$END_RC ($END_CMD)"
    [ "$END_RC" -eq 3 ] && log "cursor stop: 回す検証の命令が無い（WARN）。止めずに伝える"
  fi
  done_quiet
fi
log "cursor stop rc=$END_RC ($END_CMD)"
summary="$(printf '%s\n' "$END_OUT" | grep -E '^(FAIL|RESULT:)' | head -20)"
[ -n "$summary" ] || summary="$(printf '%s\n' "$END_OUT" | tail -20)"
if [ "$END_DOCFAIL" = 1 ]; then
  msg="このセッションで書いた文書の検査（${END_CMD}）が FAIL です。直してから終えてください。
$summary"
else
  msg="作業を終える前の検証（${END_CMD}）が FAIL です。直すのは、この依頼で自分が変えたファイルだけです。範囲外の FAIL（前から落ちている試験、触っていないファイル）は直さず、報告に書いて終えてください。指示されていないファイルは変えません。FAIL のあいだは「完了」と書きません。
$summary"
fi
followup "$msg"
