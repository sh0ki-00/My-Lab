#!/usr/bin/env bash
# skills/frontend/scripts/frontend-gate.sh [--fast|--full] [<ディレクトリ>] — フロントエンドの検査を 1 コマンドで束ねる。
#   段: 型（tsc）→ lint（eslint）→ 単体（npm test）→ build → 初期表示の JS の大きさ（size-limit。段の名前は「束」）→ トークン（token-lint）→ 動き（motion-lint）
#       → 画面（axe と Lighthouse。tools/sample-app-test.mjs があり、対象が samples/app のとき）→ 依存（npm audit。--full だけ）
#   道具や設定が無い段は SKIP と理由を出し、FAIL とは数えない。導入は提案して承認を得る。
#   出力: 段ごとに [PASS]/[FAIL]/[SKIP] の 1 行と、最後に RESULT: PASS|FAIL frontend-gate (PASS n、FAIL m、SKIP k)。1 段でも FAIL なら終了コード 1。
# 使い方: frontend-gate.sh [--fast|--full] [<ディレクトリ>]   /   frontend-gate.sh --selftest
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
HERE="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
ROOT="$(cd "$HERE/../../.." && pwd -P)"
MODE="fast"; TARGET="."
for a in "$@"; do
  case "$a" in
    --fast) MODE="fast" ;;
    --full) MODE="full" ;;
    --selftest) MODE="selftest" ;;
    *) TARGET="$a" ;;
  esac
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
  if [ -f "$ROOT/tools/sample-app-test.mjs" ] && [ "$(cd "$dir" && pwd -P)" = "$ROOT/samples/app" ]; then
    stage "画面" node "$ROOT/tools/sample-app-test.mjs"
  else skipit "画面" "axe と Lighthouse の実行の仕組みが無い（tools/sample-app-test.mjs の型で用意する）"; fi
  if [ "$MODE" = "full" ]; then
    if [ -f "$dir/package-lock.json" ]; then stage "依存" npm audit --prefix "$dir" --audit-level=high; else skipit "依存" "package-lock.json が無い"; fi
  else skipit "依存" "--full のときだけ回す"; fi
  local verdict="PASS"; [ "$fail" -eq 0 ] || verdict="FAIL"
  echo "RESULT: $verdict frontend-gate $dir (PASS $pass、FAIL $fail、SKIP $skip)"
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
  if [ "$rc" -eq 0 ]; then echo "RESULT: PASS frontend-gate --selftest (4 例)"; else echo "RESULT: FAIL frontend-gate --selftest"; fi
  exit $rc
fi
run_gate "$TARGET"
