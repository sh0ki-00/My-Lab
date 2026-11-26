#!/usr/bin/env bash
# skills/catchup/evals/run.sh — catchup の試験ケース。機械で判定できる分だけを回す。
#   1) 自己試験: catchup-facts.sh と map-check.sh の --selftest。
#   2) 完成例: examples/messy-shop の地図が map-check.sh を通り（--root は samples/messy-shop）、6 つの節と入口の 1 枚が全部「新しい」。
#      入口は 80 行以内（C-7）。データの節（backend の完成例）が data-dictionary-check.sh を通る。テンプレートは穴で落ちる。
#   3) 完成例の事実は、回し直しても同じ: samples/messy-shop に catchup-facts.sh を同じ --exclude で回し、履歴の外の事実が
#      完成例の facts.jsonl と同じ（種類、項目、値、根拠）。answers/ と問いは読まない。
#   4) map-check.sh の負例: 完成例と app/ の写しを一時のディレクトリで崩す。入口が 81 行を超える、罠への案内を消す、
#      根拠を消す、行番号を 9999 にする、記録に無い Q の番号、事実の記録を書き換える、追記の候補の状態、入口の commit を変える、
#      stamp.json を消す、根拠のコードを 1 行変える（C-2。古い節を SECTION で名指しする）。どれも決まりの名前で落ちる。
#      査読のあとに足した負例: ルートのファイルを足す（根拠に挙げていなくても入口が古い）、マイグレーションを足す（データが古い）、
#      DB の読み取りの許可の欄を消す、入口の基準の数字を 1 つ変える（C-5）、データの節の食い違いと書き込む処理の根拠を消す（C-2）。
#   5) 振り分け（C-1）: routing-c1.tsv の依頼文を route で判定し、catchup に当たるかが期待と同じ（当たるのは yes の行だけ）。
#      どの依頼文も skills/secretary/evals/routing-cases.tsv にある。
# 出力: ケースごとの行と、最後に RESULT: PASS|FAIL evals catchup (<合格>/<全部>)。
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
HERE="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
SKILL="$(cd "$HERE/.." && pwd -P)"
ROOT="$(cd "$SKILL/../.." && pwd -P)"
S="$SKILL/scripts"
EX="$SKILL/examples/messy-shop"
DICT="$ROOT/skills/backend/examples/data-dictionary-messy-shop.md"
SAMPLE="$ROOT/samples/messy-shop"
pass=0; total=0
judge() {  # judge <名前> <期待> <実際>
  total=$((total + 1))
  if [ "$2" = "$3" ]; then pass=$((pass + 1)); printf 'PASS evals catchup %s（期待 %s）\n' "$1" "$2"
  else printf 'FAIL evals catchup %s（期待 %s、実際 %s）\n' "$1" "$2" "$3"; fi
}
verdict() {  # verdict <スクリプト> <引数...> → PASS|FAIL
  if bash "$S/$1.sh" "${@:2}" >/dev/null 2>&1; then echo PASS; else echo FAIL; fi
}
has() {  # has <スクリプト> <文言> <引数...> → 出力に文言があれば PASS
  if bash "$S/$1.sh" "${@:3}" 2>&1 | grep -q -- "$2"; then echo PASS; else echo FAIL; fi
}

# 1) 自己試験
judge "catchup-facts.sh --selftest" PASS "$(verdict catchup-facts --selftest)"
judge "map-check.sh --selftest" PASS "$(verdict map-check --selftest)"

# 2) 完成例とテンプレート
judge "完成例の地図が map-check.sh を通る" PASS "$(verdict map-check --root "$SAMPLE" "$EX")"
judge "完成例の 6 つの節と入口の 1 枚が全部「新しい」" 7 "$(bash "$S/map-check.sh" --root "$SAMPLE" "$EX" 2>&1 | grep -c '^SECTION .* 新しい$')"
lines="$(wc -l < "$EX/index.md" | tr -d ' ')"
if [ "$lines" -le 80 ]; then r=PASS; else r=FAIL; fi
judge "完成例の入口は 80 行以内（$lines 行）" PASS "$r"
if bash "$ROOT/skills/backend/scripts/data-dictionary-check.sh" "$DICT" --root "$SAMPLE" >/dev/null 2>&1; then r=PASS; else r=FAIL; fi
judge "データの節（backend の完成例）が data-dictionary-check.sh を通る" PASS "$r"
judge "templates/（テンプレート）は穴で落ちる" PASS "$(has map-check '\[テンプレートの穴\]' --root "$SAMPLE" "$SKILL/templates")"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/catchup-evals.XXXXXX")" || exit 1
trap 'rm -rf "${WORK:?}"' EXIT

