#!/usr/bin/env python3
"""frontend_check — フロントエンドの成果物と実装の検査。

使い方: frontend_check.py plan <実装計画>            計画の 14 節と表（構成の動く場所、状態の置き場、取得の上限、予算の数字と測定条件、テストの 1 対 1、横断事項）
        frontend_check.py self <自己点検票>           結果の数字、判定（充足／未確認）、ゲートの出力、未確認の節、推測の語
        frontend_check.py motion <ディレクトリかファイル...>   動きの縮小版（prefers-reduced-motion）の有無、transition: all
        frontend_check.py tokens <ディレクトリかファイル...>   部品の css と html の生の色・px・書体名（トークン以外の値）
        frontend_check.py <種類> --selftest
出力: FAIL <場所> [<決まり>] <内容>、WARN …、最後に RESULT: PASS|FAIL <検査名> <対象> (FAIL n、WARN m)。1 件でも FAIL なら終了コード 1。
"""
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
SKILL = HERE.parent
NAMES = {"plan": "frontend-plan-check", "self": "self-check", "motion": "motion-lint", "tokens": "token-lint"}
CODE_EXT = (".css", ".scss", ".html", ".htm", ".jsx", ".tsx", ".vue", ".svelte")
GUESS = ["動くはず", "通るはず", "速いはず", "と思われ", "おそらく", "たぶん", "ほぼ同じ"]


# ---- 文書
def load_lines(name):
    text = pathlib.Path(name).read_text(encoding="utf-8")
    lines, in_code, in_comment, blocks, start = [], False, False, [], 0
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
                blocks.append(text.split("\n")[start:i - 1])
            start = i
            in_code = not in_code
            continue
        if not in_code:
            lines.append((i, l))
    return lines, blocks


def tables(lines):
    out, cur, section = [], None, ""
    for no, l in lines:
        s = l.strip()
        if s.startswith("#"):
            section, cur = s.lstrip("#").strip(), None
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


def section(lines, key):
    idx = next((k for k, (_, l) in enumerate(lines) if re.match(r"^##\s", l) and key in l), None)
    if idx is None:
        return None
    end = next((j for j in range(idx + 1, len(lines)) if re.match(r"^##\s", lines[j][1])), len(lines))
    return lines[idx:end]


def section_tables(ts, key):
    return [t for t in ts if key in t["section"]]


def col(t, key):
    return next((k for k, c in enumerate(t["header"]) if key in c), None)


def cell(cells, k):
    return cells[k] if k is not None and len(cells) > k else ""


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
        print(f"RESULT: {'PASS' if n == 0 else 'FAIL'} {self.check} {self.name} (FAIL {n}、WARN {len(self.items) - n})")
        return n == 0


def holes(lines, r):
    for no, l in lines:
        if re.search(r"<[^>]*>", l) and not re.search(r"<br\s*/?>", l):
            r.fail(no, "雛形の穴", "<…> が残っている")


def need_cols(r, t, cols, rule):
    pos = {}
    for c in cols:
        k = col(t, c)
        if k is None:
            r.fail(t["no"], rule, f"表に「{c}」の列が無い")
        else:
            pos[c] = k
    return pos


# ---- 実装計画
SECTIONS = ["背景と目的", "全体像", "構成", "状態", "データ取得", "エラー", "性能予算", "テスト", "アクセシビリティ", "忠実度", "横断事項", "実装の進め方", "やらないこと", "未確定"]


