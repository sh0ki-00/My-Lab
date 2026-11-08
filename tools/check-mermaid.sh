#!/usr/bin/env bash
# tools/check-mermaid.sh — tools/lib/check_mermaid.py（Mermaid の図の静的な検査）の薄い入口。使い方は python 側の冒頭にある。
dir="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
exec python3 -I "$dir/lib/check_mermaid.py" "$@"
