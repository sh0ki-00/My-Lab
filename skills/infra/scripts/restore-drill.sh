#!/usr/bin/env bash
# skills/infra/scripts/restore-drill.sh — バックアップから復元し、所要時間を実測する訓練（sqlite3、外の物に頼らない）。
#   架空の注文を N 行（既定 10 万行、種を固定）作り、オンラインで複製して目録（行数・中身の指紋・ファイルの指紋）を残す。
#   元を消したことにして複製から復元し、整合の検査・行数・中身の照合までの秒を測る。--rto を渡すと、超えたら FAIL。
# 使い方: restore-drill.sh [--rows N] [--seed S] [--rto 秒] [--json <記録>]   /   restore-drill.sh --selftest
# 本体は restore_drill.py（同じディレクトリ）。測るのは手元の手順の時間で、クラウドのデータベースの復元時間ではない。
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
dir="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
exec python3 -I "$dir/restore_drill.py" "$@"