def check_plan(name, lines, ts, r):
    title = next((l[2:].strip() for _, l in lines if l.startswith("# ")), "")
    if not title.startswith("実装計画"):
        r.fail(1, "表題", "「# 実装計画: 件名」で始める")
    for key in SECTIONS:
        if section(lines, key) is None:
            r.fail(0, "必須の節", f"「## {key}」が無い")
    t = next(iter(section_tables(ts, "構成")), None)
    if t is None:
        if section(lines, "構成") is not None:
            r.fail(0, "構成", "表（部品 | 置き場 | 動く場所 | 理由）が無い")
    else:
        pos = need_cols(r, t, ["動く場所", "理由"], "構成")
        for no, cells in t["rows"]:
            where = cell(cells, pos.get("動く場所"))
            if pos.get("動く場所") is not None and not re.match(r"^(サーバー|ブラウザ|両方)", where):
                r.fail(no, "構成", f"「{cells[0] if cells else ''}」の動く場所は サーバー／ブラウザ／両方 のどれかで書く")
            if pos.get("理由") is not None and not cell(cells, pos["理由"]).strip():
                r.fail(no, "構成", f"「{cells[0] if cells else ''}」に動く場所の理由が無い")
    t = next(iter(section_tables(ts, "状態")), None)
    if t is None:
        if section(lines, "状態") is not None:
            r.fail(0, "状態", "表（状態 | 出どころ | 置き場）が無い")
    else:
        pos = need_cols(r, t, ["置き場"], "状態")
        seen = {}
        for no, cells in t["rows"]:
            key = cells[0] if cells else ""
            if key in seen:
                r.fail(no, "状態", f"「{key}」が {seen[key]} 行目にもある。同じ値を 2 か所に持たない")
            seen[key] = no
            if pos.get("置き場") is not None and not cell(cells, pos["置き場"]).strip():
                r.fail(no, "状態", f"「{key}」の置き場が空")
    t = next(iter(section_tables(ts, "データ取得")), None)
    if t is None:
        if section(lines, "データ取得") is not None:
            r.fail(0, "データ取得", "表（要求 | いつ | 方法 | 時間の上限と失敗時）が無い")
    else:
        pos = need_cols(r, t, ["上限"], "データ取得")
        for no, cells in t["rows"]:
            v = cell(cells, pos.get("上限"))
            if pos.get("上限") is not None and not re.search(r"\d+\s*(ms|ミリ秒|秒)", v):
                r.fail(no, "データ取得", f"「{cells[0] if cells else ''}」に時間の上限（ms か秒）が無い")
            if pos.get("上限") is not None and not re.search(r"失敗|エラー|打ち切|再試行", v):
                r.fail(no, "データ取得", f"「{cells[0] if cells else ''}」に失敗時の振る舞いが無い")
    t = next(iter(section_tables(ts, "性能予算")), None)
    if t is None:
        if section(lines, "性能予算") is not None:
            r.fail(0, "性能予算", "表（指標 | 予算 | 目標 | 測り方 | 測定条件）が無い")
    else:
        pos = need_cols(r, t, ["予算", "測り方", "測定条件"], "性能予算")
        names = " ".join(cells[0] for _, cells in t["rows"] if cells)
        for want in ("LCP", "INP", "CLS"):
            if want not in names:
                r.fail(t["no"], "性能予算", f"{want} の行が無い。Core Web Vitals の 3 指標を予算にする")
        for no, cells in t["rows"]:
            if pos.get("予算") is not None and not re.search(r"\d", cell(cells, pos["予算"])):
                r.fail(no, "性能予算", f"「{cells[0] if cells else ''}」の予算に数字が無い")
            for k in ("測り方", "測定条件"):
                if pos.get(k) is not None and not cell(cells, pos[k]).strip():
                    r.fail(no, "性能予算", f"「{cells[0] if cells else ''}」の{k}が空")
    t = next(iter(section_tables(ts, "テスト")), None)
    if t is None:
        if section(lines, "テスト") is not None:
            r.fail(0, "テスト", "表（# | 受け入れ条件 | テスト | レベル | サイズ）が無い")
    else:
        pos = need_cols(r, t, ["レベル", "サイズ"], "テスト")
        for no, cells in t["rows"]:
            for k in ("レベル", "サイズ"):
                if pos.get(k) is not None and not cell(cells, pos[k]).strip():
                    r.fail(no, "テスト", f"{k}が空。受け入れ条件とテストを 1 対 1 にする")
    t = next(iter(section_tables(ts, "横断事項")), None)
    if t is None:
        if section(lines, "横断事項") is not None:
            r.fail(0, "横断事項", "表（事項 | 決めたこと | 確かめ方）が無い")
    else:
        pos = need_cols(r, t, ["決めたこと", "確かめ方"], "横断事項")
        names = " ".join(cells[0] for _, cells in t["rows"] if cells)
        for want in ("動き", "国際化", "安全", "型"):
            if want not in names:
                r.fail(t["no"], "横断事項", f"「{want}」の行が無い。動き・国際化・安全・型と道具を計画の段階で決める")
        for no, cells in t["rows"]:
            for k in ("決めたこと", "確かめ方"):
                if pos.get(k) is not None and not cell(cells, pos[k]).strip():
                    r.fail(no, "横断事項", f"「{cells[0] if cells else ''}」の{k}が空")
    holes(lines, r)


