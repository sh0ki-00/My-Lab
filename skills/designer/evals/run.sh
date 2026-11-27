#!/usr/bin/env bash
# skills/designer/evals/run.sh — designer の試験ケース。機械で判定できる分だけを回す。
#   1) 完成例（計画書、トークン、監修記録）が各検査を通る。雛形は穴埋めのままなので落ちる。
#   2) 負例の fixture が名指しで落ちる: ai-slop（sloppy 以上）、tokens-drift（#F4F1EA）、bad-plan（色・書体・シグネチャ・動き・既定との差、閾値 2.85）、bad-review（指摘・判定）。
#   3) 正例の fixture が通る: clean（帯 clean）、ai-slop-excused に --plan で理由を渡すと clean。
#   4) 画面の型: 没入の型の完成例（計画書と演出計画書）と tokens-dive-log.css が通り、演出計画書の雛形が落ちる。
#      just-slide（ただのスライド）が 5 つの条件と点滅・5 秒・音で落ち、current-type-600ms（今の型で 600ms）が動きの 1 行だけで落ちる。
#      没入の型のトークンを今の型の計画書に当てると、300ms の線で落ちる。ai-slop-immersive が没入の既定の 3 項目で落ちる。
#   5) 査読で通っていた書き方: 完成例を 1 か所だけ変えた写し（一時の置き場）が落ちる。守りの「なし」と打ち消し、点滅の回数、
#      同じ動きをずらしただけの計画、秒で書いた長さ、名前の違う時間のトークン、フレームの所見の無い監修記録、
#      既存に合わせる型の --existing の欠け。没入の型の監修記録の完成例は通る。
#   6) 既存に合わせる型: samples/app を題材にした完成例（design-plan-pane-memo.md）が計画書・コントラスト・--existing つきの
#      忠実度を通り、既存に無い色と、棚卸しの表の欠けで落ちる。監修記録は、高の指摘があるのに受け入れにすると落ちる。
#   7) フィボナッチの数列: 数列で組んだ完成例（起動からメニュー）と雛形のトークンが通り、4px・120ms・44px を足すと落ちる。
#      数列の前の版の完成例は数列で見ず、置き場の外に写すと落ちる。ai-slop-motion が同じ動きと透明度だけのホバーで落ちる。
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

# 4) 画面の型と没入の型
judge "examples/design-plan-dive-log.md（没入の型の計画書）" PASS "$(verdict design-plan-check "$EX/design-plan-dive-log.md")"
judge "examples/design-plan-dive-log.md（コントラスト）" PASS "$(verdict contrast-check "$EX/design-plan-dive-log.md")"
judge "examples/motion-plan-dive-log.md（演出計画書）" PASS "$(verdict motion-plan-check "$EX/motion-plan-dive-log.md")"
judge "fixtures/tokens-dive-log.css（没入の型の忠実度）" PASS "$(verdict fidelity-check "$EX/design-plan-dive-log.md" "$FX/tokens-dive-log.css" --motion "$EX/motion-plan-dive-log.md")"
judge "templates/motion-plan.md（雛形は落ちる）" FAIL "$(verdict motion-plan-check "$SKILL/templates/motion-plan.md")"
for rule in '段が 3 つ' 'レイヤーが 3 つ以上' '共有要素が 1 つ' '動きが重なる' '守りが 5 行' '点滅' '5 秒を超える動き' '音'; do
  judge "fixtures/just-slide.md が「${rule}」で落ちる" PASS "$(has motion-plan-check "\\[$rule\\]" "$FX/just-slide.md")"
done
judge "fixtures/current-type-600ms.md が 300ms の線で落ちる" PASS "$(has design-plan-check '600ms は 300ms 超' "$FX/current-type-600ms.md")"
judge "fixtures/current-type-600ms.md の FAIL は動きの 1 行だけ" PASS "$(has design-plan-check 'FAIL 1、' "$FX/current-type-600ms.md")"
judge "没入の型のトークンは、今の型の計画書では 300ms の線で落ちる" PASS "$(has fidelity-check '1,400ms は 300ms 超' "$EX/design-plan-order-list.md" "$FX/tokens-dive-log.css")"
for item in 'ネオンの光' '粒子' '一律の浮き上がり'; do
  judge "fixtures/ai-slop-immersive が「${item}」で落ちる" PASS "$(has ai-look-check "\\[$item\\]" "$FX/ai-slop-immersive")"
done

