#!/usr/bin/env python3
"""check-ja — 日本語の文体の検査。.company/rules/writing.md の、機械で見られる決まりを落とす。

見るもの: 禁則語、一文 60 字（超えが 5% 以内）と 100 字（0 件）、同じ文末の 4 連続、調（ですます・常体）の混在、
電報調（1 行 1 文を 4 行以上並べる）、絵文字、全角の英数字、数字と助数詞・英数字と和文の間の半角スペース。
使い方: check_ja.py <ファイル>...   /   check_ja.py --selftest
出力: FAIL <ファイル>:<行> [<決まり>] <内容> を並べ、最後に RESULT: PASS|FAIL。1 件でも FAIL なら終了コード 1。
検査から外すには、行に <!-- ja-ok --> を置く（禁則語の説明など、語そのものを書く必要がある行）。
"""
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import mdparse  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
FORBIDDEN_FILE = HERE.parent / "ja-forbidden.txt"

LONG = 60
TOO_LONG = 100
LONG_RATIO = 0.05
MIX_RATIO = 0.2

POLITE_END = re.compile(r"(です|ます|でした|ました|ません|ましょう|ください|でしょう|でしょうか|ですか|ますか|ませんか)[。！？]$")
ENDING = re.compile(r"(です|ます|でした|ました|ません|ましょう|ください|でしょう|である|ている|ない|する|ある|いる|れる|た|だ|る|い|う)[。！？]$")
EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-⛿✅❌❎❓-❕❗➕-➗➰➿️]")
FULLWIDTH = re.compile(r"[０-９Ａ-Ｚａ-ｚ]")
COUNTER = re.compile(
    r"[0-9](件|字|行|本|回|日|分|秒|個|枚|人|つ|点|度|章|節|項|段階|位|社|名|語|問|案|層|種類|か所|箇所|文|年|月|時|週|倍|割|桁|番|列|頁|ページ|台|組|歳|枠|色|画面)"
)
JA = "ぁ-ゟァ-ヺ一-鿿々"
SPACING = re.compile(rf"[A-Za-z0-9][{JA}]|[{JA}][A-Za-z0-9]")
EXEMPT = re.compile(r"ja-ok")


def load_forbidden():
    items = []
    if not FORBIDDEN_FILE.exists():
        return items
    for line in FORBIDDEN_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        pat, _, hint = line.partition("\t")
        items.append((re.compile(pat), hint.strip() or "置き換える"))
    return items


def ending_token(sentence: str) -> str:
    """文末の印。「です」「ません」のような決まった形はそのまま、動詞の「〜ます」は直前の 1 字を含めて見る。
    「書きます。足します。回ります。」は別の文末、「します。します。します。します。」は同じ文末と数える。"""
    body = sentence.rstrip("。！？")
    for fixed in ("でした", "ました", "ません", "ましょう", "ください", "でしょう", "である", "ている", "です"):
        if body.endswith(fixed):
            return fixed
    if body.endswith("ます"):
        return body[-3:]
    m = ENDING.search(sentence)
    return m.group(1) if m else body[-2:]


