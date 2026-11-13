#!/usr/bin/env bash
# tools/check-file.sh <ファイル>... — 直したファイルの検査を、種類で選んで回す。hooks が編集の直後に呼ぶ。
#   .md .mdc : check-ja（文体）。資料（docs/、tmp/flow/、tmp/ISSUE_*、tmp/PR_*、README.md、skills/*/references|examples）なら check-doc。
#              図（```mermaid）があれば check-mermaid。ja-fluent のスキルがあれば fluency-check（文の運び）
#              雛形と完成例（skills/*/templates|examples）と、写した先で AI が書く資料（tmp/flow/、tmp/ISSUE_*、tmp/PR_*）
#              なら check-persona（「秘書」「社長」の語。決まりは .company/rules/documents.md の 5 節）
#   .sh      : bash -n と shellcheck と、全角の字の直前の変数の波括弧
#   .py      : 構文（ast）
#   .mjs .js : node --check
#   .json    : jq
#   .yml .yaml : YAML の構文（ruby）。.github/ISSUE_TEMPLATE なら Issue フォームの検査も
# 写した先（<プロジェクト>/tmp/tools にあり、tmp/DEPLOYED.md がある）では、tmp/ の外のファイルは検査しない。
#   プロジェクト自身のファイル（英語の README、コメント入りの tsconfig.json、既存の台本）を、頼まれずに直させないため。
# 1 つでも FAIL なら終了コード 1。WARN の行は結果に通すが、終了コードには数えない。道具が無いことによる SKIP は FAIL と同じに扱う。
set -u
TOOLS="$(cd "$(dirname "$0")" && { /bin/pwd -P 2>/dev/null || pwd -P; })"
ROOT="$(cd "$TOOLS/.." && { /bin/pwd -P 2>/dev/null || pwd -P; })"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
fail=0
DEPLOYED=0
if [ "$(basename "$ROOT")" = "tmp" ] && [ -f "$ROOT/DEPLOYED.md" ]; then DEPLOYED=1; fi

real_path() {  # real_path <ファイル> → リンクをたどった実体の絶対パス（/tmp と /private/tmp のような別名もそろえる）
  # /bin/pwd -P を使うのは、bash 3.2 の組み込みの pwd -P が大文字小文字の違う綴りをそのまま返すため（APFS では同じ場所）
  local f="$1" d n=0
  while [ -L "$f" ] && [ "$n" -lt 20 ]; do
    n=$((n + 1))
    d="$(CDPATH='' cd "$(dirname "$f")" && { /bin/pwd -P 2>/dev/null || pwd -P; })" || return 1
    f="$(readlink "$f")" || return 1
    case "$f" in /*) ;; *) f="$d/$f" ;; esac
  done
  d="$(CDPATH='' cd "$(dirname "$f")" 2>/dev/null && { /bin/pwd -P 2>/dev/null || pwd -P; })" || return 1
  printf '%s/%s\n' "$d" "$(basename "$f")"
}

is_doc() {
  case "$1" in
    */docs/*|docs/*|*/tmp/flow/*|tmp/flow/*|*/tmp/ISSUE_*|tmp/ISSUE_*|*/tmp/PR_*|tmp/PR_*|*/README.md|README.md|*/references/*|*/examples/*) return 0 ;;
  esac
  return 1
}

persona_target() {  # persona_target <ファイル> → 「秘書」「社長」の語を見る文書か（雛形と完成例、写した先で AI が書く資料）
  local rp
  rp="$(real_path "$1")" || return 1
  case "$rp" in
    "$ROOT"/skills/*/templates/*|"$ROOT"/skills/*/examples/*) return 0 ;;
  esac
  if [ "$DEPLOYED" -eq 1 ]; then
    case "$rp" in "$ROOT"/flow/*|"$ROOT"/ISSUE_*|"$ROOT"/PR_*) return 0 ;; esac
  fi
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
    printf '%s\n' "$out" | grep -E '^WARN' || :
    printf '%s\n' "$out" | grep -E '^(FAIL|RESULT:)' || printf '%s\n' "$out" | head -20 | sed "s|^|FAIL $f [$name] |"
    printf 'RESULT: FAIL %s %s\n' "$name" "$f"
  else
    printf '%s\n' "$out" | grep -E '^WARN' || :
    printf '%s\n' "$out" | grep -E '^RESULT:' || printf 'RESULT: PASS %s %s\n' "$name" "$f"
  fi
}

for f in "$@"; do
  [ -f "$f" ] || { printf 'FAIL %s [無い] ファイルが無い\n' "$f"; fail=$((fail + 1)); continue; }
  if [ "$DEPLOYED" -eq 1 ]; then
    case "$(real_path "$f")" in
      "$ROOT"/*) ;;
      *) printf 'RESULT: PASS check-file %s（写した先のプロジェクト自身のファイルは検査の対象外）\n' "$f"; continue ;;
    esac
  fi
  case "$f" in
    *.md|*.mdc)
      run check-ja "$f" python3 -I "$TOOLS/lib/check_ja.py" "$f"
      if is_doc "$f"; then run check-doc "$f" python3 -I "$TOOLS/lib/check_doc.py" "$f"; fi
      if persona_target "$f"; then run check-persona "$f" python3 -I "$TOOLS/lib/check_persona.py" "$f"; fi
      if grep -q '^```mermaid' "$f"; then run check-mermaid "$f" python3 -I "$TOOLS/lib/check_mermaid.py" "$f"; fi
      # 文の運び（ja-fluent のスキルがあれば。My-Lab では skills/、他のプロジェクトでは tmp/skills/）
      if [ -f "$ROOT/skills/ja-fluent/scripts/fluency-check.sh" ]; then run fluency-check "$f" bash "$ROOT/skills/ja-fluent/scripts/fluency-check.sh" "$f"; fi
      ;;
    *.sh)
      run bash-n "$f" bash -n "$f"
      if need shellcheck "$f"; then run shellcheck "$f" shellcheck -x -P "$ROOT" "$f"; else fail=$((fail + 1)); fi
      # 全角の字の直前の変数は、UTF-8 の設定の bash が字の一部まで名前と読む（set -u なら落ちる）。${名前} と書く
      run var-brace "$f" python3 -I "$TOOLS/lib/check_var_brace.py" "$f"
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
