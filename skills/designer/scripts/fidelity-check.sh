#!/usr/bin/env bash
# skills/designer/scripts/fidelity-check.sh <計画書> <tokens.css> [<実装の css/html...>] — 忠実度の検査。
#   計画書の色が tokens.css にあり、tokens.css の色が計画書にあり、--duration が計画の動きの表と合い、
#   実装の css に計画に無い生の色や ms が無いことを確かめる。
# 使い方: fidelity-check.sh <計画書> <tokens.css> [<実装...>]   /   fidelity-check.sh --selftest
# 判定の本体は design_check.py（同じディレクトリ）。出力は FAIL/WARN の行と RESULT: PASS|FAIL。1 件でも FAIL なら終了コード 1。
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
dir="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
case "${1:-}" in
  "") echo "使い方: fidelity-check.sh <計画書> <tokens.css> [<実装の css/html...>] | --selftest"; exit 2 ;;
  --selftest) exec python3 -I "$dir/design_check.py" fidelity --selftest ;;
  *) [ $# -ge 2 ] || { echo "使い方: fidelity-check.sh <計画書> <tokens.css> [<実装...>]"; exit 2; }; exec python3 -I "$dir/design_check.py" fidelity "$@" ;;
esac
