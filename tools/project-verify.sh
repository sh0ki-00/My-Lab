#!/usr/bin/env bash
# tools/project-verify.sh [--fast|--full] — 他のプロジェクト（tmp/ に写した版）で、作業を終える前の検証を回す。
#   既定: AI が tmp/ に書いた文書（tmp/flow/**/*.md、tmp/ISSUE_*.md、tmp/PR_*.md）だけを検査する。
#         検査は check-file.sh（文体と資料の型）と check-refs.sh（参照の実在）。
#         プロジェクト自身の lint・test・build は、自動では見つけない。
#         前から落ちている試験や、社長の手の変更を FAIL に数えないためである。
#   任意: 社長が <root>/tmp/verify-commands.txt に 1 行 1 命令で書く。
#         あれば、その命令を上から順に全部回す（--fast でも --full でも同じ）。# で始まる行と空行は飛ばす。
#         命令はプロジェクトの root で bash -c で回し、終了コードが 0 でなければ FAIL。
#   root は、このファイルの場所から決める（<root>/tmp/tools/project-verify.sh → <root>。My-Lab の tools/ にあるときは My-Lab）。
# 出力: 検査と命令ごとの RESULT: PASS|FAIL <名前> の行と、最後に RESULT: PASS|FAIL project-verify --<mode>。
#   1 つでも FAIL なら終了コード 1。命令のファイルが無くても WARN にしない。
#   文書も命令も 1 つも無ければ、0 件の PASS（終了コード 0）。
# 記録: <root>/tmp/.verify/last-fast.txt（--full なら last-full.txt）に、日時と RESULT 行を書く。
#       My-Lab の中で回したときは、verify-all.sh の記録を上書きしないよう project-verify-last-<mode>.txt に書く。
#       写した先で PASS なら、tmp/.verify/last-pass も更新する。hooks は、これより新しいファイルがあるか、通ったときの一覧とファイルの一覧が違うときに検証を回す。
#       FAIL と、My-Lab の中で回したときは更新しない。
set -u
HERE="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
if [ "$(basename "$(dirname "$HERE")")" = "tmp" ]; then ROOT="$(cd "$HERE/../.." && pwd -P)"; RECORD_PREFIX="last"; else ROOT="$(cd "$HERE/.." && pwd -P)"; RECORD_PREFIX="project-verify-last"; fi
cd "$ROOT" || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
MODE="fast"
case "${1:-}" in --full) MODE="full" ;; --fast|"") MODE="fast" ;; *) echo "使い方: project-verify.sh [--fast|--full]"; exit 2 ;; esac
CMDS="tmp/verify-commands.txt"
fail=0; ran=0
STARTED="$(date '+%Y-%m-%d %H:%M:%S')"
SUMMARY=""

run() {  # run <名前> <コマンド...>
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

finish() {  # finish <最後の RESULT 行> <終了コード> → 出力し、tmp/.verify/last-<mode>.txt に記録して終える
  printf '%s\n' "$1"
  if mkdir -p "$ROOT/tmp/.verify" 2>/dev/null; then
    { printf '日時: %s（終了 %s）\n' "$STARTED" "$(date '+%Y-%m-%d %H:%M:%S')"
      printf '命令: bash tmp/tools/project-verify.sh --%s\n' "$MODE"
      printf '%s' "$SUMMARY"
      printf '%s\n' "$1"; } > "$ROOT/tmp/.verify/$RECORD_PREFIX-$MODE.txt"
    # 写した先の PASS だけ、hooks の印（hooks/lib.sh の changed_since_pass が読む）を更新する
    if [ "$2" -eq 0 ] && [ "$RECORD_PREFIX" = "last" ]; then touch "$ROOT/tmp/.verify/last-pass"; fi
  fi
  exit "$2"
}

# 1. AI が書いた文書。1 行 1 本で配列に入れ、空白を含むパスも 1 本のまま渡す
#    （bash 3.2 は空の配列の "${docs[@]}" を set -u で落とすので、本数を先に見る）
#    一覧は変数に受けてヒアドキュメントで読む。プロセス置換 <( ) は、sh（POSIX の形の bash）で動かすと構文エラーになる
docs=()
doclist="$({ find tmp/flow -name '*.md' -type f 2>/dev/null; ls tmp/ISSUE_*.md tmp/PR_*.md 2>/dev/null; } | LC_ALL=C sort -u)"
while IFS= read -r doc; do
  [ -n "$doc" ] && docs+=("$doc")
done <<EOF
$doclist
EOF
if [ "${#docs[@]}" -gt 0 ]; then
  run "check-file（tmp の文書 ${#docs[@]} 本）" bash "$HERE/check-file.sh" "${docs[@]}"
  run "check-refs（tmp の文書 ${#docs[@]} 本）" bash "$HERE/check-refs.sh" "${docs[@]}"
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
[ "$ran" -eq 0 ] && note="。検査する tmp/ の文書も、${CMDS} の命令も無い"
finish "$(printf 'RESULT: %s project-verify --%s (%d 件中 FAIL %d%s)' "$verdict" "$MODE" "$ran" "$fail" "$note")" "$rc"
