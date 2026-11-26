#!/usr/bin/env python3
"""check-ja — 日本語の文体の検査。.company/rules/writing.md の、機械で見られる決まりを落とす。

見るもの: 禁則語（tools/ja-forbidden.txt と、現場の語の言い換えの tools/ja-terms.txt）、一文 60 字（超えが 5% 以内）と 100 字（0 件）、
同じ文末の 4 連続、調（ですます・常体）の混在、電報調（1 行 1 文を 4 行以上並べる）、絵文字、全角の英数字、
数字と助数詞・英数字と和文の間の半角スペース。tools/ja-terms.txt が無ければ FAIL（道具が無いのと同じ）。
WARN（落とさないが知らせる）: 25 字以下の短い文が 3 つ続く（短文の連なり）、本文の文のうち短い文が 4 割を超える（短文の割合。10 文以上のとき）。
使い方: check_ja.py <ファイル>...   /   check_ja.py --selftest
出力: FAIL <ファイル>:<行> [<決まり>] <内容> と WARN <ファイル>:<行> [<決まり>] <内容> を並べ、最後に RESULT: PASS|FAIL。
FAIL が 1 件でもあれば終了コード 1。WARN は数えない。
検査から外すには、行に <!-- ja-ok --> を置く（禁則語の説明など、語そのものを書く必要がある行）。

現場の語だけを見る入口（.md 以外のファイル。tools/check-file.sh が回す）:
  check_ja.py --terms [--] <ファイル>...   /   check_ja.py --terms -（標準入力。名前は「入力」と出す）
  tools/ja-terms.txt の語だけを見る。「」の中、バッククォート 1 つで囲んだ中、3 つのバッククォートの囲みの中は数えない。
  行の終わりまで閉じない「とバッククォートは囲みと見ず、その後ろも数える。
  ファイルでは <!-- ja-ok --> のある行も数えない。標準入力（hooks が渡す返答と、commit 文・PR 文・Issue 文）では、印を見ない。
  返答の中の印は画面に見えないので、印で語を隠せないようにする。語の表そのもの（名前が ja-terms.txt のファイル）は、語を定義する行を数えない。
  出力: FAIL <名前>:<行> [現場の語] 「<語>」→ <置き換えの例> の行と、最後に RESULT: PASS|FAIL check-terms <名前> (<n> 件)。
  当たりがあれば終了コード 1。tools/ja-terms.txt が無いときも FAIL。UTF-8 で読めない字は置き換えて読み、WARN の行で知らせる。
  --added-lines <行番号,...> <ファイル>: その行だけを見る（囲みの区切りはファイル全体で数える）。
  移した先で、プロジェクト自身のファイルの git の HEAD から足した行を見るときに、tools/check-file.sh が渡す。
"""
import contextlib
import io
import pathlib
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import mdparse  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
FORBIDDEN_FILE = HERE.parent / "ja-forbidden.txt"
TERMS_FILE = HERE.parent / "ja-terms.txt"

LONG = 60
TOO_LONG = 100
LONG_RATIO = 0.05
MIX_RATIO = 0.2
SHORT = 25  # これ以下の字数の文を「短い文」と見る
SHORT_RUN = 3  # 短い文がこの数だけ続いたら WARN
SHORT_RATIO = 0.4  # 本文の文のうち短い文の割合がこれを超えたら WARN
SHORT_MIN_SENTENCES = 10  # 割合を見る最少の文数

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
TERMS_EXEMPT = re.compile(r"<!--\s*ja-ok\s*-->")  # --terms で、この印のある行は数えない
TERMS_FENCE = re.compile(r"^(`{3,})")  # --terms で数えない囲みの区切り
STDIN_NAME = "入力"


def load_table(path):
    """「正規表現<TAB>置き換えの例」の表を [(正規表現, 置き換えの例)] で読む。ファイルが無ければ None。"""
    if not path.exists():
        return None
    items = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        pat, _, hint = line.partition("\t")
        items.append((re.compile(pat), hint.strip() or "置き換える"))
    return items


def load_forbidden():
    return load_table(FORBIDDEN_FILE) or []


def load_terms():
    """現場の語の表（tools/ja-terms.txt）。無ければ None（呼ぶ側が FAIL にする）。"""
    return load_table(TERMS_FILE)


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


