#!/usr/bin/env python3
"""sre_check — SRE の成果物の検査。標準の python3 だけで動く。

使い方: sre_check.py slo <SLO 定義書.md>            SLO 定義書の欠け（SLI の測り点、目標と期間、承認者、エラーバジェットの扱い、
                                                    通知の設計と Runbook への結び、Runbook の 7 つの節と、表の外の手の 2 番手への連絡）を落とす
        sre_check.py burn <SLO 定義書.md>           通知の表のバーンレート・失敗率の閾値・短い窓・使い切るまでの時間を計算し直し、食い違いを落とす
        sre_check.py burn --slo 99.9 --period 30d [--tiers 2%:1h:呼び出し,5%:6h:呼び出し,10%:3d:チケット] [--burn 14.4]
                                                    目標と期間から多窓・多段の閾値と、使い切るまでの時間を出す
        sre_check.py burn --reference <照合の表.tsv>      原典の値を写した表と計算を突き合わせる（evals/workbook-reference.tsv）
        sre_check.py <slo|burn> --selftest
計算の式（出典: Google SRE Workbook「Alerting on SLOs」https://sre.google/workbook/alerting-on-slos/）:
  バーンレート = 予算の消費 × 期間 ÷ 長い窓、失敗率の閾値 = バーンレート × (1 − 目標)、短い窓 = 長い窓 ÷ 12、
  使い切るまで = 期間 ÷ バーンレート。
出力: FAIL <場所> [<決まり>] <内容>、MEASURE <値>、最後に RESULT: PASS|FAIL <検査名> <対象> (FAIL n)。1 件でも FAIL なら終了コード 1。
"""
import pathlib
import re
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
SKILL = HERE.parent
EXAMPLE = SKILL / "examples" / "slo-order-list.md"
NAMES = {"slo": "slo-doc-check", "burn": "burn-rate"}
DEFAULT_TIERS = [(2.0, 60.0, "呼び出し"), (5.0, 360.0, "呼び出し"), (10.0, 4320.0, "チケット")]
NEAR_USER = ("ロードバランサー", "外形", "入口", "ブラウザ", "端末", "利用者")
SLO_SECTIONS = ["SLI", "目標と期間", "承認", "エラーバジェットの扱い", "通知の設計"]
RUNBOOK_SECTIONS = ["症状", "確かめる命令", "原因の見分け方", "直す命令", "どれにも合わないとき", "直ったことの確かめ", "戻し方"]
COMMAND_SECTIONS = ["確かめる命令", "直す命令", "どれにも合わないとき", "直ったことの確かめ"]
SEVERITY = ("呼び出し", "チケット")
PLACEHOLDER = re.compile(r"〈[^〉]*〉|<[^>/!A-Za-z][^>]*>|TBD|未定|＿＿")  # <br/> と注釈は穴埋めと見ない
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
TOL = 0.01  # 文書の値と計算の値の差の許し（相対 1%。原典と文書は桁を丸めて書く）


class Report:
    def __init__(self, check, name):
        self.check, self.name, self.items, self.notes = check, name, [], []

    def fail(self, rule, detail):
        self.items.append((rule, detail))

    def note(self, text):
        self.notes.append(text)

    def rules(self):
        return {x[0] for x in self.items}

    def show(self):
        for n in self.notes:
            print(f"MEASURE {n}")
        for rule, detail in self.items:
            print(f"FAIL {self.name} [{rule}] {detail}")
        ok = not self.items
        print(f"RESULT: {'PASS' if ok else 'FAIL'} {self.check} {self.name} (FAIL {len(self.items)})")
        return ok


# ---- Markdown を節と表に分ける
def sections(text):
    """## の節ごとに (見出し, 本文の行) を返す。### 以下は親の節に含める"""
    out, head, buf, fence = [], None, [], False
    for line in text.splitlines():
        if line.startswith("```"):
            fence = not fence
        if not fence and line.startswith("## "):
            if head is not None:
                out.append((head, buf))
            head, buf = line[3:].strip(), []
        elif head is not None:
            buf.append(line)
    if head is not None:
        out.append((head, buf))
    return out


def find_section(secs, key):
    for h, body in secs:
        if key in h:
            return body
    return None


