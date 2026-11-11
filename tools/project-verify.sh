#!/usr/bin/env bash
# tools/project-verify.sh [--fast|--full|--baseline] — 他のプロジェクト（tmp/ に写した版）で、作業を終える前の検証を回す。
#   既定: AI が tmp/ に書いた文書（tmp/flow/**/*.md、tmp/ISSUE_*.md、tmp/PR_*.md）だけを検査する。
#         検査は check-file.sh（文体と資料の型）と check-refs.sh（参照の実在）。
#         プロジェクト自身の lint・test・build は、自動では見つけない。
#         前から落ちている試験や、社長の手の変更を FAIL に数えないためである。
#   範囲: FAIL に数えるのは、最後に検証が通った印（tmp/.verify/last-pass）より新しい文書だけ。
#         それ以外の文書（範囲外）も同じ検査を回すが、「範囲外」で始まる行と WARN の 1 行で見せるだけで、FAIL にも件数にも数えない。
#         引き戻しの文「範囲外の FAIL は直さず、報告に書いて終える」と仕組みを揃え、前からある文書の FAIL で終われなくならないようにする。
#         印が無ければ、全部を範囲の中と見る（分からないときは、検査する側に倒す）。名前を変えただけの文書は時刻が古いままなので範囲外。
#   任意: 社長が <root>/tmp/verify-commands.txt に 1 行 1 命令で書く。
#         あれば、その命令を上から順に全部回す（--fast でも --full でも同じ）。# で始まる行と空行は飛ばす。
#         命令はプロジェクトの root で bash -c で回し、終了コードが 0 でなければ FAIL。
#   --baseline: 写した時点の印を置く。印（tmp/.verify/last-pass）を今の時刻にし、ファイルの一覧を tmp/.verify/last-pass.list に書く。検査は回さない。
#         deploy.sh が写した直後に呼び、前からある文書を範囲外にする。写した先でだけ使い、My-Lab の中では止まる（終了コード 2）。
#   root は、このファイルの場所から決める（<root>/tmp/tools/project-verify.sh → <root>。My-Lab の tools/ にあるときは My-Lab）。
# 出力: 検査と命令ごとの RESULT: PASS|FAIL <名前> の行と、最後に RESULT: PASS|FAIL project-verify --<mode>。
#   1 つでも FAIL なら終了コード 1。命令のファイルが無くても WARN にしない。
#   範囲の中の文書も命令も 1 つも無ければ、0 件の PASS（終了コード 0）。
# 記録: <root>/tmp/.verify/last-fast.txt（--full なら last-full.txt）に、日時と RESULT 行と範囲外の WARN 行を書く。
#       My-Lab の中で回したときは、verify-all.sh の記録を上書きしないよう project-verify-last-<mode>.txt に書く。
#       写した先で PASS なら、tmp/.verify/last-pass も更新する。接続口（hooks）は、これより新しいファイルがあるか、通ったときの一覧とファイルの一覧が違うときに検証を回す。
#       FAIL と、My-Lab の中で回したときは更新しない。
set -u
HERE="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
if [ "$(basename "$(dirname "$HERE")")" = "tmp" ]; then ROOT="$(cd "$HERE/../.." && pwd -P)"; RECORD_PREFIX="last"; else ROOT="$(cd "$HERE/.." && pwd -P)"; RECORD_PREFIX="project-verify-last"; fi
cd "$ROOT" || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
MODE="fast"
case "${1:-}" in --full) MODE="full" ;; --baseline) MODE="baseline" ;; --fast|"") MODE="fast" ;; *) echo "使い方: project-verify.sh [--fast|--full|--baseline]"; exit 2 ;; esac
CMDS="tmp/verify-commands.txt"
STAMP="tmp/.verify/last-pass"
LIST="tmp/.verify/last-pass.list"
fail=0; ran=0
STARTED="$(date '+%Y-%m-%d %H:%M:%S')"
SUMMARY=""

# tree_list → root の下のファイルの一覧（./ 始まり、文字の設定によらない順）。lib.sh（hooks）の tree_list と同じ形にする（変えるときは両方）
tree_list() {
  find . \( -name node_modules -o -name .git -o -name .verify -o -name dist -o -name build -o -name .next -o -name target -o -name vendor \) -prune -o -type f -print 2>/dev/null | LC_ALL=C sort
}

# in_scope <文書> → 最後に検証が通った印より新しければ 0。印が無ければ常に 0
#   bash の -nt は秒までしか見ないので、find -newer（ナノ秒まで見る。lib.sh の changed_since_pass と同じ）で比べる
in_scope() {
  [ -f "$STAMP" ] || return 0
  [ -n "$(find "$1" -newer "$STAMP" -print 2>/dev/null)" ]
}

run() {  # run <名前> <コマンド...> → 範囲の中の検査と命令。FAIL を数える
  local name="$1"; shift
  local out rc line
  ran=$((ran + 1))
  out="$("$@" 2>&1)"; rc=$?
  if [ "$rc" -eq 0 ]; then
    line="RESULT: PASS $name"
  else
    fail=$((fail + 1))
    # 名前（命令の文）に | や & が入っても壊れないよう、sed ではなく printf で前に付ける
    printf '%s\n' "$out" | tail -15 | while IFS= read -r l; do printf 'FAIL %s: %s\n' "$name" "$l"; done
    line="RESULT: FAIL $name (rc=$rc)"
  fi
  printf '%s\n' "$line"
  SUMMARY="$SUMMARY$line"$'\n'
}

