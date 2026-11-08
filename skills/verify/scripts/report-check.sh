#!/usr/bin/env bash
# skills/verify/scripts/report-check.sh <完了報告.md> — 完了報告の検査。
#   表題が「完了報告:」で始まる。3 行の要約がある。受け入れ条件の表（確認コマンドと結果の列）があり、全行に結果があって <…> の穴が無い。
#   「直したこと」「未確認」「検証の記録」の節がある。未確認の表の各行に理由がある。検証の記録への参照がある。
#   推測の語（動くはず、通るはず、と思われ、おそらく）と、コマンドの無い「確認済み」「問題なし」を落とす。
# 使い方: report-check.sh <ファイル>   /   report-check.sh --selftest
# 出力: FAIL <ファイル>:<行> [<決まり>] <内容> と、最後に RESULT: PASS|FAIL report-check。1 件でも FAIL なら終了コード 1。
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"

check() {  # check <ファイル> → python で検査
  python3 -I - "$1" <<'PY'
import re
import sys

name = sys.argv[1]
try:
    text = open(name, encoding="utf-8").read()
except OSError as e:
    print(f"FAIL {name} [読めない] {e}")
    print(f"RESULT: FAIL report-check {name}")
    sys.exit(1)
lines = text.split("\n")
issues = []

def fail(no, rule, detail):
    issues.append((no, rule, detail))

title = next((l for l in lines if l.startswith("# ")), "")
if not title.startswith("# 完了報告:"):
    fail(1, "表題", "「# 完了報告: <件名>」で始める")

quote = [l for l in lines[:25] if l.startswith(">")]
content = [l for l in quote if re.search(r"[。！？]\s*$", l.strip("> *"))]
if len(content) != 3:
    fail(1, "要約", f"3 行の要約（引用ブロック）が {len(content)} 行")

def section(key):
    start = next((i for i, l in enumerate(lines) if l.startswith("## ") and key in l), None)
    if start is None:
        return None
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    return start, end

def table_rows(start, end):
    rows = []
    header = None
    for i in range(start, end):
        l = lines[i].strip()
        if not l.startswith("|"):
            continue
        cells = [c.strip() for c in l.strip("|").split("|")]
        if header is None:
            header = cells
            continue
        if all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
            continue
        rows.append((i + 1, cells))
    return header, rows

sec = section("受け入れ条件")
if sec is None:
    fail(0, "受け入れ条件", "「## 受け入れ条件」の節が無い")
else:
    header, rows = table_rows(*sec)
    if not header or not any("確認" in h for h in header) or not any("結果" in h for h in header):
        fail(sec[0] + 1, "受け入れ条件", "表の列に「確認コマンド」と「結果」が要る")
    elif not rows:
        fail(sec[0] + 1, "受け入れ条件", "条件の行が無い")
    else:
        ci = next(i for i, h in enumerate(header) if "確認" in h)
        ri = next(i for i, h in enumerate(header) if "結果" in h)
        for no, cells in rows:
            if len(cells) <= max(ci, ri) or not cells[ci] or not cells[ri]:
                fail(no, "受け入れ条件", "確認コマンドか結果が空")
            elif "<" in cells[ci] or "<" in cells[ri]:
                fail(no, "受け入れ条件", "雛形の <…> が残っている")

for key in ("直したこと", "未確認", "検証の記録"):
    if section(key) is None:
        fail(0, key, f"「## {key}」の節が無い")

sec = section("未確認")
if sec is not None:
    header, rows = table_rows(*sec)
    if header and any("理由" in h for h in header):
        ri = next(i for i, h in enumerate(header) if "理由" in h)
        for no, cells in rows:
            if len(cells) <= ri or not cells[ri] or "<" in cells[ri]:
                fail(no, "未確認", "理由が空か、雛形の <…> が残っている")

sec = section("検証の記録")
if sec is not None and not re.search(r"docs/verify/|\.verify/", "\n".join(lines[sec[0]:sec[1]])):
    fail(sec[0] + 1, "検証の記録", "docs/verify/<日付>.md か tmp/.verify/ への参照が無い")

in_code = False
for i, l in enumerate(lines, 1):
    if l.strip().startswith("```"):
        in_code = not in_code
        continue
    if in_code or l.strip().startswith("<!--"):
        continue
    for w in ("動くはず", "通るはず", "と思われ", "おそらく", "はずです", "はずである"):
        if w in l:
            fail(i, "推測の語", f"「{w}」。実行して結果を書くか、未確認に書く")
    if re.search(r"(確認済み|問題なし)", l) and "`" not in l and not l.startswith("|"):
        fail(i, "根拠", "「確認済み」「問題なし」には、確認コマンドと結果を添える")

for no, rule, detail in issues:
    where = f"{name}:{no}" if no else name
    print(f"FAIL {where} [{rule}] {detail}")
verdict = "PASS" if not issues else "FAIL"
print(f"RESULT: {verdict} report-check {name} ({len(issues)} 件)")
sys.exit(0 if not issues else 1)
PY
}

selftest() {
  local t rc=0
  t="$(mktemp -d)"
  cat > "$t/good.md" <<'EOF'
# 完了報告: 見本

> **3 行でわかる要約**
> 1. 見本の作業を終えました。
> 2. 検証は全体 PASS で、未確認は 1 件です。
> 3. 記録を見て、次の段階の承認をお願いします。

## 1. 受け入れ条件

2 件とも確認コマンドがあります。

| # | 条件 | 確認コマンド | 結果 |
|---|---|---|---|
| 1 | 検査が通る | `bash tools/verify-all.sh --fast` | `RESULT: PASS verify-all --fast` |
| 2 | 図が描ける | `node tools/render-mermaid.mjs docs/x.md` | `RESULT: PASS render-mermaid (3 図、0 件)` |

## 2. 直したこと

直した所はありません。

## 3. 未確認

1 件です。

| 条件 | 理由 | 確かめ方 |
|---|---|---|
| Cursor で ask が効く | 実機が手元に無い | 社長が Cursor で `git status` と commit の依頼を試す |

## 4. 検証の記録

`docs/verify/2026-11-06.md`。2026-11-06 12:00 に `--full` を回した。
EOF
  local bt='`'
  sed -e "s/| ${bt}RESULT: PASS verify-all --fast${bt} |/| <結果> |/" "$t/good.md" > "$t/hole.md"
  sed -e 's/^直した所はありません。$/直さなくても動くはずです。/' "$t/good.md" > "$t/guess.md"
  grep -v '^## 3. 未確認' "$t/good.md" | grep -v '^| Cursor' > "$t/nosec.md"
  check "$t/good.md" >/dev/null || { echo "FAIL selftest: 正例が落ちた"; rc=1; }
  check "$t/hole.md" | grep -q '\[受け入れ条件\]' || { echo "FAIL selftest: 雛形の穴が通った"; rc=1; }
  check "$t/guess.md" | grep -q '\[推測の語\]' || { echo "FAIL selftest: 推測の語が通った"; rc=1; }
  check "$t/nosec.md" | grep -q '\[未確認\]' || { echo "FAIL selftest: 節の欠けが通った"; rc=1; }
  rm -rf "$t"
  if [ "$rc" -eq 0 ]; then echo "RESULT: PASS report-check --selftest (4 例)"; else echo "RESULT: FAIL report-check --selftest"; fi
  return $rc
}

case "${1:-}" in
  --selftest) selftest ;;
  "") echo "使い方: report-check.sh <完了報告.md> | --selftest"; exit 2 ;;
  *) check "$1" ;;
esac
