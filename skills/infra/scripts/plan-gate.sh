#!/usr/bin/env bash
# skills/infra/scripts/plan-gate.sh <計画の JSON> [--attested <ダイジェストの一覧>] — 計画の差分の関所。CI が terraform show -json <計画> の出力を渡す。
#   決め方は「許す物の一覧」。承認 1 人の適用（ROUTE: apply、終了コード 0）で通すのは、一覧にある型の、一覧にある属性の変更だけ。
#     例: サービスの数、ロードバランサーの待ち先の設定、API の作業の定義のイメージのダイジェスト（来歴を確かめた物だけ）。
#     データベース（aws_db_instance）は一覧に無い。大きさの変更も守りの経路（rds:ModifyDBInstance は守りの適用だけが持つ）。
#     値の形も一覧で決める。サービスに付けてよい作業の定義は API の family の版だけ（移行や利用者づくりの版は守りの経路）。
#   一覧に無い型、一覧に無い属性、新しく作る資源、構成にある provisioner（local-exec など。適用の役割の資格で命令が動く）は、
#   守りの経路（ROUTE: guarded、終了コード 3）へ回す。
#     その計画は、承認 2 人の環境（<環境>-guarded）と守りの適用の役割でしか適用できない（AWS の側でも適用の役割には許していない）。
#   止める（RESULT: FAIL、終了コード 1）: 置き換えか削除、データを消す変更（保持を縮める、削除の保護を外す）、
#     一覧の外の部品（プロバイダ）、前提の検査（check ブロック）の不成立。
#   --attested: CI が来歴（どの commit をどの workflow が作ったか）を確かめたイメージのダイジェストを 1 行に 1 つ並べた file。
#   CI はこの検査の前に --selftest を回し、PASS でなければ止める。終了コードが 0 と 3 のほかなら、どちらの経路も通さない。
# 使い方: plan-gate.sh <計画の JSON> [--attested <file>]   /   plan-gate.sh --selftest
# 判定の本体は infra_check.py（同じディレクトリ）。
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
dir="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
case "${1:-}" in
  "") echo "使い方: plan-gate.sh <計画の JSON> [--attested <file>] | --selftest"; exit 2 ;;
  *) exec python3 -I "$dir/infra_check.py" plan "$@" ;;
esac
