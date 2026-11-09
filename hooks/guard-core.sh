#!/usr/bin/env bash
# hooks/guard-core.sh — 判定本体。コマンド文字列を 1 本受け取り、判定と理由を 1 行で返す。
#
# 判定は 3 つ。allow（許可）、ask（社長の確認）、deny（拒否）。
# 接続口（claude-*.sh、cursor-*.sh）は入出力の変換だけを持ち、判定はすべてここで行う。
#
# 使い方:
#   guard-core.sh [--signal deny] -- "<コマンド>"
#   printf '%s' "<コマンド>" | guard-core.sh [--signal deny]
# 出力: 「判定<TAB>理由」の 1 行。終了コードは常に 0（判定は出力で伝える）。
#
# 合図の語 APPROVE_GIT が含まれていれば、どの接続口のどの設定でも deny。合図で通す道は持たない。
# Cursor の beforeShellExecution では命令の文字列を AI が書くので、合図で通すと AI の自己承認になる。
# 承認は確認ダイアログ（ask）で受けるか、社長が hooks の掛からない自分の端末で実行する。
# --signal は前の呼び方との互換のために受け取るだけで、値は判定に使わない（honor を渡しても同じ判定）。
set -u

CMD=""
while [ $# -gt 0 ]; do
  case "$1" in
    --signal) shift; [ $# -gt 0 ] && shift ;;
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
raw() { printf '%s' "$CMD"  | grep -Eq -- "$1"; }  # 正規化の前の文字列を見る。逆斜線が消える前の 16 進逃げ文字を拾う

# 2. 合図の語。どこにあっても deny。
case "$flat" in
  *APPROVE_GIT*)
    out deny "合図の語 APPROVE_GIT はどの設定でも通さない。AI が付けることは最も重い違反。承認は確認ダイアログで受けるか、社長が自分の端末で実行する。"
    ;;
esac

# 2b. 守りの設定（mode のファイル）への書き込みと削除は、どの設定でも deny。
#     正規化で引用符と逆斜線は消えるが、ファイル名 company-guard.mode は残る。これを目印にする。
#     書き込み（> と >>、tee、cp、mv、truncate、sed、ln、install、dd）と削除（rm、rmdir、unlink）、
#     台本からの書き込み（python、perl、ruby、node、php）は deny。cat・ls・stat・test・wc・grep・diff の読みは allow。
if printf '%s' "$flat" | grep -Eq -- 'company-guard\.mode'; then
  if has '>>? *[^ ]*company-guard\.mode' \
     || has ' (tee|cp|mv|rm|rmdir|unlink|truncate|install|dd|ln|sed|python[0-9.]*|perl|ruby|node|php) '; then
    out deny "守りの設定（mode のファイル）は社長が自分の端末で書く。AI は読むだけで、書き換えも削除もしない。"
  fi
fi

# 3. 判定表。上から順に見て、最初に当たった行の判定を返す。
B='(^|[^[:alnum:]_.-])'                          # 語の始まり（/usr/bin/git も git と数える。mygit は数えない）
G="${B}git( +(-C +[^ ]+|-c +[^ ]+|--?[^ ]+))* +"  # git と、その直後の共通オプション（-C <dir>、-c k=v、--no-pager など）
A='( |$)'                                         # 語の終わり

ask_president() { out ask "$1"; }  # 社長の承認が要る操作。合図で allow にする道は持たない

# 3a. 関所 2: 外に出る操作
has "${G}commit${A}"      && ask_president "commit は関所 2。社長の承認があれば実行し、なければ中止する。"
has "${G}push${A}"        && ask_president "push は外に出る操作（関所 2）。社長の承認があれば実行する。"
has "${G}send-email${A}"  && ask_president "外部へ送る操作。社長の承認があれば実行する。"
has "${B}gh +pr +(create|merge|close|reopen|edit|comment|review|ready|lock|unlock)${A}" \
  && ask_president "PR の作成と変更は外に出る操作（関所 2）。社長の承認があれば実行する。"
has "${B}gh +issue +(create|close|reopen|edit|comment|delete|transfer|pin|unpin|lock|unlock|develop)${A}" \
  && ask_president "Issue の作成と変更は外に出る操作（関所 2）。社長の承認があれば実行する。"
has "${B}gh +(release|repo|gist) +(create|delete|edit|upload|delete-asset|fork|archive|unarchive|rename|sync)${A}" \
  && ask_president "GitHub への書き込みは外に出る操作。社長の承認があれば実行する。"
has "${B}gh +label +(create|delete|edit|clone)${A}" \
  && ask_president "GitHub への書き込みは外に出る操作。社長の承認があれば実行する。"
has "${B}gh +(secret|variable) +(set|delete)${A}" \
  && ask_president "GitHub の秘密と変数の書き換えは外に出る操作。社長の承認があれば実行する。"
has "${B}gh +(workflow +(run|enable|disable)|run +(cancel|rerun|delete)|cache +delete)${A}" \
  && ask_president "GitHub Actions への操作は外に出る操作。社長の承認があれば実行する。"
has "${B}gh +api( +[^ ]+)* +(-[fF] |--(field|raw-field|input)[= ]|-X *(POST|PUT|PATCH|DELETE)|--method[= ]+(POST|PUT|PATCH|DELETE))" \
  && ask_president "GitHub API への書き込みは外に出る操作。社長の承認があれば実行する。"
