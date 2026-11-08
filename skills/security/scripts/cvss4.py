#!/usr/bin/env python3
"""cvss4 — CVSS 4.0 の基本の値の文字列から点数と重さを出し、報告に書いた点数と重さの食い違いを落とす。

使い方: cvss4.py 'CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:H/VA:H/SC:N/SI:N/SA:N'
        cvss4.py --report <報告.md>     報告の中の「CVSS:4.0/…」と、同じ発見に書いた「点数」「重さ」を突き合わせる
        cvss4.py --selftest
出力: 文字列 1 本なら「<点数> <重さ> <文字列>」と RESULT の行。--report は FAIL <ファイル>:<行> [<決まり>] … と RESULT: PASS|FAIL。
      1 件でも FAIL なら終了コード 1。
見る範囲: 基本の 11 個の値（AV AC AT PR UI VC VI VA SC SI SA）。脅威（E）と環境の値は、書かれていても点数に入れず FAIL にする
      （報告の点数は基本の値だけで出す決まり。脅威と環境は報告の本文で別に書く）。
計算の仕方: FIRST の CVSS v4.0 仕様書の 8 章（CVSS v4.0 Scoring）の手順。値を 6 つの同値の群（EQ1〜EQ6）にまとめた
      「マクロの値」を表で引き、同じ群の中の最も重い値からの距離で補間する。表と最も重い値と最大の距離は、FIRST が出す
      公式の計算機（https://github.com/FIRSTdotorg/cvss-v4-calculator の cvss_lookup.js・max_composed.js・max_severity.js、
      仕様書 https://www.first.org/cvss/v4.0/specification-document）の値を写した。重さの区切りは仕様書 5 章の表
      （None 0.0、Low 0.1〜3.9、Medium 4.0〜6.9、High 7.0〜8.9、Critical 9.0〜10.0）。
"""
import decimal
import pathlib
import re
import sys
import tempfile

BASE = ["AV", "AC", "AT", "PR", "UI", "VC", "VI", "VA", "SC", "SI", "SA"]
ALLOWED = {
    "AV": "NALP", "AC": "LH", "AT": "NP", "PR": "NLH", "UI": "NPA",
    "VC": "HLN", "VI": "HLN", "VA": "HLN", "SC": "HLN", "SI": "HLN", "SA": "HLN",
}
VECTOR_RX = re.compile(r"CVSS:4\.0(?:/[A-Z]+:[A-Z])+")