def check_text(src: str):
    """本文を検査し、(行番号, 決まり, 内容) の列を返す。行番号 0 は文書全体への指摘。"""
    issues = []
    lines = mdparse.parse(src)
    forbidden = load_forbidden()
    section = ""
    sent_total = 0
    long_examples = []
    polite = 0
    plain = 0
    polite_examples = []
    plain_examples = []
    endings = []
    telegraph = []

    for ln in lines:
        if ln.kind == "heading":
            section = ln.text
            endings = []
            telegraph = []
        if ln.kind in ("blank", "fence", "code", "mermaid", "frontmatter", "comment", "skipped", "hr", "image"):
            if ln.kind != "blank":
                endings = []
                telegraph = []
            continue
        text = ln.text
        raw_exempt = EXEMPT.search(ln.raw) is not None

        m = EMOJI.search(text)
        if m:
            issues.append((ln.no, "絵文字", f"「{m.group(0)}」で強調しない"))
        m = FULLWIDTH.search(text)
        if m:
            issues.append((ln.no, "全角の英数字", f"「{m.group(0)}」は半角にする"))
        counter_spans = [(m.start(), m.end()) for m in COUNTER.finditer(text)]
        for s, e in counter_spans:
            issues.append((ln.no, "助数詞のスペース", f"「{text[s:e]}」→「{text[s]} {text[s + 1:e]}」"))
        for m in SPACING.finditer(text):
            if any(s <= m.start() < e for s, e in counter_spans):
                continue
            issues.append((ln.no, "英数字と和文のスペース", f"「{m.group(0)}」の間に半角スペース"))

        if not raw_exempt and "禁則" not in section and "禁則語" not in text:
            for rx, hint in forbidden:
                m = rx.search(text)
                if m:
                    issues.append((ln.no, "禁則語", f"「{m.group(0)}」→ {hint}"))

        if ln.kind in ("prose", "quote", "list"):
            sents = mdparse.sentences(text)
            for s, complete in sents:
                n = mdparse.length(s)
                sent_total += 1
                if n > TOO_LONG:
                    issues.append((ln.no, "100 字", f"{n} 字。2 文に切る: {s[:30]}…"))
                elif n > LONG:
                    long_examples.append((ln.no, n, s))
                if complete and ln.kind != "list":
                    if POLITE_END.search(s):
                        polite += 1
                        polite_examples.append(s)
                    else:
                        plain += 1
                        plain_examples.append(s)
                    e = ending_token(s)
                    endings.append(e)
                    if len(endings) >= 4 and len(set(endings[-4:])) == 1:
                        issues.append((ln.no, "文末の 4 連続", f"「{e}。」が 4 文続く。文末を変える"))
                        endings = []
            if ln.kind == "list":
                endings = []
                telegraph = []
            elif ln.kind == "prose" and len(sents) == 1 and sents[0][1]:
                telegraph.append(ln.no)
                if len(telegraph) == 4:
                    issues.append((telegraph[0], "電報調", "1 行 1 文が 4 行続く。2〜4 文を接続語でつないで段落にする"))
            else:
                telegraph = []
        else:
            telegraph = []

    if sent_total and len(long_examples) / sent_total > LONG_RATIO:
        ratio = len(long_examples) / sent_total
        issues.append((0, "60 字", f"60 字超が {len(long_examples)}/{sent_total} 文（{ratio:.0%}）。5% 以内にする"))
        for no, n, s in sorted(long_examples, key=lambda x: -x[1])[:10]:
            issues.append((no, "60 字", f"{n} 字: {s[:40]}…"))
    total = polite + plain
    if polite and plain and min(polite, plain) / total >= MIX_RATIO:
        minority = plain_examples if plain <= polite else polite_examples
        sample = "、".join(f"「{s[:24]}」" for s in minority[:2])
        issues.append((0, "調の混在", f"ですます {polite} 文、常体 {plain} 文。1 つの文書で 1 つに揃える（少ない側: {sample}）"))
    return issues


def report(name: str, issues) -> bool:
    for no, rule, detail in issues:
        where = f"{name}:{no}" if no else name
        print(f"FAIL {where} [{rule}] {detail}")
    verdict = "PASS" if not issues else "FAIL"
    print(f"RESULT: {verdict} check-ja {name} ({len(issues)} 件)")
    return not issues


GOOD = """# 題

> **3 行でわかる要約**
> 1. これは検査の見本です。
> 2. 文は短く、結論を先に書きます。
> 3. 次に、手順を読みます。

## 1. 目的

この節では、検査の目的を説明します。文は 60 字以内に収めるので、読みやすくなります。ただ、短い文ばかりだと単調になるため、長さを変えます。
"""

BAD = {
    "禁則語": "# 題\n\nこの仕組みは要件を実現する。\n",
    "100 字": "# 題\n\n" + "あ" * 101 + "。\n",
    "文末の 4 連続": "# 題\n\n朝は雨です。昼は晴れです。夜は曇りです。明日は雪です。\n",
    "調の混在": "# 題\n\n結論を書きます。理由を書きます。例を書きます。そして手順を書きます。確認する。終える。\n",
    "電報調": "# 題\n\n朝になった。\n雨が降った。\n傘を持った。\n駅へ歩いた。\n",
    "絵文字": "# 題\n\n✅ 完了です。\n",
    "全角の英数字": "# 題\n\n３件です。\n",
    "助数詞のスペース": "# 題\n\n3件です。\n",
    "英数字と和文のスペース": "# 題\n\nMac全体を探します。\n",
    "60 字": "# 題\n\nこの文は長いので六十字を超えてしまい、読み手が一度に理解できる長さを過ぎてしまいますから、ここで二つに切るのが決まりです。\n",
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
    print(f"RESULT: {'PASS' if ok else 'FAIL'} check-ja --selftest ({1 + len(BAD)} 例)")
    return ok


def main(argv) -> int:
    if not argv or argv == ["--selftest"]:
        if argv == ["--selftest"]:
            return 0 if selftest() else 1
        print(__doc__)
        return 2
    all_ok = True
    for name in argv:
        p = pathlib.Path(name)
        try:
            src = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            print(f"FAIL {name} [読めない] {e}")
            all_ok = False
            continue
        if not report(name, check_text(src)):
            all_ok = False
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
