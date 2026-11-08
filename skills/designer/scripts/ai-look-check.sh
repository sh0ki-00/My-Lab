#!/usr/bin/env bash
# skills/designer/scripts/ai-look-check.sh <ディレクトリかファイル...> [--plan <計画書>] — AI の既定の見た目の検査。
#   css・html・js・tsx を走査し、既定の紫、紫グラデーション、絵文字、transition: all、明滅、跳ね返り、飾り番号、
#   均一な角丸と影、既定の書体、3 列カード、汎用 CTA を数え、帯（clean／mild／sloppy／terminal）で判定する。
#   --plan <計画書> を付けると、計画書の「既定との差」で理由を書いた項目を件数から外す。
# 使い方: ai-look-check.sh <ディレクトリ> [--plan <計画書>]   /   ai-look-check.sh --selftest
# 判定の本体は design_check.py（同じディレクトリ）。出力は FAIL/WARN の行と RESULT: PASS|FAIL。1 件でも FAIL なら終了コード 1。
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
dir="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
case "${1:-}" in
  "") echo "使い方: ai-look-check.sh <ディレクトリかファイル...> [--plan <計画書>] | --selftest"; exit 2 ;;
  *) exec python3 -I "$dir/design_check.py" ailook "$@" ;;
esac
