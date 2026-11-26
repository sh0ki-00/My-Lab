#!/usr/bin/env bash
# skills/ja-fluent/evals/blind-judge.sh — 見本の返答を、別コンテキストの判定 3 体に「人の文か」を読ませて数える（仕様書 R-20261113-01 の C-07）。
# 使い方: blind-judge.sh prepare <出力先>                 判定に渡す 1 枚（judge-packet.md）を書く。直す前と後の 40 件を混ぜ、どちらかは伏せる
#         blind-judge.sh collect <票1> <票2> <票3>        判定 3 体の返事（1 行「J01<TAB>人|AI<TAB>AI らしい所」）を votes.tsv に写す
#         blind-judge.sh [score] [--min 18] [--record <md>]  votes.tsv を数える。直した後の 20 件のうち、2 体以上が「人」と読んだ件が --min 以上で PASS
#         blind-judge.sh --selftest
# 判定の回し方は skills/secretary/evals/restatement-run.sh と同じ。packet を書き、判定 3 体（Claude Code では general-purpose の
#   サブエージェント 3 つ、Cursor では新しいチャット 3 つ）に packet だけを渡し、返事を collect に渡す。判定者は見本の出どころを知らない。
# 見本は skills/secretary/evals/answers/（cases.tsv、before/<id>.txt、after/<id>.txt）。票は evals/judge/votes.tsv。
# 直す前の 20 件の票は、判定が甘すぎないかの目安として数え、WARN の行で出す（合否には数えない）。
# 出力: FAIL/WARN の行と RESULT: PASS|FAIL blind-judge (人 n/20 …)。FAIL なら終了コード 1。
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
HERE="$(cd "$(dirname "$0")" && pwd -P)" || exit 1
ANSWERS="${BLIND_JUDGE_ANSWERS:-$HERE/../../secretary/evals/answers}"
VOTES="${BLIND_JUDGE_VOTES:-$HERE/judge/votes.tsv}"
exec python3 -I - "$ANSWERS" "$VOTES" "$@" <<'PY'
import contextlib
import datetime
import io
import pathlib
import random
import re
import sys
import tempfile

SEED = "blind-judge-v1"
INSTRUCTION = """# 返答の判定

下の {n} 件は、仕事の依頼に対する日本語の返答です。書き手が人か AI かは、件ごとに伏せてあります。
1 件ずつ、文だけを読んで、人が書いた文か AI が書いた文かを判定してください。中身の正しさは見ません。
迷ったら、職場で同僚から届いた返事として自然に読めるかで決めてください。

返事は、1 件 1 行で、タブ区切りの 3 列だけを書いてください。前置きや説明は要りません。
1 列目は番号（J01 など）、2 列目は「人」か「AI」、3 列目は AI らしいと感じた所を 30 字以内で書きます（無ければ -）。

"""


def load_samples(root):
    """{key: (依頼, 本文)}。key は before/01 や after/01。"""
    root = pathlib.Path(root)
    cases = {}
    for line in (root / "cases.tsv").read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        cells = line.split("\t")
        cases[cells[0].strip()] = cells[1].strip()
    out = {}
    for side in ("before", "after"):
        for cid, req in cases.items():
            f = root / side / f"{cid}.txt"
            if f.exists():
                text = re.sub(r"\s*<!--.*?-->", "", f.read_text(encoding="utf-8")).strip()
                out[f"{side}/{cid}"] = (req, text)
    return cases, out


def order(keys):
    """見本の key を、決まった種で混ぜた順に並べ、J01 からの番号を振る。"""
    ks = sorted(keys)
    random.Random(SEED).shuffle(ks)
    return {f"J{i:02d}": k for i, k in enumerate(ks, 1)}


def prepare(root, out_dir):
    _cases, samples = load_samples(root)
    ids = order(samples)
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    body = [INSTRUCTION.format(n=len(ids))]
    for jid, key in ids.items():
        req, text = samples[key]
        body.append(f"## {jid}\n\n依頼: 「{req}」\n\n```text\n{text}\n```\n")
    (out_dir / "judge-packet.md").write_text("\n".join(body), encoding="utf-8")
    print(f"judge-packet.md を {out_dir} に書いた（見本 {len(ids)} 件。どちらの組かは packet に書いていない）")
    return 0


def parse_reply(text):
    """判定 1 体の返事から {J01: (人|AI, 指摘)} を読む。区切りはタブか、続く空白 2 つ以上か「|」。"""
    got = {}
    for line in text.splitlines():
        cells = [c.strip() for c in re.split(r"\t|\s{2,}|\|", line.strip().strip("|")) if c.strip()]
        if len(cells) >= 2 and re.fullmatch(r"J\d{2}", cells[0]) and cells[1] in ("人", "AI"):
            got[cells[0]] = (cells[1], (cells[2] if len(cells) > 2 else "-").replace("\t", " "))
    return got


