#!/usr/bin/env bash
# skills/ja-fluent/evals/run.sh — ja-fluent の試験ケース。機械で判定できる分だけを回す。
#   1) fixtures/stiff.txt（直す前の 5 組）が FAIL で、指摘が 10 件以上、読点・受身・冗長・翻訳調・カタカナ語の 5 種が出る。
#   2) fixtures/fluent.txt（直した後の 5 組）が PASS。
#   3) fixtures/double-negative.txt が FAIL [二重否定]、fixtures/passive.txt が FAIL [受身]。
#   4) SKILL.md、references/*.md、examples/*.md、templates/*.md が PASS（決まりが自分の決まりを守る）。
# 出力: ケースごとの行と、最後に RESULT: PASS|FAIL evals ja-fluent (<合格>/<全部>)。
set -u
HERE="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
SKILL="$(cd "$HERE/.." && pwd -P)"
CHECK="$SKILL/scripts/fluency-check.sh"
pass=0; total=0
judge() {  # judge <名前> <合否 0/1> <内容>
  total=$((total + 1))
  if [ "$2" -eq 0 ]; then pass=$((pass + 1)); printf 'PASS evals ja-fluent %s\n' "$1"; else printf 'FAIL evals ja-fluent %s（%s）\n' "$1" "$3"; fi
}
out="$(bash "$CHECK" "$HERE/fixtures/stiff.txt" 2>&1)"
n="$(printf '%s\n' "$out" | grep -cE '^(FAIL|WARN) ')"
kinds=0; for k in 読点 受身 冗長 翻訳調 カタカナ語; do printf '%s\n' "$out" | grep -q "\[$k\]" && kinds=$((kinds + 1)); done
if printf '%s\n' "$out" | grep -q '^RESULT: FAIL' && [ "$n" -ge 10 ] && [ "$kinds" -eq 5 ]; then judge "stiff.txt は FAIL（指摘 $n 件、5 種）" 0 ""; else judge "stiff.txt は FAIL（指摘 10 件以上、5 種）" 1 "指摘 $n 件、種類 $kinds"; fi
out="$(bash "$CHECK" "$HERE/fixtures/fluent.txt" 2>&1)"
if printf '%s\n' "$out" | grep -q '^RESULT: PASS'; then judge "fluent.txt は PASS" 0 ""; else judge "fluent.txt は PASS" 1 "$(printf '%s\n' "$out" | grep '^FAIL' | head -2 | tr '\n' ' ')"; fi
for pair in "double-negative:二重否定" "passive:受身"; do
  f="${pair%%:*}"; rule="${pair#*:}"
  if bash "$CHECK" "$HERE/fixtures/$f.txt" 2>&1 | grep -q "^FAIL .*\[$rule\]"; then judge "$f.txt は FAIL [$rule]" 0 ""; else judge "$f.txt は FAIL [$rule]" 1 "出ない"; fi
done
for f in "$SKILL/SKILL.md" "$SKILL"/references/*.md "$SKILL"/examples/*.md "$SKILL"/templates/*.md; do
  [ -f "$f" ] || continue
  if bash "$CHECK" "$f" 2>&1 | grep -q '^RESULT: PASS'; then judge "$(basename "$f") は PASS" 0 ""; else judge "$(basename "$f") は PASS" 1 "$(bash "$CHECK" "$f" 2>&1 | grep '^FAIL' | head -2 | tr '\n' ' ')"; fi
done
if [ "$pass" -eq "$total" ] && [ "$total" -gt 0 ]; then echo "RESULT: PASS evals ja-fluent ($pass/$total)"; exit 0; fi
echo "RESULT: FAIL evals ja-fluent ($pass/$total)"; exit 1