# ---- 自己点検票
def check_self(name, lines, blocks, ts, r):
    title = next((l[2:].strip() for _, l in lines if l.startswith("# ")), "")
    if not title.startswith("自己点検票"):
        r.fail(1, "表題", "「# 自己点検票: 件名」で始める")
    t = next((t for t in ts if col(t, "判定") is not None and col(t, "結果") is not None), None)
    if t is None:
        r.fail(0, "表", "点検の表（# | 観点 | 確かめたこと | 結果 | 判定）が無い")
    else:
        kr, kj = col(t, "結果"), col(t, "判定")
        for no, cells in t["rows"]:
            res, jud = cell(cells, kr), cell(cells, kj)
            if not re.match(r"^(充足|未確認)", jud):
                r.fail(no, "判定", f"「{jud}」。判定は 充足 か 未確認（理由） のどちらか")
            if jud.startswith("充足") and not re.search(r"\d|PASS", res):
                r.fail(no, "結果", f"「{cells[1] if len(cells) > 1 else ''}」の結果に数字が無い。測った値か PASS を書く")
    if section(lines, "未確認") is None:
        r.fail(0, "節", "「## 未確認」が無い。確かめられなかったことを理由つきで書く")
    if not any(any("RESULT:" in l for l in b) for b in blocks):
        r.fail(0, "ゲートの出力", "frontend-gate.sh の出力（RESULT: の行）をコードブロックで貼る")
    for no, l in lines:
        for w in GUESS:
            if w in l:
                r.fail(no, "推測", f"「{w}」。測った事実だけを書く")
                break
    holes(lines, r)


# ---- 実装の走査
def scan_files(paths):
    files = []
    for p in paths:
        p = pathlib.Path(p)
        if p.is_dir():
            files += [f for f in sorted(p.rglob("*")) if f.is_file() and f.suffix.lower() in CODE_EXT and "node_modules" not in f.parts]
        elif p.is_file():
            files.append(p)
    return files


def strip_comments(s):
    """css のコメントを、行数を変えずに空白へ置き換える。"""
    return re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)), s, flags=re.S)


def css_chunks(f, text):
    """html なら <style> の中身と style 属性、css ならそのまま。(開始行, 文字列) を返す。コメントは除く。"""
    if f.suffix.lower() in (".html", ".htm", ".vue", ".svelte"):
        out = []
        for m in re.finditer(r"<style[^>]*>(.*?)</style>", text, re.S | re.I):
            start = text[:m.start(1)].count("\n") + 1
            out.append((start, strip_comments(m.group(1))))
        for m in re.finditer(r'\sstyle\s*=\s*"([^"]*)"', text, re.I):
            start = text[:m.start(1)].count("\n") + 1
            out.append((start, m.group(1) + ";"))
        return out
    return [(1, strip_comments(text))]


def load_allow(name):
    p = HERE / name
    if not p.exists():
        return []
    return [re.compile(l.strip()) for l in p.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]


def check_motion(paths, r):
    files = scan_files(paths)
    if not files:
        r.fail(0, "対象", "走査できるファイルが無い")
        return
    allow = load_allow("motion-allow.txt")
    for f in files:
        text = f.read_text(encoding="utf-8", errors="replace")
        for base, chunk in css_chunks(f, text):
            has_reduce = "prefers-reduced-motion" in chunk
            for i, l in enumerate(chunk.split("\n")):
                no = base + i
                if re.search(r"transition:\s*all\b", l):
                    r.fail(no, "動き", f"{f}:{no} transition: all。動かす属性を書く")
                m = re.search(r"\b(transition(?:-duration)?|animation(?:-duration)?)\s*:\s*([^;}]+)", l)
                if not m or re.search(r":\s*none\b", m.group(0)):
                    continue
                decl = m.group(0)
                if any(a.search(decl) for a in allow):
                    continue
                literal = re.search(r"\b\d*\.?\d+\s*m?s\b", m.group(2))
                if literal and not has_reduce:
                    r.fail(no, "縮小版", f"{f}:{no} 「{decl.strip()}」に prefers-reduced-motion の分岐が無い（同じファイルに書く）")
                if not literal and "var(--duration" not in m.group(2) and "var(--motion" not in m.group(2) and not has_reduce:
                    r.fail(no, "縮小版", f"{f}:{no} 「{decl.strip()}」の時間がトークンでも数字でもない")


DECL = re.compile(r"(?<![\w-])(--)?([a-zA-Z-]+)\s*:\s*([^;{}]+)")
COLOR_PROPS = ("color", "background", "border", "outline", "fill", "stroke", "shadow", "caret", "accent")
NAMED = r"\b(?:white|black|red|blue|green|gray|grey|yellow|orange|purple|pink|silver|navy|teal|maroon|aqua|lime|olive)\b"


def declarations(line):
    """1 行の中の宣言（名前, 値）を返す。カスタムプロパティ（--x: …）の定義は除く。"""
    out = []
    for m in DECL.finditer(line):
        if m.group(1):
            continue
        out.append((m.group(2).lower(), m.group(3).strip()))
    return out


