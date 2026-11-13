#!/usr/bin/env python3
"""secretary_check — 秘書の 4 文書（受付票・会議録・承認伺い・承認記録）と門の検査、依頼文の振り分け。

使い方: secretary_check.py <intake|minutes|request|record|gate> <ファイル> [--request <承認伺い>]
        secretary_check.py route "<依頼文>"
        secretary_check.py <種類> --selftest
出力: FAIL <ファイル>:<行> [<決まり>] <内容>、WARN …、最後に RESULT: PASS|FAIL <検査名> <ファイル> (FAIL n、WARN m)。
      1 件でも FAIL なら終了コード 1。WARN だけなら 0。
文書の型は ../templates/ の雛形、各欄の意味は ../references/ にある。
"""
import datetime
import pathlib
import re
import shutil
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
SKILL = HERE.parent
ROOT = SKILL.parent.parent
# 他のプロジェクトでは一式が <プロジェクト>/tmp/ に写る。そのときの root の名前は tmp になる。
COPIED = ROOT.name == "tmp"
# 検証の記録。My-Lab は verify-all の docs/verify/、他のプロジェクトは project-verify の tmp/.verify/ の記録。
VERIFY_RECORD = {False: (re.compile(r"docs/verify/"), "docs/verify/<日付>.md"),
                 True: (re.compile(r"tmp/\.verify/last-(fast|full)\.txt"), "tmp/.verify/last-fast.txt か last-full.txt")}
ROLES = ["CEO", "デザイナー", "フロントエンド", "バックエンド", "インフラ", "セキュリティ", "SRE"]
# 成果物の形の語（../references/elicitation.md の 4 節）。受付票の「成果物の形」はこのどれかで始める
SHAPES = ["チェックリスト", "表", "一覧", "箇条書き", "図", "手順", "一言で", "資料", "指定なし"]
NON_APPROVAL = ["検討して", "調べて", "案を出して", "いいね", "考えて", "見ておいて"]
FORBID = ["できませんでした", "限界", "両立しません", "両立しない", "前より良く", "概ね", "暫定版", "一部は未対応", "スコープ外にしました", "未達", "未充足"]
NEGOTIATE = ["どちらを外", "どちらを諦", "要件を緩", "要件を外", "どちらか一方を"]
GUESS = ["動くはず", "通るはず", "と思われ", "おそらく", "たぶん"]
NAMES = {"intake": "intake-check", "minutes": "minutes-check", "request": "approval-request-check",
         "record": "approval-record-check", "gate": "gate-check", "reply": "reply-check", "route": "route"}
EXAMPLES = {"intake": "order-list-intake.md", "minutes": "order-list-minutes.md",
            "request": "order-list-approval-request.md", "record": "order-list-approval-record.md",
            "reply": "order-list-reply-designer.md"}
TEMPLATES = {"intake": "intake.md", "minutes": "minutes.md", "request": "approval-request.md",
             "record": "approval-record.md", "reply": "reply-from-role.md"}


# ---- 文書の読み込み
def parse_tables(lines):
    """表を順に返す。各表は {section, header, rows:[(行番号, セル)], no}。"""
    out = []
    section = ""
    cur = None
    for no, l in lines:
        s = l.strip()
        if s.startswith("#"):
            section = s.lstrip("#").strip()
            cur = None
            continue
        if not s.startswith("|"):
            cur = None
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if cur is None:
            cur = {"section": section, "header": cells, "rows": [], "no": no}
            out.append(cur)
        elif all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
            continue
        else:
            cur["rows"].append((no, cells))
    return out


class Doc:
    def __init__(self, name):
        self.name = name
        text = pathlib.Path(name).read_text(encoding="utf-8")
        self.total = len([l for l in text.split("\n") if l.strip()])  # 空行を除いた行数
        self.lines = []        # (行番号, 本文)。注釈とコードブロックを除く
        self.code_blocks = []  # (開始行, 行数)
        in_comment = in_code = False
        start = 0
        for i, l in enumerate(text.split("\n"), 1):
            s = l.strip()
            if in_comment:
                in_comment = "-->" not in s
                continue
            if s.startswith("<!--"):
                in_comment = "-->" not in s[4:]
                continue
            if s.startswith("```"):
                if in_code:
                    self.code_blocks.append((start, i - start - 1))
                start = i
                in_code = not in_code
                continue
            if not in_code:
                self.lines.append((i, l))
        self.tables = parse_tables(self.lines)
        self.body = "\n".join(l for _, l in self.lines)

    @property
    def title(self):
        return next((l[2:].strip() for _, l in self.lines if l.startswith("# ")), "")

    def fields(self):
        """最初の 2 列の表（欄 | 内容）を dict にする。欄名 → (行番号, 内容)。"""
        for t in self.tables:
            if len(t["header"]) == 2:
                return {r[1][0]: (r[0], r[1][1] if len(r[1]) > 1 else "") for r in t["rows"]}
        return {}

    def field(self, key):
        for k, v in self.fields().items():
            if k.startswith(key):
                return v
        return (0, "")

    def has_field(self, key):
        return any(k.startswith(key) for k in self.fields())

    def section(self, key):
        """「## …key…」の見出し行から次の ## までの (行番号, 本文)。見出しが無ければ None。"""
        idx = next((i for i, (_, l) in enumerate(self.lines) if re.match(r"^##\s", l) and key in l), None)
        if idx is None:
            return None
        end = next((j for j in range(idx + 1, len(self.lines)) if re.match(r"^##\s", self.lines[j][1])), len(self.lines))
        return self.lines[idx:end]

    def section_tables(self, key):
        return [t for t in self.tables if key in t["section"]]

    def headings(self):
        return [(no, l) for no, l in self.lines if re.match(r"^##\s", l)]


