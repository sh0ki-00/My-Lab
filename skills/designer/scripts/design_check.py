#!/usr/bin/env python3
"""design_check — デザイナーの成果物の検査。

使い方: design_check.py plan <デザイン計画書>              計画書の節と表（色 4〜6、書体 2〜3 役、シグネチャ、動き、キーボード、既定との差、WCAG）
        design_check.py contrast <デザイン計画書>          色の表の全組のコントラスト比を WCAG 2 の式で計算し、書かれた値と閾値を確かめる
        design_check.py contrast --pair <文字色> <背景色>  2 色の比を出す
        design_check.py ailook <ディレクトリかファイル...> [--plan <計画書>]  実装のコードから AI の既定の見た目を数える
        design_check.py fidelity <計画書> <tokens.css> [<実装の css/html...>]  計画とトークンと実装の値の突き合わせ
        design_check.py review <監修記録>                   監修記録の表と判定
        design_check.py <種類> --selftest
出力: FAIL <場所> [<決まり>] <内容>、WARN …、最後に RESULT: PASS|FAIL <検査名> <対象> (FAIL n、WARN m)。1 件でも FAIL なら終了コード 1。
"""
import pathlib
import re
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
SKILL = HERE.parent
NAMES = {"plan": "design-plan-check", "contrast": "contrast-check", "ailook": "ai-look-check",
         "fidelity": "fidelity-check", "review": "review-check"}
HEX = re.compile(r"#[0-9A-Fa-f]{6}\b")
AI_PURPLE = {"#6366F1", "#8B5CF6", "#7C3AED", "#A855F7", "#667EEA", "#764BA2", "#4F46E5", "#818CF8", "#9333EA", "#C084FC"}
EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿\U0001F900-\U0001F9FF]")
CODE_EXT = (".css", ".html", ".htm", ".js", ".jsx", ".ts", ".tsx", ".vue", ".svelte", ".scss")


# ---- 文書の読み込み（表と節）
def load_lines(name):
    text = pathlib.Path(name).read_text(encoding="utf-8")
    lines, in_code, in_comment = [], False, False
    for i, l in enumerate(text.split("\n"), 1):
        s = l.strip()
        if in_comment:
            in_comment = "-->" not in s
            continue
        if s.startswith("<!--"):
            in_comment = "-->" not in s[4:]
            continue
        if s.startswith("```"):
            in_code = not in_code
            continue
        if not in_code:
            lines.append((i, l))
    return text, lines


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


# ---- コントラスト（WCAG 2 の式）
def luminance(hex_color):
    h = hex_color.lstrip("#")
    out = []
    for i in (0, 2, 4):
        c = int(h[i:i + 2], 16) / 255
        out.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * out[0] + 0.7152 * out[1] + 0.0722 * out[2]


