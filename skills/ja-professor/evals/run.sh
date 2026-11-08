#!/usr/bin/env bash
# skills/ja-professor/evals/run.sh — ja-professor の試験ケース。機械で判定できる分だけを回す。
#   1) 完成例 3 本（N+1、索引、hooks）が explain-check を PASS。短答の完成例が --profile short で PASS。
#   2) fixtures/bad-ai-answer.txt（理解できない回答）が 4 件以上の FAIL。
#   3) templates/explanation.md（穴埋めのまま）が FAIL。
#   4) 読み手の記録に「N+1」を知っていると書くと、N+1 の説明の有無を問われなくなる（--reader）。
#   5) reader-profile-update.sh が 2 語を足し、重複を足さない。
#   判定者パネルと言い直しテストは人（別コンテキスト）が行い、evals/panel/ に記録を残す。
# 出力: ケースごとの行と、最後に RESULT: PASS|FAIL evals ja-professor (<合格>/<全部>)。
set -u
HERE="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
SKILL="$(cd "$HERE/.." && pwd -P)"
CHECK="$SKILL/scripts/explain-check.sh"
pass=0; total=0
judge() {  # judge <名前> <0 なら合格> <内容>
  total=$((total + 1))
  if [ "$2" -eq 0 ]; then pass=$((pass + 1)); printf 'PASS evals ja-professor %s\n' "$1"; else printf 'FAIL evals ja-professor %s（%s）\n' "$1" "$3"; fi
}
for ex in example-n-plus-one example-index example-hooks; do
  out="$(bash "$CHECK" "$SKILL/examples/$ex.md" 2>&1)"
  if printf '%s\n' "$out" | grep -q '^RESULT: PASS'; then judge "$ex.md は PASS" 0 ""; else judge "$ex.md は PASS" 1 "$(printf '%s\n' "$out" | grep '^FAIL' | head -2 | tr '\n' ' ')"; fi
done
out="$(bash "$CHECK" "$SKILL/examples/example-short-answer.md" --profile short 2>&1)"
if printf '%s\n' "$out" | grep -q '^RESULT: PASS'; then judge "example-short-answer.md は short で PASS" 0 ""; else judge "example-short-answer.md は short で PASS" 1 "$(printf '%s\n' "$out" | grep '^FAIL' | head -2 | tr '\n' ' ')"; fi
n="$(bash "$CHECK" "$HERE/fixtures/bad-ai-answer.txt" 2>&1 | grep -c '^FAIL')"
if [ "$n" -ge 4 ]; then judge "bad-ai-answer.txt は FAIL $n 件（4 件以上）" 0 ""; else judge "bad-ai-answer.txt は FAIL 4 件以上" 1 "$n 件"; fi
if bash "$CHECK" "$SKILL/templates/explanation.md" >/dev/null 2>&1; then judge "穴埋めのままの雛形は FAIL" 1 "通った"; else judge "穴埋めのままの雛形は FAIL" 0 ""; fi
T="$(mktemp -d)"
printf '# 読み手の記録\n\n## 知っている語\n\n| 語 | 日 | 出 |\n|---|---|---|\n| N+1 | 2026-11-06 | 前回 |\n| ORM | 2026-11-06 | 前回 |\n\n## つまずいた語\n\n| 語 | 日 | 出 |\n|---|---|---|\n' > "$T/reader.md"
printf '# 題\n\n## 解説\n\n社長\n\nご質問は 1 点ですね。(1) N+1 は直ったか、です。\n\n### 答え\n\nはい、直りました。問い合わせは 101 回から 3 回になりました。\n\n### 仕組み\n\nまとめ読みにしたので、件数が増えても回数は増えません。索引を足しても回数は減りません。\n\n### 例\n\n例えば 500 件でも 3 回です（架空）。\n\n### 確認の問い\n\n一番分かりにくかった所はどこでしょうか。進めてよければ一言ください。\n' > "$T/known.md"
out_without="$(bash "$CHECK" "$T/known.md" 2>&1)"
out_with="$(bash "$CHECK" "$T/known.md" --reader "$T/reader.md" 2>&1)"
if printf '%s\n' "$out_without" | grep -q '「N+1」に括弧の説明が無い' && ! printf '%s\n' "$out_with" | grep -q '「N+1」'; then judge "読み手の記録で N+1 の説明を省ける" 0 ""; else judge "読み手の記録で N+1 の説明を省ける" 1 "記録なし: $(printf '%s\n' "$out_without" | grep -c '^FAIL') FAIL、記録あり: $(printf '%s\n' "$out_with" | grep -c '^FAIL') FAIL"; fi
out="$(bash "$SKILL/scripts/reader-profile-update.sh" --file "$T/profile.md" --known ORM --stuck 索引 2>&1)"
if printf '%s\n' "$out" | grep -q '足した 2 語' && bash "$SKILL/scripts/reader-profile-update.sh" --file "$T/profile.md" --known ORM 2>&1 | grep -q '足した 0 語'; then judge "reader-profile-update が 2 語を足し、重複を足さない" 0 ""; else judge "reader-profile-update が 2 語を足し、重複を足さない" 1 "$out"; fi
rm -rf "$T"
if [ "$pass" -eq "$total" ] && [ "$total" -gt 0 ]; then echo "RESULT: PASS evals ja-professor ($pass/$total)"; exit 0; fi
echo "RESULT: FAIL evals ja-professor ($pass/$total)"; exit 1