outside_run() {  # outside_run <検査の名前> <コマンド...> → 範囲外の文書の検査。FAIL でも数えず、「範囲外」の行と WARN の 1 行で見せる
  local name="$1"; shift
  local out rc n line
  out="$("$@" 2>&1)"; rc=$?
  [ "$rc" -eq 0 ] && return 0
  n="$(printf '%s\n' "$out" | grep -c '^FAIL ')"
  printf '%s\n' "$out" | grep -E '^(FAIL|RESULT: FAIL)' | tail -15 | while IFS= read -r l; do printf '範囲外 %s\n' "$l"; done
  line="WARN 範囲外 ${name}（前からある文書 ${#outside[@]} 本）: FAIL の行 ${n}。最後に検証が通ったあとに変えていない文書なので、数えない。直さず、報告の未確認に書く"
  printf '%s\n' "$line"
  SUMMARY="$SUMMARY$line"$'\n'
}

finish() {  # finish <最後の RESULT 行> <終了コード> → 出力し、tmp/.verify/last-<mode>.txt に記録して終える
  printf '%s\n' "$1"
  if mkdir -p "$ROOT/tmp/.verify" 2>/dev/null; then
    { printf '日時: %s（終了 %s）\n' "$STARTED" "$(date '+%Y-%m-%d %H:%M:%S')"
      printf '命令: bash tmp/tools/project-verify.sh --%s\n' "$MODE"
      printf '%s' "$SUMMARY"
      printf '%s\n' "$1"; } > "$ROOT/tmp/.verify/$RECORD_PREFIX-$MODE.txt"
    # 写した先の PASS だけ、接続口の印（lib.sh の changed_since_pass が読む）を更新する
    if [ "$2" -eq 0 ] && [ "$RECORD_PREFIX" = "last" ]; then touch "$ROOT/$STAMP"; fi
  fi
  exit "$2"
}

# 1. AI が書いた文書。1 行 1 本で配列に入れ、空白を含むパスも 1 本のまま渡す。印より新しい文書（範囲の中）と、それ以外（範囲外）に分ける
#    （bash 3.2 は空の配列の "${docs[@]}" を set -u で落とすので、本数を先に見る）
#    一覧は変数に受けてヒアドキュメントで読む。プロセス置換 <( ) は、sh（POSIX の形の bash）で動かすと構文エラーになる
docs=(); outside=()
doclist="$({ find tmp/flow -name '*.md' -type f 2>/dev/null; ls tmp/ISSUE_*.md tmp/PR_*.md 2>/dev/null; } | LC_ALL=C sort -u)"
while IFS= read -r doc; do
  [ -n "$doc" ] || continue
  if in_scope "$doc"; then docs+=("$doc"); else outside+=("$doc"); fi
done <<EOF2
$doclist
EOF2

# --baseline: 写した時点の印と一覧を置いて終える。検査は回さない
if [ "$MODE" = "baseline" ]; then
  if [ "$RECORD_PREFIX" != "last" ]; then
    echo "FAIL project-verify --baseline: 写した先（<プロジェクト>/tmp/tools）でだけ使う。My-Lab では verify-all.sh が印を書く"
    exit 2
  fi
  mkdir -p tmp/.verify || exit 1
  if ! { tree_list > "$LIST.tmp" && mv -f "$LIST.tmp" "$LIST" && touch "$STAMP"; }; then
    rm -f "$LIST.tmp"
    echo "FAIL project-verify --baseline: tmp/.verify に印を書けない"
    exit 1
  fi
  n=$(( ${#docs[@]} + ${#outside[@]} ))
  printf 'project-verify: 写した時点の印（%s）と一覧（%s）を置いた。前からある tmp/ の文書 %d 本は、変えるまで範囲外\n' "$STAMP" "$LIST" "$n"
  exit 0
fi

if [ "${#docs[@]}" -gt 0 ]; then
  run "check-file（tmp の文書 ${#docs[@]} 本）" bash "$HERE/check-file.sh" "${docs[@]}"
  run "check-refs（tmp の文書 ${#docs[@]} 本）" bash "$HERE/check-refs.sh" "${docs[@]}"
fi
if [ "${#outside[@]}" -gt 0 ]; then
  outside_run "check-file" bash "$HERE/check-file.sh" "${outside[@]}"
  outside_run "check-refs" bash "$HERE/check-refs.sh" "${outside[@]}"
fi

# 2. 社長が書いた検証の命令（任意）。ファイルが無ければ何も回さない
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
note=""
if [ "$ran" -eq 0 ]; then
  if [ "${#outside[@]}" -gt 0 ]; then note="。最後に検証が通ったあとに変えた文書は無い（範囲外の文書 ${#outside[@]} 本は数えない）"
  else note="。検査する tmp/ の文書も、${CMDS} の命令も無い"; fi
fi
finish "$(printf 'RESULT: %s project-verify --%s (%d 件中 FAIL %d%s)' "$verdict" "$MODE" "$ran" "$fail" "$note")" "$rc"