# 3) 完成例の事実は、回し直しても同じ
bash "$S/catchup-facts.sh" --root "$SAMPLE" --exclude answers --exclude questions.md --exclude build.py --exclude score.py \
  --exclude README.md --out "$WORK/facts.jsonl" >/dev/null 2>&1
r="$(python3 -I - "$EX/facts.jsonl" "$WORK/facts.jsonl" <<'PY'
import json
import sys


def keys(path):
    out = set()
    for line in open(path, encoding="utf-8"):
        r = json.loads(line)
        if r["kind"] != "履歴":
            out.add((r["kind"], r["item"], r["value"], r["source"], r["line"], r["command"]))
    return out


a, b = keys(sys.argv[1]), keys(sys.argv[2])
print("PASS" if a and a == b else f"FAIL（完成例だけ {len(a - b)} 件、回し直しだけ {len(b - a)} 件）")
PY
)"
judge "完成例の事実（履歴の外）を回し直すと同じになる" PASS "$r"

# 4) map-check.sh の負例。完成例の地図と backend の辞書を、同じ相対の位置に写して崩す
reset() {
  rm -rf "${WORK:?}/kit" "${WORK:?}/root"
  mkdir -p "$WORK/kit/skills/catchup/examples" "$WORK/kit/skills/backend/examples" "$WORK/root"
  cp -R "$EX" "$WORK/kit/skills/catchup/examples/messy-shop"
  cp "$DICT" "$WORK/kit/skills/backend/examples/"
  cp -R "$SAMPLE/app" "$WORK/root/app"
}
M="$WORK/kit/skills/catchup/examples/messy-shop"
reset
judge "写した完成例も通る" PASS "$(verdict map-check --root "$WORK/root" "$M")"
reset; for _ in $(seq 1 30); do echo "補足の行です。" >> "$M/index.md"; done
judge "入口が 80 行を超えると [入口の長さ] で落ちる（C-7）" PASS "$(has map-check '\[入口の長さ\]' --root "$WORK/root" "$M")"
reset; grep -v '^| 罠 | \[traps.md\]' "$EX/index.md" > "$M/index.md"
judge "罠の節への案内を消すと [節の案内] で落ちる（C-7）" PASS "$(has map-check '\[節の案内\]' --root "$WORK/root" "$M")"
reset; sed 's/| 設定のファイルは無い | F-047 |/| 設定のファイルは無い | 読んだ |/' "$EX/team.md" > "$M/team.md"
judge "表の行の根拠を消すと [根拠] で落ちる（C-2）" PASS "$(has map-check '\[根拠\]' --root "$WORK/root" "$M")"
reset; sed 's#app/db.py:10-15#app/db.py:9999#' "$EX/stack.md" > "$M/stack.md"
judge "根拠の行番号を 9999 にすると [根拠の実在] で落ちる" PASS "$(has map-check '\[根拠の実在\]' --root "$WORK/root" "$M")"
reset; sed 's/223 件（Q-050）/223 件（Q-999）/' "$EX/index.md" > "$M/index.md"
judge "記録に無い Q の番号は [根拠の実在] で落ちる" PASS "$(has map-check '\[根拠の実在\]' --root "$WORK/root" "$M")"
reset; sed 's/"value": "14 本"/"value": "15 本"/' "$EX/facts.jsonl" > "$M/facts.jsonl"
judge "事実の記録を書き換えると [ハッシュ値] で落ちる" PASS "$(has map-check '\[ハッシュ値\]' --root "$WORK/root" "$M")"
reset; printf '| 2026-11-27 | データ | 値が増えた | Q-018 | あとで |\n' >> "$M/inbox.md"
judge "追記の候補の状態が決まりの外だと [追記の候補] で落ちる" PASS "$(has map-check '\[追記の候補\]' --root "$WORK/root" "$M")"
reset; sed 's/| commit | 46cf84d/| commit | 0123abc/' "$EX/index.md" > "$M/index.md"
judge "入口の commit が stamp.json と違うと [鮮度] で落ちる" PASS "$(has map-check '\[鮮度\]' --root "$WORK/root" "$M")"
reset; rm "$M/stamp.json"
judge "stamp.json が無いと [鮮度] で落ちる" PASS "$(has map-check '\[鮮度\]' --root "$WORK/root" "$M")"
reset; printf '# 足した行\n' >> "$WORK/root/app/orders.py"
judge "根拠のコードが変わると [古い] で落ちる（C-2）" PASS "$(has map-check '\[古い\]' --root "$WORK/root" "$M")"
judge "変わったコードを根拠に持つデータの節を「古い」と名指しする" PASS "$(has map-check '^SECTION データ 古い' --root "$WORK/root" "$M")"
judge "変わったコードを根拠に持たない開発の形の節は「新しい」のまま" PASS "$(has map-check '^SECTION 開発の形 新しい' --root "$WORK/root" "$M")"
judge "--fresh も同じ節を「古い」と出し、終了コード 1" FAIL "$(verdict map-check --fresh --root "$WORK/root" "$M")"
reset
judge "--fresh は崩す前の地図で通る" PASS "$(verdict map-check --fresh --root "$WORK/root" "$M")"
reset; printf '@route("/admin/refund")\ndef refund(p):\n    return 1\n' > "$WORK/root/app/refunds.py"
judge "ルートのファイルが増えると、根拠に挙げていなくても入口を「古い」とする（C-2）" PASS "$(has map-check '^SECTION 入口 古い' --fresh --root "$WORK/root" "$M")"
reset; printf 'CREATE TABLE refunds (id INTEGER);\n' > "$WORK/root/app/migrations/005_refunds.sql"
judge "マイグレーションが増えると、データの節を「古い」とする（C-2）" PASS "$(has map-check '^SECTION データ 古い' --fresh --root "$WORK/root" "$M")"
reset; grep -v '^| DB の読み取りの許可 |' "$EX/index.md" > "$M/index.md"
judge "DB の読み取りの許可の欄を消すと [入口] で落ちる" PASS "$(has map-check '\[入口\]' --root "$WORK/root" "$M")"
reset; sed 's/| 223 件（Q-051） | 一致 |/| 224 件（Q-051） | 一致 |/' "$EX/index.md" > "$M/index.md"
judge "入口の基準の数字を 1 つ変えると [基準の数字] で落ちる（C-5）" PASS "$(has map-check '\[基準の数字\]' --root "$WORK/root" "$M")"
D2="$WORK/kit/skills/backend/examples/data-dictionary-messy-shop.md"
reset; sed 's#| app/orders.py:55、app/views.py:98、app/models.py:40 | Q-023、Q-043 |#| 読んだ | 数えた |#' "$DICT" > "$D2"
judge "データの節の食い違いの根拠を消すと [データの節] で落ちる（C-2）" PASS "$(has map-check '\[データの節\].*\[根拠\]' --root "$WORK/root" "$M")"
reset; sed 's#| customers | app/customers.py:11（会員登録） |#| customers | 会員登録 |#' "$DICT" | sed 's/1 と 0 の行は 2026-10 まで（Q-049）/1 と 0 の行がある/' > "$D2"
judge "書き込む処理の行の根拠を消すと [データの節] で落ちる（C-2）" PASS "$(has map-check '\[データの節\].*\[根拠\]' --root "$WORK/root" "$M")"