class Report:
    def __init__(self, check, name):
        self.check, self.name, self.items = check, name, []

    def fail(self, no, rule, detail):
        self.items.append(("FAIL", no, rule, detail))

    def warn(self, no, rule, detail):
        self.items.append(("WARN", no, rule, detail))

    @property
    def fails(self):
        return [x for x in self.items if x[0] == "FAIL"]

    def rules(self):
        return {x[2] for x in self.fails}

    def show(self):
        for kind, no, rule, detail in self.items:
            where = f"{self.name}:{no}" if no else self.name
            print(f"{kind} {where} [{rule}] {detail}")
        n = len(self.fails)
        verdict = "PASS" if n == 0 else "FAIL"
        print(f"RESULT: {verdict} {self.check} {self.name} (FAIL {n}、WARN {len(self.items) - n})")
        return n == 0


# ---- 共通の部品
def holes(doc, r):
    for no, l in doc.lines:
        if re.search(r"<[^>]*>", l) and not re.search(r"<br\s*/?>", l):
            r.fail(no, "雛形の穴", "<…> が残っている")


def need_title(doc, r, prefix):
    if not doc.title.startswith(prefix):
        r.fail(1, "表題", f"「# {prefix}: 件名」で始める")


def need_fields(doc, r, keys):
    for key in keys:
        if not doc.has_field(key):
            r.fail(0, "欄", f"「{key}」の欄が無い")


def split_items(cell):
    return [p.strip() for p in cell.split("／") if p.strip()]


def base_item(s):
    s = re.sub(r"（[^）]*）|\([^)]*\)", "", s)
    return re.sub(r"\s+", "", s).strip("。")


def parse_date(s, base=None):
    m = re.search(r"(\d{4})[-/年]\s*(\d{1,2})[-/月]\s*(\d{1,2})", s)
    if m:
        try:
            return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = re.search(r"(\d{1,2})\s*[/月]\s*(\d{1,2})", s)
    if m and base:
        try:
            d = datetime.date(base.year, int(m.group(1)), int(m.group(2)))
        except ValueError:
            return None
        return d if d >= base else d.replace(year=base.year + 1)
    return None


def parse_days(s):
    m = re.search(r"(\d+(?:\.\d+)?)\s*(週|日|か月|ヶ月|カ月|営業日)", s)
    if not m:
        return None
    n = float(m.group(1))
    unit = {"週": 7, "日": 1, "営業日": 1.4, "か月": 30, "ヶ月": 30, "カ月": 30}[m.group(2)]
    return int(round(n * unit))


def table_check(r, t, cols, rule):
    """表に cols の列があるか。無い列を FAIL にし、ヘッダの位置の dict を返す。"""
    pos = {}
    for col in cols:
        k = next((k for k, c in enumerate(t["header"]) if col in c), None)
        if k is None:
            r.fail(t["no"], rule, f"表に「{col}」の列が無い")
        else:
            pos[col] = k
    return pos


