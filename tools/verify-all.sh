#!/usr/bin/env bash
# tools/verify-all.sh [--fast|--full] — 11 種類の検証を 1 本で回す（仕様書 9.4 節）。
#   --fast : 1 形式、2 文体・資料・図、4 固有の検査の自己試験、6 hooks の自己試験、8 参照の実在、9 スクリプトの静的検査
#   --full : fast に加えて 3 図の実描画、5 試験ケース、7 配置の試験、10 見本アプリの実測、11 秘密と依存
# 出力: 検証ごとの RESULT 行と、最後に RESULT: PASS|FAIL verify-all。1 つでも FAIL なら終了コード 1。
# 記録: --full は docs/verify/<日付>.md に書く（同じ日は実行の節を足す）。--fast は tmp/.verify/last-fast.txt に書く。
#       PASS なら tmp/.verify/last-pass を更新する。hooks は、これより新しいファイルがあるか、通ったときの一覧（last-pass.list）とファイルの一覧が違うときに検証を回す。
# 道具が無いことによる SKIP は FAIL と同じに扱う。SKIP の行は出さない。
set -u
TOOLS="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
ROOT="$(cd "$TOOLS/.." && pwd -P)" || exit 1
# 他のプロジェクトの tmp/ に写した版では回さない。一式の自己検査になり、記録も tmp/tmp/.verify に書いてしまう。
if [ "$(basename "$ROOT")" = "tmp" ]; then
  echo "verify-all: これは My-Lab の一式の検証です。他のプロジェクトでは bash tmp/tools/project-verify.sh --fast（または --full）を使う"
  echo "RESULT: FAIL verify-all (写した先では回さない。tmp/tools/project-verify.sh を使う)"
  exit 2
fi
cd "$ROOT" || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"

MODE="fast"
case "${1:-}" in
  --full) MODE="full" ;;
  --fast|"") MODE="fast" ;;
  *) echo "使い方: tools/verify-all.sh [--fast|--full]"; exit 2 ;;
esac
DATE="$(date '+%Y-%m-%d')"
TIME="$(date '+%H:%M')"
LOGDIR="$ROOT/tmp/.verify"
mkdir -p "$LOGDIR" "$ROOT/docs/verify"
LOG="$LOGDIR/verify-$MODE.log"
: > "$LOG"
NAMES=(); RESULTS=(); NOTES=(); DURS=()
T_START=$(date +%s)

# ---- 部品
# 除外: どの階層の node_modules と .git、tmp/、.claude/worktrees/（アプリが作る別の作業ツリー。中に node_modules も入る）
md_files()      { find . -name node_modules -prune -o -path ./tmp -prune -o -name .git -prune -o -path ./.claude/worktrees -prune -o \( -name '*.md' -o -name '*.mdc' \) -type f -print | sort; }
doc_files()     { md_files | grep -E '^\./(docs/|README\.md$|skills/[^/]+/(references|examples)/)' || true; }
mermaid_files() { md_files | xargs grep -l '^```mermaid' 2>/dev/null || true; }
sh_files()      { find . -name node_modules -prune -o -path ./tmp -prune -o -name .git -prune -o -path ./.claude/worktrees -prune -o -name '*.sh' -type f -print | sort; }
json_files()    { find . -name node_modules -prune -o -path ./tmp -prune -o -name .git -prune -o -path ./.claude/worktrees -prune -o -name '*.json' -type f -print | sort; }
need() { command -v "$1" >/dev/null 2>&1 || { printf 'FAIL [道具が無い] %s が入っていない（SKIP は FAIL と同じ。段階 0 で入れた道具が消えている）\n' "$1"; return 1; }; }

step() {  # step <番号> <名前> <コマンド...> → 実行し、結果を記録する
  local no="$1" name="$2"; shift 2
  local t0 t1 out rc verdict note
  t0=$(date +%s)
  out="$("$@" 2>&1)"; rc=$?
  t1=$(date +%s)
  printf '### %s %s (rc=%s, %s 秒)\n%s\n\n' "$no" "$name" "$rc" "$((t1 - t0))" "$out" >> "$LOG"
  verdict="PASS"; [ "$rc" -eq 0 ] || verdict="FAIL"
  note="$(printf '%s\n' "$out" | grep -E '^FAIL' | head -1 | cut -c1-120)"
  NAMES+=("$no $name"); RESULTS+=("$verdict"); NOTES+=("$note"); DURS+=("$((t1 - t0))")
  printf 'RESULT: %s %s %s (%s 秒)\n' "$verdict" "$no" "$name" "$((t1 - t0))"
  [ "$rc" -eq 0 ] || printf '%s\n' "$out" | grep -E '^FAIL' | head -15
}

