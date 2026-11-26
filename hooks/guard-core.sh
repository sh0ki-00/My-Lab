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

# 2b. 守りの設定（mode のファイル）と、その置き場への書き込み・削除・権限の変更は、どの設定でも deny。
#     置き場は 2 つ。root 所有の /usr/local/etc/company-guard/（名前 company-guard が目印）と、互換の ~/.cursor/（親フォルダごと目印）。
#     正規化で引用符と逆斜線は消えるが、名前は残る。命令がどちらかに触れ、かつ次のどれかがあれば deny:
#       書き込みのリダイレクト（>、>>、>|、&>。先が company-guard か、$ で隠した名前か、~/.cursor の下）、
#       書き換え・削除・権限の命令（tee、cp、mv、rm、rmdir、unlink、truncate、install、dd、ln、sed、chmod、chown、chflags、
#       台本の python・perl・ruby・node・php）。/bin/rm のようなパス付きと、; & ( | の直後の命令名も見る。
#     cat・ls・stat・test・wc・grep・diff の読みは allow。プロジェクトの中の .cursor/（hooks.json）は、家のパスでないので見ない。
#     芯の守りは文字列ではなく置き場の所有者（root）にあり、ここは AI の手元で早く止めるための網。
#     大文字小文字は区別しない。APFS では RM も /bin/rm として動き、~/.Cursor も ~/.cursor と同じ場所になるため。
hasi() { printf '%s' "$flat" | grep -Eqi -- "$1"; }   # has の、大文字小文字を区別しない版
# shellcheck disable=SC2016  # $HOME は正規表現の字面。展開しない
HP='(~|/Users/[^ /]+|/home/[^ /]+|\$HOME|\$\{HOME\})'   # 家のパスの書き方
HC="${HP}/\\.cursor"
WR='(^|[ /;&(|])(tee|cp|mv|rm|rmdir|unlink|truncate|install|dd|ln|sed|chmod|chown|chflags|python[0-9.]*|perl|ruby|node|php)( |$)'
if hasi 'company-guard' || hasi "$HC"; then
  if hasi '>>?\|? *[^ ]*(company-guard|\$)' || hasi ">>?\\|? *[^ ]*${HC}" || hasi "$WR"; then
    out deny "守りの設定（mode のファイル）と hooks の登録は社長が自分の端末で書く。AI は読むだけで、書き換えも削除もしない。"
  fi
fi

# 2b-2. 置き場をグロブ（* ? [ {）で崩した書き方。名前が字面に残らないので、2b の目印（company-guard、.cursor）では当たらない。
#     次のどれかに、2b と同じ書き込み・削除・権限の目印（グロブか $ へのリダイレクト、WR の命令）が組になれば deny:
#       家のパスの直下の名前が [ か { で始まる（~/[.]cursor、~/{.cursor,.claude}）か、. で始まりグロブの字を含む（~/.c*、~/.[c]ursor、
#       ~/.?ursor。* や ? は先頭の . に当たらないので、隠し名を指すグロブは . か [ か { で始まる）、
#       .cursor か .claude の下の名前にグロブの字がある（~/.claude/sett*、~/.cursor/hooks.js*n）、
#       絶対パスの最初の名前にグロブの字があり .c を含む（/U*/<名>/.cursor）、/usr/local/etc/ の下にグロブの字がある（company-g*）。
#     読み（ls ~/.c*/、cat ~/.c*/x、ls /usr/local/etc/*）と、他の名前の下（rm -rf ~/.cache/*、chmod 600 ~/.ssh/*、rm ~/*.log）は allow のまま。
HG="${HP}/([[{][^ ]*|\\.[^ /]*[*?[{][^ ]*|\\.(cursor|claude)/[^ ]*[*?[{])"
HG2='(^|[ =>])/[^ /]*[*?[{][^ /]*/[^ ]*\.c[^ ]*'
UG='/usr/local/etc/[^ ]*[*?[{]'
if hasi "$HG" || hasi "$HG2" || hasi "$UG"; then
  if hasi '>>?\|? *[^ ]*([*?[{]|\$)' || hasi "$WR"; then
    out deny "守りの設定と hooks の登録の置き場を、グロブ（* ? [ {）で指す書き込み・削除・権限の変更は通さない。社長が自分の端末で書く。"
  fi
fi