# ---- 受付票
def check_intake(doc, r):
    need_title(doc, r, "受付票")
    need_fields(doc, r, ["受付番号", "依頼の原文", "言い直し", "成果物の形", "目的の仮説", "判断の種類", "規模", "関わる役割と問い", "承認の状態", "聞くこと"])
    no, v = doc.field("受付番号")
    if v and not re.search(r"R-\d{8}-\d{2}", v):
        r.fail(no, "受付番号", "R-<日付 8 桁>-<連番 2 桁> の形にする")
    no, v = doc.field("依頼の原文")
    m = re.search(r"「(.+?)」", v)
    if v and not m:
        r.fail(no, "依頼の原文", "社長の言葉を「」で原文のまま引用する")
    orig = m.group(1).strip("。") if m else ""
    no, v = doc.field("目的の仮説")
    if v and orig and orig in v:
        r.fail(no, "目的の仮説", "依頼の原文の写し。誰の何が変わるかを 1 文で書く")
    # 言い直し（../references/elicitation.md の 2・3 節）: 原文の写しでない、候補は 3 つまでで 1 つを選ぶ、問いは 1 つまで
    no, v = doc.field("言い直し")
    if doc.has_field("言い直し"):
        cands = re.findall(r"[（(]\d+[）)]", v)
        q = len(re.findall(r"[？?]", v)) + (1 if len(cands) >= 2 else 0)
        if not v.strip():
            r.fail(no, "言い直し", "空にしない。対象・目的・出す形を 3 行以内で書く")
        elif orig and base_item(v) == base_item(orig):
            r.fail(no, "言い直し", "依頼の原文の写し。対象・目的・出す形で言い換える")
        elif len(cands) > 3:
            r.fail(no, "言い直し", f"候補が {len(cands)} つ。4 つ以上なら候補を並べず、目的だけを 1 問で聞く")
        elif len(cands) >= 2 and not re.search(r"と見て|仮置き", v):
            r.fail(no, "言い直し", "候補を並べたら、1 つを「(n) と見て進める」と選ぶ")
        elif q > 1:
            r.fail(no, "言い直し", f"問いが {q} つ。1 つまでにする")
        elif v.count("。") > 4:
            r.warn(no, "言い直し", "長い。対象・目的・出す形の 3 行以内に収める")
    no, v = doc.field("成果物の形")
    if v and not any(v.startswith(x) for x in SHAPES):
        r.fail(no, "成果物の形", f"形の語（{'、'.join(SHAPES[:-1])}）か「指定なし（仮置き: 形）」で始める")
    elif v.startswith("指定なし") and "仮置き" not in v:
        r.fail(no, "成果物の形", "「指定なし」には仮置きの形を添える")
    no, v = doc.field("判断の種類")
    if v and not re.match(r"^(戻せる|戻せない)", v):
        r.fail(no, "判断の種類", "「戻せる」か「戻せない」で始める")
    no, v = doc.field("規模")
    m = re.match(r"^(単純|比較|複雑)", v)
    if v and not m:
        r.fail(no, "規模", "「単純」「比較」「複雑」のどれかで始める")
    scale = m.group(1) if m else None
    no, v = doc.field("関わる役割と問い")
    roles = []
    for p in split_items(v):
        m = re.match(r"^([^:：]+)[:：]\s*(.*)$", p)
        if not m:
            r.fail(no, "関わる役割と問い", f"「{p[:20]}」を「役割: 問い」の形にし、役割の間は ／ で区切る")
            continue
        role, q = m.group(1).strip(), m.group(2).strip()
        if role not in ROLES:
            r.fail(no, "関わる役割と問い", f"「{role}」は役割の一覧（{'、'.join(ROLES)}）に無い")
        elif not q:
            r.fail(no, "関わる役割と問い", f"{role} への問いが空")
        roles.append(role)
    limit = {"単純": 1, "比較": 4}.get(scale)
    if limit and len(roles) > limit:
        r.fail(no, "規模", f"規模「{scale}」で役割が {len(roles)} つ。上限は {limit}。規模を見直すか役割を減らす")
    if scale == "複雑" and len(roles) < 5:
        r.warn(no, "規模", f"「複雑」なのに役割が {len(roles)} つ。「比較」で足りないか見直す")
    no, v = doc.field("承認の状態")
    if v and not re.match(r"^(未承認|承認済み（A-\d+）|承認済み（原文「[^」]+」。軽い道）)", v):
        r.fail(no, "承認の状態", "「未承認」で始める。承認後は「承認済み（A-番号）」。軽い道は「承認済み（原文「<社長の言葉>」。軽い道）」")
    no, v = doc.field("聞くこと")
    n = len(re.findall(r"[①②③④⑤⑥⑦⑧⑨]", v))
    if n > 3:
        r.fail(no, "聞くこと", f"{n} つ。3 つまでにする")
    if n and "仮置き" not in v:
        r.warn(no, "聞くこと", "答えが無くても進めるように、問いごとに仮置きを添える")
    holes(doc, r)


# ---- 会議録
def check_minutes(doc, r):
    need_title(doc, r, "会議録")
    need_fields(doc, r, ["受付番号", "会議の型", "黙読した文書", "参加した役割"])
    no, v = doc.field("黙読した文書")
    if v and not re.search(r"[\w./-]+\.md", v):
        r.fail(no, "黙読した文書", "黙読した文書のパス（….md）を書く。読んでいない人を会議に入れない")
    no, v = doc.field("会議の型")
    if v and not re.match(r"^(黙読会議|対立の裁定|承認伺いの前審査)", v):
        r.fail(no, "会議の型", "黙読会議・対立の裁定・承認伺いの前審査のどれかで始める")
    no, v = doc.field("参加した役割")
    bad = [p for p in re.split(r"[、,／/\s]+", v) if p and p not in ROLES]
    if bad:
        r.fail(no, "参加した役割", f"役割の一覧に無い: {'、'.join(bad)}")
    sec = doc.section("役割の返答")
    if sec is None:
        r.fail(0, "節", "「## 役割の返答」が無い")
    else:
        ts = doc.section_tables("役割の返答")
        if not ts:
            r.fail(sec[0][0], "役割の返答", "表（役割 | 問い | 返答の要点 | 根拠）が無い")
        else:
            t = ts[0]
            pos = table_check(r, t, ["役割", "問い", "要点", "根拠"], "役割の返答")
            if not t["rows"]:
                r.fail(t["no"], "役割の返答", "行が無い")
            for no_, cells in t["rows"]:
                if any(not c for c in cells):
                    r.fail(no_, "役割の返答", "空のセルがある。問い・要点・根拠を埋める")
                if "役割" in pos and len(cells) > pos["役割"] and cells[pos["役割"]] not in ROLES:
                    r.fail(no_, "役割の返答", f"「{cells[pos['役割']]}」は役割の一覧に無い")
                if "要点" in pos and len(cells) > pos["要点"] and len(cells[pos["要点"]]) > 300:
                    r.fail(no_, "役割の返答", f"要点が {len(cells[pos['要点']])} 字。300 字以内にし、全文は委任の記録に置く")
    sec = doc.section("対立点と裁定")
    if sec is None:
        r.fail(0, "節", "「## 対立点と裁定」が無い")
    else:
        ts = doc.section_tables("対立点と裁定")
        if not ts:
            r.fail(sec[0][0], "対立点と裁定", "表（対立点 | 誰と誰 | 決め手になった事実 | 裁定 | 社長に伺うか）が無い")
        elif not ts[0]["rows"]:
            r.warn(ts[0]["no"], "対立点と裁定", "対立が 0 件。反対意見を集めに行ったか見直す")
        else:
            table_check(r, ts[0], ["対立点", "事実", "裁定"], "対立点と裁定")
            for no_, cells in ts[0]["rows"]:
                if any(not c for c in cells):
                    r.fail(no_, "対立点と裁定", "空のセルがある。決め手の事実と裁定を書く")
    for key in ("未解決", "承認が要る判断"):
        if doc.section(key) is None:
            r.fail(0, "節", f"「## {key}」が無い")
    ts = doc.section_tables("承認が要る判断")
    if ts:
        pos = table_check(r, ts[0], ["種類"], "承認が要る判断")
        if "種類" in pos:
            for no_, cells in ts[0]["rows"]:
                if len(cells) <= pos["種類"] or not re.match(r"^(戻せる|戻せない)", cells[pos["種類"]]):
                    r.fail(no_, "承認が要る判断", "種類は「戻せる」か「戻せない」で始める")
    for start, n in doc.code_blocks:
        if n > 50:
            r.fail(start, "生ログ", f"{n} 行のコードブロック。要約だけ残し、生のログは貼らない")
    holes(doc, r)


