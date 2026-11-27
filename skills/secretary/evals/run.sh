#!/usr/bin/env bash
# skills/secretary/evals/run.sh — secretary の試験ケース。機械で判定できる分だけを回す。
#   1) 完成例 4 点が各検査を通り、承認伺いが gate-check を通る。雛形 4 点は穴埋めのままなので落ちる。
#   2) cases/<名前>.md と cases/<名前>.expect（「<検査名> PASS|FAIL」）を対にし、判定が期待と合うか。
#   3) 振り分け: routing-cases.tsv の全件を route で判定し、正答率が 95% 以上（56 件なら 54 件以上）。期待の「当たり無し」は、route が当たり無しと返すこと。
#   4) 言い直し: restatement-run.sh（restatements/ の出力 20 件の機械の検査と、判定 3 体の票の多数決で一致 18 件以上）。
#   5) 返答の文: answers/ の見本 20 組を answer-check に通す。before は 20 件とも FAIL か WARN、after は 20 件とも FAIL 0・WARN 0（C-08）。
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

# 4) 言い直し（仕様書 R-20261113-01 の C-01・C-02）
if bash "$HERE/restatement-run.sh" >/dev/null 2>&1; then got=PASS; else got=FAIL; fi
judge "restatements（言い直し 20 件の形と、判定 3 体の一致 18 件以上）" PASS "$got"

# 5) 返答の文（仕様書 R-20261113-01 の C-08）
nb=0; hit=0; na=0; clean=0
for f in "$HERE"/answers/before/*.txt; do
  [ -f "$f" ] || continue
  nb=$((nb + 1))
  out="$(bash "$S/answer-check.sh" "$f" 2>&1)"
  if printf '%s\n' "$out" | grep -qE '^(FAIL|WARN) '; then hit=$((hit + 1)); else printf 'FAIL evals secretary answers/before/%s が FAIL も WARN も出ない\n' "$(basename "$f")"; fi
done
for f in "$HERE"/answers/after/*.txt; do
  [ -f "$f" ] || continue
  na=$((na + 1))
  out="$(bash "$S/answer-check.sh" "$f" 2>&1)"
  if printf '%s\n' "$out" | grep -qE '^(FAIL|WARN) '; then printf '%s\n' "$out" | grep -E '^(FAIL|WARN) ' | sed 's/^/  /'; else clean=$((clean + 1)); fi
done
if [ "$nb" -eq 20 ] && [ "$hit" -eq "$nb" ]; then got=FAIL_OR_WARN; else got="$hit/$nb"; fi
judge "answers/before（直す前の見本 20 件が FAIL か WARN）" FAIL_OR_WARN "$got"
if [ "$na" -eq 20 ] && [ "$clean" -eq "$na" ]; then got=PASS; else got="$clean/$na"; fi
judge "answers/after（直した後の見本 20 件が FAIL 0・WARN 0）" PASS "$got"

if [ "$pass" -eq "$total" ] && [ "$total" -gt 0 ]; then echo "RESULT: PASS evals secretary ($pass/${total}、振り分け $correct/$n)"; exit 0; fi
echo "RESULT: FAIL evals secretary ($pass/${total}、振り分け $correct/$n)"; exit 1