def tables(lines):
    """表ごとに、見出しの名前 → 値の辞書の並びを返す"""
    out, cur = [], []
    for line in lines + [""]:
        if line.strip().startswith("|"):
            cur.append(line.strip())
            continue
        if len(cur) >= 2:
            head = [c.strip() for c in cur[0].strip("|").split("|")]
            rows = []
            for r in cur[2:]:
                cells = [c.strip() for c in r.strip("|").split("|")]
                rows.append(dict(zip(head, cells + [""] * (len(head) - len(cells)))))
            out.append((head, rows))
        cur = []
    return out


def table_with(lines, *cols):
    for head, rows in tables(lines or []):
        if all(any(c in h for h in head) for c in cols):
            return head, rows
    return None, []


def cell(row, key):
    for k, v in row.items():
        if key in k:
            return v
    return ""


def code_blocks(lines):
    out, buf, fence = [], [], False
    for line in lines:
        if line.startswith("```"):
            if fence:
                out.append("\n".join(buf))
                buf = []
            fence = not fence
            continue
        if fence:
            buf.append(line)
    return out


# ---- 数の読み方
def pct(s):
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*%", s or "")
    return float(m.group(1)) if m else None


def num(s):
    m = re.search(r"[0-9]+(?:\.[0-9]+)?", s or "")
    return float(m.group(0)) if m else None


UNITS = {"分": 1.0, "m": 1.0, "時間": 60.0, "h": 60.0, "日": 1440.0, "d": 1440.0}


def minutes(s):
    """「5 分」「1 時間」「3 日」「30d」「6h」を分にする"""
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(時間|分|日|m(?!s)|h|d)", s or "")
    if not m:
        return None
    return float(m.group(1)) * UNITS[m.group(2)]


def show_min(v):
    if v >= 1440 and abs(v / 1440 - round(v / 1440)) < 1e-9:
        return f"{v / 1440:g}d"
    if v >= 60 and abs(v / 60 - round(v / 60, 2)) < 1e-9:
        return f"{v / 60:g}h"
    return f"{round(v, 1):g}m"


def close(a, b):
    return b is not None and a is not None and abs(a - b) <= TOL * max(abs(a), abs(b), 1e-9)


def tier(slo_pct, period_min, consumption_pct, long_min):
    burn = consumption_pct / 100.0 * period_min / long_min
    return {"burn": burn, "threshold_pct": burn * (100.0 - slo_pct), "short": long_min / 12.0, "exhaust": period_min / burn}