# FIRST の cvss_lookup.js（cvssLookup_global）を写した表。鍵は EQ1 EQ2 EQ3 EQ4 EQ5 EQ6 の 6 桁、値はマクロの値の点数。
LOOKUP = {
    "000000": 10, "000001": 9.9, "000010": 9.8, "000011": 9.5, "000020": 9.5, "000021": 9.2,
    "000100": 10, "000101": 9.6, "000110": 9.3, "000111": 8.7, "000120": 9.1, "000121": 8.1,
    "000200": 9.3, "000201": 9, "000210": 8.9, "000211": 8, "000220": 8.1, "000221": 6.8,
    "001000": 9.8, "001001": 9.5, "001010": 9.5, "001011": 9.2, "001020": 9, "001021": 8.4,
    "001100": 9.3, "001101": 9.2, "001110": 8.9, "001111": 8.1, "001120": 8.1, "001121": 6.5,
    "001200": 8.8, "001201": 8, "001210": 7.8, "001211": 7, "001220": 6.9, "001221": 4.8,
    "002001": 9.2, "002011": 8.2, "002021": 7.2, "002101": 7.9, "002111": 6.9, "002121": 5,
    "002201": 6.9, "002211": 5.5, "002221": 2.7,
    "010000": 9.9, "010001": 9.7, "010010": 9.5, "010011": 9.2, "010020": 9.2, "010021": 8.5,
    "010100": 9.5, "010101": 9.1, "010110": 9, "010111": 8.3, "010120": 8.4, "010121": 7.1,
    "010200": 9.2, "010201": 8.1, "010210": 8.2, "010211": 7.1, "010220": 7.2, "010221": 5.3,
    "011000": 9.5, "011001": 9.3, "011010": 9.2, "011011": 8.5, "011020": 8.5, "011021": 7.3,
    "011100": 9.2, "011101": 8.2, "011110": 8, "011111": 7.2, "011120": 7, "011121": 5.9,
    "011200": 8.4, "011201": 7, "011210": 7.1, "011211": 5.2, "011220": 5, "011221": 3,
    "012001": 8.6, "012011": 7.5, "012021": 5.2, "012101": 7.1, "012111": 5.2, "012121": 2.9,
    "012201": 6.3, "012211": 2.9, "012221": 1.7,
    "100000": 9.8, "100001": 9.5, "100010": 9.4, "100011": 8.7, "100020": 9.1, "100021": 8.1,
    "100100": 9.4, "100101": 8.9, "100110": 8.6, "100111": 7.4, "100120": 7.7, "100121": 6.4,
    "100200": 8.7, "100201": 7.5, "100210": 7.4, "100211": 6.3, "100220": 6.3, "100221": 4.9,
    "101000": 9.4, "101001": 8.9, "101010": 8.8, "101011": 7.7, "101020": 7.6, "101021": 6.7,
    "101100": 8.6, "101101": 7.6, "101110": 7.4, "101111": 5.8, "101120": 5.9, "101121": 5,
    "101200": 7.2, "101201": 5.7, "101210": 5.7, "101211": 5.2, "101220": 5.2, "101221": 2.5,
    "102001": 8.3, "102011": 7, "102021": 5.4, "102101": 6.5, "102111": 5.8, "102121": 2.6,
    "102201": 5.3, "102211": 2.1, "102221": 1.3,
    "110000": 9.5, "110001": 9, "110010": 8.8, "110011": 7.6, "110020": 7.6, "110021": 7,
    "110100": 9, "110101": 7.7, "110110": 7.5, "110111": 6.2, "110120": 6.1, "110121": 5.3,
    "110200": 7.7, "110201": 6.6, "110210": 6.8, "110211": 5.9, "110220": 5.2, "110221": 3,
    "111000": 8.9, "111001": 7.8, "111010": 7.6, "111011": 6.7, "111020": 6.2, "111021": 5.8,
    "111100": 7.4, "111101": 5.9, "111110": 5.7, "111111": 5.7, "111120": 4.7, "111121": 2.3,
    "111200": 6.1, "111201": 5.2, "111210": 5.7, "111211": 2.9, "111220": 2.4, "111221": 1.6,
    "112001": 7.1, "112011": 5.9, "112021": 3, "112101": 5.8, "112111": 2.6, "112121": 1.5,
    "112201": 2.3, "112211": 1.3, "112221": 0.6,
    "200000": 9.3, "200001": 8.7, "200010": 8.6, "200011": 7.2, "200020": 7.5, "200021": 5.8,
    "200100": 8.6, "200101": 7.4, "200110": 7.4, "200111": 6.1, "200120": 5.6, "200121": 3.4,
    "200200": 7, "200201": 5.4, "200210": 5.2, "200211": 4, "200220": 4, "200221": 2.2,
    "201000": 8.5, "201001": 7.5, "201010": 7.4, "201011": 5.5, "201020": 6.2, "201021": 5.1,
    "201100": 7.2, "201101": 5.7, "201110": 5.5, "201111": 4.1, "201120": 4.6, "201121": 1.9,
    "201200": 5.3, "201201": 3.6, "201210": 3.4, "201211": 1.9, "201220": 1.9, "201221": 0.8,
    "202001": 6.4, "202011": 5.1, "202021": 2, "202101": 4.7, "202111": 2.1, "202121": 1.1,
    "202201": 2.4, "202211": 0.9, "202221": 0.4,
    "210000": 8.8, "210001": 7.5, "210010": 7.3, "210011": 5.3, "210020": 6, "210021": 5,
    "210100": 7.3, "210101": 5.5, "210110": 5.9, "210111": 4, "210120": 4.1, "210121": 2,
    "210200": 5.4, "210201": 4.3, "210210": 4.5, "210211": 2.2, "210220": 2, "210221": 1.1,
    "211000": 7.5, "211001": 5.5, "211010": 5.8, "211011": 4.5, "211020": 4, "211021": 2.1,
    "211100": 6.1, "211101": 5.1, "211110": 4.8, "211111": 1.8, "211120": 2, "211121": 0.9,
    "211200": 4.6, "211201": 1.8, "211210": 1.7, "211211": 0.7, "211220": 0.8, "211221": 0.2,
    "212001": 5.3, "212011": 2.4, "212021": 1.4, "212101": 2.4, "212111": 1.2, "212121": 0.5,
    "212201": 1, "212211": 0.3, "212221": 0.1,
}

