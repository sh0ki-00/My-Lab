#!/usr/bin/env bash
# skills/secretary/scripts/approval-request-check.sh <ファイル> — 承認伺いの検査。60 行、結論と伺い 1 点が先頭、5 要素の節、最短・最長・上限、日程の整合、推奨の印、落とし穴とやらないこと。
# 使い方: approval-request-check.sh <ファイル>   /   approval-request-check.sh --selftest
# 判定の本体は secretary_check.py（同じディレクトリ）。出力は FAIL/WARN の行と RESULT: PASS|FAIL。1 件でも FAIL なら終了コード 1。
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
dir="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
case "${1:-}" in
  "") echo "使い方: approval-request-check.sh <ファイル> | --selftest"; exit 2 ;;
  *) exec python3 -I "$dir/secretary_check.py" request "$@" ;;
esac
