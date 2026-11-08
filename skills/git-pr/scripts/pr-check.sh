#!/usr/bin/env bash
# skills/git-pr/scripts/pr-check.sh <PR 文.md> [--diff-lines <行数>] — PR 文の検査（仕様書 6.1 節と 6.5 節）。
#   題名が Conventional Commits の型（feat・fix・docs・refactor・perf・test・build・ci・chore）で 60 字以内。3 行の要約がある。
#   関連 Issue（Closes #番号）がある。数値が架空か実測かの 1 文がある。
#   必須の節（背景と目的、変えたこと、方針、影響、検証、レビューの観点、リリースと戻し方、用語）がある。
#   方針の表に却下した案がある。影響に利用者・既存のデータ・性能・セキュリティ・互換がある。検証の表の全行に結果があり、推測の語が無い。
#   戻し方と止める基準がある。雛形の <…> が残っていない。「AI が書いた範囲」の節が無い。
#   --diff-lines が 400 を超えると WARN（分割を促す）。
# 使い方: pr-check.sh <ファイル> [--diff-lines N]   /   pr-check.sh --selftest
# 出力: FAIL <ファイル>:<行> [<決まり>] <内容>、WARN …、最後に RESULT: PASS|FAIL pr-check。FAIL が 1 件でもあれば終了コード 1。
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"

check() {  # check <ファイル> <差分の行数（無ければ 0）>
  python3 -I - "$1" "$2" <<'PY'
import re
import sys

name = sys.argv[1]
diff_lines = int(sys.argv[2] or 0)
try:
    text = open(name, encoding="utf-8").read()
except OSError as e:
    print(f"FAIL {name} [読めない] {e}")
    print(f"RESULT: FAIL pr-check {name}")
    sys.exit(1)
raw_lines = text.split("\n")
issues = []
warns = []

def fail(no, rule, detail):
    issues.append((no, rule, detail))

lines = []
in_comment = False
in_code = False
for i, l in enumerate(raw_lines, 1):
    s = l.strip()
    if in_comment:
        if "-->" in s:
            in_comment = False
        continue
    if s.startswith("<!--"):
        if "-->" not in s[4:]:
            in_comment = True
        continue
    if s.startswith("```"):
        in_code = not in_code
        continue
    if in_code:
        continue
    lines.append((i, l))

title_no, title = next(((i, l[2:].strip()) for i, l in lines if l.startswith("# ")), (1, ""))
if not re.match(r"^(feat|fix|docs|refactor|perf|test|build|ci|chore)(\([^)]+\))?: \S", title):
    fail(title_no, "題名", "「<型>(<対象>): <何をするか>」の形にする。型は feat・fix・docs・refactor・perf・test・build・ci・chore")
if len(re.sub(r"\s", "", title)) > 60:
    fail(title_no, "題名", f"{len(re.sub(r'\s', '', title))} 字。60 字以内にする")

head = [l for i, l in lines if i <= 25]
quote = [l for l in head if l.startswith(">")]
content = [l for l in quote if re.search(r"[。！？]\s*$", l.strip("> *"))]
if len(content) != 3:
    fail(1, "要約", f"3 行の要約（引用ブロック）が {len(content)} 行")
if not any(re.search(r"(Closes|Fixes|Resolves)\s+#\d+", l) for l in head):
    fail(1, "関連 Issue", "「関連 Issue: Closes #番号」を冒頭に書く")
if not any(("架空" in l or "実測" in l) for l in head if not l.startswith("#")):
    fail(1, "数値の出どころ", "冒頭に、数値が架空か実測かを 1 文で書く")

def section(key):
    start = next((idx for idx, (i, l) in enumerate(lines) if l.startswith("## ") and key in l), None)
    if start is None:
        return None
    end = next((idx for idx in range(start + 1, len(lines)) if lines[idx][1].startswith("## ")), len(lines))
    return start, end

def body_of(sec):  # 見出しの行は含めない（見出しの語で判定が通らないように）
    return "\n".join(l for _, l in lines[sec[0] + 1:sec[1]])

for key in ("背景と目的", "変えたこと", "方針", "影響", "検証", "レビューの観点", "リリースと戻し方", "用語"):
    if section(key) is None:
        fail(0, "必須の節", f"「## {key}」が無い")

if any(l.startswith("## ") and "AI" in l and "範囲" in l for _, l in lines):
    fail(0, "禁止の節", "「AI が書いた範囲」の節は書かない（社長の指示）")

def table_rows(start, end):
    header = None
    rows = []
    for idx in range(start, end):
        i, l = lines[idx]
        s = l.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if header is None:
            header = cells
            continue
        if all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
            continue
        rows.append((i, cells))
    return header, rows

sec = section("方針")
if sec is not None and "却下" not in body_of(sec):
    fail(lines[sec[0]][0], "方針", "却下した案と理由を表に書く")

sec = section("影響")
if sec is not None:
    body = body_of(sec)
    for key in ("利用者", "既存のデータ", "性能", "セキュリティ", "互換"):
        if key not in body:
            fail(lines[sec[0]][0], "影響", f"観点「{key}」が無い")

sec = section("検証")
if sec is not None:
    header, rows = table_rows(*sec)
    if not header or not any("結果" in h for h in header):
        fail(lines[sec[0]][0], "検証", "表に「結果」の列が要る")
    elif not rows:
        fail(lines[sec[0]][0], "検証", "確かめたことの行が無い")
    else:
        ri = next(k for k, h in enumerate(header) if "結果" in h)
        for i, cells in rows:
            if len(cells) <= ri or not cells[ri]:
                fail(i, "検証", "結果が空。実行して出た値を書く")
    for i, l in lines[sec[0]:sec[1]]:
        for w in ("動くはず", "通るはず", "と思われ", "おそらく", "はずです", "はずである"):
            if w in l:
                fail(i, "検証", f"「{w}」。実行した事実だけを書く")

sec = section("リリースと戻し方")
if sec is not None:
    body = body_of(sec)
    for key in ("戻し方", "止める基準"):
        if key not in body:
            fail(lines[sec[0]][0], "戻し方", f"「{key}」が無い")

for i, l in lines:
    if re.search(r"<[^>]*>", l) and not re.search(r"<br\s*/?>", l):
        fail(i, "雛形の穴", "<…> が残っている")

if diff_lines > 400:
    warns.append((0, "大きさ", f"差分が {diff_lines} 行。400 行を超えるので、目的ごとに分ける案を冒頭に書く"))

for no, rule, detail in issues:
    where = f"{name}:{no}" if no else name
    print(f"FAIL {where} [{rule}] {detail}")
for no, rule, detail in warns:
    print(f"WARN {name} [{rule}] {detail}")
verdict = "PASS" if not issues else "FAIL"
print(f"RESULT: {verdict} pr-check {name} ({len(issues)} 件、WARN {len(warns)} 件)")
sys.exit(0 if not issues else 1)
PY
}

