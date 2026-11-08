#!/usr/bin/env bash
# skills/secretary/scripts/gate-check.sh <ファイル> — 社長向け文書の門。言い訳の語、要件の交渉、判定の転記、推測の語、検証の記録、出す前の表の未充足、承認伺いの順番と長さ。
# 使い方: gate-check.sh <ファイル>   /   gate-check.sh --selftest
# 判定の本体は secretary_check.py（同じディレクトリ）。出力は FAIL/WARN の行と RESULT: PASS|FAIL。1 件でも FAIL なら終了コード 1。
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
dir="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
case "${1:-}" in
  "") echo "使い方: gate-check.sh <ファイル> | --selftest"; exit 2 ;;
  *) exec python3 -I "$dir/secretary_check.py" gate "$@" ;;
esac