# max_composed.js を写した、群ごとの最も重い値。
MAX_COMPOSED = {
    "eq1": {0: ["AV:N/PR:N/UI:N"], 1: ["AV:A/PR:N/UI:N", "AV:N/PR:L/UI:N", "AV:N/PR:N/UI:P"], 2: ["AV:P/PR:N/UI:N", "AV:A/PR:L/UI:P"]},
    "eq2": {0: ["AC:L/AT:N"], 1: ["AC:H/AT:N", "AC:L/AT:P"]},
    "eq3": {
        0: {0: ["VC:H/VI:H/VA:H/CR:H/IR:H/AR:H"], 1: ["VC:H/VI:H/VA:L/CR:M/IR:M/AR:H", "VC:H/VI:H/VA:H/CR:M/IR:M/AR:M"]},
        1: {0: ["VC:L/VI:H/VA:H/CR:H/IR:H/AR:H", "VC:H/VI:L/VA:H/CR:H/IR:H/AR:H"],
            1: ["VC:L/VI:H/VA:L/CR:H/IR:M/AR:H", "VC:L/VI:H/VA:H/CR:H/IR:M/AR:M", "VC:H/VI:L/VA:H/CR:M/IR:H/AR:M",
                "VC:H/VI:L/VA:L/CR:M/IR:H/AR:H", "VC:L/VI:L/VA:H/CR:H/IR:H/AR:M"]},
        2: {1: ["VC:L/VI:L/VA:L/CR:H/IR:H/AR:H"]},
    },
    "eq4": {0: ["SC:H/SI:S/SA:S"], 1: ["SC:H/SI:H/SA:H"], 2: ["SC:L/SI:L/SA:L"]},
}
# max_severity.js を写した、群ごとの最大の距離（0.1 の何段か）。
MAX_SEVERITY = {
    "eq1": {0: 1, 1: 4, 2: 5}, "eq2": {0: 1, 1: 2},
    "eq3eq6": {(0, 0): 7, (0, 1): 6, (1, 0): 8, (1, 1): 8, (2, 1): 10},
    "eq4": {0: 6, 1: 5, 2: 4},
}
LEVELS = {
    "AV": {"N": 0.0, "A": 0.1, "L": 0.2, "P": 0.3}, "PR": {"N": 0.0, "L": 0.1, "H": 0.2},
    "UI": {"N": 0.0, "P": 0.1, "A": 0.2}, "AC": {"L": 0.0, "H": 0.1}, "AT": {"N": 0.0, "P": 0.1},
    "VC": {"H": 0.0, "L": 0.1, "N": 0.2}, "VI": {"H": 0.0, "L": 0.1, "N": 0.2}, "VA": {"H": 0.0, "L": 0.1, "N": 0.2},
    "SC": {"H": 0.1, "L": 0.2, "N": 0.3}, "SI": {"S": 0.0, "H": 0.1, "L": 0.2, "N": 0.3},
    "SA": {"S": 0.0, "H": 0.1, "L": 0.2, "N": 0.3}, "CR": {"H": 0.0, "M": 0.1, "L": 0.2},
    "IR": {"H": 0.0, "M": 0.1, "L": 0.2}, "AR": {"H": 0.0, "M": 0.1, "L": 0.2},
}


class VectorError(ValueError):
    pass


def parse(vector: str) -> dict:
    """基本の 11 個がちょうど 1 回ずつ、決まった順で、許された値か。違えば VectorError。"""
    s = vector.strip()
    if not s.startswith("CVSS:4.0/"):
        raise VectorError("「CVSS:4.0/」で始まらない")
    parts = s[len("CVSS:4.0/"):].split("/")
    keys = []
    m = {}
    for p in parts:
        if ":" not in p:
            raise VectorError(f"「{p}」が 名前:値 の形でない")
        k, v = p.split(":", 1)
        if k in m:
            raise VectorError(f"{k} が 2 回ある")
        if k not in ALLOWED:
            raise VectorError(f"{k} は基本の値でない（脅威と環境の値は報告の点数に入れない）")
        if len(v) != 1 or v not in ALLOWED[k]:
            raise VectorError(f"{k}:{v} は許されない値（{k} は {'/'.join(ALLOWED[k])}）")
        keys.append(k)
        m[k] = v
    missing = [k for k in BASE if k not in m]
    if missing:
        raise VectorError(f"{'・'.join(missing)} が無い")
    if keys != BASE:
        raise VectorError("値の順が仕様書と違う（AV AC AT PR UI VC VI VA SC SI SA の順）")
    # 基本だけを見るので、脅威は E:X（=A）、環境の要求は CR/IR/AR:X（=H）として計算する。
    m.update({"E": "A", "CR": "H", "IR": "H", "AR": "H"})
    return m


