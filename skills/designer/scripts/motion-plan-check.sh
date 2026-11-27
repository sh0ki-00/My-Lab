#!/usr/bin/env bash
# skills/designer/scripts/motion-plan-check.sh <演出計画書> — 演出計画書（没入の型の見せ場）の検査。
#   見せ場の 5 つの条件（段が 3 つ、レイヤーが 3 つ以上、共有要素が 1 つ、動きが重なる、守りが 5 行）を見る。
#   レイヤーは、レイヤーごとの動き（時刻・長さ・変化）が 2 種類以上あることを求め、1 行に並べたレイヤーは同じ 1 つの動きと数える。
#   共有要素は 2 つ以上の段にまたがること、守りの 5 行は「なし」や打ち消しでなく、中身の印（動かさない版、飛ばすキー、
#   フォーカスの要素など）があることを求める。
#   ほかに、点滅の上限（書いた回数の最大で 1 秒に 3 回）、5 秒を超える動きの止める操作の名前、音の消音の操作の名前、
#   2 回目以降の長さ（600ms 以下）、初回の長さの枠（600〜1,400ms）、同時に動くレイヤー 4 つまで、ぼかすレイヤー 1 つまで、
#   トークンの外の長さ、雛形の穴。拍の長さと動く量（px）とトークンの表の値は、フィボナッチの数列の値だけにする
#   （[数列]。時刻の列と合計の長さは足し算で決まるので見ない）。段もレイヤーも共有要素も無い「ただのスライド」と、同じ動きをずらしただけの計画は、ここで落ちる。
# 使い方: motion-plan-check.sh <演出計画書>   /   motion-plan-check.sh --selftest
# 判定の本体は design_check.py（同じディレクトリ）。出力は FAIL/WARN の行と RESULT: PASS|FAIL。1 件でも FAIL なら終了コード 1。
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
dir="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
case "${1:-}" in
  "") echo "使い方: motion-plan-check.sh <演出計画書> | --selftest"; exit 2 ;;
  *) exec python3 -I "$dir/design_check.py" motion "$@" ;;
esac
