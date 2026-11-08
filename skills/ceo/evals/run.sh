#!/usr/bin/env bash
# skills/ceo/evals/run.sh — ceo の試験ケース。機械で判定できる分だけを回す。
#   1) 完成例の事業判断メモと優先順位表が ceo-check を通る。雛形 2 点は穴埋めのままなので落ちる。
#   2) cases/<名前>.md と cases/<名前>.expect（「<引数> PASS|FAIL」。引数は - か --board）を対にし、判定が期待と合うか。
#   3) 壊した見本 cases/bad-judgment.md が、理由 6 つ（目的・判定・判断・KPI・やらないこと・収益性）をすべて出す。
# 出力: ケースごとの行と、最後に RESULT: PASS|FAIL evals ceo (<合格>/<全部>)。
set -u
HERE="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
SKILL="$(cd "$HERE/.." && pwd -P)"
CHECK="$SKILL/scripts/ceo-check.sh"
pass=0; total=0
judge() {  # judge <名前> <期待> <実際>
  total=$((total + 1))
  if [ "$2" = "$3" ]; then pass=$((pass + 1)); printf 'PASS evals ceo %s（期待 %s）\n' "$1" "$2"
  else printf 'FAIL evals ceo %s（期待 %s、実際 %s）\n' "$1" "$2" "$3"; fi
}
verdict() {  # verdict <ファイル> [--board] → PASS|FAIL
  if bash "$CHECK" "$@" >/dev/null 2>&1; then echo PASS; else echo FAIL; fi
}
judge "examples/judgment-order-list.md" PASS "$(verdict "$SKILL/examples/judgment-order-list.md")"
judge "examples/priority-board-order-list.md" PASS "$(verdict "$SKILL/examples/priority-board-order-list.md" --board)"
judge "templates/judgment.md（雛形は落ちる）" FAIL "$(verdict "$SKILL/templates/judgment.md")"
judge "templates/priority-board.md（雛形は落ちる）" FAIL "$(verdict "$SKILL/templates/priority-board.md" --board)"
for case_md in "$HERE"/cases/*.md; do
  [ -f "$case_md" ] || continue
  read -r arg want < "${case_md%.md}.expect"
  if [ "$arg" = "-" ]; then got="$(verdict "$case_md")"; else got="$(verdict "$case_md" "$arg")"; fi
  judge "cases/$(basename "$case_md")" "$want" "$got"
done
out="$(bash "$CHECK" "$HERE/cases/bad-judgment.md" 2>&1)"
for rule in 目的 判定 判断 KPI やらないこと 収益性; do
  if printf '%s\n' "$out" | grep -q "\[$rule\]"; then got=PASS; else got=FAIL; fi
  judge "cases/bad-judgment.md が「${rule}」で落ちる" PASS "$got"
done
if [ "$pass" -eq "$total" ] && [ "$total" -gt 0 ]; then echo "RESULT: PASS evals ceo ($pass/$total)"; exit 0; fi
echo "RESULT: FAIL evals ceo ($pass/$total)"; exit 1
