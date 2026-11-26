#!/usr/bin/env bash
# skills/backend/scripts/data-profile.sh — テーブルと列の集計（件数、空の割合、値の種類、最小と最大、最後の書き込み）を
#   読み取りだけで回し、クエリの記録（JSON Lines）に書く。文ごとに打ち切り、大きいテーブルは標本で数えて「実測（標本）」と書く。
#   個人情報らしい名前の列（日本語の名前も）と、値が 20 種類を超える列と、全文検索などの仮想表とその影の表は、件数だけにする。
#   結果にメールや電話番号の形か、2000 字を超える値があれば記録しない。
#   辞書の下書き（Markdown の表）と、罠の候補（CANDIDATE の行）を出す。
# 使い方: data-profile.sh --db <sqlite のファイル> --env <環境の名前> --log <記録.jsonl> [--tables a,b] [--draft <下書き.md>]
#           [--timeout-ms 5000] [--sample-over 200000]
#         data-profile.sh --engine postgres|mysql --database <名前> …（psql・mysql が無ければ FAIL [道具が無い]）
#         data-profile.sh --selftest
# 判定の本体は data_tools.py（同じディレクトリ）。出力は下書きと CANDIDATE・FAIL の行と RESULT: PASS|FAIL。FAIL なら終了コード 1。
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
dir="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
case "${1:-}" in
  "") echo "使い方: data-profile.sh --db <sqlite のファイル> --env <環境の名前> --log <記録.jsonl> [--draft <下書き.md>] | --selftest"; exit 2 ;;
  *) exec python3 -I "$dir/data_tools.py" profile "$@" ;;
esac
