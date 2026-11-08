#!/usr/bin/env bash
# skills/backend/evals/run.sh — backend の試験ケース（cases.md の 5 件）。機械で判定できる分だけを回す。
#   1) 完成例と雛形: 計画の完成例は通り、雛形は穴埋めのままなので落ちる。契約の完成例と雛形は 1 版の決まりを通る。
#   2) 計画の負例 fixtures/bad-plan.md が、12 の決まりで名指しで落ちる。
#   3) 契約の負例: fixtures/bad-contract.json が 4 つの決まりで、壊した 2 版目が 6 種類の壊す変更で落ちる。同じ版どうしは通る。
#   4) 問い合わせの数と p99: 見本の API は完成例の予算で通り、わざと N+1 にした写しは [N+1] で落ちる。
#   5) 見本の API の試験（契約の形、認可、冪等、エラー、ログ）が通る。
# 出力: ケースごとの行と、最後に RESULT: PASS|FAIL evals backend (<合格>/<全部>)。
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
HERE="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
SKILL="$(cd "$HERE/.." && pwd -P)"
ROOT="$(cd "$SKILL/../.." && pwd -P)"
S="$SKILL/scripts"
EX="$SKILL/examples"
FX="$HERE/fixtures"
pass=0; total=0
judge() {  # judge <名前> <期待> <実際>
  total=$((total + 1))
  if [ "$2" = "$3" ]; then pass=$((pass + 1)); printf 'PASS evals backend %s（期待 %s）\n' "$1" "$2"
  else printf 'FAIL evals backend %s（期待 %s、実際 %s）\n' "$1" "$2" "$3"; fi
}
verdict() {  # verdict <検査> <引数...> → PASS|FAIL
  if bash "$S/$1.sh" "${@:2}" >/dev/null 2>&1; then echo PASS; else echo FAIL; fi
}
has() {  # has <検査> <文言> <引数...> → PASS なら出力に文言がある
  if bash "$S/$1.sh" "${@:3}" 2>&1 | grep -q -- "$2"; then echo PASS; else echo FAIL; fi
}

# 1) 完成例と雛形
judge "examples/backend-plan-order-list.md（計画）" PASS "$(verdict backend-plan-check "$EX/backend-plan-order-list.md")"
judge "templates/backend-plan.md（雛形は落ちる）" FAIL "$(verdict backend-plan-check "$SKILL/templates/backend-plan.md")"
judge "examples/openapi-order-list.json（契約の 1 版）" PASS "$(verdict contract-check "$EX/openapi-order-list.json")"
judge "templates/openapi-contract.json（契約の雛形）" PASS "$(verdict contract-check "$SKILL/templates/openapi-contract.json")"

# 2) 計画の負例
for rule in 契約 認可 冪等 エラー 移行 問い合わせ 性能予算 観測 流出経路 テスト 段階 必須の節; do
  judge "fixtures/bad-plan.md が「$rule」で落ちる" PASS "$(has backend-plan-check "\\[$rule\\]" "$FX/bad-plan.md")"
done

# 3) 契約の負例と 2 版の比較
for rule in "エラーの 4 点" 冪等キー 認可 起点の送り; do
  judge "fixtures/bad-contract.json が「$rule」で落ちる" PASS "$(has contract-check "\\[$rule\\]" "$FX/bad-contract.json")"
done
for rule in 操作の削除 応答の欄の削除 必須の入力の追加 型の変更 列挙値の削除 状態番号の削除; do
  judge "壊した 2 版目が「$rule」で落ちる" PASS "$(has contract-check "\\[$rule\\]" "$EX/openapi-order-list.json" "$EX/openapi-order-list-v2-breaking.json")"
done
judge "同じ版どうしの比較は通る" PASS "$(verdict contract-check "$EX/openapi-order-list.json" "$EX/openapi-order-list.json")"

# 4) 問い合わせの数と p99
judge "samples/api が完成例の予算で通る（24 件と 400 件）" PASS "$(verdict query-count-check --plan "$EX/backend-plan-order-list.md" --requests 100)"
judge "わざと N+1 にした写しが [N+1] で落ちる" PASS "$(has query-count-check '\[N+1\]' --app "$FX/n1_orders_api.py" --budget-ms 300 --requests 20)"

# 5) 見本の API の試験
if python3 -I "$ROOT/samples/api/test_orders_api.py" >/dev/null 2>&1; then r=PASS; else r=FAIL; fi
judge "samples/api/test_orders_api.py（契約・認可・冪等・エラー・ログ）" PASS "$r"

if [ "$pass" -eq "$total" ] && [ "$total" -gt 0 ]; then echo "RESULT: PASS evals backend ($pass/$total)"; exit 0; fi
echo "RESULT: FAIL evals backend ($pass/$total)"; exit 1
