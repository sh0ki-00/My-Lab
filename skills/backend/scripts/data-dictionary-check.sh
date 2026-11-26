#!/usr/bin/env bash
# skills/backend/scripts/data-dictionary-check.sh — データの辞書・調査の文書・クエリの記録の検査。DB にはつながず、文書とファイルだけを見る。
#   辞書: 鮮度の 4 欄（commit は 7〜40 字の 16 進。git の無いプロジェクトでは「git なし」と作った時刻と根拠のハッシュ値で、
#         直下が git の作業ツリーでなく、根拠のファイルから作り直したハッシュ値と合うときだけ通す）、
#         6 つの記録の表、辞書の網羅（スキーマの写しの全テーブルを、辞書と書き込む処理の表に）、表の行ごとの根拠、
#         根拠の実在（ファイルと行は直下の中、クエリの番号）、値の一覧（20 種類以下の列は記録の結果と一致）、裏づけ、
#         基準の数字（行が 1 つ以上、「一致」は値が等しく出どころがある、一致か差の理由がある。C-5）、ハッシュ値、行のコピー、
#         テンプレートの穴。
#   調査の文書（結論の節を持つ .md）: 結論の数字が、挙げたクエリの結果か計算の行にあるか（日付と番号は数えない。結論では
#         バッククォートの中と単位の付いた数も照らし、割合は割合の列か計算とだけ比べ、漢数字は落とす）、数の列と計算の行の検算、
#         条件の値（辞書の値の一覧にある値だけで絞る。lower() で包んだ列と "…" も照らす）、裏づけ（実測か推定か）、検算の行。
#   クエリの記録（.jsonl）: 読み取りだけ（許す文の一覧と、読み取り専用の開き方）、ハッシュ値、環境の名前、番号の重なり、
#         個人が分かる値（形と、集計の外で出した個人情報らしい列）。
# 使い方: data-dictionary-check.sh <辞書.md> [<調査の文書.md>...] [<記録.jsonl>...] [--log <記録>] [--schema <写し>] [--dict <辞書>] [--root <直下>]
#         data-dictionary-check.sh --evidence-hash <辞書.md> --root <直下>   （git の無いプロジェクトの commit の欄の値を VALUE の行で出す）
#         data-dictionary-check.sh --selftest
# 判定の本体は data_tools.py（同じディレクトリ）。出力は FAIL の行と RESULT: PASS|FAIL。1 件でも FAIL なら終了コード 1。
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
dir="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
case "${1:-}" in
  "") echo "使い方: data-dictionary-check.sh <辞書.md> [<調査の文書.md>...] [<記録.jsonl>...] | --selftest"; exit 2 ;;
  *) exec python3 -I "$dir/data_tools.py" check "$@" ;;
esac
