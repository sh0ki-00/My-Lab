#!/usr/bin/env bash
# skills/catchup/scripts/map-check.sh — プロジェクトの地図（既定は tmp/catchup/）の検査。DB にはつながず、文書とファイルだけを見る。
#   入口の 1 枚（index.md）: 80 行以内（C-7）、冒頭の表の commit と作った日と DB の読み取りの許可、6 つの節と追記の候補への案内、
#       テンプレートの穴。基準の数字の表で「一致」と書いた行は、基準の値と数えた値が等しく、どちらも出どころの数と合う（C-5）。
#   節: 表題に節の名前、表の全部の行に根拠（ファイルと行、クエリの番号 Q-、事実の番号 F-、聞き取りの日付のどれか）。
#       根拠のファイルと行の実在（直下の外は落とす）、番号の記録の実在とハッシュ値。データの節は backend の data-dictionary-check.sh で見る。
#   追記の候補（inbox.md）: 日付、6 つの節のどれか、根拠、状態（未処理、反映済み、見送り）。未処理の数を INFO で出す。
#   鮮度（C-2）: stamp.json に記録した根拠のファイルのハッシュ値と今の中身を比べ、地図を作った commit のあとに変わった
#       ファイルを根拠に持つ節を「古い」と落とす。走査したファイルの一覧とも比べ、増えたか消えたファイルが当たる節
#       （コードは入口・データ・構成と動かし方、マイグレーションはデータ、設定は構成と動かし方・入口、文書は開発の形）も古いとする。
#       入口の 1 枚の表の根拠も同じく見る。節ごとに SECTION <節> 新しい|古い を出す。
#   --fresh は鮮度だけを見る（ふつうのセッションが、触る節が古いかを見るとき）。
#   --stamp は検査が通ったときだけ、今の commit と根拠のファイルのハッシュ値と走査したファイルの一覧を stamp.json に書く。
# 使い方: map-check.sh [<地図の置き場>] [--root <プロジェクトの直下>] [--fresh | --stamp]
#         map-check.sh --selftest
#   地図が <直下>/tmp/catchup にあれば --root は要らない。完成例は --root samples/messy-shop skills/catchup/examples/messy-shop。
# 判定の本体は catchup_tools.py（同じディレクトリ）。出力は SECTION・INFO・FAIL の行と RESULT: PASS|FAIL。FAIL なら終了コード 1。
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
dir="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
exec python3 -I "$dir/catchup_tools.py" check "$@"
