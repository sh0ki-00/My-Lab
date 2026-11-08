#!/usr/bin/env bash
# tools/check-doc.sh — tools/lib/check_doc.py（資料の型の検査）の薄い入口。使い方は python 側の冒頭にある。
dir="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
exec python3 -I "$dir/lib/check_doc.py" "$@"
