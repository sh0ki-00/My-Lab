#!/usr/bin/env python3
"""design_check — デザイナーの成果物の検査。

使い方: design_check.py plan <デザイン計画書>              計画書の節と表（画面の型、色 4〜6、書体 2〜3 役、シグネチャ、動き、キーボード、既定との差、WCAG）。
                                                           没入の型だけ、方向の 3 案・世界観の設定・場面の一覧と、動きの 4 つの区分の枠を見る。
                                                           既存に合わせる型は、色 4〜6 と既定との差の代わりに、既存の値の節（棚卸しの表）と
                                                           足す値の表を求め、計画書の色・時間・書体と字の大きさを棚卸しの値と突き合わせる
        design_check.py contrast <デザイン計画書>          色の表の全組のコントラスト比を WCAG 2 の式で計算し、書かれた値と閾値を確かめる
        design_check.py contrast --pair <文字色> <背景色>  2 色の比を出す
        design_check.py ailook <ディレクトリかファイル...> [--plan <計画書>]  実装のコードから AI の既定の見た目を数える
        design_check.py fidelity <計画書> <tokens.css> [<実装の css/html...>] [--motion <演出計画書>]... [--existing <既存の UI か棚卸しの表>]...
                                                           計画とトークンと実装の値の突き合わせ。時間のトークンは名前によらず全部を見て、
                                                           上限は計画書の画面の型で決まる。既存に合わせる型は --existing が要り、既存に無い値は
                                                           計画書の「足す値」の表に理由が無ければ落とす
        design_check.py inventory <既存の UI のディレクトリかファイル...>   既存の値（色・時間・大きさ・書体）の出現数の表を出す
        design_check.py review <監修記録>                   監修記録の表と判定（重さ「高」が 1 つ以上なら差し戻し）。没入の型ではフレームの一覧と
                                                           所見の表（5 列。空の欄を落とす）
        design_check.py motion <演出計画書>                 見せ場の 5 つの条件（段 3 つ、レイヤー 3 つ以上、共有要素、動きの重なり、守り 5 行）と、
                                                           点滅・5 秒を超える動き・音の守り、長さの枠、トークンの外の長さ
        design_check.py <種類> --selftest
出力: FAIL <場所> [<決まり>] <内容>、WARN …、最後に RESULT: PASS|FAIL <検査名> <対象> (FAIL n、WARN m)。1 件でも FAIL なら終了コード 1。
読めないファイル（無い、ディレクトリ、UTF-8 でない）は FAIL の行と RESULT の行を出し、終了コード 2。
画面の型（没入の型・既存に合わせる型・今の型）は、計画書の表題の下の表の「画面の型」の行で読む。
没入の型だけが 300ms の線を外し、区分の枠（応答 200ms、移動 500ms、見せ場は初回 1,400ms で 2 回目から 600ms）を使う。
長さは ms のほか、秒（2.5 秒、0.9s）も ms に直して読む。
"""
import pathlib
import re
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
SKILL = HERE.parent
NAMES = {"plan": "design-plan-check", "contrast": "contrast-check", "ailook": "ai-look-check",
         "fidelity": "fidelity-check", "review": "review-check", "motion": "motion-plan-check", "inventory": "ui-inventory"}
HEX = re.compile(r"#[0-9A-Fa-f]{6}\b")
AI_PURPLE = {"#6366F1", "#8B5CF6", "#7C3AED", "#A855F7", "#667EEA", "#764BA2", "#4F46E5", "#818CF8", "#9333EA", "#C084FC"}
EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿\U0001F900-\U0001F9FF]")
CODE_EXT = (".css", ".html", ".htm", ".js", ".jsx", ".ts", ".tsx", ".vue", ".svelte", ".scss")
# ms の数。1,400ms のような 3 桁区切りも読む。区切りの後ろの 400ms だけを拾わない
MS_NUM = r"(\d{1,3}(?:,\d{3})+|\d+)"
MS = re.compile(r"(?<![\d,.])" + MS_NUM + r"\s*ms")
IMMERSIVE = "没入の型"
EXISTING = "既存に合わせる型"
TYPE_RX = re.compile(r"^\s*(没入(?:の型)?|既存に合わせる(?:型)?|今の型)")
# 没入の型の区分と長さの上限（ms）。環境は周期で見る
FRAME = {"応答": 200, "移動": 500, "見せ場": 1400}
SCENE_MIN, SCENE_MAX, REPEAT_MAX = 600, 1400, 600


def ms_values(text):
    return [int(m.group(1).replace(",", "")) for m in MS.finditer(text)]


# 秒の長さ（2.5 秒、4 秒、0.9s）。ms に直して読む
SEC = re.compile(r"(?<![\d,.])(\d+(?:\.\d+)?)\s*(?:秒|s\b)")


def dur_values(text):
    """ms と秒の長さを、どちらも ms の整数で返す。"""
    return ms_values(text) + [int(round(float(m.group(1)) * 1000)) for m in SEC.finditer(text)]


def first_dur(text):
    """最初に出てくる長さ（ms か秒）を ms で返す。無ければ None。"""
    hits = [(m.start(), int(m.group(1).replace(",", ""))) for m in MS.finditer(text)]
    hits += [(m.start(), int(round(float(m.group(1)) * 1000))) for m in SEC.finditer(text)]
    return min(hits)[1] if hits else None


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


def head_rows(lines, ts):
    """表題の下（最初の ## より前）の表の行を、(項目, 行番号, 値) の並びで返す。"""
    limit = next((no for no, l in lines if re.match(r"^##\s", l)), None)
    return [(cells[0], no, cell(cells, 1)) for t in ts if limit is None or t["no"] < limit
            for no, cells in t["rows"] if cells]


def head_get(heads, key):
    return next(((no, v) for k, no, v in heads if key in k), (None, ""))


def screen_type(lines, ts):
    """「画面の型」の行を読み、(型, 行番号, 書かれた値) を返す。
    行が無ければ型は None、没入の型・既存に合わせる型・今の型のどれでもなければ ""。表題の下の表を先に見て、無ければ本文の表を見る。"""
    no, val = head_get(head_rows(lines, ts), "画面の型")
    if no is None:
        no, val = next(((n, cell(cells, 1)) for t in ts for n, cells in t["rows"] if cells and "画面の型" in cells[0]), (None, ""))
    if no is None:
        return None, 0, ""
    m = TYPE_RX.match(val)
    if not m:
        return "", no, val
    word = m.group(1)
    return (IMMERSIVE if word.startswith("没入") else "既存に合わせる型" if word.startswith("既存") else "今の型"), no, val


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
WORLD = ("主題", "方向の名前", "物語", "感情", "素材", "奥行", "動きの語彙", "参照", "取らない方向", "取る危険")
TECHNIQUE = re.compile(r"フェード(?:イン|アウト)?|スライド(?:イン|アウト)?|ズーム(?:イン|アウト)?|フリップ|バウンス|パララックス"
                       r"|fade|slide|zoom|parallax", re.I)
ID_RX = re.compile(r"`([a-z][a-z0-9]*(?:-[a-z0-9]+)+)`")


def check_plan(name, lines, ts, r):
    title = next((l[2:].strip() for _, l in lines if l.startswith("# ")), "")
    if not title.startswith("デザイン計画書"):
        r.fail(1, "表題", "「# デザイン計画書: 件名」で始める")
    stype, tno, tval = screen_type(lines, ts)
    if stype is None:
        r.fail(0, "画面の型", "表題の下の表に「画面の型」の行が無い。受付票の型（没入の型・既存に合わせる型・今の型）を写す")
    elif stype == "":
        r.fail(tno, "画面の型", f"「{tval[:24]}」は 3 つの型のどれでもない。没入の型・既存に合わせる型・今の型のどれかで始める")
    immersive = stype == IMMERSIVE
    existing = stype == EXISTING
    # 既存に合わせる型は、新しい色の数（4〜6）と既定との差を求めず、代わりに既存の値との突き合わせを必須にする
    keys = ["目的", "方向", "色", "書体", "レイアウト", "シグネチャ", "動き", "キーボード", "WCAG", "引き渡し", "やらないこと"]
    keys.insert(8, "既存の値" if existing else "既定との差")
    for key in keys:
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
        if not existing and not 4 <= n <= 6:
            r.fail(t["no"], "色", f"名前つきの色が {n} 色。4〜6 色にし、残りは導出で書く")
        for no, cells in t["rows"]:
            if cells and cells[0] not in names:
                r.fail(no, "色", f"「{cells[0]}」の 16 進が無い")
    if existing:
        check_existing_plan(lines, ts, r)
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
    # 動き。没入の型だけ区分の枠を使い、ほかの型は 300ms の線のまま
    ts_motion = section_tables(ts, "動き")
    if ts_motion:
        t = ts_motion[0]
        if col(t, "減らす設定") is None:
            r.fail(t["no"], "動き", "表に「動きを減らす設定のとき」の列が無い")
        if col(t, "キーボード") is None:
            r.fail(t["no"], "動き", "表に「キーボード起点のとき」の列が無い")
        if immersive:
            check_motion_rows_immersive(t, r)
        else:
            for no, cells in t["rows"]:
                ms = dur_values(" ".join(cells))
                if not ms:
                    r.fail(no, "動き", f"「{cells[0] if cells else ''}」に ms の数字が無い")
                elif max(ms) > 300:
                    r.fail(no, "動き", f"{max(ms):,}ms は 300ms 超。{stype or '今の型'}では動きを 300ms 未満にする（長い演出は没入の型だけ）")
    elif section(lines, "動き") is not None:
        r.fail(0, "動き", "動きの表（場面 | 時間と曲線 | 何を伝えるか | 減らす設定 | キーボード起点）が無い")
    body_all = "\n".join(l for _, l in lines)
    if re.search(r"transition:\s*all", body_all):
        r.fail(0, "動き", "transition: all を使わない。動かす属性を書く")
    if immersive:
        check_immersive_plan(lines, ts, r)
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
    # 既定との差（既存に合わせる型では求めない。既存の値との突き合わせが代わりに掛かる）
    ts_diff = [] if existing else section_tables(ts, "既定との差")
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
    elif not existing and section(lines, "既定との差") is not None:
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


