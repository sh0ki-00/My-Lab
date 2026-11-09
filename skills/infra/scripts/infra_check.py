#!/usr/bin/env python3
"""infra_check — インフラの成果物と構成コードの検査。

使い方: infra_check.py arch <インフラ構成設計書>        設計書の欠け（6 本の柱、3 層、IAM、秘密、暗号化、監査ログ、復元、環境の差、費用の幅、流出経路と 6 つの出口、信頼の根、攻撃者の目）
        infra_check.py iac <ディレクトリか .tf...>       Terraform の静的検査（規則 IAC-001〜012。番号・重さ・直し方を出す）
        infra_check.py iac --rules                       規則の一覧を出す
        infra_check.py plan <terraform show -json の計画>  計画の差分の関所（置き換え・削除・前提の検査で止め、守りの差分は承認 2 人の経路へ回す）
        infra_check.py <種類> --selftest
出力: FAIL <場所> [<決まり>] <内容>、WARN …、最後に RESULT: PASS|FAIL <検査名> <対象> (…)。1 件でも FAIL なら終了コード 1。
例外: .tf の行か直前の行に「# iac-scan:allow IAC-nnn <理由>」を書くと、その規則をその行で外す。理由の無い例外は FAIL。
"""
import fnmatch
import json
import pathlib
import re
import shutil
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
SKILL = HERE.parent
FIX = SKILL / "evals" / "fixtures"
NAMES = {"arch": "arch-check", "iac": "iac-scan", "plan": "plan-gate"}


class Report:
    def __init__(self, check, name):
        self.check, self.name, self.items = check, name, []

    def fail(self, where, rule, detail):
        self.items.append(("FAIL", where, rule, detail))

    def warn(self, where, rule, detail):
        self.items.append(("WARN", where, rule, detail))

    @property
    def fails(self):
        return [x for x in self.items if x[0] == "FAIL"]

    def show(self, extra=""):
        for kind, where, rule, detail in self.items:
            print(f"{kind} {where or self.name} [{rule}] {detail}")
        n = len(self.fails)
        tail = f"{extra}、" if extra else ""
        print(f"RESULT: {'PASS' if n == 0 else 'FAIL'} {self.check} {self.name} ({tail}FAIL {n}、WARN {len(self.items) - n})")
        return n == 0


# =====================================================================
# 1. 設計書（arch）
# =====================================================================
PILLARS = ["運用の上手さ", "セキュリティ", "信頼性", "性能の効率", "費用の最適化", "持続可能性"]
EXITS = {
    "公開設定": ["公開設定"],
    "権限の持たせすぎ": ["権限の持たせすぎ"],
    "ログへの混入": ["ログへの混入"],
    "他人の ID での閲覧": ["他人の ID", "他人のID"],
    "依存部品": ["依存部品"],
    "放置された複製": ["放置された複製"],
}
LAYERS = ["公開", "アプリ", "データ"]
SECTIONS = ["背景", "6 本の柱", "ネットワーク", "IAM", "秘密情報", "暗号化", "監査ログ", "バックアップと復元",
            "環境の差", "費用の幅", "流出経路", "ここから入る", "未確定"]
GUESS = ["はず", "おそらく", "たぶん", "と思われ", "だろう"]
BAD_SECRET_PLACE = [".env", "コードに", "直書き", "tfvars", "リポジトリ", "平文"]


def load_doc(name):
    text = pathlib.Path(name).read_text(encoding="utf-8")
    lines, in_code, lang, in_comment = [], False, "", False
    mermaid = []  # (行, 節)
    for i, l in enumerate(text.split("\n"), 1):
        s = l.strip()
        if in_comment:
            in_comment = "-->" not in s
            continue
        if not in_code and s.startswith("<!--"):
            in_comment = "-->" not in s[4:]
            continue
        if s.startswith("```"):
            if not in_code:
                lang = s[3:].strip()
                if lang == "mermaid":
                    mermaid.append(i)
            in_code = not in_code
            continue
        if not in_code:
            lines.append((i, l))
    return lines, mermaid


def split_sections(lines, mermaid):
    """## の節ごとに (見出し, 行の並び, 図の数, 見出しの行) を返す。### は親の節に入れる。"""
    secs, cur = [], None
    for no, l in lines:
        if re.match(r"^##\s", l):
            cur = {"title": l.lstrip("#").strip(), "lines": [], "no": no, "mermaid": 0}
            secs.append(cur)
        elif cur is not None:
            cur["lines"].append((no, l))
    for m in mermaid:
        owner = None
        for s in secs:
            if s["no"] < m:
                owner = s
        if owner:
            owner["mermaid"] += 1
    return secs


def tables_of(sec_lines):
    out, cur = [], None
    for no, l in sec_lines:
        s = l.strip()
        if not s.startswith("|"):
            cur = None
            continue
        cells = [c.strip() for c in s.strip().strip("|").split("|")]
        if cur is None:
            cur = {"header": cells, "rows": [], "no": no}
            out.append(cur)
        elif all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
            continue
        else:
            cur["rows"].append((no, cells))
    return out


def col(t, *keys):
    for k, c in enumerate(t["header"]):
        if any(key in c for key in keys):
            return k
    return None


def cell(cells, k):
    return cells[k].strip() if k is not None and len(cells) > k else ""


def empty(v):
    return v.strip() in ("", "-", "—", "ー", "なし", "未定", "TBD")


def find_sec(secs, key):
    return next((s for s in secs if key in s["title"]), None)


def find_table(sec, *cols):
    for t in tables_of(sec["lines"]):
        if all(col(t, c) is not None for c in cols):
            return t
    return None


def text_of(sec):
    return "\n".join(l for _, l in sec["lines"])


def yen(v):
    m = re.search(r"([0-9][0-9,]*(?:\.[0-9]+)?)", v.replace("，", ","))
    return float(m.group(1).replace(",", "")) if m else None


