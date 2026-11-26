#!/usr/bin/env bash
# skills/frontend/scripts/frontend-gate.sh [--fast|--full] [--plan <実装計画>] [--measure <計測の設定>] [<ディレクトリ>] — フロントエンドの検査を 1 コマンドで束ねる。
#   段: 型（tsc）→ lint（eslint）→ 単体（npm test）→ build → 初期表示の JS の大きさ（size-limit。段の名前は「束」）→ トークン（token-lint）→ 動き（motion-lint）
#       → 演出（motion-measure。--plan の計画書の「画面の型」が没入のときだけ）
#       → 画面（axe と Lighthouse。tools/sample-app-test.mjs があり、対象が samples/app のとき）→ 依存（npm audit。--full だけ）
#   演出の段: 計測の設定（既定は計画書と同じ置き場の motion-measure.json）で、対象の URL か置き場と、演出の ID を渡す。
#       没入の型で設定が無ければ FAIL。--full は 2 条件 × 3 回、--fast は 2 条件 × 1 回で測る。
#       画面の型は、見出しに「画面の型」を含む行で読む（** とバッククォートは外す。デザイナーの検査と同じ読み方）。
#       --plan があるのに行か値が読めなければ FAIL、没入でない型は SKIP と型を出す。--plan の無いときは、この段を出さない。
#       計画書と同じ置き場に design-plan.md があれば、両方の画面の型が同じかを確かめ、食い違えば「型の照合」で FAIL。
#   道具や設定が無い段は SKIP と理由を出し、FAIL とは数えない。導入は提案して承認を得る。
#   出力: 段ごとに [PASS]/[FAIL]/[SKIP] の 1 行と、最後に RESULT: PASS|FAIL frontend-gate (PASS n、FAIL m、SKIP k)。1 段でも FAIL なら終了コード 1。
# 使い方: frontend-gate.sh [--fast|--full] [--plan <実装計画>] [--measure <計測の設定>] [<ディレクトリ>]   /   frontend-gate.sh --selftest
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
HERE="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
ROOT="$(cd "$HERE/../../.." && pwd -P)"
MODE="fast"; TARGET="."; PLAN=""; MEASURE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --fast) MODE="fast" ;;
    --full) MODE="full" ;;
    --selftest) MODE="selftest" ;;
    --plan) case "${2:-}" in ""|--*) echo "FAIL frontend-gate [使い方] --plan のあとに実装計画のパスを渡す"; echo "RESULT: FAIL frontend-gate 使い方"; exit 2 ;; esac
            PLAN="$2"; shift ;;
    --measure) MEASURE="${2:-}"; shift ;;
    *) TARGET="$1" ;;
  esac
  shift