def check_motion_rows_immersive(t, r):
    """没入の型の動きの表。区分ごとの長さの枠、見せ場の 2 回目と演出 ID、環境の周期と止める手段。"""
    kk = col(t, "区分")
    if kk is None:
        r.fail(t["no"], "動き", "没入の型の動きの表に「区分」の列が無い。応答・移動・見せ場・環境のどれかを行ごとに書く")
        return
    kn = col(t, "場面")
    for no, cells in t["rows"]:
        kind = cell(cells, kk)
        label = cell(cells, kn) or kind
        joined = " ".join(cells)
        k = next((x for x in ("応答", "移動", "見せ場", "環境") if x in kind), None)
        if k is None:
            r.fail(no, "動き", f"区分「{kind}」は応答・移動・見せ場・環境のどれでもない")
            continue
        if k == "環境":
            m = re.search(r"周期\s*(\d+(?:\.\d+)?)\s*秒", joined)
            if not m:
                r.fail(no, "動き", f"環境の動き「{label[:20]}」に周期が無い。「周期 N 秒」で書く（4 秒以上）")
            elif float(m.group(1)) < 4:
                r.fail(no, "動き", f"環境の周期 {m.group(1)} 秒は 4 秒未満。4 秒以上でゆっくり小さく動かす")
            if "止め" not in joined or STOP_NEG.search(joined):
                r.fail(no, "動き", "環境の動きに止める手段が無い。5 秒を超えて続く動きは止められるようにする（WCAG 2.2 の 2.2.2）")
            continue
        ms = dur_values(joined)
        if not ms:
            r.fail(no, "動き", f"「{label[:20]}」に ms の数字が無い")
            continue
        if max(ms) > FRAME[k]:
            r.fail(no, "動き", f"{k}は {FRAME[k]:,}ms まで（没入の型の枠）。{max(ms):,}ms を書いている（秒も ms に直して数える）")
        if k == "見せ場":
            m = re.search(r"2\s*回目(.*)", joined)
            second = first_dur(m.group(1)) if m else None
            if second is None:
                r.fail(no, "動き", "見せ場に 2 回目以降の長さが無い。2 回目からは 600ms 以下の短い版にする")
            elif second > REPEAT_MAX:
                r.fail(no, "動き", f"見せ場の 2 回目以降が {second:,}ms。600ms 以下の短い版にする")
            if not ID_RX.search(joined):
                r.fail(no, "動き", "見せ場に演出 ID（`scene-start-login` のような名前）が無い。演出計画書と結ぶ")


def check_immersive_plan(lines, ts, r):
    """没入の型だけの節: 方向の 3 案、世界観の設定 10 行、場面の一覧。"""
    t3 = section_tables(ts, "3 案")
    if not t3:
        r.fail(0, "方向の 3 案", "「### 方向の 3 案」の表が無い。方向を 3 案、静止画 1 枚ずつで並べ、依頼者が 1 つ選ぶ")
    else:
        t = t3[0]
        if len(t["rows"]) != 3:
            r.fail(t["no"], "方向の 3 案", f"案が {len(t['rows'])} つ。3 案を並べる")
        ki, kc = col(t, "静止画"), col(t, "選")
        if ki is None:
            r.fail(t["no"], "方向の 3 案", "表に「静止画」の列が無い。案ごとに静止画を 1 枚置く")
        else:
            for no, cells in t["rows"]:
                if not cell(cells, ki).strip():
                    r.fail(no, "方向の 3 案", f"案「{cells[0]}」の静止画が空")
        if kc is None:
            r.fail(t["no"], "方向の 3 案", "表に「依頼者の選択」の列が無い")
        else:
            chosen = [no for no, cells in t["rows"] if "選んだ" in cell(cells, kc)]
            if len(chosen) != 1:
                r.fail(t["no"], "方向の 3 案", f"依頼者が選んだ案が {len(chosen)} つ。1 つを選んでもらってから色と書体を決める")
    tw = section_tables(ts, "世界観")
    if not tw:
        r.fail(0, "世界観の設定", "「### 世界観の設定」の表が無い。色と書体の前に、世界を 10 行で決める")
    else:
        t = tw[0]
        heads = [cells[0] for _, cells in t["rows"] if cells]
        miss = [k for k in WORLD if not any(k in h for h in heads)]
        if miss:
            r.fail(t["no"], "世界観の設定", f"{'・'.join(miss)} の行が無い。世界観の設定は 10 行で書く")
        for no, cells in t["rows"]:
            v = cell(cells, 1)
            if not v.strip():
                r.fail(no, "世界観の設定", f"「{cells[0]}」が空")
            elif "動きの語彙" in cells[0]:
                rest = re.sub(r"[\s、。・,/（）()「」]", "", TECHNIQUE.sub("", v))
                if len(rest) < 4:
                    r.fail(no, "世界観の設定", "動きの語彙が技法の名前だけ。主題の動詞で書く（潜る、灯る など）")
    if section(lines, "場面") is None:
        r.fail(0, "場面の一覧", "「## 場面の一覧」が無い。画面を場面として並べ、矢印に区分と動きの語彙を書く")
    else:
        rows = [cells for t in section_tables(ts, "場面") for _, cells in t["rows"]]
        if not any("見せ場" in " ".join(c) for c in rows):
            r.fail(0, "場面の一覧", "場面の一覧の表に見せ場が無い。世界に入る場面に見せ場を 1 つ置く")


def single_key_used(lines):
    sec = section(lines, "キーボード")
    if sec is None:
        return False
    return any(re.search(r"\|\s*[A-Z]\s*(と\s*[A-Z]\s*)?[（(｜|]", l) or re.search(r"\|\s*[A-Z]\s*\|", l) for _, l in sec)


# ---- 演出計画書（没入の型の見せ場）
STAGES = ("入り", "見せ場", "収まり")
GUARDS = ("動きを減らす設定", "飛ばす手段", "2 回目以降", "アセットが間に合わない", "終わりのフォーカス")
TOKEN_NAME = re.compile(r"--[a-z0-9-]+")
# 守りの値が「なし」だけ（代わりの版と手段を書いていない）
NEG_ONLY = re.compile(r"^(?:なし|無し|無い|ない|－|-|—|―|n/?a|none)(?:[。．.、]|$)", re.I)
# 止める手段・飛ばす手段・消音の手段を打ち消す書き方（置かない、無い、できない、られない）
STOP_NEG = re.compile(r"止め(?:られ)?ない|止まらない|止められず|(?:止める|停止の)(?:手段|操作|ボタン)は?(?:無い|ない|なし|置かない|置けない|設けない)")
SKIP_NEG = re.compile(r"飛ばせない|飛ばさない|飛ばせず|(?:飛ばす)?(?:手段|操作)は?(?:無い|ない|なし|置かない|置けない|設けない)")
MUTE_NEG = re.compile(r"消音の?(?:操作|ボタン|スイッチ|手段)?は?(?:置かない|置けない|設けない|無い|ない|なし)|消(?:音)?せない|消音(?:でき|させられ)ない")
SILENT = re.compile(r"音なし|音は(?:無し|なし|入れない)|音を入れない|鳴らさない|音を使わない")


def guard_problem(key, v):
    """見せ場の守りの 5 行の中身を見る。None なら良い。値が「なし」だけ、打ち消し、中身の印が無いのを落とす。"""
    s = v.strip()
    if NEG_ONLY.match(s):
        return f"「{s[:12]}」だけ。代わりの版と手段を書く"
    if key == "動きを減らす設定":
        if re.search(r"用意しない|作らない|版は(?:無い|ない|なし)", s):
            return "動きを減らす設定の版を打ち消している。位置を動かさない版を書く"
        if not (re.search(r"動かさない|止め", s) or (re.search(r"溶け込|溶かし|フェード", s) and dur_values(s))):
            return "位置を動かさない版（「動かさない」）か、溶け込みとその長さ（ms）を書く"
    elif key == "飛ばす手段":
        if SKIP_NEG.search(s):
            return "飛ばす手段を打ち消している。どのキーで飛ばせるかを書く"
        if not re.search(r"キー|Esc|Enter|Space|押", s):
            return "飛ばすキー（どのキーでも、Esc など）か押す場所を書く"
    elif key == "アセットが間に合わない":
        if not re.search(r"短い版|替え|動く|動かす|出す|待たず|ms", s):
            return "間に合わないときの代わりの版か手段を書く（短い版に替える、共有要素だけは動かす など）"
    elif key == "終わりのフォーカス":
        if re.search(r"(?:入れ|置か|決め)ない", s):
            return "終わりのフォーカスを打ち消している。フォーカスを入れる要素を書く"
        if not re.search(r"入力欄|ボタン|欄|見出し|リンク|`[^`]+`|#[\w-]+|「[^」]+」", s):
            return "フォーカスを入れる要素の名前（1 つ目の入力欄、`#email` など）を書く"
    return None


def flash_counts(text):
    """点滅の回数の書き方（N 回、1 秒に N 回、毎秒 N 回、N Hz）を全部読む。"""
    return [int(x) for x in re.findall(r"(\d+)\s*回", text)] + [int(float(x)) for x in re.findall(r"(\d+(?:\.\d+)?)\s*Hz", text, re.I)]


def guard_rows(t):
    kv = col(t, "版")
    kv = 1 if kv is None else kv
    return [(cells[0].strip(), no, cell(cells, kv)) for no, cells in t["rows"] if cells]


def find_guard(rows, key, start=False):
    return next(((no, v) for k, no, v in rows if (k.startswith(key) if start else key in k)), (None, ""))


def read_beats(t, names, r):
    """時刻ごとの表を読み、拍の並びを返す。拍は時刻・段・レイヤー・長さ・変化を持つ。"""
    want = ("時刻", "段", "レイヤー", "変化", "長さ", "伝える")
    idx = {w: col(t, w) for w in want}
    miss = [w for w in want if idx[w] is None]
    if miss:
        r.fail(t["no"], "時刻ごとの表", f"列が足りない（{'・'.join(miss)}）。時刻 | 段 | レイヤーと対象 | 変化 | 長さと曲線 | 伝えること")
        return []
    beats = []
    for no, cells in t["rows"]:
        at = ms_values(cell(cells, idx["時刻"]))
        if not at:
            r.fail(no, "時刻ごとの表", "時刻が無い。押した時刻を 0ms として ms で書く")
            continue
        stage_cell = cell(cells, idx["段"])
        stage = next((s for s in STAGES if s in stage_cell), None)
        if stage is None:
            r.fail(no, "段が 3 つ", f"段「{stage_cell[:12]}」は入り・見せ場・収まりのどれでもない")
        target = cell(cells, idx["レイヤー"])
        hit = [n for n in names if n in target]
        if names and not hit:
            r.fail(no, "レイヤー", f"「{target[:20]}」がレイヤーの表のどれでもない。レイヤーの名前で書く")
        lens = ms_values(cell(cells, idx["長さ"]))
        if not lens:
            r.fail(no, "時刻ごとの表", "長さが無い。止まって変わるだけなら 0ms と書く")
        beats.append({"no": no, "at": at[0], "stage": stage, "layers": hit, "target": target,
                      "dur": lens[0] if lens else 0, "change": cell(cells, idx["変化"]), "length": cell(cells, idx["長さ"])})
    return beats


