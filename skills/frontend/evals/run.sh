#!/usr/bin/env bash
# skills/frontend/evals/run.sh — frontend の試験ケース。機械で判定できる分だけを回す。
#   1) 完成例（実装計画、自己点検票。今の型の注文一覧と、没入の型の深海の探査日誌）が各検査を通る。雛形は穴埋めのままなので落ちる。
#   2) 負例の fixture が名指しで落ちる: bad-plan（構成・状態・データ取得・性能予算・テスト・横断事項・雛形の穴）、
#      bad-self-check（判定・結果・推測・ゲートの出力・節）、bad-app（生の色・生の px・生の書体、動き・縮小版、gate が FAIL）。
#   3) 正例の fixture と見本アプリが通る: good-app（token-lint、motion-lint、gate）、samples/app と samples/immersive（token-lint、motion-lint）。
#   4) 動きの検査の拡張: fixtures/motion/ の負例が名指しで落ちる。c-token・d1-jsx・h-autoplay・i-infinite・j-unrelated は
#      拡張の前に素通りした 5 例。js-animate・js-raf・js-canvas・skip・sound は JavaScript と音の負例。good-scene と scene は通る。
#      mute-token・skip-sw・html-reduced・video-muted・reset-cancel・const-duration は、関係の無い語（色のトークン、
#      skipWaiting()、別の規則の prefers-reduced-motion、muted 属性、別のファイルの cancel()）と定数の長さで通っていた 6 例。
#   5) 演出の計測の判定: fixtures/measure/ の記録の JSON（架空）を motion-measure --judge --allow-fictional で判定する。ブラウザは使わない。
#      good.json は 12 項目 PASS、bad.json は 12 項目が 1 つずつ落ち、no-scene.json は約束が無いので全部落ちる。
#      架空の記録は --allow-fictional を付けないと、12 項目が通っても FAIL になる。
#   6) --browser を付けたときだけ: fixtures/scene を画面なしのブラウザで実際に測り、12 項目 PASS を確かめる（2 条件 × 1 回、約 15 秒）。
# 使い方: run.sh [--browser]
# 出力: ケースごとの行と、最後に RESULT: PASS|FAIL evals frontend (<合格>/<全部>)。
set -u
BROWSER=0; [ "${1:-}" = "--browser" ] && BROWSER=1
HERE="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
SKILL="$(cd "$HERE/.." && pwd -P)"
ROOT="$(cd "$SKILL/../.." && pwd -P)"
S="$SKILL/scripts"
EX="$SKILL/examples"
FX="$HERE/fixtures"
pass=0; total=0
judge() {  # judge <名前> <期待> <実際>
  total=$((total + 1))
  if [ "$2" = "$3" ]; then pass=$((pass + 1)); printf 'PASS evals frontend %s（期待 %s）\n' "$1" "$2"
  else printf 'FAIL evals frontend %s（期待 %s、実際 %s）\n' "$1" "$2" "$3"; fi
}
verdict() {  # verdict <検査> <引数...> → PASS|FAIL
  if bash "$S/$1.sh" "${@:2}" >/dev/null 2>&1; then echo PASS; else echo FAIL; fi
}
has() {  # has <検査> <文言> <引数...> → PASS なら出力に文言がある
  if bash "$S/$1.sh" "${@:3}" 2>&1 | grep -q -- "$2"; then echo PASS; else echo FAIL; fi
}

# 1) 完成例と雛形
judge "examples/frontend-plan-order-list.md（実装計画）" PASS "$(verdict frontend-plan-check "$EX/frontend-plan-order-list.md")"
judge "examples/self-check-order-list.md（自己点検票）" PASS "$(verdict self-check "$EX/self-check-order-list.md")"
judge "examples/frontend-plan-dive-log.md（没入の型の実装計画）" PASS "$(verdict frontend-plan-check "$EX/frontend-plan-dive-log.md")"
judge "examples/self-check-dive-log.md（没入の型の自己点検票）" PASS "$(verdict self-check "$EX/self-check-dive-log.md")"
judge "templates/frontend-plan.md（雛形は落ちる）" FAIL "$(verdict frontend-plan-check "$SKILL/templates/frontend-plan.md")"
judge "templates/self-check.md（雛形は落ちる）" FAIL "$(verdict self-check "$SKILL/templates/self-check.md")"

# 2) 負例
for rule in 構成 状態 データ取得 性能予算 テスト 横断事項 雛形の穴; do
  judge "fixtures/bad-plan.md が「${rule}」で落ちる" PASS "$(has frontend-plan-check "\\[$rule\\]" "$FX/bad-plan.md")"
done
for rule in 判定 結果 推測 ゲートの出力 節; do
  judge "fixtures/bad-self-check.md が「${rule}」で落ちる" PASS "$(has self-check "\\[$rule\\]" "$FX/bad-self-check.md")"
done
for rule in 生の色 "生の px" 生の書体; do
  judge "fixtures/bad-app が「${rule}」で落ちる" PASS "$(has token-lint "\\[$rule\\]" "$FX/bad-app")"
done
for rule in 動き 縮小版; do
  judge "fixtures/bad-app が「${rule}」で落ちる" PASS "$(has motion-lint "\\[$rule\\]" "$FX/bad-app")"