def check_all(src: str):
    """本文を検査し、(FAIL の列, WARN の列) を返す。各要素は (行番号, 決まり, 内容)。行番号 0 は文書全体への指摘。"""
    issues = []
    warnings = []
    short_run = 0
    short_total = 0
    prose_total = 0
    lines = mdparse.parse(src)
    forbidden = load_forbidden()
    terms = load_terms()
    if terms is None:
        issues.append((0, "道具が無い", f"{TERMS_FILE.name}（現場の語の表）が無い。言い換えを見られない（SKIP は FAIL と同じ）"))
        terms = []
    forbidden = forbidden + terms  # 現場の語の言い換えも、.md では禁則語と同じに落とす
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
            short_run = 0
        if ln.kind in ("blank", "fence", "code", "mermaid", "frontmatter", "comment", "skipped", "hr", "image"):
            if ln.kind != "blank":
                endings = []
                telegraph = []
                short_run = 0
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
                if complete and ln.kind == "prose":
                    prose_total += 1
                    if n <= SHORT:
                        short_total += 1
                        short_run += 1
                        if short_run == SHORT_RUN:
                            warnings.append((ln.no, "短文の連なり", f"{SHORT} 字以下の文が {SHORT_RUN} つ続く。理由と条件は「〜ので」「〜とき」で 1 文にまとめる"))
                            short_run = 0
                    else:
                        short_run = 0
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
                short_run = 0
            elif ln.kind == "prose" and len(sents) == 1 and sents[0][1]:
                telegraph.append(ln.no)
                if len(telegraph) == 4:
                    issues.append((telegraph[0], "電報調", "1 行 1 文が 4 行続く。2〜4 文を接続語でつないで段落にする"))
            else:
                telegraph = []
        else:
            telegraph = []
            short_run = 0

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
    if prose_total >= SHORT_MIN_SENTENCES and short_total / prose_total > SHORT_RATIO:
        ratio = short_total / prose_total
        warnings.append((0, "短文の割合", f"{SHORT} 字以下の文が {short_total}/{prose_total} 文（{ratio:.0%}）。4 割以内にし、つながる文は「〜ので」で 1 文にまとめる"))
    return issues, warnings


def check_text(src: str):
    """FAIL だけを返す（従来の入口）。"""
    return check_all(src)[0]


def report(name: str, issues, warnings=()) -> bool:
    for no, rule, detail in issues:
        where = f"{name}:{no}" if no else name
        print(f"FAIL {where} [{rule}] {detail}")
    for no, rule, detail in warnings:
        where = f"{name}:{no}" if no else name
        print(f"WARN {where} [{rule}] {detail}")
    verdict = "PASS" if not issues else "FAIL"
    extra = f"、WARN {len(warnings)} 件" if warnings else ""
    print(f"RESULT: {verdict} check-ja {name} ({len(issues)} 件{extra})")
    return not issues


# ---- 現場の語だけを見る入口（--terms）

def mask_quotes(line: str) -> str:
    """「」（入れ子を含む）と、バッククォートで囲んだ中の字を消す。
    括弧とバッククォートは残し、消した前後の字が 1 語につながらないようにする。
    行の終わりまで閉じない「とバッククォートは囲みと見ない。始まりの字は残し、その後ろを改めて見る。
    閉じない印 1 つで、行の残りの語を隠せないようにするため。"""
    out = []
    depth = 0
    code = False
    start = -1  # 今の囲みの始まりの位置（line の添字）
    keep = 0  # 囲みの始まりの字を足す前の out の長さ
    for i, ch in enumerate(line):
        if code:
            if ch == "`":
                code = False
                out.append(ch)
            continue
        if depth == 0 and ch == "`":
            code = True
            start, keep = i, len(out)
            out.append(ch)
        elif ch == "「":
            if depth == 0:
                start, keep = i, len(out)
                out.append(ch)
            depth += 1
        elif ch == "」" and depth > 0:
            depth -= 1
            if depth == 0:
                out.append(ch)
        elif depth == 0:
            out.append(ch)
    if code or depth:
        return "".join(out[:keep]) + line[start] + mask_quotes(line[start + 1:])
    return "".join(out)


def is_terms_table(name: str) -> bool:
    """語の表そのもの（名前が ja-terms.txt）か。語を定義する行は、語を書かないと定義できないので数えない。"""
    return pathlib.PurePath(name).name == TERMS_FILE.name


