#!/usr/bin/env bash
# tools/check-refs.sh — tools/lib/check_refs.py（文書が指すパスの実在の検査）の薄い入口。使い方は python 側の冒頭にある。
dir="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
exec python3 -I "$dir/lib/check_refs.py" "$@"