def check_motion_plan(name, lines, ts, r):
    title = next((l[2:].strip() for _, l in lines if l.startswith("# ")), "")
    if not title.startswith("演出計画書"):
        r.fail(1, "表題", "「# 演出計画書: 件名」で始める")
    stype, tno, tval = screen_type(lines, ts)
    if stype is None:
        r.fail(0, "画面の型", "表題の下の表に「画面の型」の行が無い。演出計画書は没入の型で書く")
    elif stype != IMMERSIVE:
        r.fail(tno, "画面の型", f"画面の型が「{tval[:20]}」。演出計画書は没入の型だけで書き、ほかの型の動きは計画書の動きの表に書く")
    heads = head_rows(lines, ts)
    no, v = head_get(heads, "演出 ID")
    if no is None or not ID_RX.search(v):
        r.fail(no or 0, "演出 ID", "表題の下の表に演出 ID（`scene-start-login` のような英小文字とハイフンの名前）を書く")
    no, v = head_get(heads, "区分")
    if no is None or "見せ場" not in v:
        r.fail(no or 0, "区分", "演出計画書は見せ場ごとに書く。区分の行に「見せ場」と書く（移動は計画書の動きの表に書く）")
    no_len, v_len = head_get(heads, "長さ")
    m = re.search(r"初回\s*(?<![\d,.])" + MS_NUM + r"\s*ms", v_len)
    first = int(m.group(1).replace(",", "")) if m else None
    if first is None:
        r.fail(no_len or 0, "長さ", "表題の下の表の「長さ」に「初回 Nms」を書く（見せ場は初回 600〜1,400ms）")
    elif not SCENE_MIN <= first <= SCENE_MAX:
        r.fail(no_len, "長さ", f"初回 {first:,}ms は見せ場の枠（600〜1,400ms）の外")
    # レイヤーの表
    tl = section_tables(ts, "レイヤー")
    layers = [cells[0].strip() for _, cells in tl[0]["rows"] if cells and cells[0].strip()] if tl else []
    if not tl:
        r.fail(0, "レイヤーが 3 つ以上", "「## レイヤー」の表が無い。奥から手前へ、レイヤーと対象と作り方を並べる")
    names = sorted(layers, key=len, reverse=True)
    # 時刻ごとの表
    tt = section_tables(ts, "時刻")
    beats = read_beats(tt[0], names, r) if tt else []
    where = tt[0]["no"] if tt else 0
    if not tt:
        r.fail(0, "時刻ごとの表", "「## 時刻ごとの表」が無い")
    moving = [b for b in beats if b["dur"] > 0]
    # 条件 1: 段が 3 つ
    stages = {b["stage"] for b in beats if b["stage"]}
    if beats and len(stages) < 3:
        got = "・".join(s for s in STAGES if s in stages) or "なし"
        r.fail(where, "段が 3 つ", f"段が {len(stages)} つ（{got}）。入り（押した合図）・見せ場（場面が動く）・収まり（部品が落ち着く）を書く")
    elif beats:
        firsts = [min(b["at"] for b in beats if b["stage"] == s) for s in STAGES]
        if firsts != sorted(firsts):
            r.fail(where, "段が 3 つ", "段の始まりが入り・見せ場・収まりの順になっていない")
    if beats and min(b["at"] for b in beats) > 100:
        r.fail(where, "入り", "最初の動きが 100ms より後。押してから 100ms 以内に、押した合図の動きを置く")
    # 条件 2: レイヤーが 3 つ以上で、違う時刻か速さで動く。1 行に複数のレイヤーを書いた行は、そのレイヤーたちの同じ 1 つの動きと数える。
    # レイヤーごとに (始まり, 長さ, 変化) の組を集め、組の集まりが 2 種類以上あることを求める
    moved = sorted({l for b in moving for l in b["layers"]})
    sigs = {}
    for b in moving:
        for l in b["layers"]:
            sigs.setdefault(l, set()).add((b["at"], b["dur"], b["change"].strip()))
    if beats and len(moved) < 3:
        r.fail(where, "レイヤーが 3 つ以上", f"動くレイヤーが {len(moved)} つ（{'・'.join(moved) or 'なし'}）。奥・中・手前の 3 つ以上を、違う時刻か速さで動かす")
    elif moving and len({frozenset(v) for v in sigs.values()}) < 2:
        r.fail(where, "レイヤーが 3 つ以上", "どのレイヤーも同じ時刻・長さ・変化で動く（1 行に並べたレイヤーは同じ 1 つの動き）。奥と手前を、違う時刻か速さで動かす")
    if len(moving) >= 2 and len({b["change"].strip() for b in moving}) == 1:
        r.fail(where, "レイヤーが 3 つ以上", f"どの行の変化も「{moving[0]['change'].strip()[:20]}」で同じ。レイヤーごとに違う変化を書く（同じ動きをずらしただけの計画は通さない）")
    peak, when = 0, 0
    for p in sorted({b["at"] for b in moving}):
        active = {l for b in moving if b["at"] <= p < b["at"] + b["dur"] for l in b["layers"]}
        if len(active) > peak:
            peak, when = len(active), p
    if peak > 4:
        r.fail(where, "同時に動くレイヤー", f"{when:,}ms に {peak} つのレイヤーが同時に動く。4 つまでにし、フレーム落ちを防ぐ")
    blurred = sorted({l for b in moving if re.search(r"ぼか|ぼけ|blur", b["change"]) for l in b["layers"]})
    if len(blurred) > 1:
        r.fail(where, "ぼかすレイヤー", f"ぼかすレイヤーが {len(blurred)} つ（{'・'.join(blurred)}）。ぼかしは重いので 1 つまでにする")
    # 条件 3: 共有要素が 1 つ
    no_sh, v_sh = head_get(heads, "共有要素")
    shared = re.split(r"[。、（(:：]", v_sh.strip())[0].strip() if v_sh else ""
    if no_sh is None or not shared or re.match(r"^(なし|無し|無い|ない)$", shared):
        r.fail(no_sh or 0, "共有要素が 1 つ", "表題の下の表に「共有要素」を書く。前の場面の部品を 1 つ名指し、次の場面まで付いて来させる")
        shared = ""
    else:
        rows_sh = [b for b in beats if shared in b["target"]]
        stages_sh = {b["stage"] for b in rows_sh if b["stage"]}
        if len(rows_sh) < 2:
            r.fail(no_sh, "共有要素が 1 つ", f"共有要素「{shared}」が時刻ごとの表に {len(rows_sh)} 行しか無い。前の場面と次の場面の両方で動かす")
        elif len(stages_sh) < 2:
            r.fail(no_sh, "共有要素が 1 つ", f"共有要素「{shared}」が 1 つの段（{'・'.join(stages_sh) or 'なし'}）の中でしか動かない。2 つ以上の段にまたがらせ、次の場面まで付いて来させる")
    # 条件 4: 動きが重なる
    pairs = sum(1 for a in moving for b in moving if a is not b and a["at"] < b["at"] < a["at"] + a["dur"])
    if beats and pairs == 0:
        r.fail(where, "動きが重なる", "前の動きが終わる前に次の動きが始まる組が無い。順に並べるだけでは、1 枚ずつ差し替える紙芝居に見える")
    # 条件 5: 守りが 5 行。ほかに 2 回目以降の長さ、点滅、5 秒を超える動き、音
    tg = section_tables(ts, "守り")
    grows = guard_rows(tg[0]) if tg else []
    gwhere = tg[0]["no"] if tg else 0
    missing = [g for g in GUARDS if not find_guard(grows, g)[1].strip()]
    if missing:
        r.fail(gwhere, "守りが 5 行", f"{'と'.join('「' + g + '」' for g in missing)}の行が無い。代わりの版と手段の無い演出は出さない")
    weak = []
    for g in GUARDS:
        gno, gv = find_guard(grows, g)
        problem = guard_problem(g, gv) if gv.strip() else None
        if problem:
            weak.append(g)
            r.fail(gno, "守りが 5 行", f"「{g}」: {problem}")
    no2, v2 = find_guard(grows, "2 回目以降")
    if no2 is not None and v2.strip():
        ms2 = dur_values(v2)
        if not ms2:
            r.fail(no2, "2 回目以降", "短い版の長さを ms で書く（600ms 以下）")
        elif ms2[0] > REPEAT_MAX:
            r.fail(no2, "2 回目以降", f"短い版が {ms2[0]:,}ms。2 回目からは 600ms 以下にする")
    nof, vf = find_guard(grows, "点滅")
    if nof is None:
        r.fail(gwhere, "点滅", "守りの表に点滅の行が無い。明るさの大きな切り替わりの回数を書く（1 秒に 3 回まで。WCAG 2.2 の 2.3.1）")
    else:
        counts = flash_counts(vf)
        if not counts:
            r.fail(nof, "点滅", "点滅の回数が無い。「0 回」か「1 秒に N 回」で書く")
        elif max(counts) > 3:
            r.fail(nof, "点滅", f"明るさの大きな切り替わりが {max(counts)} 回（書いた回数の最大）。1 秒に 3 回までにする（WCAG 2.2 の 2.3.1）")
    for b in beats:
        mb = [int(x) for x in re.findall(r"(?:1\s*秒に|毎秒)\s*(\d+)\s*回", b["change"])]
        if mb and max(mb) > 3:
            r.fail(b["no"], "点滅", f"1 秒に {max(mb)} 回の切り替わり。1 秒に 3 回までにする（WCAG 2.2 の 2.3.1）")
    no5, v5 = find_guard(grows, "5 秒")
    if no5 is None:
        r.fail(gwhere, "5 秒を超える動き", "守りの表に「5 秒を超える動き」の行が無い。止める手段を書き、無ければ「無い」と書く（WCAG 2.2 の 2.2.2）")
    else:
        s5 = v5.strip()
        none_claimed = re.match(r"^(無い|ない|なし|無し)(?:[。、]|$)", s5) and not re.search(r"続|流れ|回り|動き続", s5)
        named = re.search(r"「[^」]*止[^」]*」", s5) or re.search(r"止める(?:ボタン|操作|スイッチ)", s5)
        if not none_claimed and (STOP_NEG.search(s5) or not named):
            r.fail(no5, "5 秒を超える動き", "5 秒を超えて続く動きに止める操作が無いか、打ち消している。止める操作の名前（「動きを止める」など）を書いて置く（WCAG 2.2 の 2.2.2）")
    nos, vs = find_guard(grows, "音", start=True)
    if nos is None:
        r.fail(gwhere, "音", "守りの表に音の行が無い。最初の版は音なしにし、入れるなら消音の操作を常に置く（WCAG 2.2 の 1.4.2）")
    else:
        silent = SILENT.search(vs)
        named = "消音" in vs and (re.search(r"「[^」]+」", vs) or re.search(r"消音の(?:操作|ボタン|スイッチ)", vs))
        if not silent and (MUTE_NEG.search(vs) or not named):
            r.fail(nos, "音", "音を鳴らすのに消音の操作が無いか、打ち消している。消音の操作の名前を書き、常に画面に置く（WCAG 2.2 の 1.4.2）")
    # トークンの外の長さ
    tk = section_tables(ts, "トークン")
    if not tk:
        r.fail(0, "トークン", "「## トークン」の表が無い。時刻ごとの表の長さを、トークンの名前と値で持つ")
    else:
        kv = col(tk[0], "値")
        kv = 1 if kv is None else kv
        token_ms, token_names = set(), set()
        for _, cells in tk[0]["rows"]:
            nm = TOKEN_NAME.search(cells[0]) if cells else None
            if nm:
                token_names.add(nm.group(0))
            token_ms |= set(ms_values(cell(cells, kv)))
        for b in beats:
            text = b["length"] + " " + b["change"]
            for val in ms_values(text):
                if val and val not in token_ms:
                    r.fail(b["no"], "トークンの外の長さ", f"{val:,}ms がトークンの表に無い。長さはトークンで持つ")
            for nm in TOKEN_NAME.findall(text):
                if nm not in token_names:
                    r.fail(b["no"], "トークンの外の長さ", f"{nm} がトークンの表に無い")
    # 時刻ごとの表の終わりと、初回の長さ
    if beats and first:
        end = max(b["at"] + b["dur"] for b in beats)
        if end > first + 20:
            r.fail(where, "長さ", f"時刻ごとの表は {end:,}ms まで続く。初回の長さ {first:,}ms に収める")
    good_guards = len([g for g in GUARDS if g not in missing and g not in weak])
    print(f"見せ場の 5 つの条件: 段 {len(stages)} つ、動くレイヤー {len(moved)} つ、共有要素「{shared or 'なし'}」、"
          f"重なり {pairs} 組、守り {good_guards}/{len(GUARDS)} 行")
    holes(lines, r)


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


