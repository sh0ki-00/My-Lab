#!/usr/bin/env bash
# skills/secretary/scripts/minutes-check.sh <ファイル> — 会議録の検査。黙読した文書、役割の返答（要点 300 字以内）、対立点と裁定、未解決、承認が要る判断の種類、生のログ。
# 使い方: minutes-check.sh <ファイル>   /   minutes-check.sh --selftest
# 判定の本体は secretary_check.py（同じディレクトリ）。出力は FAIL/WARN の行と RESULT: PASS|FAIL。1 件でも FAIL なら終了コード 1。
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
dir="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
case "${1:-}" in
  "") echo "使い方: minutes-check.sh <ファイル> | --selftest"; exit 2 ;;
  *) exec python3 -I "$dir/secretary_check.py" minutes "$@" ;;
esac