# ---- slo-doc-check
def check_slo(path):
    rep = Report("slo-doc-check", str(path))
    p = pathlib.Path(path)
    if not p.is_file():
        rep.fail("無い", "ファイルが無い")
        return rep
    text = p.read_text(encoding="utf-8")
    secs = sections(text)
    for key in SLO_SECTIONS:
        if find_section(secs, key) is None:
            rep.fail("必須の節", f"「## {key}」を含む節が無い")
    for m in PLACEHOLDER.finditer(text):
        rep.fail("穴埋め", f"埋めていない欄「{m.group(0)}」")
        break
    # SLI
    _, slis = table_with(find_section(secs, "SLI"), "SLI", "測り点", "有効", "良い")
    names = []
    if not slis:
        rep.fail("SLI", "SLI の表（SLI・測り点・有効な要求・良い要求）が無い")
    for r in slis:
        name = cell(r, "SLI")
        names.append(name)
        point = cell(r, "測り点")
        if not any(w in point for w in NEAR_USER):
            rep.fail("測り点", f"SLI「{name}」の測り点「{point}」が利用者に近くない（{'・'.join(NEAR_USER)} のどれかで測る）")
        if not cell(r, "有効") or not cell(r, "良い"):
            rep.fail("SLI", f"SLI「{name}」に有効な要求か良い要求の定めが無い")
    # 目標と期間
    _, goals = table_with(find_section(secs, "目標と期間"), "SLI", "目標", "期間")
    slo = {}
    if not goals:
        rep.fail("目標と期間", "目標と期間の表（SLI・目標・期間）が無い")
    for r in goals:
        name, t, per = cell(r, "SLI"), pct(cell(r, "目標")), minutes(cell(r, "期間"))
        if t is None or not 0 < t < 100:
            rep.fail("目標と期間", f"SLI「{name}」の目標が 0〜100% の数でない")
        if per is None or per < 1440:
            rep.fail("目標と期間", f"SLI「{name}」の期間が日で書かれていない")
        if name not in names:
            rep.fail("目標と期間", f"目標の SLI「{name}」が SLI の表に無い")
        slo[name] = (t, per)
    for n in names:
        if n not in slo:
            rep.fail("目標と期間", f"SLI「{n}」に目標と期間が無い")
    # 承認
    _, apps = table_with(find_section(secs, "承認"), "承認者", "日付")
    good_app = [r for r in apps if cell(r, "承認者") and not PLACEHOLDER.search(cell(r, "承認者"))
                and DATE.search(cell(r, "日付")) and "承認" in (cell(r, "判断") or "承認")]
    if not good_app:
        rep.fail("承認者", "承認者・日付・判断（承認）のそろった行が無い。承認者の無い SLO は出さない")
    # エラーバジェットの扱い
    body = "\n".join(find_section(secs, "エラーバジェットの扱い") or [])
    if "使い切" not in body or not any(w in body for w in ("止め", "凍結", "リリース")):
        rep.fail("エラーバジェットの扱い", "使い切ったときの決まり（リリースを止める等）が書かれていない")
    # 通知の設計と Runbook
    _, alerts = table_with(find_section(secs, "通知の設計"), "通知", "SLI", "重さ", "長い窓", "バーンレート", "Runbook")
    if not alerts:
        rep.fail("通知", "通知の表（通知・SLI・重さ・長い窓・バーンレート・Runbook）が無い")
    book_of, alert_of = {}, {}
    pages = set()
    for r in alerts:
        a, s, sev = cell(r, "通知").strip("`"), cell(r, "SLI"), cell(r, "重さ")
        if s not in slo:
            rep.fail("通知", f"通知「{a}」の SLI「{s}」が目標の表に無い（原因だけの通知は作らない）")
        if sev not in SEVERITY:
            rep.fail("通知", f"通知「{a}」の重さ「{sev}」が {'・'.join(SEVERITY)} でない")
        if sev == "呼び出し":
            pages.add(s)
        lo, sh = minutes(cell(r, "長い窓")), minutes(cell(r, "短い窓"))
        if lo is None or sh is None or sh >= lo:
            rep.fail("通知", f"通知「{a}」の窓が多窓でない（短い窓 < 長い窓にする）")
        m = re.search(r"`([^`]+\.md)`|\(([^)]+\.md)\)", cell(r, "Runbook"))
        if not m:
            rep.fail("Runbook", f"通知「{a}」に Runbook への結びが無い")
            continue
        rb = m.group(1) or m.group(2)
        if book_of.setdefault(a, rb) != rb:
            rep.fail("Runbook", f"通知「{a}」に Runbook が 2 本ある（通知 1 つに 1 本）")
        if alert_of.setdefault(rb, a) != a:
            rep.fail("Runbook", f"Runbook「{rb}」を 2 つの通知が使う（通知 1 つに 1 本）")
    for s in slo:
        if alerts and s not in pages:
            rep.fail("通知", f"SLI「{s}」に呼び出しの通知が無い")
    for a, rb in book_of.items():
        f = (p.parent / rb).resolve()
        if not f.is_file():
            rep.fail("Runbook", f"通知「{a}」の Runbook「{rb}」が無い")
            continue
        rtext = f.read_text(encoding="utf-8")
        rsecs = sections(rtext)
        for key in RUNBOOK_SECTIONS:
            if find_section(rsecs, key) is None:
                rep.fail("Runbook の節", f"{rb} に「## {key}」が無い")
        for key in COMMAND_SECTIONS:
            b = find_section(rsecs, key)
            if b is not None and not any(c.strip() for c in code_blocks(b)):
                rep.fail("Runbook の命令", f"{rb} の「{key}」に命令のコードが無い")
        b = find_section(rsecs, "どれにも合わないとき")
        if b is not None and "2 番手" not in "\n".join(b):
            rep.fail("表の外", f"{rb} の「どれにも合わないとき」に、2 番手へ知らせる手が無い")
        if a not in rtext:
            rep.fail("Runbook", f"{rb} に通知の名前「{a}」が無い")
    rep.note(f"SLI {len(slis)}、通知の行 {len(alerts)}、Runbook {len(book_of)} 本、承認の行 {len(good_app)}")
    return rep


