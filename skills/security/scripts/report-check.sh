#!/usr/bin/env bash
# skills/security/scripts/report-check.sh — 侵入テストの報告の発見ごとに 5 点（何ができてしまうか・再現の手順・直し方・再検証・重さと採点の根拠）があるかを落とす。
#   再現と再検証は命令の囲みで、宛先は手元（127.0.0.1）だけ、攻撃のコードを書かない。--matrix で検知の行列も見る。
#   --roe <RoE> で、再現・再検証の宛先と名を挙げた試験と立てる写しを、RoE の範囲の表（宛先と写しの置き場）に突き合わせる。
# 使い方: report-check.sh [--roe <RoE.md>] <報告.md>...   /   report-check.sh --matrix <行列.md>...   /   report-check.sh --selftest（報告と行列の両方）
# 判定の本体は security_check.py（同じディレクトリ）。出力は FAIL の行と RESULT: PASS|FAIL。1 件でも FAIL なら終了コード 1。
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
dir="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
case "${1:-}" in
  "") echo "使い方: report-check.sh [--roe <RoE.md>] <報告.md>... | --matrix <行列.md>... | --selftest"; exit 2 ;;
  --selftest)
    python3 -I "$dir/security_check.py" report --selftest; a=$?
    python3 -I "$dir/security_check.py" matrix --selftest; b=$?
    # 最後の行は、ファイルの名で報告と行列の両方をまとめて名乗る
    if [ "$a" -eq 0 ] && [ "$b" -eq 0 ]; then echo "RESULT: PASS report-check --selftest（報告と行列）"; exit 0; fi
    echo "RESULT: FAIL report-check --selftest（報告と行列）"; exit 1 ;;
  --matrix) shift; exec python3 -I "$dir/security_check.py" matrix "$@" ;;
  *) exec python3 -I "$dir/security_check.py" report "$@" ;;
esac
