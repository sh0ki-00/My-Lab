#!/usr/bin/env bash
# skills/frontend/evals/run.sh — frontend の試験ケース。機械で判定できる分だけを回す。
#   1) 完成例（実装計画、自己点検票）が各検査を通る。雛形は穴埋めのままなので落ちる。
#   2) 負例の fixture が名指しで落ちる: bad-plan（構成・状態・データ取得・性能予算・テスト・横断事項・雛形の穴）、
#      bad-self-check（判定・結果・推測・ゲートの出力・節）、bad-app（生の色・生の px・生の書体、動き・縮小版、gate が FAIL）。
#   3) 正例の fixture と見本アプリが通る: good-app（token-lint、motion-lint、gate）、samples/app（token-lint、motion-lint）。
# 出力: ケースごとの行と、最後に RESULT: PASS|FAIL evals frontend (<合格>/<全部>)。
set -u
HERE="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
SKILL="$(cd "$HERE/.." && pwd -P)"
ROOT="$(cd "$SKILL/../.." && pwd -P)"
S="$SKILL/scripts"
EX="$SKILL/examples"
FX="$HERE/fixtures"
pass=0; total=0
judge() {  # judge <名前> <期待> <実際>
  total=$((total + 1))
  if [ "$2" = "$3" ]; then pass=$((pass + 1)); printf 'PASS evals frontend %s（期待 %s）\n' "$1" "$2"
  else printf 'FAIL evals frontend %s（期待 %s、実際 %s）\n' "$1" "$2" "$3"; fi
}
verdict() {  # verdict <検査> <引数...> → PASS|FAIL
  if bash "$S/$1.sh" "${@:2}" >/dev/null 2>&1; then echo PASS; else echo FAIL; fi
}
has() {  # has <検査> <文言> <引数...> → PASS なら出力に文言がある
  if bash "$S/$1.sh" "${@:3}" 2>&1 | grep -q -- "$2"; then echo PASS; else echo FAIL; fi
}

# 1) 完成例と雛形
judge "examples/frontend-plan-order-list.md（実装計画）" PASS "$(verdict frontend-plan-check "$EX/frontend-plan-order-list.md")"
judge "examples/self-check-order-list.md（自己点検票）" PASS "$(verdict self-check "$EX/self-check-order-list.md")"
judge "templates/frontend-plan.md（雛形は落ちる）" FAIL "$(verdict frontend-plan-check "$SKILL/templates/frontend-plan.md")"
judge "templates/self-check.md（雛形は落ちる）" FAIL "$(verdict self-check "$SKILL/templates/self-check.md")"

# 2) 負例
for rule in 構成 状態 データ取得 性能予算 テスト 横断事項 雛形の穴; do
  judge "fixtures/bad-plan.md が「${rule}」で落ちる" PASS "$(has frontend-plan-check "\\[$rule\\]" "$FX/bad-plan.md")"
done
for rule in 判定 結果 推測 ゲートの出力 節; do
  judge "fixtures/bad-self-check.md が「${rule}」で落ちる" PASS "$(has self-check "\\[$rule\\]" "$FX/bad-self-check.md")"
done
for rule in 生の色 "生の px" 生の書体; do
  judge "fixtures/bad-app が「${rule}」で落ちる" PASS "$(has token-lint "\\[$rule\\]" "$FX/bad-app")"
done
for rule in 動き 縮小版; do
  judge "fixtures/bad-app が「${rule}」で落ちる" PASS "$(has motion-lint "\\[$rule\\]" "$FX/bad-app")"
done
judge "fixtures/bad-app で gate が FAIL" PASS "$(has frontend-gate '^RESULT: FAIL frontend-gate' "$FX/bad-app")"

# 3) 正例
judge "fixtures/good-app が token-lint を通る" PASS "$(verdict token-lint "$FX/good-app")"
judge "fixtures/good-app が motion-lint を通る" PASS "$(verdict motion-lint "$FX/good-app")"
judge "fixtures/good-app で gate が PASS" PASS "$(has frontend-gate '^RESULT: PASS frontend-gate' "$FX/good-app")"
judge "samples/app が token-lint を通る" PASS "$(verdict token-lint "$ROOT/samples/app")"
judge "samples/app が motion-lint を通る" PASS "$(verdict motion-lint "$ROOT/samples/app")"

if [ "$pass" -eq "$total" ] && [ "$total" -gt 0 ]; then echo "RESULT: PASS evals frontend ($pass/$total)"; exit 0; fi
echo "RESULT: FAIL evals frontend ($pass/$total)"; exit 1
