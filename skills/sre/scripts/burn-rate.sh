#!/usr/bin/env bash
# skills/sre/scripts/burn-rate.sh — 多窓・多段のバーンレートの計算と、SLO 定義書の通知の表との照合。
#   計算: バーンレート = 予算の消費 × 期間 ÷ 長い窓、失敗率の閾値 = バーンレート × (1 − 目標)、短い窓 = 長い窓 ÷ 12、
#         使い切るまで = 期間 ÷ バーンレート。出典は Google SRE Workbook「Alerting on SLOs」（evals/workbook-reference.tsv に照合の表）。
# 使い方: burn-rate.sh <SLO 定義書.md>...                      文書の通知の表を計算し直し、食い違いを [食い違い] で落とす
#         burn-rate.sh --slo 99.9 [--period 30d] [--tiers 2%:1h:呼び出し,5%:6h:呼び出し,10%:3d:チケット] [--burn 1,1000]
#                                                             目標と期間から閾値の表と、使い切るまでの時間を出す
#         burn-rate.sh --reference <照合の表.tsv>                原典の値を写した表と計算を突き合わせる
#         burn-rate.sh --selftest
# 判定の本体は sre_check.py（同じディレクトリ）。1 件でも FAIL なら終了コード 1。
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
dir="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
case "${1:-}" in
  "") echo "使い方: burn-rate.sh <SLO 定義書.md>... | --slo <目標の %> [--period 30d] [--tiers …] [--burn …] | --selftest"; exit 2 ;;
  *) exec python3 -I "$dir/sre_check.py" burn "$@" ;;
esac
