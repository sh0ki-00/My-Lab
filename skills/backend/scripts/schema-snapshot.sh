#!/usr/bin/env bash
# skills/backend/scripts/schema-snapshot.sh — 実物の DB からスキーマ（テーブル・列・型・制約・インデックス・トリガー・ビュー）を
#   読み取りだけで書き出し、ハッシュ値を出す。別の写しか、マイグレーションの SQL から作った形と比べ、ずれを DIFF の行に並べる。
#   sqlite の生成列と隠れ列も写しに入れる（table_xinfo）。マイグレーションは sqlite で流せる素の SQL だけを受ける。
#   --expect-hash に辞書の鮮度の欄のハッシュ値を渡すと、今の DB の形が変わっていれば FAIL にする（調査の前に回す）。
# 使い方: schema-snapshot.sh --db <sqlite のファイル> [--out <写し.json>] [--env <環境の名前>]
#           [--compare <別の写し.json>] [--from-migrations <SQL...>] [--expect-hash <ハッシュ値>]
#         schema-snapshot.sh --engine postgres|mysql --database <名前> …（psql・mysql が無ければ FAIL [道具が無い]）
#         schema-snapshot.sh --selftest
# 判定の本体は data_tools.py（同じディレクトリ）。出力は HASH・DIFF・FAIL の行と RESULT: PASS|FAIL。FAIL なら終了コード 1。
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
dir="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
case "${1:-}" in
  "") echo "使い方: schema-snapshot.sh --db <sqlite のファイル> [--out <写し.json>] [--compare <写し.json>] [--from-migrations <SQL...>] | --selftest"; exit 2 ;;
  *) exec python3 -I "$dir/data_tools.py" snapshot "$@" ;;
esac
