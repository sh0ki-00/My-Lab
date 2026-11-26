#!/usr/bin/env bash
# skills/security/evals/run.sh — security の試験ケース（cases.md の 9 件）。機械で判定できる分だけを回す。
#   1) 完成例と雛形: 完成例は 4 つの検査を通り、雛形は穴埋めのままなので落ちる。
#   2) RoE の負例 fixtures/bad-roe.md が、7 つの決まりで名指しで落ちる。
#   3) 報告の負例 fixtures/bad-report.md が、7 つの決まりで名指しで落ちる。
#   4) 点数の負例 fixtures/wrong-score-report.md が食い違いで落ち、完成例の 3 つの文字列は計算と同じ。
#   5) 検知の行列の負例 fixtures/bad-matrix.md が、4 つの決まりで落ちる。
#   6) 報告が指す見本の試験 3 本が通る（網を使わない）。
#   7) 写しの負例 fixtures/bad-copy-report.md が、--roe で RoE の範囲と突き合わせて 4 つの決まりで落ち、--roe なしでは通る。
#   8) RoE の負例 fixtures/bad-cloud-roe.md が、所有の確認と署名がそろっていても、手元の外の宛先だけで落ちる。
#   11) 誤検知の確かめの負例 fixtures/bad-fp-report.md が、再現 1 回・空の升・誤検知の発見・表に無い発見の 4 つで落ちる。
# 出力: ケースごとの行と、最後に RESULT: PASS|FAIL evals security (<合格>/<全部>)。
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
HERE="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
SKILL="$(cd "$HERE/.." && pwd -P)"
ROOT="$(cd "$SKILL/../.." && pwd -P)"
S="$SKILL/scripts"
EX="$SKILL/examples"
TP="$SKILL/templates"
FX="$HERE/fixtures"
pass=0; total=0
judge() {  # judge <名前> <期待> <実際>
  total=$((total + 1))
  if [ "$2" = "$3" ]; then pass=$((pass + 1)); printf 'PASS evals security %s（期待 %s）\n' "$1" "$2"
  else printf 'FAIL evals security %s（期待 %s、実際 %s）\n' "$1" "$2" "$3"; fi
}
verdict() {  # verdict <検査> <引数...> → PASS|FAIL
  if bash "$S/$1.sh" "${@:2}" >/dev/null 2>&1; then echo PASS; else echo FAIL; fi
}
has() {  # has <検査> <文言> <引数...> → PASS なら出力に文言がある
  if bash "$S/$1.sh" "${@:3}" 2>&1 | grep -q -- "$2"; then echo PASS; else echo FAIL; fi
}

# 1) 完成例と雛形
judge "examples/roe-order-list.md（RoE）" PASS "$(verdict roe-check "$EX/roe-order-list.md")"
judge "examples/pentest-report-order-list.md（報告の 5 点）" PASS "$(verdict report-check "$EX/pentest-report-order-list.md")"
judge "examples/pentest-report-order-list.md（RoE の宛先と写し）" PASS "$(cd "$ROOT" && verdict report-check --roe "$EX/roe-order-list.md" "$EX/pentest-report-order-list.md")"
judge "examples/pentest-report-order-list.md（点数と重さ）" PASS "$(verdict cvss4 --report "$EX/pentest-report-order-list.md")"
judge "examples/detection-matrix-order-list.md（検知の行列）" PASS "$(verdict report-check --matrix "$EX/detection-matrix-order-list.md")"
judge "templates/roe.md（雛形は落ちる）" FAIL "$(verdict roe-check "$TP/roe.md")"
judge "templates/pentest-report.md（雛形は落ちる）" FAIL "$(verdict report-check "$TP/pentest-report.md")"
judge "templates/detection-matrix.md（雛形は落ちる）" FAIL "$(verdict report-check --matrix "$TP/detection-matrix.md")"

# 2) RoE の負例
for rule in 所有の確認 範囲外の宛先 許可 連絡先 期間 止める条件 やらないこと; do
  judge "fixtures/bad-roe.md が「${rule}」で落ちる" PASS "$(has roe-check "\\[$rule\\]" "$FX/bad-roe.md")"
done

# 3) 報告の負例
for rule in 何ができてしまうか 直し方 再検証 重さと採点の根拠 採点の根拠 範囲外の宛先 攻撃コード; do
  judge "fixtures/bad-report.md が「${rule}」で落ちる" PASS "$(has report-check "\\[$rule\\]" "$FX/bad-report.md")"
done

