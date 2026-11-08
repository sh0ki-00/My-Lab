#!/usr/bin/env bash
# skills/secretary/scripts/intake-check.sh <ファイル> — 受付票の検査。欄の欠け、原文の写しの目的、判断の種類、規模と役割数、承認の状態、聞くことの数、雛形の穴。
# 使い方: intake-check.sh <ファイル>   /   intake-check.sh --selftest
# 判定の本体は secretary_check.py（同じディレクトリ）。出力は FAIL/WARN の行と RESULT: PASS|FAIL。1 件でも FAIL なら終了コード 1。
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
dir="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
case "${1:-}" in
  "") echo "使い方: intake-check.sh <ファイル> | --selftest"; exit 2 ;;
  *) exec python3 -I "$dir/secretary_check.py" intake "$@" ;;
esac
