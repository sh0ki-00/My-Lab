#!/usr/bin/env bash
# skills/catchup/scripts/catchup-facts.sh — プロジェクトの事実を機械で拾い、AI に推測させない。プロジェクトのファイルは読むだけ。
#   拾うもの: 読んだ範囲、言語（拡張子の数）、ディレクトリ、言語の版とフレームワーク（設定ファイルの行）、起動とテストのコマンド、
#   試験のファイル、git の履歴（commit、この 1 年の commit と作者の数、開発の形）、画面と API のルート（注釈の中のルートも印を付ける）、
#   定時の処理、外とのつながり、設定の口（環境変数と .env のキーの名前）、DB（sqlite のファイル、マイグレーション、接続の設定の口）、
#   文書、書き方の決まり、UI の部品。.env の値と、commit の作者の名前とメールは出さない。
#   コマンドと cron の行は、KEY=値 の値、URL の利用者とパスワード、-u と -p の後ろ、Bearer の後ろを「（伏せた）」にしてから写す。
#   --out を渡すと、事実の記録（JSON Lines）に F-001 の形の続き番号とハッシュ値を付けて足す。地図の行は、この番号を根拠に引ける。
# 使い方: catchup-facts.sh --root <プロジェクトの直下> [--out tmp/catchup/facts.jsonl] [--exclude <読まない所>]... [--max-files 20000]
#         catchup-facts.sh --selftest
# 判定の本体は catchup_tools.py（同じディレクトリ）。出力は事実の表と RESULT: PASS|FAIL。FAIL なら終了コード 1。
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
dir="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
case "${1:-}" in
  "") echo "使い方: catchup-facts.sh --root <プロジェクトの直下> [--out tmp/catchup/facts.jsonl] [--exclude <読まない所>] | --selftest"; exit 2 ;;
  *) exec python3 -I "$dir/catchup_tools.py" facts "$@" ;;
esac
