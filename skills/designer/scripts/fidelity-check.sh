#!/usr/bin/env bash
# skills/designer/scripts/fidelity-check.sh <計画書> <tokens.css> [<実装の css/html...>] [--motion <演出計画書>] [--existing <既存の UI か棚卸しの表>] — 忠実度の検査。
#   計画書の色が tokens.css にあり、tokens.css の色が計画書にあり、時間のトークン（名前によらず ms か s の値の全部）が
#   計画の動きの表と合い、実装の css に計画に無い生の色や ms が無いことを確かめる。時間の上限は計画書の画面の型で決まり、
#   今の型と既存に合わせる型は 300ms、没入の型は見せ場の枠 1,400ms（区分ごとの枠は計画書の検査が見る）。
#   --motion を付けると（没入の型だけ）、演出計画書のトークンの表の名前と値が tokens.css と同じかも見る。
#   既存に合わせる型は --existing が要る。トークンと実装の色・時間・大きさ・書体が既存の UI に無ければ、
#   計画書の「足す値」の表に理由が無い限り落とす。
#   --inventory <既存の UI...> は、既存の値の出現数の表（棚卸しの表）を出す。保存して --existing に渡せる。
# 使い方: fidelity-check.sh <計画書> <tokens.css> [<実装...>] [--motion <演出計画書>] [--existing <既存の UI か棚卸しの表>]
#         fidelity-check.sh --inventory <既存の UI のディレクトリかファイル...>   /   fidelity-check.sh --selftest
# 判定の本体は design_check.py（同じディレクトリ）。出力は FAIL/WARN の行と RESULT: PASS|FAIL。1 件でも FAIL なら終了コード 1。
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
dir="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
case "${1:-}" in
  "") echo "使い方: fidelity-check.sh <計画書> <tokens.css> [<実装の css/html...>] [--motion <演出計画書>] [--existing <既存の UI>] | --inventory <既存の UI...> | --selftest"; exit 2 ;;
  --selftest) python3 -I "$dir/design_check.py" fidelity --selftest && exec python3 -I "$dir/design_check.py" inventory --selftest ;;
  --inventory) shift; [ $# -ge 1 ] || { echo "使い方: fidelity-check.sh --inventory <既存の UI のディレクトリかファイル...>"; exit 2; }; exec python3 -I "$dir/design_check.py" inventory "$@" ;;
  *) [ $# -ge 2 ] || { echo "使い方: fidelity-check.sh <計画書> <tokens.css> [<実装...>]"; exit 2; }; exec python3 -I "$dir/design_check.py" fidelity "$@" ;;
esac