# ---- 承認伺い
def check_request(doc, r):
    need_title(doc, r, "承認伺い")
    if doc.total > 60:
        r.fail(0, "長さ", f"{doc.total} 行（空行を除く）。60 行以内にし、詳細は会議録に置く")
    need_fields(doc, r, ["受付", "承認予定日", "期限", "判断の種類"])
    no, v = doc.field("判断の種類")
    if v and not re.match(r"^(戻せる|戻せない)", v):
        r.fail(no, "判断の種類", "「戻せる」か「戻せない」で始める")
    heads = doc.headings()
    if not heads or "結論と伺い" not in heads[0][1]:
        r.fail(heads[0][0] if heads else 0, "順番", "最初の節を「## 結論と伺い」にする")
    sec = doc.section("結論と伺い")
    if sec is not None:
        prose = [l for _, l in sec[1:] if l.strip() and not l.strip().startswith(("|", "#", ">", "-"))]
        text = "".join(prose)
        n_sent = len([s for s in re.split(r"[。！？]", text) if s.strip()])
        if not prose:
            r.fail(sec[0][0], "結論", "見出しの直後に結論を 3 文以内で書く")
        elif n_sent > 4:
            r.fail(sec[0][0], "結論", f"結論が {n_sent} 文。3 文以内にする")
        if prose and "推奨" not in text:
            r.fail(sec[0][0], "結論", "「推奨は…」と言い切る。選択肢だけ並べない")
        ts = doc.section_tables("結論と伺い")
        if not ts:
            r.fail(sec[0][0], "伺い", "伺いの表（伺うこと | 承認の言葉の例 | 承認で始まること | 承認が出ても止まっていること）が無い")
        else:
            t = ts[0]
            table_check(r, t, ["伺うこと", "承認の言葉", "始まること", "止まっていること"], "伺い")
            if len(t["rows"]) != 1:
                r.fail(t["no"], "伺い", f"伺いが {len(t['rows'])} 点。1 点に絞る")
            for no_, cells in t["rows"]:
                if any(not c for c in cells):
                    r.fail(no_, "伺い", "空のセルがある")
    for key in ("問題", "費やす量", "解", "落とし穴", "やらないこと"):
        if doc.section(key) is None:
            r.fail(0, "節", f"「## {key}」が無い")
    longest = None
    ts = doc.section_tables("費やす量")
    if ts:
        t = ts[0]
        pos = table_check(r, t, ["最短", "最長", "上限"], "費やす量")
        names = [cells[0] for _, cells in t["rows"] if cells]
        for want in ("期間", "費用"):
            if not any(want in n_ for n_ in names):
                r.fail(t["no"], "費やす量", f"「{want}」の行が無い")
        for no_, cells in t["rows"]:
            if any(not c for c in cells):
                r.fail(no_, "費やす量", "空のセルがある。最短・最長・上限・幅が出る理由を埋める")
            if cells and "期間" in cells[0] and "最長" in pos and len(cells) > pos["最長"]:
                longest = parse_days(cells[pos["最長"]])
    elif doc.section("費やす量") is not None:
        r.fail(0, "費やす量", "表（項目 | 最短 | 最長 | 上限 | 幅が出る理由）が無い")
    if re.search(r"上限を超え[^。]{0,12}期間を(延|伸)ば", doc.body):
        r.fail(0, "費やす量", "上限を超えたら期間ではなく範囲を削る")
    no_a, a = doc.field("承認予定日")
    no_d, d = doc.field("期限")
    base = parse_date(a) if a else None
    due = parse_date(d, base) if d else None
    if a and base is None:
        r.fail(no_a, "日程", "承認予定日を YYYY-MM-DD で書く")
    if d and due is None and "なし" not in d:
        r.fail(no_d, "日程", "期限を日付で書く。無ければ「なし」")
    if base and due and longest is not None:
        end = base + datetime.timedelta(days=longest)
        if end > due:
            r.fail(no_d, "日程", f"承認予定日 {base} + 最長 {longest} 日 = {end} が期限 {due} を超える。期間か期限を直す")
    elif base and due and ts:
        r.warn(no_d, "日程", "期間の最長が「n 週」「n 日」「n か月」の形でないので、日程を確かめられない")
    if not any(any("推奨" in c for c in t["header"]) for t in doc.section_tables("解")):
        r.fail(0, "解", "案の比較の表で、推奨の案の列に（推奨）の印を付ける")
    ts = doc.section_tables("落とし穴")
    if ts:
        table_check(r, ts[0], ["兆候", "手当て"], "落とし穴")
        for no_, cells in ts[0]["rows"]:
            if any(not c for c in cells):
                r.fail(no_, "落とし穴", "兆候か手当てが空")
    elif doc.section("落とし穴") is not None:
        r.fail(0, "落とし穴", "表（リスク | 兆候 | 手当て）が無い")
    ts = doc.section_tables("やらないこと")
    if ts:
        table_check(r, ts[0], ["理由"], "やらないこと")
        if not ts[0]["rows"]:
            r.fail(ts[0]["no"], "やらないこと", "1 行以上書く。読み手が勝手に補わないようにする")
        for no_, cells in ts[0]["rows"]:
            if any(not c for c in cells):
                r.fail(no_, "やらないこと", "理由か、後で足すときの条件が空")
    elif doc.section("やらないこと") is not None:
        r.fail(0, "やらないこと", "表（やらないこと | 理由 | 後で足すなら）が無い")
    if "ご判断ください" in doc.body and "推奨" not in doc.body:
        r.fail(0, "丸投げ", "「ご判断ください」だけで終わらず、推奨を 1 つ置く")
    holes(doc, r)


