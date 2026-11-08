#!/usr/bin/env bash
# skills/designer/scripts/review-check.sh <監修記録> — 監修記録の検査。
#   7 つの節、指摘の表の 5 欄、判定の 3 択と条件の確認方法、AI らしさの件数と帯、WCAG の値、雛形の穴。
# 使い方: review-check.sh <監修記録>   /   review-check.sh --selftest
# 判定の本体は design_check.py（同じディレクトリ）。出力は FAIL/WARN の行と RESULT: PASS|FAIL。1 件でも FAIL なら終了コード 1。
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
dir="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
case "${1:-}" in
  "") echo "使い方: review-check.sh <監修記録> | --selftest"; exit 2 ;;
  *) exec python3 -I "$dir/design_check.py" review "$@" ;;
esac
