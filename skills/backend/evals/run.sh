#!/usr/bin/env bash
# skills/backend/evals/run.sh — backend の試験ケース（cases.md の 6 件）。機械で判定できる分だけを回す。
#   1) 完成例と雛形: 計画の完成例は通り、雛形は穴埋めのままなので落ちる。契約の完成例と雛形は 1 版の決まりを通る。
#   2) 計画の負例 fixtures/bad-plan.md が、12 の決まりで名指しで落ちる。
#   3) 契約の負例: fixtures/bad-contract.json が 4 つの決まりで、壊した 2 版目が 6 種類の壊す変更で落ちる。同じ版どうしは通る。
#   4) 問い合わせの数と p99: 見本の API は完成例の予算で通り、わざと N+1 にした写しは [N+1] で落ちる。
#   5) 見本の API の試験（契約の形、認可、冪等、エラー、ログ）が通る。
#   6) 既存のデータを読む道具: fixtures/data/shop.sql のサンプルの DB を一時のディレクトリに作り、写し・集計・クエリ・書き込む処理を回す。
#      辞書と調査の文書の正例は通り、わざと崩した例（結論の数を 1 つ変える、辞書に無い値で絞る、UPDATE の文を記録に混ぜる、
#      読み取り専用でない開き方、値を消す、テーブルを消す、行番号、結果の書き換え、メール）は決まりの名前で落ちる。テンプレートは落ちる。
#      査読のあとに足した負例: 別名・関数で包んだ個人情報、\r で終える注釈と U& と日本語の名前の関数、本番の環境の名前、
#      結論の数の 5 つの書き方（変わる条件の文、バッククォート、生の数の %、日の付いた数、漢数字）、lower() と "…" の条件の値、
#      データの節の根拠と書き込む処理の網羅、基準の数字（行が無い、一致なのに値が違う）、直下の外を指す根拠。
#      辞書の完成例 examples/data-dictionary-messy-shop.md が --root samples/messy-shop で通る。
#      git の無いプロジェクトの辞書: commit の欄が「git なし」と作った時刻と根拠のハッシュ値なら通り、ハッシュ値が無い、
#      git の作業ツリーの中、根拠のファイルが変わった、の 3 つは [鮮度] で落ちる。
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
  judge "fixtures/bad-plan.md が「${rule}」で落ちる" PASS "$(has backend-plan-check "\\[$rule\\]" "$FX/bad-plan.md")"
done

# 3) 契約の負例と 2 版の比較
for rule in "エラーの 4 点" 冪等キー 認可 起点の送り; do
  judge "fixtures/bad-contract.json が「${rule}」で落ちる" PASS "$(has contract-check "\\[$rule\\]" "$FX/bad-contract.json")"
done
for rule in 操作の削除 応答の欄の削除 必須の入力の追加 型の変更 列挙値の削除 状態番号の削除; do
  judge "壊した 2 版目が「${rule}」で落ちる" PASS "$(has contract-check "\\[$rule\\]" "$EX/openapi-order-list.json" "$EX/openapi-order-list-v2-breaking.json")"
done
judge "同じ版どうしの比較は通る" PASS "$(verdict contract-check "$EX/openapi-order-list.json" "$EX/openapi-order-list.json")"

# 4) 問い合わせの数と p99
judge "samples/api が完成例の予算で通る（24 件と 400 件）" PASS "$(verdict query-count-check --plan "$EX/backend-plan-order-list.md" --requests 100)"
judge "わざと N+1 にした写しが [N+1] で落ちる" PASS "$(has query-count-check '\[N+1\]' --app "$FX/n1_orders_api.py" --budget-ms 300 --requests 20)"

# 5) 見本の API の試験
if python3 -I "$ROOT/samples/api/test_orders_api.py" >/dev/null 2>&1; then r=PASS; else r=FAIL; fi
judge "samples/api/test_orders_api.py（契約・認可・冪等・エラー・ログ）" PASS "$r"

