#!/usr/bin/env bash
# tools/check-file.sh <ファイル>... — 直したファイルの検査を、種類で選んで回す。hooks が編集の直後に呼ぶ。
#   .md .mdc : check-ja（文体。禁則語として、tools/ja-terms.txt の現場の語の言い換えも見る）。
#              資料（docs/、tmp/flow/、tmp/ISSUE_*、tmp/PR_*、README.md、skills/*/references|examples）なら check-doc。
#              図（```mermaid）があれば check-mermaid。ja-fluent のスキルがあれば fluency-check（文の運び）
#              雛形と完成例（skills/*/templates|examples）と、移した先で AI が書く資料（tmp/flow/、tmp/ISSUE_*、tmp/PR_*）
#              なら check-persona（「秘書」「社長」の語。決まりは .company/rules/documents.md の 5 節）
#   .md 以外の文字のファイル（.sh .py .mjs .js .cjs .json .txt .tsv .yml .yaml .css .html .toml と、一覧に無い拡張子でも
#              NUL の字を含まない文字のファイル。.ts .tsx .go .rb .sql .vue など）:
#              check-terms（tools/lib/check_ja.py --terms。tools/ja-terms.txt の語だけを見る）と、種類ごとの次の検査
#   .sh      : bash -n と shellcheck と、全角の字の直前の変数の波括弧
#   .py      : 構文（ast）
#   .mjs .js .cjs : node --check
#   .json    : jq
#   .yml .yaml : YAML の構文（ruby）。.github/ISSUE_TEMPLATE なら Issue フォームの検査も
# 移した先（<プロジェクト>/tmp/tools にあり、tmp/DEPLOYED.md がある）で、tmp/ の外のファイル（プロジェクト自身のもの）は、
#   git の HEAD から足した行だけを check-terms で見る（.md も同じ）。ほかの検査は回さない。
#   英語の README、コメント入りの tsconfig.json、既存のスクリプトを、頼まれずに直させないため。
#   git が無いとき、git の作業ツリーの外のファイル、追跡していないファイル、commit が 1 つも無いときは、全体を check-terms で見る。
#   足した行は HEAD との差分で数えるので、人やほかのセッションが書いた、まだ commit していない行も入る。
#   自分が書いていない行や、git の意味でない語（プロジェクト自身の用語）で落ちたときは、書き換えずに依頼者に伺う
#   （読み方は skills/verify/references/checks.md の 1 節）。編集の前の中身との差分で見る直しは、まだ入れていない。
#   文字でない種類（画像など、NUL の字を含むファイル）と、空のファイルは検査しない。
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

is_text() {  # is_text <ファイル> → 現場の語を見る、文字のファイルか。主な拡張子か、NUL の字を含まない文字のファイル
  case "$1" in
    *.md|*.mdc|*.sh|*.py|*.mjs|*.js|*.cjs|*.json|*.txt|*.tsv|*.yml|*.yaml|*.css|*.html|*.toml) return 0 ;;
  esac
  # 一覧に無い拡張子（.ts .go .rb .sql .vue など）は中身で決める。grep -I は NUL の字を含むファイルを文字でないと見て、当たりにしない
  LC_ALL=C grep -Iq . "$1" 2>/dev/null
}