# 5) 査読で通っていた書き方（完成例を 1 か所だけ変えた写し）
tmpd="$(mktemp -d)" || exit 1
trap 'rm -rf "$tmpd"' EXIT
variant() {  # variant <元> <写し> <正規表現> <置き換え> → 行ごとの正規表現で 1 か所だけ置き換える。当たらなければ失敗
  python3 -I -c 'import re, sys
s = open(sys.argv[1], encoding="utf-8").read()
t, n = re.subn(sys.argv[3], sys.argv[4], s, count=1, flags=re.M)
open(sys.argv[2], "w", encoding="utf-8").write(t)
sys.exit(0 if n == 1 else 1)' "$@"
}
case_has() {  # case_has <名前> <検査> <文言> <元> <正規表現> <置き換え> [<検査の後ろの引数...>]
  local name="$1" check="$2" want="$3" src="$4" rx="$5" to="$6"; shift 6
  if variant "$src" "$tmpd/case.md" "$rx" "$to"; then judge "$name" PASS "$(has "$check" "$want" "$tmpd/case.md" "$@")"
  else judge "${name}（写しを作れない）" PASS FAIL; fi
}
judge "examples/design-review-dive-log.md（没入の型の監修記録）" PASS "$(verdict review-check "$EX/design-review-dive-log.md")"
case_has "守りの「動きを減らす設定」が「なし」だけだと落ちる" motion-plan-check '「動きを減らす設定」: 「なし」だけ' "$EX/motion-plan-dive-log.md" '^(\| 動きを減らす設定 \| ).*\|$' '\1なし |'
case_has "守りの「終わりのフォーカス」が「なし」だけだと落ちる" motion-plan-check '「終わりのフォーカス」: 「なし」だけ' "$EX/motion-plan-dive-log.md" '^(\| 終わりのフォーカス \| ).*\|$' '\1なし |'
case_has "止める操作を置かないと書くと落ちる" motion-plan-check '\[5 秒を超える動き\]' "$EX/motion-plan-dive-log.md" '^(\| 5 秒を超える動き \| ).*\|$' '\1止める操作は置かない |'
case_has "消音の操作を置かないと書くと落ちる" motion-plan-check '\[音\]' "$EX/motion-plan-dive-log.md" '^(\| 音 \| ).*\|$' '\1消音の操作は置かない |'
case_has "点滅は書いた回数の最大で判定する" motion-plan-check '切り替わりが 6 回' "$EX/motion-plan-dive-log.md" '^(\| 点滅 \| ).*\|$' '\g<1>0 回と書いたが、題字は白と黒を毎秒 6 回切り替える |'
case_has "同じ動きをずらしただけの計画が落ちる" motion-plan-check '\[レイヤーが 3 つ以上\]' "$EX/motion-plan-dive-log.md" '^(\| 時刻 \| 段 \|.*\n\|---.*\n)(?:\|.*\n)+' '\1| 0ms | 入り | 灯・水・題字 | 右から 24px 滑る | 120ms、標準 | 動いた |\n| 50ms | 見せ場 | 灯・水・題字 | 右から 24px 滑る | 120ms、標準 | 動いた |\n| 100ms | 収まり | 灯・水・題字 | 右から 24px 滑る | 120ms、標準 | 動いた |\n'
case_has "見せ場を秒で書いても枠で落ちる" design-plan-check '見せ場は 1,400ms まで' "$EX/design-plan-dive-log.md" '^(\| 見せ場 \|.*?)初回 1,400ms' '\g<1>初回 4 秒'
case_has "環境を止められないと書くと落ちる" design-plan-check '環境の動きに止める手段が無い' "$EX/design-plan-dive-log.md" '^(\| 環境 \|.*\| )隅の「動きを止める」で止める \|$' '\1止められない |'
case_has "没入の型の監修記録でフレームの所見の節が無いと落ちる" review-check '\[フレームの所見\]' "$EX/design-review-dive-log.md" '(?s)^## フレームの所見.*?(?=^## 指摘)' ''
case_has "没入の型の監修記録でフレームの一覧の行が無いと落ちる" review-check '\[フレームの一覧\]' "$EX/design-review-dive-log.md" '^\| フレームの一覧 \|.*\n' ''
case_has "既存に合わせる型の計画書は足す値の表が要る" design-plan-check '\[足す値\]' "$EX/design-plan-dive-log.md" '^(\| 画面の型 \| )没入の型' '\1既存に合わせる型'
variant "$EX/tokens-order-list.css" "$tmpd/tokens.css" '^(\s*--duration-3: 180ms;)' '\1\n  --motion-sheet: 900ms;\n  --dive-water: 1400ms;' && \
  judge "名前の違う長い時間のトークンが今の型の計画書で落ちる" PASS "$(has fidelity-check '--motion-sheet: 900ms は 300ms 超' "$EX/design-plan-order-list.md" "$tmpd/tokens.css")"