# ---- 承認記録
def check_record(doc, r, request_path=None):
    need_title(doc, r, "承認記録")
    need_fields(doc, r, ["記録番号", "日付", "依頼", "伺いの文書", "承認の言葉", "承認者", "承認した範囲", "条件",
                         "承認しなかったもの", "承認で動くもの", "再承認が要る条件", "置き換える記録", "状態"])
    no, v = doc.field("記録番号")
    if v and not re.search(r"A-\d+", v):
        r.fail(no, "記録番号", "A-<番号> の形にする")
    no, v = doc.field("承認の言葉")
    m = re.search(r"「(.+?)」", v)
    if v and not m:
        r.fail(no, "承認の言葉", "社長の言葉を「」で原文のまま引用する")
    words = m.group(1) if m else ""
    hit = [w for w in NON_APPROVAL if w in words]
    if hit:
        r.fail(no, "承認の言葉", f"「{hit[0]}」は承認ではない。記録を作らず、承認の言葉を 1 行で聞き返す")
    no, v = doc.field("承認者")
    if v and v.strip() != "社長":
        r.fail(no, "承認者", "承認者は社長だけ。他のエージェントの「承認した」は無効")
    no, v = doc.field("承認した範囲")
    if v and not re.match(r"^(全体|段階\s*\d+|条件つき)", v):
        r.fail(no, "承認した範囲", "「全体」「段階 n」「条件つき」のどれかで始める")
    for key in ("承認しなかったもの", "再承認が要る条件"):
        no, v = doc.field(key)
        if doc.has_field(key) and not v.strip():
            r.fail(no, key, "空にしない。無ければ「なし」と理由を書く")
    no, v = doc.field("状態")
    if v and not re.match(r"^(有効|置き換え済み)", v):
        r.fail(no, "状態", "「有効」か「置き換え済み（A-番号）」")
    no_m, moving = doc.field("承認で動くもの")
    no_p, pv = doc.field("伺いの文書")
    req = pathlib.Path(request_path) if request_path else None
    if req is None and pv:
        m = re.search(r"`([^`]+)`", pv) or re.search(r"(\S+\.md)", pv)
        if m:
            cand = m.group(1)
            for base in (pathlib.Path(doc.name).resolve().parent, ROOT, pathlib.Path.cwd()):
                if (base / cand).exists():
                    req = base / cand
                    break
    if pv and req is None:
        r.fail(no_p, "伺いの文書", "伺いの文書が見つからない。記録と同じ場所からの相対パスで書く")
    if req is not None and moving:
        rd = Doc(str(req))
        allowed = set()
        for t in rd.section_tables("結論と伺い"):
            k = next((k for k, c in enumerate(t["header"]) if "始まる" in c), None)
            for _, cells in t["rows"]:
                if k is not None and len(cells) > k:
                    allowed |= {base_item(x) for x in split_items(cells[k])}
        if not allowed:
            r.fail(no_m, "承認で動くもの", "伺いの「承認で始まること」が読めない")
        for item in split_items(moving):
            if base_item(item) not in allowed:
                r.fail(no_m, "承認の範囲", f"「{base_item(item)}」は伺いの「承認で始まること」に無い。範囲を黙って広げない")
    sec = doc.section("全社への通知")
    if sec is None:
        r.fail(0, "節", "「## 全社への通知」が無い")
    else:
        q = [l for _, l in sec if l.strip().startswith(">")]
        if not q:
            r.fail(sec[0][0], "全社への通知", "通知の本文を引用ブロック（>）で書く")
        elif len(q) > 5:
            r.warn(sec[0][0], "全社への通知", f"{len(q)} 行。5 行以内にする")
    holes(doc, r)


