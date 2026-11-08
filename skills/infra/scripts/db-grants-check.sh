#!/usr/bin/env bash
# skills/infra/scripts/db-grants-check.sh <db-access.json> <roles.sql> — データベースの権限の正本と、利用者づくりの SQL の突き合わせ。
#   正本はバックエンドの db-access.json（表ごとの読み書きの列と、行の制限の掛け方）。インフラの roles.sql はそれに合わせる。
#   表の権限、列の単位の INSERT と UPDATE、正本に無い表と一括の権限、行の制限（店の列・親の表・鍵と via の道・全行の読むだけ・権限なし）、
#   実行中の文の見方（pg_stat_activity）の取り上げ、
#   全店を見る値（shop_scope）、SQL の最後の検査の一覧が、1 つでも正本と違えば落とす。
#   店は API が書ける値（app.shop_id）で決めない。鍵の表は鍵のハッシュ（app.key_hash）の合う行だけを見せ、店はそこから DB の側で引く。
# 使い方: db-grants-check.sh samples/api/db-access.json samples/infra/db/roles.sql   /   db-grants-check.sh --selftest
# 判定の本体は db_grants_check.py（同じディレクトリ）。出力は FAIL の行と RESULT: PASS|FAIL。1 件でも FAIL なら終了コード 1。
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
dir="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
case "${1:-}" in
  "") echo "使い方: db-grants-check.sh <db-access.json> <roles.sql> | --selftest"; exit 2 ;;
  *) exec python3 -I "$dir/db_grants_check.py" "$@" ;;
esac