done
pass=0; fail=0; skip=0
clip() {  # clip <字数> → 標準入力の最初の行を、バイトではなく字で切る。cut -c は C ロケールでバイトを数え、和文の字を割って不正な UTF-8 を出す
  python3 -I -c 'import sys
n = int(sys.argv[1])
line = sys.stdin.buffer.read().decode("utf-8", "replace").split("\n", 1)[0]
sys.stdout.buffer.write(line[:n].encode("utf-8"))' "$1"
}
stage() {  # stage <名前> <コマンド...> → 実行して [PASS]/[FAIL]
  local name="$1"; shift
  local out rc
  out="$("$@" 2>&1)"; rc=$?
  if [ "$rc" -eq 0 ]; then pass=$((pass + 1)); printf '[PASS] %-10s %s\n' "$name" "$(printf '%s\n' "$out" | grep -E 'RESULT:|passed|ok' | tail -1 | clip 80)"
  else fail=$((fail + 1)); printf '[FAIL] %-10s %s\n' "$name" "$(printf '%s\n' "$out" | grep -E '^FAIL|error|Error' | head -1 | clip 100)"; printf '%s\n' "$out" | grep -E '^FAIL' | head -10; fi
}
skipit() { skip=$((skip + 1)); printf '[SKIP] %-10s %s\n' "$1" "$2"; }
failit() { fail=$((fail + 1)); printf '[FAIL] %-10s %s\n' "$1" "$2"; }
screen_type() {  # screen_type <実装計画> → 「画面の型」を見出しに含む行の値（** とバッククォートを外す）。行が無ければ「（行が無い）」
  python3 -I -c 'import sys
fence = False
clean = lambda c: c.replace("*", "").replace("`", "").strip()
for line in open(sys.argv[1], encoding="utf-8"):
    s = line.strip()
    if s.startswith("```"):
        fence = not fence
        continue
    if fence or not s.startswith("|"):
        continue
    cells = [clean(c) for c in s.strip("|").split("|")]
    if len(cells) >= 2 and "画面の型" in cells[0]:
        print(cells[1] or "（値が空）")
        break
else:
    print("（行が無い）")' "$1"
}
type_word() {  # type_word <画面の型の値> → 没入・既存・今 のどれか（読めなければ空）
  case "$1" in 没入*) echo 没入 ;; 既存に合わせる*) echo 既存 ;; 今の型*) echo 今 ;; *) echo "" ;; esac
}
scene_stage() {  # scene_stage <ディレクトリ> → 計画書の画面の型が没入なら、演出の段（motion-measure）を回す
  local dir="$1" kind cfg dplan dkind
  [ -n "$PLAN" ] || return 0
  [ -f "$PLAN" ] || { failit "演出" "計画書 $PLAN が無い"; return 0; }
  kind="$(screen_type "$PLAN")"
  # 同じ置き場にデザイン計画書があれば、画面の型が同じかを確かめる（受付票の型を、両方が写しているはず）
  dplan="$(dirname "$PLAN")/design-plan.md"
  if [ -f "$dplan" ]; then
    dkind="$(screen_type "$dplan")"
    if [ -n "$(type_word "$kind")" ] && [ -n "$(type_word "$dkind")" ] && [ "$(type_word "$kind")" != "$(type_word "$dkind")" ]; then
      failit "型の照合" "実装計画の画面の型は「${kind}」、デザイン計画書（${dplan}）は「${dkind}」。受付票の型にそろえる"
    fi
  fi
  case "$kind" in
    没入*) ;;
    既存に合わせる*|今の型*) skipit "演出" "画面の型は「${kind}」。演出の段は没入の型だけ"; return 0 ;;
    *) failit "演出" "計画書 ${PLAN} の画面の型が読めない（${kind}）。没入の型・既存に合わせる型・今の型のどれかを書く"; return 0 ;;
  esac
  cfg="${MEASURE:-$(dirname "$PLAN")/motion-measure.json}"
  if [ ! -f "$cfg" ]; then
    failit "演出" "画面の型が没入なのに、計測の設定 $cfg が無い（scene と、dir か url を書く。references/immersive.md の 7 節）"
  elif [ "$MODE" = "full" ]; then
    stage "演出" bash "$HERE/motion-measure.sh" --config "$cfg" --default-dir "$dir"
  else
    stage "演出" bash "$HERE/motion-measure.sh" --config "$cfg" --default-dir "$dir" --runs 1
  fi
}

