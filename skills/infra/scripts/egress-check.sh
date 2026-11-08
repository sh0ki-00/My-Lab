#!/usr/bin/env bash
# skills/infra/scripts/egress-check.sh <置き場...> — 自前のコード（画面と API）に、外へ移る処理と外へ送る処理が無いかを落とす。
#   CI の必須の検査が PR ごとに回す（samples/infra/ci/egress-check.yml）。web/ と API の置き場はセキュリティが持ち主で、これは 2 人目の目の前の機械の目。
#   画面: location への代入と assign・replace、window.open、sendBeacon、外の宛先（http:// か https:// か //）への fetch・XMLHttpRequest・EventSource・
#     WebSocket、画像と script の src と form の action への外の宛先。API: urllib.request、requests、httpx、http.client、aiohttp の取り込みと、socket で外へつなぐ呼び出し。
#   例外の書き方は置かない。要る宛先が出たら、検査そのものを守りの経路（セキュリティの承認）で変える。
# 使い方: egress-check.sh web/src api   /   egress-check.sh --selftest
# 判定の本体は egress_check.py（同じディレクトリ）。出力は FAIL の行と RESULT: PASS|FAIL。1 件でも FAIL なら終了コード 1。
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
dir="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
case "${1:-}" in
  "") echo "使い方: egress-check.sh <置き場...> | --selftest"; exit 2 ;;
  *) exec python3 -I "$dir/egress_check.py" "$@" ;;
esac
