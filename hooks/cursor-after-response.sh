#!/usr/bin/env bash
# hooks/cursor-after-response.sh — Cursor の afterAgentResponse の hook。返答の本文（text）に、現場の語の言い換えがあるかを見る。
# 判定は lib.sh の terms_check（My-Lab の正本 tools/lib/check_ja.py --terms -）に任せ、語の一覧は持たない。
#   鉤括弧の中とバッククォートの中は数えない。ja-ok の印は見ない。python3 か正本が無いときは、数えずに何もしない。
# 当たれば、$LAB_ROOT/tmp/.verify/terms-<会話の名前> に「語<TAB>置き換えの語」を足す。会話の名前は conversation_id（lib.sh の session_name）。
# この事象には返答を止める出力が無いので、stop の hook（cursor-stop.sh）が印を読み、続きの指示（followup_message）で書き直させる。
# 何も出さず、終了コードは常に 0。
# 引数 --global: Mac 全体の登録から呼ばれたとき。プロジェクト自身が同じ hook を登録していれば、重ねて回さない。
set -u
# shellcheck source=hooks/lib.sh
. "$(dirname "$0")/lib.sh"

GLOBAL=0; [ "${1:-}" = "--global" ] && GLOBAL=1
input="$(cat)"
root="$(project_root "$input")"
if [ "$GLOBAL" = 1 ] && project_registers "$root" cursor-after-response.sh; then exit 0; fi
text="$(json_get text "$input")"
[ -n "$text" ] || exit 0
hits="$(printf '%s\n' "$text" | terms_check)" || exit 0
mark="$(terms_mark "$(session_name "$input")")"
mkdir -p "$(dirname "$mark")" 2>/dev/null || exit 0
{ printf '%s\n' "$hits" >> "$mark"; } 2>/dev/null || exit 0
log "cursor after-response: 返答に現場の語の言い換え（$(terms_join "$hits" 1)）。stop で書き直させる"
exit 0