persona_target() {  # persona_target <ファイル> → 「秘書」「社長」の語を見る文書か（雛形と完成例、移した先で AI が書く資料）
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

terms() {  # terms <ファイル> → 現場の語の検査（ファイル全体）
  python3 -I "$TOOLS/lib/check_ja.py" --terms -- "$1"
}

added_lines() {  # added_lines <実体のパス> → git の HEAD から足した行の番号を「,」区切りで書く（足した行が無ければ空）
  # git が無い、作業ツリーの外、追跡していない、HEAD が無い（commit が 1 つも無い）、diff が取れないときは終了コード 1
  local d b out
  command -v git >/dev/null 2>&1 || return 1
  d="$(dirname "$1")"; b="$(basename "$1")"
  git -C "$d" --literal-pathspecs ls-files --error-unmatch -- "$b" >/dev/null 2>&1 || return 1
  git -C "$d" rev-parse -q --verify HEAD >/dev/null 2>&1 || return 1
  out="$(git -C "$d" --literal-pathspecs diff --no-color --no-ext-diff --no-textconv -U0 HEAD -- "$b" 2>/dev/null)" || return 1
  # 塊の見出し「@@ -a,b +c,d @@」から新しい側の行番号を数え、「+」の行の番号だけを書く（awk は文字の設定によらない C で回す）
  printf '%s\n' "$out" | LC_ALL=C awk '
    /^@@ / { h = $0; sub(/^@@ -[0-9]+(,[0-9]+)? [+]/, "", h); n = h + 0; inh = 1; next }
    !inh { next }
    /^[+]/ { printf "%s%d", sep, n; sep = ","; n++; next }
    /^ / { n++ }
  '
}

# shellcheck disable=SC2329  # run が名前で呼ぶ
terms_added() {  # terms_added <ファイル> → 移した先のプロジェクト自身のファイル。git の HEAD から足した行だけを見る（追跡外などは全体）
  local f="$1" rp lines
  rp="$(real_path "$f")" || rp="$f"
  if lines="$(added_lines "$rp")"; then
    python3 -I "$TOOLS/lib/check_ja.py" --terms --added-lines "$lines" -- "$f"
  else
    terms "$f"
  fi
}

for f in "$@"; do
  [ -f "$f" ] || { printf 'FAIL %s [無い] ファイルが無い\n' "$f"; fail=$((fail + 1)); continue; }
  if [ "$DEPLOYED" -eq 1 ]; then
    case "$(real_path "$f")" in
      "$ROOT"/*) ;;
      *)
        if is_text "$f"; then
          run check-terms "$f" terms_added "$f"
        else
          printf 'RESULT: PASS check-file %s（移した先のプロジェクト自身のファイルで、現場の語を見る種類でもないので検査の対象外）\n' "$f"
        fi
        continue ;;
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
      run check-terms "$f" terms "$f"
      run bash-n "$f" bash -n "$f"
      if need shellcheck "$f"; then run shellcheck "$f" shellcheck -x -P "$ROOT" "$f"; else fail=$((fail + 1)); fi
      # 全角の字の直前の変数は、UTF-8 の設定の bash が字の一部まで名前と読む（set -u なら落ちる）。${名前} と書く
      run var-brace "$f" python3 -I "$TOOLS/lib/check_var_brace.py" "$f"
      ;;
    *.py)
      run check-terms "$f" terms "$f"
      run python-syntax "$f" python3 -I -c 'import ast, sys; ast.parse(open(sys.argv[1], encoding="utf-8").read(), sys.argv[1])' "$f"
      ;;
    *.mjs|*.js|*.cjs)
      run check-terms "$f" terms "$f"
      run node-check "$f" node --check "$f"
      ;;
    *.json)
      run check-terms "$f" terms "$f"
      if need jq "$f"; then run json "$f" jq -e . "$f"; else fail=$((fail + 1)); fi
      ;;
    *.yml|*.yaml)
      run check-terms "$f" terms "$f"
      if need ruby "$f"; then
        run yaml "$f" ruby -ryaml -e 'YAML.load_file(ARGV[0]); puts "ok"' "$f"
        case "$f" in
          *ISSUE_TEMPLATE/config.yml) ;;
          *ISSUE_TEMPLATE/*.yml) [ -f "$TOOLS/check-issue-form.sh" ] && run issue-form "$f" bash "$TOOLS/check-issue-form.sh" "$f" ;;
        esac
      else fail=$((fail + 1)); fi
      ;;
    *.txt|*.tsv|*.css|*.html|*.toml)
      run check-terms "$f" terms "$f"
      ;;
    *)
      if is_text "$f"; then
        run check-terms "$f" terms "$f"
      else
        printf 'RESULT: PASS check-file %s（文字のファイルでないので検査の対象外）\n' "$f"
      fi
      ;;
  esac
done
[ "$fail" -eq 0 ]