def check_arch(name, r):
    lines, mermaid = load_doc(name)
    title = next((l[2:].strip() for _, l in lines if l.startswith("# ")), "")
    if "インフラ構成" not in title:
        r.fail(f"{name}:1", "表題", "表題に「インフラ構成」が無い（例: 設計書: <件名>のインフラ構成）")
    for no, l in lines:
        if re.search(r"<[^>\s][^>]*>", l) and not re.search(r"<br\s*/?>", l):
            r.fail(f"{name}:{no}", "雛形の穴", "<…> が残っている")
        for g in GUESS:
            if g in l and "ja-ok" not in l:
                r.fail(f"{name}:{no}", "推測", f"「{g}」がある。測った値か、未実測と書く")
                break
    secs = split_sections(lines, mermaid)
    for key in SECTIONS:
        if find_sec(secs, key) is None:
            r.fail(name, "節", f"「## …{key}…」の節が無い")
    at = lambda s: f"{name}:{s['no']}"  # noqa: E731

    # 6 本の柱
    s = find_sec(secs, "6 本の柱")
    if s:
        t = find_table(s, "柱", "決め", "測り方")
        if t is None:
            r.fail(at(s), "6 本の柱", "「柱」「決め」「測り方」の列の表が無い")
        else:
            kp, kd, km = col(t, "柱"), col(t, "決め"), col(t, "測り方")
            for p in PILLARS:
                row = next((c for _, c in t["rows"] if p in cell(c, kp)), None)
                if row is None:
                    r.fail(at(s), "6 本の柱", f"柱「{p}」の行が無い")
                elif empty(cell(row, kd)) or empty(cell(row, km)):
                    r.fail(at(s), "6 本の柱", f"柱「{p}」の決めか測り方が空")

    # ネットワークの 3 層
    s = find_sec(secs, "ネットワーク")
    if s:
        if s["mermaid"] == 0:
            r.fail(at(s), "ネットワーク", "ネットワークの図（Mermaid）が無い")
        t = find_table(s, "層", "置くもの", "受ける通信")
        if t is None:
            r.fail(at(s), "ネットワーク", "「層」「置くもの」「受ける通信」の列の表が無い")
        else:
            kl = col(t, "層")
            for layer in LAYERS:
                if not any(layer in cell(c, kl) for _, c in t["rows"]):
                    r.fail(at(s), "ネットワーク", f"「{layer}」の層の行が無い")

    # IAM
    s = find_sec(secs, "IAM")
    if s:
        t = find_table(s, "主体", "許す操作", "対象")
        if t is None:
            r.fail(at(s), "IAM", "「主体」「許す操作」「対象」の列の表が無い")
        else:
            ka, ko = col(t, "許す操作"), col(t, "対象")
            for no, c in t["rows"]:
                for k, label in ((ka, "許す操作"), (ko, "対象")):
                    v = cell(c, k).replace("`", "")
                    if empty(v):
                        r.fail(f"{name}:{no}", "IAM", f"{label}が空")
                    elif re.search(r"(^|[\s:,、])\*($|[\s,、])", v) or "すべて" in v or "全部" in v:
                        r.fail(f"{name}:{no}", "IAM", f"{label}が「*」か「すべて」。名指しにする")
        if "長期のアクセスキー" not in text_of(s):
            r.fail(at(s), "IAM", "長期のアクセスキーの扱い（作らない、など）が書かれていない")

    # 秘密情報
    s = find_sec(secs, "秘密情報")
    if s:
        t = find_table(s, "秘密", "置き場", "回転", "読める")
        if t is None:
            r.fail(at(s), "秘密情報", "「秘密」「置き場」「回転」「読める主体」の列の表が無い")
        else:
            kp, kr = col(t, "置き場"), col(t, "回転")
            for no, c in t["rows"]:
                v = cell(c, kp)
                if empty(v) or any(b in v for b in BAD_SECRET_PLACE):
                    r.fail(f"{name}:{no}", "秘密情報", f"置き場「{v}」。秘密の保管庫に置く（コード・.env・変数の値に置かない）")
                if empty(cell(c, kr)):
                    r.fail(f"{name}:{no}", "秘密情報", "回転の決めが空")

    # 暗号化
    s = find_sec(secs, "暗号化")
    if s:
        t = find_table(s, "対象", "保存時", "通信", "鍵")
        if t is None:
            r.fail(at(s), "暗号化", "「対象」「保存時」「通信時」「鍵」の列の表が無い")
        else:
            if len(t["rows"]) < 3:
                r.fail(at(s), "暗号化", f"対象が {len(t['rows'])} 行。データの在りかを全部並べる（3 行以上）")
            for no, c in t["rows"]:
                for key in ("保存時", "通信", "鍵"):
                    if empty(cell(c, col(t, key))):
                        r.fail(f"{name}:{no}", "暗号化", f"「{key}」が空かなし")

    # 監査ログ
    s = find_sec(secs, "監査ログ")
    if s:
        tx = text_of(s)
        if not any(k in tx for k in ("消せない", "オブジェクトロック", "改ざん")):
            r.fail(at(s), "監査ログ", "消せない仕組み（オブジェクトロック、改ざんの検知など）が書かれていない")
        if not re.search(r"[0-9]+\s*(日|年|か月)", tx) or "保持" not in tx:
            r.fail(at(s), "監査ログ", "保持の期間（数字と日・年）が無い")

    # バックアップと復元
    s = find_sec(secs, "バックアップと復元")
    if s:
        tx = text_of(s)
        for key in ("RPO", "RTO"):
            if not re.search(rf"{key}[^\n|]*[0-9]", tx) and not re.search(rf"\|\s*{key}[^|]*\|[^|]*[0-9]", tx):
                r.fail(at(s), "復元", f"{key} の数字が無い")
        t = find_table(s, "項目", "目標", "実測", "測り方")
        if t is None:
            r.fail(at(s), "復元", "「項目」「目標」「実測」「測り方」の列の表が無い")
        else:
            kg, km, kh = col(t, "目標"), col(t, "実測"), col(t, "測り方")
            measured = False
            for no, c in t["rows"]:
                g, m = cell(c, kg), cell(c, km)
                if m and m == g and "未実測" not in m:
                    r.fail(f"{name}:{no}", "目標と実測", f"実測が目標と同じ文字「{m}」。測った値か「未実測」と書く")
                if re.search(r"[0-9.]+\s*秒", m) and "restore-drill" in cell(c, kh):
                    measured = True
            if not measured:
                r.fail(at(s), "復元", "restore-drill で測った復元の秒（実測の列）が無い")

    # 環境の差
    s = find_sec(secs, "環境の差")
    if s:
        t = find_table(s, "項目", "検証環境", "本番")
        if t is None or len(t["rows"]) < 3:
            r.fail(at(s), "環境の差", "「項目」「検証環境」「本番」の列で 3 行以上の表が無い")
        if "同じコード" not in text_of(s):
            r.fail(at(s), "環境の差", "「同じコード」で違いは変数の値だけ、と書かれていない")

    # 費用の幅
    s = find_sec(secs, "費用の幅")
    if s:
        t = find_table(s, "最小", "最大", "前提")
        if t is None:
            r.fail(at(s), "費用の幅", "「最小」「最大」「前提」の列の表が無い")
        else:
            klo, khi, kpre, kname = col(t, "最小"), col(t, "最大"), col(t, "前提"), 0
            items, total = [], None
            for no, c in t["rows"]:
                lo, hi = yen(cell(c, klo)), yen(cell(c, khi))
                if lo is None or hi is None:
                    r.fail(f"{name}:{no}", "費用の幅", "最小か最大に数字が無い")
                    continue
                if lo > hi:
                    r.fail(f"{name}:{no}", "費用の幅", f"最小 {lo:g} が最大 {hi:g} より大きい")
                if empty(cell(c, kpre)):
                    r.fail(f"{name}:{no}", "費用の幅", "前提が空")
                if "合計" in cell(c, kname):
                    total = (no, lo, hi)
                else:
                    items.append((lo, hi))
            if total is None:
                r.fail(at(s), "費用の幅", "「合計」の行が無い")
            else:
                no, lo, hi = total
                if lo >= hi:
                    r.fail(f"{name}:{no}", "費用の幅", "合計が 1 点になっている。最小と最大の幅で書く")
                slo, shi = sum(x for x, _ in items), sum(y for _, y in items)
                if items and (abs(slo - lo) > 0.5 or abs(shi - hi) > 0.5):
                    r.fail(f"{name}:{no}", "費用の幅", f"合計 {lo:g}〜{hi:g} が行の和 {slo:g}〜{shi:g} と合わない")

    # 流出経路と 6 つの出口
    s = find_sec(secs, "流出経路")
    if s:
        if s["mermaid"] == 0:
            r.fail(at(s), "流出経路", "データの在りかと出口の図（Mermaid）が無い")
        t = find_table(s, "出口", "守り", "確認方法")
        if t is None:
            r.fail(at(s), "流出経路", "「出口」「守り」「確認方法」の列の表が無い")
        else:
            ke, kd, kc = col(t, "出口"), col(t, "守り"), col(t, "確認方法")
            for ex, keys in EXITS.items():
                row = next((c for _, c in t["rows"] if any(k in cell(c, ke) for k in keys)), None)
                if row is None:
                    r.fail(at(s), "流出経路", f"出口「{ex}」の行が無い")
                elif empty(cell(row, kd)) or empty(cell(row, kc)):
                    r.fail(at(s), "流出経路", f"出口「{ex}」の守りか確認方法が空")

    # 信頼の根: SCP と保護を外せる立場（組織の管理の口座、GitHub の組織の持ち主など）。拒否では守れないので、持ち方と鳴らし方と file を書く。
    s = find_sec(secs, "信頼の根")
    if s is None:
        r.fail(name, "信頼の根", "「## 信頼の根」の節が無い。SCP と保護を外せる立場と、その守り・鳴る所・file を書く")
    else:
        t = find_table(s, "信頼の根", "守り", "file")
        if t is None or not t["rows"]:
            r.fail(at(s), "信頼の根", "「信頼の根」「守り」「file」の列の表が無い")
        else:
            kd, kf = col(t, "守り"), col(t, "file")
            for no, c in t["rows"]:
                if empty(cell(c, kd)) or empty(cell(c, kf)):
                    r.fail(f"{name}:{no}", "信頼の根", "守りか file が空。file を書けない守りは未確定に回す")

    # 攻撃者の目
    s = find_sec(secs, "ここから入る")
    if s:
        t = find_table(s, "出口", "ここから入る", "答え")
        if t is None:
            r.fail(at(s), "攻撃者の目", "「出口」「私ならここから入る」「答え」の列の表が無い")
        else:
            ke, ka = col(t, "出口"), col(t, "答え")
            for ex, keys in EXITS.items():
                row = next((c for _, c in t["rows"] if any(k in cell(c, ke) for k in keys)), None)
                if row is None or empty(cell(row, ka)):
                    r.fail(at(s), "攻撃者の目", f"出口「{ex}」への攻め手と答えが無い")


# =====================================================================
# 2. 構成コード（iac）: HCL の小さな読み取り
# =====================================================================
class Block:
    def __init__(self, kind, labels, file, line):
        self.kind, self.labels, self.file, self.line = kind, labels, file, line
        self.attrs, self.blocks = {}, []

    @property
    def addr(self):
        return ".".join(self.labels) if self.kind == "resource" else ".".join([self.kind] + self.labels)

    def a(self, key):
        return self.attrs.get(key, (None, 0))[0]

    def al(self, key):
        return self.attrs.get(key, (None, self.line))[1] or self.line

    def sub(self, kind):
        return [b for b in self.blocks if b.kind == kind]