has "${B}(npm|pnpm|yarn) +publish${A}" && ask_president "パッケージの公開は外に出る操作。社長の承認があれば実行する。"
has "${B}docker +push${A}"             && ask_president "イメージの公開は外に出る操作。社長の承認があれば実行する。"

# 3b. 取り消せない操作
has "${G}reset( +[^ ]+)* +--(hard|merge)${A}" \
  && ask_president "作業の破棄（reset --hard）。取り消せないので、社長の承認があれば実行する。"
has "${G}clean( +[^ ]+)*( +--force| +-[a-zA-Z]*[fdxX][a-zA-Z]*)${A}" \
  && ask_president "追跡外ファイルの削除（clean -f）。取り消せないので、社長の承認があれば実行する。"
has "${G}stash +(drop|clear)${A}" \
  && ask_president "退避した変更の破棄（stash drop）。取り消せないので、社長の承認があれば実行する。"
has "${G}branch( +[^ ]+)* +(-[a-zA-Z]*[dD][a-zA-Z]*|--delete|--force)${A}" \
  && ask_president "ブランチの削除。社長の承認があれば実行する。"
has "${G}tag( +[^ ]+)* +(-d|--delete)${A}" \
  && ask_president "タグの削除。社長の承認があれば実行する。"
has "${G}(checkout|restore)( +[^ ]+)* +--(ours|theirs)${A}" \
  && ask_president "片側を捨てるコンフリクトの解消（--ours/--theirs）は原則しない。社長の承認があれば実行する。"
has "${G}(merge|rebase|pull|cherry-pick|revert)( +[^ ]+)* +(-X *|--strategy-option[= ]+)(ours|theirs)${A}" \
  && ask_president "片側を捨てるコンフリクトの解消（-X ours/theirs）は原則しない。社長の承認があれば実行する。"
has "${G}(merge|pull)( +[^ ]+)* +(-s +ours|--strategy[= ]+ours)${A}" \
  && ask_president "片側を捨てるマージ（-s ours）は原則しない。社長の承認があれば実行する。"
has "${G}(rebase|filter-branch|filter-repo|replace)${A}" \
  && ask_president "履歴の書き換え。社長の承認があれば実行する。"
has "${G}reflog +(expire|delete)${A}" \
  && ask_president "履歴の書き換え（reflog の削除）。社長の承認があれば実行する。"
has "${G}gc( +[^ ]+)* +--prune" \
  && ask_president "履歴の書き換え（gc --prune）。社長の承認があれば実行する。"
has "${G}update-ref +-d${A}" \
  && ask_president "参照の削除。社長の承認があれば実行する。"
has "${G}checkout( +[^ ]+)* +(-f|--force)${A}" \
  && ask_president "作業の破棄（checkout --force）。社長の承認があれば実行する。"
has "${G}checkout +(-- |\\.(/| |$))" \
  && ask_president "作業中の変更の破棄（checkout -- / checkout .）。社長の承認があれば実行する。"
if has "${G}restore${A}"; then
  if ! has "${G}restore( +[^ ]+)* +(--staged|-S)${A}" || has "${G}restore( +[^ ]+)* +(--worktree|-W)${A}"; then
    ask_president "作業中の変更の破棄（restore）。社長の承認があれば実行する。"
  fi
fi
has "${G}worktree +remove( +[^ ]+)* +(-f|--force)${A}" \
  && ask_president "作業ツリーの強制削除。社長の承認があれば実行する。"
has "${B}rm( +-[^ ]+)* +[^ ]*\\.git(/[^ ]*)?${A}" \
  && ask_president "リポジトリの破壊（.git の削除）。社長の承認があれば実行する。"

# 3c. 符号化した命令。復号した結果をシェルに渡す書き方は、中身を照合できないので ask。
#     復号の目印（base64 の -d/-D、xxd -r、Python の fromhex ほか、正規化の前の 16 進逃げ文字）と、
#     シェルに渡す目印（| sh、sh -c、eval、os.system ほか）が、同じ命令にそろったときだけ掛ける。
#     復号だけ（base64 -d file > out、xxd -r）や、eval だけ・python3 -c だけは allow のまま。
_decode() {
  has 'base64( +-[^ ]+)* +(--decode|-[a-zA-Z]*[dD])([^a-zA-Z]|$)' \
    || has '(^| )xxd +(-[^ ]+ +)*-r' \
    || has 'fromhex|unhexlify|b64decode|codecs\.decode' \
    || raw '\\x[0-9A-Fa-f][0-9A-Fa-f]'
}
_sink() {
  has '\| *(sh|bash|zsh|dash|ksh|fish)( |$|\|)' \
    || has '(^| )(sh|bash|zsh|dash|ksh|fish) +-c( |$)' \
    || has '(^| )eval( |$)' \
    || has 'os\.system|subprocess|os\.popen|\.popen|(^| )exec\(|(^| )eval\('
}
if _decode && _sink; then
  ask_president "復号した文字列をシェルに渡す書き方は、中身を判定できない。平文で書くか、社長の確認を受ける。"
fi

out allow "読むだけか、取り消せる操作。"