WORLD_ROLE_ROWS = ("主題", "物語", "感情", "素材", "奥行", "動きの語彙", "参照")


def plan_reasons(plan_path):
    """(既定との差の表で理由が 10 字以上ある行の文字列, 世界観の設定の決めたことの文字列, 没入の型か) を返す。
    世界観の設定は没入の型の計画書だけで読み、役目を書く行（主題・物語・感情・素材と光・奥行の層・動きの語彙・参照）だけを読む。
    「取らない方向」と「取る危険」と「方向の名前」は読まない（名指しして外した既定や、危険として書いた既定を、理由と取り違えない）。"""
    if not plan_path:
        return "", "", False
    _, lines = load_lines(plan_path)
    ts = tables(lines)
    out = []
    for t in section_tables(ts, "既定との差"):
        kr = col(t, "なぜ") if col(t, "なぜ") is not None else col(t, "理由")
        for _, cells in t["rows"]:
            if kr is not None and len(cell(cells, kr)) >= 10:
                out.append(" ".join(cells))
    immersive = screen_type(lines, ts)[0] == IMMERSIVE
    world = []
    tw = section_tables(ts, "世界観") if immersive else []
    if tw:
        world = [cell(cells, 1) for _, cells in tw[0]["rows"]
                 if cells and any(k in cells[0] for k in WORLD_ROLE_ROWS) and not re.search(r"取らない|取る危険", cells[0])]
    return "\n".join(out), "\n".join(world), immersive


# 没入の型の既定（references/ai-look-catalog.md の 5 節）。ガラスの板は「ぼかし」の項目で数える
SHADOW = re.compile(r"box-shadow|text-shadow|drop-shadow", re.I)
RGB = re.compile(r"rgba?\(\s*(\d{1,3})[\s,]+(\d{1,3})[\s,]+(\d{1,3})")
PARTICLES = re.compile(r"tsparticles|particles(?:\.min)?\.js|particlesJS|react-particles", re.I)
RISE = re.compile(r"fade-?in-?up|fade-?up|slide-?in-?up|slide-?up|data-aos=[\"'](?:fade|slide)-up"
                  r"|initial=\{\{\s*opacity:\s*0\s*,\s*y:\s*\d+", re.I)


def neon_color(line):
    """シアンから紫と赤紫の、彩度の高い色が行にあるか。"""
    import colorsys
    rgbs = [tuple(int(h[i:i + 2], 16) for i in (1, 3, 5)) for h in HEX.findall(line)]
    rgbs += [tuple(int(x) for x in m.groups()) for m in RGB.finditer(line)]
    for rgb in rgbs:
        hue, light, sat = colorsys.rgb_to_hls(*(min(c, 255) / 255 for c in rgb))
        if 170 <= hue * 360 <= 330 and sat >= 0.6 and 0.35 <= light <= 0.85:
            return True
    return False


def check_ailook(paths, plan_path, r):
    files = scan_files(paths)
    if not files:
        r.fail(0, "対象", "走査できるファイル（css・html・js・tsx・vue・svelte）が無い")
        return
    reasons, world, immersive_plan = plan_reasons(plan_path)
    # 没入の型の計画書では、既定を件数から外す理由を世界観の設定の行からだけ読む（既定との差の「既定」の列で外さない）
    source = world if immersive_plan else reasons
    items = []  # (file:line, 項目, 説明)

    def hit(f, no, key, desc, excuse_words=()):
        if any(w in source for w in excuse_words):
            return
        items.append((f"{f}:{no}", key, desc))

    radii, shadows, blur, ctas = {}, [], 0, 0
    glows, rises, particles = [], [], None
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
            if SHADOW.search(l) and any(int(x) >= 20 for x in re.findall(r"(\d+)px", l)) and neon_color(l):
                glows.append(f"{f}:{no}")
            if PARTICLES.search(l) and particles is None:
                particles = (f, no)
            if RISE.search(l):
                rises.append(f"{f}:{no}")
    if len(glows) >= 3:
        hit("(全体)", 0, "ネオンの光", f"シアンか紫の光る影（ぼかし 20px 以上）が {len(glows)} か所。最初は {glows[0]}", ("ネオン", "発光"))
    if particles:
        hit(particles[0], particles[1], "粒子", "粒子の部品を読み込んでいる（意味の無い粒子）", ("粒子",))
    if len(rises) >= 6:
        hit("(全体)", 0, "一律の浮き上がり", f"同じ「下から浮き上がる」動きが {len(rises)} か所。最初は {rises[0]}", ("浮き上が",))
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
        where = "世界観の設定に役目を書いた" if immersive_plan else "計画書の「既定との差」に理由がある"
        r.fail(0, "帯", f"{n} 件で {band}。{where}項目は --plan で除ける")


# ---- 忠実度
def css_vars(text):
    """--名前: 値; を dict に。"""
    out = {}
    for m in re.finditer(r"(--[a-z0-9-]+)\s*:\s*([^;]+);", text, re.I):
        out.setdefault(m.group(1), m.group(2).strip())
    return out


def motion_tokens(path):
    """演出計画書のトークンの表を、名前 → 値の文字列で返す。"""
    _, lines = load_lines(path)
    out = {}
    for t in section_tables(tables(lines), "トークン"):
        kv = col(t, "値")
        kv = 1 if kv is None else kv
        for _, cells in t["rows"]:
            m = TOKEN_NAME.search(cells[0]) if cells else None
            if m:
                out.setdefault(m.group(0), cell(cells, kv).strip().strip("`").strip())
    return out


TIME_VALUE = re.compile(r"^\s*(\d*\.?\d+)\s*(ms|s)\s*$", re.I)


def time_ms(value):
    """トークンの値が時間（120ms、0.9s）なら ms の整数、そうでなければ None。var() や calc() は参照先で見る。"""
    m = TIME_VALUE.match(value.strip().strip("`"))
    if not m:
        return None
    n = float(m.group(1))
    return int(round(n if m.group(2).lower() == "ms" else n * 1000))


# ---- 既存の値（既存に合わせる型）
SHORT_HEX = re.compile(r"#([0-9A-Fa-f]{3})(?![0-9A-Fa-f])")
PX_VALUE = re.compile(r"(?<![\w.-])(\d+(?:\.\d+)?)px\b")
FONT_DECL = re.compile(r"(?:font-family|--font[\w-]*)\s*:\s*([^;{}\n]+)", re.I)


def first_font(value):
    name = value.split(",")[0].strip().strip("'\"").strip()
    return "" if not name or name.startswith("var(") else name.lower()


def blank_comments(text):
    """css と js の /* */、html の <!-- --> を、行数を変えずに空白へ置き換える。注釈の数字を値と数えない。"""
    blank = lambda m: re.sub(r"[^\n]", " ", m.group(0))  # noqa: E731
    return re.sub(r"<!--.*?-->", blank, re.sub(r"/\*.*?\*/", blank, text, flags=re.S), flags=re.S)


def values_in(text):
    """(種類, 値) の組を、行番号つきで返す。色は 16 進の大文字、時間は Nms、大きさは Npx、書体は最初の名前の小文字。"""
    out = []
    for no, l in enumerate(blank_comments(text).split("\n"), 1):
        for h in HEX.findall(l):
            out.append((no, "色", h.upper()))
        for m in SHORT_HEX.finditer(l):
            out.append((no, "色", "#" + "".join(c * 2 for c in m.group(1)).upper()))
        for m in RGB.finditer(l):
            out.append((no, "色", "#" + "".join(f"{min(int(x), 255):02X}" for x in m.groups())))
        for v in dur_values(l):
            if v:
                out.append((no, "時間", f"{v}ms"))
        for m in PX_VALUE.finditer(l):
            if m.group(1) not in ("0", "1"):
                out.append((no, "大きさ", f"{m.group(1)}px"))
        for m in FONT_DECL.finditer(l):
            f = first_font(m.group(1))
            if f:
                out.append((no, "書体", f))
    return out


def norm_value(v):
    """「足す値」の表と棚卸しの表の値をそろえる。"""
    s = v.strip().strip("`").strip()
    if HEX.fullmatch(s):
        return s.upper()
    if SHORT_HEX.fullmatch(s):
        return "#" + "".join(c * 2 for c in s[1:]).upper()
    t = time_ms(s)
    if t is not None:
        return f"{t}ms"
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*px", s)
    if m:
        return f"{m.group(1)}px"
    return s.strip("'\"").lower()


def inventory(paths):
    """既存の UI の値を {(種類, 値): [出現数, 最初の場所]} で返す。"""
    inv = {}
    for f in scan_files(paths):
        text = f.read_text(encoding="utf-8", errors="replace")
        for no, kind, val in values_in(text):
            item = inv.setdefault((kind, val), [0, f"{f}:{no}"])
            item[0] += 1
    return inv


def run_inventory(paths, r):
    files = scan_files(paths)
    if not files:
        r.fail(0, "対象", "走査できるファイル（css・html・js・tsx・vue・svelte）が無い")
        return
    inv = inventory(paths)
    order = {"色": 0, "時間": 1, "大きさ": 2, "書体": 3}
    print(f"# 既存の値の棚卸し: {' '.join(paths)}\n")
    print("| 種類 | 値 | 出現数 | 最初の場所 |")
    print("|---|---|---|---|")
    for (kind, val), (n, where) in sorted(inv.items(), key=lambda x: (order[x[0][0]], -x[1][0], x[0][1])):
        print(f"| {kind} | {val} | {n} | {where} |")
    counts = "、".join(f"{k} {sum(1 for (kk, _) in inv if kk == k)}" for k in order)
    print(f"\n既存の値: {counts}（ファイル {len(files)} 本）")


