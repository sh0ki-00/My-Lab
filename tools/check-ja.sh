#!/usr/bin/env bash
# tools/check-ja.sh — tools/lib/check_ja.py（日本語の文体の検査）の薄い入口。使い方は python 側の冒頭にある。
dir="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
exec python3 -I "$dir/lib/check_ja.py" "$@"
