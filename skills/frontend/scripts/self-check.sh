#!/usr/bin/env bash
# skills/frontend/scripts/self-check.sh <自己点検票> — 自己点検票の検査。
#   結果に数字か PASS があるか、判定が 充足／未確認 か、frontend-gate.sh の出力が貼ってあるか、未確認の節があるか、推測の語が無いか。
# 使い方: self-check.sh <自己点検票>   /   self-check.sh --selftest
# 判定の本体は frontend_check.py（同じディレクトリ）。出力は FAIL/WARN の行と RESULT: PASS|FAIL。1 件でも FAIL なら終了コード 1。
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
dir="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
case "${1:-}" in
  "") echo "使い方: self-check.sh <自己点検票> | --selftest"; exit 2 ;;
  *) exec python3 -I "$dir/frontend_check.py" self "$@" ;;
esac