def existing_values(paths):
    """--existing の値の集まり。.md は棚卸しの表（値の列）を読み、ほかは既存の UI のコードを走査する。"""
    vals = set()
    for p in paths:
        if pathlib.Path(p).suffix.lower() == ".md":
            _, lines = load_lines(p)
            for t in tables(lines):
                kv = col(t, "値")
                if kv is not None:
                    vals |= {norm_value(cell(cells, kv)) for _, cells in t["rows"]}
        else:
            vals |= {v for (_, v) in inventory([p])}
    return vals


def added_values(ts):
    """計画書の「足す値」の表の値（理由のある行だけ）。"""
    out = set()
    for t in section_tables(ts, "足す値"):
        kv, kr = col(t, "値"), col(t, "理由")
        for _, cells in t["rows"]:
            v = cell(cells, kv).strip()
            if v and not re.match(r"^(なし|無し)$", v) and len(cell(cells, kr).strip()) >= 6:
                out.add(norm_value(v))
    return out


def check_added_values(ts, r):
    """既存に合わせる型の計画書: 「足す値」の表（値 | 種類 | 理由）がある。足さないなら「なし」の 1 行。"""
    ta = section_tables(ts, "足す値")
    if not ta:
        r.fail(0, "足す値", "既存に合わせる型は「足す値」の表（値 | 種類 | 理由）を書く。既存の UI に無い値を足すときだけ 1 行ずつ理由と書き、足さないなら「なし」の 1 行")
        return
    t = ta[0]
    kv, kr = col(t, "値"), col(t, "理由")
    if kv is None or kr is None:
        r.fail(t["no"], "足す値", "表に「値」と「理由」の列が要る")
        return
    for no, cells in t["rows"]:
        v = cell(cells, kv).strip()
        if not re.match(r"^(なし|無し)$", v) and len(cell(cells, kr).strip()) < 6:
            r.fail(no, "足す値", f"「{v[:16]}」の理由が短い。既存の値で足りない理由を 6 字以上で書く")


def plan_inventory(ts):
    """既存に合わせる型の計画書の「## 既存の値」の節にある棚卸しの表（種類 | 値 | 出現数 | 最初の場所）の値。"""
    vals = set()
    for t in section_tables(ts, "既存の値"):
        kv = col(t, "値")
        if kv is None or col(t, "種類") is None or col(t, "出現数") is None:
            continue
        vals |= {norm_value(cell(cells, kv)) for _, cells in t["rows"] if cell(cells, kv).strip()}
    return vals


def check_existing_plan(lines, ts, r):
    """既存に合わせる型の計画書: 「## 既存の値」の節に棚卸しの表と出どころがあり、足す値の表があり、
    計画書の名前つきの色・動きの長さ・書体と字の大きさが、棚卸しの値か「足す値」の表（理由つき）にある。"""
    sec = section(lines, "既存の値")
    known = plan_inventory(ts)
    if sec is not None:
        body = "\n".join(l for _, l in sec)
        if "--inventory" not in body:
            r.fail(sec[0][0], "既存の値", "棚卸しの出どころ（fidelity-check.sh --inventory <既存の UI の置き場>）を節に書く")
        if not known:
            r.fail(sec[0][0], "既存の値", "棚卸しの表（種類 | 値 | 出現数 | 最初の場所）が無いか、値が 0 件。--inventory の出力を貼る")
    check_added_values(ts, r)
    if not known:
        return
    allowed = known | added_values(ts)
    hint = "足すなら「足す値」の表に理由を書く"
    for t, k, _ in palette(ts):
        if is_derived(t):
            continue  # 導出の色は既存の色の式。式の元の色を名前つきの表で突き合わせる
        for no, cells in t["rows"]:
            m = HEX.search(cell(cells, k))
            if m and m.group(0).upper() not in allowed:
                r.fail(no, "既存の値", f"色 {m.group(0).upper()}（{cells[0]}）は既存の UI に無い。{hint}")
    for t in section_tables(ts, "動き")[:1]:
        for no, cells in t["rows"]:
            for v in dur_values(" ".join(cells)):
                if v and f"{v}ms" not in allowed:
                    r.fail(no, "既存の値", f"時間 {v}ms（{cells[0][:16]}）は既存の UI に無い。{hint}")
    fonts = sorted(v for v in allowed if not re.match(r"^(#|\d)", v))
    for t in section_tables(ts, "書体")[:1]:
        kf = col(t, "書体")
        for no, cells in t["rows"]:
            if kf is not None and not any(f in cell(cells, kf).lower() for f in fonts):
                r.fail(no, "既存の値", f"書体の行「{cells[0]}」の書体が既存の UI の書体（{'・'.join(fonts) or 'なし'}）に無い。{hint}")
            for m in re.finditer(r"(\d+(?:\.\d+)?)\s*px", " ".join(cells)):
                if f"{m.group(1)}px" not in allowed:
                    r.fail(no, "既存の値", f"大きさ {m.group(1)}px（書体の行「{cells[0]}」）は既存の UI に無い。{hint}")


def check_fidelity(plan_path, tokens_path, impl_paths, r, motion_paths=(), existing_paths=()):
    _, lines = load_lines(plan_path)
    ts = tables(lines)
    stype = screen_type(lines, ts)[0]
    immersive = stype == IMMERSIVE
    plan_hex, must_hex = set(), set()
    for t, _, names in palette(ts):
        plan_hex |= set(names.values())
        if not is_derived(t):
            must_hex |= set(names.values())
    # 計画書の動きの表の長さ（ms と秒）。没入の型の行は、区分の枠を計画書の検査が確かめてある
    plan_ms = set()
    for t in section_tables(ts, "動き"):
        for _, cells in t["rows"]:
            plan_ms |= set(dur_values(" ".join(cells)))
    tokens = pathlib.Path(tokens_path).read_text(encoding="utf-8")
    token_vars = css_vars(tokens)
    if motion_paths and not immersive:
        r.fail(0, "画面の型", "演出計画書（--motion）は没入の型だけ。計画書の画面の型が没入の型でない")
    motion_tok = {}
    for mp in motion_paths:
        for name, val in motion_tokens(mp).items():
            motion_tok[name] = val
            got = token_vars.get(name)
            if got is None:
                r.fail(0, "動き", f"演出計画書の {name}（{val}）が tokens.css に無い")
            elif (ms_values(val) or [re.sub(r"\s", "", val)]) != (ms_values(got) or [re.sub(r"\s", "", got)]):
                r.fail(0, "動き", f"{name} は演出計画書で {val}、tokens.css で {got}。演出計画書の値に合わせる")
    token_hex = {h.upper() for h in HEX.findall(tokens)}
    for h in sorted(must_hex - token_hex):
        r.fail(0, "色", f"計画書の {h} が tokens.css に無い")
    for h in sorted(token_hex - plan_hex):
        r.fail(0, "色", f"tokens.css の {h} が計画書の色の表に無い（導出なら color-mix で書く）")
    # 時間のトークンは名前によらず全部を見る（--duration-* だけでなく --motion-*・--dive-* なども）。
    # 演出計画書のトークンの表にある名前は、上で値の一致を見た。ほかは計画書の動きの表の値に限り、上限は画面の型で決める
    for name, val in token_vars.items():
        ms = time_ms(val)
        if ms is None:
            continue
        if name in motion_tok:
            if ms > SCENE_MAX:
                r.fail(0, "動き", f"{name}: {ms:,}ms は見せ場の枠 {SCENE_MAX:,}ms 超")
            continue
        limit = SCENE_MAX if immersive else 300
        if ms > limit:
            r.fail(0, "動き", f"{name}: {ms:,}ms は見せ場の枠 {limit:,}ms 超" if immersive else f"{name}: {ms:,}ms は 300ms 超")
        if plan_ms and ms not in plan_ms and ms != 0:
            hint = "（演出計画書のトークンなら、その名前で演出計画書のトークンの表に書き、--motion で渡す）" if immersive else ""
            r.fail(0, "動き", f"{name}: {ms:,}ms は計画書の動きの表に無い{hint}")
    if re.search(r"transition:\s*all\b", tokens):
        r.fail(0, "動き", "tokens.css に transition: all がある")
    impl_texts = []
    for p in impl_paths:
        text = pathlib.Path(p).read_text(encoding="utf-8", errors="replace")
        if pathlib.Path(p).resolve() == pathlib.Path(tokens_path).resolve():
            continue
        impl_texts.append((p, text))
        for no, l in enumerate(text.split("\n"), 1):
            for h in HEX.findall(l):
                if h.upper() not in plan_hex:
                    r.fail(no, "生の値", f"{p}:{no} の {h} は計画書に無い色。トークン（var(--…)）で参照する")
            if re.search(r"transition:\s*all\b", l):
                r.fail(no, "動き", f"{p}:{no} に transition: all がある")
            for v in ms_values(l):
                if plan_ms and v not in plan_ms and v != 0:
                    r.fail(no, "動き", f"{p}:{no} の {v}ms は計画書の動きの表に無い")
    # 既存に合わせる型: トークンと実装の値が、既存の UI の値か、計画書の「足す値」の表にある
    if stype == EXISTING and not existing_paths:
        r.fail(0, "既存の値", "既存に合わせる型は --existing <既存の UI の置き場か棚卸しの表> を渡し、既存の値と突き合わせる")
    if existing_paths:
        known = existing_values(existing_paths) | added_values(ts)
        seen = set()
        for where, text in [(tokens_path, tokens)] + impl_texts:
            for no, kind, val in values_in(text):
                if val in known or (where, val) in seen:
                    continue
                seen.add((where, val))
                r.fail(no, "既存の値", f"{where}:{no} の{kind} {val} は既存の UI に無い。足すなら計画書の「足す値」の表に理由を書く")


# ---- 監修記録
def check_review(name, lines, ts, r):
    title = next((l[2:].strip() for _, l in lines if l.startswith("# ")), "")
    if not title.startswith("監修記録"):
        r.fail(1, "表題", "「# 監修記録: 件名」で始める")
    for key in ("忠実度", "AI らしさ", "WCAG", "キーボード", "動き", "指摘", "判定"):
        if section(lines, key) is None:
            r.fail(0, "必須の節", f"「## {key}」が無い")
    ts_i = section_tables(ts, "指摘")
    highs = 0
    if ts_i:
        t = ts_i[0]
        for want in ("場所", "計画の値", "実装の値", "直し方", "重さ"):
            if col(t, want) is None:
                r.fail(t["no"], "指摘", f"表に「{want}」の列が無い")
        kw = col(t, "重さ")
        for no, cells in t["rows"]:
            if any(not c for c in cells):
                r.fail(no, "指摘", "空の欄がある。5 つの欄を全部埋める")
            if kw is not None and cell(cells, kw).strip().startswith("高"):
                highs += 1
    elif section(lines, "指摘") is not None:
        r.fail(0, "指摘", "指摘の表（場所 | 計画の値 | 実装の値 | 直し方 | 重さ）が無い。無ければ 1 行「なし」")
    sec = section(lines, "判定")
    if sec is not None:
        body = "\n".join(l for _, l in sec)
        m = re.search(r"(条件つき受け入れ|受け入れ|差し戻し)", body)
        if not m:
            r.fail(sec[0][0], "判定", "判定は 受け入れ／条件つき受け入れ／差し戻し の 3 択で書く")
        elif highs and m.group(1) != "差し戻し":
            # references/review-method.md の 4 節: 重さ「高」の指摘が 1 つ以上なら差し戻し
            r.fail(sec[0][0], "判定", f"重さ「高」の指摘が {highs} 件あるのに、判定が「{m.group(1)}」。高が 1 つ以上なら差し戻しにする（references/review-method.md の 4 節）")
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
    if screen_type(lines, ts)[0] == IMMERSIVE:
        check_review_frames(lines, ts, r)
    holes(lines, r)