def macro(m: dict):
    av, pr, ui = m["AV"], m["PR"], m["UI"]
    if av == "N" and pr == "N" and ui == "N":
        eq1 = 0
    elif (av == "N" or pr == "N" or ui == "N") and av != "P":
        eq1 = 1
    else:
        eq1 = 2
    eq2 = 0 if (m["AC"] == "L" and m["AT"] == "N") else 1
    vc, vi, va = m["VC"], m["VI"], m["VA"]
    if vc == "H" and vi == "H":
        eq3 = 0
    elif vc == "H" or vi == "H" or va == "H":
        eq3 = 1
    else:
        eq3 = 2
    if m["SI"] == "S" or m["SA"] == "S":
        eq4 = 0
    elif m["SC"] == "H" or m["SI"] == "H" or m["SA"] == "H":
        eq4 = 1
    else:
        eq4 = 2
    eq5 = {"A": 0, "P": 1, "U": 2}[m["E"]]
    crit = (m["CR"] == "H" and vc == "H") or (m["IR"] == "H" and vi == "H") or (m["AR"] == "H" and va == "H")
    eq6 = 0 if crit else 1
    return [eq1, eq2, eq3, eq4, eq5, eq6]


def _key(eqs):
    return "".join(str(x) for x in eqs)


def _lookup(eqs):
    return LOOKUP.get(_key(eqs))


def _get(vec: str, name: str) -> str:
    for part in vec.split("/"):
        if part.startswith(name + ":"):
            return part.split(":", 1)[1]
    raise KeyError(name)


def score(vector: str) -> float:
    m = parse(vector)
    if all(m[k] == "N" for k in ("VC", "VI", "VA", "SC", "SI", "SA")):
        return 0.0
    eqs = macro(m)
    eq1, eq2, eq3, eq4, eq5, eq6 = eqs
    value = _lookup(eqs)

    def lower(i):
        n = list(eqs)
        n[i] += 1
        return _lookup(n)

    s_eq1, s_eq2, s_eq4, s_eq5 = lower(0), lower(1), lower(3), lower(4)
    if eq3 == 0 and eq6 == 0:
        left = _lookup([eq1, eq2, eq3, eq4, eq5, eq6 + 1])
        right = _lookup([eq1, eq2, eq3 + 1, eq4, eq5, eq6])
        cands = [x for x in (left, right) if x is not None]
        s_eq3eq6 = max(cands) if cands else None
    elif eq3 == 1 and eq6 == 0:
        s_eq3eq6 = _lookup([eq1, eq2, eq3, eq4, eq5, eq6 + 1])
    else:  # (0,1) (1,1) は eq3 を 1 つ下げる。(2,1) は下が無い
        s_eq3eq6 = _lookup([eq1, eq2, eq3 + 1, eq4, eq5, eq6])

    eq3_maxes = MAX_COMPOSED["eq3"][eq3][eq6]
    max_vectors = [f"{a}/{b}/{c}/{d}" for a in MAX_COMPOSED["eq1"][eq1] for b in MAX_COMPOSED["eq2"][eq2]
                   for c in eq3_maxes for d in MAX_COMPOSED["eq4"][eq4]]
    names = ["AV", "PR", "UI", "AC", "AT", "VC", "VI", "VA", "SC", "SI", "SA", "CR", "IR", "AR"]
    dist = None
    for mv in max_vectors:
        d = {k: LEVELS[k][m[k]] - LEVELS[k][_get(mv, k)] for k in names}
        if all(v >= 0 for v in d.values()):
            dist = d
            break
    if dist is None:  # 仕様の上では起きない
        raise VectorError("最も重い値が見つからない")
    cur = {
        "eq1": dist["AV"] + dist["PR"] + dist["UI"],
        "eq2": dist["AC"] + dist["AT"],
        "eq3eq6": dist["VC"] + dist["VI"] + dist["VA"] + dist["CR"] + dist["IR"] + dist["AR"],
        "eq4": dist["SC"] + dist["SI"] + dist["SA"],
    }
    step = 0.1
    maxsev = {
        "eq1": MAX_SEVERITY["eq1"][eq1] * step, "eq2": MAX_SEVERITY["eq2"][eq2] * step,
        "eq3eq6": MAX_SEVERITY["eq3eq6"][(eq3, eq6)] * step, "eq4": MAX_SEVERITY["eq4"][eq4] * step,
    }
    lowers = {"eq1": s_eq1, "eq2": s_eq2, "eq3eq6": s_eq3eq6, "eq4": s_eq4, "eq5": s_eq5}
    total, n = 0.0, 0
    for k, low in lowers.items():
        if low is None:
            continue
        n += 1
        if k == "eq5":
            continue  # 群 5 の中の距離はいつも 0
        total += (value - low) * (cur[k] / maxsev[k])
    mean = total / n if n else 0.0
    v = max(0.0, min(10.0, value - mean))
    return float(decimal.Decimal(repr(round(v, 10))).quantize(decimal.Decimal("0.1"), rounding=decimal.ROUND_HALF_UP))


