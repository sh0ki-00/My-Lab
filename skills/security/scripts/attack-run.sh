#!/usr/bin/env bash
# skills/security/scripts/attack-run.sh — attack_run.py の薄い入口。
#   常設の RoE の範囲で、ローカルで起こしたアプリに、攻撃の表の手口だけを送る。使い方は attack_run.py の冒頭にある。
#   攻撃の相手は、ソースコードから手元で起こしたアプリだけ。クラウド・本番・第三者には 1 本も送らない。
# 使い方: attack-run.sh --target 127.0.0.1:<ポート> --probe <入口の一覧.json> --roe <常設の RoE.md> [--baseline <台帳.json>] [--ledger <出力.json>]
#         attack-run.sh --selftest
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
dir="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
case "${1:-}" in
  "") echo "使い方: attack-run.sh --target 127.0.0.1:<ポート> --probe <入口.json> --roe <RoE.md> [--baseline <台帳>] [--ledger <出力>] | --selftest"; exit 2 ;;
  *) exec python3 -I "$dir/attack_run.py" "$@" ;;
esac
