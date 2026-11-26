#!/usr/bin/env bash
# tools/project-verify.sh [--fast|--full] [--] [<ファイル>...] — 他のプロジェクト（tmp/ に移した版）で、作業を終える前の検証を回す。
#   文書: 引数で渡した文書だけを、check-file.sh（文体と資料の型）と check-refs.sh（参照の実在）で検査する。
#         文書とは、tmp/flow/ の下の .md と、tmp/ISSUE_*.md、tmp/PR_*.md。パスは root からの相対でも絶対でもよい。
#         引数に無い文書は、一覧に載せず、開かず、出力と記録に名前も出さない。ほかのセッションが書いた文書の FAIL で、
#         このセッションを止めないためである。AI は、このセッションで書いた文書を渡す（Bash のコマンドで書いた文書も）。
#         引数が無ければ、文書を 1 本も検査せず、「文書の指定なし（検査した文書 0 本）」と 1 行出す。
#         文書でない引数は検査せず、「文書でないので見ない n 本」と 1 行出す。無いファイルの引数は FAIL にする。
#         hooks（hooks/lib.sh の end_verify）は、この冒頭の使い方の行にある「[--] [<ファイル>...]」の字で、文書を引数で受ける版かを見分ける。
#         字を変えるときは、lib.sh の pv_takes_docs も合わせる。
#   命令: <root>/tmp/verify-commands.txt に 1 行 1 命令で書いてあれば、上から順に全部回す（引数と --fast・--full によらない）。
#         # で始まる行と空行は飛ばす。命令はプロジェクトの root で bash -c で回し、終了コードが 0 でなければ FAIL。
#         プロジェクト自身の lint・test・build は、自動では見つけない。前から落ちている試験や、人の手の変更を FAIL に数えないため。
#   --baseline: 移した時点の印を置く。印（tmp/.verify/last-pass）を今の時刻にし、ファイルの一覧を tmp/.verify/last-pass.list に書く。
#         検査は回さず、引数も取らない。deploy.sh が移した直後に呼ぶ。hooks は、印のあとにファイルが変わるまで検証を回さない。
#         移した先でだけ使い、My-Lab の中では止まる（終了コード 2）。
#   root は、このファイルの場所から決める（<root>/tmp/tools/project-verify.sh → <root>。My-Lab の tools/ にあるときは My-Lab）。
# 出力: 検査と命令ごとの RESULT: PASS|FAIL <名前> の行と、最後に RESULT: PASS|FAIL|WARN project-verify --<mode> (<n> 件中 FAIL <m>…)。
#   落ちた検査と命令は、その出力を「FAIL <名前>: 」を前に付けて 15 行まで見せる。文書の検査は落ちた行を先に、命令は末尾の行を見せる。
#   1 つでも FAIL なら終了コード 1。使い方の誤りは終了コード 2。文書を渡して命令のファイルが無いときは、WARN にしない。
#   検査した文書も命令も 1 つも無ければ、PASS にせず WARN（終了コード 3）で終える。何も検査していない回を、
#   commit の前の「PASS の記録」に使わせないためである。hooks は終了コード 3 を通す（引き戻さない）。
# 記録: <root>/tmp/.verify/last-fast.txt（--full なら last-full.txt）に、日時と命令（渡した引数を含む）と RESULT 行を書く。
#       My-Lab の中で回したときは、verify-all.sh の記録を上書きしないよう project-verify-last-<mode>.txt に書く。
#       移した先で PASS なら、tmp/.verify/last-pass も更新する。hooks は、これより新しいファイルがあるか、通ったときの一覧とファイルの一覧が違うときに検証を回す。
#       FAIL と WARN と、My-Lab の中で回したときは更新しない。
set -u
# パスは /bin/pwd -P でそろえる（bash 3.2 の組み込みの pwd -P は、大文字小文字の違う綴りをそのまま返す）。引数のパスとの比べ方と揃える
phys_pwd() { /bin/pwd -P 2>/dev/null || pwd -P; }
HERE="$(cd "$(dirname "$0")" && phys_pwd)" || exit 1
if [ "$(basename "$(dirname "$HERE")")" = "tmp" ]; then ROOT="$(cd "$HERE/../.." && phys_pwd)"; RECORD_PREFIX="last"; else ROOT="$(cd "$HERE/.." && phys_pwd)"; RECORD_PREFIX="project-verify-last"; fi
cd "$ROOT" || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
USAGE="使い方: project-verify.sh [--fast|--full] [--] [<ファイル>...]   /   project-verify.sh --baseline"
MODE="fast"
while [ "$#" -gt 0 ]; do
  case "$1" in
    --fast) MODE="fast" ;;
    --full) MODE="full" ;;
    --baseline) MODE="baseline" ;;
    --) shift; break ;;
    -?*) echo "$USAGE"; exit 2 ;;
    *) break ;;
  esac
  shift