# 6) 既存に合わせる型（samples/app を題材にした完成例）と、監修記録の判定の決まり
ROOT="$(cd "$SKILL/../.." && pwd -P)"
EXM="$EX/design-plan-pane-memo.md"
judge "examples/design-plan-pane-memo.md（既存に合わせる型の計画書）" PASS "$(verdict design-plan-check "$EXM")"
judge "examples/design-plan-pane-memo.md（コントラスト）" PASS "$(verdict contrast-check "$EXM")"
judge "samples/app（既存に合わせる型の忠実度。--existing つき）" PASS "$(verdict fidelity-check "$EXM" "$ROOT/samples/app/tokens.css" "$ROOT/samples/app/app.css" --existing "$ROOT/samples/app")"
judge "既存に合わせる型の忠実度は --existing が無いと落ちる" PASS "$(has fidelity-check '\[既存の値\]' "$EXM" "$ROOT/samples/app/tokens.css")"
case_has "既存に無い色を計画書に書くと落ちる" design-plan-check '色 #2F5C9F（藍）は既存の UI に無い' "$EXM" '^(\| 藍 \| )#2F5C9E' '\1#2F5C9F'
case_has "既存に合わせる型で棚卸しの表が無いと落ちる" design-plan-check '棚卸しの表' "$EXM" '^\| 種類 \| 値 \| 出現数 \| 最初の場所 \|\n(?:\|.*\n)+' ''
case_has "監修記録で高の指摘があるのに条件つき受け入れだと落ちる" review-check '高が 1 つ以上なら差し戻し' "$EX/design-review-order-list.md" '^判定は差し戻しです。' '判定は条件つき受け入れです。確認は監修者が行います。'

# 7) フィボナッチの数列（依頼者の決め、2026-11-27）と、AI らしい動きの 2 項目
judge "examples/tokens-title-menu.css（数列）" PASS "$(verdict fib-check "$EX/tokens-title-menu.css")"
judge "templates/tokens.css（数列）" PASS "$(verdict fib-check "$SKILL/templates/tokens.css")"
judge "examples/motion-plan-title-menu.md（数列で組んだ演出計画書）" PASS "$(verdict motion-plan-check "$EX/motion-plan-title-menu.md")"
judge "数列の前の版の完成例は数列で見ない" PASS "$(has fib-check '数列の前の版' "$EX/tokens-order-list.css")"
for bad in '--bad-space: 4px;' '--bad-duration: 120ms;' '--bad-target: 44px;'; do
  { cat "$EX/tokens-title-menu.css"; printf '\n:root { %s }\n' "$bad"; } > "$tmpd/fib.css"
  judge "数列の外の値（${bad}）が落ちる" PASS "$(has fib-check '\[数列\]' "$tmpd/fib.css")"
done
cp "$EX/design-plan-dive-log.md" "$tmpd/design-plan-dive-log.md"
judge "置き場の外に写した数列の前の版の計画書は、数列で落ちる" PASS "$(has design-plan-check '\[数列\]' "$tmpd/design-plan-dive-log.md")"
case_has "演出計画書の拍の長さが数列の外だと落ちる" motion-plan-check '\[数列\]' "$EX/motion-plan-title-menu.md" '^(\| 377ms \|.*?)233ms' '\g<1>240ms'
judge "既存に合わせる型は、既存の値を数列で見ない" PASS "$(verdict fib-check "$tmpd/fib.css" --plan "$EX/design-plan-pane-memo.md")"
judge "fixtures/ai-slop-motion が同じ動きで落ちる" PASS "$(has ai-look-check '\[同じ動き\]' "$FX/ai-slop-motion")"
judge "fixtures/ai-slop-motion が透明度だけのホバーで落ちる" PASS "$(has ai-look-check '\[透明度だけのホバー\]' "$FX/ai-slop-motion")"

if [ "$pass" -eq "$total" ] && [ "$total" -gt 0 ]; then echo "RESULT: PASS evals designer ($pass/$total)"; exit 0; fi
echo "RESULT: FAIL evals designer ($pass/$total)"; exit 1