class HclParser:
    def __init__(self, text, file):
        self.t, self.i, self.file, self.n = text, 0, file, len(text)

    def line(self, i=None):
        return self.t.count("\n", 0, self.i if i is None else i) + 1

    def skip_ws(self, newlines=True):
        while self.i < self.n:
            c = self.t[self.i]
            if c in " \t\r" or (newlines and c == "\n"):
                self.i += 1
            elif c == "#" or self.t.startswith("//", self.i):
                j = self.t.find("\n", self.i)
                self.i = self.n if j < 0 else j
            elif self.t.startswith("/*", self.i):
                j = self.t.find("*/", self.i)
                self.i = self.n if j < 0 else j + 2
            else:
                break

    def read_string(self):
        j = self.i + 1
        while j < self.n:
            if self.t[j] == "\\":
                j += 2
                continue
            if self.t[j] == '"':
                break
            j += 1
        s = self.t[self.i:j + 1]
        self.i = j + 1
        return s

    def read_expr(self):
        start, depth = self.i, 0
        while self.i < self.n:
            c = self.t[self.i]
            if c == '"':
                self.read_string()
                continue
            if self.t.startswith("<<", self.i) and re.match(r"<<-?([A-Za-z_]+)", self.t[self.i:]):
                m = re.match(r"<<-?([A-Za-z_]+)", self.t[self.i:])
                endm = re.compile(rf"^\s*{m.group(1)}\s*$", re.M).search(self.t, self.i + m.end())
                self.i = endm.end() if endm else self.n
                continue
            if c == "#" or self.t.startswith("//", self.i):
                if depth == 0:
                    break
                j = self.t.find("\n", self.i)
                self.i = self.n if j < 0 else j
                continue
            if c in "([{":
                depth += 1
            elif c in ")]}":
                if depth == 0:
                    break
                depth -= 1
            elif c == "\n" and depth == 0:
                break
            self.i += 1
        return self.t[start:self.i].strip()

    def body(self, parent):
        while True:
            self.skip_ws()
            if self.i >= self.n:
                return
            if self.t[self.i] == "}":
                self.i += 1
                return
            m = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*").match(self.t, self.i)
            if not m:
                self.i += 1
                continue
            ident, at = m.group(0), self.i
            self.i = m.end()
            self.skip_ws(newlines=False)
            if self.i < self.n and self.t[self.i] == "=" and not self.t.startswith("==", self.i):
                self.i += 1
                self.skip_ws(newlines=False)
                eline = self.line()
                parent.attrs[ident] = (self.read_expr(), eline)
                continue
            labels = []
            while self.i < self.n and self.t[self.i] != "{":
                self.skip_ws(newlines=False)
                if self.t[self.i] == '"':
                    labels.append(self.read_string()[1:-1])
                elif self.t[self.i] == "{":
                    break
                else:
                    m2 = re.compile(r"[A-Za-z0-9_-]+").match(self.t, self.i)
                    if not m2:
                        break
                    labels.append(m2.group(0))
                    self.i = m2.end()
            if self.i < self.n and self.t[self.i] == "{":
                self.i += 1
                b = Block(ident, labels, self.file, self.line(at))
                parent.blocks.append(b)
                self.body(b)


def parse_tf(path):
    text = path.read_text(encoding="utf-8")
    root = Block("file", [], path, 1)
    HclParser(text, path).body(root)
    return root, text


def tfvars_values(paths):
    vals = {}
    for p in paths:
        for line in p.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+?)\s*$", line)
            if m:
                vals.setdefault(m.group(1), []).append(m.group(2))
    return vals


def literal(v):
    if v is None:
        return None
    v = v.strip()
    m = re.fullmatch(r'"([^"]*)"', v)
    if m and "${" not in m.group(1):
        return m.group(1)
    if v in ("true", "false"):
        return v == "true"
    if re.fullmatch(r"-?[0-9]+(\.[0-9]+)?", v):
        return float(v)
    return None


# 規則: 番号、重さ、名前、直し方
RULES = {
    "IAC-001": ("CRITICAL", "外から読める保存先", "バケットの ACL を private にし、方針の Principal \"*\" の Allow を消す。読ませる相手は Service と SourceArn の条件で名指しする"),
    "IAC-002": ("HIGH", "公開のブロック", "aws_s3_bucket_public_access_block を置き、4 項目（block_public_acls ほか）をすべて true にする"),
    "IAC-003": ("HIGH", "権限の「*」", "操作と対象を名指しする。対象を絞れない操作だけ「# iac-scan:allow IAC-003 <理由>」で外す"),
    "IAC-004": ("CRITICAL", "管理の口の全開", "0.0.0.0/0 と ::/0 から管理の口（22、3389、5432 など）を開けない。受ける相手はセキュリティグループで名指しし、人は承認つきの接続で入る"),
    "IAC-005": ("HIGH", "暗号化の無い保存", "storage_encrypted = true か、aws_s3_bucket_server_side_encryption_configuration で aws:kms を指定する"),
    "IAC-006": ("CRITICAL", "外から届くデータベース", "publicly_accessible = false にし、データの層のサブネットに置く"),
    "IAC-007": ("HIGH", "削除の保護", "deletion_protection = true、skip_final_snapshot = false にする"),
    "IAC-008": ("HIGH", "バックアップの保持", "backup_retention_period を 7 日以上にする（全環境の値で）"),
    "IAC-009": ("HIGH", "監査ログの無効", "aws_cloudtrail を置き、enable_logging・enable_log_file_validation・is_multi_region_trail を true にする"),
    "IAC-010": ("MEDIUM", "版の管理の無いバケット", "aws_s3_bucket_versioning で status = \"Enabled\" にする"),
    "IAC-011": ("CRITICAL", "コードに書いた秘密", "値を消して秘密の保管庫（Secrets Manager、manage_master_user_password）から参照する。漏れた値は無効にして作り直す"),
    "IAC-012": ("HIGH", "平文の通信", "ロードバランサーは HTTPS にし、CloudFront は redirect-to-https か https-only にする"),
}
ADMIN_PORTS = [22, 23, 3389, 5432, 3306, 1433, 1521, 6379, 27017, 9200, 5900, 2375, 2376, 6443]
OPEN_CIDRS = ("0.0.0.0/0", "::/0")
STAR_ONLY_ACTIONS = {"ecr:getauthorizationtoken", "sts:getcalleridentity", "xray:puttracesegments", "xray:puttelemetryrecords"}
BROAD_MANAGED = ("AdministratorAccess", "PowerUserAccess", "IAMFullAccess")
SECRET_ATTR = re.compile(r"(?i)(^|_)(password|passwd|secret|secret_string|secret_key|access_key|api_key|token|private_key)$")
SECRET_RAW = [
    (re.compile(r"(?<![A-Z0-9])(AKIA|ASIA)[A-Z0-9]{16}(?![A-Z0-9])"), "アクセスキーの形の文字列"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "秘密鍵"),
    (re.compile(r"(?i)name\s*[:=]\s*\"[A-Z0-9_]*(PASSWORD|SECRET|TOKEN|API_KEY)[A-Z0-9_]*\"\s*,\s*\"?value\"?\s*[:=]\s*\"[^\"$]+\""), "環境変数に書いた秘密"),
]
ALLOW_RX = re.compile(r"#\s*iac-scan:allow\s+(IAC-[0-9]{3})\s*(.*)$")