done
if [ "$MODE" = "baseline" ] && [ "$#" -gt 0 ]; then echo "$USAGE"; exit 2; fi
CMDS="tmp/verify-commands.txt"
STAMP="tmp/.verify/last-pass"
LIST="tmp/.verify/last-pass.list"
fail=0; ran=0
STARTED="$(date '+%Y-%m-%d %H:%M:%S')"
SUMMARY=""
COMMAND_LINE="bash tmp/tools/project-verify.sh --$MODE"

# tree_list → root の下のファイルの一覧（./ 始まり、文字の設定によらない順）。lib.sh（hooks）の tree_list と同じ形にする（変えるときは両方）
tree_list() {
  find . \( -name node_modules -o -name .git -o -name .verify -o -name dist -o -name build -o -name .next -o -name target -o -name vendor \) -prune -o -type f -print 2>/dev/null | LC_ALL=C sort
}

# rel_of <ファイル> → root からの相対パス。置き場のリンクは実体にそろえる。root の外なら何も書かない
rel_of() {
  local d b
  d="$(CDPATH='' cd "$(dirname "$1")" 2>/dev/null && phys_pwd)" || return 0
  b="$(basename "$1")"
  if [ "$d" = "$ROOT" ]; then printf '%s' "$b"; return 0; fi
  case "$d" in "$ROOT"/*) printf '%s/%s' "${d#"$ROOT"/}" "$b" ;; esac
}

# is_doc <root からの相対パス> → 検査する文書（tmp/flow/ の下の .md、tmp/ISSUE_*.md、tmp/PR_*.md）なら 0
is_doc() {
  case "$1" in
    tmp/flow/*.md) return 0 ;;
    tmp/ISSUE_*.md|tmp/PR_*.md) case "${1#tmp/}" in */*) return 1 ;; esac; return 0 ;;
  esac
  return 1
}

PICK_FAILS=0   # 1 のあいだ、run は落ちた行を先に見せる（文書の検査）
run() {  # run <名前> <コマンド...> → 検査と命令。FAIL を数える
  local name="$1"; shift
  local out rc line shown=""
  ran=$((ran + 1))
  out="$("$@" 2>&1)"; rc=$?
  if [ "$rc" -eq 0 ]; then
    line="RESULT: PASS $name"
  else
    fail=$((fail + 1))
    # 文書の検査は、落ちた行（RESULT: FAIL の行、次に FAIL の行）を 15 行まで見せる。渡した文書が多いとき、
    #   通った文書の行で、落ちた文書の名前を押し出さないため。落ちた行が無いときと命令は、今までどおり末尾の 15 行
    if [ "$PICK_FAILS" = 1 ]; then
      shown="$( { printf '%s\n' "$out" | grep -E '^RESULT: FAIL'; printf '%s\n' "$out" | grep -E '^FAIL'; } | head -15)"
    fi
    [ -n "$shown" ] || shown="$(printf '%s\n' "$out" | tail -15)"
    # 名前（命令の文）に | や & が入っても壊れないよう、sed ではなく printf で前に付ける
    printf '%s\n' "$shown" | while IFS= read -r l; do printf 'FAIL %s: %s\n' "$name" "$l"; done
    line="RESULT: FAIL $name (rc=$rc)"
  fi
  printf '%s\n' "$line"
  SUMMARY="$SUMMARY$line"$'\n'
}

note() {  # note <文> → 文書の数の知らせを 1 行出し、記録にも残す
  printf '%s\n' "$1"
  SUMMARY="$SUMMARY$1"$'\n'
}

finish() {  # finish <最後の RESULT 行> <終了コード> → 出力し、tmp/.verify/last-<mode>.txt に記録して終える
  printf '%s\n' "$1"
  if mkdir -p "$ROOT/tmp/.verify" 2>/dev/null; then
    { printf '日時: %s（終了 %s）\n' "$STARTED" "$(date '+%Y-%m-%d %H:%M:%S')"
      printf '命令: %s\n' "$COMMAND_LINE"
      printf '%s' "$SUMMARY"
      printf '%s\n' "$1"; } > "$ROOT/tmp/.verify/$RECORD_PREFIX-$MODE.txt"
    # 移した先の PASS だけ、hooks の印（lib.sh の changed_since_pass が読む）を更新する
    if [ "$2" -eq 0 ] && [ "$RECORD_PREFIX" = "last" ]; then touch "$ROOT/$STAMP"; fi
  fi
  exit "$2"
}