def terms_hits(src: str, terms, table=False, only=None, exempt=True):
    """現場の語の当たりを [(行番号, 語, 置き換えの例)] で返す。
    「」の中、バッククォートで囲んだ中、``` の囲みの中は数えない（行の終わりまで閉じないものは囲みと見ない）。
    exempt が真なら、<!-- ja-ok --> のある行も数えない。標準入力では偽にする（返答の印は画面に見えないため）。
    table が真なら語の表そのもので、語を定義する行（空でなく、# で始まらない行）も数えない。
    only（行番号の集合）があれば、その行だけを見る。囲みの区切りは、only によらずファイル全体で数える。"""
    hits = []
    fence = ""
    for no, raw in enumerate(src.split("\n"), 1):
        line = raw.rstrip("\r")
        st = line.strip()
        if fence:
            if st.startswith(fence):
                fence = ""
            continue
        m = TERMS_FENCE.match(st)
        if m:
            fence = m.group(1)
            continue
        if only is not None and no not in only:
            continue
        if exempt and TERMS_EXEMPT.search(line):
            continue
        if table and st and not st.startswith("#"):
            continue
        target = mask_quotes(line)
        for rx, hint in terms:
            for mm in rx.finditer(target):
                hits.append((no, mm.group(0), hint))
    return hits


def parse_lines(spec: str):
    """「3,5,9」を {3, 5, 9} にする。空なら空の集合。数でない値があれば None。"""
    out = set()
    for part in re.split(r"[,\s]+", spec.strip()):
        if not part:
            continue
        if not re.fullmatch(r"[0-9]+", part):
            return None
        out.add(int(part))
    return out


def read_source(name: str):
    """(本文, 読めない理由, UTF-8 で読めない字があったか) を返す。"-" は標準入力。"""
    try:
        data = sys.stdin.buffer.read() if name == "-" else pathlib.Path(name).read_bytes()
    except (OSError, AttributeError, ValueError) as e:
        return None, str(e), False
    try:
        return data.decode("utf-8"), None, False
    except UnicodeDecodeError:
        return data.decode("utf-8", errors="replace"), None, True


def terms_main(args) -> int:
    """--terms の入口。args は --terms より後ろの引数。"""
    usage = ("使い方: check_ja.py --terms [--] <ファイル>...   /   check_ja.py --terms -（標準入力）"
             "   /   check_ja.py --terms --added-lines <行番号,...> [--] <ファイル>")
    files = []
    only = None
    opts = True
    i = 0
    while i < len(args):
        a = args[i]
        if opts and a == "--":
            opts = False
        elif opts and a == "--added-lines":
            only = parse_lines(args[i + 1]) if i + 1 < len(args) else None
            if only is None:
                print(usage)
                return 2
            i += 1
        else:
            files.append(a)
        i += 1
    if not files or (only is not None and len(files) != 1):
        print(usage)
        return 2
    terms = load_terms()
    if terms is None:
        print(f"FAIL {TERMS_FILE} [道具が無い] 現場の語の表が無い（SKIP は FAIL と同じ）")
        print(f"RESULT: FAIL check-terms ({len(files)} 本。表が無いので見られない)")
        return 1
    note = f"、足した {len(only)} 行を見た" if only is not None else ""
    all_ok = True
    for name in files:
        label = STDIN_NAME if name == "-" else name
        src, err, bad = read_source(name)
        if err is not None:
            print(f"FAIL {label} [読めない] {err}")
            print(f"RESULT: FAIL check-terms {label} (読めない)")
            all_ok = False
            continue
        hits = terms_hits(src, terms, table=(name != "-" and is_terms_table(name)), only=only, exempt=(name != "-"))
        for no, word, hint in hits:
            print(f"FAIL {label}:{no} [現場の語] 「{word}」→ {hint}")
        if bad:
            print(f"WARN {label} [文字コード] UTF-8 で読めない字がある。読めた字だけを見た")
        print(f"RESULT: {'FAIL' if hits else 'PASS'} check-terms {label} ({len(hits)} 件{note})")
        if hits:
            all_ok = False
    return 0 if all_ok else 1


GOOD = """# 題

> **3 行でわかる要約**
> 1. これは検査の見本です。
> 2. 文は短く、結論を先に書きます。
> 3. 次に、手順を読みます。

## 1. 目的

目的は、検査の見本を示すことです。文は 60 字以内に収めるので、読みやすくなります。ただ、短い文ばかりだと単調になるため、長さを変えます。
"""

