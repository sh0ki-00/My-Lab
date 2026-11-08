#!/usr/bin/env bash
# skills/sre/evals/run.sh — sre の試験ケース（cases.md の 5 件）。機械で判定できる分だけを回す。
#   1) 完成例と雛形: 定義書の完成例は slo-doc-check と burn-rate を通り、雛形は落ちる。
#   2) 負例 fixtures/bad-slo.md が、承認者・測り点・エラーバジェットの扱い・Runbook と、食い違いで名指しで落ちる。
#   3) 原典との照合: workbook-reference.tsv の 8 行と計算が一致し、値を 1 つ変えた写しは落ちる。
#   4) 当番役の訓練: 完成例の Runbook 4 本の原因と、表の外と別の起動の 1 件ずつが、写しの障害を Runbook のコードだけで直す。
#   5) 確かめの道具: 出題役の命令で別の置き場の鍵を読む確かめは落ち、道具で立て直さない直す節は別の起動で落ちる。
# 出力: ケースごとの行と、最後に RESULT: PASS|FAIL evals sre (<合格>/<全部>)。
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:${PATH:-}"
HERE="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
SKILL="$(cd "$HERE/.." && pwd -P)"
S="$SKILL/scripts"
EX="$SKILL/examples"
FX="$HERE/fixtures"
pass=0; total=0
judge() {  # judge <名前> <期待> <実際>
  total=$((total + 1))
  if [ "$2" = "$3" ]; then pass=$((pass + 1)); printf 'PASS evals sre %s（期待 %s）\n' "$1" "$2"
  else printf 'FAIL evals sre %s（期待 %s、実際 %s）\n' "$1" "$2" "$3"; fi
}
verdict() {  # verdict <検査> <引数...> → PASS|FAIL
  if bash "$S/$1.sh" "${@:2}" >/dev/null 2>&1; then echo PASS; else echo FAIL; fi
}
has() {  # has <検査> <文言> <引数...> → 出力に文言があれば PASS
  if bash "$S/$1.sh" "${@:3}" 2>&1 | grep -q -- "$2"; then echo PASS; else echo FAIL; fi
}

# 1) 完成例と雛形
judge "examples/slo-order-list.md（slo-doc-check）" PASS "$(verdict slo-doc-check "$EX/slo-order-list.md")"
judge "examples/slo-order-list.md（burn-rate）" PASS "$(verdict burn-rate "$EX/slo-order-list.md")"
judge "templates/slo.md（雛形は落ちる）" FAIL "$(verdict slo-doc-check "$SKILL/templates/slo.md")"
judge "templates/slo.md が「穴埋め」で落ちる" PASS "$(has slo-doc-check '\[穴埋め\]' "$SKILL/templates/slo.md")"

# 2) 負例
for rule in 承認者 測り点 エラーバジェットの扱い Runbook; do
  judge "fixtures/bad-slo.md が「$rule」で落ちる" PASS "$(has slo-doc-check "\\[$rule\\]" "$FX/bad-slo.md")"
done
judge "fixtures/bad-slo.md が burn-rate の「食い違い」で落ちる" PASS "$(has burn-rate '\[食い違い\]' "$FX/bad-slo.md")"

# 3) 原典との照合
judge "workbook-reference.tsv と計算が一致する" PASS "$(verdict burn-rate --reference "$HERE/workbook-reference.tsv")"
tmp="$(mktemp -d)" || exit 1
trap 'rm -rf "$tmp"' EXIT
sed 's/^tier	99.9	30d	2%:1h	14.4	5m$/tier	99.9	30d	2%:1h	12	5m/' "$HERE/workbook-reference.tsv" > "$tmp/tampered.tsv"
judge "値を 1 つ変えた照合の表は「原典と不一致」で落ちる" PASS "$(has burn-rate '\[原典と不一致\]' --reference "$tmp/tampered.tsv")"

# 4) 当番役の訓練
out="$(bash "$S/runbook-drill.sh" "$EX"/runbooks/*.md 2>&1)"
printf '%s\n' "$out" | grep -E '^(MEASURE|FAIL)' | sed 's/^/  /'
if printf '%s\n' "$out" | grep -q '^RESULT: PASS runbook-drill (17 件'; then r=PASS; else r=FAIL; fi
judge "完成例の Runbook 4 本で 17 件の訓練（表の外の 4 件と別の起動の 4 件を含む）が全部直る" PASS "$r"

# 5) 確かめは Runbook の道具だけ（2026-11-08 の 2 回目の訓練の学び）
RB="$EX/runbooks/orders-list-availability-page.md"
# Runbook の中の文字そのものを写すので、$ は広げない。
# shellcheck disable=SC2016
VERIFY_LINE='bash "$SRE/sample-api.sh" probe --count 20 && bash "$SRE/sample-api.sh" status'
# shellcheck disable=SC2016
setter='curl -fsS -o /dev/null -H "Authorization: Bearer $(grep -m1 -o "[^ ]*$" "$RUN/drill-$PORT.out")" "http://127.0.0.1:$PORT/v1/orders"'
awk -v v="$VERIFY_LINE" -v s="$setter" '$0 == v {print s; next} {print}' "$RB" > "$tmp/rb-setter-verify.md"
judge "出題役の命令で別の置き場の鍵を読んで確かめる Runbook は「確かめの道具」で落ちる" PASS \
  "$(has runbook-drill '\[確かめの道具\]' "$tmp/rb-setter-verify.md")"
awk '/^### C4/ {c4 = 1} /^## / {c4 = 0} c4 && $0 == "bash \"$SRE/sample-api.sh\" start" {next} {print}' "$RB" > "$tmp/rb-no-restart.md"
judge "C4 の直す節が道具で立て直さない Runbook は、別の起動の 1 件で「復旧」に落ちる" PASS \
  "$(has runbook-drill '\[復旧\].*C4-別の起動' "$tmp/rb-no-restart.md" --only alt)"

if [ "$pass" -eq "$total" ] && [ "$total" -gt 0 ]; then echo "RESULT: PASS evals sre ($pass/$total)"; exit 0; fi
echo "RESULT: FAIL evals sre ($pass/$total)"; exit 1