# 6) 既存のデータを読む道具（サンプルの DB は一時のディレクトリに作り、道具は読み取りだけで開く）
DATA="$FX/data"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/backend-evals.XXXXXX")" || exit 1
trap 'rm -rf "${WORK:?}"' EXIT
python3 -I -c 'import sqlite3, sys; c = sqlite3.connect(sys.argv[1]); c.executescript(open(sys.argv[2], encoding="utf-8").read()); c.commit()' \
  "$WORK/shop.db" "$DATA/shop.sql"
DB=(--db "$WORK/shop.db" --env "手元の作り物（評価用のサンプルの DB）")
LOG="$WORK/queries.jsonl"
judge "schema-snapshot.sh がサンプルの DB を写す" PASS "$(verdict schema-snapshot "${DB[@]}" --out "$WORK/schema.json")"
judge "data-profile.sh が全部のテーブルを集計する（Q-001〜Q-028）" PASS "$(verdict data-profile "${DB[@]}" --log "$LOG" --draft "$WORK/draft.md")"
query() { verdict data-query "${DB[@]}" --log "$LOG" --sql "$1"; }
judge "data-query.sh が 10 月のキャンセルを値ごとに数える（Q-029）" PASS "$(query "SELECT status, COUNT(*) AS n FROM orders WHERE created_at >= '2026-10-01' AND created_at < '2026-11-01' AND status IN ('cancel', 'canceled') GROUP BY status ORDER BY status")"
judge "data-query.sh が検算を別の表で数える（Q-030）" PASS "$(query "SELECT COUNT(*) AS n FROM order_events WHERE kind LIKE 'cancel%' AND created_at >= '2026-10-01' AND created_at < '2026-11-01'")"
judge "data-query.sh が辞書に無い値で絞る文も記録する（Q-031。検査で落とす）" PASS "$(query "SELECT COUNT(*) AS n FROM orders WHERE status = 'cancelled' AND created_at >= '2026-10-01' AND created_at < '2026-11-01'")"
judge "data-query.sh が lower() で包んだ列の条件も記録する（Q-032。検査で落とす）" PASS "$(query "SELECT COUNT(*) AS n FROM orders WHERE lower(status) = 'cancelled'")"
judge "data-query.sh が \"…\" で書いた条件も記録する（Q-033。検査で落とす）" PASS "$(query 'SELECT COUNT(*) AS n FROM orders WHERE status = "cancelled"')"
before="$(wc -l < "$LOG" | tr -d ' ')"
judge "data-query.sh が UPDATE を回さずに落とす" PASS "$(has data-query '\[一覧の外の文\]' "${DB[@]}" --log "$LOG" --sql "UPDATE orders SET status = 'canceled'")"
judge "data-query.sh が読み取り専用でない開き方（mode=rw）を落とす" PASS "$(has data-query '\[読み取りだけ\]' --db "file:$WORK/shop.db?mode=rw" --env x --log "$LOG" --sql "SELECT 1")"
pii() { has data-query '\[個人が分かる値\]' "${DB[@]}" --log "$LOG" --sql "$1"; }
judge "別名を付けた会員の名前（name AS n）を [個人が分かる値] で落とす" PASS "$(pii "SELECT name AS n FROM customers")"
judge "形を変えたメール（replace）を [個人が分かる値] で落とす" PASS "$(pii "SELECT replace(email, '@', ' at ') AS x FROM customers")"
judge "形を変えたメール（hex）を [個人が分かる値] で落とす" PASS "$(pii "SELECT hex(email) AS x FROM customers")"
judge "\\r で終える注釈の後ろの DELETE を [1 文だけ] で落とす" PASS "$(has data-query '\[1 文だけ\]' "${DB[@]}" --log "$LOG" --sql $'SELECT COUNT(*) AS n FROM orders -- x\r; DELETE FROM orders')"
printf 'n\n24\n' > "$WORK/prod.csv"
judge "--import でも \\r の注釈の後ろの DELETE を [1 文だけ] で落とす" PASS "$(has data-query '\[1 文だけ\]' --env 本番の集計の書き出し --log "$LOG" --import "$WORK/prod.csv" --sql $'SELECT COUNT(*) AS n FROM orders -- x\r; DELETE FROM orders')"
judge "U& の引用を [書き方] で落とす" PASS "$(has data-query '\[書き方\]' "${DB[@]}" --log "$LOG" --sql "SELECT U&\"pg_sleep\" UESCAPE '!' (10) AS n")"
judge "日本語の名前の関数を [関数の呼び出し] で落とす" PASS "$(has data-query '\[関数の呼び出し\]' "${DB[@]}" --log "$LOG" --sql "SELECT 書き込み(1) AS n")"
judge "本番の環境の名前で DB につなぐと [環境の名前] で落ちる" PASS "$(has data-query '\[環境の名前\]' --db "$WORK/shop.db" --env 本番 --log "$LOG" --sql "SELECT COUNT(*) AS n FROM orders")"
judge "落とした文は記録に書かない" "$before" "$(wc -l < "$LOG" | tr -d ' ')"
if grep -q '@' "$LOG"; then r=FAIL; else r=PASS; fi
judge "記録に個人が分かる値（メールの形）が無い" PASS "$r"
judge "writers-map.sh が古い値を書く定時の処理を拾う" PASS "$(has writers-map 'batch/daily.py:5（UPDATE' --code "$DATA/code" --schema "$WORK/schema.json")"
judge "writers-map.sh がトリガーを書き込む処理に数える" PASS "$(has writers-map '| order_events | トリガー orders_status_event' --code "$DATA/code" --schema "$WORK/schema.json")"
judge "writers-map.sh が書き込む処理の無い表を「不明」と出す" PASS "$(has writers-map '| orders_old | 不明 |' --code "$DATA/code" --schema "$WORK/schema.json")"
cp "$DATA/dictionary.md" "$DATA/oct-cancel.md" "$WORK/"
CHK=(--root "$DATA/code")
judge "辞書と調査の文書の正例が通る" PASS "$(verdict data-dictionary-check "$WORK/dictionary.md" "$WORK/oct-cancel.md" "${CHK[@]}")"
judge "templates/data-dictionary.md（テンプレートは落ちる）" FAIL "$(verdict data-dictionary-check "$SKILL/templates/data-dictionary.md")"
sed 's/キャンセルは 4 件/キャンセルは 5 件/' "$WORK/oct-cancel.md" > "$WORK/neg-number.md"
judge "結論の数を 1 つ変えると [数字の出どころ] で落ちる" PASS "$(has data-dictionary-check '\[数字の出どころ\]' "$WORK/dictionary.md" "$WORK/neg-number.md" "${CHK[@]}")"
n=0
bt='`'
for repl in 'キャンセルは 5 件で、結論が変わる条件は返品の扱いです。' "キャンセルは ${bt}5${bt} 件です。" 'キャンセルは 4 件で、前の月より 3% 増えました。' \
            'キャンセルは 4 件で、注文から取り消しまで平均 12 日でした。' 'キャンセルは五件です。'; do
  n=$((n + 1))
  sed "s/キャンセルは 4 件です。/${repl}/" "$WORK/oct-cancel.md" > "$WORK/neg-number-${n}.md"
  judge "結論の数の書き方 ${n}（${repl}）も [数字の出どころ] で落ちる" PASS "$(has data-dictionary-check '\[数字の出どころ\]' "$WORK/dictionary.md" "$WORK/neg-number-${n}.md" "${CHK[@]}")"
