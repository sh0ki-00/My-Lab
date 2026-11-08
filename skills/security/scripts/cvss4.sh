#!/usr/bin/env bash
# skills/security/scripts/cvss4.sh — CVSS 4.0 の基本の値の文字列から点数と重さを出す。報告に書いた点数と重さの食い違いを落とす。
#   表と計算の手順は FIRST の CVSS v4.0 仕様書と公式の計算機の値を写した（出典は cvss4.py の冒頭）。
# 使い方: cvss4.sh 'CVSS:4.0/AV:N/AC:L/AT:N/PR:L/UI:N/VC:H/VI:N/VA:N/SC:N/SI:N/SA:N'
#         cvss4.sh --report <報告.md>   /   cvss4.sh --selftest
# 判定の本体は cvss4.py（同じディレクトリ）。出力は FAIL の行と RESULT: PASS|FAIL。1 件でも FAIL なら終了コード 1。
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
dir="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
case "${1:-}" in
  "") echo "使い方: cvss4.sh <CVSS:4.0/…> | --report <報告.md> | --selftest"; exit 2 ;;
  *) exec python3 -I "$dir/cvss4.py" "$@" ;;
esac
