#!/usr/bin/env bash
# skills/frontend/scripts/token-lint.sh <ディレクトリかファイル...> — トークン以外の生の値の検査。
#   部品の css と html（style の中）の生の色（16 進・rgb・hsl）、px（0 と 1px を除く）、書体名を FAIL にする。
#   名前に tokens を含むファイル（トークンの定義）と @media の行は対象外。許可リストは token-allow.txt。
# 使い方: token-lint.sh <ディレクトリ>   /   token-lint.sh --selftest
# 判定の本体は frontend_check.py（同じディレクトリ）。出力は FAIL/WARN の行と RESULT: PASS|FAIL。1 件でも FAIL なら終了コード 1。
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
dir="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
case "${1:-}" in
  "") echo "使い方: token-lint.sh <ディレクトリかファイル...> | --selftest"; exit 2 ;;
  *) exec python3 -I "$dir/frontend_check.py" tokens "$@" ;;
esac
