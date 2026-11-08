#!/usr/bin/env python3
"""check-doc — 資料の型の検査。.company/rules/documents.md の、機械で見られる決まりを落とす。

見るもの: 冒頭の 3 行の要約（引用ブロック、各行が文）、節の冒頭の導入の文（表・図・箇条書きから始めない）、
図と表の密度（本文 500 字に 1 つ）、図の直後の読み方、用語の初出の括弧説明、見出しの深さ（4 階層まで）、
文書の種類ごとの必須の節（仕様書・設計書・調査報告・手順書・完了報告）。
使い方: check_doc.py <ファイル>...   /   check_doc.py --selftest
出力: FAIL <ファイル>:<行> [<決まり>] <内容> を並べ、最後に RESULT: PASS|FAIL。1 件でも FAIL なら終了コード 1。
"""
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import mdparse  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
TERMS_FILE = HERE.parent / "doc-terms.txt"

DENSITY = 500
MAX_LEVEL = 4
REQUIRED = {
    "仕様書": ["完成の条件", "全体像", "将来の変化", "実装の進め方", "やらないこと", "未確定", "確認事項"],
    "設計書": ["背景", "目標", "設計", "代替案", "横断", "流出経路"],
    "調査報告": ["問い", "一次情報", "比較", "結論", "出典"],
    "手順書": ["目的", "準備", "手順", "失敗", "片付け"],
    "完了報告": ["確認", "未確認"],
}
KIND_NAME = {"table": "表", "fence": "コードか図", "list": "箇条書き", "image": "画像", "hr": "区切り線"}


def load_terms():
    terms = []
    if not TERMS_FILE.exists():
        return terms
    for line in TERMS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        terms.append(line.split("\t")[0].strip())
    return terms


def term_regex(term: str):
    if re.fullmatch(r"[A-Za-z0-9+/. -]+", term):
        return re.compile(rf"(?<![A-Za-z0-9+/]){re.escape(term)}(?![A-Za-z0-9+/])")
    return re.compile(re.escape(term))


def next_content(lines, i):
    for ln in lines[i + 1:]:
        if ln.kind in ("blank", "comment"):
            continue
        return ln
    return None


def check_text(src: str):
    issues = []
    lines = mdparse.parse(src)
    h1 = next((i for i, ln in enumerate(lines) if ln.kind == "heading" and ln.level == 1), None)
    if h1 is None:
        issues.append((0, "表題", "# の見出し（表題）が無い"))
        return issues

    # 1. 3 行の要約（引用ブロック）
    quote = []
    started = False
    for ln in lines[h1 + 1:]:
        if ln.kind == "heading":
            break
        if ln.in_quote and ln.kind in ("list", "quote"):
            quote.append(ln)
            started = True
        elif started and ln.kind != "blank":
            break
    content = [q for q in quote if not ("要約" in q.text and not q.text.endswith("。"))]
    if not quote:
        issues.append((lines[h1].no, "要約", "表題の下に 3 行の要約（引用ブロック > ）が無い"))
    elif len(content) != 3:
        issues.append((quote[0].no, "要約", f"要約が {len(content)} 行。何の文書か・結論・次にすることの 3 行にする"))
    else:
        for q in content:
            if not q.text.endswith(("。", "！", "？")):
                issues.append((q.no, "要約", "要約の各行は文にする（。で終える）"))

    # 2. 節の冒頭の導入の文、見出しの深さ
    for i, ln in enumerate(lines):
        if ln.kind != "heading":
            continue
        if ln.level > MAX_LEVEL:
            issues.append((ln.no, "見出しの深さ", f"{ln.level} 階層。4 階層までにする"))
        if ln.level == 1:
            continue
        nxt = next_content(lines, i)
        if nxt is None:
            issues.append((ln.no, "空の節", "見出しの下に本文が無い"))
        elif nxt.kind == "heading":
            if nxt.level <= ln.level:
                issues.append((ln.no, "空の節", "見出しの直後が同じ階層の見出し。本文を書くか見出しを消す"))
        elif nxt.kind in ("prose", "quote", "skipped"):
            pass
        elif nxt.kind == "list" and "目次" in ln.text:
            pass
        else:
            issues.append((ln.no, "導入の文", f"節が{KIND_NAME.get(nxt.kind, nxt.kind)}から始まる。「この節で分かること」を 1〜2 文先に書く"))

    # 3. 図と表の密度
    body = sum(mdparse.length(ln.text) for ln in lines if ln.kind in ("prose", "quote", "list"))
    mermaids = mdparse.code_blocks(lines, "mermaid")
    tables = 0
    prev_table = False
    for ln in lines:
        if ln.kind == "table" and not prev_table:
            tables += 1
        prev_table = ln.kind == "table"
    required = body // DENSITY
    if len(mermaids) + tables < required:
        issues.append((0, "図と表の密度", f"図 {len(mermaids)} と表 {tables}。本文 {body} 字には {required} 個以上"))

    # 4. 図の直後の読み方
    for _lang, start, end, _content in mermaids:
        idx = next(i for i, ln in enumerate(lines) if ln.no == end)
        following = [ln for ln in lines[idx + 1:] if ln.kind not in ("blank", "comment")][:3]
        if not any("読み方" in ln.text for ln in following if ln.kind in ("prose", "quote", "list")):
            issues.append((start, "図の読み方", "図の直後に「図の読み方: …」を 1〜2 文書く"))

    # 5. 用語の初出の括弧説明
    glossary = set()
    section = ""
    for ln in lines:
        if ln.kind == "heading":
            section = ln.text
        elif ln.kind == "table" and "用語" in section:
            first_cell = ln.text.split("|")[0].strip()
            if first_cell:
                glossary.add(first_cell)
    # 表だけに出る語は初出と見ない。説明は、本文の初出の行か、それより前の行（表を含む）にあればよい

    def glossed(text, m):
        after = text[m.end():m.end() + 40]
        before = text[:m.start()]
        inside = before.count("（") > before.count("）") or before.count("(") > before.count(")")
        return re.match(r"\s*[（(]", after) is not None or inside

    for term in load_terms():
        if any(term in g for g in glossary):
            continue
        rx = term_regex(term)
        first_prose = None
        first_any = None
        gloss_at = None
        for ln in lines:
            if ln.kind not in ("prose", "quote", "list", "table"):
                continue
            if not rx.search(ln.text):
                continue
            if first_any is None:
                first_any = ln
            if gloss_at is None and any(glossed(ln.text, mm) for mm in rx.finditer(ln.text)):
                gloss_at = ln.no
            if first_prose is None and ln.kind != "table":
                first_prose = ln
        if first_any is None:
            continue
        if gloss_at is None:
            issues.append(((first_prose or first_any).no, "用語の初出", f"「{term}」に括弧の説明がどこにも無い"))
        elif first_prose is not None and gloss_at > first_prose.no:
            issues.append((first_prose.no, "用語の初出", f"「{term}」の初出に括弧の説明が無い（説明は {gloss_at} 行目）"))

    # 6. 文書の種類ごとの必須の節
    title = lines[h1].text
    headings = [ln.text for ln in lines if ln.kind == "heading" and ln.level >= 2]
    for kind, keys in REQUIRED.items():
        if re.match(rf"^{kind}\s*[:：]", title):
            for key in keys:
                if not any(key in h for h in headings):
                    issues.append((lines[h1].no, "必須の節", f"{kind}に「{key}」の節が無い"))
    return issues


