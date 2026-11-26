#!/usr/bin/env bash
# skills/backend/scripts/data-query.sh — クエリを 1 本、読み取りだけで回し、クエリの記録（JSON Lines）に書く。
#   許す文は 1 文だけの SELECT と WITH … SELECT。許す関数の一覧の外（外へ書き出す関数、状態を変える関数）は回さずに落とす。
#   sqlite は mode=ro の URI と query_only で開き、mode=rw などの開き方は FAIL [読み取りだけ] にする。
#   記録には番号（Q-001 の形の続き番号）、環境の名前、時刻、SQL、結果、ハッシュ値を書く。AI は記録を手で書かない。
#   個人情報らしい列（人の表の name、email、氏名、住所など）を COUNT などの集計の外で出す文は、別名や関数で包んでも記録しない。
#   メールと電話番号の形の値と、2000 字を超える値も記録しない。PostgreSQL と MySQL は、向き先が手元のときだけ回す。
#   本番の数は、依頼者が回した結果（CSV）を --import で取り込む。DB にはつながず、同じ形で記録に書く。「本番」の環境の名前は --import だけ。
# 使い方: data-query.sh --db <sqlite のファイル> --env <環境の名前> --log <記録.jsonl> --sql <文> [--purpose <何の数か>]
#         data-query.sh --engine postgres|mysql --database <名前> --env … --log … --sql …（psql・mysql が無ければ FAIL [道具が無い]）
#         data-query.sh --import <結果.csv> --env <本番の集計の書き出し> --log … --sql <依頼者に渡した文>
#         data-query.sh --selftest
# 判定の本体は data_tools.py（同じディレクトリ）。出力は QUERY と結果の行と RESULT: PASS|FAIL。FAIL なら終了コード 1。
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
dir="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
case "${1:-}" in
  "") echo "使い方: data-query.sh --db <sqlite のファイル> --env <環境の名前> --log <記録.jsonl> --sql <文> | --selftest"; exit 2 ;;
  *) exec python3 -I "$dir/data_tools.py" query "$@" ;;
esac