# ---- burn-rate
def check_burn_doc(path):
    rep = Report("burn-rate", str(path))
    p = pathlib.Path(path)
    if not p.is_file():
        rep.fail("無い", "ファイルが無い")
        return rep
    secs = sections(p.read_text(encoding="utf-8"))
    _, goals = table_with(find_section(secs, "目標と期間"), "SLI", "目標", "期間")
    slo = {cell(r, "SLI"): (pct(cell(r, "目標")), minutes(cell(r, "期間"))) for r in goals}
    _, alerts = table_with(find_section(secs, "通知の設計"), "通知", "予算の消費", "長い窓", "バーンレート")
    if not slo or not alerts:
        rep.fail("表", "目標と期間の表か、通知の表（予算の消費・長い窓・バーンレート）が無い")
        return rep
    for r in alerts:
        a, s = cell(r, "通知").strip("`"), cell(r, "SLI")
        if s not in slo or None in slo[s]:
            rep.fail("表", f"通知「{a}」の SLI「{s}」の目標と期間が読めない")
            continue
        t, per = slo[s]
        c, lo = pct(cell(r, "予算の消費")), minutes(cell(r, "長い窓"))
        if c is None or lo is None:
            rep.fail("表", f"通知「{a}」の予算の消費か長い窓が読めない")
            continue
        want = tier(t, per, c, lo)
        got = {"burn": num(cell(r, "バーンレート")), "threshold_pct": pct(cell(r, "閾値")),
               "short": minutes(cell(r, "短い窓")), "exhaust": minutes(cell(r, "使い切る"))}
        label = {"burn": "バーンレート", "threshold_pct": "失敗率の閾値", "short": "短い窓", "exhaust": "使い切るまで"}
        for k, v in want.items():
            if not close(v, got[k]):
                shown = f"{v:.4g}%" if k == "threshold_pct" else (show_min(v) if k in ("short", "exhaust") else f"{v:.4g}")
                rep.fail("食い違い", f"通知「{a}」の{label[k]}が「{cell(r, label[k][:4]) or got[k]}」。計算は {shown}")
        rep.note(f"{a}: 目標 {t:g}% 期間 {show_min(per)} 消費 {c:g}% 長い窓 {show_min(lo)} → バーンレート {want['burn']:.4g}、"
                 f"閾値 {want['threshold_pct']:.4g}%、短い窓 {show_min(want['short'])}、使い切るまで {show_min(want['exhaust'])}")
    return rep


def calc(slo_pct, period_min, tiers, burns):
    print(f"SLO {slo_pct:g}% 期間 {show_min(period_min)} エラーバジェット {100 - slo_pct:.4g}%（全部が失敗なら {show_min(period_min * (100 - slo_pct) / 100)} で使い切る）")
    for c, lo, sev in tiers:
        w = tier(slo_pct, period_min, c, lo)
        print(f"TIER {sev} 予算の消費={c:g}% 長い窓={show_min(lo)} 短い窓={show_min(w['short'])} バーンレート={w['burn']:.4g}"
              f" 失敗率の閾値={w['threshold_pct']:.4g}% 使い切るまで={show_min(w['exhaust'])}")
    for b in burns:
        print(f"EXHAUST バーンレート={b:g} 失敗率={b * (100 - slo_pct):.4g}% 使い切るまで={show_min(period_min / b)}")
    return True