selftest() {
  local t rc=0 here good
  here="$(cd "$(dirname "$0")" && pwd -P)"
  good="$here/../examples/pr-example.md"
  t="$(mktemp -d)"
  check "$good" 0 >/dev/null || { echo "FAIL selftest: 完成例が落ちた"; rc=1; }
  check "$good" 450 | grep -q '^WARN' || { echo "FAIL selftest: 400 行超の WARN が出ない"; rc=1; }
  sed -e '1s/.*/# 注文一覧を速くする/' "$good" > "$t/title.md"
  check "$t/title.md" 0 | grep -q '\[題名\]' || { echo "FAIL selftest: 型の無い題名が通った"; rc=1; }
  sed -e 's/| 却下 |/| 保留 |/' "$good" > "$t/norej.md"
  check "$t/norej.md" 0 | grep -q '\[方針\]' || { echo "FAIL selftest: 却下の無い方針が通った"; rc=1; }
  sed -e 's/^実行して確かめた結果だけを書きます。/本番でも動くはずです。/' "$good" > "$t/guess.md"
  check "$t/guess.md" 0 | grep -q '\[検証\]' || { echo "FAIL selftest: 推測の語が通った"; rc=1; }
  sed -e 's/^関連 Issue: Closes #128。/関連 Issue: 無し。/' "$good" > "$t/noissue.md"
  check "$t/noissue.md" 0 | grep -q '\[関連 Issue\]' || { echo "FAIL selftest: 関連 Issue の欠けが通った"; rc=1; }
  grep -v '^| 戻し方 |' "$good" > "$t/norollback.md"
  check "$t/norollback.md" 0 | grep -q '\[戻し方\]' || { echo "FAIL selftest: 戻し方の欠けが通った"; rc=1; }
  rm -rf "$t"
  if [ "$rc" -eq 0 ]; then echo "RESULT: PASS pr-check --selftest (7 例)"; else echo "RESULT: FAIL pr-check --selftest"; fi
  return $rc
}

case "${1:-}" in
  --selftest) selftest ;;
  "") echo "使い方: pr-check.sh <PR 文.md> [--diff-lines N] | --selftest"; exit 2 ;;
  *)
    file="$1"; shift
    n=0
    while [ $# -gt 0 ]; do
      case "$1" in
        --diff-lines) n="${2:-0}"; shift 2 ;;
        *) echo "使い方: pr-check.sh <PR 文.md> [--diff-lines N]"; exit 2 ;;
      esac
    done
    check "$file" "$n"
    ;;
esac
