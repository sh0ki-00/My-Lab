#!/usr/bin/env bash
# skills/secretary/evals/run.sh — secretary の試験ケース。機械で判定できる分だけを回す。
#   1) 完成例 4 点が各検査を通り、承認伺いが gate-check を通る。雛形 4 点は穴埋めのままなので落ちる。
#   2) cases/<名前>.md と cases/<名前>.expect（「<検査名> PASS|FAIL」）を対にし、判定が期待と合うか。
#   3) 振り分け: routing-cases.tsv の全件を route で判定し、正答率が 95% 以上（44 件なら 42 件以上）。期待の「当たり無し」は、route が当たり無しと返すこと。
# 出力: ケースごとの行と、最後に RESULT: PASS|FAIL evals secretary (<合格>/<全部>)。
set -u
HERE="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
SKILL="$(cd "$HERE/.." && pwd -P)"
S="$SKILL/scripts"
EX="$SKILL/examples"
pass=0; total=0
judge() {  # judge <名前> <期待> <実際>
  total=$((total + 1))
  if [ "$2" = "$3" ]; then pass=$((pass + 1)); printf 'PASS evals secretary %s（期待 %s）\n' "$1" "$2"
  else printf 'FAIL evals secretary %s（期待 %s、実際 %s）\n' "$1" "$2" "$3"; fi
}
verdict() {  # verdict <検査> <ファイル> [追加の引数...] → PASS|FAIL
  if bash "$S/$1.sh" "${@:2}" >/dev/null 2>&1; then echo PASS; else echo FAIL; fi
}

# 1) 完成例と雛形
judge "examples/order-list-intake.md" PASS "$(verdict intake-check "$EX/order-list-intake.md")"
judge "examples/order-list-minutes.md" PASS "$(verdict minutes-check "$EX/order-list-minutes.md")"
judge "examples/order-list-approval-request.md" PASS "$(verdict approval-request-check "$EX/order-list-approval-request.md")"
judge "examples/order-list-approval-record.md" PASS "$(verdict approval-record-check "$EX/order-list-approval-record.md")"
judge "examples/order-list-approval-request.md（門）" PASS "$(verdict gate-check "$EX/order-list-approval-request.md")"
judge "examples/order-list-reply-designer.md" PASS "$(verdict reply-check "$EX/order-list-reply-designer.md")"
judge "templates/reply-from-role.md（雛形は落ちる）" FAIL "$(verdict reply-check "$SKILL/templates/reply-from-role.md")"
judge "templates/intake.md（雛形は落ちる）" FAIL "$(verdict intake-check "$SKILL/templates/intake.md")"
judge "templates/minutes.md（雛形は落ちる）" FAIL "$(verdict minutes-check "$SKILL/templates/minutes.md")"
judge "templates/approval-request.md（雛形は落ちる）" FAIL "$(verdict approval-request-check "$SKILL/templates/approval-request.md")"
judge "templates/approval-record.md（雛形は落ちる）" FAIL "$(verdict approval-record-check "$SKILL/templates/approval-record.md")"

# 2) 壊した見本
for case_md in "$HERE"/cases/*.md; do
  [ -f "$case_md" ] || continue
  read -r script want < "${case_md%.md}.expect"
  judge "cases/$(basename "$case_md")" "$want" "$(verdict "$script" "$case_md")"
done

# 3) 振り分け
norm() {  # "A+B" → 並べ替えた "A+B"。"-" と「秘書のみ」は "-"
  local s="$1"
  [ "$s" = "秘書のみ" ] && s="-"
  if [ "$s" = "-" ] || [ -z "$s" ]; then echo "-"; else printf '%s\n' "$s" | tr '+' '\n' | sort | paste -sd+ -; fi
}
n=0; correct=0
while IFS=$'\t' read -r text want || [ -n "${text:-}" ]; do
  case "$text" in ''|'#'*) continue ;; esac
  n=$((n + 1))
  got="$(python3 -I "$S/secretary_check.py" route "$text" | sed -n 's/^役割: //p')"
  if [ "$(norm "$want")" = "$(norm "$got")" ]; then correct=$((correct + 1))
  else printf 'FAIL evals secretary 振り分け「%s」（期待 %s、実際 %s）\n' "$text" "$want" "$got"; fi
done < "$HERE/routing-cases.tsv"
rate=0; [ "$n" -gt 0 ] && rate=$((correct * 100 / n))
if [ "$n" -gt 0 ] && [ $((correct * 20)) -ge $((n * 19)) ]; then got=PASS; else got=FAIL; fi
judge "振り分け $n 件の正答率 95% 以上（$correct/$n = $rate%）" PASS "$got"

if [ "$pass" -eq "$total" ] && [ "$total" -gt 0 ]; then echo "RESULT: PASS evals secretary ($pass/$total、振り分け $correct/$n)"; exit 0; fi
echo "RESULT: FAIL evals secretary ($pass/$total、振り分け $correct/$n)"; exit 1