class IacScan:
    def __init__(self, paths, r):
        self.r, self.files, self.blocks, self.texts = r, [], [], {}
        for p in paths:
            p = pathlib.Path(p)
            if p.is_dir():
                self.files += sorted(x for x in p.rglob("*.tf") if ".terraform" not in x.parts)
                self.tfvars = sorted(p.rglob("*.tfvars"))
            else:
                self.files.append(p)
        if not hasattr(self, "tfvars"):
            self.tfvars = []
        for f in self.files:
            root, text = parse_tf(f)
            self.blocks += root.blocks
            self.texts[f] = text.split("\n")
        self.vars = {b.labels[0]: b for b in self.blocks if b.kind == "variable" and b.labels}
        self.tfv = tfvars_values(self.tfvars)

    def res(self, rtype):
        return [b for b in self.blocks if b.kind == "resource" and b.labels and b.labels[0] == rtype]

    def allowed(self, rule, f, line):
        lines = self.texts.get(f, [])
        for ln in (line, line - 1):
            if 1 <= ln <= len(lines):
                m = ALLOW_RX.search(lines[ln - 1])
                if m and m.group(1) == rule:
                    if not m.group(2).strip():
                        self.r.fail(f"{f}:{ln}", "例外の理由", f"{rule} の例外に理由が無い")
                    return True
        return False

    def hit(self, rule, f, line, detail):
        if self.allowed(rule, f, line):
            return
        sev, title, fix = RULES[rule]
        self.r.fail(f"{f}:{line}", f"{rule} {sev} {title}", f"{detail}。直し方: {fix}")

    def values(self, expr):
        """式の値の候補（変数は既定値と全 tfvars の値）。分からなければ []。"""
        lit = literal(expr)
        if lit is not None:
            return [lit]
        m = re.fullmatch(r"var\.([A-Za-z_][A-Za-z0-9_]*)", (expr or "").strip())
        if not m:
            return []
        out = []
        v = self.vars.get(m.group(1))
        if v is not None and v.a("default") is not None:
            out.append(literal(v.a("default")))
        out += [literal(x) for x in self.tfv.get(m.group(1), [])]
        return [x for x in out if x is not None]

    def refs(self, rtype, attr="bucket"):
        """companion 資源（rtype）が指す aws_s3_bucket の名前の集合と、その資源。"""
        out = {}
        for b in self.res(rtype):
            m = re.search(r"aws_s3_bucket\.([A-Za-z0-9_-]+)\.", b.a(attr) or "")
            if m:
                out.setdefault(m.group(1), []).append(b)
        return out

    # ---- 方針（JSON か HCL の式）を文に分ける
    @staticmethod
    def statements(expr):
        out = []
        for i, ch in enumerate(expr):
            if ch != "{":
                continue
            depth, j = 0, i
            while j < len(expr):
                if expr[j] == "{":
                    depth += 1
                elif expr[j] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            obj = expr[i + 1:j]
            top, d = [], 0
            for c in obj:
                if c == "{":
                    d += 1
                elif c == "}":
                    d -= 1
                elif d == 0:
                    top.append(c)
            top = "".join(top)
            if re.search(r"[\"']?Effect[\"']?\s*[:=]", top):
                out.append((obj, top, i + 1))
        return out

    @staticmethod
    def field(top, key):
        m = re.search(rf"[\"']?{key}[\"']?\s*[:=]\s*(\[[^\]]*\]|\"[^\"]*\"|[^\n,]+)", top)
        if not m:
            return None
        return re.findall(r"\"([^\"]*)\"", m.group(1)) or [m.group(1).strip()]

    def check_policy(self, b, attr, kind):
        expr = b.a(attr)
        if not expr:
            return
        line = b.al(attr)
        for obj, top, at in self.statements(expr):
            def where(key, _obj=obj, _at=at):
                m = re.search(rf"[\"']?{key}[\"']?\s*[:=]", _obj)
                return line + expr[:_at + (m.start() if m else 0)].count("\n")
            effect = (self.field(top, "Effect") or ["Allow"])[0]
            if effect != "Allow":
                continue
            pm = re.search(r"[\"']?Principal[\"']?\s*[:=]\s*(\"\*\"|\{[^}]*\"\*\"[^}]*\})", obj)
            has_cond = re.search(r"[\"']?Condition[\"']?\s*[:=]", obj) is not None
            if kind == "bucket" and pm and not has_cond:
                self.hit("IAC-001", b.file, where("Principal"), f"{b.addr} の方針が誰にでも Allow している")
            if kind != "iam":
                continue
            actions = [a.lower() for a in (self.field(top, "Action") or [])]
            resources = self.field(top, "Resource") or []
            for a in actions:
                if "*" in a:
                    self.hit("IAC-003", b.file, where("Action"), f"{b.addr} の操作「{a}」に * がある")
            if "*" in resources:
                only = actions and all(a in STAR_ONLY_ACTIONS for a in actions)
                note = "（対象を絞れない操作なので、理由つきの例外で外せる）" if only else ""
                self.hit("IAC-003", b.file, where("Resource"), f"{b.addr} の対象が「*」{note}")

    def run(self):
        r = self.r
        # IAC-001、IAC-002、IAC-005、IAC-010: バケット
        buckets = self.res("aws_s3_bucket")
        pab = self.refs("aws_s3_bucket_public_access_block")
        ver = self.refs("aws_s3_bucket_versioning")
        sse = self.refs("aws_s3_bucket_server_side_encryption_configuration")
        for b in buckets:
            n = b.labels[1]
            if b.a("acl") and literal(b.a("acl")) in ("public-read", "public-read-write", "authenticated-read"):
                self.hit("IAC-001", b.file, b.al("acl"), f"{b.addr} の ACL が {literal(b.a('acl'))}")
            blocks = pab.get(n, [])
            if not blocks:
                self.hit("IAC-002", b.file, b.line, f"{b.addr} に公開を止める設定が無い")
            else:
                for p in blocks:
                    for k in ("block_public_acls", "block_public_policy", "ignore_public_acls", "restrict_public_buckets"):
                        if literal(p.a(k)) is not True:
                            self.hit("IAC-002", p.file, p.al(k), f"{p.addr} の {k} が true でない")
            inline_ver = any(literal(v.a("enabled")) is True for v in b.sub("versioning"))
            vblocks = ver.get(n, [])
            ok_ver = inline_ver or any(literal(vc.a("status")) == "Enabled" for v in vblocks for vc in v.sub("versioning_configuration"))
            if not ok_ver:
                self.hit("IAC-010", b.file, b.line, f"{b.addr} に版の管理が無い")
            ok_sse = bool(b.sub("server_side_encryption_configuration")) or bool(sse.get(n))
            if not ok_sse:
                self.hit("IAC-005", b.file, b.line, f"{b.addr} に保存時の暗号化の設定が無い")
        for a in self.res("aws_s3_bucket_acl"):
            if literal(a.a("acl")) in ("public-read", "public-read-write", "authenticated-read"):
                self.hit("IAC-001", a.file, a.al("acl"), f"{a.addr} の ACL が {literal(a.a('acl'))}")
        for p in self.res("aws_s3_bucket_policy"):
            self.check_policy(p, "policy", "bucket")
            self.check_policy(p, "policy", "iam")
        # IAC-003: IAM の方針と、広すぎる管理の方針
        for t in ("aws_iam_policy", "aws_iam_role_policy", "aws_iam_user_policy", "aws_iam_group_policy"):
            for p in self.res(t):
                self.check_policy(p, "policy", "iam")
        for d in [b for b in self.blocks if b.kind == "data" and b.labels and b.labels[0] == "aws_iam_policy_document"]:
            for st in d.sub("statement"):
                if literal(st.a("effect")) == "Deny":
                    continue
                acts = [x.lower() for x in re.findall(r"\"([^\"]*)\"", st.a("actions") or "")]
                ress = re.findall(r"\"([^\"]*)\"", st.a("resources") or "")
                for a in acts:
                    if "*" in a:
                        self.hit("IAC-003", d.file, st.al("actions"), f"{d.addr} の操作「{a}」に * がある")
                if "*" in ress:
                    self.hit("IAC-003", d.file, st.al("resources"), f"{d.addr} の対象が「*」")
        for t in ("aws_iam_role_policy_attachment", "aws_iam_user_policy_attachment", "aws_iam_group_policy_attachment", "aws_iam_policy_attachment"):
            for a in self.res(t):
                if any((a.a("policy_arn") or "").endswith(f"/{m}\"") or (a.a("policy_arn") or "").endswith(f"/{m}") for m in BROAD_MANAGED):
                    self.hit("IAC-003", a.file, a.al("policy_arn"), f"{a.addr} が広すぎる管理の方針を付けている")
        for u in self.res("aws_iam_access_key"):
            self.hit("IAC-011", u.file, u.line, f"{u.addr} が長期のアクセスキーを作っている")
        # IAC-004: 管理の口
        for sg in self.res("aws_security_group"):
            for ing in sg.sub("ingress"):
                cidrs = re.findall(r"\"([^\"]*)\"", (ing.a("cidr_blocks") or "") + (ing.a("ipv6_cidr_blocks") or ""))
                self.check_port(sg, ing, cidrs, ing.a("protocol"))
        for rule in self.res("aws_security_group_rule"):
            if literal(rule.a("type")) == "ingress":
                cidrs = re.findall(r"\"([^\"]*)\"", (rule.a("cidr_blocks") or "") + (rule.a("ipv6_cidr_blocks") or ""))
                self.check_port(rule, rule, cidrs, rule.a("protocol"))
        for rule in self.res("aws_vpc_security_group_ingress_rule"):
            cidrs = [x for x in (literal(rule.a("cidr_ipv4")), literal(rule.a("cidr_ipv6"))) if x]
            self.check_port(rule, rule, cidrs, rule.a("ip_protocol"))
        # IAC-005〜008: データベースと保存の領域
        for t in ("aws_db_instance", "aws_rds_cluster"):
            for db in self.res(t):
                if literal(db.a("storage_encrypted")) is not True:
                    self.hit("IAC-005", db.file, db.al("storage_encrypted"), f"{db.addr} の storage_encrypted が true でない")
                if True in self.values(db.a("publicly_accessible")):
                    self.hit("IAC-006", db.file, db.al("publicly_accessible"), f"{db.addr} が外から届く（publicly_accessible）")
                if literal(db.a("deletion_protection")) is not True:
                    self.hit("IAC-007", db.file, db.al("deletion_protection"), f"{db.addr} の deletion_protection が true でない")
                if literal(db.a("skip_final_snapshot")) is True:
                    self.hit("IAC-007", db.file, db.al("skip_final_snapshot"), f"{db.addr} が消すときに最後の複製を取らない")
                vals = self.values(db.a("backup_retention_period"))
                if db.a("backup_retention_period") is None:
                    self.hit("IAC-008", db.file, db.line, f"{db.addr} に backup_retention_period が無い")
                elif not vals:
                    r.warn(f"{db.file}:{db.al('backup_retention_period')}", "IAC-008 HIGH バックアップの保持", f"{db.addr} の保持の日数を値に解けない")
                elif min(vals) < 7:
                    self.hit("IAC-008", db.file, db.al("backup_retention_period"), f"{db.addr} の保持が {min(vals):g} 日（どれかの環境）")
        for t, key in (("aws_ebs_volume", "encrypted"), ("aws_efs_file_system", "encrypted")):
            for v in self.res(t):
                if literal(v.a(key)) is not True:
                    self.hit("IAC-005", v.file, v.al(key), f"{v.addr} の {key} が true でない")
        # IAC-009: 監査ログ
        trails = self.res("aws_cloudtrail")
        root_module = any(b.kind == "provider" and b.labels and b.labels[0] == "aws" for b in self.blocks)
        if root_module and not trails:
            prov = next(b for b in self.blocks if b.kind == "provider")
            self.hit("IAC-009", prov.file, prov.line, "aws の provider を持つ構成に aws_cloudtrail が無い")
        for t in trails:
            if literal(t.a("enable_logging")) is False:
                self.hit("IAC-009", t.file, t.al("enable_logging"), f"{t.addr} の記録が止めてある")
            for k in ("enable_log_file_validation", "is_multi_region_trail"):
                if literal(t.a(k)) is not True:
                    self.hit("IAC-009", t.file, t.al(k), f"{t.addr} の {k} が true でない")
        # IAC-011: 秘密
        for b in self.walk():
            for k, (v, line) in b.attrs.items():
                lit = literal(v)
                if SECRET_ATTR.search(k) and isinstance(lit, str) and lit:
                    self.hit("IAC-011", b.file, line, f"{b.addr} の {k} に値が書いてある")
            if b.kind == "variable" and b.labels and SECRET_ATTR.search(b.labels[0]):
                d = literal(b.a("default"))
                if isinstance(d, str) and d:
                    self.hit("IAC-011", b.file, b.al("default"), f"変数 {b.labels[0]} の既定値に秘密が書いてある")
        for f, lines in self.texts.items():
            for i, l in enumerate(lines, 1):
                for rx, what in SECRET_RAW:
                    if rx.search(l):
                        self.hit("IAC-011", f, i, what)
        for k, vals in self.tfv.items():
            if SECRET_ATTR.search(k) and any(isinstance(literal(v), str) and literal(v) for v in vals):
                r.fail(f"{k}", "IAC-011 CRITICAL コードに書いた秘密", f"tfvars の {k} に値がある。直し方: {RULES['IAC-011'][2]}")
        # IAC-012: 平文の通信
        for lst in self.res("aws_lb_listener"):
            if literal(lst.a("protocol")) == "HTTP":
                redirect = any(literal(d.a("type")) == "redirect" for d in lst.sub("default_action"))
                if not redirect:
                    self.hit("IAC-012", lst.file, lst.al("protocol"), f"{lst.addr} が HTTP のまま転送している")
        for cf in self.res("aws_cloudfront_distribution"):
            for beh in cf.sub("default_cache_behavior") + cf.sub("ordered_cache_behavior"):
                if literal(beh.a("viewer_protocol_policy")) == "allow-all":
                    self.hit("IAC-012", cf.file, beh.al("viewer_protocol_policy"), f"{cf.addr} が HTTP を許している")
        self.check_boundaries()
        return len([b for b in self.blocks if b.kind in ("resource", "data")])

    def check_boundaries(self):
        """境界の外: 権限の境界を付けた役割の方針に、境界の Allow の外の操作があれば落とす。
        方針に書いても AWS は拒むので、守り（棚卸しなど）が毎回その操作で黙って落ちる。役割を 1 つずつ見ず、型でまとめて確かめる。"""
        bpols = [p for p in self.res("aws_iam_policy") if "boundary" in p.labels[-1] or "boundary" in (p.a("name") or "")]

        def shape(text):
            # 名前の形（補間 ${…} を * にする）。境界の役割と方針を、名前の形が同じものどうしで結ぶ。
            return re.sub(r"\$\{[^}]*\}", "*", re.sub(r'["\s]', "", text or "")).split("policy/")[-1]

        local_vals = {}
        for b in self.blocks:
            if b.kind == "locals":
                for k, (v, _ln) in b.attrs.items():
                    local_vals.setdefault(k, v)
        allow_by_shape, allow_by_label = {}, {}
        for p in bpols:
            got = allow_by_shape.setdefault(shape(p.a("name")), set())
            allow_by_label[p.labels[-1]] = got
            for _obj, top, _at in self.statements(p.a("policy") or ""):
                if (self.field(top, "Effect") or ["Allow"])[0] == "Allow":
                    got |= {a.lower() for a in (self.field(top, "Action") or [])}
        if not any(allow_by_shape.values()):
            return
        role_allow = {}
        for b in self.res("aws_iam_role"):
            expr = (b.a("permissions_boundary") or "").strip()
            if len(b.labels) < 2 or not expr:
                continue
            m = re.fullmatch(r"local\.(\w+)", expr)
            d = re.fullmatch(r"aws_iam_policy\.(\w+)\.arn", expr)
            # この構成コードの中に定義の無い境界（芯の StackSet が置く境界など）は、ここでは確かめない。
            allow = allow_by_label.get(d.group(1)) if d else allow_by_shape.get(shape(local_vals.get(m.group(1)) if m else expr))
            if allow:
                role_allow[b.labels[1]] = allow
        roles = set(role_allow)
        for rp in self.res("aws_iam_role_policy"):
            m = re.search(r"aws_iam_role\.([A-Za-z0-9_-]+)", rp.a("role") or "")
            if not m or m.group(1) not in roles:
                continue
            for _obj, top, _at in self.statements(rp.a("policy") or ""):
                if (self.field(top, "Effect") or ["Allow"])[0] != "Allow":
                    continue
                for a in self.field(top, "Action") or []:
                    if ":" in a and not any(fnmatch.fnmatchcase(a.lower(), pat) for pat in role_allow[m.group(1)]):
                        self.r.fail(f"{rp.file}:{rp.line}", "境界の外", f"{rp.addr} の操作 {a} が権限の境界の外。方針に書いても拒まれる。境界に足すか、方針から外す")

    def walk(self):
        stack = list(self.blocks)
        while stack:
            b = stack.pop()
            yield b
            stack += b.blocks

    def check_port(self, owner, rule, cidrs, proto):
        if not any(c in OPEN_CIDRS for c in cidrs):
            return
        p = literal(proto)
        if p in ("-1", "all", -1.0):
            self.hit("IAC-004", owner.file, rule.line, f"{owner.addr} がすべての口を 0.0.0.0/0 に開けている")
            return
        lo, hi = literal(rule.a("from_port")), literal(rule.a("to_port"))
        if not isinstance(lo, float) or not isinstance(hi, float):
            self.r.warn(f"{owner.file}:{rule.line}", "IAC-004 CRITICAL 管理の口の全開", f"{owner.addr} の口の番号を値に解けない")
            return
        hits = [str(pt) for pt in ADMIN_PORTS if lo <= pt <= hi]
        if hits:
            self.hit("IAC-004", owner.file, rule.line, f"{owner.addr} が {','.join(hits)} 番を 0.0.0.0/0 に開けている")


