#!/usr/bin/env bash
# skills/infra/scripts/deps-diff.sh <main の lock> <PR の lock> [--github] — 部品の一覧（SBOM）の差分。CI の必須の検査が PR ごとに回す。
#   新しい部品、版の変更、消えた部品は知らせる（終了コード 3。PR の注記と job の要約に出し、lock の file の持ち主のセキュリティが読む）。
#   止める（終了コード 1）: 登録所の外の取り込み元、指紋（integrity）の無い部品、版を変えない指紋の変更、新しい入れ時の命令。
#   画面の部品はブラウザで動くので、画面の移動による持ち出しはブラウザでは止められない。部品が入る所で、機械の差分と 2 人目の目を通す。
# 使い方: deps-diff.sh <main の package-lock.json> <PR の package-lock.json> [--github]   /   deps-diff.sh --selftest
# 判定の本体は deps_diff.py（同じディレクトリ）。
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
dir="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
case "${1:-}" in
  "") echo "使い方: deps-diff.sh <main の lock> <PR の lock> [--github] | --selftest"; exit 2 ;;
  *) exec python3 -I "$dir/deps_diff.py" "$@" ;;
esac
