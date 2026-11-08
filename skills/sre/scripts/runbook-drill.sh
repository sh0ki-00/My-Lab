#!/usr/bin/env bash
# skills/sre/scripts/runbook-drill.sh — Runbook の訓練。当番役が Runbook のコードだけで、架空の障害を復旧できるかを機械で確かめる。
#   Runbook の「原因の見分け方」の表の原因（C1〜C7）ごとに、使い捨ての写しと 127.0.0.1 の空いたポートで障害を起こし、
#   症状（probe が BAD）→「確かめる命令」の出力に表の印 →「直す命令」の原因の節 →「直ったことの確かめ」が終了コード 0 →
#   probe が GOOD、の順に見る。Runbook ごとに 1 件、表の外の障害（シードの中身の壊れを、pid の記録なしで手で立てた形）も起こし、
#   「どれにも合わないとき」の節のコードで直るかと、2 番手へ知らせる手があるかを見る。本番と samples/ の正本には注入しない。
#   Runbook ごとに別の起動の 1 件（出題役が道具の外の命令で立て、鍵は道具の読まない RUN/drill-<PORT>.out）も起こし、
#   表の最後の原因の節と道具の probe で直るかを見る。「直ったことの確かめ」が道具の命令（sample-api.sh probe・status・tally・pid）
#   の外を使う Runbook は、訓練せずに [確かめの道具] で落とす。
# 使い方: runbook-drill.sh <runbook.md>... [--keep] [--only table|outside|alt]   /   runbook-drill.sh --selftest
# 判定の本体は sre_drill.py（同じディレクトリ）。出力は MEASURE（復旧までの秒）と FAIL の行と RESULT: PASS|FAIL。
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:${PATH:-}"
dir="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
case "${1:-}" in
  "") echo "使い方: runbook-drill.sh <runbook.md>... [--keep] [--only table|outside|alt] | --selftest"; exit 2 ;;
  *) exec python3 -I "$dir/sre_drill.py" drill "$@" ;;
esac