run_gate() {
  local dir="$1"
  [ -d "$dir" ] || { echo "FAIL frontend-gate [対象] $dir が無い"; echo "RESULT: FAIL frontend-gate"; return 1; }
  local pkg="$dir/package.json"
  if [ -f "$dir/tsconfig.json" ]; then
    if [ -d "$dir/node_modules/typescript" ]; then stage "型" npx --prefix "$dir" tsc --noEmit -p "$dir"; else skipit "型" "tsconfig.json はあるが typescript が入っていない（npm ci を提案）"; fi
  else skipit "型" "tsconfig.json が無い"; fi
  if ls "$dir"/eslint.config.* "$dir"/.eslintrc* >/dev/null 2>&1; then
    if [ -d "$dir/node_modules/eslint" ]; then stage "lint" npx --prefix "$dir" eslint "$dir" --max-warnings 0; else skipit "lint" "eslint の設定はあるが eslint が入っていない"; fi
  else skipit "lint" "eslint の設定が無い"; fi
  if [ -f "$pkg" ] && grep -q '"test"' "$pkg"; then stage "単体" npm test --silent --prefix "$dir"; else skipit "単体" "package.json に test が無い"; fi
  if [ -f "$pkg" ] && grep -q '"build"' "$pkg"; then stage "build" npm run build --silent --prefix "$dir"; else skipit "build" "package.json に build が無い"; fi
  if [ -f "$dir/.size-limit.json" ] || { [ -f "$pkg" ] && grep -q '"size-limit"' "$pkg"; }; then
    if [ -d "$dir/node_modules/size-limit" ]; then stage "束" npx --prefix "$dir" size-limit; else skipit "束" "size-limit の設定はあるが size-limit が入っていない"; fi
  else skipit "束" "size-limit の設定が無い"; fi
  stage "トークン" bash "$HERE/token-lint.sh" "$dir"
  stage "動き" bash "$HERE/motion-lint.sh" "$dir"
  scene_stage "$dir"
  if [ -f "$ROOT/tools/sample-app-test.mjs" ] && [ "$(cd "$dir" && pwd -P)" = "$ROOT/samples/app" ]; then
    stage "画面" node "$ROOT/tools/sample-app-test.mjs"
  else skipit "画面" "axe と Lighthouse の実行の仕組みが無い（tools/sample-app-test.mjs の型で用意する）"; fi
  if [ "$MODE" = "full" ]; then
    if [ -f "$dir/package-lock.json" ]; then stage "依存" npm audit --prefix "$dir" --audit-level=high; else skipit "依存" "package-lock.json が無い"; fi
  else skipit "依存" "--full のときだけ回す"; fi
  local verdict="PASS"; [ "$fail" -eq 0 ] || verdict="FAIL"
  echo "RESULT: $verdict frontend-gate $dir (PASS ${pass}、FAIL ${fail}、SKIP $skip)"
  [ "$fail" -eq 0 ]
}