# --baseline: 移した時点の印と一覧を置いて終える。検査は回さない
if [ "$MODE" = "baseline" ]; then
  if [ "$RECORD_PREFIX" != "last" ]; then
    echo "FAIL project-verify --baseline: 移した先（<プロジェクト>/tmp/tools）でだけ使う。My-Lab では verify-all.sh が印を書く"
    exit 2
  fi
  mkdir -p tmp/.verify || exit 1
  if ! { tree_list > "$LIST.tmp" && mv -f "$LIST.tmp" "$LIST" && touch "$STAMP"; }; then
    rm -f "$LIST.tmp"
    echo "FAIL project-verify --baseline: tmp/.verify に印を書けない"
    exit 1
  fi
  printf 'project-verify: 移した時点の印（%s）と一覧（%s）を置いた。文書は、引数で渡したものだけを検査する\n' "$STAMP" "$LIST"
  exit 0
fi

# 1. 引数を分ける。文書は root からの相対パスにそろえ、同じ文書は 1 本に数える。空白を含むパスも 1 本のまま渡す
#    引数に無い文書は探さない（tmp/flow を一覧にしない）。bash 3.2 は空の配列の "${docs[@]}" を set -u で落とすので、本数を先に見る
docs=(); missing=(); others=0
[ "$#" -gt 0 ] && COMMAND_LINE="$COMMAND_LINE --"
for a in "$@"; do
  COMMAND_LINE="$COMMAND_LINE '$a'"
  if [ ! -f "$a" ]; then missing+=("$a"); continue; fi
  rel="$(rel_of "$a")"
  if [ -n "$rel" ] && is_doc "$rel"; then
    dup=0
    if [ "${#docs[@]}" -gt 0 ]; then for d in "${docs[@]}"; do [ "$d" = "$rel" ] && dup=1; done; fi
    [ "$dup" -eq 1 ] || docs+=("$rel")
  else
    others=$((others + 1))
  fi
done

[ "$#" -gt 0 ] || note "文書の指定なし（検査した文書 0 本）"
[ "$others" -eq 0 ] || note "文書でないので見ない ${others} 本"
if [ "${#missing[@]}" -gt 0 ]; then
  ran=$((ran + 1)); fail=$((fail + 1))
  for m in "${missing[@]}"; do printf 'FAIL 引数のファイル: %s が無い（ファイルでないか、root からの相対パスでない）\n' "$m"; done
  line="RESULT: FAIL 引数のファイル（無い ${#missing[@]} 本）"
  printf '%s\n' "$line"
  SUMMARY="$SUMMARY$line"$'\n'
fi
if [ "${#docs[@]}" -gt 0 ]; then
  PICK_FAILS=1
  run "check-file（渡した文書 ${#docs[@]} 本）" bash "$HERE/check-file.sh" "${docs[@]}"
  run "check-refs（渡した文書 ${#docs[@]} 本）" bash "$HERE/check-refs.sh" "${docs[@]}"
  PICK_FAILS=0
fi

# 2. 検証の命令（任意）。ファイルが無ければ何も回さない
#    先に全部読んでから回す。読みながら回すと、命令が標準入力からファイルの残りを読んでしまう
cmds=()
if [ -f "$CMDS" ]; then
  while IFS= read -r cmd || [ -n "$cmd" ]; do
    cmd="${cmd%$'\r'}"
    cmd="$(printf '%s' "$cmd" | LC_ALL=C sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
    case "$cmd" in ''|'#'*) continue ;; esac
    cmds+=("$cmd")
  done < "$CMDS"
fi
if [ "${#cmds[@]}" -gt 0 ]; then
  for cmd in "${cmds[@]}"; do
    run "$cmd" bash -c "$cmd" </dev/null
  done
fi

if [ "$fail" -eq 0 ]; then verdict=PASS; rc=0; else verdict=FAIL; rc=1; fi
tail_note=""
if [ "$ran" -eq 0 ]; then
  # 何も検査していない回は PASS にしない。このセッションで書いた文書を引数で渡して回し直す
  verdict=WARN; rc=3
  tail_note="。検査なし: 検査した文書も、${CMDS} の命令も無い。このセッションで書いた文書を引数で渡す"
fi
finish "$(printf 'RESULT: %s project-verify --%s (%d 件中 FAIL %d%s)' "$verdict" "$MODE" "$ran" "$fail" "$tail_note")" "$rc"
