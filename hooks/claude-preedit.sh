#!/usr/bin/env bash
# hooks/claude-preedit.sh — Claude Code の PreToolUse（Write・Edit・MultiEdit・NotebookEdit）接続口。
# 書く先のパスを実体のパス（リンクと .. を解いた物）にし、大文字小文字をそろえて比べ、守りの設定と hooks の登録に当たれば deny を返す。
# 当たらなければ何も出さず、通常の権限の流れに任せる。シェルの門（claude-pretooluse.sh）は Bash しか見ないので、Write・Edit の道をここで閉じる。
#   deny にする先: ~/.cursor/ の下、~/.claude/settings.json、~/.claude/hooks/ の下、~/.claude/CLAUDE.md、/usr/local/etc/company-guard/ の下、
#                  My-Lab（この hooks の置き場の親）の hooks/ の下、.claude/settings.json、.cursor/hooks.json
#   比較は両側を小文字にそろえる。APFS は大文字小文字を区別せず、real_path はフォルダは本当の綴りに直すが最後の名前は打たれた綴りのまま返すため。
#   さらに、書く先が名前を 2 つ以上持つファイル（ハードリンク）なら deny。別の名前（ln ~/.claude/settings.json /tmp/x）から同じ中身を
#   書き換える道を、パスの比較では見分けられないため。
# 引数 --global: Mac 全体の登録から呼ばれたとき。プロジェクト自身が同じ接続口を登録していれば、理由を省いて判定だけ返す。
# shellcheck disable=SC2088  # 文の中の ~/ は人に見せる表記で、展開させない
set -u
# shellcheck source=hooks/lib.sh
. "$(dirname "$0")/lib.sh"

GLOBAL=0; [ "${1:-}" = "--global" ] && GLOBAL=1
input="$(cat)"
tool="$(json_get tool_name "$input")"
case "$tool" in Write|Edit|MultiEdit|NotebookEdit) ;; *) exit 0 ;; esac
file="$(json_get tool_input.file_path "$input")"
[ -n "$file" ] || file="$(json_get tool_input.notebook_path "$input")"
[ -n "$file" ] || exit 0
root="$(project_root "$input")"
case "$file" in /*) ;; '~') file="$HOME" ;; '~/'*) file="$HOME/${file#'~/'}" ;; *) file="$root/$file" ;; esac
real="$(real_path "$file")" || real="$file"
home="$(real_path "$HOME")" || home="$HOME"
lab="$(real_path "$LAB_ROOT")" || lab="$LAB_ROOT"
guard_dir="$(dirname "$(guard_mode_file)")"
guard_dir="$(real_path "$guard_dir")" || :   # /var と /private/var のような別名をそろえる（置き場がまだ無くても）
real_lc="$(lower "$real")"; home_lc="$(lower "$home")"; lab_lc="$(lower "$lab")"; guard_lc="$(lower "$guard_dir")"

under() { case "$real_lc" in "$1"|"$1"/*) return 0 ;; esac; return 1; }   # under <場所（小文字）> → 実体のパスがその下（か、それ自身）なら 0
why=""
if under "$home_lc/.cursor";                              then why="~/.cursor の下（Cursor の hooks の登録と守りの設定）"
elif [ "$real_lc" = "$home_lc/.claude/settings.json" ];   then why="~/.claude/settings.json（Mac 全体の hooks の登録）"
elif under "$home_lc/.claude/hooks";                      then why="~/.claude/hooks の下"
elif [ "$real_lc" = "$home_lc/.claude/claude.md" ];       then why="~/.claude/CLAUDE.md（常時ルール。本文は社長が貼る）"
elif under "$guard_lc";                                   then why="${guard_dir}（守りの設定の置き場）"
elif under "$lab_lc/hooks";                               then why="My-Lab の hooks/ の下（守りの本体）"
elif [ "$real_lc" = "$lab_lc/.claude/settings.json" ];    then why="My-Lab の .claude/settings.json（hooks の登録）"
elif [ "$real_lc" = "$lab_lc/.cursor/hooks.json" ];       then why="My-Lab の .cursor/hooks.json（hooks の登録）"
fi

if [ -n "$why" ]; then
  reason="${why}は AI が編集しない。守りの設定と hooks は社長が自分の端末で書く。直す必要があれば、差分を tmp/ に置いて社長に示す。"
else
  # パスでは当たらなくても、書く先が名前を 2 つ以上持つ（ハードリンク）なら deny。どの名前が守りのファイルかはパスから分からない
  links=""; [ -f "$real" ] && links="$(link_count "$real")"
  case "$links" in ''|0|1) exit 0 ;; esac
  reason="書く先（${real}）は名前を ${links} 個持つファイル（ハードリンク）で、別の名前から守りの設定や hooks を書き換える道と見分けられないので書かない。元の 1 つの名前で書くか、リンクを外す。"
fi
log "claude preedit deny $real"
if [ "$GLOBAL" = 1 ] && project_registers "$root" claude-preedit.sh; then
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny"}}\n'
else
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":%s}}\n' "$(json_str "$reason")"
fi
exit 0
