#!/usr/bin/env bash
# skills/sre/scripts/slo-doc-check.sh — SLO 定義書の欠けの検査。
#   利用者に近い測り点の SLI、目標と期間、承認者（名前・日付・判断）、エラーバジェットを使い切ったときの決まり、
#   多窓の通知の表と、通知 1 つに 1 本の Runbook への結び、Runbook の 7 つの節（症状・確かめる命令・原因の見分け方・
#   直す命令・どれにも合わないとき・直ったことの確かめ・戻し方）と命令のコード。承認者の無い SLO は [承認者] で落とす。
# 使い方: slo-doc-check.sh <SLO 定義書.md>...   /   slo-doc-check.sh --selftest
# 判定の本体は sre_check.py（同じディレクトリ）。出力は FAIL と MEASURE の行と RESULT: PASS|FAIL。1 件でも FAIL なら終了コード 1。
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
dir="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
case "${1:-}" in
  "") echo "使い方: slo-doc-check.sh <SLO 定義書.md>... | --selftest"; exit 2 ;;
  *) exec python3 -I "$dir/sre_check.py" slo "$@" ;;
esac
