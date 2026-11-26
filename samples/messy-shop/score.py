#!/usr/bin/env python3
"""score — messy-shop の 10 問の答えを、正答（answers/answers.json）と比べて採点する。

使い方:
  python3 score.py <答えの JSON> [--show] [--json] [--min N]
      答えの JSON は {"Q1": 数, …, "Q8": "YYYY-MM-DD", "Q9": [会員番号, 会員番号, 会員番号], "Q10": 数} の形。
      {"answers": {…}} のように 1 段包んであってもよい。問いごとに 正 か 誤 を出し、最後に RESULT: <正の数>/10 を出す。
      --show は正答も並べる（答える側には見せない）。--json は結果を JSON で出す。
      --min N は、正が N 問に届かなければ終了コード 1 にする（キャッチアップの効き目の試験 C-3 の線は 9）。
  python3 score.py --verify-db <DB のパス>
      build.py で作った DB に、answers.json の文を読むだけの接続で回す。正答の文が answer と同じか、
      別の道筋の文（alt）が誤差の内で合うか、コードの数え方の文（naive）が記録の値どおりで正答と合わないか、
      表の行の数が同じかを見る。1 つでも違えば終了コード 1。
  python3 score.py --selftest
      正答をそのまま渡すと 10 点、1 問だけ変えると 9 点になるかを、10 問それぞれで確かめる。
      数の書き方のゆれ（桁区切り、単位）、日付の書き方、一覧の順、誤差の境目、answers.json の形も見る。DB は使わない。
数の答えは整数か小数、または「1,234」「1234 円」のような文字でもよい。単位は 円・件・個・人 を外して読む。
日付は「2026-01-02」「2026/1/2」「2026年1月2日」を同じと見る。一覧は会員番号の整数の列で、順も比べる。
python3 の標準だけで動く。3.9 以上。
"""
import argparse
import datetime as dt
import json
import pathlib
import re
import sqlite3
import sys
import unicodedata

HERE = pathlib.Path(__file__).resolve().parent
ANSWERS = HERE / "answers" / "answers.json"
UNITS = ("円", "件", "個", "人")
NUM = re.compile(r"[-+]?\d+(?:\.\d+)?")
DATE = re.compile(r"(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})日?")
FORMS = ("number", "text", "list")