def report(name: str, issues) -> bool:
    for no, rule, detail in issues:
        where = f"{name}:{no}" if no else name
        print(f"FAIL {where} [{rule}] {detail}")
    verdict = "PASS" if not issues else "FAIL"
    print(f"RESULT: {verdict} check-doc {name} ({len(issues)} 件)")
    return not issues


GOOD = """# 手順書: 見本

| 項目 | 内容 |
|---|---|
| 作成日 | 2026-11-06 |

> **3 行でわかる要約**
> 1. これは検査の見本です。
> 2. 要約は 3 行で、何の文書か・結論・次にすることを書きます。
> 3. 次に、目的の節を読みます。

## 1. 目的

この節では目的を書きます。hooks（コマンドの直前に走る検査）が止める範囲を、表で示します。

| 操作 | 判定 |
|---|---|
| 読む | 許可 |

## 2. 準備

準備の流れを図にします。

```mermaid
flowchart LR
    A["読む"] --> B["書く"]
```

図の読み方: 左から右へ進みます。

## 3. 手順

1 行 1 操作で書きます。

1. 読む。
2. 書く。

## 4. 失敗したとき

戻し方を書きます。

## 5. 片付け

一時ファイルを消します。
"""

BAD = {
    "要約": "# 題\n\n## 1. 目的\n\n本文です。\n",
    "導入の文": "# 題\n\n> 1. 要約です。\n> 2. 要約です。\n> 3. 要約です。\n\n## 1. 目的\n\n| a | b |\n|---|---|\n| 1 | 2 |\n",
    "空の節": "# 題\n\n> 1. 要約です。\n> 2. 要約です。\n> 3. 要約です。\n\n## 1. 目的\n\n## 2. 次\n\n本文です。\n",
    "図の読み方": "# 題\n\n> 1. 要約です。\n> 2. 要約です。\n> 3. 要約です。\n\n## 1. 目的\n\n図です。\n\n```mermaid\nflowchart LR\n    A[\"a\"] --> B[\"b\"]\n```\n\n## 2. 次\n\n本文です。\n",
    "用語の初出": "# 題\n\n> 1. 要約です。\n> 2. 要約です。\n> 3. 要約です。\n\n## 1. 目的\n\nhooks が止めます。\n",
    "見出しの深さ": "# 題\n\n> 1. 要約です。\n> 2. 要約です。\n> 3. 要約です。\n\n## 1. 目的\n\n本文です。\n\n##### 深い\n\n本文です。\n",
    "図と表の密度": "# 題\n\n> 1. 要約です。\n> 2. 要約です。\n> 3. 要約です。\n\n## 1. 目的\n\n" + ("長い本文です。" * 90) + "\n",
    "必須の節": "# 仕様書: 見本\n\n> 1. 要約です。\n> 2. 要約です。\n> 3. 要約です。\n\n## 1. 目的\n\n本文です。\n",
}


def selftest() -> bool:
    ok = True
    issues = check_text(GOOD)
    if issues:
        ok = False
        print(f"FAIL selftest: 正例が落ちた: {issues}")
    for rule, text in BAD.items():
        found = {r for _, r, _ in check_text(text)}
        if rule not in found:
            ok = False
            print(f"FAIL selftest: 負例「{rule}」が通った（検出: {sorted(found)}）")
    print(f"RESULT: {'PASS' if ok else 'FAIL'} check-doc --selftest ({1 + len(BAD)} 例)")
    return ok


def main(argv) -> int:
    if argv == ["--selftest"]:
        return 0 if selftest() else 1
    if not argv:
        print(__doc__)
        return 2
    all_ok = True
    for name in argv:
        try:
            src = pathlib.Path(name).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            print(f"FAIL {name} [読めない] {e}")
            all_ok = False
            continue
        if not report(name, check_text(src)):
            all_ok = False
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
