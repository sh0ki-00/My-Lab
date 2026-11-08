#!/usr/bin/env bash
# skills/infra/scripts/migrate-gate.sh <移行の SQL...> — 移行の文を、許す文の一覧（足し算の DDL だけ）で確かめる。
#   PR の必須の検査と、移行のイメージを押し込む前に回す。一覧の外（行の読み書き、関数、トリガー、規則、権限、スキーマ、search_path、
#   psql の命令、関数の呼び出し、定数でない既定値）は落とし、別の承認 2 人の経路へ回す。DB の側でも roles.sql の事象のトリガーが強制する。
# 使い方: migrate-gate.sh migrations/*.sql   /   migrate-gate.sh --selftest
# 判定の本体は migrate_gate.py（同じディレクトリ）。出力は FAIL の行と RESULT: PASS|FAIL。1 件でも FAIL なら終了コード 1。
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
dir="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
case "${1:-}" in
  "") echo "使い方: migrate-gate.sh <移行の SQL...> | --selftest"; exit 2 ;;
  *) exec python3 -I "$dir/migrate_gate.py" "$@" ;;
esac