if [ "$MODE" = "selftest" ]; then
  rc=0
  out="$(MODE=fast; run_gate "$HERE/../evals/fixtures/good-app")"
  printf '%s\n' "$out" | grep -q '^RESULT: PASS frontend-gate' || { echo "FAIL selftest: 正例の good-app が PASS にならない"; printf '%s\n' "$out" | tail -3; rc=1; }
  pass=0; fail=0; skip=0
  out="$(run_gate "$HERE/../evals/fixtures/bad-app")"
  printf '%s\n' "$out" | grep -q '^\[FAIL\] トークン' || { echo "FAIL selftest: 負例の bad-app でトークンの段が落ちない"; rc=1; }
  printf '%s\n' "$out" | grep -q '^\[FAIL\] 動き' || { echo "FAIL selftest: 負例の bad-app で動きの段が落ちない"; rc=1; }
  printf '%s\n' "$out" | grep -q '^RESULT: FAIL frontend-gate' || { echo "FAIL selftest: 負例が FAIL にならない"; rc=1; }
  printf '%s\n' "$out" | python3 -I -c 'import sys; sys.stdin.buffer.read().decode("utf-8")' 2>/dev/null || { echo "FAIL selftest: 負例の出力に不正な UTF-8 がある"; rc=1; }
  # 和文の字を割らずに切る（バイトで切ると 7 バイト目で「生」の途中になる）
  [ "$(printf '%s\n' 'FAIL 生の色の検査' | clip 7)" = 'FAIL 生の' ] || { echo "FAIL selftest: clip が和文を字で切らない"; rc=1; }
  # 演出の段: 没入の型で設定が無い、設定の URL が外、没入でない型。どれもブラウザを起こさない
  tmpd="$(mktemp -d)" || exit 1
  good="$HERE/../evals/fixtures/good-app"
  printf '# 実装計画: 試験\n\n| 項目 | 内容 |\n|---|---|\n| 画面の型 | 没入 |\n' > "$tmpd/frontend-plan.md"
  printf '# 実装計画: 試験\n\n| 項目 | 内容 |\n|---|---|\n| 画面の型 | 既存に合わせる |\n' > "$tmpd/plan-existing.md"
  pass=0; fail=0; skip=0
  out="$(PLAN="$tmpd/frontend-plan.md"; run_gate "$good")"
  printf '%s\n' "$out" | grep -q '^\[FAIL\] 演出.*計測の設定' || { echo "FAIL selftest: 没入の型で計測の設定が無いのに、演出の段が落ちない"; rc=1; }
  printf '{"scene": "start-to-login", "url": "https://example.com/"}\n' > "$tmpd/motion-measure.json"
  pass=0; fail=0; skip=0
  out="$(PLAN="$tmpd/frontend-plan.md"; run_gate "$good")"
  printf '%s\n' "$out" | grep -q '^\[FAIL\] 演出' || { echo "FAIL selftest: 計測の設定の URL が外なのに、演出の段が落ちない"; rc=1; }
  printf '%s\n' "$out" | grep -q '127.0.0.1' || { echo "FAIL selftest: 外の URL を断った理由が出ない"; rc=1; }
  pass=0; fail=0; skip=0
  out="$(PLAN="$tmpd/plan-existing.md"; run_gate "$good")"
  printf '%s\n' "$out" | grep -q '^\[SKIP\] 演出.*既存に合わせる' || { echo "FAIL selftest: 既存に合わせる型で、演出の段が SKIP と型を出さない"; rc=1; }
  printf '%s\n' "$out" | grep -q '^RESULT: PASS frontend-gate' || { echo "FAIL selftest: 既存に合わせる型の正例が PASS にならない"; rc=1; }
  # 見出しの書き方が違っても、デザイナーの検査と同じく没入と読む。行が無い計画書は、演出の段で落ちる
  rm -f "$tmpd/motion-measure.json"
  # shellcheck disable=SC2016  # バッククォートは計画書の書き方そのもので、展開しない
  for head in '| 画面の型（受付票の写し） | 没入の型 |' '| **画面の型** | `没入の型` |'; do
    printf '# 実装計画: 試験\n\n| 項目 | 内容 |\n|---|---|\n%s\n' "$head" > "$tmpd/frontend-plan.md"
    pass=0; fail=0; skip=0
    out="$(PLAN="$tmpd/frontend-plan.md"; run_gate "$good")"
    printf '%s\n' "$out" | grep -q '^\[FAIL\] 演出.*計測の設定' || { echo "FAIL selftest: 「${head}」を没入の型と読まない"; rc=1; }
  done
  printf '# 実装計画: 試験\n\n| 項目 | 内容 |\n|---|---|\n| 作成日 | 2026-11-26 |\n' > "$tmpd/frontend-plan.md"
  pass=0; fail=0; skip=0
  out="$(PLAN="$tmpd/frontend-plan.md"; run_gate "$good")"
  printf '%s\n' "$out" | grep -q '^\[FAIL\] 演出.*画面の型が読めない' || { echo "FAIL selftest: 画面の型の行が無い計画書で、演出の段が落ちない"; rc=1; }
  # 同じ置き場のデザイン計画書と型が食い違えば落ちる
  printf '# 実装計画: 試験\n\n| 項目 | 内容 |\n|---|---|\n| 画面の型 | 今の型 |\n' > "$tmpd/frontend-plan.md"
  printf '# デザイン計画書: 試験\n\n| 項目 | 内容 |\n|---|---|\n| 画面の型 | 没入の型。材料は架空 |\n' > "$tmpd/design-plan.md"
  pass=0; fail=0; skip=0
  out="$(PLAN="$tmpd/frontend-plan.md"; run_gate "$good")"
  printf '%s\n' "$out" | grep -q '^\[FAIL\] 型の照合' || { echo "FAIL selftest: デザイン計画書と型が食い違うのに落ちない"; rc=1; }
  rm -rf "$tmpd"
  if [ "$rc" -eq 0 ]; then echo "RESULT: PASS frontend-gate --selftest (12 例)"; else echo "RESULT: FAIL frontend-gate --selftest"; fi
  exit $rc
fi
run_gate "$TARGET"
