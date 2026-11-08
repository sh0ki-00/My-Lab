#!/usr/bin/env bash
# skills/backend/scripts/backend-plan-check.sh — 設計と実装計画の検査。
#   節（背景・契約・認可・冪等・エラー・データと移行・問い合わせ・性能予算・観測・流出経路・テスト・段階・未確定）と表の中身:
#   契約の操作と状態番号、認可の 403 と 404、冪等キーの保持と違う内容、エラーの 4 点、移行の戻し方、問い合わせの数と N+1、
#   p99 と測定点、1 要求 1 行のログと追跡番号、流出経路の図と 6 つの出口の守りと確認方法、テストのレベル、段階の止めたとき、雛形の穴。
# 使い方: backend-plan-check.sh <設計と実装計画>   /   backend-plan-check.sh --selftest
# 判定の本体は backend_check.py（同じディレクトリ）。出力は FAIL と MEASURE の行と RESULT: PASS|FAIL。1 件でも FAIL なら終了コード 1。
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
dir="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
case "${1:-}" in
  "") echo "使い方: backend-plan-check.sh <設計と実装計画> | --selftest"; exit 2 ;;
  *) exec python3 -I "$dir/backend_check.py" plan "$@" ;;
esac