def ratio(fg, bg):
    a, b = luminance(fg), luminance(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def color_tables(ts):
    """色の節の表のうち、16 進の列を持つものを返す。"""
    out = []
    for t in ts:
        if "色" not in t["section"]:
            continue
        k = next((k for k, c in enumerate(t["header"]) if "16" in c or "hex" in c.lower() or "進" in c), None)
        if k is None:
            continue
        out.append((t, k))
    return out


def palette(ts):
    """名前 → 16 進。明るい版とダーク版は表ごとに別の辞書。"""
    result = []
    for t, k in color_tables(ts):
        names = {}
        for _, cells in t["rows"]:
            m = HEX.search(cell(cells, k))
            if m and cells:
                names[cells[0]] = m.group(0).upper()
        result.append((t, k, names))
    return result


PAIR = re.compile(r"(#[0-9A-Fa-f]{6}|[^\s、。（）()／/#]+?)\s*(?:の文字)?\s*(?:の上)?\s*で\s*(\d+(?:\.\d+)?)\s*対\s*1")


def is_derived(t):
    return "導出" in t["section"] or any("導出" in c for c in t["header"])


def check_contrast(name, lines, ts, r):
    found = 0
    pal = palette(ts)
    base = pal[0][2] if pal else {}
    for t, k, own_names in pal:
        names = {**base, **own_names}
        kc = next((k2 for k2, c in enumerate(t["header"]) if "比" in c or "組み合わせ" in c), None)
        if kc is None:
            r.fail(t["no"], "色の表", "表に「組み合わせと比」の列が無い")
            continue
        kr = next((k2 for k2, c in enumerate(t["header"]) if "役割" in c or "使う場所" in c), None)
        for no, cells in t["rows"]:
            own = HEX.search(cell(cells, k))
            if not own:
                r.fail(no, "色の表", f"「{cells[0] if cells else ''}」に 16 進が無い")
                continue
            own = own.group(0).upper()
            role = cell(cells, kr) if kr is not None else ""
            text_cell = cell(cells, kc)
            for m in PAIR.finditer(text_cell):
                other_token, value = m.group(1), float(m.group(2))
                other = other_token.upper() if HEX.fullmatch(other_token) else names.get(other_token)
                if other is None:
                    r.warn(no, "色の表", f"「{other_token}」はこの表の色の名前でも 16 進でもないので、比を確かめられない")
                    continue
                found += 1
                got = ratio(own, other)
                if abs(got - value) > 0.05:
                    r.fail(no, "計算", f"{cells[0]} {own} と {other_token} {other} の比は {got:.2f} 対 1。書かれた {value:.2f} と違う")
                need = 3.0 if re.search(r"部品|枠|焦点|アイコン|大きい文字", role + text_cell) else 4.5
                if re.search(r"装飾|罫線", role + text_cell) and value < 3.0:
                    continue
                if got < need:
                    r.fail(no, "閾値", f"{cells[0]} と {other_token} の比 {got:.2f} 対 1 は {need} 対 1 未満。文字なら 4.5、部品なら 3.0 以上にする")
    if found == 0:
        r.fail(0, "色の表", "確かめられる組（「<色名>で N 対 1」の形）が 1 つも無い")


# ---- デザイン計画書
def check_plan(name, lines, ts, r):
    title = next((l[2:].strip() for _, l in lines if l.startswith("# ")), "")
    if not title.startswith("デザイン計画書"):
        r.fail(1, "表題", "「# デザイン計画書: 件名」で始める")
    for key in ("目的", "方向", "色", "書体", "レイアウト", "シグネチャ", "動き", "キーボード", "既定との差", "WCAG", "引き渡し", "やらないこと"):
        if section(lines, key) is None:
            r.fail(0, "必須の節", f"「## {key}」が無い")
    if section(lines, "未確定") is None:
        r.warn(0, "節", "「## 未確定」が無い。決めていないことが無ければ「なし」と 1 行書く")
    pal = [p for p in palette(ts) if not is_derived(p[0])]
    if not pal:
        r.fail(0, "色", "色の節に 16 進の列を持つ表が無い")
    else:
        t, k, names = pal[0]
        n = len(names)
        if not 4 <= n <= 6:
            r.fail(t["no"], "色", f"名前つきの色が {n} 色。4〜6 色にし、残りは導出で書く")
        for no, cells in t["rows"]:
            if cells and cells[0] not in names:
                r.fail(no, "色", f"「{cells[0]}」の 16 進が無い")
    # 書体
    ts_font = section_tables(ts, "書体")
    if not ts_font:
        if section(lines, "書体") is not None:
            r.fail(0, "書体", "書体の表（役 | 書体 | 大きさと太さ | 使う場所 | 理由）が無い")
    else:
        t = ts_font[0]
        n = len(t["rows"])
        if n < 2:
            r.fail(t["no"], "書体", f"役が {n} つ。見出しと本文の 2 役以上にする")
        elif n > 3:
            r.warn(t["no"], "書体", f"役が {n} つ。4 役以上は理由を書く")
        for no, cells in t["rows"]:
            joined = " ".join(cells)
            for m in re.finditer(r"(\d+)\s*px", joined):
                if int(m.group(1)) < 12:
                    r.fail(no, "書体", f"{m.group(1)}px は 12px 未満。補助の文字も 12px を下限にする")
            for m in re.finditer(r"太さ\s*(\d{3})", joined):
                if int(m.group(1)) < 400:
                    r.fail(no, "書体", f"太さ {m.group(1)} は細すぎる。400 以上にする")
    # シグネチャ
    sec = section(lines, "シグネチャ")
    if sec is not None:
        body = "\n".join(l for _, l in sec)
        if "伝える情報" not in body:
            r.fail(sec[0][0], "シグネチャ", "「伝える情報」の行が無い。情報を持たない装飾はシグネチャにしない")
    # 動き
    ts_motion = section_tables(ts, "動き")
    if ts_motion:
        t = ts_motion[0]
        if col(t, "減らす設定") is None:
            r.fail(t["no"], "動き", "表に「動きを減らす設定のとき」の列が無い")
        if col(t, "キーボード") is None:
            r.fail(t["no"], "動き", "表に「キーボード起点のとき」の列が無い")
        for no, cells in t["rows"]:
            joined = " ".join(cells)
            ms = [int(x) for x in re.findall(r"(\d+)\s*ms", joined)]
            if not ms:
                r.fail(no, "動き", f"「{cells[0] if cells else ''}」に ms の数字が無い")
            elif max(ms) > 300:
                r.fail(no, "動き", f"{max(ms)}ms は 300ms 超。動きは 300ms 未満にする")
    elif section(lines, "動き") is not None:
        r.fail(0, "動き", "動きの表（場面 | 時間と曲線 | 何を伝えるか | 減らす設定 | キーボード起点）が無い")
    body_all = "\n".join(l for _, l in lines)
    if re.search(r"transition:\s*all", body_all):
        r.fail(0, "動き", "transition: all を使わない。動かす属性を書く")
    # キーボード
    ts_key = section_tables(ts, "キーボード")
    sec_key = section(lines, "キーボード")
    if ts_key and sec_key is not None:
        t = ts_key[0]
        kk = col(t, "キー")
        single = any(re.match(r"^[A-Z](\s|$|、|（)", cell(cells, kk)) for _, cells in t["rows"])
        body = "\n".join(l for _, l in sec_key)
        if single and not re.search(r"オフにできる|無効にできる|修飾キー", body):
            r.fail(t["no"], "キーボード", "1 文字キーを使うなら、設定でオフにできるか修飾キーを足せると書く（WCAG 2.2 の 2.1.4）")
        if not re.search(r"矢印|↑|↓", body):
            r.warn(t["no"], "キーボード", "矢印キーでの移動が無い。読み上げの利用者は矢印で表を移る")
    # 既定との差
    ts_diff = section_tables(ts, "既定との差")
    if ts_diff:
        t = ts_diff[0]
        for want in ("既定", "この計画", "なぜ"):
            if col(t, want) is None and not (want == "なぜ" and col(t, "理由") is not None):
                r.fail(t["no"], "既定との差", f"表に「{want}」の列が無い")
        axes = [cells[0] for _, cells in t["rows"] if cells]
        for ax in ("色", "書体", "レイアウト", "シグネチャ", "動き"):
            if not any(ax in a for a in axes):
                r.fail(t["no"], "既定との差", f"「{ax}」の軸が無い。5 軸すべてで既定との差を言う")
        if not any("外した装飾" in a for a in axes):
            r.fail(t["no"], "既定との差", "「外した装飾」の行が無い。仕上げに装飾を 1 つ外す")
        kr = col(t, "なぜ") if col(t, "なぜ") is not None else col(t, "理由")
        for no, cells in t["rows"]:
            if kr is not None and len(cell(cells, kr)) < 10:
                r.fail(no, "既定との差", f"「{cells[0]}」の理由が短い。この依頼に効く理由を 10 字以上で書く")
    elif section(lines, "既定との差") is not None:
        r.fail(0, "既定との差", "自己批評の表（軸 | 既定 | この計画 | なぜこの依頼に効くか）が無い")
    # WCAG
    ts_wcag = section_tables(ts, "WCAG")
    if ts_wcag:
        t = ts_wcag[0]
        kv, kc = col(t, "値"), col(t, "確認")
        if kv is None or kc is None:
            r.fail(t["no"], "WCAG", "表に「値」と「確認方法」の列が要る")
        for no, cells in t["rows"]:
            if kv is not None and not cell(cells, kv).strip():
                r.fail(no, "WCAG", "値が空。設計上の値を書き、実装後に測り直す")
        crit = " ".join(cells[0] for _, cells in t["rows"] if cells)
        if single_key_used(lines) and "2.1.4" not in crit:
            r.fail(t["no"], "WCAG", "1 文字キーを使う計画なので 2.1.4（文字キーのショートカット）の行が要る")
        for want in ("1.4.3", "2.4.7", "2.5.8", "2.4.11"):
            if want not in crit:
                r.fail(t["no"], "WCAG", f"{want} の行が無い")
    elif section(lines, "WCAG") is not None:
        r.fail(0, "WCAG", "点検の表（達成基準 | この計画 | 値 | 確認方法）が無い")
    holes(lines, r)


def single_key_used(lines):
    sec = section(lines, "キーボード")
    if sec is None:
        return False
    return any(re.search(r"\|\s*[A-Z]\s*(と\s*[A-Z]\s*)?[（(｜|]", l) or re.search(r"\|\s*[A-Z]\s*\|", l) for _, l in sec)


# ---- AI の既定の見た目
def scan_files(paths):
    files = []
    for p in paths:
        p = pathlib.Path(p)
        if p.is_dir():
            files += [f for f in sorted(p.rglob("*")) if f.is_file() and f.suffix.lower() in CODE_EXT and "node_modules" not in f.parts]
        elif p.is_file():
            files.append(p)
    return files


def plan_reasons(plan_path):
    """既定との差の表で、理由（10 字以上）がある行の文字列を返す。"""
    if not plan_path:
        return ""
    _, lines = load_lines(plan_path)
    out = []
    for t in section_tables(tables(lines), "既定との差"):
        kr = col(t, "なぜ") if col(t, "なぜ") is not None else col(t, "理由")
        for _, cells in t["rows"]:
            if kr is not None and len(cell(cells, kr)) >= 10:
                out.append(" ".join(cells))
    return "\n".join(out)


def check_ailook(paths, plan_path, r):
    files = scan_files(paths)
    if not files:
        r.fail(0, "対象", "走査できるファイル（css・html・js・tsx・vue・svelte）が無い")
        return
    reasons = plan_reasons(plan_path)
    items = []  # (file:line, 項目, 説明)

    def hit(f, no, key, desc, excuse_words=()):
        if any(w in reasons for w in excuse_words):
            return
        items.append((f"{f}:{no}", key, desc))

    radii, shadows, blur, ctas = {}, [], 0, 0
    for f in files:
        text = f.read_text(encoding="utf-8", errors="replace")
        for no, l in enumerate(text.split("\n"), 1):
            low = l.lower()
            for hx in HEX.findall(l):
                if hx.upper() in AI_PURPLE:
                    hit(f, no, "既定色", f"{hx} は生成 UI の既定の紫", ("紫", hx.upper()))
            if re.search(r"bg-gradient-to-|from-(purple|indigo|violet)|to-(purple|indigo|violet)", l):
                hit(f, no, "グラデーション", "紫系のグラデーションの utility", ("グラデーション",))
            if "linear-gradient(" in low and any(h.upper() in AI_PURPLE for h in HEX.findall(l)):
                hit(f, no, "グラデーション", "既定色の linear-gradient", ("グラデーション",))
            if "backdrop-filter" in low and "blur" in low:
                blur += 1
            if EMOJI.search(l) and f.suffix.lower() in (".html", ".htm", ".jsx", ".tsx", ".vue", ".svelte"):
                hit(f, no, "絵文字", "マークアップの中の絵文字アイコン", ("絵文字",))
            if re.search(r"transition:\s*all\b|\btransition-all\b", l):
                hit(f, no, "動き", "transition: all（動かす属性を書く）", ())
            if re.search(r"animate-(pulse|bounce)", l):
                hit(f, no, "動き", "animate-pulse / animate-bounce（装飾だけの動き）", ("明滅", "pulse"))
            m = re.search(r"cubic-bezier\(\s*[\d.]+\s*,\s*[\d.]+\s*,\s*[\d.]+\s*,\s*([\d.]+)\s*\)", l)
            if m and float(m.group(1)) >= 1.3:
                hit(f, no, "動き", f"cubic-bezier の第 4 引数 {m.group(1)}（跳ね返る動き）", ("跳ね",))
            if re.search(r"<h[1-6][^>]*>\s*0[1-9]\b", l):
                hit(f, no, "番号", "見出しの 01/02/03 の飾り番号", ("番号",))
            for m in re.finditer(r"border-radius:\s*([\d.]+(?:px|rem))", low):
                radii[m.group(1)] = radii.get(m.group(1), 0) + 1
            for m in re.finditer(r"\bshadow-(md|lg|xl|2xl)\b", l):
                shadows.append(m.group(0))
            if re.search(r"Get Started|Learn More|詳しく見る|今すぐ始める", l):
                ctas += 1
            if re.search(r"font-family:\s*[\"']?(Inter|Roboto|Arial|system-ui)[\"']?\s*(,\s*sans-serif)?\s*;", l):
                hit(f, no, "書体", f"既定の書体だけ（{l.strip()[:40]}）", ("Inter", "Roboto", "書体"))
            if "grid-cols-3" in l:
                hit(f, no, "レイアウト", "3 列のカードの型（grid-cols-3）", ("カード", "3 列"))
    if blur >= 3:
        hit("(全体)", 0, "ぼかし", f"backdrop-filter: blur が {blur} か所（ガラス風の多用）", ("ぼかし", "ガラス"))
    if radii and len(radii) == 1 and sum(radii.values()) >= 6:
        v = next(iter(radii))
        hit("(全体)", 0, "角丸", f"角丸が {sum(radii.values())} か所すべて {v}（均一な角丸）", ("角丸",))
    if len(shadows) >= 4 and len(set(shadows)) == 1:
        hit("(全体)", 0, "影", f"影の utility が {len(shadows)} か所すべて {shadows[0]}（均一な影）", ("影",))
    if ctas >= 3:
        hit("(全体)", 0, "文言", f"汎用の CTA 文言が {ctas} 回", ("文言", "CTA"))
    n = len(items)
    band = "clean" if n <= 1 else "mild" if n <= 3 else "sloppy" if n <= 6 else "terminal"
    for where, key, desc in items:
        r.fail(0, key, f"{where} {desc}") if band != "clean" else r.warn(0, key, f"{where} {desc}")
    print(f"AI らしさ: {n} 件、帯 {band}（0〜1 clean、2〜3 mild、4〜6 sloppy、7 以上 terminal。pixelslop の区分）")
    if band != "clean":
        r.fail(0, "帯", f"{n} 件で {band}。計画書の「既定との差」に理由がある項目は --plan で除ける")


# ---- 忠実度
def css_vars(text):
    """--名前: 値; を dict に。"""
    out = {}
    for m in re.finditer(r"(--[a-z0-9-]+)\s*:\s*([^;]+);", text, re.I):
        out.setdefault(m.group(1), m.group(2).strip())
    return out


def check_fidelity(plan_path, tokens_path, impl_paths, r):
    _, lines = load_lines(plan_path)
    ts = tables(lines)
    plan_hex, must_hex = set(), set()
    for t, _, names in palette(ts):
        plan_hex |= set(names.values())
        if not is_derived(t):
            must_hex |= set(names.values())
    plan_ms = set()
    for t in section_tables(ts, "動き"):
        for _, cells in t["rows"]:
            plan_ms |= {int(x) for x in re.findall(r"(\d+)\s*ms", " ".join(cells))}
    tokens = pathlib.Path(tokens_path).read_text(encoding="utf-8")
    token_hex = {h.upper() for h in HEX.findall(tokens)}
    for h in sorted(must_hex - token_hex):
        r.fail(0, "色", f"計画書の {h} が tokens.css に無い")
    for h in sorted(token_hex - plan_hex):
        r.fail(0, "色", f"tokens.css の {h} が計画書の色の表に無い（導出なら color-mix で書く）")
    for name, val in css_vars(tokens).items():
        if name.startswith("--duration"):
            m = re.search(r"(\d+)\s*ms", val)
            if m:
                ms = int(m.group(1))
                if ms > 300:
                    r.fail(0, "動き", f"{name}: {ms}ms は 300ms 超")
                if plan_ms and ms not in plan_ms and ms != 0:
                    r.fail(0, "動き", f"{name}: {ms}ms は計画書の動きの表に無い")
    if re.search(r"transition:\s*all\b", tokens):
        r.fail(0, "動き", "tokens.css に transition: all がある")
    for p in impl_paths:
        text = pathlib.Path(p).read_text(encoding="utf-8", errors="replace")
        if pathlib.Path(p).resolve() == pathlib.Path(tokens_path).resolve():
            continue
        for no, l in enumerate(text.split("\n"), 1):
            for h in HEX.findall(l):
                if h.upper() not in plan_hex:
                    r.fail(no, "生の値", f"{p}:{no} の {h} は計画書に無い色。トークン（var(--…)）で参照する")
            if re.search(r"transition:\s*all\b", l):
                r.fail(no, "動き", f"{p}:{no} に transition: all がある")
            for m in re.finditer(r"(\d+)\s*ms", l):
                if plan_ms and int(m.group(1)) not in plan_ms and int(m.group(1)) != 0:
                    r.fail(no, "動き", f"{p}:{no} の {m.group(1)}ms は計画書の動きの表に無い")


# ---- 監修記録
def check_review(name, lines, ts, r):
    title = next((l[2:].strip() for _, l in lines if l.startswith("# ")), "")
    if not title.startswith("監修記録"):
        r.fail(1, "表題", "「# 監修記録: 件名」で始める")
    for key in ("忠実度", "AI らしさ", "WCAG", "キーボード", "動き", "指摘", "判定"):
        if section(lines, key) is None:
            r.fail(0, "必須の節", f"「## {key}」が無い")
    ts_i = section_tables(ts, "指摘")
    if ts_i:
        t = ts_i[0]
        for want in ("場所", "計画の値", "実装の値", "直し方", "重さ"):
            if col(t, want) is None:
                r.fail(t["no"], "指摘", f"表に「{want}」の列が無い")
        for no, cells in t["rows"]:
            if any(not c for c in cells):
                r.fail(no, "指摘", "空の欄がある。5 つの欄を全部埋める")
    elif section(lines, "指摘") is not None:
        r.fail(0, "指摘", "指摘の表（場所 | 計画の値 | 実装の値 | 直し方 | 重さ）が無い。無ければ 1 行「なし」")
    sec = section(lines, "判定")
    if sec is not None:
        body = "\n".join(l for _, l in sec)
        m = re.search(r"(条件つき受け入れ|受け入れ|差し戻し)", body)
        if not m:
            r.fail(sec[0][0], "判定", "判定は 受け入れ／条件つき受け入れ／差し戻し の 3 択で書く")
        elif m.group(1) == "条件つき受け入れ" and not re.search(r"確認", body):
            r.fail(sec[0][0], "判定", "条件つき受け入れには、条件の確認方法を書く")
    ts_a = section_tables(ts, "AI らしさ")
    if ts_a or section(lines, "AI らしさ") is not None:
        body = "\n".join(l for _, l in (section(lines, "AI らしさ") or []))
        if not re.search(r"\d+\s*件", body) or not re.search(r"clean|mild|sloppy|terminal", body):
            r.fail(0, "AI らしさ", "件数と帯（clean／mild／sloppy／terminal）を書く。感想で書かない")
    for t in section_tables(ts, "WCAG"):
        kv = col(t, "値")
        for no, cells in t["rows"]:
            if kv is not None and not cell(cells, kv).strip():
                r.fail(no, "WCAG", "測った値が空")
    holes(lines, r)


# ---- 自己試験
EX_PLAN = SKILL / "examples" / "design-plan-order-list.md"
EX_TOKENS = SKILL / "examples" / "tokens-order-list.css"
EX_REVIEW = SKILL / "examples" / "design-review-order-list.md"
FIX = SKILL / "evals" / "fixtures"


def run(kind, args):
    if kind == "contrast" and args[:1] == ["--pair"]:
        pair = args[1:3]
        if len(pair) != 2 or not all(HEX.fullmatch(x) for x in pair):
            print("FAIL --pair [引数] 文字色と背景色を #RRGGBB の形で 2 つ渡す（例: --pair \"#767676\" \"#FFFFFF\"）")
            return 2
        fg, bg = pair
        print(f"{fg} on {bg}: {ratio(fg, bg):.2f} 対 1")
        return 0
    if kind == "ailook":
        plan = None
        if "--plan" in args:
            i = args.index("--plan")
            plan = args[i + 1]
            args = args[:i] + args[i + 2:]
        r = Report(NAMES[kind], " ".join(args))
        check_ailook(args, plan, r)
        return 0 if r.show() else 1
    if kind == "fidelity":
        r = Report(NAMES[kind], args[0])
        check_fidelity(args[0], args[1], args[2:], r)
        return 0 if r.show() else 1
    name = args[0]
    _, lines = load_lines(name)
    ts = tables(lines)
    r = Report(NAMES[kind], name)
    {"plan": check_plan, "contrast": check_contrast, "review": check_review}[kind](name, lines, ts, r)
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
    if kind == "contrast":
        checks.append((abs(ratio("#999999", "#FFFFFF") - 2.85) < 0.01, "#999999 対 #FFFFFF が 2.85 にならない"))
        checks.append((abs(ratio("#767676", "#FFFFFF") - 4.54) < 0.01, "#767676 対 #FFFFFF が 4.54 にならない"))
        rc, _ = quiet("contrast", [str(EX_PLAN)])
        checks.append((rc == 0, "完成例の色の表が落ちた"))
        rc, out = quiet("contrast", [str(FIX / "bad-plan.md")])
        checks.append((rc == 1 and "[閾値]" in out, "低コントラストの見本が通った"))
    elif kind == "plan":
        rc, out = quiet("plan", [str(EX_PLAN)])
        checks.append((rc == 0, f"完成例が落ちた: {out[-300:]}"))
        rc, out = quiet("plan", [str(FIX / "bad-plan.md")])
        for rule in ("色", "書体", "シグネチャ", "動き", "既定との差"):
            checks.append((f"[{rule}]" in out, f"負例で「{rule}」が出ない"))
        rc, out = quiet("plan", [str(SKILL / "templates" / "design-plan.md")])
        checks.append(("[雛形の穴]" in out, "雛形（穴埋めのまま）が通った"))
    elif kind == "ailook":
        rc, out = quiet("ailook", [str(FIX / "ai-slop")])
        checks.append((rc == 1 and ("sloppy" in out or "terminal" in out), f"AI らしい見本が落ちない: {out[-200:]}"))
        rc, out = quiet("ailook", [str(FIX / "clean")])
        checks.append((rc == 0 and "clean" in out, f"計画どおりの見本が通らない: {out[-200:]}"))
        rc, out = quiet("ailook", [str(FIX / "ai-slop-excused"), "--plan", str(FIX / "plan-with-reasons.md")])
        checks.append((rc == 0, f"理由のある既定が件数から外れない: {out[-200:]}"))
    elif kind == "fidelity":
        rc, out = quiet("fidelity", [str(EX_PLAN), str(EX_TOKENS), str(FIX / "clean" / "orders.css")])
        checks.append((rc == 0, f"完成例と正しい実装が落ちた: {out[-300:]}"))
        rc, out = quiet("fidelity", [str(EX_PLAN), str(FIX / "tokens-drift.css")])
        checks.append((rc == 1 and "#F4F1EA" in out, f"ずれた tokens が通った: {out[-200:]}"))
    elif kind == "review":
        rc, out = quiet("review", [str(EX_REVIEW)])
        checks.append((rc == 0, f"完成例が落ちた: {out[-300:]}"))
        rc, out = quiet("review", [str(FIX / "bad-review.md")])
        for rule in ("指摘", "判定"):
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
    kind = argv[0]
    if argv[1] == "--selftest":
        return 0 if selftest(kind) else 1
    return run(kind, argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