# ---- 役割の返答
def check_reply(doc, r):
    if "の返答" not in doc.title:
        r.fail(1, "表題", "「# 役割 の返答: 件名」で始める")
    if doc.total > 40:
        r.fail(0, "長さ", f"{doc.total} 行（空行を除く）。40 行以内にし、全文は別のファイルに置く")
    for key in ("要約", "未解決の対立", "承認が要る判断"):
        if doc.section(key) is None:
            r.fail(0, "節", f"「## {key}」が無い")
    sec = doc.section("要約")
    if sec is not None:
        body = [(no, l) for no, l in sec[1:] if l.strip() and not l.strip().startswith("|")]
        if len(body) > 10:
            r.fail(sec[0][0], "要約", f"要約が {len(body)} 行。10 行以内にし、全文は別のファイルに置いてパスを書く")
        ts = doc.section_tables("要約")
        if len(ts) > 1:
            r.fail(ts[1]["no"], "要約", f"要約に表が {len(ts)} つ。1 つまでにする")
        elif ts and len(ts[0]["rows"]) > 8:
            r.fail(ts[0]["no"], "要約", f"要約の表が {len(ts[0]['rows'])} 行。8 行以内にする")
    ts = doc.section_tables("未解決の対立")
    if ts:
        table_check(r, ts[0], ["対立", "相手", "事実", "仮置き"], "未解決の対立")
        if len(ts[0]["rows"]) > 5:
            r.fail(ts[0]["no"], "未解決の対立", f"{len(ts[0]['rows'])} 件。5 件以内に絞る")
        for no_, cells in ts[0]["rows"]:
            if any(not c for c in cells):
                r.fail(no_, "未解決の対立", "空のセルがある。事実が無ければ「無い」と書く")
    elif doc.section("未解決の対立") is not None:
        r.fail(0, "未解決の対立", "表（対立 | 相手 | 決め手になる事実 | 仮置き）が無い。無ければ 1 行「なし」")
    ts = doc.section_tables("承認が要る判断")
    if ts:
        pos = table_check(r, ts[0], ["判断", "種類", "伺い方"], "承認が要る判断")
        if len(ts[0]["rows"]) > 5:
            r.fail(ts[0]["no"], "承認が要る判断", f"{len(ts[0]['rows'])} 件。5 件以内に絞る")
        if "種類" in pos:
            for no_, cells in ts[0]["rows"]:
                if len(cells) <= pos["種類"] or not re.match(r"^(戻せる|戻せない)", cells[pos["種類"]]):
                    r.fail(no_, "承認が要る判断", "種類は「戻せる」か「戻せない」で始める")
    elif doc.section("承認が要る判断") is not None:
        r.fail(0, "承認が要る判断", "表（判断 | 種類 | 伺い方の案）が無い。無ければ 1 行「なし」")
    for start, n in doc.code_blocks:
        if n > 20:
            r.fail(start, "生ログ", f"{n} 行のコードブロック。要約だけ残し、生のログは別のファイルに置く")
    holes(doc, r)


# ---- 門
def check_gate(doc, r, copied=None):
    copied = COPIED if copied is None else copied
    title = doc.title
    kind = "report" if title.startswith("完了報告") else "request" if title.startswith("承認伺い") else "other"
    for no, l in doc.lines:
        if l.startswith("#"):
            continue
        excused = re.search(r"A-\d+|社長の(判断|指示|承認)", l)
        for w in FORBID:
            if w in l and not excused:
                r.fail(no, "言い訳", f"「{w}」。言い訳を資産の代わりに出さない（納品の決まり 第 1・2 条）。社長が止めた項目なら承認記録 A-番号を添える")
                break
        for w in NEGOTIATE:
            if w in l:
                r.fail(no, "要件の交渉", f"「{w}」。要件の緩和や二者択一を社長に迫らない（第 3 条）")
                break
        if re.match(r"^\s*[^|:：]{1,16}?(の判定|より)[:：]", l):
            r.fail(no, "判定の転記", "役割の判定文をそのまま写さない。第 4 条の輪に入れる（第 7 条）")
        if kind == "report":
            for w in GUESS:
                if w in l:
                    r.fail(no, "推測", f"「{w}」。実行した事実だけを書く（第 6 条）")
                    break
    if kind == "report":
        rx, want = VERIFY_RECORD[copied]
        if not rx.search(doc.body):
            where = "他のプロジェクト" if copied else "My-Lab"
            r.fail(0, "検証の記録", f"検証の記録（{where} では {want}）への参照が無い")
        for t in doc.tables:
            k = next((k for k, c in enumerate(t["header"]) if c == "判定"), None)
            if k is None:
                continue
            for no_, cells in t["rows"]:
                if len(cells) > k and cells[k] and not re.match(r"^充足", cells[k]) and not re.search(r"A-\d+", cells[k]):
                    r.fail(no_, "出す前の表", f"判定「{cells[k]}」。全行が充足になるまで出さない（第 5 条）")
    elif kind == "request":
        heads = doc.headings()
        if not heads or "結論と伺い" not in heads[0][1]:
            r.fail(0, "順番", "承認伺いは「## 結論と伺い」から始める")
        if doc.total > 60:
            r.fail(0, "長さ", f"{doc.total} 行。60 行以内")
    else:
        r.warn(0, "種類", "表題が「完了報告:」「承認伺い:」のどちらでもない。言い訳・交渉・転記の検査だけ行った")


# ---- 振り分け
def load_rules():
    rules = []
    for line in (HERE / "routing-rules.tsv").read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 5:
            continue
        rx, roles, skill, kind, alone = parts[:5]
        rules.append((re.compile(rx), [x for x in roles.split("+") if x and x != "-"], skill, kind, alone.strip() == "yes"))
    return rules


NO_HIT = "当たり無し。秘書が振り分けの表で確かめる"


def route(text):
    roles, skills, kinds, alone_roles = [], [], [], []
    hits = [(rs, skill, kind, alone) for rx, rs, skill, kind, alone in load_rules() if rx.search(text)]
    # どの規則にも当たらないときは、質問と決めつけず、当たり無しと返す（秘書が表で確かめる）
    if not hits:
        return [], [], [NO_HIT], "未定"
    # 単独の規則が当たったら、役割を持つ他の規則は型とスキルにも数えない（役割なしの規則は残す）
    any_alone = any(alone for _, _, _, alone in hits)
    for rs, skill, kind, alone in hits:
        for x in rs:
            if x not in roles:
                roles.append(x)
            if alone and x not in alone_roles:
                alone_roles.append(x)
        if any_alone and rs and not alone:
            continue
        if skill != "-" and skill not in skills:
            skills.append(skill)
        if kind not in kinds:
            kinds.append(kind)
    if alone_roles:
        roles = alone_roles
    n = len(roles)
    scale = "単純" if n <= 1 else "比較" if n <= 4 else "複雑"
    return roles, skills, kinds, scale