done
sed 's/| Q-030 | 実測 |/| Q-031 | 実測 |/' "$WORK/oct-cancel.md" > "$WORK/neg-condition.md"
judge "辞書に無い値（cancelled）で絞ると [条件の値] で落ちる" PASS "$(has data-dictionary-check '\[条件の値\]' "$WORK/dictionary.md" "$WORK/neg-condition.md" "${CHK[@]}")"
for q in Q-032 Q-033; do
  sed "s/| Q-030 | 実測 |/| $q | 実測 |/" "$WORK/oct-cancel.md" > "$WORK/neg-condition-$q.md"
  judge "lower() と \"…\" の条件の値（${q}）も [条件の値] で落ちる" PASS "$(has data-dictionary-check '\[条件の値\]' "$WORK/dictionary.md" "$WORK/neg-condition-$q.md" "${CHK[@]}")"
done
sed 's#| app/Models/Order.php:13 | Q-020 |#| 読んだ | 数えた |#' "$WORK/dictionary.md" > "$WORK/neg-ledger.md"
judge "食い違いの行の根拠を消すと [根拠] で落ちる（データの節）" PASS "$(has data-dictionary-check '\[根拠\]' "$WORK/neg-ledger.md" "${CHK[@]}")"
grep -v '^| customers | web/customers.js:3' "$WORK/dictionary.md" > "$WORK/neg-writers.md"
judge "書き込む処理の表からテーブルを消すと [書き込む処理] で落ちる" PASS "$(has data-dictionary-check '\[書き込む処理\]' "$WORK/neg-writers.md" "${CHK[@]}")"
grep -v '^| キャンセル | status が cancel' "$WORK/dictionary.md" > "$WORK/neg-base-none.md"
judge "基準の数字の行を消すと [基準の数字] で落ちる（C-5）" PASS "$(has data-dictionary-check '\[基準の数字\]' "$WORK/neg-base-none.md" "${CHK[@]}")"
sed 's/10 月は 4 件（依頼の文/10 月は 300 件（依頼の文/' "$WORK/dictionary.md" > "$WORK/neg-base-diff.md"
judge "一致と書いて基準の値と数えた値が違うと [基準の数字] で落ちる（C-5）" PASS "$(has data-dictionary-check '\[基準の数字\]' "$WORK/neg-base-diff.md" "${CHK[@]}")"
sed 's#（app/Models/Order.php:13）#（../dictionary.md:1）#' "$WORK/dictionary.md" > "$WORK/neg-outside.md"
judge "直下の外のファイルを根拠にすると [根拠の実在] で落ちる" PASS "$(has data-dictionary-check '直下.*の外' "$WORK/neg-outside.md" "${CHK[@]}")"
judge "UPDATE の文を記録に混ぜると [読み取りだけ] で落ちる" PASS "$(has data-dictionary-check '\[読み取りだけ\]' "$DATA/forged-update.jsonl")"
judge "読み取り専用でない開き方の記録が [読み取りだけ] で落ちる" PASS "$(has data-dictionary-check '\[読み取りだけ\]' "$DATA/forged-rw-open.jsonl")"
sed 's/、.cancel. 1 件（Q-017）/（Q-017）/' "$WORK/dictionary.md" > "$WORK/neg-values.md"  # . は値を囲むバッククォート
judge "辞書から値を 1 つ消すと [値の一覧] で落ちる" PASS "$(has data-dictionary-check '\[値の一覧\]' "$WORK/neg-values.md" "${CHK[@]}")"
grep -v '^| orders_old |' "$WORK/dictionary.md" > "$WORK/neg-cover.md"
judge "辞書からテーブルを 1 つ消すと [辞書の網羅] で落ちる" PASS "$(has data-dictionary-check '\[辞書の網羅\]' "$WORK/neg-cover.md" "${CHK[@]}")"
sed 's#app/Models/Order.php:10）#app/Models/Order.php:10000）#' "$WORK/dictionary.md" > "$WORK/neg-line.md"
judge "根拠の行番号を 1 万にすると [根拠の実在] で落ちる" PASS "$(has data-dictionary-check '\[根拠の実在\]' "$WORK/neg-line.md" "${CHK[@]}")"
sed 's/\["canceled", 3\]/["canceled", 4]/' "$LOG" > "$WORK/neg-hash.jsonl"
judge "記録の結果の数を書き換えると [ハッシュ値] で落ちる" PASS "$(has data-dictionary-check '\[ハッシュ値\]' "$WORK/neg-hash.jsonl")"
sed 's/| サンプルの店を調べる人 |/| owner@example.invalid |/' "$WORK/dictionary.md" > "$WORK/neg-mail.md"
judge "辞書にメールの形を書くと [行のコピー] で落ちる" PASS "$(has data-dictionary-check '\[行のコピー\]' "$WORK/neg-mail.md" "${CHK[@]}")"
# データの辞書の完成例（samples/messy-shop で道具を回した辞書）。catchup の試験も同じことを見る
judge "examples/data-dictionary-messy-shop.md（辞書の完成例）が --root samples/messy-shop で通る" PASS "$(verdict data-dictionary-check "$EX/data-dictionary-messy-shop.md" --root "$ROOT/samples/messy-shop")"
# git の無いプロジェクトの辞書。commit の欄は「git なし」と作った時刻と根拠のハッシュ値（--evidence-hash の値）。
# 一時の場所の上にある git を見ないよう、GIT_CEILING_DIRECTORIES を一時の場所にする。根拠のファイルが変わると [鮮度] で落ち、git の中では通らない
NG="$WORK/nogit"
mkdir -p "$NG"
cp -R "$DATA/code" "$NG/code"
cp "$WORK/dictionary.md" "$WORK/schema.json" "$LOG" "$NG/"
export GIT_CEILING_DIRECTORIES="$WORK"
NGCHK=(--root "$NG/code")
val="$(bash "$S/data-dictionary-check.sh" --evidence-hash "$NG/dictionary.md" "${NGCHK[@]}" 2>&1 | sed -n 's/^VALUE //p')"
case "$val" in "git なし（"*"根拠のハッシュ値 "*) r=PASS ;; *) r=FAIL ;; esac
judge "--evidence-hash が git の無い場所で commit の欄の値を出す" PASS "$r"
sed 's/^| commit | .* |$/| commit | '"${val}"' |/' "$NG/dictionary.md" > "$NG/nogit.md"
judge "git の無いプロジェクトの辞書は、commit の欄が「git なし」と作った時刻と根拠のハッシュ値なら通る" PASS "$(verdict data-dictionary-check "$NG/nogit.md" "${NGCHK[@]}")"
sed 's/、根拠のハッシュ値 [0-9a-f]*）/）/' "$NG/nogit.md" > "$NG/neg-nohash.md"
judge "「git なし」に根拠のハッシュ値が無いと [鮮度] で落ちる" PASS "$(has data-dictionary-check '\[鮮度\] .*根拠のハッシュ値（' "$NG/neg-nohash.md" "${NGCHK[@]}")"
cp "$NG/nogit.md" "$WORK/nogit-in-git.md"
judge "git の作業ツリーの中では「git なし」を [鮮度] で落とす" PASS "$(has data-dictionary-check '\[鮮度\] .*git の作業ツリー' "$WORK/nogit-in-git.md" "${CHK[@]}")"
printf '// 足した行\n' >> "$NG/code/app/Models/Order.php"
judge "根拠のファイルが変わると、「git なし」の辞書は [鮮度] で落ちる" PASS "$(has data-dictionary-check '\[鮮度\] .*ハッシュ値が合わない' "$NG/nogit.md" "${NGCHK[@]}")"
unset GIT_CEILING_DIRECTORIES

if [ "$pass" -eq "$total" ] && [ "$total" -gt 0 ]; then echo "RESULT: PASS evals backend ($pass/$total)"; exit 0; fi
echo "RESULT: FAIL evals backend ($pass/$total)"; exit 1