def check_reference(path):
    """原典の値を写した照合の表（タブ区切り）と、計算を突き合わせる。
    行: exhaust <目標%> <期間> <バーンレート> <失敗率> <使い切るまで>   /   tier <目標%> <期間> <消費%:長い窓> <バーンレート> <短い窓>
        threshold <目標%> <期間> <消費%:長い窓> <失敗率の閾値>"""
    rep = Report("burn-rate", str(path))
    rows = [ln.split("\t") for ln in pathlib.Path(path).read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")]
    for i, r in enumerate(rows, 1):
        kind, t, per = r[0], float(r[1]), minutes(r[2])
        if kind == "exhaust":
            b = float(r[3])
            got = (b * (100 - t), per / b)
            want = (pct(r[4]), minutes(r[5]))
        elif kind in ("tier", "threshold"):
            c, lo = r[3].split(":")
            w = tier(t, per, pct(c), minutes(lo))
            got = (w["burn"], w["short"]) if kind == "tier" else (w["threshold_pct"],)
            want = (float(r[4]), minutes(r[5])) if kind == "tier" else (pct(r[4]),)
        else:
            rep.fail("照合の表", f"{i} 行目の種類「{kind}」を知らない")
            continue
        for g, w in zip(got, want):
            if not close(g, w):
                rep.fail("原典と不一致", f"{i} 行目 {' '.join(r)}: 計算 {g:.4g}、原典 {w}")
        rep.note(f"{i} 行目 {kind} {' '.join(r[1:])} → 計算 {', '.join(f'{g:.4g}' for g in got)}")
    if not rows:
        rep.fail("照合の表", "行が無い")
    return rep


def parse_tiers(s):
    out = []
    for part in s.split(","):
        c, lo, sev = part.split(":")
        out.append((pct(c) if "%" in c else float(c), minutes(lo), sev))
    return out


# ---- 自己試験
GOOD_SLO = """# SLO 定義書: 見本

## SLI（測り点と数え方）

| SLI | 測り点 | 有効な要求 | 良い要求 |
|---|---|---|---|
| 可用性 | ロードバランサーの記録 | GET の要求 | 200 の要求 |

## 目標と期間

| SLI | 目標 | 期間 |
|---|---|---|
| 可用性 | 99.9% | 30 日 |

## 承認

| 承認者 | 立場 | 日付 | 判断 |
|---|---|---|---|
| 見本の責任者 | 事業 | 2026-11-06 | 承認 |

## エラーバジェットの扱い

使い切ったら機能のリリースを止めます。

## 通知の設計

| 通知 | SLI | 重さ | 予算の消費 | 長い窓 | 短い窓 | バーンレート | 失敗率の閾値 | 使い切るまで | Runbook |
|---|---|---|---|---|---|---|---|---|---|
| `AvailPage` | 可用性 | 呼び出し | 2% | 1 時間 | 5 分 | 14.4 | 1.44% | 50 時間 | `rb-page.md` |
| `AvailPage` | 可用性 | 呼び出し | 5% | 6 時間 | 30 分 | 6 | 0.6% | 120 時間 | `rb-page.md` |
| `AvailTicket` | 可用性 | チケット | 10% | 3 日 | 6 時間 | 1 | 0.1% | 30 日 | `rb-ticket.md` |
"""
GOOD_RB = "# Runbook: {a}\n\n" + "".join(f"## {s}\n\n本文。2 番手へ知らせる。\n\n```sh\necho {s}\n```\n\n" for s in RUNBOOK_SECTIONS)


def selftest(kind):
    ok = True
    with tempfile.TemporaryDirectory() as tmp:
        base = pathlib.Path(tmp)

        def make(name, text, books=("rb-page.md", "rb-ticket.md"), rb_text=None):
            d = base / name
            d.mkdir()
            (d / "slo.md").write_text(text, encoding="utf-8")
            for b, a in zip(books, ("AvailPage", "AvailTicket")):
                (d / b).write_text(rb_text if rb_text is not None else GOOD_RB.format(a=a), encoding="utf-8")
            return d / "slo.md"

        def expect(label, rep, rule):
            nonlocal ok
            if rule is None and rep.items:
                ok = False
                print(f"FAIL selftest {kind}: 正例「{label}」が落ちた: {rep.items}")
            elif rule is not None and rule not in rep.rules():
                ok = False
                print(f"FAIL selftest {kind}: 負例「{label}」が [{rule}] で落ちない（検出: {sorted(rep.rules())}）")

        n = 0
        if kind == "slo":
            cases = [
                ("正例", make("good", GOOD_SLO), None),
                ("承認者が空", make("noapp", GOOD_SLO.replace("| 見本の責任者 |", "|  |")), "承認者"),
                ("承認の節が無い", make("nosec", GOOD_SLO.replace("## 承認\n", "## 記録\n")), "必須の節"),
                ("測り点が DB", make("point", GOOD_SLO.replace("ロードバランサーの記録", "DB の CPU")), "測り点"),
                ("期間が無い", make("period", GOOD_SLO.replace("| 30 日 |", "| 毎月 |")), "目標と期間"),
                ("バジェットの決まりが無い", make("budget", GOOD_SLO.replace("使い切ったら機能のリリースを止めます。", "未記入。")), "エラーバジェットの扱い"),
                ("Runbook の欄が空", make("norb", GOOD_SLO.replace("`rb-ticket.md` |", " |")), "Runbook"),
                ("Runbook が無い", make("missing", GOOD_SLO, books=("rb-page.md",)), "Runbook"),
                ("Runbook の節の欠け", make("rbsec", GOOD_SLO, rb_text=GOOD_RB.format(a="AvailPage AvailTicket").replace("## 戻し方", "## 後で")), "Runbook の節"),
                ("表の外の節が無い", make("noout", GOOD_SLO, rb_text=GOOD_RB.format(a="AvailPage AvailTicket").replace("## どれにも合わないとき", "## 後で")), "Runbook の節"),
                ("表の外で 2 番手へ知らせない", make("no2nd", GOOD_SLO, rb_text=GOOD_RB.format(a="AvailPage AvailTicket").replace("本文。2 番手へ知らせる。", "本文。")), "表の外"),
                ("原因だけの通知", make("cause", GOOD_SLO.replace("| `AvailTicket` | 可用性 |", "| `AvailTicket` | CPU |")), "通知"),
                ("穴埋めのまま", make("hole", GOOD_SLO.replace("見本の責任者", "〈承認者の名前〉")), "穴埋め"),
            ]
            for label, path, rule in cases:
                expect(label, check_slo(path), rule)
            n = len(cases)
        else:
            cases = [
                ("正例", make("good", GOOD_SLO), None),
                ("バーンレートの食い違い", make("burn", GOOD_SLO.replace("| 14.4 | 1.44% |", "| 12 | 1.44% |")), "食い違い"),
                ("閾値の食い違い", make("thr", GOOD_SLO.replace("| 6 | 0.6% |", "| 6 | 6% |")), "食い違い"),
                ("短い窓の食い違い", make("short", GOOD_SLO.replace("| 3 日 | 6 時間 |", "| 3 日 | 1 時間 |")), "食い違い"),
                ("使い切るまでの食い違い", make("exh", GOOD_SLO.replace("| 50 時間 |", "| 5 時間 |")), "食い違い"),
            ]
            for label, path, rule in cases:
                expect(label, check_burn_doc(path), rule)
            # 原典の値（Workbook の表）と照らす
            for c, lo, burn in ((2, 60, 14.4), (5, 360, 6), (10, 4320, 1)):
                w = tier(99.9, 43200, c, lo)
                if not close(w["burn"], burn):
                    ok = False
                    print(f"FAIL selftest burn: 消費 {c}% 窓 {lo} 分で {w['burn']}（原典 {burn}）")
            for b, mins in ((1, 43200), (2, 21600), (10, 4320), (1000, 43.2)):
                if not close(43200 / b, mins):
                    ok = False
                    print(f"FAIL selftest burn: バーンレート {b} の使い切るまで")
            n = len(cases) + 7
    print(f"RESULT: {'PASS' if ok else 'FAIL'} {NAMES[kind]} --selftest ({n} 例)")
    return ok


def main(argv):
    if len(argv) < 2 or argv[0] not in NAMES:
        print(__doc__)
        return 2
    kind, args = argv[0], argv[1:]
    if args == ["--selftest"]:
        return 0 if selftest(kind) else 1
    if kind == "slo":
        ok = all([check_slo(a).show() for a in args])
        return 0 if ok else 1
    if args[0].startswith("--") and args[0] != "--reference":
        opts = {"--slo": None, "--period": "30d", "--tiers": None, "--burn": None}
        it = iter(args)
        for a in it:
            if a not in opts:
                print(f"知らない引数: {a}")
                return 2
            opts[a] = next(it, None)
        if opts["--slo"] is None:
            print("--slo <目標の %> が要る")
            return 2
        t, per = float(opts["--slo"].rstrip("%")), minutes(opts["--period"])
        tiers = parse_tiers(opts["--tiers"]) if opts["--tiers"] else DEFAULT_TIERS
        burns = [float(b) for b in opts["--burn"].split(",")] if opts["--burn"] else []
        calc(t, per, tiers, burns)
        return 0
    if args[0] == "--reference" and len(args) == 2:
        return 0 if check_reference(args[1]).show() else 1
    ok = all([check_burn_doc(a).show() for a in args])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
