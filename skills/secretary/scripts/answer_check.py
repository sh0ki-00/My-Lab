#!/usr/bin/env python3
"""answer_check — 依頼者への返答（チャットに出す文）の検査。answer-check.sh の本体。

使い方: answer_check.py <ファイル>... [--vocab <語彙表.md>]   /   answer_check.py --selftest
見ること（決まりは skills/secretary/references/answer-style.md）:
  FAIL: 受付の定型句（承知しました、「…」の件）、前置きと締めの常套句、RESULT の行、受付番号・役割の数・「仮置き」の語、
        自作の言い換え語（戻し先は WORDS の表）、1 行 1 文の縦並び 3 行以上、同じ文末の 4 連続、100 字を超える文
  WARN: 言い換えの疑いのある 1 字の語（印・輪・門）、語彙表の語への括弧説明、括弧説明が 100 字に 1 つを超える、
        同じ文末の 3 連続、25 字以下の短い文の 3 連続、60 字を超える文
見ないもの: 3 つのバッククォートの囲みの中（RESULT の行だけは囲みの中も見る）、バッククォートで囲んだ語、注釈（<!-- -->。ja-ok の印も数えない）。
出力: FAIL/WARN <ファイル>:<行> [<決まり>] <内容>、ファイルごとに RESULT: PASS|FAIL answer-check <ファイル> (FAIL n、WARN m)。
      1 件でも FAIL なら終了コード 1。WARN だけなら 0。
"""
import pathlib
import re
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
VOCAB = HERE.parent / "references" / "vocabulary.md"

# 受付の定型句と、前置き・締めの常套句（FAIL）
STOCK = [
    (re.compile(r"承知(しました|いたしました)|かしこまりました|了解(しました|です)"), "受付の定型句。言い直しか答えで始める"),
    (re.compile(r"^「[^」]{1,60}」の件"), "依頼の原文の繰り返し。対象・目的・出す形で言い直す"),
    (re.compile(r"以下(に示します|のとおりです|にまとめます)|以上です|お役に立てれば|いかがでしょうか|お気軽に"),  # <!-- ja-ok -->
     "前置きか締めの常套句。消す"),
]
# 受付の文言（FAIL）。依頼者には要らない社内の印
INTAKE = [
    (re.compile(r"R-\d{8}-\d{2}|受付番号"), "受付番号を書かない"),
    (re.compile(r"\d+ ?つの役割|役割 ?\d+ ?つ"), "役割の数を書かない"),
    (re.compile(r"仮置き"), "「仮置き」の語を書かない。「〜と見て進めます」と言う"),  # <!-- ja-ok -->
]
# 自作の言い換え語と戻し先。(正規表現, 戻し先, 重さ)。1 字の語は誤りの当たりがあるので WARN にする
WORDS = [
    (r"台本", "スクリプト", "FAIL"),  # <!-- ja-ok -->
    (r"接続口", "hooks", "FAIL"),  # <!-- ja-ok -->
    (r"関所", "承認（承認 1・承認 2）", "FAIL"),  # <!-- ja-ok -->
    (r"写した先", "移した先（deploy.sh で一式を移したプロジェクト）", "FAIL"),  # <!-- ja-ok -->
    (r"索引", "インデックス", "FAIL"),  # <!-- ja-ok -->
    (r"枝分か?れ", "分岐", "FAIL"),  # <!-- ja-ok -->
    (r"(?<!分)枝(?!番|豆|葉|刈り|分か?れ)", "ブランチ", "FAIL"),  # <!-- ja-ok -->
    (r"口座", "アカウント", "FAIL"),  # <!-- ja-ok -->
    (r"合言葉", "パスワード", "FAIL"),  # <!-- ja-ok -->
    (r"入れ物", "置き場", "FAIL"),  # <!-- ja-ok -->
    (r"(?<![矢目調捺刻押消旗極])印(?![刷鑑象字章税])", "最後に通った時刻（記録のファイル）", "WARN"),  # <!-- ja-ok -->
    (r"(?<![車指年一花両内腕首竹])輪(?![郭切廻番ゴ])", "ループ", "WARN"),  # <!-- ja-ok -->
    (r"(?<![専部入名正校登閘])門(?![限番下前戸外])", "検査", "WARN"),  # <!-- ja-ok -->
]
WORDS = [(re.compile(p), to, lv) for p, to, lv in WORDS]
RESULT_LINE = re.compile(r"(^|`)\s*RESULT:")
PAREN = re.compile(r"（[^（）]{2,}）")
SENT_END = re.compile(r"(?<=[。！？])")
MAX_SENT, WARN_SENT, SHORT = 100, 60, 25