done
judge "fixtures/bad-app で gate が FAIL" PASS "$(has frontend-gate '^RESULT: FAIL frontend-gate' "$FX/bad-app")"

# 3) 正例
judge "fixtures/good-app が token-lint を通る" PASS "$(verdict token-lint "$FX/good-app")"
judge "fixtures/good-app が motion-lint を通る" PASS "$(verdict motion-lint "$FX/good-app")"
judge "fixtures/good-app で gate が PASS" PASS "$(has frontend-gate '^RESULT: PASS frontend-gate' "$FX/good-app")"
judge "samples/app が token-lint を通る" PASS "$(verdict token-lint "$ROOT/samples/app")"
judge "samples/app が motion-lint を通る" PASS "$(verdict motion-lint "$ROOT/samples/app")"
judge "samples/immersive が token-lint を通る" PASS "$(verdict token-lint "$ROOT/samples/immersive")"
judge "samples/immersive が motion-lint を通る" PASS "$(verdict motion-lint "$ROOT/samples/immersive")"

# 4) 動きの検査の拡張（負例: <ディレクトリ>:<落ちる決まり>）
for c in c-token:縮小版 d1-jsx:縮小版 h-autoplay:自動再生 i-infinite:止める j-unrelated:縮小版 js-animate:縮小版 js-raf:縮小版 js-canvas:縮小版 skip:飛ばす sound:消音 \
         mute-token:消音 skip-sw:飛ばす html-reduced:縮小版 video-muted:消音 reset-cancel:止める const-duration:飛ばす; do
  name="${c%%:*}"; rule="${c#*:}"
  judge "fixtures/motion/${name} が「${rule}」で落ちる" PASS "$(has motion-lint "\\[${rule}\\]" "$FX/motion/$name")"
done
judge "fixtures/motion/c-token が、上書きの無いトークン --duration-2 を名指す" PASS "$(has motion-lint "トークン --duration-2 に縮小版の上書きが無い" "$FX/motion/c-token")"
judge "fixtures/motion/j-unrelated の動き 3 本が全部落ちる" PASS "$(if [ "$(bash "$S/motion-lint.sh" "$FX/motion/j-unrelated" 2>&1 | grep -c '\[縮小版\]')" -eq 3 ]; then echo PASS; else echo FAIL; fi)"
judge "fixtures/motion/good-scene が motion-lint を通る" PASS "$(verdict motion-lint "$FX/motion/good-scene")"
judge "fixtures/scene が motion-lint を通る" PASS "$(verdict motion-lint "$FX/scene")"
judge "fixtures/scene が token-lint を通る" PASS "$(verdict token-lint "$FX/scene")"

# 5) 演出の計測の判定（記録の JSON。ブラウザは使わない）。記録は架空なので、判定の試験だけ --allow-fictional で許す
judge "fixtures/measure/good.json の判定が PASS" PASS "$(has motion-measure '^RESULT: PASS motion-measure start-to-login (PASS 12、FAIL 0' --judge "$FX/measure/good.json" --allow-fictional)"
judge "fixtures/measure/good.json（架空）は --allow-fictional なしでは FAIL" FAIL "$(verdict motion-measure --judge "$FX/measure/good.json")"
for no in 1 2 3 4 5 6 7 8 9 10 11 12; do
  judge "fixtures/measure/bad.json で項目 ${no} が落ちる" PASS "$(has motion-measure "^RESULT: FAIL motion-measure ${no} " --judge "$FX/measure/bad.json" --allow-fictional)"
done
judge "fixtures/measure/bad.json の全体が FAIL" FAIL "$(verdict motion-measure --judge "$FX/measure/bad.json" --allow-fictional)"
judge "fixtures/measure/no-scene.json が約束の欠けで落ちる" PASS "$(has motion-measure '^RESULT: FAIL motion-measure 1 .*window.__scene が無い' --judge "$FX/measure/no-scene.json" --allow-fictional)"

# 6) 実ブラウザの計測（--browser のときだけ）。時刻の項目は、同じ機械でほかの重い処理が走ると揺れる。
#    落ちたら理由の FAIL の行を出し、記録を残す。通ったら記録の一時の置き場を消す
if [ "$BROWSER" -eq 1 ]; then
  tmpd="$(mktemp -d)"
  out="$(bash "$S/motion-measure.sh" --dir "$FX/scene" --scene start-to-login --runs 1 --record "$tmpd/scene.json" 2>&1)"
  if printf '%s\n' "$out" | grep -q '^RESULT: PASS motion-measure start-to-login (PASS 12、FAIL 0'; then got=PASS; rm -rf "$tmpd"; else got=FAIL; fi
  judge "fixtures/scene を画面なしのブラウザで測って 12 項目 PASS" PASS "$got"
  if [ "$got" = FAIL ]; then printf '%s\n' "$out" | grep -E '^FAIL' | head -8; echo "記録: $tmpd/scene.json"; fi
fi

if [ "$pass" -eq "$total" ] && [ "$total" -gt 0 ]; then echo "RESULT: PASS evals frontend ($pass/$total)"; exit 0; fi
echo "RESULT: FAIL evals frontend ($pass/$total)"; exit 1
