#!/usr/bin/env bash
# skills/sre/scripts/sample-api.sh — 手元の見本の API（samples/api の写し）を、当番が Runbook の命令で扱う道具。
#   copy            正本（SRC）から写し（API_DIR）へ、見本の 4 つの file を写す
#   start [--orders N]  写しの server.py を 127.0.0.1:PORT で裏に立てる。鍵は KEYS（既定 RUN/keys.txt、権限 600）、ログは RUN/api.log。
#                   動いている API に道具の鍵で入れれば何もしない。入れなければ（道具の外で立てた API）、道具で立て直して
#                   鍵を作り直す（REKEY）。立てたら RUN/keys.* の古い鍵の file を消し、鍵の置き場を KEYS の 1 つにする
#   stop            立てた API を止め、鍵の file を消す。pid の記録が無くても、PORT で待ち受ける写しの server.py を止める
#   status          プロセスの状態、起動の設定と決めた値の差、ポートの持ち主、写しと正本の差、シードの中身の照合（SEED ok|bad）、
#                   鍵の置き場、ログの最後の誤り。読むだけで何も変えない
#   pid             写しの API の pid を 1 行で出す（RUN/api.pid か、PORT の待ち受けから）
#   rebuild         正本の 4 つの file と決めた設定で写しを作り直して立てる。違う file と直す前の status は RUN/broken/<時刻>/ へ
#   probe [--count N] [--threshold-ms 50]  利用者と同じ道で一覧を呼ぶ。全部が 200 で、閾値を超えた遅さが 1 割以下なら GOOD（終了コード 0）
#   tally [--last N]  要約のログの最後の N 行を、状態番号・コード・例外・断りの理由・利用者・時間で数える
# 環境の変数: API_DIR（既定 tmp/flow/stage5/api）、RUN（既定 tmp/flow/stage5/run）、PORT（既定 8080）、SRC（既定 samples/api）、
#   KEYS（既定 RUN/keys.txt。無ければ RUN/keys.* を探す）。
# 写しが samples/ の中なら断る。使い方: sample-api.sh <命令> [引数]   /   sample-api.sh --selftest
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:${PATH:-}"
dir="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
case "${1:-}" in
  "") echo "使い方: sample-api.sh copy|start|stop|status|pid|rebuild|probe|tally [引数] | --selftest"; exit 2 ;;
  *) exec python3 -I "$dir/sre_drill.py" api "$@" ;;
esac
