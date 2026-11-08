#!/usr/bin/env bash
# skills/frontend/scripts/motion-lint.sh <ディレクトリかファイル...> — 動きの縮小版の検査。
#   transition か animation を数字の時間で書いたファイルに prefers-reduced-motion の分岐が無ければ FAIL。transition: all も FAIL。
#   時間をトークン（var(--duration-…)）で書いた指定は、トークン側の縮小版に任せて通す。許可リストは motion-allow.txt。
# 使い方: motion-lint.sh <ディレクトリ>   /   motion-lint.sh --selftest
# 判定の本体は frontend_check.py（同じディレクトリ）。出力は FAIL/WARN の行と RESULT: PASS|FAIL。1 件でも FAIL なら終了コード 1。
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
dir="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
case "${1:-}" in
  "") echo "使い方: motion-lint.sh <ディレクトリかファイル...> | --selftest"; exit 2 ;;
  *) exec python3 -I "$dir/frontend_check.py" motion "$@" ;;
esac