def collect(root, votes_path, replies):
    _cases, samples = load_samples(root)
    ids = order(samples)
    rows = []
    for n, f in enumerate(replies, 1):
        got = parse_reply(pathlib.Path(f).read_text(encoding="utf-8"))
        lack = [j for j in ids if j not in got]
        if lack:
            print(f"FAIL collect 判定{n} の返事に {len(lack)} 件の判定が無い（{', '.join(lack[:5])} など）")
            return 1
        for jid, key in ids.items():
            # 5 列目の印は、判定者の言葉の引用（言い換え語の名指しを含む）を、言い換えの検査が数えないためのもの
            rows.append(f"{key}\t判定{n}\t{got[jid][0]}\t{got[jid][1]}\t<!-- ja-ok -->")
    head = (f"# 判定 3 体の票（{datetime.date.today().isoformat()}）。別コンテキストの判定者が、直す前と後を混ぜた {len(ids)} 件を、どちらの組かを伏せて読んだ。\n"
            "# 列: 見本（before/<id> か after/<id>） / 判定者 / 人|AI / AI らしい所（判定者の言葉のまま） / 印。packet は blind-judge.sh prepare で同じ順に作り直せる。\n")
    pathlib.Path(votes_path).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(votes_path).write_text(head + "\n".join(rows) + "\n", encoding="utf-8")
    print(f"{votes_path} に {len(rows)} 票を書いた")
    return 0


def tally(root, votes_path):
    """{key: [(判定者, 人|AI, 指摘), ...]} と見本の一覧を返す。"""
    cases, samples = load_samples(root)
    votes = {}
    p = pathlib.Path(votes_path)
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            c = line.split("\t")
            if len(c) >= 3:
                votes.setdefault(c[0].strip(), []).append((c[1].strip(), c[2].strip(), c[3].strip() if len(c) > 3 else "-"))
    return cases, samples, votes, p.exists()


def score(root, votes_path, minimum, record):
    cases, samples, votes, exists = tally(root, votes_path)
    fails = warns = 0
    after = sorted(k for k in samples if k.startswith("after/"))
    before = sorted(k for k in samples if k.startswith("before/"))
    if not exists:
        print(f"FAIL votes [C-07] {votes_path} が無い。prepare で packet を作り、判定 3 体の返事を collect に渡す")
        print(f"RESULT: FAIL blind-judge (人 0/{len(after)}、票なし)")
        return 1
    if len(after) != 20:
        print(f"FAIL samples [C-07] 直した後の見本が {len(after)} 件（20 件要る）")
        fails += 1
    human = 0
    lines = []
    for k in after + before:
        v = votes.get(k, [])
        hv = sum(1 for _j, h, _w in v if h == "人")
        if len(v) < 3:
            print(f"FAIL {k} [C-07] 票が {len(v)} つ。判定 3 体の票を揃える")
            fails += 1
            continue
        if k.startswith("after/"):
            if hv >= 2:
                human += 1
            else:
                notes = "、".join(w for _j, h, w in v if h == "AI" and w != "-")
                print(f"WARN {k} [C-07] 人と読んだのが {hv}/3 体。指摘: {notes or '-'}")
                warns += 1
        lines.append((k, hv, len(v), "；".join(w for _j, h, w in v if h == "AI" and w != "-") or "-"))
    ai_before = sum(1 for k in before if sum(1 for _j, h, _w in votes.get(k, []) if h == "AI") >= 2)
    if before and ai_before * 2 < len(before):
        print(f"WARN before [目安] 直す前の見本で AI と読まれたのが {ai_before}/{len(before)} 件。判定が甘い見込み")
        warns += 1
    if human < minimum:
        print(f"FAIL votes [C-07] 2 体以上に人と読まれた直した後の見本が {human}/{len(after)} 件。{minimum} 件以上にする")
        fails += 1
    ok = fails == 0
    result = (f"RESULT: {'PASS' if ok else 'FAIL'} blind-judge (人 {human}/{len(after)}、"
              f"直す前を AI と読んだ {ai_before}/{len(before)}、FAIL {fails}、WARN {warns})")
    print(result)
    if record:
        md = ["# 判定 3 体の記録（C-07）", "",
              "> **3 行でわかる要約**",
              f"> 1. 直した後の見本 {len(after)} 件のうち、判定 3 体の 2 体以上が人の文と読んだのは {human} 件です。",
              f"> 2. 直す前の見本は {len(before)} 件のうち {ai_before} 件が、2 体以上に AI の文と読まれました。",
              f"> 3. 目標は {minimum} 件で、合否は {'PASS' if ok else 'FAIL'} でした。", "",
              "## 1. 結果", "",
              f"票は `{votes_path}` にあり、`blind-judge.sh score` で数え直せます。直す前と後を混ぜた 1 枚を、どちらの組かを伏せて判定者に渡しました。", "",
              "```text", result, "```", "",
              "## 2. 見本ごとの票", "",
              "AI らしいと言われた所は、判定者の言葉のままです。", "",
              "| 見本 | 人と読んだ数 | AI らしいと言われた所 |", "|---|---|---|"]
        md += [f"| {k} | {hv}/{n} | {w.replace('|', '｜')} | <!-- ja-ok -->" for k, hv, n, w in lines]
        pathlib.Path(record).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(record).write_text("\n".join(md) + "\n", encoding="utf-8")
    return 0 if ok else 1


