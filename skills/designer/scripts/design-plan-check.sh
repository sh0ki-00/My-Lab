#!/usr/bin/env bash
# skills/designer/scripts/design-plan-check.sh <デザイン計画書> — デザイン計画書の検査。
#   必須の節、色 4〜6 色、書体 2〜3 役と 12px・400 の下限、シグネチャの伝える情報、動きの ms と減らす設定、
#   1 文字キーの 2.1.4、既定との差の 5 軸と外した装飾、WCAG の値、雛形の穴。
# 使い方: design-plan-check.sh <デザイン計画書>   /   design-plan-check.sh --selftest
# 判定の本体は design_check.py（同じディレクトリ）。出力は FAIL/WARN の行と RESULT: PASS|FAIL。1 件でも FAIL なら終了コード 1。
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
dir="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
case "${1:-}" in
  "") echo "使い方: design-plan-check.sh <デザイン計画書> | --selftest"; exit 2 ;;
  *) exec python3 -I "$dir/design_check.py" plan "$@" ;;
esac
