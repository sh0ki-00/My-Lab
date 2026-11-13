#!/usr/bin/env python3
"""restatement_eval — 言い直しの評価（仕様書 R-20261113-01 の C-01・C-02）。

使い方: restatement_eval.py prepare <出力先ディレクトリ> [--dir <評価セットのディレクトリ>]
        restatement_eval.py score [--dir <評価セットのディレクトリ>] [--min <一致の最少件数>]
        restatement_eval.py --selftest
prepare: cases.tsv から 2 つの packet を書く。restater-packet.md は原文と文脈だけ（言い直しを書く側に渡す）。
         judge-packet.md は原文・文脈・意図・出力（outputs/<id>.md）を並べる（判定 3 体に渡す）。
score:   outputs/<id>.md を機械で見る（C-02: 言い直し 3 行以内、候補 3 つまで、候補を並べたら 1 つを選ぶ、問い 1 つまで）。
         votes.tsv（id / 判定者 / 一致 1|0 / 候補にある 1|0 / 理由）の多数決で一致を数え、--min（既定 18）以上なら PASS。
出力: FAIL/WARN の行と RESULT: PASS|FAIL restatement-run (一致 n/N、問いの超過 m)。1 件でも FAIL なら終了コード 1。
"""
import pathlib
import re
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
CAND = re.compile(r"^[（(]\d+[）)]")
MAX_LINES, MAX_CANDS, MAX_Q = 3, 3, 1


def read_tsv(path, ncols):
    rows = []
    for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        cells = line.split("\t")
        if len(cells) < ncols:
            raise ValueError(f"{path.name}:{no} 列が {len(cells)} つ（{ncols} つ要る）")
        rows.append([c.strip() for c in cells[:ncols]])
    return rows


def analyze(text):
    """出力 1 件を機械で見る。(FAIL の一覧, WARN の一覧, 言い直しの行数, 候補の数, 問いの数) を返す。"""
    lines = [l.rstrip() for l in text.strip().splitlines()]
    fails, warns = [], []
    if not lines or not "".join(lines).strip():
        return ["出力が空"], warns, 0, 0, 0
    first_cand = next((i for i, l in enumerate(lines) if CAND.match(l.strip())), None)
    if first_cand is None:
        para = []
        for l in lines:
            if not l.strip():
                break
            para.append(l)
        restate = para
    else:
        restate = [l for l in lines[:first_cand] if l.strip()]
    cands = [l for l in lines if CAND.match(l.strip())]
    body = "\n".join(lines)
    q = body.count("？") + body.count("?") + (1 if len(cands) >= 2 else 0)
    if len(restate) > MAX_LINES:
        fails.append(f"言い直しが {len(restate)} 行。{MAX_LINES} 行以内にする")
    if len(cands) > MAX_CANDS:
        fails.append(f"候補が {len(cands)} つ。{MAX_CANDS} つまでにし、多ければ目的だけを 1 問で聞く")
    elif len(cands) >= 2 and not re.search(r"と見て|と読んで|と受け取って進め", body):
        fails.append("候補を並べたのに、1 つを「(n) と見て進めます」と選んでいない")
    if q > MAX_Q:
        fails.append(f"問いが {q} つ。{MAX_Q} つまでにする")
    if re.search(r"承知しました|の件、|かしこまりました|了解しました", body):
        warns.append("受付の定型句（承知しました、の件）が残っている")
    if re.search(r"^RESULT:", body, re.M):
        warns.append("RESULT の行が返答に入っている")
    return fails, warns, len(restate), len(cands), q


def prepare(out_dir, case_dir):
    cases = read_tsv(case_dir / "cases.tsv", 5)
    out_dir.mkdir(parents=True, exist_ok=True)
    r = ["# 言い直しを書く側に渡す依頼の一覧", "",
         "列は id、依頼の原文、文脈（直前の話題）です。社長の意図はこの一覧に無く、原文と文脈だけから言い直しを書きます。", "",
         "| id | 依頼の原文 | 文脈 |", "|---|---|---|"]
    j = ["# 判定 3 体に渡す一覧", "",
         "列は id、依頼の原文、文脈、社長の意図、言い直しの出力です。出力の読み方（仮置きに選んだ候補、または 1 つの読み方）が意図と合うかを判定します。", "",
         "| id | 依頼の原文 | 文脈 | 社長の意図 | 出力 |", "|---|---|---|---|---|"]
    missing = 0
    for cid, text, ctx, intent, _shape in cases:
        r.append(f"| {cid} | {text} | {ctx} |")
        f = case_dir / "outputs" / f"{cid}.md"
        out = f.read_text(encoding="utf-8").strip().replace("\n", "<br>").replace("|", "｜") if f.exists() else "（まだ無い）"
        if not f.exists():
            missing += 1
        j.append(f"| {cid} | {text} | {ctx} | {intent} | {out} |")
    (out_dir / "restater-packet.md").write_text("\n".join(r) + "\n", encoding="utf-8")
    (out_dir / "judge-packet.md").write_text("\n".join(j) + "\n", encoding="utf-8")
    print(f"restater-packet.md と judge-packet.md を {out_dir} に書いた（依頼 {len(cases)} 件、出力の無い件 {missing}）")
    return 0