def check_iac(paths, r):
    for p in paths:
        if not pathlib.Path(p).exists():
            r.fail(p, "無い", "ファイルかディレクトリが無い")
            return 0
    scan = IacScan(paths, r)
    if not scan.files:
        r.fail(" ".join(paths), "対象", ".tf が 1 つも無い")
        return 0
    return scan.run()


def print_rules():
    print("| 番号 | 重さ | 名前 | 直し方 |")
    print("|---|---|---|---|")
    for k, (sev, title, fix) in RULES.items():
        print(f"| {k} | {sev} | {title} | {fix} |")
    return 0


# =====================================================================
# 3. 計画の差分の関所（plan）: terraform show -json の出力を読む
# =====================================================================
# 決め方は「許す物の一覧」。承認 1 人の適用（ROUTE: apply）で通してよいのは、下の一覧にある型の、一覧にある属性の変更だけ。
# 一覧に無い型、一覧に無い属性の変更、新しく作る資源は、すべて守りの経路（ROUTE: guarded、承認 2 人）へ回す。
# データを消すか消せるようにする変更（置き換え、削除、保持を縮める、削除の保護を外す）と、一覧の外の部品（プロバイダ）は止める。
# AWS の側でも、一覧の外の操作は適用の役割に持たせていない（foundation/iam.tf）。データへ届く操作は SCP が名指しの役割のほかを拒む（org/scp.tf）。
APPLY_ALLOW = {
    "aws_ecs_service": {"desired_count", "task_definition"},
    # 中身は API のイメージのダイジェストだけ（apply_task_ok で見る）。移行と利用者づくりの作業の定義は一覧に入れない。
    "aws_ecs_task_definition": {"container_definitions"},
    "aws_appautoscaling_target": {"min_capacity", "max_capacity"},
    "aws_appautoscaling_policy": {"target_tracking_scaling_policy_configuration"},
    # データベース（aws_db_instance）は一覧に入れない。大きさの変更も rds:ModifyDBInstance で、同じ 1 回の操作が合言葉・公開・網・
    # パラメータグループ・削除の保護・保持の日数まで変える。この操作に効く IAM の条件キーは rds:ManageMasterUserPassword だけで、
    # 大きさだけに絞れない（aws-facts の 47〜52）。適用の役割にも持たせず（foundation/iam.tf）、全部を守りの経路へ回す。
    "aws_lb_target_group": {"health_check", "deregistration_delay"},
}
# 一覧の属性のうち、値の形まで決める物。属性の名前だけでなく、指す先も一覧の内側に限る（値が計画の時点で決まらないときは、
# 指す先の資源の変更が別に判定される）。サービスに付ける作業の定義は API の family の版だけ。移行や利用者づくりの版は守りの経路。
APPLY_VALUES = {
    ("aws_ecs_service", "task_definition"): re.compile(r"(^|task-definition/)[^/:]*-orders-api(:[0-9]+)?$"),
}
# どの型でも比べない属性（AWS が決める値と、札の写し）。
IGNORED_ATTRS = {"id", "arn", "revision", "arn_without_revision", "tags_all", "tags"}
# 置き換えで出すのが平常の型（データを持たない）。作り直しの中身が一覧の属性だけなら承認 1 人で通す。
REPLACE_OK = {"aws_ecs_task_definition"}
# 承認 1 人で版を足してよい作業の定義の family（名前の末尾）。移行（db-migrate）と利用者づくり（db-bootstrap）は入れない。
APPLY_TASK_FAMILIES = ("-orders-api",)
# データを消すか、消せるようにする変更。置き換えと削除と同じく止める（守りの経路でも通さない）。
#   (属性, 止める向き): "decrease" は値が減る、"to-false" は true から外す、"to-true" は true にする。
STOP_ATTRS = {
    "aws_db_instance": [("backup_retention_period", "decrease"), ("deletion_protection", "to-false"), ("skip_final_snapshot", "to-true")],
    "aws_cloudwatch_log_group": [("retention_in_days", "decrease")],
    "aws_backup_vault_lock_configuration": [("min_retention_days", "decrease")],
    "aws_lb": [("enable_deletion_protection", "to-false")],
}
# 計画と適用で読み込んでよい部品（プロバイダ）。一覧の外の部品は、計画のときにコードが動くので止める。
ALLOWED_PROVIDERS = {
    "registry.terraform.io/hashicorp/aws", "registry.terraform.io/hashicorp/archive", "registry.terraform.io/integrations/github",
}
DIGEST_RX = re.compile(r"^(?P<repo>[^@\s]+)@(?P<digest>sha256:[0-9a-f]{64})$")