def check_tokens(paths, r):
    files = [f for f in scan_files(paths) if "tokens" not in f.name.lower()]
    if not files:
        r.fail(0, "対象", "走査できるファイルが無い（tokens を含む名前のファイルは対象外）")
        return
    allow = load_allow("token-allow.txt")
    for f in files:
        text = f.read_text(encoding="utf-8", errors="replace")
        for base, chunk in css_chunks(f, text):
            for i, l in enumerate(chunk.split("\n")):
                no = base + i
                if l.strip().startswith("@"):
                    continue
                for prop, val in declarations(l):
                    decl = f"{prop}: {val}"
                    if any(a.search(decl) for a in allow):
                        continue
                    named = any(k in prop for k in COLOR_PROPS) and re.search(NAMED, val)
                    if re.search(r"#[0-9A-Fa-f]{3,8}\b|\brgba?\(|\bhsla?\(", val) or named:
                        r.fail(no, "生の色", f"{f}:{no} 「{decl[:60]}」。色はトークン（var(--…)）で参照する")
                        continue
                    px = [m for m in re.finditer(r"(?<![\w.-])(\d+(?:\.\d+)?)px\b", val) if m.group(1) not in ("0", "1")]
                    if px:
                        r.fail(no, "生の px", f"{f}:{no} 「{decl[:60]}」。大きさと余白はトークンで参照する")
                        continue
                    if prop == "font-family" and not val.startswith("var("):
                        r.fail(no, "生の書体", f"{f}:{no} 「{decl[:60]}」。書体はトークン（var(--font-…)）で参照する")


# ---- 自己試験
EX_PLAN = SKILL / "examples" / "frontend-plan-order-list.md"
EX_SELF = SKILL / "examples" / "self-check-order-list.md"
FIX = SKILL / "evals" / "fixtures"


def run(kind, args):
    r = Report(NAMES[kind], " ".join(args) if kind in ("motion", "tokens") else args[0])
    if kind == "motion":
        check_motion(args, r)
    elif kind == "tokens":
        check_tokens(args, r)
    else:
        lines, blocks = load_lines(args[0])
        ts = tables(lines)
        if kind == "plan":
            check_plan(args[0], lines, ts, r)
        else:
            check_self(args[0], lines, blocks, ts, r)
    return 0 if r.show() else 1


def quiet(kind, args):
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = run(kind, args)
    return rc, buf.getvalue()


def selftest(kind):
    ok = True
    name = NAMES[kind]
    checks = []
    if kind == "plan":
        rc, out = quiet("plan", [str(EX_PLAN)])
        checks.append((rc == 0, f"完成例が落ちた: {out[-300:]}"))
        rc, out = quiet("plan", [str(FIX / "bad-plan.md")])
        for rule in ("構成", "データ取得", "性能予算", "横断事項", "雛形の穴"):
            checks.append((f"[{rule}]" in out, f"負例で「{rule}」が出ない"))
        rc, out = quiet("plan", [str(SKILL / "templates" / "frontend-plan.md")])
        checks.append(("[雛形の穴]" in out, "雛形（穴埋めのまま）が通った"))
    elif kind == "self":
        rc, out = quiet("self", [str(EX_SELF)])
        checks.append((rc == 0, f"完成例が落ちた: {out[-300:]}"))
        rc, out = quiet("self", [str(FIX / "bad-self-check.md")])
        for rule in ("判定", "結果", "推測", "ゲートの出力"):
            checks.append((f"[{rule}]" in out, f"負例で「{rule}」が出ない"))
    elif kind == "motion":
        rc, out = quiet("motion", [str(FIX / "good-app")])
        checks.append((rc == 0, f"正例が落ちた: {out[-300:]}"))
        rc, out = quiet("motion", [str(FIX / "bad-app")])
        checks.append((rc == 1 and "[縮小版]" in out and "[動き]" in out, f"負例が通った: {out[-300:]}"))
    elif kind == "tokens":
        rc, out = quiet("tokens", [str(FIX / "good-app")])
        checks.append((rc == 0, f"正例が落ちた: {out[-300:]}"))
        rc, out = quiet("tokens", [str(FIX / "bad-app")])
        for rule in ("生の色", "生の px", "生の書体"):
            checks.append((f"[{rule}]" in out, f"負例で「{rule}」が出ない"))
    for passed, msg in checks:
        if not passed:
            ok = False
            print(f"FAIL selftest {name}: {msg}")
    print(f"RESULT: {'PASS' if ok else 'FAIL'} {name} --selftest ({len(checks)} 例)")
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