def show_route(text):
    roles, skills, kinds, scale = route(text)
    print(f"依頼: {text}")
    if kinds == [NO_HIT]:
        print(f"型: {NO_HIT}")
        print("役割: 当たり無し")
        print("スキル: secretary")
        print("規模: 未定（表で確かめてから決める）")
        return 0
    print(f"型: {'、'.join(kinds)}")
    print(f"役割: {'+'.join(roles) or '秘書のみ'}")
    print(f"スキル: {'、'.join(skills) or 'secretary'}")
    print(f"規模: {scale}（役割 {len(roles)}）")
    return 0


# ---- 自己試験
def mutate(src, old, new):
    if old not in src:
        raise ValueError(f"見本に「{old}」が無い。自己試験の前提が変わった")
    return src.replace(old, new, 1)


def run_check(kind, path, request_path=None, copied=None):
    doc = Doc(path)
    r = Report(NAMES[kind], path)
    if kind == "intake":
        check_intake(doc, r)
    elif kind == "minutes":
        check_minutes(doc, r)
    elif kind == "request":
        check_request(doc, r)
    elif kind == "record":
        check_record(doc, r, request_path)
    elif kind == "gate":
        check_gate(doc, r, copied)
    elif kind == "reply":
        check_reply(doc, r)
    return r


MUTATIONS = {
    "intake": [
        ("承認の状態", "未承認（", "承認済み（口頭）（"),
        ("規模", "比較（", "単純（"),
        ("関わる役割と問い", "CEO: ", "QA: "),
        ("聞くこと", "③", "③ 仮置き ④ 4 つ目の問い ③"),
        ("言い直し", "| 言い直し | 対象は管理画面の注文一覧で、", "| 言い直し | 管理画面の注文一覧を作り直したい |\n| 言い直し（元） | 対象は管理画面の注文一覧で、"),
        ("成果物の形", "| 成果物の形 | 指定なし（仮置き: ", "| 成果物の形 | いい感じに（仮置き: "),
    ],
    "minutes": [
        ("欄", "| 黙読した文書 |", "| 黙読 |"),
        ("承認が要る判断", "| 戻せる |", "| 未定 |"),
        ("節", "## 対立点と裁定", "## 対立"),
        ("生ログ", "## 承認が要る判断", "```\n" + "log\n" * 60 + "```\n\n## 承認が要る判断"),
    ],
    "request": [
        ("日程", "| 期限 | 2026-12-08", "| 期限 | 2026-11-20"),
        ("結論", "推奨は案 A で、", "案 A と案 B があり、"),
        ("解", "案 A（推奨）", "案 A"),
        ("長さ", "## やらないこと", "## やらないこと\n" + "補足の行です。\n" * 20),
    ],
    "record": [
        ("承認の言葉", "「段階 1 は進めて。", "「検討して。"),
        ("承認者", "| 承認者 | 社長 |", "| 承認者 | 秘書 |"),
        ("承認の範囲", "| 承認で動くもの | ", "| 承認で動くもの | 返金の一括（フロントエンド、11 月 20 日まで）／"),
        ("状態", "| 状態 | 有効 |", "| 状態 | 仮 |"),
    ],
    "reply": [
        ("要約", "## 未解決の対立", "補足の行です。\n" * 12 + "\n## 未解決の対立"),
        ("承認が要る判断", "| 戻せる | 1 点の条件として併記 |", "| 未定 | 1 点の条件として併記 |"),
        ("節", "## 承認が要る判断", "## 判断"),
        ("生ログ", "## 未解決の対立", "```\n" + "log\n" * 25 + "```\n\n## 未解決の対立"),
    ],
}

BAD_REPORT = """# 完了報告: 見本

> **3 行でわかる要約**
> 1. 検査の見本です。
> 2. 結論は未達です。
> 3. 次に直します。

## 1. 確認

| # | 要件 | 判定 |
|---|---|---|
| 1 | 画面が 1 秒で出る | 未充足 |

qa の判定: 不合格。性能はできませんでしたが、前より良くなりました。おそらく次は通るはずです。
"""

GOOD_REPORT = """# 完了報告: 見本

> **3 行でわかる要約**
> 1. 検査の見本です。
> 2. 受け入れ条件 1 件が充足です。
> 3. 社長にしてほしいことは、commit の承認です。

## 1. 確認

| # | 要件 | 判定 |
|---|---|---|
| 1 | 画面が 1 秒で出る | 充足 |

検証の記録は `{record}` にあります。
"""

# 検証の記録の受け方（置き場, 記録のパス, 通るか）。他のプロジェクトは tmp/.verify/ だけ、My-Lab は docs/verify/ だけを受ける。
GATE_RECORD_CASES = [
    (False, "docs/verify/2026-11-08.md", True),
    (False, "tmp/.verify/last-fast.txt", False),
    (True, "tmp/.verify/last-fast.txt", True),
    (True, "tmp/.verify/last-full.txt", True),
    (True, "docs/verify/2026-11-08.md", False),
    (True, "tmp/.verify/verify-full.log", False),
]