def load_vocab(path):
    """語彙表（.md の表）の 1 列目を語として読む。見出しの行と区切りの行は飛ばす。"""
    words = []
    try:
        lines = pathlib.Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return words
    for line in lines:
        if not line.startswith("|") or re.match(r"^\|\s*-", line):
            continue
        cell = line.strip("|").split("|")[0].strip().strip("`")
        if cell and cell != "語":
            words.append(cell)
    return sorted(set(words), key=len, reverse=True)


def clean_lines(text):
    """(行番号, 検査する文字列) を返す。囲みの中は空にし、注釈とバッククォートの中を消す。"""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    out, fence = [], False
    for no, line in enumerate(text.splitlines(), 1):
        if re.match(r"^\s*```", line):
            fence = not fence
            out.append((no, "", line))
            continue
        out.append((no, "" if fence else line, line))
    return out


def ending(s):
    """文末の 2 字（句点の前）。「です」「ます」「した」のように比べる。"""
    core = re.sub(r"[。！？」）\s]+$", "", s)
    return core[-2:] if len(core) >= 2 else core


def plain(s):
    """字数を数える形。バッククォートの中と空白を除く。"""
    return re.sub(r"\s", "", re.sub(r"`[^`]*`", "", s))


def check(text, vocab):
    """(FAIL の一覧, WARN の一覧) を返す。要素は (行, 決まり, 内容)。"""
    fails, warns = [], []
    rows = clean_lines(text)
    sents = []        # (行, 文)
    run_single = 0
    for no, line, raw in rows:
        if RESULT_LINE.search(raw):  # 囲みの中でも、貼れば貼ったことになる
            fails.append((no, "RESULT の行", "検査の結果の行を貼らない。検査が通ったことと記録のパスを 1 文で書く"))
        body = re.sub(r"`[^`]*`", "", line)
        if not body.strip():
            run_single = 0
            continue
        for rx, why in STOCK:
            if rx.search(body.strip()):
                fails.append((no, "定型句", why))
        for rx, why in INTAKE:
            if rx.search(body):
                fails.append((no, "受付の文言", why))
        for rx, to, lv in WORDS:
            m = rx.search(body)
            if m:
                (fails if lv == "FAIL" else warns).append((no, "言い換え語", f"「{m.group(0)}」は「{to}」に戻す"))
        for w in vocab:
            if re.search(re.escape(w) + r"（", body):
                warns.append((no, "語彙表の語", f"「{w}」は依頼者の語なので、括弧で説明しない"))
        is_prose = not re.match(r"^\s*([-*+>|#]|\d+[.)]|[（(]\d+[）)])", body)
        parts = [p for p in SENT_END.split(body.strip()) if p.strip()]
        if is_prose:
            for p in parts:
                sents.append((no, p))
            if len(parts) == 1 and body.strip().endswith(("。", "？", "！")):
                run_single += 1
                if run_single == 3:
                    fails.append((no, "縦並び", "1 行 1 文を 3 行以上縦に並べている。2〜4 文を 1 つの段落にする"))
            else:
                run_single = 0
        else:
            run_single = 0
    all_chars = sum(len(plain(s)) for _, s in sents)
    parens = sum(len(PAREN.findall(s)) for _, s in sents)
    if parens and parens * 100 > max(all_chars, 1):
        warns.append((sents[0][0] if sents else 1, "括弧説明",
                      f"括弧説明が {parens} つで、本文 {all_chars} 字に対して多い（100 字に 1 つまで）"))
    same, short = 1, 0
    for i, (no, s) in enumerate(sents):
        n = len(plain(s))
        if n > MAX_SENT:
            fails.append((no, "長い文", f"{n} 字の文。100 字を超える文は切る"))
        elif n > WARN_SENT:
            warns.append((no, "長い文", f"{n} 字の文。60 字以内にする"))
        if i and ending(s) and ending(s) == ending(sents[i - 1][1]):
            same += 1
            if same == 3:
                warns.append((no, "同じ文末", f"「{ending(s)}」で終わる文が 3 つ続く"))
            if same == 4:
                fails.append((no, "同じ文末", f"「{ending(s)}」で終わる文が 4 つ続く"))
        else:
            same = 1
        short = short + 1 if n <= SHORT else 0
        if short == 3:
            warns.append((no, "短い文", "25 字以下の文が 3 つ続く。理由や条件でつないで 1 文にする"))
    return fails, warns


