#!/usr/bin/env bash
# hooks/guard-core.sh — 判定本体。コマンド文字列を 1 本受け取り、判定と理由を 1 行で返す。
#
# 判定は 3 つ。allow（許可）、ask（社長の確認）、deny（拒否）。
# 接続口（claude-*.sh、cursor-*.sh）は入出力の変換だけを持ち、判定はすべてここで行う。
#
# 使い方:
#   guard-core.sh [--signal deny|honor] -- "<コマンド>"
#   printf '%s' "<コマンド>" | guard-core.sh [--signal deny|honor]
# 出力: 「判定<TAB>理由」の 1 行。終了コードは常に 0（判定は出力で伝える）。
#
# --signal deny  : 合図の語 APPROVE_GIT が含まれていれば deny。Claude Code 用。確認ダイアログがあるので合図は使わない。
# --signal honor : 先頭の APPROVE_GIT=1 だけを社長の合図として allow。Cursor で確認（ask）が効かないときの退避路。
#                  合図は社長が自分で付けるもので、AI が付けることは最も重い違反である。
set -u

SIGNAL_MODE="deny"
CMD=""
while [ $# -gt 0 ]; do
  case "$1" in
    --signal) SIGNAL_MODE="${2:-deny}"; shift 2 ;;
    --) shift; CMD="$*"; break ;;
    *) CMD="${CMD}${CMD:+ }$1"; shift ;;
  esac
done
if [ -z "$CMD" ] && [ ! -t 0 ]; then CMD="$(cat)"; fi

out() { printf '%s\t%s\n' "$1" "$2"; exit 0; }

# 1. 正規化。引用符と逆斜線を外し、改行とタブを空白にし、連続する空白を 1 つに詰める。
#    引用符で区切った書き方や、改行で分けた書き方でも同じ判定にするため。前後に空白を 1 つ置く。
quotes=$'\'"\\\\'
flat="$(printf ' %s ' "$CMD" | tr -d "$quotes" | tr '\n\t\r' '   ' | tr -s ' ')"

has() { printf '%s' "$flat" | grep -Eq -- "$1"; }

# 2. 合図の語。
SIGNAL_OK=0
case "$flat" in
  *APPROVE_GIT*)
    if [ "$SIGNAL_MODE" = "honor" ] && has '^ APPROVE_GIT=1 '; then
      SIGNAL_OK=1
    elif [ "$SIGNAL_MODE" = "honor" ]; then
      out deny "合図の語 APPROVE_GIT=1 はコマンドの先頭にだけ置ける。先頭以外の合図と、AI が付けた合図は無効。"
    else
      out deny "合図の語 APPROVE_GIT は社長が自分で付けるもの。AI が付けることは最も重い違反。Claude Code では確認ダイアログで承認を受ける。"
    fi
    ;;
esac

# 3. 判定表。上から順に見て、最初に当たった行の判定を返す。
B='(^|[^[:alnum:]_.-])'                          # 語の始まり（/usr/bin/git も git と数える。mygit は数えない）
G="${B}git( +(-C +[^ ]+|-c +[^ ]+|--?[^ ]+))* +"  # git と、その直後の共通オプション（-C <dir>、-c k=v、--no-pager など）
A='( |$)'                                         # 語の終わり

ask_or_allow() {  # 社長の合図つきなら allow、なければ ask
  if [ "$SIGNAL_OK" = 1 ]; then out allow "社長の合図（先頭の APPROVE_GIT=1）を確認した。$1"; fi
  out ask "$1"
}

# 3a. 関所 2: 外に出る操作
has "${G}commit${A}"      && ask_or_allow "commit は関所 2。社長の承認があれば実行し、なければ中止する。"
has "${G}push${A}"        && ask_or_allow "push は外に出る操作（関所 2）。社長の承認があれば実行する。"
has "${G}send-email${A}"  && ask_or_allow "外部へ送る操作。社長の承認があれば実行する。"
has "${B}gh +pr +(create|merge|close|reopen|edit|comment|review|ready|lock|unlock)${A}" \
  && ask_or_allow "PR の作成と変更は外に出る操作（関所 2）。社長の承認があれば実行する。"
has "${B}gh +issue +(create|close|reopen|edit|comment|delete|transfer|pin|unpin|lock|unlock|develop)${A}" \
  && ask_or_allow "Issue の作成と変更は外に出る操作（関所 2）。社長の承認があれば実行する。"
has "${B}gh +(release|repo|gist) +(create|delete|edit|upload|delete-asset|fork|archive|unarchive|rename|sync)${A}" \
  && ask_or_allow "GitHub への書き込みは外に出る操作。社長の承認があれば実行する。"