# 没入の型の監修で、フレームの所見の表に要る行（references/review-method.md の 6 節）
FRAME_ROWS = ((r"縮小版|減らす", "動きを減らす設定"), (r"短い版|2\s*回目", "2 回目以降"), (r"飛ばし", "飛ばしたとき"), (r"静止", "静止の画面"))


def check_review_frames(lines, ts, r):
    """没入の型の監修記録: フレームの一覧の行（置き場と撮った条件）と、フレームの所見の表（0ms から終わりまで、2 回目以降、
    動きを減らす設定、飛ばしたとき、静止の画面）。撮ったフレームを見ずに動きを受け入れた記録を通さない。"""
    no, v = next(((n, cell(cells, 1)) for t in ts for n, cells in t["rows"] if cells and "フレームの一覧" in cells[0]), (None, ""))
    if no is None or not v.strip():
        r.fail(no or 0, "フレームの一覧", "没入の型の監修記録は、対象の表に「フレームの一覧」の行（置き場と撮った条件）を書く")
    ft = section_tables(ts, "フレームの所見")
    if not ft:
        r.fail(0, "フレームの所見", "「## フレームの所見」の表（フレーム | 計画 | 見えたもの | 直し方 | 重さ）が無い。100ms ごとのフレームを見て書く")
        return
    t = ft[0]
    for want in ("フレーム", "計画", "見えたもの", "直し方", "重さ"):
        if col(t, want) is None:
            r.fail(t["no"], "フレームの所見", f"表に「{want}」の列が無い")
    for no, cells in t["rows"]:
        if len(cells) < len(t["header"]) or any(not c.strip() for c in cells):
            r.fail(no, "フレームの所見", "空の欄がある。直すことが無い行は、直し方と重さに「なし」と書く")
    heads = [cells[0] for _, cells in t["rows"] if cells]
    timed = [h for h in heads if re.match(r"^[\d,]+\s*ms", h)]
    if not any(re.match(r"^0\s*ms", h) for h in heads) or len(timed) < 2:
        r.fail(t["no"], "フレームの所見", f"押した時刻の 0ms から終わりまでの行が無い（時刻の行 {len(timed)} つ）。100ms ごとのフレームを 1 行ずつ書く")
    for rx, label in FRAME_ROWS:
        if not any(re.search(rx, h) for h in heads):
            r.fail(t["no"], "フレームの所見", f"{label}の行が無い。撮って見る（references/review-method.md の 6 節）")


# ---- 自己試験
EX_PLAN = SKILL / "examples" / "design-plan-order-list.md"
EX_TOKENS = SKILL / "examples" / "tokens-order-list.css"
EX_REVIEW = SKILL / "examples" / "design-review-order-list.md"
EX_DIVE = SKILL / "examples" / "design-plan-dive-log.md"
EX_MOTION = SKILL / "examples" / "motion-plan-dive-log.md"
EX_REVIEW_DIVE = SKILL / "examples" / "design-review-dive-log.md"
EX_EXISTING = SKILL / "examples" / "design-plan-pane-memo.md"
FIX = SKILL / "evals" / "fixtures"
# 既存に合わせる型の試験に使う、小さな既存の UI と計画書とトークン（架空）
EXISTING_CSS = (":root { --ink: #222222; --paper: #FAFAFA; --accent: #0A66C2; --line: #D0D7DE; }\n"
                ".btn { transition: opacity 120ms; padding: 8px 12px; font-family: 'Hiragino Sans', sans-serif; font-size: 14px; }\n")
EXISTING_PLAN = """# デザイン計画書: 既存に合わせる試験

| 項目 | 内容 |
|---|---|
| 画面の型 | 既存に合わせる型 |

## 色

| 名前 | 16 進 | 役割と使う場所 | 組み合わせと比 |
|---|---|---|---|
| 墨 | #222222 | 本文 | 紙で 15.24 対 1 |
| 紙 | #FAFAFA | 地 | 墨で 15.24 対 1 |
| 藍 | #0A66C2 | 主ボタン | 紙で 5.45 対 1 |
| 罫 | #D0D7DE | 罫線（装飾） | 紙で 1.39 対 1 |

## 動き

| 場面 | 時間と曲線 | 何を伝えるか | 動きを減らす設定のとき | キーボード起点のとき |
|---|---|---|---|---|
| ボタン | 120ms、標準 | 押せた | 0ms | 0ms |

### 足す値

| 値 | 種類 | 理由 |
|---|---|---|
| なし | － | 既存の値だけで足りる |
"""
EXISTING_TOKENS = (":root {\n  --ink: #222222;\n  --paper: #FAFAFA;\n  --accent: #0A66C2;\n  --line: #D0D7DE;\n"
                   "  --duration-1: 120ms;\n  --space-2: 8px;\n  --font-text: 'Hiragino Sans', sans-serif;\n}\n")


def run(kind, args):
    """検査を回す。読めないファイル（無い、ディレクトリ、UTF-8 でない）は traceback ではなく FAIL と RESULT の行で返す（終了コード 2）。"""
    try:
        return run_checked(kind, args)
    except (OSError, UnicodeDecodeError) as e:
        target = getattr(e, "filename", None) or (args[0] if args else "")
        why = {FileNotFoundError: "無い", IsADirectoryError: "ディレクトリ", UnicodeDecodeError: "UTF-8 でない"}.get(type(e), type(e).__name__)
        print(f"FAIL {target} [対象] 読めない（{why}）")
        print(f"RESULT: FAIL {NAMES[kind]} {target}")
        return 2


def take_option(args, flag):
    """args から「flag 値」の組を全部抜き、(値の一覧, 残りの args) を返す。値が無ければ None を返す。"""
    vals = []
    while flag in args:
        i = args.index(flag)
        if i + 1 >= len(args) or args[i + 1].startswith("--"):
            return None, args
        vals.append(args[i + 1])
        args = args[:i] + args[i + 2:]
    return vals, args


def run_checked(kind, args):
    if kind == "inventory":
        r = Report(NAMES[kind], " ".join(args))
        run_inventory(args, r)
        return 0 if r.show() else 1
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
        motion, args = take_option(args, "--motion")
        if motion is None:
            print("FAIL --motion [引数] --motion のあとに演出計画書のパスを渡す")
            return 2
        existing, args = take_option(args, "--existing")
        if existing is None:
            print("FAIL --existing [引数] --existing のあとに既存の UI の置き場か棚卸しの表（.md）を渡す")
            return 2
        if len(args) < 2:
            print("使い方: fidelity <計画書> <tokens.css> [<実装...>] [--motion <演出計画書>] [--existing <既存の UI か棚卸しの表>]")
            return 2
        r = Report(NAMES[kind], args[0])
        check_fidelity(args[0], args[1], args[2:], r, motion, existing)
        return 0 if r.show() else 1
    name = args[0]
    _, lines = load_lines(name)
    ts = tables(lines)
    r = Report(NAMES[kind], name)
    {"plan": check_plan, "contrast": check_contrast, "review": check_review, "motion": check_motion_plan}[kind](name, lines, ts, r)
    return 0 if r.show() else 1


def quiet(kind, args):
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = run(kind, args)
    return rc, buf.getvalue()


def fail_lines(out):
    return [l for l in out.splitlines() if l.startswith("FAIL ")]


def variants(kind, base, cases):
    """完成例を 1 か所だけ変えた写しを回し、(落ちたか, 出力) を案ごとに返す。cases は (名前, 正規表現, 置き換え, 期待する文言)。"""
    out = []
    with tempfile.TemporaryDirectory() as tmp:
        for label, pattern, repl, want in cases:
            body, n = re.subn(pattern, repl, base, count=1, flags=re.M)
            p = pathlib.Path(tmp) / "variant.md"
            p.write_text(body, encoding="utf-8")
            rc, got = quiet(kind, [str(p)])
            out.append((n == 1 and rc == 1 and want in got, f"{label}: 置き換え {n} か所、出力 {got[-240:]}"))
    return out