def run_file(path, vocab):
    try:
        text = pathlib.Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        print(f"FAIL {path} [読めない] {e.__class__.__name__}")
        print(f"RESULT: FAIL answer-check {path} (FAIL 1、WARN 0)")
        return 1
    fails, warns = check(text, vocab)
    for no, rule, why in sorted(fails):
        print(f"FAIL {path}:{no} [{rule}] {why}")
    for no, rule, why in sorted(warns):
        print(f"WARN {path}:{no} [{rule}] {why}")
    ok = not fails
    print(f"RESULT: {'PASS' if ok else 'FAIL'} answer-check {path} (FAIL {len(fails)}、WARN {len(warns)})")
    return 0 if ok else 1


# 自己試験。(名前, 本文, 期待: "PASS"（FAIL も WARN も 0）か、当たる決まりの名前と重さ)
GOOD = ("先週 API が遅かったのは、注文一覧の検索でインデックスが効いていなかったためです。"
        "11 月 3 日から 7 日のログ 12 万行を見ると、遅い呼び出しの 9 割が期間指定の一覧取得でした。\n\n"
        "インデックスを 1 本足せば、p95 は 1 秒を切る見込みで、作業は 30 分ほどです。"
        "進めてよければ、足してから同じ条件で測り直します。\n")
SELF = [
    ("正例", GOOD, None),
    ("承知しました", "「ログ見て」の件、承知しました。" + GOOD, ("定型句", "FAIL")),
    ("RESULT の行", GOOD + "RESULT: PASS check-file tmp/flow/a.md\n", ("RESULT の行", "FAIL")),
    ("受付番号", GOOD + "受付は R-20261113-01 です。記録に残しました。\n", ("受付の文言", "FAIL")),
    ("仮置き", "目的は原因探しと仮置きして、ログを読みます。\n", ("受付の文言", "FAIL")),  # <!-- ja-ok -->
    ("言い換え語", "写した先の tmp/ に置きました。続けて検証も回します。\n", ("言い換え語", "FAIL")),  # <!-- ja-ok -->
    ("縦並び", "原因はインデックスです。\n遅いのは一覧です。\n直すと速くなります。\n", ("縦並び", "FAIL")),
    ("語彙表の語", "p95（100 回のうち 95 回が収まる値）は 4.2 秒でした。進めてよければ直します。\n", ("語彙表の語", "WARN")),
    ("同じ文末 4", "原因は一覧です。条件は期間です。件数は多いです。直し方は 1 つです。\n", ("同じ文末", "FAIL")),
    ("100 字超", "あ" * 101 + "。\n", ("長い文", "FAIL")),
    ("囲みの中は見ない", "結果は記録に残しました。続けて直します。\n```\n承知しました\n```\n", None),
    ("囲みの中の RESULT の行", "結果は記録に残しました。続けて直します。\n```\nRESULT: PASS x\n```\n", ("RESULT の行", "FAIL")),
]


def selftest():
    ok = True
    vocab = load_vocab(VOCAB)
    if "p95" not in vocab or "インデックス" not in vocab:
        ok = False
        print(f"FAIL selftest answer-check: 語彙表 {VOCAB} から p95 とインデックスを読めない")
    for name, text, want in SELF:
        fails, warns = check(text, vocab)
        if want is None:
            if fails or warns:
                ok = False
                print(f"FAIL selftest answer-check: 「{name}」が通らない（{fails + warns}）")
            continue
        rule, lv = want
        hit = any(r == rule for _, r, _ in (fails if lv == "FAIL" else warns))
        if not hit:
            ok = False
            print(f"FAIL selftest answer-check: 「{name}」で {lv} [{rule}] が出ない（FAIL {fails}、WARN {warns}）")
    with tempfile.TemporaryDirectory() as t:
        p = pathlib.Path(t) / "bad.txt"
        p.write_bytes(b"\xff\xfe")
        import io, contextlib
        with contextlib.redirect_stdout(io.StringIO()):
            rc = run_file(p, vocab)
        if rc != 1:
            ok = False
            print("FAIL selftest answer-check: 読めないファイルで終了コードが 1 にならない")
    print(f"RESULT: {'PASS' if ok else 'FAIL'} answer-check --selftest ({len(SELF) + 1} 例)")
    return 0 if ok else 1


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 2
    if argv[0] == "--selftest":
        return selftest()
    args = list(argv)
    vocab_path = VOCAB
    if "--vocab" in args:
        i = args.index("--vocab")
        if i + 1 >= len(args):
            print("使い方: answer_check.py <ファイル>... [--vocab <語彙表.md>]")
            return 2
        vocab_path = pathlib.Path(args[i + 1])
        del args[i:i + 2]
    vocab = load_vocab(vocab_path)
    rc = 0
    for f in args:
        rc |= run_file(f, vocab)
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
