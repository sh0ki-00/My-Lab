#!/usr/bin/env bash
# skills/secretary/scripts/reply-check.sh <ファイル> — 役割の返答の検査。表題、3 節（要約・未解決の対立・承認が要る判断）、要約 10 行以内（表は 1 つ 8 行まで）、対立と判断は 5 件以内、種類は戻せる／戻せない、40 行以内、生のログ、雛形の穴。
# 使い方: reply-check.sh <ファイル>   /   reply-check.sh --selftest
# 判定の本体は secretary_check.py（同じディレクトリ）。出力は FAIL/WARN の行と RESULT: PASS|FAIL。1 件でも FAIL なら終了コード 1。
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
dir="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
case "${1:-}" in
  "") echo "使い方: reply-check.sh <ファイル> | --selftest"; exit 2 ;;
  *) exec python3 -I "$dir/secretary_check.py" reply "$@" ;;
esac