BAD = {
    "禁則語": "# 題\n\nこの仕組みは要件を実現する。この節では、それを説明する。\n",
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

# WARN の負例。落ちないが、知らせる
WARN_BAD = {
    "短文の連なり": "# 題\n\n朝です。雨です。寒いです。だから傘を持ちました。\n",
    "短文の割合": "# 題\n\n" + "長い文を書きますので、ここでは二十五字を超えるようにしています。短い文です。" * 5 + "\n",
}


# 現場の語の言い換え（git のブランチを別の語にする）を落とし、無関係な語は通す。(名前, 本文, 落ちるべきか)
# 行の末尾の印は、--terms でこのファイルを見るときに、語の例を数えないためのもの
TERM_CASES = [
    ("ブランチの言い換え", "# 題\n\n作業用の枝を切って、そこで直します。\n", True),  # <!-- ja-ok -->
    ("ブランチの言い換え（分かれ）", "# 題\n\nマージは、枝分かれを取り込む操作です。\n", True),  # <!-- ja-ok -->
    ("ブランチ", "# 題\n\n作業用のブランチを切って、そこで直します。\n", False),
    ("枝番", "# 題\n\n受付番号には、依頼ごとに枝番を付けます。\n", False),  # <!-- ja-ok -->
    ("枝刈り", "# 題\n\n探索の木は、見込みの無い道を枝刈りして小さくします。\n", False),  # <!-- ja-ok -->
    ("分枝", "# 題\n\n整数の問題は、分枝限定法で解きます。\n", False),  # <!-- ja-ok -->
    ("枝豆", "# 題\n\n今日のつまみは、ゆでた枝豆です。\n", False),  # <!-- ja-ok -->
]

# --terms（.md 以外のファイル）で見る例。(名前, 本文, 当たる行の番号)
TERMS_ONLY_CASES = [
    ("鉤括弧の中", "# 決まり: 「枝」とは書かない\n", []),  # <!-- ja-ok -->
    ("バッククォートの中", "echo `枝`  # 語の例\n", []),  # <!-- ja-ok -->
    ("囲みの中", "```\n作業用の枝\n```\nおわり\n", []),  # <!-- ja-ok -->
    ("ja-ok の印の行", "作業用の枝 <!-- ja-ok -->\n", []),  # <!-- ja-ok -->
    ("枝刈り", "# 探索を枝刈りする\n", []),  # <!-- ja-ok -->
    ("枝分かれ", "# 処理が枝分かれする\n", [1]),  # <!-- ja-ok -->
    ("作業用の枝", "x = 1\n# 作業用の枝を切る\n", [2]),  # <!-- ja-ok -->
    ("鉤括弧の外と中", "# 「枝」と書かず、枝とも書かない\n", [1]),  # <!-- ja-ok -->
    ("閉じないバッククォート", "# `x 作業用の枝を切る\n", [1]),  # <!-- ja-ok -->
    ("閉じない鉤括弧", "# 「x 作業用の枝を切る\n", [1]),  # <!-- ja-ok -->
    ("閉じた鉤括弧のあとの閉じないバッククォート", "# 「枝」と書かず `作業用の枝\n", [1]),  # <!-- ja-ok -->
    ("閉じない鉤括弧の後ろの閉じた囲み", "# 「x と `枝` は書く\n", []),  # <!-- ja-ok -->
]
# 置き換えの例: 履歴が分かれる様子の語は「分岐」、それ以外は「ブランチ」。2 つの行は同じ字に重ねて当たらない。(本文, 置き換えの例の始まり)
HINT_CASES = [
    ("main から履歴が枝分かれした\n", "分岐"),  # <!-- ja-ok -->
    ("履歴が枝分れした\n", "分岐"),  # <!-- ja-ok -->
    ("作業用の枝を切る\n", "ブランチ"),  # <!-- ja-ok -->
]
# --added-lines: 指定の行（1・3・5 行）だけを見る。5 行は囲みの中なので数えない（囲みは指定の外の 4 行で始まる）
ADDED_SRC = "作業用の枝\nx = 1\n枝分かれ\n```\n枝\n```\n"  # <!-- ja-ok -->
ADDED_ONLY = {1, 3, 5}
ADDED_WANT = [1, 3]
# 語の表そのもの: 語を定義する行は数えず、注釈の行は数える
TABLE_SRC = "# 注釈に書いた枝\n(?<!分)枝\tブランチ\n"  # <!-- ja-ok -->
TABLE_WANT = [1]
STDIN_SRC = "作業用の枝を切る\n"  # <!-- ja-ok -->
# 標準入力（返答と commit 文）では、ja-ok の印で語を隠せない。ファイルでは、印のある行を数えない
STDIN_EXEMPT_SRC = "作業用の枝を切る <!-- ja-ok -->\n"  # <!-- ja-ok -->


def selftest_terms() -> tuple:
    """--terms の自己試験。(通ったか, 例の数) を返す。"""
    global TERMS_FILE
    ok = True
    n = 0
    terms = load_terms()
    if terms is None:
        print(f"FAIL selftest: {TERMS_FILE} が無い")
        return False, 1
    for label, text, want in TERMS_ONLY_CASES:
        n += 1
        got = [no for no, _, _ in terms_hits(text, terms)]
        if got != want:
            ok = False
            print(f"FAIL selftest: --terms の「{label}」で当たる行が {got}（期待 {want}）")
    n += 1
    got = [no for no, _, _ in terms_hits(ADDED_SRC, terms, only=ADDED_ONLY)]
    if got != ADDED_WANT:
        ok = False
        print(f"FAIL selftest: --added-lines で当たる行が {got}（期待 {ADDED_WANT}）")
    n += 1
    got = [no for no, _, _ in terms_hits(TABLE_SRC, terms, table=is_terms_table("tools/ja-terms.txt"))]
    if got != TABLE_WANT:
        ok = False
        print(f"FAIL selftest: 語の表そのもので当たる行が {got}（期待 {TABLE_WANT}）")
    for text, want in HINT_CASES:
        n += 1
        got = [hint for _, _, hint in terms_hits(text, terms)]
        if len(got) != 1 or not got[0].startswith(want):
            ok = False
            print(f"FAIL selftest: 「{text.strip()}」の置き換えの例が {got}（期待 「{want}」で始まる 1 件）")
    # 標準入力: 名前は「入力」、当たりがあれば終了コード 1。ja-ok の印があっても数える
    for src in (STDIN_SRC, STDIN_EXEMPT_SRC):
        n += 1
        proc = subprocess.run([sys.executable, "-I", str(pathlib.Path(__file__).resolve()), "--terms", "-"],
                              input=src.encode("utf-8"), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        out = proc.stdout.decode("utf-8", errors="replace")
        if proc.returncode != 1 or f"FAIL {STDIN_NAME}:1 [現場の語]" not in out or f"RESULT: FAIL check-terms {STDIN_NAME} (1 件)" not in out:
            ok = False
            print(f"FAIL selftest: --terms - の終了コード {proc.returncode}（期待 1）、出力: {out.strip()[:120]}")
    n += 1
    if terms_hits(STDIN_EXEMPT_SRC, terms):
        ok = False
        print("FAIL selftest: ファイルの ja-ok の印のある行を数えた")
    # 表が無ければ、--terms も .md の検査も FAIL（道具が無いのと同じ）
    n += 1
    saved = TERMS_FILE
    buf = io.StringIO()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            TERMS_FILE = pathlib.Path(tmp) / "ja-terms.txt"
            target = pathlib.Path(tmp) / "x.txt"
            target.write_text("x\n", encoding="utf-8")
            with contextlib.redirect_stdout(buf):
                rc = terms_main([str(target)])
            md_rules = {r for _, r, _ in check_text(GOOD)}
    finally:
        TERMS_FILE = saved
    if rc != 1 or "[道具が無い]" not in buf.getvalue() or "道具が無い" not in md_rules:
        ok = False
        print(f"FAIL selftest: 表が無いのに通った（--terms の終了コード {rc}、.md の検出: {sorted(md_rules)}）")
    return ok, n


def selftest() -> bool:
    ok = True
    issues, warnings = check_all(GOOD)
    if issues or warnings:
        ok = False
        print(f"FAIL selftest: 正例が落ちた: {issues + warnings}")
    for rule, text in BAD.items():
        found = {r for _, r, _ in check_text(text)}
        if rule not in found:
            ok = False
            print(f"FAIL selftest: 負例「{rule}」が通った（検出: {sorted(found)}）")
    for rule, text in WARN_BAD.items():
        found = {r for _, r, _ in check_all(text)[1]}
        if rule not in found:
            ok = False
            print(f"FAIL selftest: WARN の負例「{rule}」が通った（検出: {sorted(found)}）")
    for label, text, want in TERM_CASES:
        got = "禁則語" in {r for _, r, _ in check_text(text)}
        if got != want:
            ok = False
            print(f"FAIL selftest: 現場の語「{label}」が{'通った' if want else '落ちた'}")
    terms_ok, terms_n = selftest_terms()
    ok = ok and terms_ok
    total = 1 + len(BAD) + len(WARN_BAD) + len(TERM_CASES) + terms_n
    print(f"RESULT: {'PASS' if ok else 'FAIL'} check-ja --selftest ({total} 例)")
    return ok


def main(argv) -> int:
    if argv and argv[0] == "--terms":
        return terms_main(argv[1:])
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
        issues, warnings = check_all(src)
        if not report(name, issues, warnings):
            all_ok = False
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
