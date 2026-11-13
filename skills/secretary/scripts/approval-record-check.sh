#!/usr/bin/env bash
# skills/secretary/scripts/approval-record-check.sh <ファイル> [--request <承認伺い>] — 承認記録の検査。承認の言葉が原文で承認の語、承認者は依頼者、範囲の形、承認で動くもの ⊆ 伺いの承認で始まること、状態。
# 使い方: approval-record-check.sh <ファイル> [--request <承認伺い>]   /   approval-record-check.sh --selftest
# 判定の本体は secretary_check.py（同じディレクトリ）。出力は FAIL/WARN の行と RESULT: PASS|FAIL。1 件でも FAIL なら終了コード 1。
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
dir="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
case "${1:-}" in
  "") echo "使い方: approval-record-check.sh <ファイル> [--request <承認伺い>] | --selftest"; exit 2 ;;
  *) exec python3 -I "$dir/secretary_check.py" record "$@" ;;
esac
