#!/usr/bin/env bash
# skills/secretary/scripts/answer-check.sh <ファイル>... — 依頼者への返答（チャットに出す文）の検査。決まりは references/answer-style.md。
#   FAIL: 受付の定型句、前置きと締めの常套句、RESULT の行、受付番号・役割の数・「仮置き」の語、自作の言い換え語、1 行 1 文の縦並び、同じ文末の 4 連続、100 字超の文
#   WARN: 1 字の言い換えの疑い（印・輪・門）、語彙表（references/vocabulary.md）の語への括弧説明、括弧説明の密度、同じ文末の 3 連続、短い文の 3 連続、60 字超の文
# 使い方: answer-check.sh <ファイル>... [--vocab <語彙表.md>]   /   answer-check.sh --selftest
# 判定の本体は answer_check.py（同じディレクトリ）。出力は FAIL/WARN の行とファイルごとの RESULT: PASS|FAIL answer-check。1 件でも FAIL なら終了コード 1。
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
dir="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
case "${1:-}" in
  "") echo "使い方: answer-check.sh <ファイル>... [--vocab <語彙表.md>] | --selftest"; exit 2 ;;
  *) exec python3 -I "$dir/answer_check.py" "$@" ;;
esac
