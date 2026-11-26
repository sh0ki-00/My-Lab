#!/usr/bin/env bash
# skills/security/scripts/roe-check.sh — RoE（交戦規則）に 範囲・許可・連絡先・期間・止める条件・やらないこと があるかを落とす。
#   範囲の対象ごとに所有の確認、許可に署名と日付、やらないことに本番と第三者。RoE が通らないうちは道具を向けない。
#   範囲の表の宛先は、手元（127.0.0.1・localhost・::1）だけを通す。所有の確認があっても、ほかの宛先と、手元と読めない宛先は落とす。
#   攻撃の相手は、ソースコードから手元で起こしたアプリだけ。クラウドの環境は、検証環境でも対象にしない。
# 使い方: roe-check.sh <RoE.md>...   /   roe-check.sh --selftest
# 判定の本体は security_check.py（同じディレクトリ）。出力は FAIL の行と RESULT: PASS|FAIL。1 件でも FAIL なら終了コード 1。
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
dir="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
case "${1:-}" in
  "") echo "使い方: roe-check.sh <RoE.md>... | --selftest"; exit 2 ;;
  *) exec python3 -I "$dir/security_check.py" roe "$@" ;;
esac
