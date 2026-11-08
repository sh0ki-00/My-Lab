#!/usr/bin/env bash
# skills/designer/scripts/contrast-check.sh <デザイン計画書> — コントラスト比の検査。
#   計画書の色の表の全組を WCAG 2 の式で計算し、書かれた値（±0.05）と閾値（文字 4.5、部品 3.0）を確かめる。
#   --pair <文字色> <背景色> で 2 色の比を出す。
# 使い方: contrast-check.sh <デザイン計画書>   /   contrast-check.sh --pair "#767676" "#FFFFFF"   /   contrast-check.sh --selftest
# 判定の本体は design_check.py（同じディレクトリ）。出力は FAIL/WARN の行と RESULT: PASS|FAIL。1 件でも FAIL なら終了コード 1。
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
dir="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
case "${1:-}" in
  "") echo "使い方: contrast-check.sh <デザイン計画書> | --pair <文字色> <背景色> | --selftest"; exit 2 ;;
  *) exec python3 -I "$dir/design_check.py" contrast "$@" ;;
esac