# 3. 判定表。上から順に見て、最初に当たった行の判定を返す。
B='(^|[^[:alnum:]_.-])'                          # 語の始まり（/usr/bin/git も git と数える。mygit は数えない）
G="${B}git( +(-C +[^ ]+|-c +[^ ]+|--?[^ ]+))* +"  # git と、その直後の共通オプション（-C <dir>、-c k=v、--no-pager など）
A='( |$)'                                         # 語の終わり

NOTE=""   # ask の理由に書き足す文（2d で本文のファイルを読めなかったときなど）
ask_president() { out ask "$1${NOTE:+ $NOTE}"; }  # 社長の承認が要る操作。合図で allow にする道は持たない

# 2c. hooks の登録と本体への書き込み・削除・移動・権限の変更も deny。Write・Edit の門（claude-preedit.sh）と同じ場所を、Bash の側でも守る。
#     場所: ~/.claude/settings.json、~/.claude/hooks/、~/.claude/CLAUDE.md、My-Lab の hooks/ と .claude/settings.json と .cursor/hooks.json。
#     My-Lab は絶対パスと、~ や $HOME からの書き方で見る。My-Lab の中で動いているとき（接続口が渡す COMPANY_GUARD_PROJECT_ROOT、無ければ
#     CLAUDE_PROJECT_DIR・CURSOR_PROJECT_DIR・PWD が My-Lab の下）は、hooks/・./hooks/・../hooks/・.claude/settings.json・.cursor/hooks.json の
#     相対パスも見る。他のプロジェクトの hooks/ は見ない。
#     場所がその命令の引数のとき deny にする形: リダイレクト（> >> >| &>）、tee・mv・rm・rmdir・unlink・truncate・install・dd・ln・chmod・chown・
#       chflags・patch・shred・ed・ex、cp と rsync は場所が最後の引数（写す先）か -t の先、sed と perl は -i（上書き）つき、
#       git checkout <ref> -- <場所> と git restore <場所>。
#     命令のどこかに場所があれば deny にする形: 台本を -c や -e で命令の中に書く python・perl・ruby・node・php、
#       場所を変数に入れる書き方（f=hooks/x）と書き込みの目印（$ へのリダイレクト、上の命令）の組。
#     読みと検査は allow のまま（cat・ls・diff・grep・git diff・git add・shellcheck・bash hooks/selftest.sh・python3 <台本> hooks/*.sh・
#       cp hooks/x /tmp/ のように場所が写す元）。大文字小文字は区別しない。
#     git の merge・checkout <ブランチ>・apply・stash pop で hooks/ の中身が変わる道と、別の命令に分けた書き方は、文字列では見ない。
# shellcheck disable=SC2016  # 正規表現の中の $ は字面。展開しない
LAB="${LAB_ROOT:-$(cd "$(dirname "$0")/.." 2>/dev/null && pwd -P)}"
if r="$(CDPATH='' cd "$LAB" 2>/dev/null && { /bin/pwd -P 2>/dev/null || pwd -P; })"; then LAB="$r"; fi   # 実体のパスに（無ければ字面のまま）
lower()  { printf '%s' "$1" | LC_ALL=C tr '[:upper:]' '[:lower:]'; }
re_esc() { printf '%s' "$1" | sed -e 's,[][\.*^$+?(){}|],\\&,g'; }   # 正規表現の字を逃がす
LAB_RE="$(re_esc "$LAB")"
case "$LAB" in "$HOME"/*) LAB_RE="(${LAB_RE}|${HP}/$(re_esc "${LAB#"$HOME"/}"))" ;; esac
proot="${COMPANY_GUARD_PROJECT_ROOT:-${CLAUDE_PROJECT_DIR:-${CURSOR_PROJECT_DIR:-$PWD}}}"
if r="$(CDPATH='' cd "$proot" 2>/dev/null && { /bin/pwd -P 2>/dev/null || pwd -P; })"; then proot="$r"; fi
IN_LAB=0; case "$(lower "$proot")" in "$(lower "$LAB")"|"$(lower "$LAB")"/*) IN_LAB=1 ;; esac
mk_tp() {  # mk_tp <hooks の段の正規表現> → 場所の正規表現。家の下、My-Lab の絶対パス、My-Lab の中なら相対パスも
  local hk="$1" ph pl pr
  ph="${HP}/\\.claude/(settings\\.json|${hk}|claude\\.md)"
  pl="${LAB_RE}/(${hk}|\\.claude/settings\\.json|\\.cursor/hooks\\.json)"
  pr="([^ ;&|()]*\\.\\./|\\./)?(${hk}|\\.claude/settings\\.json|\\.cursor/hooks\\.json)"
  if [ "$IN_LAB" = 1 ]; then printf '(%s|%s|%s)' "$ph" "$pl" "$pr"; else printf '(%s|%s)' "$ph" "$pl"; fi
}
TP="$(mk_tp 'hooks(/| |$)')"                        # 場所の始まり（後ろに何が続いても）
TPT="$(mk_tp 'hooks(/[^ ;&|()]*)?')"                # 場所が 1 つの引数の全部（cp の写す先の判定で、次の引数まで 1 語と見ないため）
PRE='(^|[ ;&(|=>])'                                 # 引数の始まり（> の直後と、of= のような = の直後も）
if hasi "${PRE}${TP}"; then
  ARG="( +[^ ;&|()]+)* +([^ =;&|()]*=)?${TP}"       # 同じ 1 つの命令の引数に場所がある（; && || | ( ) を越えない）
  W1='(^|[ /;&(|])(tee|mv|rm|rmdir|unlink|truncate|install|dd|ln|chmod|chown|chflags|patch|shred|ed|ex)'
  W2='(^|[ /;&(|])(tee|cp|rsync|mv|rm|rmdir|unlink|truncate|install|dd|ln|sed|perl|chmod|chown|chflags|patch|shred|ed|ex)( |$)'
  INPL='(-[a-z]*i[^ ]*|--in-place[^ ]*)'           # sed と perl の上書き（-i、-i.bak、-pi、-Ei）
  if hasi ">>?\\|? *${TP}" \
    || hasi "${W1}${ARG}" \
    || hasi "(^|[ /;&(|])(cp|rsync)( +[^ ;&|()]+)* +${TPT} *(\$|[;&|)])" \
    || hasi "(^|[ /;&(|])(cp|rsync|mv|install)( +[^ ;&|()]+)* +(-t|--target-directory)[= ]*${TP}" \
    || hasi "(^|[ /;&(|])(sed|perl)( +[^ ;&|()]+)* +${INPL}${ARG}" \
    || hasi "(^|[ /;&(|])(sed|perl)${ARG}( +[^ ;&|()]+)* +${INPL}( |\$)" \
    || hasi '(^|[ /;&(|])(python[0-9.]*|perl|ruby|node)( +-[^ ]+)* +-[a-z]*[ce]( |$)|(^|[ /;&(|])php( +-[^ ]+)* +-r( |$)' \
    || hasi "${G}(checkout|restore)${ARG}" \
    || { hasi "(^|[ ;&(|])[a-z_][a-z0-9_]*=${TP}" && { hasi '>>?\|? *[^ ]*\$' || hasi "$W2"; }; }
  then
    out deny "hooks の登録と本体（~/.claude/settings.json、~/.claude/hooks、~/.claude/CLAUDE.md、My-Lab の hooks/ と .claude/settings.json と .cursor/hooks.json）は社長が自分の端末で書く。AI は読むだけで、書き換えも削除も移動もしない。直す必要があれば、差分を tmp/ に置いて社長に示す。"
  fi
fi

# 2d. commit 文・PR 文・Issue 文の現場の語の言い換え（git のブランチを別の語にするなど）は deny。3a の確認（ask）より先に返す。
#     見る命令: git commit・merge・tag、gh pr（create、edit、comment、review、merge）、gh issue（create、edit、comment）、
#       gh release（create、edit）、gh api（-f・-F・--field・--raw-field・--input で本文を送るとき）。
#     見る文: 命令の文の全部と、次のファイルの中身（1 本 1 MB まで、20 本まで）。
#       -F・--file・--body-file・--input に渡したファイル（-aF のようにまとめた短いオプションも）と、gh api の key=@<ファイル>。
#       $(cat <ファイル>) の <ファイル>。< <ファイル> と cat <ファイル> | の <ファイル> は、-F - や --body-file - のように
#       本文を標準入力から読む命令のときだけ読む（git commit -m x && cat a | grep y の a のような、本文でないファイルを読まない）。
#     読み先: 相対パスは、命令の作業場所（hooks が入力の cwd から渡す COMPANY_GUARD_CWD。無ければ COMPANY_GUARD_PROJECT_ROOT、
#       無ければ今の場所）と、命令の中の cd <場所>（順に積む）と git -C <場所> の先と、プロジェクトの root から読む。あるものを全部読む。
#       引用符は外し、逆斜線で逃がした字（空白など）は解く。-（標準入力）そのものは読まない。
#     -F・--file・--body-file・--input のファイルが、どの読み先にも無いか読めないときは、確認（ask）の理由に書き足す。
#     ファイルの名前は、命令の文を 1 回ずつ走査して拾う（grep -o）。-F が多い長い命令でも、時間が -F の数に比例して伸びない。
#       拾うのは 200 本まで。超えたら、全部は確かめていないと確認の理由に書き足す。
#     判定は lib.sh の terms_check（My-Lab の正本 tools/lib/check_ja.py --terms -）に任せ、ここは語の一覧を持たない。
#       鉤括弧の中とバッククォートの中は数えない。標準入力なので ja-ok の印は見ない（正本の決まり）。
#       lib.sh は子のシェルで読み、LAB_ROOT ほかを上書きしない。
#     python3 か正本が無いなど、数えられないときは何もせず、3a の ask に任せる。ほかの命令では python を起こさない。
q1="'"
MV="(\"[^\"]*\"|${q1}[^${q1}]*${q1}|([^[:space:];&|()<>\"${q1}\\\\]|\\\\.)+)"   # 値: 引用符の中か、逃がした字を含む 1 語
unquote() {  # 標準入力の 1 行 1 つの値から、囲みの引用符を外し、引用符の無い値の逆斜線の逃げを解く
  LC_ALL=C sed -E -e "/^[\"${q1}]/!s/\\\\(.)/\\1/g" -e 's/^"(.*)"$/\1/' -e "s/^${q1}(.*)${q1}\$/\\1/"
}
msg_files() {  # 本文を読むファイルの候補を「o<TAB>パス」（オプションで渡したファイル）、「s<TAB>パス」（$(cat) の先）、
  #             「h<TAB>パス」（< と cat | の先。本文を標準入力から読む命令のときだけ使う）で書く
  { printf '%s\n' "$CMD" | grep -oE -- "(^|[[:space:];&|(])(-[a-zA-Z]*F|--file|--body-file|--input)(=|[[:space:]]*)${MV}" \
      | LC_ALL=C sed -E 's/^[[:space:];&|(]?(-[a-zA-Z]*F|--file|--body-file|--input)(=|[[:space:]]*)//' | unquote | sed 's/^/o	/'
    printf '%s\n' "$CMD" | grep -oE -- "=@${MV}" | LC_ALL=C sed -E 's/^=@//' | unquote | sed 's/^/o	/'
    printf '%s\n' "$CMD" | grep -oE -- "[\$][(]cat[[:space:]]+${MV}" | LC_ALL=C sed -E 's/^[$][(]cat[[:space:]]+//' | unquote | sed 's/^/s	/'
    printf '%s\n' "$CMD" | grep -oE -- "(^|[^<])<[[:space:]]*${MV}" | LC_ALL=C sed -E 's/^[^<]?<[[:space:]]*//' | unquote | sed 's/^/h	/'
    printf '%s\n' "$CMD" | grep -oE -- "(^|[[:space:];&|(])cat[[:space:]]+${MV}[[:space:]]*[|]" \
      | LC_ALL=C sed -E 's/^[[:space:];&|(]?cat[[:space:]]+//; s/[[:space:]]*[|]$//' | unquote | sed 's/^/h	/'
  } | LC_ALL=C awk -F'\t' '$2 != "" && $2 != "-" && !seen[$2]++'
}
msg_dirs() {  # 本文のファイルを読む場所を 1 行 1 つで書く。命令の作業場所、cd の先（順に積む）、git -C の先、プロジェクトの root
  local cwd="${COMPANY_GUARD_CWD:-${COMPANY_GUARD_PROJECT_ROOT:-$PWD}}" cur kind d t
  printf '%s\n' "$cwd"
  cur="$cwd"
  while IFS='	' read -r kind d; do
    [ -n "$d" ] || continue
    d="$(printf '%s\n' "$d" | unquote)"
    # shellcheck disable=SC2088  # '~/' は命令の文の字面。展開させずに比べ、$HOME に置き換える
    case "$d" in /*) t="$d" ;; '~') t="$HOME" ;; '~/'*) t="$HOME/${d#'~/'}" ;; *) t="$cur/$d" ;; esac
    printf '%s\n' "$t"
    [ "$kind" = cd ] && cur="$t"
  done <<EOF
$(printf '%s\n' "$CMD" | grep -oE -- "(^|[[:space:];&|(])(cd|-C)[[:space:]]+${MV}" \
    | LC_ALL=C sed -E 's/^[[:space:];&|(]?(cd|-C)[[:space:]]+/\1	/' | head -n 20)
EOF
  [ -z "${COMPANY_GUARD_PROJECT_ROOT:-}" ] || printf '%s\n' "$COMPANY_GUARD_PROJECT_ROOT"
}
terms_reason() {  # 標準入力の文に言い換えがあれば、deny の理由の文を書いて 0。無いか、数えられなければ 1
  # shellcheck source=hooks/lib.sh
  ( . "$(dirname "$0")/lib.sh" || exit 1
    hits="$(terms_check)" || exit 1
    printf 'commit 文・PR 文・Issue 文に%sがあります。%sに直してから、もう一度実行してください。' "$(terms_join "$hits" 1)" "$(terms_join "$hits" 2)" )
}
if has 'commit|merge|tag|gh +(pr|issue|release|api)' \
  && { has "${G}(commit|merge|tag)${A}" || has "${B}gh +pr +(create|edit|comment|review|merge)${A}" \
       || has "${B}gh +issue +(create|edit|comment)${A}" || has "${B}gh +release +(create|edit)${A}" \
       || has "${B}gh +api( +[^ ]+)* +(-[fF] |--(field|raw-field|input)[= ])"; }; then
  mtext="$CMD"; nread=0; missing=""; ncand=0; stdin_msg=0
  has '(^| )(-[a-zA-Z]*F|--file|--body-file|--input)(=| +)-( |$)' && stdin_msg=1   # 本文を標準入力から読む（-F -、--body-file=- ほか）
  mdirs=()
  while IFS= read -r d; do
    if [ -n "$d" ]; then mdirs+=("$d"); fi
  done <<EOF
$(msg_dirs | LC_ALL=C awk '!seen[$0]++')
EOF
  while IFS='	' read -r kind p; do
    [ -n "$p" ] || continue
    if [ "$kind" = h ] && [ "$stdin_msg" = 0 ]; then continue; fi
    ncand=$((ncand + 1))
    if [ "$ncand" -gt 200 ]; then NOTE="本文のファイルの候補が多いので、全部は確かめていない。"; break; fi
    cands=()
    # shellcheck disable=SC2088  # '~/' は命令の文の字面。展開させずに比べ、$HOME に置き換える
    case "$p" in
      /*) cands=("$p") ;;
      '~/'*) cands=("$HOME/${p#'~/'}") ;;
      *) if [ "${#mdirs[@]}" -gt 0 ]; then for d in "${mdirs[@]}"; do cands+=("$d/$p"); done; fi ;;
    esac
    found=0
    [ "${#cands[@]}" -gt 0 ] || cands=("$p")   # bash 3.2 は空の配列の "${a[@]}" を set -u で落とす
    for f in "${cands[@]}"; do
      [ -f "$f" ] && [ -r "$f" ] || continue
      found=1
      [ "$nread" -lt 20 ] || continue
      nread=$((nread + 1))
      mtext="$mtext"$'\n'"$(head -c 1048576 "$f" 2>/dev/null)"
    done
    if [ "$found" = 0 ] && [ "$kind" = o ]; then missing="${missing}${missing:+、}${p}"; fi
  done <<EOF
$(msg_files)
EOF
  [ -z "$missing" ] || NOTE="${NOTE}本文のファイル（${missing}）を読めず、現場の語を確かめていない。"
  if why="$(printf '%s\n' "$mtext" | terms_reason)"; then out deny "$why"; fi
fi

# 2e. クラウドにつなぐコマンドは、設定によらず ask（S-7）。読むだけのコマンド（aws s3 ls、kubectl get）も含む。
#     インフラに触る作業は開発環境でだけ行い、そのたびに承認を得る（決まりは .company/rules/evidence-and-safety.md）。
#     名前で拾う網で、全部ではない。make deploy や npm run deploy のような包みのスクリプトの中身と、curl の宛先は、文字列では見えない。
#       決まりでは、包みのスクリプトも、クラウドにつながるなら承認を得てから回す。
#     いつも確認にする名前（CLOUD_ANY）: aws（awscli、aws-cli、aws-vault）、pulumi、kubectl、helm、helmfile、eksctl、skaffold、oc、
#       argocd、k9s、gcloud、gsutil、bq、google-cloud-cli、cloud-sdk、az、azure-cli、doctl、serverless、sls、sst、amplify、copilot、
#       eb、firebase、wrangler、flyctl、fly、vercel、netlify、heroku、s3cmd、rclone。
#     副命令で分ける名前（CLOUD_SUB。通す副命令のほかは確認）: terraform と tofu（fmt・validate）、terragrunt（hclfmt）、
#       packer（fmt）、sam（build・init・local）、cdk と aws-cdk（init・doctor・docs・acknowledge・notices・context）、
#       cdktf（synth・init・get）。どの名前も、help と version の副命令と、-help・--help・-h・-version・--version だけの呼び出しは通す。
#       cdk の synth と list は、文脈の取得で AWS に問い合わせることがあるので確認にする。前に -chdir=<場所> のようなオプションがあってもよい。
#     名前の始まりは、行頭・空白・; & | ( ` と / の直後。sh -c "aws …"、xargs aws、npx cdk deploy、パスの最後の名前
#       （/usr/local/aws-cli/aws、./node_modules/.bin/cdk、docker run の像 amazon/aws-cli、infra/aws）を拾う。
#       名前の終わりは、空白・; & | ) ` : と行末。$(which aws)、`which aws`、像の版つきの hashicorp/terraform:1.9 も拾う。
#       パスの途中の名前（infra/aws/main.tf）、隠しの名前（~/.aws）、名前の一部（aws_s3_bucket、helm-chart.md）は見ない。
#     cd terraform、grep aws、iac-scan.sh terraform のように、名前が引数にあるだけの命令も ask になる（取りこぼさない側に倒す）。
#     今の deny（2・2b・2c・2d）のあと、3a の ask の前に置く。git push と同じ命令にあれば、クラウドの理由を先に見せる。
#     大文字小文字は区別しない（APFS では AWS も aws として動く）。
# shellcheck disable=SC2016  # ` は正規表現の字面（命令の置き換えの区切り）。展開しない
CB='(^|[ ;&|(`/])'    # クラウドのコマンドの名前の始まり
# shellcheck disable=SC2016  # 同上
CE='([ ;&|)`:]|$)'    # 名前の終わり
CLOUD_ANY='aws|awscli|aws-cli|aws-vault|pulumi|kubectl|helm|helmfile|eksctl|skaffold|oc|argocd|k9s|gcloud|gsutil|bq|google-cloud-cli|cloud-sdk|az|azure-cli|doctl|serverless|sls|sst|amplify|copilot|eb|firebase|wrangler|flyctl|fly|vercel|netlify|heroku|s3cmd|rclone'
CLOUD_SUB='terraform|tofu|terragrunt|packer|sam|cdk|aws-cdk|cdktf'
cloud_sub_ok() {  # cloud_sub_ok <名前から始まる命令の切れ端> → 通す副命令（か help・version だけの呼び出し）なら 0
  local m w name sub="" flag=0 ok
  m="$(lower "$1")"
  case "$m" in [\ \;\&\|\(\`/]*) m="${m:1}" ;; esac
  set -f
  # shellcheck disable=SC2086  # 語に分けるため、わざと引用符で囲まない。グロブは set -f で広げない
  set -- $m
  set +f
  [ "$#" -gt 0 ] || return 1
  name="${1%%[@:]*}"; shift
  for w in "$@"; do
    case "$w" in
      -help|--help|-h|-version|--version) flag=1 ;;
      -*=*) ;;
      # 副命令の前に、値を別の語で取るオプション（--app init deploy の --app）があると、どの語が副命令か読めない。通さない
      -*) return 1 ;;
      *) sub="$w"; break ;;
    esac
  done
  if [ -z "$sub" ]; then [ "$flag" = 1 ]; return; fi
  # 副命令のあとに、クラウドのコマンドの名前がそのまま 1 語で出たら通さない（terraform fmt terraform apply のような並べ方）
  for w in "$@"; do
    case "$w" in "$sub") continue ;; esac
    if printf '%s\n' "$w" | grep -Eqix -- "(${CLOUD_ANY}|${CLOUD_SUB})"; then return 1; fi
  done
  case "$sub" in help|version) return 0 ;; esac
  case "$name" in
    terraform|tofu) ok='fmt validate' ;;
    terragrunt) ok='hclfmt' ;;
    packer) ok='fmt' ;;
    sam) ok='build init local' ;;
    cdk|aws-cdk) ok='init doctor docs doc acknowledge ack notices context' ;;
    cdktf) ok='synth init get' ;;
    *) return 1 ;;
  esac
  case " $ok " in *" $sub "*) return 0 ;; esac
  return 1
}
cloud=0
if hasi "${CB}(${CLOUD_ANY})${CE}"; then
  cloud=1
elif hasi "${CB}(${CLOUD_SUB})(@[^ ;&|()\`]*)?${CE}"; then
  # 現れるたびに、名前から ; & | ( ) ` の前までを切り出して見る。同じ命令に 2 つあっても、片方の fmt で通さない
  # 改行は命令の区切りなので ; に替える（flat は改行を空白にするので使わない）。( で切るのは $( と <( の中の命令を別に見るため
  cflat="$(printf ' %s ' "$CMD" | tr -d "$quotes" | tr '\n\r' ';;' | tr '\t' ' ' | tr -s ' ')"
  while IFS= read -r m; do
    [ -n "$m" ] || continue
    if ! cloud_sub_ok "$m"; then cloud=1; break; fi
  done <<EOF
$(printf '%s' "$cflat" | grep -Eoi -- "${CB}(${CLOUD_SUB})(@[^ ;&|()\`]*|:[^ ;&|()\`]*)?${CE}[^;&|()\`]*")
EOF
fi
[ "$cloud" = 1 ] && ask_president "クラウドにつなぐコマンドは、開発環境でだけ、そのたびに承認を得て回す（読むだけのコマンドも含む）。承認を伺う文に、環境の名前と、読むだけか書き換えるかを書く。"

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
#     復号の目印（base64・base32 の -d/-D、xxd -r、openssl の -d、uudecode、Python の fromhex ほか、
#     正規化の前の逃げ文字: 16 進 \x67、8 進 \147、g、$'…' の中の n と t 以外の逃げ文字）と、
#     シェルに渡す目印（| sh、sh -c、/bin/sh、env sh、eval、source、. file、xargs、$( )、` `、<( )、os.system ほか）が、
#     同じ命令にそろったときだけ掛ける。復号だけ（base64 -d file > out）や、eval だけ・source だけ・python3 -c だけは allow のまま。
_decode() {
  has 'base(64|32)( +-[^ ]+)* +(--decode|-[a-zA-Z]*[dD])([^a-zA-Z]|$)' \
    || has '(^| )xxd +(-[^ ]+ +)*-r' \
    || has '(^| |/)openssl +(enc|base64|aes[^ ]*|des[^ ]*|bf[^ ]*|rc[24][^ ]*|camellia[^ ]*)( +[^ ]+)* +-d( |$)' \
    || has '(^| |/)uudecode( |$)' \
    || has 'fromhex|unhexlify|b64decode|b32decode|codecs\.decode' \
    || raw '\\x[0-9A-Fa-f][0-9A-Fa-f]|\\[0-7][0-7][0-7]|\\u[0-9A-Fa-f]{4}' \
    || raw "\\\$'([^'\\\\]|\\\\[nt])*\\\\[^nt']"
}
_sink() {
  has '\| *([^ ]*/)?(sh|bash|zsh|dash|ksh|fish)( |$|\|)' \
    || has '(^| |/)(sh|bash|zsh|dash|ksh|fish) +-c( |$)' \
    || has '(^| )env( +-[^ ]+)* +([^ ]*/)?(sh|bash|zsh|dash|ksh|fish)( |$)' \
    || has '(^| )(eval|source|xargs)( |$)' \
    || has '(^ *|[;&|(] *)\. +[^ ;&|]' \
    || has '\$\(|`|<\(' \
    || has 'os\.system|subprocess|os\.popen|\.popen|(^| )exec\(|(^| )eval\('
}
if _decode && _sink; then
  ask_president "復号した文字列をシェルに渡す書き方は、中身を判定できない。平文で書くか、社長の確認を受ける。"
fi

out allow "読むだけか、取り消せる操作。"