def selftest():
    ok = True
    with tempfile.TemporaryDirectory() as t:
        root = pathlib.Path(t) / "answers"
        (root / "before").mkdir(parents=True)
        (root / "after").mkdir()
        rows = ["# 見本"]
        for i in range(1, 21):
            cid = f"{i:02d}"
            rows.append(f"{cid}\t依頼 {cid}\t場面\t-")
            (root / "before" / f"{cid}.txt").write_text(f"承知しました。\n見本 {cid} の前です。\n", encoding="utf-8")
            (root / "after" / f"{cid}.txt").write_text(f"見本 {cid} の後の文です。\n", encoding="utf-8")
        (root / "cases.tsv").write_text("\n".join(rows) + "\n", encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            prepare(root, pathlib.Path(t) / "pk")
        packet = (pathlib.Path(t) / "pk" / "judge-packet.md").read_text(encoding="utf-8")
        if packet.count("## J") != 40 or "before" in packet or "after" in packet:
            ok = False
            print("FAIL selftest blind-judge: packet が 40 件でないか、組の名前が見える")
        ids = order(load_samples(root)[1])
        def reply(human_after):
            return "\n".join(f"{j}\t{'人' if (k.startswith('after/') and int(k[-2:]) <= human_after) else 'AI'}\t-" for j, k in ids.items())
        reps = []
        for n, h in enumerate((20, 18, 17), 1):
            f = pathlib.Path(t) / f"r{n}.txt"
            f.write_text(reply(h), encoding="utf-8")
            reps.append(f)
        votes = pathlib.Path(t) / "votes.tsv"
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc1 = collect(root, votes, reps)
            rc2 = score(root, votes, 18, pathlib.Path(t) / "judge.md")
        if rc1 or rc2:
            ok = False
            print("FAIL selftest blind-judge: 2 体以上が人と読んだ 18 件で通らない\n" + buf.getvalue())
        with contextlib.redirect_stdout(io.StringIO()):
            rc = score(root, votes, 19, None)
        if rc == 0:
            ok = False
            print("FAIL selftest blind-judge: 18 件で --min 19 が通った")
        (pathlib.Path(t) / "r3.txt").write_text(reply(17).split("\n", 1)[1], encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            rc = collect(root, votes, reps)
        if rc == 0:
            ok = False
            print("FAIL selftest blind-judge: 判定の欠けた返事を collect が受けた")
        if parse_reply("| J07 | 人 | - |\nJ08  AI  前置き\n") != {"J07": ("人", "-"), "J08": ("AI", "前置き")}:
            ok = False
            print("FAIL selftest blind-judge: 表と空白区切りの返事を読めない")
        with contextlib.redirect_stdout(io.StringIO()):
            rc = score(root, pathlib.Path(t) / "none.tsv", 18, None)
        if rc == 0:
            ok = False
            print("FAIL selftest blind-judge: 票が無いのに通った")
    print(f"RESULT: {'PASS' if ok else 'FAIL'} blind-judge --selftest (6 例)")
    return 0 if ok else 1


def main(argv):
    root, votes, args = argv[0], argv[1], list(argv[2:])
    if args and args[0] == "--selftest":
        return selftest()
    if args and args[0] in ("-h", "--help"):
        print("使い方: blind-judge.sh prepare <出力先> | collect <票1> <票2> <票3> | [score] [--min 18] [--record <md>] | --selftest")
        return 2
    if args and args[0] == "prepare":
        if len(args) < 2:
            print("使い方: blind-judge.sh prepare <出力先>")
            return 2
        return prepare(root, args[1])
    if args and args[0] == "collect":
        if len(args) != 4:
            print("使い方: blind-judge.sh collect <票1> <票2> <票3>")
            return 2
        return collect(root, votes, args[1:])
    if args and args[0] == "score":
        args = args[1:]
    minimum, record = 18, None
    while args:
        if args[0] == "--min" and len(args) > 1:
            minimum = int(args[1]); args = args[2:]
        elif args[0] == "--record" and len(args) > 1:
            record = args[1]; args = args[2:]
        else:
            print(f"使い方: 知らない引数 {args[0]}")
            return 2
    return score(root, votes, minimum, record)


sys.exit(main(sys.argv[1:]))
PY
