#!/usr/bin/env bash
# skills/frontend/scripts/frontend-plan-check.sh <実装計画> — 実装計画の検査。
#   14 節の有無、構成の表の動く場所（サーバー／ブラウザ／両方）と理由、状態の重複と置き場、取得の上限時間と失敗時、
#   性能予算の LCP・INP・CLS と数字と測定条件、テストの対応表のレベルとサイズ、横断事項（動き・国際化・安全・型）、雛形の穴。
# 使い方: frontend-plan-check.sh <実装計画>   /   frontend-plan-check.sh --selftest
# 判定の本体は frontend_check.py（同じディレクトリ）。出力は FAIL/WARN の行と RESULT: PASS|FAIL。1 件でも FAIL なら終了コード 1。
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
dir="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
case "${1:-}" in
  "") echo "使い方: frontend-plan-check.sh <実装計画> | --selftest"; exit 2 ;;
  *) exec python3 -I "$dir/frontend_check.py" plan "$@" ;;
esac
