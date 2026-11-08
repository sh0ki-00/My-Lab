#!/usr/bin/env bash
# skills/secretary/scripts/route.sh <依頼文> — 依頼文の振り分け。routing-rules.tsv の規則で、関わる役割・読むスキル・依頼の型・規模を返す。
# 使い方: route.sh <依頼文>   /   route.sh --selftest
# 判定の本体は secretary_check.py（同じディレクトリ）。出力は FAIL/WARN の行と RESULT: PASS|FAIL。1 件でも FAIL なら終了コード 1。
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
dir="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
case "${1:-}" in
  "") echo "使い方: route.sh <依頼文> | --selftest"; exit 2 ;;
  *) exec python3 -I "$dir/secretary_check.py" route "$@" ;;
esac
