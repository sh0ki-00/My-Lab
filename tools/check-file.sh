#!/usr/bin/env bash
# tools/check-file.sh <ファイル>... — 直したファイルの検査を、種類で選んで回す。hooks が編集の直後に呼ぶ。
#   .md .mdc : check-ja（文体）。資料（docs/、tmp/flow/、tmp/ISSUE_*、tmp/PR_*、README.md、skills/*/references|examples）なら check-doc。
#              図（```mermaid）があれば check-mermaid。ja-fluent のスキルがあれば fluency-check（文の運び）
#   .sh      : bash -n と shellcheck
#   .py      : 構文（ast）
#   .mjs .js : node --check
#   .json    : jq
#   .yml .yaml : YAML の構文（ruby）。.github/ISSUE_TEMPLATE なら Issue フォームの検査も
# 1 つでも FAIL なら終了コード 1。道具が無いことによる SKIP は FAIL と同じに扱う。
set -u
TOOLS="$(cd "$(dirname "$0")" && pwd -P)"
ROOT="$(cd "$TOOLS/.." && pwd -P)"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
fail=0

is_doc() {
  case "$1" in
    */docs/*|docs/*|*/tmp/flow/*|tmp/flow/*|*/tmp/ISSUE_*|tmp/ISSUE_*|*/tmp/PR_*|tmp/PR_*|*/README.md|README.md|*/references/*|*/examples/*) return 0 ;;
  esac
  return 1
}

need() {  # need <道具> → 無ければ FAIL
  if ! command -v "$1" >/dev/null 2>&1; then
    printf 'FAIL %s [道具が無い] %s が入っていない（SKIP は FAIL と同じ）\n' "$2" "$1"
    return 1
  fi
}

run() {  # run <名前> <ファイル> <コマンド...> → FAIL なら fail を増やす
  local name="$1" f="$2"; shift 2
  local out rc
  out="$("$@" 2>&1)"; rc=$?
  if [ "$rc" -ne 0 ]; then
    fail=$((fail + 1))
    printf '%s\n' "$out" | grep -E '^(FAIL|RESULT:)' || printf '%s\n' "$out" | head -20 | sed "s|^|FAIL $f [$name] |"
    printf 'RESULT: FAIL %s %s\n' "$name" "$f"
  else
    printf '%s\n' "$out" | grep -E '^RESULT:' || printf 'RESULT: PASS %s %s\n' "$name" "$f"
  fi
}

for f in "$@"; do
  [ -f "$f" ] || { printf 'FAIL %s [無い] ファイルが無い\n' "$f"; fail=$((fail + 1)); continue; }
  case "$f" in
    *.md|*.mdc)
      run check-ja "$f" python3 -I "$TOOLS/lib/check_ja.py" "$f"
      if is_doc "$f"; then run check-doc "$f" python3 -I "$TOOLS/lib/check_doc.py" "$f"; fi
      if grep -q '^```mermaid' "$f"; then run check-mermaid "$f" python3 -I "$TOOLS/lib/check_mermaid.py" "$f"; fi
      # 文の運び（ja-fluent のスキルがあれば。My-Lab では skills/、他のプロジェクトでは tmp/skills/）
      if [ -f "$ROOT/skills/ja-fluent/scripts/fluency-check.sh" ]; then run fluency-check "$f" bash "$ROOT/skills/ja-fluent/scripts/fluency-check.sh" "$f"; fi
      ;;
    *.sh)
      run bash-n "$f" bash -n "$f"
      if need shellcheck "$f"; then run shellcheck "$f" shellcheck -x -P "$ROOT" "$f"; else fail=$((fail + 1)); fi
      ;;
    *.py)
      run python-syntax "$f" python3 -I -c 'import ast, sys; ast.parse(open(sys.argv[1], encoding="utf-8").read(), sys.argv[1])' "$f"
      ;;
    *.mjs|*.js|*.cjs)
      run node-check "$f" node --check "$f"
      ;;
    *.json)
      if need jq "$f"; then run json "$f" jq -e . "$f"; else fail=$((fail + 1)); fi
      ;;
    *.yml|*.yaml)
      if need ruby "$f"; then
        run yaml "$f" ruby -ryaml -e 'YAML.load_file(ARGV[0]); puts "ok"' "$f"
        case "$f" in
          *ISSUE_TEMPLATE/config.yml) ;;
          *ISSUE_TEMPLATE/*.yml) [ -f "$TOOLS/check-issue-form.sh" ] && run issue-form "$f" bash "$TOOLS/check-issue-form.sh" "$f" ;;
        esac
      else fail=$((fail + 1)); fi
      ;;
    *)
      printf 'RESULT: PASS check-file %s（検査の対象外）\n' "$f"
      ;;
  esac
done
[ "$fail" -eq 0 ]