def load_answers(path=ANSWERS):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def to_number(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v
    if not isinstance(v, str):
        return None
    s = unicodedata.normalize("NFKC", v).strip().replace(",", "").replace(" ", "")
    for u in UNITS:
        if s.endswith(u):
            s = s[: -len(u)]
            break
    if not NUM.fullmatch(s):
        return None
    return float(s) if "." in s else int(s)


def to_date(v):
    if not isinstance(v, str):
        return None
    m = DATE.fullmatch(unicodedata.normalize("NFKC", v).strip())
    if not m:
        return None
    try:
        return dt.date(*(int(x) for x in m.groups())).isoformat()
    except ValueError:
        return None


def to_list(v):
    if isinstance(v, str):
        v = [x for x in re.split(r"[,、\s]+", unicodedata.normalize("NFKC", v).strip()) if x]
    if not isinstance(v, list):
        return None
    out = []
    for x in v:
        n = to_number(x)
        if n is None or (isinstance(n, float) and not n.is_integer()):
            return None
        out.append(int(n))
    return out


def limit_of(spec):
    tol = spec.get("tolerance") or {}
    if "abs" in tol:
        return float(tol["abs"])
    return abs(spec["answer"]) * float(tol.get("rel", 0))


def judge(spec, given):
    """(正か, 理由) を返す。"""
    if given is None:
        return False, "答えが無い"
    form, want = spec["form"], spec["answer"]
    if form == "number":
        n = to_number(given)
        if n is None:
            return False, "数として読めない"
        if abs(n - want) <= limit_of(spec) + 1e-9:
            return True, ""
        return False, "正答と合わない"
    if form == "text":
        if spec.get("normalize") == "date":
            g = to_date(given)
            if g is None:
                return False, "日付として読めない"
        else:
            g = unicodedata.normalize("NFKC", str(given)).strip()
        return (True, "") if g == want else (False, "正答と合わない")
    if form == "list":
        g = to_list(given)
        if g is None:
            return False, "一覧として読めない"
        same = g == want if spec.get("ordered") else sorted(g) == sorted(want)
        return (True, "") if same else (False, "正答と合わない。順も比べる" if spec.get("ordered") else "正答と合わない")
    return False, "answers.json の形が分からない: " + str(form)


def unwrap(sub):
    if isinstance(sub, dict) and isinstance(sub.get("answers"), dict):
        sub = sub["answers"]
    if not isinstance(sub, dict):
        return {}
    return {str(k).strip().upper(): v for k, v in sub.items()}


def grade(questions, submission):
    sub = unwrap(submission)
    results = []
    for q in sorted(questions, key=lambda k: int(k[1:])):
        ok, why = judge(questions[q], sub.get(q))
        results.append({"q": q, "ok": ok, "given": sub.get(q), "reason": why})
    return sum(1 for r in results if r["ok"]), results


def tolerance_text(spec):
    tol = spec.get("tolerance")
    if not tol:
        return "完全に一致"
    if "abs" in tol:
        return "差 %s まで" % tol["abs"]
    return "正答の %s%% まで" % (float(tol["rel"]) * 100)


def score_main(path, show, as_json, minimum):
    doc = load_answers()
    questions = doc["questions"]
    try:
        with open(path, encoding="utf-8") as fh:
            submission = json.load(fh)
    except (OSError, ValueError) as e:
        print("FAIL score: 答えの JSON を読めない: %s" % e)
        return 2
    n, results = grade(questions, submission)
    if as_json:
        out = {"score": n, "total": len(questions), "results": results}
        if show:
            for r in results:
                r["answer"] = questions[r["q"]]["answer"]
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        for r in results:
            line = "%-4s %s  答え %s" % (r["q"], "正" if r["ok"] else "誤", json.dumps(r["given"], ensure_ascii=False))
            if r["reason"]:
                line += "（%s）" % r["reason"]
            if show:
                spec = questions[r["q"]]
                line += "  正答 %s（%s）" % (json.dumps(spec["answer"], ensure_ascii=False), tolerance_text(spec))
            print(line)
        print("RESULT: %d/%d" % (n, len(questions)))
    if minimum is not None and n < minimum:
        return 1
    return 0


def single_select(sql):
    s = sql.strip()
    if s.endswith(";"):
        s = s[:-1].rstrip()
    return s.upper().startswith("SELECT") and ";" not in s


def run(con, sql, form):
    if form == "list":
        return [r[0] for r in con.execute(sql).fetchall()]
    row = con.execute(sql).fetchone()
    return row[0] if row else None


def verify_db(path):
    doc = load_answers()
    p = pathlib.Path(path).expanduser().resolve()
    if not p.is_file():
        print("FAIL verify-db: %s が無い。build.py で作ってから渡す" % p)
        return 1
    con = sqlite3.connect(p.as_uri() + "?mode=ro", uri=True)
    con.execute("PRAGMA query_only = ON")
    fails = 0

    def bad(where, msg):
        nonlocal fails
        fails += 1
        print("FAIL verify-db %s %s" % (where, msg))

    try:
        for table, n in sorted(doc["tables"].items()):
            got = con.execute('SELECT COUNT(*) FROM "%s"' % table.replace('"', '""')).fetchone()[0]
            if got != n:
                bad(table, "行の数が %d（answers.json は %d）。種か app/ の形が変わった" % (got, n))
        for q in sorted(doc["questions"], key=lambda k: int(k[1:])):
            spec = doc["questions"][q]
            before = fails
            sqls = [("sql", spec["sql"])] + [("alt%d" % i, s) for i, s in enumerate(spec["alt"], 1)]
            sqls.append(("naive", spec["naive"]["sql"]))
            if not all(single_select(s) for _, s in sqls):
                bad(q, "1 文だけの SELECT でない文がある")
                continue
            got = run(con, spec["sql"], spec["form"])
            if got != spec["answer"]:
                bad(q, "正答の文の結果が %s（answer は %s）" % (got, spec["answer"]))
            for label, s in sqls[1:-1]:
                ok, _why = judge(spec, run(con, s, spec["form"]))
                if not ok:
                    bad(q, "%s の結果が正答と合わない" % label)
            naive = run(con, spec["naive"]["sql"], spec["form"])
            if naive != spec["naive"]["answer"]:
                bad(q, "naive の結果が %s（記録は %s）" % (naive, spec["naive"]["answer"]))
            if judge(spec, naive)[0]:
                bad(q, "コードの数え方（naive）でも正答になる。罠が効いていない")
            if fails > before:
                continue
            print("ok   verify-db %s 正答 %s、別の道筋 %d 本、コードの数え方は %s" % (
                q, json.dumps(spec["answer"], ensure_ascii=False), len(spec["alt"]),
                json.dumps(naive, ensure_ascii=False)))
    finally:
        con.close()
    print("RESULT: %s verify-db %s（FAIL %d 件）" % ("PASS" if fails == 0 else "FAIL", p.name, fails))
    return 0 if fails == 0 else 1


def wrong_value(spec):
    want = spec["answer"]
    if spec["form"] == "number":
        return want + int(limit_of(spec)) * 2 + 1
    if spec["form"] == "text":
        return "1999-01-01" if want != "1999-01-01" else "2000-01-01"
    rev = list(reversed(want))
    return rev if rev != want else [0]


def selftest():
    doc = load_answers()
    qs = doc["questions"]
    total = len(qs)
    fails = []
    n_cases = 0

    def expect(label, cond):
        nonlocal n_cases
        n_cases += 1
        if not cond:
            fails.append(label)

    # answers.json の形
    expect("問いが 10 問", total == 10)
    for q, spec in qs.items():
        expect(q + " の形", spec.get("form") in FORMS)
        expect(q + " の文が SELECT 1 文", single_select(spec["sql"]) and single_select(spec["naive"]["sql"]))
        expect(q + " のコードの数え方は誤りになる", not judge(spec, spec["naive"]["answer"])[0])
    perfect = {q: spec["answer"] for q, spec in qs.items()}
    n, _ = grade(qs, perfect)
    expect("正答そのもので %d 点" % total, n == total)
    for q in qs:
        sub = dict(perfect)
        sub[q] = wrong_value(qs[q])
        n, res = grade(qs, sub)
        expect("%s だけ変えて %d 点" % (q, total - 1), n == total - 1 and not next(r for r in res if r["q"] == q)["ok"])
    # 書き方のゆれと境目。問いの形ごとに、最初の 1 問で見る
    num = next(q for q in sorted(qs) if qs[q]["form"] == "number" and (qs[q].get("tolerance") or {}).get("abs") == 0)
    rel = next(q for q in sorted(qs) if qs[q]["form"] == "number" and "rel" in (qs[q].get("tolerance") or {}))
    day = next(q for q in sorted(qs) if qs[q].get("normalize") == "date")
    lst = next(q for q in sorted(qs) if qs[q]["form"] == "list")
    a_num, a_rel, a_day, a_lst = qs[num]["answer"], qs[rel]["answer"], qs[day]["answer"], qs[lst]["answer"]
    y, m, d = (int(x) for x in a_day.split("-"))
    cases = [
        ("数を文字で", num, str(a_num), True),
        ("数に桁区切りと単位", rel, "{:,} 円".format(a_rel), True),
        ("全角の数字", num, unicodedata.normalize("NFKC", str(a_num)).translate(str.maketrans("0123456789", "０１２３４５６７８９")), True),
        ("誤差 0 の問いで 1 違う", num, a_num + 1, False),
        ("割合の誤差の内", rel, a_rel * (1 + float(qs[rel]["tolerance"]["rel"]) * 0.9), True),
        ("割合の誤差の外", rel, a_rel * (1 + float(qs[rel]["tolerance"]["rel"]) * 1.1), False),
        ("数として読めない", num, "たくさん", False),
        ("真偽は数ではない", num, True, False),
        ("日付を / で", day, "%d/%d/%d" % (y, m, d), True),
        ("日付を 年月日 で", day, "%d年%d月%d日" % (y, m, d), True),
        ("日付でない", day, "八月の初め", False),
        ("一覧を文字の数で", lst, [str(x) for x in a_lst], True),
        ("一覧を 1 本の文字で", lst, ", ".join(str(x) for x in a_lst), True),
        ("一覧の順が違う", lst, list(reversed(a_lst)), list(reversed(a_lst)) == a_lst),
        ("一覧が足りない", lst, a_lst[:-1], False),
    ]
    for label, q, value, want in cases:
        sub = dict(perfect)
        sub[q] = value
        n, _ = grade(qs, sub)
        expect(label, (n == total) == want)
    sub = dict(perfect)
    del sub[num]
    expect("答えの無い問いは誤", grade(qs, sub)[0] == total - 1)
    expect("包んだ形と小文字の番号", grade(qs, {"answers": {k.lower(): v for k, v in perfect.items()}})[0] == total)
    for label in fails:
        print("FAIL score --selftest %s" % label)
    print("RESULT: %s score --selftest（%d 例、FAIL %d 件）" % ("PASS" if not fails else "FAIL", n_cases, len(fails)))
    return 0 if not fails else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="messy-shop の 10 問の答えを採点する")
    ap.add_argument("submission", nargs="?", help="答えの JSON のパス")
    ap.add_argument("--show", action="store_true", help="正答も並べる（答える側には見せない）")
    ap.add_argument("--json", action="store_true", help="結果を JSON で出す")
    ap.add_argument("--min", type=int, default=None, help="正がこの数に届かなければ終了コード 1")
    ap.add_argument("--verify-db", metavar="DB", help="build.py で作った DB で answers.json の文を確かめる")
    ap.add_argument("--selftest", action="store_true", help="採点の自己試験（DB は使わない）")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.verify_db:
        return verify_db(a.verify_db)
    if not a.submission:
        ap.print_usage()
        return 2
    return score_main(a.submission, a.show, a.json, a.min)


if __name__ == "__main__":
    sys.exit(main())