def severity(s: float) -> str:
    if s == 0.0:
        return "None"
    if s < 4.0:
        return "Low"
    if s < 7.0:
        return "Medium"
    if s < 9.0:
        return "High"
    return "Critical"


SCORE_RX = re.compile(r"点数[^0-9\n]{0,12}(\d{1,2}(?:\.\d)?)")
SEV_RX = re.compile(r"重さ[^A-Za-z\n]{0,12}(None|Low|Medium|High|Critical)")
FINDING_RX = re.compile(r"^###\s+(F-\d+)")


def check_report(path: pathlib.Path):
    """発見（### F-n）ごとに、CVSS:4.0 の文字列・点数・重さを 1 つずつ拾い、計算と突き合わせる。"""
    issues = []
    lines = path.read_text(encoding="utf-8").splitlines()
    blocks, cur = [], None
    for no, line in enumerate(lines, 1):
        fm = FINDING_RX.match(line)
        if fm:
            cur = {"id": fm.group(1), "no": no, "lines": []}
            blocks.append(cur)
        elif re.match(r"^##\s", line):
            cur = None
        elif cur is not None:
            cur["lines"].append((no, line))
    if not blocks:
        issues.append((0, "発見", "「### F-1」の形の発見が 1 件も無い"))
    for b in blocks:
        vec = sc = sev = None
        for no, line in b["lines"]:
            if vec is None:
                vm = VECTOR_RX.search(line)
                if vm:
                    vec = (no, vm.group(0))
            if sc is None:
                sm = SCORE_RX.search(line)
                if sm:
                    sc = (no, float(sm.group(1)))
            if sev is None:
                em = SEV_RX.search(line)
                if em:
                    sev = (no, em.group(1))
        tag = b["id"]
        if vec is None:
            issues.append((b["no"], "CVSS の文字列", f"{tag} に CVSS:4.0/… の文字列が無い"))
            continue
        try:
            calc = score(vec[1])
        except VectorError as e:
            issues.append((vec[0], "CVSS の文字列", f"{tag} の文字列が読めない: {e}"))
            continue
        if sc is None:
            issues.append((b["no"], "点数", f"{tag} に「点数: x.x」が無い（計算では {calc}）"))
        elif abs(sc[1] - calc) > 1e-9:
            issues.append((sc[0], "点数の食い違い", f"{tag} は {sc[1]} と書いたが、{vec[1]} の計算は {calc}"))
        if sev is None:
            issues.append((b["no"], "重さ", f"{tag} に「重さ: High」の形が無い（計算では {severity(calc)}）"))
        elif sev[1] != severity(calc):
            issues.append((sev[0], "重さの食い違い", f"{tag} は {sev[1]} と書いたが、点数 {calc} の重さは {severity(calc)}"))
    return issues, len(blocks)