has "${B}gh +label +(create|delete|edit|clone)${A}" \
  && ask_or_allow "GitHub への書き込みは外に出る操作。社長の承認があれば実行する。"
has "${B}gh +(secret|variable) +(set|delete)${A}" \
  && ask_or_allow "GitHub の秘密と変数の書き換えは外に出る操作。社長の承認があれば実行する。"
has "${B}gh +(workflow +(run|enable|disable)|run +(cancel|rerun|delete)|cache +delete)${A}" \
  && ask_or_allow "GitHub Actions への操作は外に出る操作。社長の承認があれば実行する。"
has "${B}gh +api( +[^ ]+)* +(-[fF] |--(field|raw-field|input)[= ]|-X *(POST|PUT|PATCH|DELETE)|--method[= ]+(POST|PUT|PATCH|DELETE))" \
  && ask_or_allow "GitHub API への書き込みは外に出る操作。社長の承認があれば実行する。"
has "${B}(npm|pnpm|yarn) +publish${A}" && ask_or_allow "パッケージの公開は外に出る操作。社長の承認があれば実行する。"
has "${B}docker +push${A}"             && ask_or_allow "イメージの公開は外に出る操作。社長の承認があれば実行する。"

# 3b. 取り消せない操作
has "${G}reset( +[^ ]+)* +--(hard|merge)${A}" \
  && ask_or_allow "作業の破棄（reset --hard）。取り消せないので、社長の承認があれば実行する。"
has "${G}clean( +[^ ]+)*( +--force| +-[a-zA-Z]*[fdxX][a-zA-Z]*)${A}" \
  && ask_or_allow "追跡外ファイルの削除（clean -f）。取り消せないので、社長の承認があれば実行する。"
has "${G}stash +(drop|clear)${A}" \
  && ask_or_allow "退避した変更の破棄（stash drop）。取り消せないので、社長の承認があれば実行する。"
has "${G}branch( +[^ ]+)* +(-[a-zA-Z]*[dD][a-zA-Z]*|--delete|--force)${A}" \
  && ask_or_allow "ブランチの削除。社長の承認があれば実行する。"
has "${G}tag( +[^ ]+)* +(-d|--delete)${A}" \
  && ask_or_allow "タグの削除。社長の承認があれば実行する。"
has "${G}(checkout|restore)( +[^ ]+)* +--(ours|theirs)${A}" \
  && ask_or_allow "片側を捨てるコンフリクトの解消（--ours/--theirs）は原則しない。社長の承認があれば実行する。"
has "${G}(merge|rebase|pull|cherry-pick|revert)( +[^ ]+)* +(-X *|--strategy-option[= ]+)(ours|theirs)${A}" \
  && ask_or_allow "片側を捨てるコンフリクトの解消（-X ours/theirs）は原則しない。社長の承認があれば実行する。"
has "${G}(merge|pull)( +[^ ]+)* +(-s +ours|--strategy[= ]+ours)${A}" \
  && ask_or_allow "片側を捨てるマージ（-s ours）は原則しない。社長の承認があれば実行する。"
has "${G}(rebase|filter-branch|filter-repo|replace)${A}" \
  && ask_or_allow "履歴の書き換え。社長の承認があれば実行する。"
has "${G}reflog +(expire|delete)${A}" \
  && ask_or_allow "履歴の書き換え（reflog の削除）。社長の承認があれば実行する。"
has "${G}gc( +[^ ]+)* +--prune" \
  && ask_or_allow "履歴の書き換え（gc --prune）。社長の承認があれば実行する。"
has "${G}update-ref +-d${A}" \
  && ask_or_allow "参照の削除。社長の承認があれば実行する。"
has "${G}checkout( +[^ ]+)* +(-f|--force)${A}" \
  && ask_or_allow "作業の破棄（checkout --force）。社長の承認があれば実行する。"
has "${G}checkout +(-- |\\.(/| |$))" \
  && ask_or_allow "作業中の変更の破棄（checkout -- / checkout .）。社長の承認があれば実行する。"
if has "${G}restore${A}"; then
  if ! has "${G}restore( +[^ ]+)* +(--staged|-S)${A}" || has "${G}restore( +[^ ]+)* +(--worktree|-W)${A}"; then
    ask_or_allow "作業中の変更の破棄（restore）。社長の承認があれば実行する。"
  fi
fi
has "${G}worktree +remove( +[^ ]+)* +(-f|--force)${A}" \
  && ask_or_allow "作業ツリーの強制削除。社長の承認があれば実行する。"
has "${B}rm( +-[^ ]+)* +[^ ]*\\.git(/[^ ]*)?${A}" \
  && ask_or_allow "リポジトリの破壊（.git の削除）。社長の承認があれば実行する。"

out allow "読むだけか、取り消せる操作。"
