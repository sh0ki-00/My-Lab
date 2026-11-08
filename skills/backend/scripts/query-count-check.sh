#!/usr/bin/env bash
# skills/backend/scripts/query-count-check.sh — 問い合わせの数と p99 の実測。
#   見本の API を件数の違うデータ（既定 24 件と 400 件）で HTTP に載せ、1 要求で流れた SQL を sqlite3 の set_trace_callback で数える。
#   一覧の行が増えても SQL の数が増えないこと（N+1 が無いこと）と、出荷指示の件数で SQL が増えないことを確かめる。
#   あわせて一覧の p99（遅い方から 1%）を測り、計画書の性能予算の表の「GET /v1/orders」の p99 と比べる。
# 使い方: query-count-check.sh [--app <module.py>] [--plan <計画.md> | --budget-ms <ms>] [--sizes 24,400] [--requests 200]
#         query-count-check.sh --selftest
# 判定の本体は backend_check.py（同じディレクトリ）。出力は FAIL と MEASURE の行と RESULT: PASS|FAIL。1 件でも FAIL なら終了コード 1。
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
dir="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
case "${1:-}" in
  --selftest) exec python3 -I "$dir/backend_check.py" queries --selftest ;;
  *) exec python3 -I "$dir/backend_check.py" queries "$@" ;;
esac
