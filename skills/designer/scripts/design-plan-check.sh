#!/usr/bin/env bash
# skills/designer/scripts/design-plan-check.sh <デザイン計画書> — デザイン計画書の検査。
#   画面の型の行（没入の型・既存に合わせる型・今の型）、必須の節、色 4〜6 色、書体 2〜3 役と 12px・400 の下限、
#   シグネチャの伝える情報、動きの ms と減らす設定、1 文字キーの 2.1.4、既定との差の 5 軸と外した装飾、WCAG の値、雛形の穴。
#   動きの長さは、没入の型だけ区分の枠（応答 200ms、移動 500ms、見せ場は初回 1,400ms で 2 回目から 600ms、環境は周期 4 秒以上）で見る。
#   ほかの型は 300ms の線のまま落とす。長さは秒（2.5 秒、0.9s）も ms に直して読む。環境の止める手段の打ち消し（止められない）は落とす。
#   没入の型では、方向の 3 案・世界観の設定 10 行・場面の一覧も見る。
#   書体の表の px と、動きの表の ms・秒・px は、フィボナッチの数列の値だけにする（[数列]。systems.md の 7 節）。
#   見せ場の行の長さは合計なので見ず、拍の長さは演出計画書で見る。既存に合わせる型は既存の値を使うので見ない。
#   既存に合わせる型では、色 4〜6 色と既定との差を求めない代わりに、「## 既存の値」の節の棚卸しの表（--inventory の出力）と
#   「足す値」の表（値 | 種類 | 理由）を求め、計画書の名前つきの色・動きの長さ・書体と字の大きさを、棚卸しの値か足す値と突き合わせる。
# 使い方: design-plan-check.sh <デザイン計画書>   /   design-plan-check.sh --selftest
# 判定の本体は design_check.py（同じディレクトリ）。出力は FAIL/WARN の行と RESULT: PASS|FAIL。1 件でも FAIL なら終了コード 1。
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
dir="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
case "${1:-}" in
  "") echo "使い方: design-plan-check.sh <デザイン計画書> | --selftest"; exit 2 ;;
  *) exec python3 -I "$dir/design_check.py" plan "$@" ;;
esac
