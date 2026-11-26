#!/usr/bin/env bash
# hooks/claude-stop.sh — Claude Code の Stop の hook。返答の言い換えを見て、作業を終える前に検証を回す。
# 1. 返答に現場の語の言い換え（git のブランチを別の語にするなど）があれば、検証より先に
#    {"decision":"block","reason":...} で書き直させる。判定は lib.sh の terms_check（My-Lab の正本の検査）に任せる。
#    返答は Stop の入力の last_assistant_message から読む。無ければ、会話の記録（transcript_path の JSONL）の最後の返答から読む。
#    鉤括弧の中とバッククォートの中は数えない。python3 か正本が無いときは、数えずに通す。
# 2. 検証は lib.sh の end_verify で回す。移した先は、そのセッションが書いた文書だけを渡す。
#    移した先でも My-Lab でも、Write・Edit で何も書いていないセッションでは回さない。
#    FAIL なら {"decision":"block","reason":...} を返し、直すまで終われないようにする。
#    通ったら、今のファイルの一覧を tmp/.verify/last-pass.list に残す。次の Stop は、消しただけ・名前を変えただけの変更もこれで見つける。
# 上限: この hook の指示で続けた回数（返答の書き直しと検証の差し戻しを合わせて数える）が 3 回に達したら、
#   FAIL や語が残っていても止めて記録に残す。回数は tmp/.verify/stop-count-<session_id> に数える。Cursor の loop_count と同じ数え方。
#   上限で止めるとき、返答に語が残っていれば {"systemMessage":...} で画面に出す（改善提案書 12 章の 7）。
#   新しい依頼の始まり（stop_hook_active が false）と、検証が通ったときと、上限で止めたときに 0 に戻す。
#   stop_hook_active を送らない呼び手（Claude Code 形式の hook を Cursor が回すとき）でも、回数だけで止まる。
#   返答の書き直しの回数を記録できないときは、差し戻し続けないよう、書き直させずに画面に出して検証へ進む。
# 14 日より古いセッションの記録（tmp/.verify/sessions/）は、ここで消す。
# 引数 --global: Mac 全体の登録から呼ばれたとき。プロジェクト自身が同じ hooks を登録していれば、重ねて回さない。
set -u
# shellcheck source=hooks/lib.sh
. "$(dirname "$0")/lib.sh"

LIMIT=3
GLOBAL=0; [ "${1:-}" = "--global" ] && GLOBAL=1
input="$(cat)"
sid="$(json_get session_id "$input")"; sid="${sid:-none}"
name="$(session_name "$input")"
active="$(json_get stop_hook_active "$input")"
root="$(project_root "$input")"
if [ "$GLOBAL" = 1 ] && project_registers "$root" claude-stop.sh; then exit 0; fi

note=""   # 画面に出す注意（systemMessage）。返答の言い換えが、差し戻しの上限のあとも残ったとき
pass_out() {  # 止めずに終える。注意があれば画面に出す
  if [ -n "$note" ]; then printf '{"systemMessage":%s}\n' "$(json_str "$note")"; fi
  exit 0
}
block_out() {  # block_out <理由> → 続けさせる。注意があれば一緒に画面に出す
  if [ -n "$note" ]; then
    printf '{"decision":"block","reason":%s,"systemMessage":%s}\n' "$(json_str "$1")" "$(json_str "$note")"
  else
    printf '{"decision":"block","reason":%s}\n' "$(json_str "$1")"
  fi
  exit 0
}

# 新しい依頼の始まり（stop_hook_active が false）は 0 から数え直す。印の無い呼び手では戻さず、回数だけで止める
[ "$active" = "false" ] && stop_count "$sid" reset >/dev/null

# 1. 返答の言い換え。検証より先に見る
msg="$(json_get last_assistant_message "$input")"
[ -n "$msg" ] || msg="$(transcript_last_reply "$(json_get transcript_path "$input")")"
words=""; repls=""
if [ -n "$msg" ] && hits="$(printf '%s\n' "$msg" | terms_check)"; then
  words="$(terms_join "$hits" 1)"; repls="$(terms_join "$hits" 2)"
fi
if [ "$(stop_count "$sid")" -ge "$LIMIT" ]; then
  log "claude stop: 続きの指示が上限（$LIMIT 回）。FAIL や返答の語が残っていても止める"
  stop_count "$sid" reset >/dev/null
  [ -z "$words" ] || note="返答に${words}が残りました。差し戻しは ${LIMIT} 回までなので、止めずに通します。git の語は言い換えず、${repls}と書きます。"
  pass_out
fi
if [ -n "$words" ]; then
  if stop_count "$sid" bump >/dev/null; then
    log "claude stop: 返答に現場の語の言い換え（${words}）。書き直させる"
    block_out "返答に${words}がありました。git の語は言い換えません。${repls}に直して、返答を書き直してください。"
  fi
  log "claude stop: 返答の書き直しの回数を記録できない。語が残ったことを画面に出して、検証へ進む"
  note="返答に${words}が残りました。差し戻しの回数を記録できないので、書き直させずに通します。git の語は言い換えず、${repls}と書きます。"
fi

# 2. 作業の終わりの検証
( session_prune "$root" ) >/dev/null 2>&1 || :
[ -n "$(verify_cmd "$root")" ] || pass_out
if end_verify "$root" "$name"; then
  if [ "$END_RAN" = 1 ]; then
    log "claude stop rc=$END_RC ($END_CMD)"
    [ "$END_RC" -eq 3 ] && log "claude stop: 回す検証の命令が無い（WARN）。止めずに伝える"
    stop_count "$sid" reset >/dev/null
  fi
  pass_out
fi
log "claude stop rc=$END_RC ($END_CMD)"
stop_count "$sid" bump >/dev/null
summary="$(printf '%s\n' "$END_OUT" | grep -E '^(FAIL|RESULT:)' | head -20)"
[ -n "$summary" ] || summary="$(printf '%s\n' "$END_OUT" | tail -20)"
if [ "$END_DOCFAIL" = 1 ]; then
  reason="このセッションで書いた文書の検査（${END_CMD}）が FAIL です。直してから終えてください。
$summary"
else
  reason="作業を終える前の検証（${END_CMD}）が FAIL。直すのは、この依頼で自分が変えたファイルだけ。範囲外の FAIL（前から落ちている試験、触っていないファイル）は直さず、報告に書いて終える。指示されていないファイルは変えない。FAIL のあいだは「完了」と書かない。
$summary"
fi
block_out "$reason"