def changed_attrs(ch):
    before, after = ch.get("before") or {}, ch.get("after") or {}
    unknown = ch.get("after_unknown") or {}
    keys = set(before) | set(after) | {k for k, v in unknown.items() if v}
    return sorted(k for k in keys - IGNORED_ATTRS if before.get(k) != after.get(k) or unknown.get(k))


def apply_task_ok(ch, attested):
    """API の作業の定義で、変わったのがイメージのダイジェストだけ、しかも来歴を確かめたダイジェストなら空。違えば理由を返す。"""
    before, after = ch.get("before") or {}, ch.get("after") or {}
    if (ch.get("after_unknown") or {}).get("container_definitions"):
        return "container_definitions が計画の時点で決まらない"
    if not str(after.get("family", "")).endswith(APPLY_TASK_FAMILIES):
        return f"family {after.get('family')} は承認 1 人の一覧の外（移行と利用者づくりは守りの経路）"
    try:
        old, new = json.loads(before.get("container_definitions") or "[]"), json.loads(after.get("container_definitions") or "[]")
    except (TypeError, ValueError):
        return "container_definitions を読めない"
    if len(old) != len(new):
        return "コンテナの数が変わる"
    for o, n in zip(old, new):
        if {k: v for k, v in o.items() if k != "image"} != {k: v for k, v in n.items() if k != "image"}:
            diff = sorted(k for k in set(o) | set(n) if k != "image" and o.get(k) != n.get(k))
            return f"コンテナ {n.get('name')} の {','.join(diff)} が変わる（命令・環境変数・秘密・ログの置き場は守りの経路）"
        mo, mn = DIGEST_RX.match(str(o.get("image", ""))), DIGEST_RX.match(str(n.get("image", "")))
        if not mn:
            return f"コンテナ {n.get('name')} のイメージがダイジェストで固定されていない"
        if mo and mo.group("repo") != mn.group("repo"):
            return f"コンテナ {n.get('name')} のイメージのリポジトリが変わる"
        if (not mo or mo.group("digest") != mn.group("digest")) and mn.group("digest") not in attested:
            return f"ダイジェスト {mn.group('digest')[:19]}… の来歴が確かめられていない（--attested の一覧に無い）"
    return ""


METRIC_VALUE_OK = re.compile(r"^-?[0-9]+(\.[0-9]+)?$")


def metric_copy_reasons(typ, ch):
    """メトリクスフィルタが記録の欄の値をメトリクスへ写す形か。次元（dimensions）を持つか、値（value）が数の定数でなければ理由を返す。
    次元の値は ListMetrics で、値は GetMetricData で読めるので、記録の欄（氏名や問い合わせの文）を数えずに外へ運べる（第 13 回）。"""
    if typ == "aws_cloudwatch_log_data_protection_policy":
        # データ保護の方針の監査の所見の送り先（S3、Firehose、ロググループ）は空だけを許す。所見に値が入るかは確かめず、外への道を置かない。
        try:
            doc = json.loads((ch.get("after") or {}).get("policy_document") or "{}")
        except (TypeError, ValueError):
            return ["policy_document を読めない"]
        dest = [((st.get("Operation") or {}).get("Audit") or {}).get("FindingsDestination") for st in doc.get("Statement", [])]
        return ["監査の所見の送り先を置く（空だけを許す）"] if any(dest) else []
    if typ != "aws_cloudwatch_log_metric_filter":
        return []
    out = []
    for mt in (ch.get("after") or {}).get("metric_transformation") or []:
        if mt.get("dimensions"):
            out.append(f"次元 {sorted(mt['dimensions'])} で記録の欄をメトリクスの次元に写す")
        if not METRIC_VALUE_OK.match(str(mt.get("value", ""))):
            out.append(f"値 {mt.get('value')} で記録の欄をメトリクスの値に写す（数の定数だけを許す）")
    return out


def stop_reasons(typ, ch):
    before, after = ch.get("before") or {}, ch.get("after") or {}
    out = metric_copy_reasons(typ, ch)
    for attr, how in STOP_ATTRS.get(typ, []):
        b, a = before.get(attr), after.get(attr)
        if how == "decrease" and isinstance(b, (int, float)) and isinstance(a, (int, float)) and a < b:
            out.append(f"{attr} を {b:g} から {a:g} に縮める")
        elif how == "to-false" and b is True and a is not True:
            out.append(f"{attr} を外す")
        elif how == "to-true" and b is not True and a is True:
            out.append(f"{attr} を true にする")
    return out


