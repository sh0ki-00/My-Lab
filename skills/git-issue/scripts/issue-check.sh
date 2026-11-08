#!/usr/bin/env bash
# skills/git-issue/scripts/issue-check.sh <Issue 文.md> — Issue 文の検査（仕様書 6.1 節と 6.4 節）。
#   題名が 60 字以内で、直し方（直す・修正）ではなく症状を書いている。3 行の要約がある。数値が架空か実測かの 1 文がある。
#   必須の節（背景と目的、起きていること、完了の条件、やらないこと、手がかり、用語、未確定）がある。
#   完了の条件の表に「確認方法」の列があり、全行が空でなく、雛形の <…> が残っていない。優先度の語が無い。
#   不具合（題名に「不具合」か、起きていることに番号つきの手順）なら、再現手順・期待する結果・実際の結果・再現の頻度・環境が揃う。
# 使い方: issue-check.sh <ファイル>   /   issue-check.sh --selftest
# 出力: FAIL <ファイル>:<行> [<決まり>] <内容> と、最後に RESULT: PASS|FAIL issue-check。1 件でも FAIL なら終了コード 1。
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"

check() {
  python3 -I - "$1" <<'PY'
import re
import sys

name = sys.argv[1]
try:
    text = open(name, encoding="utf-8").read()
except OSError as e:
    print(f"FAIL {name} [読めない] {e}")
    print(f"RESULT: FAIL issue-check {name}")
    sys.exit(1)
raw_lines = text.split("\n")
issues = []

def fail(no, rule, detail):
    issues.append((no, rule, detail))

# 注釈（<!-- -->）とコードブロックを外した行の列。行番号は元のまま
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
if not title:
    fail(1, "題名", "「# 題名」が無い")
else:
    if len(re.sub(r"\s", "", title)) > 60:
        fail(title_no, "題名", f"{len(re.sub(r'\s', '', title))} 字。60 字以内にする")
    if re.search(r"(を直す|直す|を修正する|修正する|修正|改修する|fix|Fix)\s*$", title):
        fail(title_no, "題名", "直し方ではなく、起きている症状を書く")

head = [l for i, l in lines if i <= 25]
quote = [l for l in head if l.startswith(">")]
content = [l for l in quote if re.search(r"[。！？]\s*$", l.strip("> *"))]
if len(content) != 3:
    fail(1, "要約", f"3 行の要約（引用ブロック）が {len(content)} 行")
if not any(("架空" in l or "実測" in l) for l in head if not l.startswith("#")):
    fail(1, "数値の出どころ", "冒頭に、数値が架空か実測かを 1 文で書く")

def section(key):
    start = next((idx for idx, (i, l) in enumerate(lines) if l.startswith("## ") and key in l), None)
    if start is None:
        return None
    end = next((idx for idx in range(start + 1, len(lines)) if lines[idx][1].startswith("## ")), len(lines))
    return start, end

for key in ("背景と目的", "起きていること", "完了の条件", "やらないこと", "手がかり", "用語", "未確定"):
    if section(key) is None:
        fail(0, "必須の節", f"「## {key}」が無い")

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

sec = section("完了の条件")
if sec is not None:
    header, rows = table_rows(*sec)
    if not header or not any("確認" in h for h in header):
        fail(lines[sec[0]][0], "完了の条件", "表に「確認方法」の列が要る")
    elif not rows:
        fail(lines[sec[0]][0], "完了の条件", "条件の行が無い")
    else:
        ci = next(k for k, h in enumerate(header) if "確認" in h)
        for i, cells in rows:
            if len(cells) <= ci or not cells[ci]:
                fail(i, "完了の条件", "確認方法が空。誰が何をすれば判定できるかを書く")

for i, l in lines:
    if l.startswith("#"):
        continue
    m = re.search(r"優先度|優先順位|高優先|最優先|緊急度|\bP[0-3]\b", l)
    if m:
        fail(i, "優先度", f"「{m.group(0)}」を書かない。優先は社長が決める")
    if re.search(r"<[^>]*>", l) and not re.search(r"<br\s*/?>", l):
        fail(i, "雛形の穴", "<…> が残っている")

sec = section("起きていること")
is_bug = "不具合" in title or (sec is not None and any(re.match(r"^\s*\d+\.", l) for _, l in lines[sec[0]:sec[1]]))
if is_bug and sec is not None:
    body = lines[sec[0]:sec[1]]
    if not any(re.match(r"^\s*\d+\.", l) for _, l in body):
        fail(lines[sec[0]][0], "不具合", "番号つきの再現手順が無い")
    joined = "\n".join(l for _, l in body)
    for key in ("期待する結果", "実際の結果", "再現の頻度", "環境"):
        if key not in joined:
            fail(lines[sec[0]][0], "不具合", f"「{key}」が無い")

for no, rule, detail in issues:
    where = f"{name}:{no}" if no else name
    print(f"FAIL {where} [{rule}] {detail}")
verdict = "PASS" if not issues else "FAIL"
print(f"RESULT: {verdict} issue-check {name} ({len(issues)} 件)")
sys.exit(0 if not issues else 1)
PY
}

selftest() {
  local t rc=0 here
  here="$(cd "$(dirname "$0")" && pwd -P)"
  t="$(mktemp -d)"
  local good="$here/../examples/issue-example.md"
  check "$good" >/dev/null || { echo "FAIL selftest: 完成例が落ちた"; rc=1; }
  sed -e 's/^| 1 | 期間 1 年で、最初の 50 件が 3 秒以内に出る | .* |$/| 1 | 期間 1 年で、最初の 50 件が 3 秒以内に出る | |/' "$good" > "$t/nocheck.md"
  check "$t/nocheck.md" | grep -q '\[完了の条件\]' || { echo "FAIL selftest: 確認方法の欠けが通った"; rc=1; }
  sed -e 's/^目的は、/優先度は高です。目的は、/' "$good" > "$t/priority.md"
  check "$t/priority.md" | grep -q '\[優先度\]' || { echo "FAIL selftest: 優先度の語が通った"; rc=1; }
  grep -v '^| 実際の結果' "$good" > "$t/nobug.md"
  check "$t/nobug.md" | grep -q '\[不具合\]' || { echo "FAIL selftest: 実際の結果の欠けが通った"; rc=1; }
  sed -e '1s/.*/# 注文一覧の表示を修正する/' "$good" > "$t/title.md"
  check "$t/title.md" | grep -q '\[題名\]' || { echo "FAIL selftest: 直し方の題名が通った"; rc=1; }
  grep -v '^## 用語' "$good" > "$t/nosec.md"
  check "$t/nosec.md" | grep -q '\[必須の節\]' || { echo "FAIL selftest: 節の欠けが通った"; rc=1; }
  rm -rf "$t"
  if [ "$rc" -eq 0 ]; then echo "RESULT: PASS issue-check --selftest (6 例)"; else echo "RESULT: FAIL issue-check --selftest"; fi
  return $rc
}

case "${1:-}" in
  --selftest) selftest ;;
  "") echo "使い方: issue-check.sh <Issue 文.md> | --selftest"; exit 2 ;;
  *) check "$1" ;;
esac
