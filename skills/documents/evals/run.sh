#!/usr/bin/env bash
# skills/documents/evals/run.sh — documents の試験ケース。機械で判定できる分だけを回す。
#   1) cases/<名前>.md と cases/<名前>.expect（PASS か FAIL）を対にし、scripts/shape-check.sh の判定が期待と合うか。
#      cases/<名前>.args があれば、その中身（--kind 種類、--theirs）を shape-check.sh に渡す。
#   2) 完成例 examples/*.md が shape-check を通るか。
#   3) 雛形 templates/*.md が shape-check で落ちるか（〈…〉の印が残ったまま出せば落ちる）。
# 出力: ケースごとの行と、最後に RESULT: PASS|FAIL evals documents (<合格>/<全部>)。
set -u
HERE="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
SKILL="$(cd "$HERE/.." && pwd -P)"
CHECK="$SKILL/scripts/shape-check.sh"
pass=0; total=0
judge() {  # judge <名前> <期待> <実際>
  total=$((total + 1))
  if [ "$2" = "$3" ]; then pass=$((pass + 1)); printf 'PASS evals documents %s（期待 %s）\n' "$1" "$2"
  else printf 'FAIL evals documents %s（期待 %s、実際 %s）\n' "$1" "$2" "$3"; fi
}
for case_md in "$HERE"/cases/*.md; do
  [ -f "$case_md" ] || continue
  want="$(tr -d '[:space:]' < "${case_md%.md}.expect" 2>/dev/null || echo PASS)"
  args=""
  [ -f "${case_md%.md}.args" ] && args="$(tr -d '\n' < "${case_md%.md}.args")"
  # shellcheck disable=SC2086
  if bash "$CHECK" $args "$case_md" >/dev/null 2>&1; then got=PASS; else got=FAIL; fi
  judge "cases/$(basename "$case_md")" "$want" "$got"
done
for ex in "$SKILL"/examples/*.md; do
  [ -f "$ex" ] || continue
  if bash "$CHECK" "$ex" >/dev/null 2>&1; then got=PASS; else got=FAIL; fi
  judge "examples/$(basename "$ex")" PASS "$got"
done
for tp in "$SKILL"/templates/*.md; do
  [ -f "$tp" ] || continue
  if bash "$CHECK" "$tp" >/dev/null 2>&1; then got=PASS; else got=FAIL; fi
  judge "templates/$(basename "$tp")（埋めずに出すと落ちる）" FAIL "$got"
done
if [ "$pass" -eq "$total" ] && [ "$total" -gt 0 ]; then echo "RESULT: PASS evals documents ($pass/$total)"; exit 0; fi
echo "RESULT: FAIL evals documents ($pass/$total)"; exit 1
