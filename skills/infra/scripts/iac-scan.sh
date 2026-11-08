#!/usr/bin/env bash
# skills/infra/scripts/iac-scan.sh <ディレクトリか .tf...> — Terraform の構成コードの静的検査（適用も init もしない）。
#   規則 IAC-001〜012: 外から読める保存先、公開のブロックの無いバケット、権限の「*」、管理の口の全開、暗号化の無い保存、
#   外から届くデータベース、削除の保護、バックアップの保持、監査ログの無効、版の管理の無いバケット、コードに書いた秘密、平文の通信。
#   変数は既定値と、ディレクトリの下の全 *.tfvars の値で見る（どれか 1 つの環境でも穴なら落とす）。
# 使い方: iac-scan.sh <ディレクトリか .tf...>   /   iac-scan.sh --rules   /   iac-scan.sh --selftest
# 判定の本体は infra_check.py（同じディレクトリ）。出力は FAIL の行（番号・重さ・直し方つき）と RESULT: PASS|FAIL。
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
dir="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
case "${1:-}" in
  "") echo "使い方: iac-scan.sh <ディレクトリか .tf...> | --rules | --selftest"; exit 2 ;;
  *) exec python3 -I "$dir/infra_check.py" iac "$@" ;;
esac
