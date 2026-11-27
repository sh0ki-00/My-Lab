#!/usr/bin/env bash
# skills/designer/scripts/ai-look-check.sh <ディレクトリかファイル...> [--plan <計画書>] — AI の既定の見た目の検査。
#   css・html・js・tsx を走査し、既定の紫、紫グラデーション、絵文字、transition: all、明滅、跳ね返り、飾り番号、
#   均一な角丸と影、既定の書体、3 列カード、汎用 CTA、同じ動き（同じ animation が 6 か所以上）、
#   透明度だけのホバー（:hover の中身が opacity だけ、が 3 か所以上）を数え、帯（clean／mild／sloppy／terminal）で判定する。
#   没入の型の既定（ネオンの光、粒子の部品、一律の浮き上がり。ガラスの板は「ぼかし」）も数える。
#   --plan <計画書> を付けると、計画書の「既定との差」で理由を書いた項目を件数から外す。
#   没入の型の計画書では、世界観の設定のうち役目を書く行（主題・物語・感情・素材と光・奥行の層・動きの語彙・参照）だけを理由と見る。
#   「取らない方向」と「取る危険」に名指しした既定は、件数から外さない。
# 使い方: ai-look-check.sh <ディレクトリ> [--plan <計画書>]   /   ai-look-check.sh --selftest
# 判定の本体は design_check.py（同じディレクトリ）。出力は FAIL/WARN の行と RESULT: PASS|FAIL。1 件でも FAIL なら終了コード 1。
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
dir="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
case "${1:-}" in
  "") echo "使い方: ai-look-check.sh <ディレクトリかファイル...> [--plan <計画書>] | --selftest"; exit 2 ;;
  *) exec python3 -I "$dir/design_check.py" ailook "$@" ;;
esac