# ---- 検証の本体
v_format() {  # 1 形式: スキルの構成、JSON、常時ルールの frontmatter、Python と Node の構文
  local rc=0 f
  bash "$TOOLS/check-skill.sh" || rc=1
  need jq || return 1
  for f in $(json_files); do jq -e . "$f" >/dev/null 2>&1 || { printf 'FAIL %s [json] 読めない\n' "$f"; rc=1; }; done
  for f in .cursor/rules/*.mdc; do
    [ -f "$f" ] || continue
    if ! { head -1 "$f" | grep -q '^---$' && grep -q '^description:' "$f" && grep -q '^alwaysApply:' "$f"; }; then
      printf 'FAIL %s [mdc] frontmatter に description と alwaysApply が要る\n' "$f"; rc=1
    fi
  done
  for f in "$TOOLS"/lib/*.py; do python3 -I -c 'import ast, sys; ast.parse(open(sys.argv[1], encoding="utf-8").read(), sys.argv[1])' "$f" || { printf 'FAIL %s [python] 構文\n' "$f"; rc=1; }; done
  for f in "$TOOLS"/*.mjs; do [ -f "$f" ] && { node --check "$f" || { printf 'FAIL %s [node] 構文\n' "$f"; rc=1; }; }; done
  for f in .github/ISSUE_TEMPLATE/*.yml; do
    [ -f "$f" ] || continue
    bash "$TOOLS/check-file.sh" "$f" | grep -E '^FAIL' && rc=1
  done
  return $rc
}
v_style() {  # 2 文体・資料・図
  local rc=0 files docs mm
  files="$(md_files)"; docs="$(doc_files)"; mm="$(mermaid_files)"
  # shellcheck disable=SC2086
  [ -n "$files" ] && { python3 -I "$TOOLS/lib/check_ja.py" $files || rc=1; }
  # shellcheck disable=SC2086
  [ -n "$docs" ] && { python3 -I "$TOOLS/lib/check_doc.py" $docs || rc=1; }
  # shellcheck disable=SC2086
  [ -n "$mm" ] && { python3 -I "$TOOLS/lib/check_mermaid.py" $mm || rc=1; }
  return $rc
}
v_render() {  # 3 図の実描画
  local mm; mm="$(mermaid_files)"
  need node || return 1
  [ -n "$mm" ] || { echo "RESULT: PASS render-mermaid (0 図)"; return 0; }
  # shellcheck disable=SC2086
  node "$TOOLS/render-mermaid.mjs" $mm
}
v_selftests() {  # 4 固有の検査の自己試験: tools の検査と、各スキルの scripts/
  local rc=0 f
  for f in "$TOOLS"/lib/check_*.py; do python3 -I "$f" --selftest || rc=1; done
  for f in skills/*/scripts/*.sh; do [ -f "$f" ] && { bash "$f" --selftest || { printf 'FAIL %s [自己試験]\n' "$f"; rc=1; }; }; done
  return $rc
}
v_evals() {  # 5 試験ケース
  local rc=0 f n=0
  for f in skills/*/evals/run.sh; do [ -f "$f" ] || continue; n=$((n + 1)); bash "$f" || { printf 'FAIL %s [evals]\n' "$f"; rc=1; }; done
  [ "$n" -gt 0 ] || echo "RESULT: PASS evals (スキルが 0 本)"
  return $rc
}
v_hooks() {  # 6 hooks の自己試験。C と、社長の端末と同じ UTF-8 の文字の設定の 2 つで回す（AI の道具は C なので、C だけでは落ちる所が隠れる）
  local rc=0
  if ! locale -a 2>/dev/null | grep -qx 'ja_JP.UTF-8'; then printf 'FAIL [道具が無い] 文字の設定 ja_JP.UTF-8 が無い（SKIP は FAIL と同じ）\n'; return 1; fi
  bash hooks/selftest.sh || rc=1
  echo "（UTF-8 の文字の設定で、もう一度）"
  LC_ALL=ja_JP.UTF-8 bash hooks/selftest.sh || rc=1
  return $rc
}
v_placement() { bash "$TOOLS/placement-test.sh"; }         # 7 配置の試験
v_refs()      { bash "$TOOLS/check-refs.sh"; }             # 8 参照の実在
v_shellcheck() {  # 9 スクリプトの静的検査: shellcheck と、全角の字の直前の変数（tools/lib/check_var_brace.py）
  local files n rc=0; files="$(sh_files)"; n="$(printf '%s\n' "$files" | wc -l | tr -d ' ')"
  need shellcheck || return 1
  # shellcheck disable=SC2086
  if shellcheck -x -P "$ROOT" $files; then echo "RESULT: PASS shellcheck ($n 本)"; else rc=1; fi
  # shellcheck disable=SC2086
  if python3 -I "$TOOLS/lib/check_var_brace.py" $files; then echo "RESULT: PASS var-brace ($n 本)"; else rc=1; fi
  return $rc
}
v_sample() {  # 10 見本アプリの実測
  need node || return 1
  node "$TOOLS/sample-app-test.mjs"
}
v_secrets() {  # 11 秘密と依存
  local rc=0
  need gitleaks && { gitleaks dir . --config .gitleaks.toml --no-banner --redact --exit-code 1 >/dev/null 2>"$LOGDIR/gitleaks.err" \
    && echo "RESULT: PASS gitleaks (秘密 0 件)" || { printf 'FAIL gitleaks [秘密] %s\n' "$(grep -E 'leaks found|Finding' "$LOGDIR/gitleaks.err" | head -1)"; rc=1; }; } || rc=1
  need trivy && { trivy fs --scanners vuln,misconfig --severity HIGH,CRITICAL --exit-code 1 --skip-dirs node_modules,tmp --quiet . >"$LOGDIR/trivy.out" 2>&1 \
    && echo "RESULT: PASS trivy (HIGH 以上 0 件)" || { printf 'FAIL trivy [依存] %s\n' "$(grep -E 'Total:|CRITICAL|HIGH' "$LOGDIR/trivy.out" | head -1)"; rc=1; }; } || rc=1
  need semgrep && { semgrep scan --config "$TOOLS/semgrep" --error --quiet --metrics=off . >"$LOGDIR/semgrep.out" 2>&1 \
    && echo "RESULT: PASS semgrep (自前の規則、指摘 0 件)" || { printf 'FAIL semgrep [静的検査] %s\n' "$(grep -vE '^\s*$' "$LOGDIR/semgrep.out" | head -1)"; rc=1; }; } || rc=1
  return $rc
}

