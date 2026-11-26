#!/usr/bin/env python3
"""attack_check — 攻撃の台帳（attack_run が書いた JSON）の検査。線 7 を機械で確かめる。

見るもの:
  - 台帳の各行の欄は、決めた 7 つ（handle・entry・actor・status・len・marker・ms）だけか。余計な欄があれば落とす。
  - 台帳のどの値にも、鍵や本文のような秘密が無いか（Bearer の鍵の形、長い 16 進、HttpOnly の Cookie、住所や氏名の形）。
  - found・new・old の 3 つがそろうか。new にある手口は found にあるか。
使い方: attack_check.py <台帳.json>...   /   attack_check.py --selftest
出力: FAIL の行と、最後に RESULT: PASS|FAIL attack-check。1 件でも FAIL なら終了コード 1。
"""
import json
import re
import sys
import tempfile

ALLOWED = {"handle", "entry", "actor", "status", "len", "marker", "ms"}
SECRET = re.compile(r"token-\w|Bearer\s+\S|[0-9a-f]{24,}|set-cookie|password|pw_hash|HttpOnly", re.I)


def check(path):
    issues = []
    try:
        d = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError) as e:
        return [(0, "読めない", str(e))]
    for k in ("found", "new", "old", "rows"):
        if k not in d:
            issues.append((0, "欄", "台帳に「%s」が無い" % k))
    for i, row in enumerate(d.get("rows", []), 1):
        extra = set(row) - ALLOWED
        if extra:
            issues.append((i, "余計な欄", "行 %d に、決めた欄の外（%s）がある" % (i, "・".join(sorted(extra)))))
    blob = json.dumps(d, ensure_ascii=False)
    for m in SECRET.finditer(blob):
        issues.append((0, "秘密", "台帳に秘密の形の値がある（%s…）" % m.group(0)[:12]))
        break
    for h in d.get("new", []):
        if h not in d.get("found", []):
            issues.append((0, "食い違い", "new の %s が found に無い" % h))
    return issues


def main(files):
    total = 0
    for f in files:
        for no, rule, detail in check(f):
            total += 1
            where = "%s:%d" % (f, no) if no else f
            print("FAIL %s [%s] %s" % (where, rule, detail))
    v = "FAIL" if total else "PASS"
    print("RESULT: %s attack-check (%d 本、%d 件)" % (v, len(files), total))
    return 1 if total else 0


def selftest():
    ok = True
    good = {"found": ["A02"], "new": ["A02"], "old": [], "sent": 5,
            "rows": [{"handle": "A02", "entry": "order_detail", "actor": "op_a", "status": 200, "len": 50, "marker": None, "ms": 3}]}
    bad_extra = {"found": [], "new": [], "old": [], "rows": [{"handle": "A01", "entry": "x", "actor": "n", "status": 200, "len": 1, "marker": None, "ms": 1, "body": "..."}]}
    bad_secret = {"found": [], "new": [], "old": [], "rows": [{"handle": "A05", "entry": "x", "actor": "guess", "status": 200, "len": 1, "marker": "token-op_a", "ms": 1}]}
    with tempfile.TemporaryDirectory() as t:
        import os
        def w(name, obj):
            p = os.path.join(t, name)
            json.dump(obj, open(p, "w", encoding="utf-8"), ensure_ascii=False)
            return p
        cases = [("good", good, 0), ("extra", bad_extra, 1), ("secret", bad_secret, 1)]
        for name, obj, want_fail in cases:
            n = len(check(w(name + ".json", obj)))
            got = 1 if n else 0
            if got != want_fail:
                ok = False
                print("FAIL selftest attack-check: 例 %s の判定 %d（期待 %d、件数 %d）" % (name, got, want_fail, n))
    print("RESULT: %s attack-check --selftest (3 例)" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    if sys.argv[1:] == ["--selftest"]:
        sys.exit(selftest())
    if not sys.argv[1:]:
        print("使い方: attack_check.py <台帳.json>... | --selftest")
        sys.exit(2)
    sys.exit(main(sys.argv[1:]))
