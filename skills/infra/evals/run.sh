#!/usr/bin/env bash
# skills/infra/evals/run.sh — infra の試験ケース（cases.md）。機械で判定できる分だけを回す。
#   1) 設計書: 完成例が arch-check を通り、雛形と負例が名指しで落ちる。
#   2) 構成コード: 良い例と見本（samples/infra）が iac-scan を通り、悪い例と見本を壊した写しが規則の番号で落ちる。
#   3) 復元: restore-drill が小さな行数で PASS し、RTO を超えたら落ちる。
#   4) 計画の関所: plan-gate が置き換えと削除で止め、許す物の一覧の外を承認 2 人の経路へ回す。
#   5) データベースの権限: db-grants-check が正本との食い違いを落とし、見本が正本と合う。
#   6) 部品の一覧の差分: deps-diff が新しい部品と版の変更を知らせ、危ない形を止める。
#   7) 自前のコード: egress-check が外へ移る処理と外へ送る処理を落とし、見本の API が通る。
#   8) 移行の文: migrate-gate が許す文の一覧の外を落とし、移行の段の正例を通す。
# 出力: ケースごとの行と、最後に RESULT: PASS|FAIL evals infra (<合格>/<全部>)。
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
HERE="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
SKILL="$(cd "$HERE/.." && pwd -P)"
ROOT="$(cd "$SKILL/../.." && pwd -P)"
S="$SKILL/scripts"
FX="$HERE/fixtures"
pass=0; total=0
judge() {  # judge <名前> <期待> <実際>
  total=$((total + 1))
  if [ "$2" = "$3" ]; then pass=$((pass + 1)); printf 'PASS evals infra %s（期待 %s）\n' "$1" "$2"
  else printf 'FAIL evals infra %s（期待 %s、実際 %s）\n' "$1" "$2" "$3"; fi
}
verdict() {  # verdict <検査> <引数...> → PASS|FAIL
  if bash "$S/$1.sh" "${@:2}" >/dev/null 2>&1; then echo PASS; else echo FAIL; fi
}
has() {  # has <検査> <文言> <引数...> → 出力に文言があれば PASS
  if bash "$S/$1.sh" "${@:3}" 2>&1 | grep -q -- "$2"; then echo PASS; else echo FAIL; fi
}

# 1) 設計書
judge "1 examples/infra-design-order-list.md が arch-check を通る" PASS "$(verdict arch-check "$SKILL/examples/infra-design-order-list.md")"
judge "2 templates/infra-design.md が「雛形の穴」で落ちる" PASS "$(has arch-check '\[雛形の穴\]' "$SKILL/templates/infra-design.md")"
for rule in "6 本の柱" ネットワーク IAM 秘密情報 暗号化 監査ログ 復元 目標と実測 環境の差 費用の幅 流出経路 信頼の根 攻撃者の目 推測; do
  judge "3 fixtures/bad-design.md が「$rule」で落ちる" PASS "$(has arch-check "\\[$rule\\]" "$FX/bad-design.md")"
done

# 2) 構成コード
judge "4 fixtures/good-iac が iac-scan を通る" PASS "$(verdict iac-scan --fixture "$FX/good-iac")"
bad_out="$(bash "$S/iac-scan.sh" --fixture "$FX/bad-iac" 2>&1)"
for n in 001 002 003 004 005 006 007 008 009 010 011 012; do
  if printf '%s\n' "$bad_out" | grep -q "\[IAC-$n "; then got=PASS; else got=FAIL; fi
  judge "5 fixtures/bad-iac が IAC-$n で落ちる" PASS "$got"
done
if printf '%s\n' "$bad_out" | grep -q '\[例外の理由\]'; then got=PASS; else got=FAIL; fi
judge "5 fixtures/bad-iac の理由の無い例外が落ちる" PASS "$got"
if printf '%s\n' "$bad_out" | grep -q '\[境界の外\]'; then got=PASS; else got=FAIL; fi
judge "5 fixtures/bad-iac の境界の外の操作が落ちる" PASS "$got"
if [ -d "$ROOT/samples/infra" ]; then
  judge "6 samples/infra が iac-scan を通る" PASS "$(verdict iac-scan "$ROOT/samples/infra")"
  work="$(mktemp -d)"; trap 'rm -rf "$work"' EXIT
  cp -R "$ROOT/samples/infra/." "$work/"
  sed -i.bak 's/publicly_accessible    = false/publicly_accessible    = true/' "$work/database.tf"
  cat >> "$work/network.tf" <<'TF'

resource "aws_vpc_security_group_ingress_rule" "ssh_world" {
  security_group_id = aws_security_group.api.id
  ip_protocol       = "tcp"
  from_port         = 22
  to_port           = 22
  cidr_ipv4         = "0.0.0.0/0"
}
TF
  sed -i.bak -E 's/^backup_retention_days( *)= 14$/backup_retention_days\1= 1/' "$work/env/prod.tfvars"
  broken="$(bash "$S/iac-scan.sh" "$work" 2>&1)"
  for n in 006 004 008; do
    if printf '%s\n' "$broken" | grep -q "\[IAC-$n "; then got=PASS; else got=FAIL; fi
    judge "7 見本を壊した写しが IAC-$n で落ちる" PASS "$got"
  done
fi

# 2b) 計画の関所
judge "10 plan-gate の自己試験（一覧の内と外・置き換え・削除・データを消す変更・来歴・部品・前提の検査）が通る" PASS "$(has plan-gate '^RESULT: PASS plan-gate --selftest' --selftest)"

# 2c) データベースの権限と正本
judge "11 db-grants-check の自己試験が通る" PASS "$(has db-grants-check '^RESULT: PASS db-grants-check --selftest' --selftest)"
if [ -f "$ROOT/samples/api/db-access.json" ] && [ -f "$ROOT/samples/infra/db/roles.sql" ]; then
  judge "12 見本の roles.sql が正本の db-access.json と合う" PASS "$(verdict db-grants-check "$ROOT/samples/api/db-access.json" "$ROOT/samples/infra/db/roles.sql")"
fi

# 2d) 部品の一覧の差分
judge "13 deps-diff の自己試験（新しい部品・版・取り込み元・指紋・入れ時の命令）が通る" PASS "$(has deps-diff '^RESULT: PASS deps-diff --selftest' --selftest)"

# 2e) 自前のコードの外へ移る処理
judge "14 egress-check の自己試験（画面の移動・ビーコン・外の宛先・API の外への接続）が通る" PASS "$(has egress-check '^RESULT: PASS egress-check --selftest' --selftest)"
if [ -d "$ROOT/samples/api" ]; then
  judge "15 見本の API に外へ移る処理が無い" PASS "$(verdict egress-check "$ROOT/samples/api")"
fi

# 2f) 移行の文の許す一覧
judge "16 migrate-gate の自己試験（行の写し・関数・規則・権限・スキーマ・psql の命令・既定値の式）が通る" PASS "$(has migrate-gate '^RESULT: PASS migrate-gate --selftest' --selftest)"

# 3) 復元
judge "8 restore-drill（5000 行、RTO 60 秒）が通る" PASS "$(has restore-drill '^RESULT: PASS restore-drill (行 5000' --rows 5000 --rto 60)"
judge "9 restore-drill が RTO 0 秒で落ちる" PASS "$(has restore-drill '\[RTO\]' --rows 5000 --rto 0)"

if [ "$pass" -eq "$total" ] && [ "$total" -gt 0 ]; then echo "RESULT: PASS evals infra ($pass/$total)"; exit 0; fi
echo "RESULT: FAIL evals infra ($pass/$total)"; exit 1