# 4) 点数の食い違い
judge "fixtures/wrong-score-report.md が「点数の食い違い」で落ちる" PASS "$(has cvss4 '\[点数の食い違い\]' --report "$FX/wrong-score-report.md")"
judge "fixtures/wrong-score-report.md が「重さの食い違い」で落ちる" PASS "$(has cvss4 '\[重さの食い違い\]' --report "$FX/wrong-score-report.md")"
judge "F-1 の文字列は 9.3 Critical" PASS "$(has cvss4 '^9.3 Critical ' 'CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:H/VA:N/SC:N/SI:N/SA:N')"
judge "F-2 の文字列は 7.1 High" PASS "$(has cvss4 '^7.1 High ' 'CVSS:4.0/AV:N/AC:L/AT:N/PR:L/UI:N/VC:H/VI:N/VA:N/SC:N/SI:N/SA:N')"
judge "F-3 の文字列は 5.3 Medium" PASS "$(has cvss4 '^5.3 Medium ' 'CVSS:4.0/AV:N/AC:L/AT:N/PR:L/UI:N/VC:N/VI:L/VA:N/SC:N/SI:N/SA:N')"

# 5) 検知の行列の負例
for rule in 行列 通知 検知 検証; do
  judge "fixtures/bad-matrix.md が「${rule}」で落ちる" PASS "$(has report-check "\\[$rule\\]" --matrix "$FX/bad-matrix.md")"
done

# 6) 報告が指す見本の試験
for t in test_tokens_cannot_be_made_from_user_ids test_detail_and_other_shop_is_404 test_auth_and_roles; do
  if python3 -I "$ROOT/samples/api/test_orders_api.py" "OrdersApiTest.$t" >/dev/null 2>&1; then r=PASS; else r=FAIL; fi
  judge "見本の試験 $t" PASS "$r"
done

# 7) 再検証の宛先と試験の置き場を、RoE の範囲の写しと突き合わせる
judge "fixtures/bad-copy-report.md は --roe なしでは通る（突き合わせが要る理由）" PASS "$(cd "$ROOT" && verdict report-check "$FX/bad-copy-report.md")"
copy_rules=("RoE の範囲外" 再検証の写し 試験の置き場 立てる写し)
for rule in "${copy_rules[@]}"; do
  judge "fixtures/bad-copy-report.md が --roe で「${rule}」で落ちる" PASS "$(cd "$ROOT" && has report-check "\\[$rule\\]" --roe "$FX/bad-copy-roe.md" "$FX/bad-copy-report.md")"
done

# 8) 宛先は手元（127.0.0.1・localhost・::1）だけ。クラウドの環境は、検証環境でも所有の確認があっても範囲に書けない
judge "fixtures/bad-cloud-roe.md は roe-check を通らない" FAIL "$(verdict roe-check "$FX/bad-cloud-roe.md")"
cloud_out="$(bash "$S/roe-check.sh" "$FX/bad-cloud-roe.md" 2>&1)"
if printf '%s\n' "$cloud_out" | grep -q '\[範囲外の宛先\]' \
   && ! printf '%s\n' "$cloud_out" | grep -qE '\[(所有の確認|許可|連絡先|期間|止める条件|やらないこと|範囲)\]'; then r=PASS; else r=FAIL; fi
judge "fixtures/bad-cloud-roe.md は所有の確認と署名があっても「範囲外の宛先」だけで落ちる" PASS "$r"

# 9) 攻撃の道具の自己試験（9 つの線・台帳の形）
judge "attack-run の 9 つの線の自己試験" PASS "$(verdict attack-run --selftest)"
judge "attack-check の台帳の自己試験" PASS "$(verdict attack-check --selftest)"

# 10) 検知力の試験（脆弱性を仕込んだサンプル。サーバーを立てる）。S-3・S-4・S-6
if python3 "$HERE/vulnerable-app/detect-test.py" >/dev/null 2>&1; then r=PASS; else r=FAIL; fi
judge "検知力: 穴 12 件を見つけ、ふさいだ版で 0 件、届いた本数が一致" PASS "$r"

# 11) 誤検知の確かめ（references/five-points-and-retest.md の「誤検知を確かめる」）
fp_out="$(bash "$S/report-check.sh" "$FX/bad-fp-report.md" 2>&1)"
for msg in "F-1 の再現が 2 回に満たない" "C-1 の 守りの層 が空" "F-1 を誤検知と判定したのに、発見に書いている" "F-2 に、誤検知の確かめで「本物」と判定した行が無い"; do
  if printf '%s\n' "$fp_out" | grep -q -- "\[誤検知の確かめ\] ${msg}"; then r=PASS; else r=FAIL; fi
  judge "fixtures/bad-fp-report.md が「誤検知の確かめ」で落ちる（${msg}）" PASS "$r"
done
judge "fixtures/bad-report.md は誤検知の確かめの節が無いことでも落ちる" PASS "$(has report-check '\[誤検知の確かめ\]' "$FX/bad-report.md")"

if [ "$pass" -eq "$total" ] && [ "$total" -gt 0 ]; then echo "RESULT: PASS evals security ($pass/$total)"; exit 0; fi
echo "RESULT: FAIL evals security ($pass/$total)"; exit 1
