#!/usr/bin/env bash
# tools/check-skill.sh — tools/lib/check_skill.py（スキルの形式検査）の薄い入口。使い方は python 側の冒頭にある。
dir="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
exec python3 -I "$dir/lib/check_skill.py" "$@"
