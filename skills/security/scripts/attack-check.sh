#!/usr/bin/env bash
# skills/security/scripts/attack-check.sh — 攻撃の台帳（attack-run が書いた JSON）の検査。
#   線 7 を機械で確かめる: 台帳の行は、決めた欄（手口・入口・利用者・状態・長さ・印・時間）だけを持ち、
#   本文や鍵のような秘密を残さない。found・new・old がそろう。
# 使い方: attack-check.sh <台帳.json>...   /   attack-check.sh --selftest
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
dir="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
case "${1:-}" in
  "") echo "使い方: attack-check.sh <台帳.json>... | --selftest"; exit 2 ;;
  *) exec python3 -I "$dir/attack_check.py" "$@" ;;
esac