def score(case_dir, minimum):
    cases = read_tsv(case_dir / "cases.tsv", 5)
    ids = [c[0] for c in cases]
    fail_n, warn_n, over_q = 0, 0, 0
    for cid, text, _ctx, _intent, _shape in cases:
        f = case_dir / "outputs" / f"{cid}.md"
        if not f.exists():
            print(f"FAIL {cid} [出力] outputs/{cid}.md が無い")
            fail_n += 1
            continue
        fails, warns, nl, nc, q = analyze(f.read_text(encoding="utf-8"))
        if q > MAX_Q:
            over_q += 1
        for m in fails:
            print(f"FAIL {cid} [C-02] {m}（「{text}」）")
            fail_n += 1
        for m in warns:
            print(f"WARN {cid} [返答の形] {m}（「{text}」）")
            warn_n += 1
    votes_path = case_dir / "votes.tsv"
    agree = 0
    if not votes_path.exists():
        print("FAIL votes [C-01] votes.tsv が無い。判定 3 体の票を置く")
        fail_n += 1
    else:
        votes = {}
        for cid, judge, ok, _incl, _why in read_tsv(votes_path, 5):
            votes.setdefault(cid, {})[judge] = ok == "1"
        for cid in ids:
            v = votes.get(cid, {})
            if len(v) < 3:
                print(f"FAIL {cid} [C-01] 票が {len(v)} つ。判定 3 体の票を揃える")
                fail_n += 1
                continue
            if sum(v.values()) * 2 > len(v):
                agree += 1
        if agree < minimum:
            print(f"FAIL votes [C-01] 一致が {agree}/{len(ids)} 件。{minimum} 件以上にする（言い直しの決まりを直して書き直す）")
            fail_n += 1
    ok = fail_n == 0
    print(f"RESULT: {'PASS' if ok else 'FAIL'} restatement-run (一致 {agree}/{len(ids)}、問いの超過 {over_q}、FAIL {fail_n}、WARN {warn_n})")
    return 0 if ok else 1


SELF_CASES = ("# 見本\n"
              "01\t注文データを調査して\t昨日のエラーの話\t注文が落ちた原因を探す\t-\n"
              "02\tチェックリスト作って\t明日がリリース\tリリース前の確認項目\tチェックリスト\n")
GOOD_01 = ("「注文データを調査して」は、こう受け取りました。対象は注文のデータで、出す形は分析の記録 1 枚です。目的は、次の 3 つのどれかだと思います。\n"
           "(1) 先月の注文の件数と金額の推移を集計する\n(2) 注文が落ちた原因を探す\n(3) 注文テーブルの品質を点検する\n"
           "昨日話していたエラーの続きだと思うので、(2) と見て進めます。違えば番号で止めてください。\n")
GOOD_02 = "「チェックリスト作って」は、明日のリリースの前に確認する項目を、チェックボックスの .md で出す依頼と受け取りました。項目を書いたら、同じ形でここにも貼ります。\n"
BAD_FOUR = GOOD_01.replace("(3) 注文テーブルの品質を点検する\n", "(3) 注文テーブルの品質を点検する\n(4) 返金の件数を数える\n")
BAD_TWO_Q = GOOD_02.rstrip("\n") + " 期間は先月でよいですか？ 形式は表でもよいですか？\n"
BAD_NO_PICK = GOOD_01.replace("昨日話していたエラーの続きだと思うので、(2) と見て進めます。違えば番号で止めてください。\n", "どれにしますか。\n")
BAD_LONG = "対象は注文のデータです。\n目的は原因を探すことです。\n出す形は記録です。\n期間は先週です。\n違えば止めてください。\n"


def selftest():
    ok = True
    with tempfile.TemporaryDirectory() as tmp:
        d = pathlib.Path(tmp)
        (d / "outputs").mkdir()
        (d / "cases.tsv").write_text(SELF_CASES, encoding="utf-8")
        (d / "outputs" / "01.md").write_text(GOOD_01, encoding="utf-8")
        (d / "outputs" / "02.md").write_text(GOOD_02, encoding="utf-8")
        votes = "\n".join(f"{cid}\t判定{j}\t1\t1\t合う" for cid in ("01", "02") for j in (1, 2, 3)) + "\n"
        (d / "votes.tsv").write_text(votes, encoding="utf-8")
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = score(d, 2)
            prepare(d / "pk", d)
        if rc != 0 or not (d / "pk" / "judge-packet.md").exists():
            ok = False
            print("FAIL selftest restatement-run: 正例が落ちた\n" + buf.getvalue())
        for name, text, rule in (("候補 4 つ", BAD_FOUR, "候補が 4 つ"), ("問い 2 つ", BAD_TWO_Q, "問いが"),
                                 ("選ばない", BAD_NO_PICK, "選んでいない"), ("4 行", BAD_LONG, "行。")):
            fails, _w, _nl, _nc, _q = analyze(text)
            if not any(rule in m for m in fails):
                ok = False
                print(f"FAIL selftest restatement-run: 負例「{name}」が通った（検出: {fails}）")
        (d / "votes.tsv").write_text(votes.replace("01\t判定3\t1", "01\t判定3\t0").replace("01\t判定2\t1", "01\t判定2\t0"), encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            rc = score(d, 2)
        if rc == 0:
            ok = False
            print("FAIL selftest restatement-run: 一致 1/2 で --min 2 が通った")
    print(f"RESULT: {'PASS' if ok else 'FAIL'} restatement-run --selftest (7 例)")
    return 0 if ok else 1


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 2
    if argv[0] == "--selftest":
        return selftest()
    case_dir = HERE
    minimum = 18
    args = list(argv)
    if "--dir" in args:
        i = args.index("--dir")
        case_dir = pathlib.Path(args[i + 1])
        del args[i:i + 2]
    if "--min" in args:
        i = args.index("--min")
        minimum = int(args[i + 1])
        del args[i:i + 2]
    if args[0] == "prepare":
        if len(args) < 2:
            print("使い方: restatement_eval.py prepare <出力先ディレクトリ>")
            return 2
        return prepare(pathlib.Path(args[1]), case_dir)
    if args[0] == "score":
        return score(case_dir, minimum)
    print(__doc__.strip())
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