# 検算の例。公式の計算機の例として知られた値を置く。網に出られない作業場では公式の計算機と並べて照合していないので、
# 表を写し直したときや版が変わったときは、公式の計算機で同じ文字列を入れて点数が同じかを確かめる。
KNOWN = [
    ("CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:H/VA:H/SC:N/SI:N/SA:N", 9.3, "Critical"),
    ("CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:H/VA:H/SC:H/SI:H/SA:H", 10.0, "Critical"),
    ("CVSS:4.0/AV:N/AC:L/AT:N/PR:L/UI:N/VC:H/VI:H/VA:H/SC:N/SI:N/SA:N", 8.7, "High"),
    ("CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:N/VA:N/SC:N/SI:N/SA:N", 8.7, "High"),
    ("CVSS:4.0/AV:L/AC:L/AT:N/PR:L/UI:N/VC:H/VI:H/VA:H/SC:N/SI:N/SA:N", 8.5, "High"),
    ("CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:L/VI:N/VA:N/SC:N/SI:N/SA:N", 6.9, "Medium"),
    ("CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:N/VI:N/VA:N/SC:N/SI:N/SA:N", 0.0, "None"),
]


def selftest():
    bad = 0

    def judge(name, ok, detail=""):
        nonlocal bad
        bad += 0 if ok else 1
        print(f"{'PASS' if ok else 'FAIL'} cvss4 {name}{('（' + detail + '）') if detail else ''}")

    judge("表は 270 行（6 つの群の組の全部）", len(LOOKUP) == 270, f"{len(LOOKUP)} 行")
    for vec, want, sev in KNOWN:
        got = score(vec)
        judge(f"検算 {vec[9:]}", got == want and severity(got) == sev, f"期待 {want} {sev}、実際 {got} {severity(got)}")
    for name, vec in [("基本の値が欠ける", "CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:H/VA:H/SC:N/SI:N"),
                      ("許されない値", "CVSS:4.0/AV:X/AC:L/AT:N/PR:N/UI:N/VC:H/VI:H/VA:H/SC:N/SI:N/SA:N"),
                      ("3.1 の文字列", "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"),
                      ("脅威の値を混ぜる", "CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:H/VA:H/SC:N/SI:N/SA:N/E:A"),
                      ("順が違う", "CVSS:4.0/AC:L/AV:N/AT:N/PR:N/UI:N/VC:H/VI:H/VA:H/SC:N/SI:N/SA:N")]:
        try:
            score(vec)
            judge(f"負例 {name} を断る", False, "通ってしまった")
        except VectorError:
            judge(f"負例 {name} を断る", True)
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="cvss4-"))
    good = ("# 報告\n\n## 発見\n\n### F-1: 例\n\n採点は `CVSS:4.0/AV:N/AC:L/AT:N/PR:L/UI:N/VC:H/VI:H/VA:H/SC:N/SI:N/SA:N` です。\n\n"
            "点数: 8.7、重さ: High\n")
    cases = [("点数と重さが計算と同じ", good, 0),
             ("点数を盛る", good.replace("点数: 8.7", "点数: 9.1"), 1),
             ("重さを軽く書く", good.replace("重さ: High", "重さ: Medium"), 1),
             ("文字列が無い", "# 報告\n\n## 発見\n\n### F-1: 例\n\n点数: 8.7、重さ: High\n", 1)]
    for name, text, want in cases:
        p = tmp / "r.md"
        p.write_text(text, encoding="utf-8")
        got, _ = check_report(p)
        judge(f"報告 {name}", len(got) == want, f"期待 {want} 件、実際 {len(got)} 件")
    total = 1 + len(KNOWN) + 5 + len(cases)
    print(f"RESULT: {'PASS' if bad == 0 else 'FAIL'} cvss4 --selftest ({total} 例)")
    return 0 if bad == 0 else 1


def main(argv):
    if argv[:1] == ["--selftest"]:
        return selftest()
    if argv[:1] == ["--report"] and len(argv) >= 2:
        fails, total = 0, 0
        for f in argv[1:]:
            issues, n = check_report(pathlib.Path(f))
            total += n
            for no, rule, msg in issues:
                print(f"FAIL {f}:{no} [{rule}] {msg}")
            fails += len(issues)
        print(f"RESULT: {'PASS' if fails == 0 else 'FAIL'} cvss4 --report (発見 {total}、FAIL {fails})")
        return 0 if fails == 0 else 1
    if len(argv) == 1 and not argv[0].startswith("-"):
        try:
            s = score(argv[0])
        except VectorError as e:
            print(f"FAIL [CVSS の文字列] {e}")
            print("RESULT: FAIL cvss4")
            return 1
        print(f"{s} {severity(s)} {argv[0]}")
        print("RESULT: PASS cvss4")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