# ---- 実行
step 1 "形式" v_format
step 2 "文体・資料・図" v_style
[ "$MODE" = "full" ] && step 3 "図の実描画" v_render
step 4 "固有の検査の自己試験" v_selftests
[ "$MODE" = "full" ] && step 5 "試験ケース" v_evals
step 6 "hooks の自己試験" v_hooks
[ "$MODE" = "full" ] && step 7 "配置の試験" v_placement
step 8 "参照の実在" v_refs
step 9 "スクリプトの静的検査" v_shellcheck
[ "$MODE" = "full" ] && step 10 "見本アプリの実測" v_sample
[ "$MODE" = "full" ] && step 11 "秘密と依存" v_secrets

# ---- 集計と記録
T_END=$(date +%s)
FAILS=0
for r in "${RESULTS[@]}"; do [ "$r" = "FAIL" ] && FAILS=$((FAILS + 1)); done
TOTAL="${#RESULTS[@]}"
VERDICT="PASS"; [ "$FAILS" -eq 0 ] || VERDICT="FAIL"

table() {
  local i
  printf '| # | 検証 | 結果 | 秒 | 最初の FAIL |\n|---|---|---|---|---|\n'
  for i in "${!NAMES[@]}"; do
    printf '| %s | %s | %s | %s |\n' "${NAMES[$i]}" "${RESULTS[$i]}" "${DURS[$i]}" "${NOTES[$i]//|/／}"
  done
}
RUN_FRAG="$LOGDIR/runs-$DATE.md"
{
  printf '## 実行（%s、--%s、全体 %s）\n\n' "$TIME" "$MODE" "$VERDICT"
  printf '%s 種類を %s 秒で回しました。秒は検証ごとの所要時間です。\n\n' "$TOTAL" "$((T_END - T_START))"
  table
  printf '\n'
} > "$LOGDIR/last-$MODE.txt"
if [ "$MODE" = "full" ]; then
  cat "$LOGDIR/last-full.txt" >> "$RUN_FRAG"
  RUNS=$(grep -c '^## 実行' "$RUN_FRAG")
  {
    printf '# 検証の記録: %s\n\n' "$DATE"
    printf '> **3 行でわかる要約**\n'
    printf '> 1. %s に tools/verify-all.sh --full を回した記録です。回数は %s 回です。\n' "$DATE" "$RUNS"
    printf '> 2. 最新の実行（%s）は、%s 種類のうち FAIL が %s 件で、全体は %s です。\n' "$TIME" "$TOTAL" "$FAILS" "$VERDICT"
    printf '> 3. FAIL があれば、その検証を直してからもう一度回します。PASS なら、完了報告の証拠としてこの記録を指します。\n\n'
    printf '## 1. 目的\n\n'
    printf '作業の最後に回した検証の結果を残し、完了報告の証拠にします。検証の中身は仕様書の 9.4 節にある 11 種類です。hooks（コマンドの直前と編集の直後に走る検査）が回した fast の結果は tmp/.verify/ に残ります。ここには --full の結果だけを書きます。\n\n'
    printf '10 の見本アプリの実測では、Lighthouse（Google の性能測定）と axe（アクセシビリティ検査）を使います。Playwright（ブラウザの自動操作）で画面も動かします。11 の秘密と依存では、gitleaks（秘密の検出）と trivy（依存の既知の穴）を使います。semgrep（コードの静的検査）は自前の規則で回します。1 日に複数回回したときは、実行ごとの節を下に足します。\n\n'
    awk -v n=1 '/^## 実行/{ n++; sub(/^## 実行/, "## " n ". 実行") } { print }' "$RUN_FRAG"
  } > "docs/verify/$DATE.md"
fi
[ "$VERDICT" = "PASS" ] && touch "$LOGDIR/last-pass"
printf 'RESULT: %s verify-all --%s (%s 種類、FAIL %s、%s 秒)\n' "$VERDICT" "$MODE" "$TOTAL" "$FAILS" "$((T_END - T_START))"
[ "$MODE" = "full" ] && printf '記録: docs/verify/%s.md（詳細は tmp/.verify/verify-full.log）\n' "$DATE"
[ "$VERDICT" = "PASS" ]