ROUTE_CASES = [
    ("管理画面の注文一覧を作り直したい", {"CEO", "デザイナー", "フロントエンド", "バックエンド"}),
    ("どっちを先にやる？", {"CEO"}),
    ("アラートが鳴りすぎる", {"SRE"}),
    ("PR 文を書いて", set()),
    ("ログイン画面に、パスワードを見せる切り替えを付けたい", {"デザイナー", "フロントエンド"}),
    ("ログイン画面のパスワードの保存方法を変えたい", {"バックエンド", "セキュリティ"}),
    ("注文一覧の CSV を書き出したい", {"バックエンド", "セキュリティ"}),
    ("管理画面のボタンから注文を CSV でダウンロードしたい", {"フロントエンド", "バックエンド", "セキュリティ"}),
    ("要約ログの出力の項目を決めたい", set()),
    ("リリース前のチェックリストを作って", set()),
    ("注文データを調査して", set()),
]
# どの規則にも当たらない依頼文。型が「当たり無し」になることを見る
ROUTE_NO_HIT = ["来週の段取りを相談したい", "要約ログの出力の項目を決めたい"]


def selftest(kind):
    ok = True
    name = NAMES[kind]
    if kind == "route":
        for text, want in ROUTE_CASES:
            got = set(route(text)[0])
            if got != want:
                ok = False
                print(f"FAIL selftest route: 「{text}」→ {sorted(got)}（期待 {sorted(want)}）")
        for text in ROUTE_NO_HIT:
            kinds = route(text)[2]
            if kinds != [NO_HIT]:
                ok = False
                print(f"FAIL selftest route: 「{text}」の型が {kinds}（期待 当たり無し）")
        print(f"RESULT: {'PASS' if ok else 'FAIL'} route --selftest ({len(ROUTE_CASES) + len(ROUTE_NO_HIT)} 例)")
        return ok
    with tempfile.TemporaryDirectory() as tmp:
        tmpd = pathlib.Path(tmp)
        for f in EXAMPLES.values():
            shutil.copy(SKILL / "examples" / f, tmpd / f)
        if kind == "gate":
            good = str(tmpd / EXAMPLES["request"])
            r = run_check("gate", good)
            if r.fails:
                ok = False
                print(f"FAIL selftest gate: 完成例（承認伺い）が落ちた: {sorted(r.rules())}")
            bad = tmpd / "bad-report.md"
            bad.write_text(BAD_REPORT, encoding="utf-8")
            for copied in (False, True):
                found = run_check("gate", str(bad), copied=copied).rules()
                for rule in ("言い訳", "判定の転記", "推測", "出す前の表", "検証の記録"):
                    if rule not in found:
                        ok = False
                        print(f"FAIL selftest gate: 「{rule}」が通った（他のプロジェクト={copied}、検出: {sorted(found)}）")
            for i, (copied, record, want) in enumerate(GATE_RECORD_CASES):
                f = tmpd / f"report-{i}.md"
                f.write_text(GOOD_REPORT.format(record=record), encoding="utf-8")
                got = not run_check("gate", str(f), copied=copied).fails
                if got != want:
                    ok = False
                    where = "他のプロジェクト" if copied else "My-Lab"
                    print(f"FAIL selftest gate: {where}で記録「{record}」が{'通った' if got else '落ちた'}（期待 {'PASS' if want else 'FAIL'}）")
            n = 1 + 5 * 2 + len(GATE_RECORD_CASES)
        else:
            good = tmpd / EXAMPLES[kind]
            r = run_check(kind, str(good))
            if r.fails:
                ok = False
                print(f"FAIL selftest {name}: 完成例が落ちた: {[(x[2], x[3]) for x in r.fails]}")
            src = good.read_text(encoding="utf-8")
            for i, (rule, old, new) in enumerate(MUTATIONS[kind]):
                bad = tmpd / f"bad-{i}-{EXAMPLES[kind]}"
                try:
                    bad.write_text(mutate(src, old, new), encoding="utf-8")
                except ValueError as e:
                    ok = False
                    print(f"FAIL selftest {name}: 負例「{rule}」を作れない。{e}")
                    continue
                found = run_check(kind, str(bad)).rules()
                if rule not in found:
                    ok = False
                    print(f"FAIL selftest {name}: 負例「{rule}」が通った（検出: {sorted(found)}）")
            tmpl = SKILL / "templates" / TEMPLATES[kind]
            if tmpl.exists() and "雛形の穴" not in run_check(kind, str(tmpl)).rules():
                ok = False
                print(f"FAIL selftest {name}: 雛形（穴埋めのまま）が通った")
            n = 1 + len(MUTATIONS[kind]) + 1
    print(f"RESULT: {'PASS' if ok else 'FAIL'} {name} --selftest ({n} 例)")
    return ok


def main(argv):
    if len(argv) < 2 or argv[0] not in NAMES:
        print(__doc__)
        return 2
    kind = argv[0]
    if argv[1] == "--selftest":
        return 0 if selftest(kind) else 1
    if kind == "route":
        return show_route(" ".join(argv[1:]))
    request_path = None
    if "--request" in argv:
        i = argv.index("--request")
        request_path = argv[i + 1] if i + 1 < len(argv) else None
        argv = argv[:i] + argv[i + 2:]
    path = argv[1]
    if not pathlib.Path(path).exists():
        print(f"FAIL {path} [読めない] ファイルが無い")
        print(f"RESULT: FAIL {NAMES[kind]} {path}")
        return 1
    return 0 if run_check(kind, path, request_path).show() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
