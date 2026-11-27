#!/usr/bin/env bash
# skills/designer/scripts/fib-check.sh <tokens.css> [--plan <計画書>] — 寸法と時間がフィボナッチの数列に入っているかの検査。
#   トークン（--名前: 値）の中の px・ms・秒の値が、0、1、2、3、5、8、13、21、34、55、89、144、233、377、610、987 … のどれかかを見る。
#   影の px も、小数（0.5s）も見る。色・割合・曲線の数は見ない。標準の下限は、数列の次の段へ切り上げた値を使う（12px は 13px、44px は 55px）。
#   --plan の計画書が既存に合わせる型なら、既存の値は見ず、計画書の「足す値」の表の値だけを見る。
#   数列の前の版の完成例（examples と evals/fixtures の決まった名前）は WARN を出して見ない。次の PR で数列に直す（承認記録 A-24）。
#   決まりは skills/designer/references/systems.md の 7 節（依頼者の決め、2026-11-27）。
# 使い方: fib-check.sh <tokens.css> [--plan <計画書>]   /   fib-check.sh --selftest
# 判定の本体は design_check.py（同じディレクトリ）。出力は FAIL/WARN の行と RESULT: PASS|FAIL。1 件でも FAIL なら終了コード 1。
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
dir="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
case "${1:-}" in
  "") echo "使い方: fib-check.sh <tokens.css> [--plan <計画書>] | --selftest"; exit 2 ;;
  *) exec python3 -I "$dir/design_check.py" fib "$@" ;;
esac
