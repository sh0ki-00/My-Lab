#!/usr/bin/env bash
# skills/verify/evals/run.sh — verify スキルの試験ケース。機械で判定できる分だけを回す。
#   cases/<名前>.md と cases/<名前>.expect（PASS か FAIL）を対にし、scripts/report-check.sh の判定が期待と合うかを見る。
# 出力: ケースごとの行と、最後に RESULT: PASS|FAIL evals verify (<合格>/<全部>)。
set -u
HERE="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
CHECK="$HERE/../scripts/report-check.sh"
pass=0; total=0
for case_md in "$HERE"/cases/*.md; do
  [ -f "$case_md" ] || continue
  total=$((total + 1))
  want="$(tr -d '[:space:]' < "${case_md%.md}.expect" 2>/dev/null || echo PASS)"
  if bash "$CHECK" "$case_md" >/dev/null 2>&1; then got=PASS; else got=FAIL; fi
  if [ "$got" = "$want" ]; then
    pass=$((pass + 1))
    printf 'PASS evals verify %s（期待 %s）\n' "$(basename "$case_md")" "$want"
  else
    printf 'FAIL evals verify %s（期待 %s、実際 %s）\n' "$(basename "$case_md")" "$want" "$got"
  fi
done
if [ "$total" -eq 0 ]; then echo "FAIL evals verify: cases/ が空"; echo "RESULT: FAIL evals verify (0/0)"; exit 1; fi
if [ "$pass" -eq "$total" ]; then echo "RESULT: PASS evals verify ($pass/$total)"; exit 0; fi
echo "RESULT: FAIL evals verify ($pass/$total)"; exit 1
