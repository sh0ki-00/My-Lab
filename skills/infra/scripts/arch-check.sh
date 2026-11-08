#!/usr/bin/env bash
# skills/infra/scripts/arch-check.sh <インフラ構成設計書> — 設計書の欠けの検査。
#   6 本の柱ごとの決めと測り方、ネットワークの 3 層と図、最小権限の IAM（「*」なし）、秘密情報の置き場と回転、暗号化、
#   消せない監査ログと保持の期間、バックアップと復元（RPO・RTO・restore-drill で測った秒）、環境の差、費用の幅（最小・最大・前提、合計の和）、
#   流出経路図と 6 つの出口の表（守りと確認方法）、攻撃者の目（私ならここから入る、への答え）、雛形の穴、推測の語。
# 使い方: arch-check.sh <設計書>   /   arch-check.sh --selftest
# 判定の本体は infra_check.py（同じディレクトリ）。出力は FAIL/WARN の行と RESULT: PASS|FAIL。1 件でも FAIL なら終了コード 1。
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
dir="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
case "${1:-}" in
  "") echo "使い方: arch-check.sh <設計書> | --selftest"; exit 2 ;;
  *) exec python3 -I "$dir/infra_check.py" arch "$@" ;;
esac
