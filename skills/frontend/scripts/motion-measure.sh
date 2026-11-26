#!/usr/bin/env bash
# skills/frontend/scripts/motion-measure.sh — 没入の型の演出を、画面なしのブラウザで 12 項目測って判定する（本体は motion-measure.mjs）。
#   対象のページは window.__scene（ledger、play()、seek(ms)、skip()、reset()。任意で ready）を持つ約束にする（references/immersive.md の 6 節）。
#   CPU を等速と 4 倍遅くの 2 条件で 3 回ずつ回し、項目ごとに悪い側を採る。外のネットワークには出ない（対象は 127.0.0.1 などだけ。
#   HTTP と WebSocket の外への要求は止めて数え、Service Worker も止める）。
#   測った値は記録の JSON（既定は tmp/.verify/motion-measure-<演出の ID>.json）に残し、判定は記録だけから出す。
# 使い方: motion-measure.sh --config <設定.json> [--default-dir <置き場>] [--runs <回数>] [--record <記録.json>]
#         motion-measure.sh --dir <置き場> --scene <演出の ID> [--path /]   /   motion-measure.sh --url <URL> --scene <演出の ID>
#         motion-measure.sh <上の対象の指定> --frames <置き場>   （監修のフレームを PNG で撮り、一覧を frames.json に書く）
#         motion-measure.sh --judge <記録.json>   （ブラウザを使わず、記録を判定し直す。架空の記録は FAIL。試験だけ --allow-fictional）
#         motion-measure.sh --selftest            （記録の正例と負例で判定を試す。ブラウザもサーバーも使わない）
# 出力: 項目ごとの RESULT: PASS|FAIL motion-measure <番号> <名前>: … の 12 行（落ちた項目は前に FAIL の行）、描画の方式、記録の置き場、
#       最後に全体の RESULT 行。1 項目でも FAIL なら終了コード 1、設定の誤りは 2。
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
dir="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
if ! command -v node >/dev/null 2>&1; then
  echo "FAIL motion-measure [道具が無い] node が入っていない（SKIP は FAIL と同じ）"
  echo "RESULT: FAIL motion-measure 道具"
  exit 1
fi
case "${1:-}" in
  "") echo "使い方: motion-measure.sh --config <設定.json> | --dir <置き場> --scene <ID> | --url <URL> --scene <ID> [--frames <置き場>] | --judge <記録.json> | --selftest"; exit 2 ;;
  *) exec node "$dir/motion-measure.mjs" "$@" ;;
esac
