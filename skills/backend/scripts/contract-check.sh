#!/usr/bin/env bash
# skills/backend/scripts/contract-check.sh — 契約（OpenAPI 3.1 の JSON）の検査。
#   1 版: 全操作にエラーの 4 点（分類・原因・対処・追跡番号）の応答、書き込みに必須の Idempotency-Key、認可の方式、
#         一覧に起点の送り（after か cursor、limit の上限、nextCursor。offset と page は不可）。
#   2 版: 契約を壊す変更（操作の削除、応答の欄の削除、必須の入力の追加、型の変更、列挙値の削除、状態番号の削除）。
# 使い方: contract-check.sh <契約.json> [<新版.json>]   /   contract-check.sh --selftest
# 判定の本体は backend_check.py（同じディレクトリ）。出力は FAIL と MEASURE の行と RESULT: PASS|FAIL。1 件でも FAIL なら終了コード 1。
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
dir="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
case "${1:-}" in
  "") echo "使い方: contract-check.sh <契約.json> [<新版.json>] | --selftest"; exit 2 ;;
  *) exec python3 -I "$dir/backend_check.py" contract "$@" ;;
esac