# 5) 振り分け（C-1）
hits=0; n=0
while IFS=$'\t' read -r text want || [ -n "${text:-}" ]; do
  case "$text" in ''|'#'*) continue ;; esac
  n=$((n + 1))
  skills="$(python3 -I "$ROOT/skills/secretary/scripts/secretary_check.py" route "$text" | sed -n 's/^スキル: //p')"
  case "$skills" in *catchup*) got=yes; hits=$((hits + 1)) ;; *) got=no ;; esac
  judge "振り分け「${text}」が catchup に当たるか" "$want" "$got"
  if cut -f1 "$ROOT/skills/secretary/evals/routing-cases.tsv" | grep -qxF -- "$text"; then r=PASS; else r=FAIL; fi
  judge "「${text}」が secretary の routing-cases.tsv にもある" PASS "$r"
done < "$HERE/routing-c1.tsv"
want_hits="$(grep -c "$(printf '\t')yes$" "$HERE/routing-c1.tsv")"
judge "C-1: $n 件のうち catchup に当たるのは、頼む形の ${want_hits} 件だけ" "$want_hits" "$hits"

if [ "$pass" -eq "$total" ] && [ "$total" -gt 0 ]; then echo "RESULT: PASS evals catchup ($pass/$total)"; exit 0; fi
echo "RESULT: FAIL evals catchup ($pass/$total)"; exit 1
