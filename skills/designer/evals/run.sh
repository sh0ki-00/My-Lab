#!/usr/bin/env bash
# skills/designer/evals/run.sh — designer の試験ケース。機械で判定できる分だけを回す。
#   1) 完成例（計画書、トークン、監修記録）が各検査を通る。雛形は穴埋めのままなので落ちる。
#   2) 負例の fixture が名指しで落ちる: ai-slop（sloppy 以上）、tokens-drift（#F4F1EA）、bad-plan（色・書体・シグネチャ・動き・既定との差、閾値 2.85）、bad-review（指摘・判定）。
#   3) 正例の fixture が通る: clean（帯 clean）、ai-slop-excused に --plan で理由を渡すと clean。
# 出力: ケースごとの行と、最後に RESULT: PASS|FAIL evals designer (<合格>/<全部>)。
set -u
HERE="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
SKILL="$(cd "$HERE/.." && pwd -P)"
S="$SKILL/scripts"
EX="$SKILL/examples"
FX="$HERE/fixtures"
pass=0; total=0
judge() {  # judge <名前> <期待> <実際>
  total=$((total + 1))
  if [ "$2" = "$3" ]; then pass=$((pass + 1)); printf 'PASS evals designer %s（期待 %s）\n' "$1" "$2"
  else printf 'FAIL evals designer %s（期待 %s、実際 %s）\n' "$1" "$2" "$3"; fi
}
verdict() {  # verdict <検査> <引数...> → PASS|FAIL
  if bash "$S/$1.sh" "${@:2}" >/dev/null 2>&1; then echo PASS; else echo FAIL; fi
}
has() {  # has <検査> <文言> <引数...> → PASS なら出力に文言がある
  if bash "$S/$1.sh" "${@:3}" 2>&1 | grep -q -- "$2"; then echo PASS; else echo FAIL; fi
}

# 1) 完成例と雛形
judge "examples/design-plan-order-list.md（計画書）" PASS "$(verdict design-plan-check "$EX/design-plan-order-list.md")"
judge "examples/design-plan-order-list.md（コントラスト）" PASS "$(verdict contrast-check "$EX/design-plan-order-list.md")"
judge "examples/tokens-order-list.css（忠実度）" PASS "$(verdict fidelity-check "$EX/design-plan-order-list.md" "$EX/tokens-order-list.css" "$FX/clean/orders.css")"
judge "examples/design-review-order-list.md（監修記録）" PASS "$(verdict review-check "$EX/design-review-order-list.md")"
judge "templates/design-plan.md（雛形は落ちる）" FAIL "$(verdict design-plan-check "$SKILL/templates/design-plan.md")"
judge "templates/design-review.md（雛形は落ちる）" FAIL "$(verdict review-check "$SKILL/templates/design-review.md")"

# 2) 負例
judge "fixtures/ai-slop が sloppy 以上" PASS "$(has ai-look-check 'sloppy\|terminal' "$FX/ai-slop")"
judge "fixtures/tokens-drift.css が #F4F1EA で落ちる" PASS "$(has fidelity-check '#F4F1EA' "$EX/design-plan-order-list.md" "$FX/tokens-drift.css")"
for rule in 色 書体 シグネチャ 動き 既定との差; do
  judge "fixtures/bad-plan.md が「${rule}」で落ちる" PASS "$(has design-plan-check "\\[$rule\\]" "$FX/bad-plan.md")"
done
judge "fixtures/bad-plan.md が 2.85 対 1 で落ちる" PASS "$(has contrast-check '2.85' "$FX/bad-plan.md")"
for rule in 指摘 判定; do
  judge "fixtures/bad-review.md が「${rule}」で落ちる" PASS "$(has review-check "\\[$rule\\]" "$FX/bad-review.md")"
done

# 3) 正例
judge "fixtures/clean が clean" PASS "$(has ai-look-check '帯 clean' "$FX/clean")"
judge "fixtures/ai-slop-excused が --plan で clean" PASS "$(has ai-look-check '帯 clean' "$FX/ai-slop-excused" --plan "$FX/plan-with-reasons.md")"

if [ "$pass" -eq "$total" ] && [ "$total" -gt 0 ]; then echo "RESULT: PASS evals designer ($pass/$total)"; exit 0; fi
echo "RESULT: FAIL evals designer ($pass/$total)"; exit 1