def selftest(kind):
    ok = True
    name = NAMES[kind]
    checks = []
    if kind == "contrast":
        checks.append((abs(ratio("#999999", "#FFFFFF") - 2.85) < 0.01, "#999999 対 #FFFFFF が 2.85 にならない"))
        checks.append((abs(ratio("#767676", "#FFFFFF") - 4.54) < 0.01, "#767676 対 #FFFFFF が 4.54 にならない"))
        rc, _ = quiet("contrast", [str(EX_PLAN)])
        checks.append((rc == 0, "完成例の色の表が落ちた"))
        rc, out = quiet("contrast", [str(EX_DIVE)])
        checks.append((rc == 0, f"没入の型の完成例の色の表が落ちた: {out[-300:]}"))
        rc, out = quiet("contrast", [str(FIX / "bad-plan.md")])
        checks.append((rc == 1 and "[閾値]" in out, "低コントラストの見本が通った"))
    elif kind == "plan":
        rc, out = quiet("plan", [str(EX_PLAN)])
        checks.append((rc == 0, f"完成例が落ちた: {out[-300:]}"))
        rc, out = quiet("plan", [str(FIX / "bad-plan.md")])
        for rule in ("色", "書体", "シグネチャ", "動き", "既定との差", "画面の型"):
            checks.append((f"[{rule}]" in out, f"負例で「{rule}」が出ない"))
        rc, out = quiet("plan", [str(SKILL / "templates" / "design-plan.md")])
        checks.append(("[雛形の穴]" in out, "雛形（穴埋めのまま）が通った"))
        rc, out = quiet("plan", [str(EX_DIVE)])
        checks.append((rc == 0, f"没入の型の完成例が落ちた: {out[-300:]}"))
        rc, out = quiet("plan", [str(FIX / "current-type-600ms.md")])
        checks.append((rc == 1 and "600ms は 300ms 超" in out and len(fail_lines(out)) == 1,
                       f"今の型の 600ms が、それだけで落ちない: {out[-300:]}"))
        checks += variants("plan", EX_DIVE.read_text(encoding="utf-8"), [
            ("今の型にすると見せ場の 1,400ms が落ちる", r"^(\| 画面の型 \| )没入の型", r"\1今の型", "1,400ms は 300ms 超"),
            ("既存に合わせる型でも 300ms の線のまま", r"^(\| 画面の型 \| )没入の型", r"\1既存に合わせる型", "300ms 超"),
            ("画面の型の行が無いと落ちる", r"^\| 画面の型 \|.*\n", "", "[画面の型]"),
            ("3 つ以外の型は落ちる", r"^(\| 画面の型 \| )没入の型", r"\1ゲームの型", "[画面の型]"),
            ("没入の型でも移動の 600ms は落ちる", r"^(\| 移動 \|.*?)400ms", r"\g<1>600ms", "移動は 500ms まで"),
            ("見せ場の 2 回目が 600ms を超えると落ちる", r"^(\| 見せ場 \|.*?)2 回目から 600ms", r"\g<1>2 回目から 800ms", "2 回目以降が 800ms"),
            ("環境の周期が 4 秒未満だと落ちる", r"^(\| 環境 \|.*?)周期 4\.2 秒", r"\g<1>周期 2 秒", "4 秒未満"),
            ("世界観の設定が 10 行に足りないと落ちる", r"^\| 取らない方向 \|.*\n", "", "[世界観の設定]"),
            ("方向が 2 案だと落ちる", r"^\| C \|.*\n", "", "[方向の 3 案]"),
            ("動きの語彙が技法の名前だけだと落ちる", r"^(\| 動きの語彙 \| ).*\|$", r"\1フェード、スライド、ズーム |", "技法の名前だけ"),
            # 秒で書いても ms に直して枠で見る
            ("見せ場を秒で書いても枠で落ちる", r"^(\| 見せ場 \|.*?)初回 1,400ms", r"\g<1>初回 4 秒", "見せ場は 1,400ms まで"),
            ("移動を秒で書いても枠で落ちる", r"^(\| 移動 \|.*?)400ms", r"\g<1>2.5 秒", "移動は 500ms まで"),
            ("2 回目を秒で書いても読む", r"^(\| 見せ場 \|.*?)2 回目から 600ms", r"\g<1>2 回目から 0.8 秒", "2 回目以降が 800ms"),
            # 環境の動きの止める手段を打ち消すと落ちる
            ("環境を止められないと書くと落ちる", r"^(\| 環境 \|.*\| )隅の「動きを止める」で止める \|$", r"\1止められない |", "環境の動きに止める手段が無い"),
            # 既存に合わせる型は、足す値の表が要る
            ("既存に合わせる型は足す値の表が要る", r"^(\| 画面の型 \| )没入の型", r"\1既存に合わせる型", "[足す値]"),
        ])
        # 既存に合わせる型: 色の数と既定との差を求めず、棚卸しの表との突き合わせを求める
        rc, out = quiet("plan", [str(EX_EXISTING)])
        checks.append((rc == 0, f"既存に合わせる型の完成例が落ちた: {out[-300:]}"))
        ex_text = EX_EXISTING.read_text(encoding="utf-8")
        checks += variants("plan", ex_text, [
            ("既存に無い色を名前つきの表に書くと落ちる", r"^(\| 藍 \| )#2F5C9E", r"\1#2F5C9F", "色 #2F5C9F（藍）は既存の UI に無い"),
            ("既存に無い時間を動きの表に書くと落ちる", r"^(\| メモ欄のホバーで枠が濃くなる \| )80ms", r"\g<1>90ms", "時間 90ms"),
            ("既存に無い書体を書くと落ちる", r"^(\| 本文 \| )BIZ UDPGothic（既存の --font-text）", r"\1Inter", "書体の行「本文」の書体が既存の UI の書体"),
            ("既存に無い字の大きさを書くと落ちる", r"^(\| 補助 \|.*?)12px", r"\g<1>13px", "大きさ 13px"),
            ("棚卸しの表が無いと落ちる", r"^\| 種類 \| 値 \| 出現数 \| 最初の場所 \|\n(?:\|.*\n)+", "", "棚卸しの表（種類 | 値 | 出現数 | 最初の場所）が無い"),
            ("棚卸しの出どころが無いと落ちる", r"`bash skills/designer/scripts/fidelity-check.sh --inventory samples/app`", "手で数えた表", "棚卸しの出どころ"),
            ("既存の値の節が無いと落ちる", r"(?s)^## 既存の値.*?(?=^## 色)", "", "「## 既存の値」が無い"),
            ("今の型にすると既定との差が要る", r"^(\| 画面の型 \| )既存に合わせる型", r"\1今の型", "「## 既定との差」が無い"),
        ])
        # 足す値の表に理由を書けば、既存に無い値も通る
        added = re.sub(r"^(\| メモ欄のホバーで枠が濃くなる \| )80ms", r"\g<1>90ms", ex_text, count=1, flags=re.M)
        added = added.replace("| なし | － | 既存の値だけで足りる。メモ欄は既存の検索欄と同じ枠・字・焦点の枠で描く |",
                              "| 90ms | 時間 | 試験のために足した値。既存の 80ms では短すぎると仮に決めた |", 1)
        with tempfile.TemporaryDirectory() as tmp:
            p3 = pathlib.Path(tmp) / "existing.md"
            p3.write_text(added, encoding="utf-8")
            rc, out = quiet("plan", [str(p3)])
            checks.append((rc == 0, f"足す値の表に理由を書いた 90ms が落ちた: {out[-300:]}"))
        with tempfile.TemporaryDirectory() as tmp:
            p2 = pathlib.Path(tmp) / "plan.md"
            p2.write_text((FIX / "current-type-600ms.md").read_text(encoding="utf-8").replace("| 伝票を開く | 600ms、", "| 伝票を開く | 1 秒、", 1), encoding="utf-8")
            rc, out = quiet("plan", [str(p2)])
            checks.append((rc == 1 and "1,000ms は 300ms 超" in out, f"今の型で 1 秒と書いた動きが通った: {out[-300:]}"))
    elif kind == "motion":
        rc, out = quiet("motion", [str(EX_MOTION)])
        checks.append((rc == 0, f"完成例が落ちた: {out[-300:]}"))
        rc, out = quiet("motion", [str(SKILL / "templates" / "motion-plan.md")])
        checks.append(("[雛形の穴]" in out, "雛形（穴埋めのまま）が通った"))
        rc, out = quiet("motion", [str(FIX / "just-slide.md")])
        for rule in ("段が 3 つ", "レイヤーが 3 つ以上", "共有要素が 1 つ", "動きが重なる", "守りが 5 行", "点滅", "5 秒を超える動き", "音"):
            checks.append((rc == 1 and f"[{rule}]" in out, f"ただのスライドで「{rule}」が出ない"))
        checks += variants("motion", EX_MOTION.read_text(encoding="utf-8"), [
            ("点滅が 1 秒に 5 回だと落ちる", r"^(\| 点滅 \| ).*\|$", r"\1白と黒を 1 秒に 5 回切り替える |", "[点滅]"),
            ("点滅の行が無いと落ちる", r"^\| 点滅 \|.*\n", "", "[点滅]"),
            ("トークンに無い長さは落ちる", r"^(\| 120ms \|.*?)880ms", r"\g<1>900ms", "[トークンの外の長さ]"),
            ("2 回目以降が 600ms を超えると落ちる", r"^(\| 2 回目以降 \|.*?)600ms", r"\g<1>700ms", "[2 回目以降]"),
            ("消音の無い音は落ちる", r"^(\| 音 \| ).*\|$", r"\1スタートを押すと 2 秒の音を鳴らす |", "[音]"),
            ("止める手段の無い 5 秒超えは落ちる", r"^(\| 5 秒を超える動き \| ).*\|$", r"\1マリンスノーは流れ続ける |", "[5 秒を超える動き]"),
            ("共有要素の行が無いと落ちる", r"^\| 共有要素 \|.*\n", "", "[共有要素が 1 つ]"),
            ("今の型の演出計画書は落ちる", r"^(\| 画面の型 \| )没入の型", r"\1今の型", "[画面の型]"),
            ("初回が 1,400ms を超えると落ちる", r"^(\| 長さ \| )初回 1,400ms", r"\1初回 1,600ms", "[長さ]"),
            ("動きを減らす設定の行が無いと落ちる", r"^\| 動きを減らす設定 \|.*\n", "", "[守りが 5 行]"),
            # 守りの値が「なし」だけ・打ち消し・中身の印が無いのは落ちる
            ("動きを減らす設定が「なし」だと落ちる", r"^(\| 動きを減らす設定 \| ).*\|$", r"\1なし |", "「動きを減らす設定」: 「なし」だけ"),
            ("飛ばす手段が「なし」だと落ちる", r"^(\| 飛ばす手段 \| ).*\|$", r"\1なし |", "「飛ばす手段」: 「なし」だけ"),
            ("アセットが間に合わないときが「なし」だと落ちる", r"^(\| アセットが間に合わないとき \| ).*\|$", r"\1なし |", "「アセットが間に合わない」: 「なし」だけ"),
            ("終わりのフォーカスが「なし」だと落ちる", r"^(\| 終わりのフォーカス \| ).*\|$", r"\1なし |", "「終わりのフォーカス」: 「なし」だけ"),
            ("飛ばせないと書くと落ちる", r"^(\| 飛ばす手段 \| ).*\|$", r"\1見せ場の途中では飛ばせない |", "「飛ばす手段」: 飛ばす手段を打ち消している"),
            ("終わりのフォーカスに要素が無いと落ちる", r"^(\| 終わりのフォーカス \| ).*\|$", r"\1演出が終わったら決める |", "「終わりのフォーカス」: フォーカスを入れる要素の名前"),
            ("止める操作を置かないと書くと落ちる", r"^(\| 5 秒を超える動き \| ).*\|$", r"\1止める操作は置かない |", "[5 秒を超える動き]"),
            ("消音の操作を置かないと書くと落ちる", r"^(\| 音 \| ).*\|$", r"\1消音の操作は置かない |", "[音]"),
            ("点滅の回数は全部読み、最大で判定する", r"^(\| 点滅 \| ).*\|$", r"\g<1>0 回と書いたが、題字は白と黒を毎秒 6 回切り替える |", "切り替わりが 6 回"),
            # 同じスライドを 3 行にずらしただけでは、レイヤーの条件で落ちる
            ("同じ動きをずらしただけでは落ちる", r"^(\| 時刻 \| 段 \|.*\n\|---.*\n)(?:\|.*\n)+",
             r"\1| 0ms | 入り | 灯・水・題字 | 右から 24px 滑る | 120ms、標準 | 動いた |\n| 50ms | 見せ場 | 灯・水・題字 | 右から 24px 滑る | 120ms、標準 | 動いた |\n| 100ms | 収まり | 灯・水・題字 | 右から 24px 滑る | 120ms、標準 | 動いた |\n",
             "[レイヤーが 3 つ以上]"),
            # 共有要素は 2 つの段にまたがる
            ("共有要素が 1 つの段の中だけだと落ちる", r"^\| 200ms \| 見せ場 \| 灯 \|", "| 200ms | 入り | 灯 |", "の中でしか動かない"),
        ])
    elif kind == "ailook":
        rc, out = quiet("ailook", [str(FIX / "ai-slop")])
        checks.append((rc == 1 and ("sloppy" in out or "terminal" in out), f"AI らしい見本が落ちない: {out[-200:]}"))
        rc, out = quiet("ailook", [str(FIX / "clean")])
        checks.append((rc == 0 and "clean" in out, f"計画どおりの見本が通らない: {out[-200:]}"))
        rc, out = quiet("ailook", [str(FIX / "ai-slop-excused"), "--plan", str(FIX / "plan-with-reasons.md")])
        checks.append((rc == 0, f"理由のある既定が件数から外れない: {out[-200:]}"))
        rc, out = quiet("ailook", [str(FIX / "ai-slop-immersive")])
        checks.append((rc == 1 and all(f"[{k}]" in out for k in ("ネオンの光", "粒子", "一律の浮き上がり")),
                       f"没入の既定の例が 3 項目で落ちない: {out[-300:]}"))
        rc, out = quiet("ailook", [str(FIX / "ai-slop-immersive"), "--plan", str(EX_DIVE)])
        checks.append((rc == 1 and "[粒子]" not in out and "[ネオンの光]" in out,
                       f"世界観の設定に役目のある粒子だけが外れる、にならない: {out[-300:]}"))
        # 「取る危険」に危険として書いた既定は、件数から外さない
        with tempfile.TemporaryDirectory() as tmp:
            p2 = pathlib.Path(tmp) / "plan.md"
            body, n = re.subn(r"^(\| 取る危険 1 つ \| ).*\|$", r"\1ネオンの光に寄りすぎて、よくある AI の画面に見える危険 |", EX_DIVE.read_text(encoding="utf-8"), count=1, flags=re.M)
            p2.write_text(body, encoding="utf-8")
            rc, out = quiet("ailook", [str(FIX / "ai-slop-immersive"), "--plan", str(p2)])
            checks.append((n == 1 and rc == 1 and "[ネオンの光]" in out, f"取る危険に書いた既定が件数から外れた: {out[-300:]}"))
    elif kind == "fidelity":
        rc, out = quiet("fidelity", [str(EX_PLAN), str(EX_TOKENS), str(FIX / "clean" / "orders.css")])
        checks.append((rc == 0, f"完成例と正しい実装が落ちた: {out[-300:]}"))
        rc, out = quiet("fidelity", [str(EX_PLAN), str(FIX / "tokens-drift.css")])
        checks.append((rc == 1 and "#F4F1EA" in out, f"ずれた tokens が通った: {out[-200:]}"))
        dive_tokens = FIX / "tokens-dive-log.css"
        rc, out = quiet("fidelity", [str(EX_DIVE), str(dive_tokens), "--motion", str(EX_MOTION)])
        checks.append((rc == 0, f"没入の型の計画とトークンが落ちた: {out[-300:]}"))
        rc, out = quiet("fidelity", [str(EX_PLAN), str(dive_tokens)])
        checks.append((rc == 1 and "1,400ms は 300ms 超" in out, f"今の型の計画で見せ場のトークンが通った: {out[-200:]}"))
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp) / "tokens.css"
            p.write_text(dive_tokens.read_text(encoding="utf-8").replace("--dive-water: 880ms", "--dive-water: 900ms"), encoding="utf-8")
            rc, out = quiet("fidelity", [str(EX_DIVE), str(p), "--motion", str(EX_MOTION)])
            checks.append((rc == 1 and "--dive-water" in out, f"演出計画書と違うトークンが通った: {out[-200:]}"))
            # 時間のトークンは名前によらず見る: 今の型の計画書に --motion-* と --dive-* の長いトークンを当てる
            p.write_text(EX_TOKENS.read_text(encoding="utf-8").replace("--duration-3: 180ms;", "--duration-3: 180ms;\n  --motion-sheet: 900ms;\n  --dive-water: 1400ms;\n  --fade-x: 0.9s;", 1), encoding="utf-8")
            rc, out = quiet("fidelity", [str(EX_PLAN), str(p), str(FIX / "clean" / "orders.css")])
            checks.append((rc == 1 and all(x in out for x in ("--motion-sheet: 900ms は 300ms 超", "--dive-water: 1,400ms は 300ms 超", "--fade-x: 900ms は 300ms 超")),
                           f"名前の違う長い時間のトークンが通った: {out[-300:]}"))
            # 没入の型でも、演出計画書にも計画書にも無い長さのトークンは落ちる
            p.write_text(dive_tokens.read_text(encoding="utf-8").replace("--stagger: 60ms;", "--stagger: 60ms;\n  --dive-glow: 9000ms;", 1), encoding="utf-8")
            rc, out = quiet("fidelity", [str(EX_DIVE), str(p), "--motion", str(EX_MOTION)])
            checks.append((rc == 1 and "--dive-glow: 9,000ms" in out, f"計画に無い 9,000ms のトークンが通った: {out[-300:]}"))
            # 既存に合わせる型: 既存の UI の値と突き合わせる
            ex = pathlib.Path(tmp) / "existing"
            ex.mkdir()
            (ex / "app.css").write_text(EXISTING_CSS, encoding="utf-8")
            plan = pathlib.Path(tmp) / "plan.md"
            plan.write_text(EXISTING_PLAN, encoding="utf-8")
            tok = pathlib.Path(tmp) / "tokens-existing.css"
            tok.write_text(EXISTING_TOKENS, encoding="utf-8")
            rc, out = quiet("fidelity", [str(plan), str(tok), "--existing", str(ex)])
            checks.append((rc == 0, f"既存の値だけのトークンが落ちた: {out[-300:]}"))
            rc, out = quiet("fidelity", [str(plan), str(tok)])
            checks.append((rc == 1 and "[既存の値]" in out and "--existing" in out, f"既存に合わせる型で --existing が無いのに通った: {out[-300:]}"))
            tok.write_text(EXISTING_TOKENS.replace("--space-2: 8px;", "--space-2: 8px;\n  --space-5: 20px;"), encoding="utf-8")
            rc, out = quiet("fidelity", [str(plan), str(tok), "--existing", str(ex)])
            checks.append((rc == 1 and "20px は既存の UI に無い" in out, f"既存に無い 20px が通った: {out[-300:]}"))
            plan.write_text(EXISTING_PLAN.replace("| なし | － | 既存の値だけで足りる |", "| 20px | 大きさ | 表の行の高さに使う。既存の 8px と 12px では詰まる |"), encoding="utf-8")
            rc, out = quiet("fidelity", [str(plan), str(tok), "--existing", str(ex)])
            checks.append((rc == 0, f"足す値の表に理由のある 20px が落ちた: {out[-300:]}"))
            rc, out = quiet("inventory", [str(ex)])
            inv = pathlib.Path(tmp) / "inventory.md"
            inv.write_text(out, encoding="utf-8")
            checks.append((rc == 0 and all(x in out for x in ("| 色 | #222222 |", "| 時間 | 120ms |", "| 大きさ | 8px |", "| 書体 | hiragino sans |")),
                           f"棚卸しの表に既存の値が出ない: {out[-300:]}"))
            rc, out = quiet("fidelity", [str(plan), str(tok), "--existing", str(inv)])
            checks.append((rc == 0, f"棚卸しの表（.md）を --existing に渡すと落ちた: {out[-300:]}"))
    elif kind == "inventory":
        with tempfile.TemporaryDirectory() as tmp:
            (pathlib.Path(tmp) / "app.css").write_text(EXISTING_CSS + "/* 注釈の 999ms と #ABCDEF は数えない */\n", encoding="utf-8")
            rc, out = quiet("inventory", [tmp])
            checks.append((rc == 0 and "| 色 | #0A66C2 |" in out and "999ms" not in out and "#ABCDEF" not in out, f"棚卸しの表が違う: {out[-300:]}"))
            rc, out = quiet("inventory", [str(pathlib.Path(tmp) / "none")])
            checks.append((rc == 1 and "[対象]" in out, "走査できるファイルの無い棚卸しが通った"))
    elif kind == "review":
        rc, out = quiet("review", [str(EX_REVIEW)])
        checks.append((rc == 0, f"完成例が落ちた: {out[-300:]}"))
        rc, out = quiet("review", [str(FIX / "bad-review.md")])
        for rule in ("指摘", "判定"):
            checks.append((f"[{rule}]" in out, f"負例で「{rule}」が出ない"))
        rc, out = quiet("review", [str(EX_REVIEW_DIVE)])
        checks.append((rc == 0, f"没入の型の監修記録の完成例が落ちた: {out[-300:]}"))
        checks += variants("review", EX_REVIEW_DIVE.read_text(encoding="utf-8"), [
            ("没入の型でフレームの所見の節が無いと落ちる", r"(?s)^## フレームの所見.*?(?=^## 指摘)", "", "[フレームの所見]"),
            ("没入の型でフレームの一覧の行が無いと落ちる", r"^\| フレームの一覧 \|.*\n", "", "[フレームの一覧]"),
            ("没入の型で静止の画面の行が無いと落ちる", r"^\| 静止の画面 \|.*\n", "", "静止の画面の行が無い"),
            ("没入の型で飛ばしたときの行が無いと落ちる", r"^\| 飛ばしたとき \|.*\n", "", "飛ばしたときの行が無い"),
            ("没入の型でフレームの所見に空の欄があると落ちる", r"^(\| 200ms \|.*\| )なし \| なし \|$", r"\1 | なし |", "[フレームの所見] 空の欄"),
            ("重さ「高」の指摘があるのに条件つき受け入れだと落ちる", r"^判定は差し戻しです。", "判定は条件つき受け入れです。確認は別の監修者が行います。", "高が 1 つ以上なら差し戻し"),
        ])
        checks += variants("review", EX_REVIEW.read_text(encoding="utf-8"), [
            ("今の型の監修記録でも、高の指摘があるのに受け入れだと落ちる", r"^判定は差し戻しです。", "判定は受け入れです。", "高が 1 つ以上なら差し戻し"),
        ])
    if kind in ("plan", "motion", "review"):
        # 読めないファイルは traceback ではなく、FAIL と RESULT の行で返す
        with tempfile.TemporaryDirectory() as tmp:
            bad = pathlib.Path(tmp) / "bad.md"
            bad.write_bytes(b"\xff\xfe# \x80\n")
            for label, target in (("無いファイル", str(pathlib.Path(tmp) / "none.md")), ("ディレクトリ", tmp), ("UTF-8 でないファイル", str(bad))):
                rc, out = quiet(kind, [target])
                checks.append((rc == 2 and f"RESULT: FAIL {name} " in out and "[対象] 読めない" in out, f"{label}で FAIL と RESULT の行が出ない: {out[-200:]}"))
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
