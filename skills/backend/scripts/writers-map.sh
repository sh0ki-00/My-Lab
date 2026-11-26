#!/usr/bin/env bash
# skills/backend/scripts/writers-map.sh — テーブルごとの書き込む処理の候補を出す。
#   コード: INSERT・UPDATE・DELETE・REPLACE・MERGE・TRUNCATE の文と、主な ORM の書き方（Laravel、Rails、Django、SQLAlchemy、
#   Prisma、TypeORM、Sequelize、Knex）を拾う。モデルの表は宣言（Laravel の table の属性、Rails の table_name、Django の db_table、
#   SQLAlchemy の __tablename__ など）か、モデルの名前で決める。
#   表の名前は、引用（"…"、`…`、[…]）の中の空白や日本語の字も、引用の無い日本語の名前も拾う。
#   DB: トリガーの本文から書く先の表を拾う（スキーマの写しか、読み取りだけで開いた DB から）。
#   書き込む処理が 1 つも見つからない表は「不明」と出す。定時の処理と外からの通知の候補も並べる。
# 使い方: writers-map.sh --code <コードの置き場> [--schema <写し.json> | --db <sqlite のファイル>] [--tables a,b]
#         writers-map.sh --selftest
# 判定の本体は data_tools.py（同じディレクトリ）。出力は書き込む処理の表（下書き）と RESULT: PASS|FAIL。FAIL なら終了コード 1。
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
dir="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
case "${1:-}" in
  "") echo "使い方: writers-map.sh --code <コードの置き場> [--schema <写し.json> | --db <sqlite のファイル>] | --selftest"; exit 2 ;;
  *) exec python3 -I "$dir/data_tools.py" writers "$@" ;;
esac