def config_provisioners(plan):
    """構成（configuration）にある provisioner（local-exec など）を、子の module まで並べる。
    provisioner は資源の属性の差分に出ず、作り直しのときに適用の役割の資格で命令を動かす。"""
    out = []

    def walk(mod, prefix):
        for res in (mod or {}).get("resources", []) or []:
            for pv in res.get("provisioners", []) or []:
                out.append((prefix + str(res.get("address", "?")), str(pv.get("type", "?"))))
        for name, call in ((mod or {}).get("module_calls") or {}).items():
            walk((call or {}).get("module"), f"{prefix}module.{name}.")

    walk((plan.get("configuration") or {}).get("root_module"), "")
    return out


def load_attested(path, r):
    if not path:
        return set()
    try:
        lines = pathlib.Path(path).read_text(encoding="utf-8").splitlines()
    except OSError as e:
        r.fail(path, "来歴の一覧", f"来歴を確かめたダイジェストの一覧を読めない（{e}）")
        return set()
    return {s.strip() for s in lines if re.fullmatch(r"sha256:[0-9a-f]{64}", s.strip())}


def check_plan(path, r, attested_path=None):
    try:
        plan = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        r.fail(path, "読めない", f"計画の JSON を読めない（{e}）。terraform show -json <計画> の出力を渡す")
        return {}, "stop"
    attested = load_attested(attested_path, r)
    counts = {"追加": 0, "変更": 0, "置き換え": 0, "削除": 0, "守り": 0}
    route = "apply"
    providers = {p.get("full_name") for p in ((plan.get("configuration") or {}).get("provider_config") or {}).values()}
    providers |= {rc.get("provider_name") for rc in plan.get("resource_changes", [])}
    for p in sorted(x for x in providers if x and x not in ALLOWED_PROVIDERS):
        r.fail(p, "部品の一覧", f"部品 {p} は一覧の外。計画のときにコードが動くので止める（部品の指紋は main の版を使う）")
    # 命令を動かす仕掛け（provisioner）は、承認 1 人の一覧に無い。属性の差分が一覧の内側でも、構成にあれば守りの経路へ回す。
    for addr, kind in config_provisioners(plan):
        counts["守り"] += 1
        route = "guarded"
        print(f"GUARD {addr} [守りの差分] provisioner {kind} は承認 1 人の一覧の外（適用の役割の資格で命令が動く）。守りの適用（<環境>-guarded、承認 2 人）で適用する")
    for rc in plan.get("resource_changes", []):
        ch = rc.get("change", {})
        acts = ch.get("actions", [])
        if acts in (["no-op"], ["read"]) or not acts:
            continue
        addr, typ = rc.get("address", "?"), rc.get("type", "")
        why = []
        if "delete" in acts and "create" in acts:
            counts["置き換え"] += 1
            if typ not in REPLACE_OK:
                r.fail(addr, "置き換えか削除", f"{addr} が置き換えになる（{'/'.join(acts)}）。適用せず止め、差分を秘書に渡す")
                continue
        elif "delete" in acts:
            counts["削除"] += 1
            r.fail(addr, "置き換えか削除", f"{addr} が削除になる。適用せず止め、差分を秘書に渡す")
            continue
        elif "create" in acts:
            counts["追加"] += 1
            why.append("新しく作る資源は一覧の外")
        else:
            counts["変更"] += 1
        for s in stop_reasons(typ, ch):
            r.fail(addr, "データを消す変更", f"{addr} が {s}。どの経路でも通さず止め、差分を秘書に渡す")
        if not why:
            allow = APPLY_ALLOW.get(typ)
            if allow is None:
                why.append(f"型 {typ} は承認 1 人の一覧の外")
            else:
                extra = [k for k in changed_attrs(ch) if k not in allow]
                if extra:
                    why.append(f"一覧の外の属性 {','.join(extra)}")
                after, unknown = ch.get("after") or {}, ch.get("after_unknown") or {}
                for (vt, va), rx in APPLY_VALUES.items():
                    if vt == typ and va in changed_attrs(ch) and not unknown.get(va) and not rx.search(str(after.get(va, ""))):
                        why.append(f"{va} の値 {after.get(va)} は一覧の外（指してよいのは API の family の版だけ）")
                if typ == "aws_ecs_task_definition" and not extra:
                    reason = apply_task_ok(ch, attested)
                    if reason:
                        why.append(reason)
        if why:
            counts["守り"] += 1
            route = "guarded"
            print(f"GUARD {addr} [守りの差分] {'。'.join(why)}。守りの適用（<環境>-guarded、承認 2 人）で適用する")
    for chk in plan.get("checks", []) or []:
        if chk.get("status") == "fail":
            where = (chk.get("address") or {}).get("to_display") or (chk.get("address") or {}).get("name") or "check"
            r.fail(where, "前提の検査", f"{where} が満たされていない。直してから計画を出し直す")
    return counts, route


# =====================================================================
# 4. 実行と自己試験
# =====================================================================
def materialize(src_dir, dst):
    """fixture の *.tf.in を .tf に写す。秘密の形の文字列は、ここで組み立てる（ファイルには置かない）。"""
    fake = {"__FAKE_AKIA__": "AKIA" + "FAKEFAKEFAKEFAKE", "__FAKE_SECRET__": "fake-" + "not-a-real-value"}
    for f in sorted(pathlib.Path(src_dir).glob("*.tf.in")):
        text = f.read_text(encoding="utf-8")
        for k, v in fake.items():
            text = text.replace(k, v)
        (pathlib.Path(dst) / f.name[:-3]).write_text(text, encoding="utf-8")
    return dst


def run(kind, args):
    if kind == "iac" and args and args[0] == "--rules":
        return print_rules()
    if kind == "iac" and args and args[0] == "--fixture":
        # evals から: fixture の .tf.in を一時ディレクトリに .tf として写して検査する
        tmp = tempfile.mkdtemp(prefix="iac-fixture-")
        try:
            materialize(args[1], tmp)
            r = Report(NAMES[kind], args[1])
            n = check_iac([tmp], r)
            for i, it in enumerate(r.items):
                r.items[i] = (it[0], (it[1] or "").replace(tmp, args[1]), it[2], it[3])
            return 0 if r.show(f"資源 {n}、規則 {len(RULES)}") else 1
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    r = Report(NAMES[kind], " ".join(args))
    if kind == "plan":
        attested = None
        if "--attested" in args:
            i = args.index("--attested")
            attested = args[i + 1] if i + 1 < len(args) else ""
            args = args[:i] + args[i + 2:]
        counts, route = check_plan(args[0], r, attested)
        summary = "、".join(f"{k} {v}" for k, v in counts.items())
        ok = r.show(f"{summary}、経路 {route if not r.fails else 'stop'}")
        if not ok:
            return 1
        print(f"ROUTE: {route}")
        return 3 if route == "guarded" else 0
    if kind == "arch":
        check_arch(args[0], r)
        return 0 if r.show() else 1
    n = check_iac(args, r)
    return 0 if r.show(f"資源 {n}、規則 {len(RULES)}") else 1


def quiet(kind, args):
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = run(kind, args)
    return rc, buf.getvalue()


