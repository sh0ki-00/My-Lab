#!/usr/bin/env bash
# skills/git-issue/evals/run.sh — git-issue の試験ケース。機械で判定できる分だけを回す。
#   1) cases/<名前>.md と cases/<名前>.expect（PASS か FAIL）を対にし、scripts/issue-check.sh の判定が期待と合うか。
#   2) 完成例 examples/issue-example.md が issue-check を通るか。
#   3) templates/*.yml が My-Lab の .github/ISSUE_TEMPLATE/ と同じ中身か（写しの食い違いを止める）。
# 出力: ケースごとの行と、最後に RESULT: PASS|FAIL evals git-issue (<合格>/<全部>)。
set -u
HERE="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
SKILL="$(cd "$HERE/.." && pwd -P)"
ROOT="$(cd "$SKILL/../.." && pwd -P)"
CHECK="$SKILL/scripts/issue-check.sh"
pass=0; total=0
judge() {  # judge <名前> <期待> <実際>
  total=$((total + 1))
  if [ "$2" = "$3" ]; then pass=$((pass + 1)); printf 'PASS evals git-issue %s（期待 %s）\n' "$1" "$2"
  else printf 'FAIL evals git-issue %s（期待 %s、実際 %s）\n' "$1" "$2" "$3"; fi
}
for case_md in "$HERE"/cases/*.md; do
  [ -f "$case_md" ] || continue
  want="$(tr -d '[:space:]' < "${case_md%.md}.expect" 2>/dev/null || echo PASS)"
  if bash "$CHECK" "$case_md" >/dev/null 2>&1; then got=PASS; else got=FAIL; fi
  judge "$(basename "$case_md")" "$want" "$got"
done
if bash "$CHECK" "$SKILL/examples/issue-example.md" >/dev/null 2>&1; then got=PASS; else got=FAIL; fi
judge "examples/issue-example.md" PASS "$got"
if [ -d "$ROOT/.github/ISSUE_TEMPLATE" ]; then
  for y in "$SKILL"/templates/*.yml; do
    [ -f "$y" ] || continue
    if cmp -s "$y" "$ROOT/.github/ISSUE_TEMPLATE/$(basename "$y")"; then got=PASS; else got=FAIL; fi
    judge "templates/$(basename "$y") が .github と同じ" PASS "$got"
  done
fi
if [ "$pass" -eq "$total" ] && [ "$total" -gt 0 ]; then echo "RESULT: PASS evals git-issue ($pass/$total)"; exit 0; fi
echo "RESULT: FAIL evals git-issue ($pass/$total)"; exit 1
