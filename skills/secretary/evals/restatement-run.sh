#!/usr/bin/env bash
# skills/secretary/evals/restatement-run.sh — 言い直しの評価（仕様書 R-20261113-01 の C-01・C-02）。
# 使い方: restatement-run.sh prepare <出力先>   言い直しを書く側と判定 3 体に渡す packet を書く
#         restatement-run.sh [score]           outputs/<id>.md の機械の検査と、votes.tsv の多数決で一致を数える（18 件以上で PASS）
#         restatement-run.sh --selftest
# 判定の本体は restatements/restatement_eval.py。出力は FAIL/WARN の行と RESULT: PASS|FAIL restatement-run。1 件でも FAIL なら終了コード 1。
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
dir="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
case "${1:-}" in
  --selftest) exec python3 -I "$dir/restatements/restatement_eval.py" --selftest ;;
  prepare) exec python3 -I "$dir/restatements/restatement_eval.py" "$@" ;;
  ""|score) exec python3 -I "$dir/restatements/restatement_eval.py" score "${@:2}" ;;
  *) echo "使い方: restatement-run.sh prepare <出力先> | score | --selftest"; exit 2 ;;
esac