def selftest(kind):
    checks = []
    if kind == "arch":
        rc, out = quiet("arch", [str(SKILL / "examples" / "infra-design-order-list.md")])
        checks.append((rc == 0, f"完成例が落ちた: {out[-400:]}"))
        rc, out = quiet("arch", [str(FIX / "bad-design.md")])
        for rule in ("6 本の柱", "ネットワーク", "IAM", "秘密情報", "復元", "費用の幅", "流出経路", "攻撃者の目", "信頼の根", "推測"):
            checks.append((f"[{rule}]" in out, f"負例で「{rule}」が出ない"))
        rc, out = quiet("arch", [str(SKILL / "templates" / "infra-design.md")])
        checks.append(("[雛形の穴]" in out and rc == 1, "雛形（穴埋めのまま）が通った"))
    elif kind == "plan":
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="plan-gate-"))
        try:
            def plan_of(changes, checks=()):
                f = tmp / f"p{len(list(tmp.iterdir()))}.json"
                f.write_text(json.dumps({"resource_changes": [
                    {"address": f"{t}.x", "type": t, "provider_name": "registry.terraform.io/hashicorp/aws",
                     "change": {"actions": a, "before": b, "after": c}} for t, a, b, c in changes
                ], "checks": [{"address": {"to_display": "check.x"}, "status": s} for s in checks]}), encoding="utf-8")
                return str(f)
            def td(family, image="r/x@sha256:" + "a" * 64, **extra):
                c = {"name": "c", "image": image, "environment": [{"name": "A", "value": "1"}], **extra}
                return {"family": family, "execution_role_arn": "e", "task_role_arn": "t", "container_definitions": json.dumps([c])}
            dig_b = "sha256:" + "b" * 64
            att = tmp / "attested.txt"
            att.write_text(dig_b + "\n", encoding="utf-8")
            rep = ["delete", "create"]
            cases = [
                # (名前, 変更, 期待の終了コード, 期待の文言, --attested を渡すか, 部品)
                ("変更だけの計画が適用の経路にならない", [("aws_ecs_service", ["update"], {"desired_count": 2}, {"desired_count": 3}),
                 ("aws_db_instance", ["no-op"], {}, {})], 0, "ROUTE: apply", False, None),
                ("方針の変更が守りの経路にならない", [("aws_iam_role_policy", ["update"], {"policy": "a"}, {"policy": "b"})], 3, "ROUTE: guarded", False, None),
                ("データベースの置き換えで止まらない", [("aws_db_instance", rep, {}, {})], 1, "[置き換えか削除]", False, None),
                ("バケットの削除で止まらない", [("aws_s3_bucket", ["delete"], {}, {})], 1, "[置き換えか削除]", False, None),
                ("前提の検査の不成立で止まらない", [("aws_ecs_service", ["update"], {}, {})], 1, "[前提の検査]", False, "check-fail"),
                ("データベースの大きさの変更が守りの経路にならない（rds:ModifyDBInstance は守りの適用だけ）",
                 [("aws_db_instance", ["update"], {"instance_class": "db.t4g.micro"}, {"instance_class": "db.t4g.medium"})], 3, "aws_db_instance", False, None),
                ("パラメータグループの付け替えが守りの経路にならない",
                 [("aws_db_instance", ["update"], {"parameter_group_name": "a"}, {"parameter_group_name": "default.postgres16"})], 3, "aws_db_instance", False, None),
                ("合言葉の管理を外す変更が守りの経路にならない",
                 [("aws_db_instance", ["update"], {"manage_master_user_password": True}, {"manage_master_user_password": False})], 3, "ROUTE: guarded", False, None),
                ("保持の日数を 0 にする変更で止まらない",
                 [("aws_db_instance", ["update"], {"backup_retention_period": 14}, {"backup_retention_period": 0})], 1, "[データを消す変更]", False, None),
                ("一覧の外の型（Lambda）が守りの経路にならない",
                 [("aws_lambda_function", ["update"], {"environment": "a"}, {"environment": "b"})], 3, "aws_lambda_function", False, None),
                ("新しく作る資源が守りの経路にならない", [("aws_ecr_lifecycle_policy", ["create"], None, {"policy": "x"})], 3, "新しく作る", False, None),
                ("来歴を確かめた API のダイジェストの差し替えが適用の経路にならない",
                 [("aws_ecs_task_definition", rep, td("o-prod-orders-api"), td("o-prod-orders-api", "r/x@" + dig_b))], 0, "ROUTE: apply", True, None),
                ("来歴の無いダイジェストが守りの経路にならない",
                 [("aws_ecs_task_definition", rep, td("o-prod-orders-api"), td("o-prod-orders-api", "r/x@" + dig_b))], 3, "来歴", False, None),
                ("API の作業の定義の命令の書き換えが守りの経路にならない",
                 [("aws_ecs_task_definition", rep, td("o-prod-orders-api"), td("o-prod-orders-api", command=["sh", "-c", "x"]))], 3, "command", True, None),
                ("移行の作業の定義の書き換えが守りの経路にならない",
                 [("aws_ecs_task_definition", rep, td("o-prod-db-migrate"), td("o-prod-db-migrate", "r/x@" + dig_b))], 3, "family", True, None),
                ("役割の欄が変わる作業の定義が守りの経路にならない",
                 [("aws_ecs_task_definition", rep, td("o-prod-orders-api"), {**td("o-prod-orders-api"), "task_role_arn": "c"})], 3, "task_role_arn", True, None),
                ("メトリクスフィルタの次元で記録の欄を写す変更で止まらない",
                 [("aws_cloudwatch_log_metric_filter", ["create"], None, {"metric_transformation": [{"name": "x", "value": "1",
                   "dimensions": {"who": "$.requestParameters.queryString"}}]})], 1, "次元", False, None),
                ("メトリクスフィルタの値で記録の欄を写す変更で止まらない",
                 [("aws_cloudwatch_log_metric_filter", ["update"], {"metric_transformation": [{"name": "x", "value": "1"}]},
                   {"metric_transformation": [{"name": "x", "value": "$.requestParameters.amount"}]})], 1, "値", False, None),
                ("データ保護の方針の所見を外へ送る変更で止まらない",
                 [("aws_cloudwatch_log_data_protection_policy", ["update"], {"policy_document": "{}"},
                   {"policy_document": json.dumps({"Statement": [{"Operation": {"Audit": {"FindingsDestination": {"S3": {"Bucket": "evil"}}}}}]})})],
                 1, "所見の送り先", False, None),
                ("一覧の外の部品（external）で止まらない", [("aws_ecs_service", ["update"], {}, {})], 1, "[部品の一覧]", False, "external"),
                ("サービスを移行の版に付け替える変更が守りの経路にならない",
                 [("aws_ecs_service", ["update"], {"task_definition": "arn:aws:ecs:r:1:task-definition/o-prod-orders-api:7"},
                   {"task_definition": "arn:aws:ecs:r:1:task-definition/o-prod-db-migrate:3"})], 3, "一覧の外", False, None),
                ("サービスを API の新しい版に付け替える変更が適用の経路にならない",
                 [("aws_ecs_service", ["update"], {"task_definition": "arn:aws:ecs:r:1:task-definition/o-prod-orders-api:7"},
                   {"task_definition": "arn:aws:ecs:r:1:task-definition/o-prod-orders-api:8"})], 0, "ROUTE: apply", False, None),
                ("構成の provisioner（local-exec）が、ダイジェストだけの差し替えでも守りの経路にならない",
                 [("aws_ecs_task_definition", rep, td("o-prod-orders-api"), td("o-prod-orders-api", "r/x@" + dig_b))], 3, "provisioner local-exec", True, "provisioner"),
            ]
            for name, changes, want_rc, want_text, use_att, extra in cases:
                pf = plan_of(changes, checks=["fail"] if extra == "check-fail" else ())
                if extra == "provisioner":
                    data = json.loads(pathlib.Path(pf).read_text(encoding="utf-8"))
                    data["configuration"] = {"root_module": {"module_calls": {"app": {"module": {"resources": [
                        {"address": "aws_ecs_task_definition.api", "provisioners": [{"type": "local-exec"}]}]}}}}}
                    pathlib.Path(pf).write_text(json.dumps(data), encoding="utf-8")
                if extra == "external":
                    data = json.loads(pathlib.Path(pf).read_text(encoding="utf-8"))
                    data["configuration"] = {"provider_config": {"external": {"full_name": "registry.terraform.io/hashicorp/external"}}}
                    pathlib.Path(pf).write_text(json.dumps(data), encoding="utf-8")
                rc, out = quiet("plan", [pf] + (["--attested", str(att)] if use_att else []))
                checks.append((rc == want_rc and want_text in out, f"{name}（終了コード {rc}）: {out[-300:]}"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    else:
        rc, out = quiet("iac", ["--fixture", str(FIX / "good-iac")])
        checks.append((rc == 0, f"良い例の .tf が落ちた: {out[-400:]}"))
        rc, out = quiet("iac", ["--fixture", str(FIX / "bad-iac")])
        checks.append((rc == 1, "悪い例の .tf が通った"))
        for rule in RULES:
            checks.append((f"[{rule} " in out, f"悪い例で {rule} が出ない"))
        checks.append(("[例外の理由]" in out, "理由の無い例外が通った"))
        checks.append(("[境界の外]" in out, "境界の外の操作を持つ役割が通った"))
    ok = True
    for passed, msg in checks:
        if not passed:
            ok = False
            print(f"FAIL selftest {NAMES[kind]}: {msg}")
    print(f"RESULT: {'PASS' if ok else 'FAIL'} {NAMES[kind]} --selftest ({len(checks)} 例)")
    return ok


def main(argv):
    if len(argv) < 2 or argv[0] not in NAMES:
        print(__doc__)
        return 2
    if argv[1] == "--selftest":
        return 0 if selftest(argv[0]) else 1
    return run(argv[0], argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
