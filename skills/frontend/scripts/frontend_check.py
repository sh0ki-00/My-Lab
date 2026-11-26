#!/usr/bin/env python3
"""frontend_check — フロントエンドの成果物と実装の検査。

使い方: frontend_check.py plan <実装計画>            計画の 14 節と表（構成の動く場所、状態の置き場、取得の上限、予算の数字と測定条件、テストの 1 対 1、横断事項）
        frontend_check.py self <自己点検票>           結果の数字、判定（充足／未確認）、ゲートの出力、未確認の節、推測の語
        frontend_check.py motion <ディレクトリかファイル...>   動きの縮小版（prefers-reduced-motion）、transition: all、
                                                       JavaScript の動き、音の消音、自動再生、回り続ける動きの止める手段、長い動きの飛ばす手段
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
# motion-lint だけが読む JavaScript。ビルドの出力と、ほかから持ってきたコードは読まない
PLAIN_SCRIPT_EXT = (".js", ".mjs", ".cjs", ".ts")
MOTION_EXT = CODE_EXT + PLAIN_SCRIPT_EXT
BUILT = {"node_modules", "dist", "build", ".next", "out", "vendor", "coverage"}
GUESS =["動くはず", "通るはず", "速いはず", "と思われ", "おそらく", "たぶん", "ほぼ同じ"]


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


# ---- 画面の型（受付票から写した行）。見出しは「画面の型」を含めばよく、** とバッククォートは外して読む
SCREEN_TYPE_RX = re.compile(r"^\s*(没入(?:の型)?|既存に合わせる(?:型)?|今の型)")


def screen_type_row(ts):
    """(行番号, 値) を返す。行が無ければ (None, "")。"""
    clean = lambda c: c.replace("*", "").replace("`", "").strip()  # noqa: E731
    for t in ts:
        for no, cells in t["rows"]:
            if cells and "画面の型" in clean(cells[0]):
                return no, clean(cells[1]) if len(cells) > 1 else ""
    return None, ""


def check_screen_type(ts, r):
    """画面の型の行を見て、没入かを返す。行が無ければ FAIL（gate の演出の段も、この行が読めないと落ちる）。"""
    no, v = screen_type_row(ts)
    if no is None:
        r.fail(0, "画面の型", "文書情報の表に「画面の型」の行が無い。受付票の型（没入の型・既存に合わせる型・今の型）を写す（gate の --plan はこの行で演出の段を決める）")
        return False
    if not SCREEN_TYPE_RX.match(v):
        r.fail(no, "画面の型", f"「{v[:20]}」。没入の型・既存に合わせる型・今の型のどれかで始める")
        return False
    return v.lstrip().startswith("没入")


# ---- 実装計画
SECTIONS = ["背景と目的", "全体像", "構成", "状態", "データ取得", "エラー", "性能予算", "テスト", "アクセシビリティ", "忠実度", "横断事項", "実装の進め方", "やらないこと", "未確定"]


def check_plan(name, lines, ts, r):
    title = next((l[2:].strip() for _, l in lines if l.startswith("# ")), "")
    if not title.startswith("実装計画"):
        r.fail(1, "表題", "「# 実装計画: 件名」で始める")
    for key in SECTIONS:
        if section(lines, key) is None:
            r.fail(0, "必須の節", f"「## {key}」が無い")
    if check_screen_type(ts, r):
        check_plan_immersive(lines, ts, r)
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


def check_plan_immersive(lines, ts, r):
    """没入の型の実装計画: 「演出の実装」の節（演出 ID、受け取る演出計画書、計測の設定）と、性能予算の演出の行。"""
    t = next(iter(section_tables(ts, "演出の実装")), None)
    if t is None:
        r.fail(0, "演出の実装", "没入の型は「## 演出の実装」の表（演出 ID | 受け取る演出計画書 | 台帳 | レイヤーと手段 | 計測の設定）を書く")
    else:
        pos = need_cols(r, t, ["演出 ID", "演出計画書", "計測の設定"], "演出の実装")
        if not t["rows"]:
            r.fail(t["no"], "演出の実装", "演出の行が無い。見せ場ごとに 1 行書く")
        for no, cells in t["rows"]:
            for k, v in pos.items():
                if not cell(cells, v).strip():
                    r.fail(no, "演出の実装", f"「{k}」が空")
    budget = next(iter(section_tables(ts, "性能予算")), None)
    if budget is not None and not any(cells and "演出" in cells[0] for _, cells in budget["rows"]):
        r.fail(budget["no"], "性能予算", "没入の型は、性能予算の表に演出の行（最初のフレーム 100ms、50ms 超のフレーム 0 個、演出のアセット 600KB と、測る条件）を書く")


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
    immersive = check_screen_type(ts, r) or any(cells and "演出の記録" in cells[0] for t2 in ts for _, cells in t2["rows"])
    if immersive:
        check_self_immersive(lines, blocks, ts, t, r)
    for no, l in lines:
        for w in GUESS:
            if w in l:
                r.fail(no, "推測", f"「{w}」。測った事実だけを書く")
                break
    holes(lines, r)


def check_self_immersive(lines, blocks, ts, t, r):
    """没入の型の自己点検票: 演出の 12 項目の行（motion-measure の 1〜12）に数字があり、「演出の計測」の節に
    motion-measure の出力（RESULT の行）を貼り、演出の記録とフレームの一覧の置き場がある。"""
    if t is not None:
        kc = col(t, "確かめたこと")
        hit = {int(m.group(1)) for _, cells in t["rows"] for m in [re.search(r"motion-measure の\s*(\d+)", cell(cells, kc) if kc is not None else " ".join(cells))] if m}
        miss = [n for n in range(1, 13) if n not in hit]
        if miss:
            r.fail(t["no"], "演出の 12 項目", f"motion-measure の {'・'.join(map(str, miss))} の行が無い。没入の型は 18〜29 の行に 12 項目の数字を写す")
    sec = section(lines, "演出の計測")
    if sec is None:
        r.fail(0, "演出の計測", "没入の型は「## 演出の計測」の節に motion-measure の出力をそのまま貼る")
    elif not any(any(re.search(r"RESULT: (PASS|FAIL) motion-measure ", l) for l in b) for b in blocks):
        r.fail(sec[0][0], "演出の計測", "motion-measure の出力（RESULT: … motion-measure の行）をコードブロックで貼る")
    for key in ("演出の記録", "フレームの一覧"):
        row = next(((no, cell(cells, 1)) for t2 in ts for no, cells in t2["rows"] if cells and key in cells[0]), (None, ""))
        if row[0] is None or not row[1].strip():
            r.fail(row[0] or 0, key, f"没入の型は文書情報の表に「{key}」の行（置き場）を書く")


# ---- 実装の走査
def scan_files(paths, exts=CODE_EXT):
    files = []
    for p in paths:
        p = pathlib.Path(p)
        if p.is_dir():
            for f in sorted(p.rglob("*")):
                if not f.is_file() or f.suffix.lower() not in exts or "node_modules" in f.parts:
                    continue
                rel = f.relative_to(p).parts[:-1]
                if f.suffix.lower() in PLAIN_SCRIPT_EXT and (BUILT & set(rel) or f.name.endswith((".min.js", ".d.ts"))):
                    continue
                if exts is MOTION_EXT and f.suffix.lower() in PLAIN_SCRIPT_EXT + (".jsx", ".tsx") and (TEST_DIRS & set(rel) or re.search(r"\.(test|spec)\.", f.name)):
                    continue
                files.append(f)
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


TIME = re.compile(r"(?<![\w.-])\d*\.?\d+\s*m?s\b")
REDUCE_MQ = re.compile(r"prefers-reduced-motion\s*:\s*reduce")
NOPREF_MQ = re.compile(r"prefers-reduced-motion\s*:\s*no-preference")
MOTION_DECL = re.compile(r"^(transition|animation)(-duration)?$")
# 縮小版の分岐が「動きを上書きした」と見る宣言の名前
MOTION_TOUCH = re.compile(r"^(transition|animation|transform|translate|scale|rotate|view-transition-name)")
VAR = re.compile(r"var\(\s*(--[\w-]+)")
# JavaScript の動き。同じモジュールに縮小版の分岐（REDUCED_REF）が要る
JS_MOTION = [
    (re.compile(r"\.animate\s*\("), "element.animate"),
    (re.compile(r"\bnew\s+(?:KeyframeEffect|Animation)\s*\("), "Web Animations"),
    (re.compile(r"\bstartViewTransition\s*\("), "View Transitions"),
    (re.compile(r"\.style\.(?:transition|animation)\w*\s*="), "style に書いた動き"),
    (re.compile(r"\btransition=\{\{[^}]*\bduration\b"), "JSX の transition"),
    (re.compile(r"\banimate=\{\{"), "JSX の animate"),
    (re.compile(r"<motion\.[A-Za-z]"), "motion の部品"),
    (re.compile(r"\btransition\s*:\s*\{[^}]*\bduration\b"), "動きの設定の duration"),
    (re.compile(r"\bgsap\.(?:to|from|fromTo|timeline)\s*\("), "GSAP"),
]
RAF = re.compile(r"\brequestAnimationFrame\s*\(")
RAF_STYLE = re.compile(r"\.style\b|\bsetProperty\s*\(")
RAF_CANVAS = re.compile(r"\bgetContext\s*\(")
# canvas のエンジンは、止める関数（cancelAnimationFrame）を同じモジュールに持てば、縮小版の判断を呼ぶ側に任せてよい。
# 縮小版で本当に止まるかは、計測（motion-measure の項目 6 の、終わったあとの静止）が確かめる
ENGINE_STOP = re.compile(r"cancelAnimationFrame\s*\(")
# 試験のコード（音や動きの API を真似る）は、アプリのコードではないので読まない
TEST_DIRS = {"tests", "test", "__tests__", "e2e", "spec"}
REDUCED_REF = re.compile(r"prefers-reduced-motion|[Rr]educedMotion")
CSS_IN_JS = re.compile(r"\b(transition|animation)(?:-duration)?\s*:\s*(['\"`]?)([^;'\"`{}\n]+)")
# duration の式（三項演算子の両方の数を含む）か、animate(…, 数) の 2 つ目の引数
JS_DURATION = re.compile(r"\bduration\s*[:=]\s*([^,;{}\n]+)|\.animate\s*\([^()]*?,\s*(\d+)\s*\)")
LONG_MS = 500  # これを超える JavaScript の動きには、飛ばす手段が要る（見せ場の動き）
# 飛ばす手段。Service Worker の skipWaiting() など、動きと関係の無い名前は数えない
SKIP = re.compile(r"skipTransition\s*\(|\.finish\s*\(|\b(?!skipWaiting\b)\w*[Ss]kip\w*\s*\(")
SOUND = [(re.compile(r"\bnew\s+Audio\s*\("), "new Audio"), (re.compile(r"\b(?:webkit)?AudioContext\b"), "AudioContext")]
MEDIA_PLAY = re.compile(r"\.play\s*\(")
MEDIA_WORD = re.compile(r"\b(?:[Aa]udio|[Vv]ideo|HTMLMediaElement)\b")
# 消音の手段の名前。CSS のトークン（--muted）は数えない。html は script の中だけで探すので、要素の muted 属性も数えない
MUTE = re.compile(r"(?<![-\w])[Mm]ut(?:e|ed|ing)\b|(?<![-\w])[Mm]ute[A-Z_]|[a-z]Mut(?:e|ed|ing)\b")
# CSS の回り続ける動きを、ほかのファイルの JavaScript から止める手段（play state か、getAnimations で拾って止める）
CSS_STOP_JS = re.compile(r"animationPlayState|getAnimations\s*\([^)]*\)[\s\S]{0,200}?\.(?:pause|cancel)\s*\(")
MEDIA_TAG = re.compile(r"<(video|audio)\b([^>]*)>", re.I)
INFINITE_JS = re.compile(r"\biterations\s*:\s*Infinity\b")
STOP = [
    re.compile(r"animation-play-state\s*:\s*paused"),
    re.compile(r"animationPlayState"),
    re.compile(r"\.pause\s*\("),
    re.compile(r"\.cancel\s*\("),
    re.compile(r"cancelAnimationFrame\s*\("),
    re.compile(r"<video\b[^>]*\bcontrols\b", re.I),
]


def split_top(s):
    """カンマで分ける。括弧の中のカンマ（cubic-bezier(0.2, 0, 0, 1) など）では分けない。"""
    out, depth, cur = [], 0, []
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur))
    return out


def css_decls(text, base=1):
    """css を宣言の列にする。要素は (行, 名前, 値, セレクタの組, media の条件の組)。@keyframes の中は除く。
    ルールの外の宣言（style 属性の中身）は、セレクタを空の組にする。入れ子のルールは内側のセレクタで見る。"""
    out, stack, buf, at = [], [], [], None
    line = base

    def flush():
        s = "".join(buf).strip()
        if not s or ":" not in s or any(k == "keyframes" for k, _ in stack):
            return
        if stack and stack[-1][0] != "rule":
            return
        name, _, value = s.partition(":")
        sels = stack[-1][1] if stack else ()
        medias = tuple(d for k, d in stack if k == "media")
        out.append((at if at is not None else line, name.strip().lower(), value.strip(), sels, medias))

    for ch in text:
        if ch == "{":
            prelude = " ".join("".join(buf).split())
            low = prelude.lower()
            if low.startswith("@media"):
                stack.append(("media", low))
            elif low.startswith("@") and "keyframes" in low:
                stack.append(("keyframes", low))
            elif low.startswith("@"):
                stack.append(("group", low))
            else:
                stack.append(("rule", tuple(" ".join(s.split()) for s in split_top(prelude) if s.strip())))
            buf, at = [], None
        elif ch == "}":
            flush()
            if stack:
                stack.pop()
            buf, at = [], None
        elif ch == ";":
            flush()
            buf, at = [], None
        else:
            if at is None and not ch.isspace():
                at = line
            buf.append(ch)
        if ch == "\n":
            line += 1
    flush()
    return out


def covers(cover, sel):
    """縮小版の分岐のセレクタ（cover）が、動きのセレクタ sel を上書きするか。同じセレクタ、全称（*）、
    View Transitions の (*) の形を認める。"""
    for c in cover:
        if c == sel or c == "*" or c.startswith("*") or c.endswith(" *"):
            return True
        m = re.fullmatch(r"(::view-transition-[a-z-]+)\(\*\)", c)
        if m and sel.startswith(m.group(1) + "("):
            return True
    return False


def strip_var(value):
    """var(…) を外した値。var の 2 つ目の引数（代わりの値）の時間は、トークンの側の話なので数えない。"""
    prev = None
    while prev != value:
        prev, value = value, re.sub(r"var\([^()]*\)", " ", value)
    return value


def line_of(text, pos):
    return text[:pos].count("\n") + 1


def code_only(f, text):
    """注釈を、行数を変えずに空白へ置き換える。注釈に書いた語（止める、飛ばすなど）で検査が通らないようにする。
    行の途中から始まる // の注釈は残す（URL の // と見分けられないため）。"""
    blank = lambda m: re.sub(r"[^\n]", " ", m.group(0))  # noqa: E731
    text = re.sub(r"/\*.*?\*/", blank, text, flags=re.S)
    if f.suffix.lower() in (".html", ".htm", ".vue", ".svelte"):
        text = re.sub(r"<!--.*?-->", blank, text, flags=re.S)
    if f.suffix.lower() not in (".css", ".scss"):
        text = re.sub(r"(?m)^[ \t]*//[^\n]*", blank, text)
    return text


SCRIPT_FILES = (".js", ".mjs", ".cjs", ".ts", ".jsx", ".tsx")
MARKUP_FILES = (".html", ".htm", ".vue", ".svelte")
IMPORT_REF = re.compile(r"""(?:\bfrom\s*|\bimport\s*\(?\s*|<script\b[^>]*\bsrc\s*=\s*)["']([^"']+)["']""")


def script_parts(f, text):
    """html の類は <script> の中身だけを、行数を変えずに返す。ほかのファイルはそのまま。"""
    if f.suffix.lower() not in MARKUP_FILES:
        return text
    out = re.sub(r"[^\n]", " ", text)
    for m in re.finditer(r"<script\b[^>]*>(.*?)</script>", text, re.S | re.I):
        out = out[:m.start(1)] + m.group(1) + out[m.end(1):]
    return out


class MotionScope:
    """走査した全部のファイルの材料: トークンの定義と縮小版の上書き。止める・飛ばす・消音の手段は、
    動きや音を書いたファイルの中（と、そのファイルが読み込む走査中のファイル）でだけ探す。"""

    def __init__(self, files):
        self.defs, self.overridden = {}, set()
        self.texts = {}
        self.scripts = {}
        self.decls = {}
        self.imports = {}
        by_path = {f.resolve(): f for f in files}
        for f in files:
            text = code_only(f, f.read_text(encoding="utf-8", errors="replace"))
            self.texts[f] = text
            self.scripts[f] = script_parts(f, text)
            refs = set()
            for m in IMPORT_REF.finditer(text):
                if m.group(1).startswith("."):
                    g = by_path.get((f.parent / m.group(1)).resolve())
                    if g is not None and g != f:
                        refs.add(g)
            self.imports[f] = refs
            decls = []
            if f.suffix.lower() not in SCRIPT_FILES:
                for base, chunk in css_chunks(f, text):
                    decls += css_decls(chunk, base)
            self.decls[f] = decls
            for _no, name, value, _sels, medias in decls:
                if not name.startswith("--"):
                    continue
                self.defs.setdefault(name, []).append(value)
                if any(REDUCE_MQ.search(m) for m in medias):
                    self.overridden.add(name)
        self.css_stop_js = any(CSS_STOP_JS.search(self.texts[f]) for f in files if f.suffix.lower() in SCRIPT_FILES)
        self.media_pause_js = any(re.search(r"\.pause\s*\(", self.scripts[f]) and MEDIA_WORD.search(self.scripts[f]) for f in files)

    def has(self, f, rx):
        """f の中（html は script の中）か、f が読み込む走査中のファイルに rx があるか。"""
        return any(rx.search(self.scripts[g]) for g in [f, *sorted(self.imports.get(f, ()))])

    def is_time(self, name, depth=0):
        if depth > 5:
            return False
        if name not in self.defs:
            return re.search(r"dur|delay|motion|time|speed", name) is not None
        for v in self.defs[name]:
            if TIME.search(strip_var(v)) or any(self.is_time(t, depth + 1) for t in VAR.findall(v)):
                return True
        return False

    def reduced(self, name, depth=0):
        """トークンが、縮小版の分岐で直接か、参照する先のトークンで上書きされているか。"""
        if name in self.overridden:
            return True
        if depth > 5 or name not in self.defs:
            return False
        refs = [t for v in self.defs[name] for t in VAR.findall(v) if self.is_time(t)]
        return bool(refs) and all(self.reduced(t, depth + 1) for t in refs)


def allowed(allow, name, value):
    """許可リストに当たるか。transition は、カンマで分けた全部が当たるときだけ通す。"""
    parts = split_top(value) if name == "transition" else [value]
    return all(any(a.search(f"{name}: {p.strip()}") for a in allow) for p in parts if p.strip())


def motion_value(r, scope, f, no, decl, value, where, has_cover):
    """時間の書き方で、縮小版の有無を判定する。has_cover は、縮小版の分岐が同じ場所の動きを上書きしているか。"""
    if has_cover:
        return
    toks = [t for t in VAR.findall(value) if scope.is_time(t)]
    if TIME.search(strip_var(value)):
        r.fail(no, "縮小版", f"{f}:{no} 「{decl}」に縮小版が無い。{where}")
    elif toks:
        undefined = [t for t in toks if t not in scope.defs]
        missing = [t for t in toks if t in scope.defs and not scope.reduced(t)]
        if undefined:
            r.fail(no, "縮小版", f"{f}:{no} 「{decl}」のトークン {'、'.join(undefined)} の定義が対象に無い。tokens を含むファイルも一緒に渡す")
        if missing:
            r.fail(no, "縮小版", f"{f}:{no} 「{decl}」のトークン {'、'.join(missing)} に縮小版の上書きが無い。prefers-reduced-motion: reduce の中で書き換える")
    else:
        r.fail(no, "縮小版", f"{f}:{no} 「{decl}」の時間が数字でもトークンでもない。時間を書き、縮小版で同じ動きを上書きする")


def check_css_motion(r, scope, f, allow, infinite):
    decls = scope.decls[f]
    cover = set()
    for _no, name, _value, sels, medias in decls:
        if any(REDUCE_MQ.search(m) for m in medias) and MOTION_TOUCH.match(name):
            cover.update(sels)
    for no, name, value, sels, medias in decls:
        decl = f"{name}: {value}"
        if name == "transition" and re.match(r"all\b", value):
            r.fail(no, "動き", f"{f}:{no} transition: all。動かす属性を書く")
        if any(REDUCE_MQ.search(m) or NOPREF_MQ.search(m) for m in medias):
            continue  # 縮小版そのものか、動きを許す分岐の中
        if (name == "animation" and re.search(r"\binfinite\b", value)) or (name == "animation-iteration-count" and "infinite" in value):
            infinite.append((f, no, decl, "css"))
        if not MOTION_DECL.match(name) or re.match(r"none\b", value) or allowed(allow, name, value):
            continue
        if sels:
            where = f"prefers-reduced-motion: reduce の中で、同じセレクタ（{'、'.join(sels)}）の動きを上書きする"
            motion_value(r, scope, f, no, decl, value, where, any(covers(cover, s) for s in sels))
        else:
            motion_value(r, scope, f, no, decl, value, "style 属性の動きは縮小版で上書きできない。class に移して上書きする", False)


def check_script_motion(r, scope, f, allow, infinite):
    """JavaScript（と html などの中の script）の動き・音。CSS の文字列（CSS-in-JS）も見る。"""
    text = scope.texts[f]
    suffix = f.suffix.lower()
    # 縮小版の分岐は同じモジュールで探す。html は script の中だけ（同じ html の CSS の prefers-reduced-motion では通さない）
    reduced_ref = REDUCED_REF.search(scope.scripts[f]) is not None
    if suffix in (".js", ".mjs", ".cjs", ".ts", ".jsx", ".tsx"):
        for i, l in enumerate(text.split("\n"), 1):
            m = CSS_IN_JS.search(l)
            if not m:
                continue
            name, value = m.group(1), m.group(3).strip()
            decl = f"{name}: {value}"
            if name == "transition" and re.match(r"all\b", value):
                r.fail(i, "動き", f"{f}:{i} transition: all。動かす属性を書く")
            if re.match(r"none\b", value) or allowed(allow, name, value):
                continue
            if name == "animation" and re.search(r"\binfinite\b", value):
                infinite.append((f, i, decl, "css"))
            # CSS の文字列は、拡張の前と同じく prefers-reduced-motion の字がファイルにあるかで見る（検査を緩めない）
            motion_value(r, scope, f, i, decl, value, "同じモジュールで prefers-reduced-motion を見て、動きを止めるか替える", "prefers-reduced-motion" in text)
    hits = []
    for rx, label in JS_MOTION:
        m = rx.search(text)
        if m:
            hits.append((line_of(text, m.start()), label))
    m = RAF.search(text)
    if m and RAF_STYLE.search(text):
        hits.append((line_of(text, m.start()), "requestAnimationFrame で style を変える動き"))
    elif m and RAF_CANVAS.search(text) and not ENGINE_STOP.search(text):
        hits.append((line_of(text, m.start()), "requestAnimationFrame で canvas を描き、止める関数の無いエンジン"))
    hits.sort()
    if hits and not reduced_ref:
        no = hits[0][0]
        labels = "、".join(dict.fromkeys(h[1] for h in hits))
        r.fail(no, "縮小版", f"{f}:{no} JavaScript の動き（{labels}）に縮小版の分岐が無い。同じモジュールで prefers-reduced-motion を見る")
    if hits:
        longest, unknown = 0, []
        for m in JS_DURATION.finditer(text):
            if m.group(2):
                longest = max(longest, float(m.group(2)))
                continue
            expr = m.group(1)
            raws = re.findall(r"(?<![\w.])\d+(?:\.\d+)?(?![\w.])", expr)
            # 名前で書いた長さ（duration: LONG）は、同じファイルの const・let・var の数を引く
            for ident in re.findall(r"(?<![\w.$])([A-Za-z_$][\w$]*)(?![\w$(])", expr):
                d = re.search(rf"\b(?:const|let|var)\s+{re.escape(ident)}\s*=\s*(\d+(?:\.\d+)?)\s*[;,\n]", text)
                if d:
                    raws.append(d.group(1))
            if not raws:
                unknown.append(expr.strip()[:24])
            for raw in raws:
                v = float(raw)
                longest = max(longest, v * 1000 if ("." in raw or v <= 10) else v)  # 0.9 や 2 は秒（motion の部品の書き方）
        if longest > LONG_MS and not scope.has(f, SKIP):
            no = hits[0][0]
            r.fail(no, "飛ばす", f"{f}:{no} {longest:.0f}ms の動きに飛ばす手段が無い。同じモジュールで、どのキーでも終わりの状態へ進める（finish()、skipTransition()、skip の関数）")
        elif unknown and not scope.has(f, SKIP):
            no = hits[0][0]
            r.warn(no, "飛ばす", f"{f}:{no} 動きの長さ（{'、'.join(dict.fromkeys(unknown))}）が数字でなく、同じファイルの定数でも引けない。{LONG_MS}ms を超えるなら飛ばす手段を置く")
    for m in INFINITE_JS.finditer(text):
        no = line_of(text, m.start())
        infinite.append((f, no, "iterations: Infinity", "js"))
    sounds = [(line_of(text, m.start()), label) for rx, label in SOUND for m in [rx.search(text)] if m]
    m = MEDIA_PLAY.search(text)
    if m and MEDIA_WORD.search(text):
        sounds.append((line_of(text, m.start()), "音か映像の play()"))
    if sounds and not scope.has(f, MUTE):
        sounds.sort()
        no = sounds[0][0]
        r.fail(no, "消音", f"{f}:{no} 音（{'、'.join(dict.fromkeys(s[1] for s in sounds))}）に消音の手段が無い。同じモジュールに、動きとは別の消音のスイッチを置く")


def check_media_tags(r, f, text, infinite):
    for m in MEDIA_TAG.finditer(text):
        tag, attrs = m.group(1).lower(), m.group(2)
        no = line_of(text, m.start())
        if not re.search(r"\bautoplay\b", attrs, re.I):
            continue
        if tag == "audio":
            r.fail(no, "自動再生", f"{f}:{no} audio の autoplay。音は操作のあとで鳴らす（WCAG 2.2 の 1.4.2）")
        elif not re.search(r"\bmuted\b", attrs, re.I):
            r.fail(no, "自動再生", f"{f}:{no} video の autoplay に muted が無い。音のある映像を勝手に流さない")
        if re.search(r"\bloop\b", attrs, re.I) and not re.search(r"\bcontrols\b", attrs, re.I):
            infinite.append((f, no, f"{tag} の autoplay と loop", "media"))


def node_script(f):
    """1 行目が #! で始まる JavaScript は、Node で回す道具（試験や計測のスクリプト）で、ブラウザでは動かない。"""
    if f.suffix.lower() not in PLAIN_SCRIPT_EXT:
        return False
    with open(f, "rb") as fh:
        return fh.read(2) == b"#!"


def check_motion(paths, r):
    files = [f for f in scan_files(paths, MOTION_EXT) if not node_script(f)]
    if not files:
        r.fail(0, "対象", "走査できるファイルが無い")
        return
    allow = load_allow("motion-allow.txt")
    scope = MotionScope(files)
    infinite = []
    for f in files:
        suffix = f.suffix.lower()
        if suffix not in (".js", ".mjs", ".cjs", ".ts", ".jsx", ".tsx"):
            check_css_motion(r, scope, f, allow, infinite)
        if suffix in (".js", ".mjs", ".cjs", ".ts", ".jsx", ".tsx", ".html", ".htm", ".vue", ".svelte"):
            check_script_motion(r, scope, f, allow, infinite)
        if suffix in (".html", ".htm", ".vue", ".svelte", ".jsx", ".tsx"):
            check_media_tags(r, f, scope.texts[f], infinite)
    # 止める手段は、回り続ける動きを書いたファイルの中（と、そのファイルが読み込むファイル）で探す。
    # CSS の動きは、JavaScript の animationPlayState か getAnimations() からの pause()・cancel() でも止められる
    for f, no, decl, kind in infinite:
        local = any(scope.has(f, rx) for rx in STOP) or (f.suffix.lower() not in SCRIPT_FILES and any(rx.search(scope.texts[f]) for rx in STOP))
        if local or (kind == "css" and scope.css_stop_js) or (kind == "media" and scope.media_pause_js):
            continue
        r.fail(no, "止める", f"{f}:{no} 「{decl}」は回り続けるのに、同じファイルに止める手段が無い（WCAG 2.2 の 2.2.2）。animation-play-state: paused か pause() で止める操作を置く")


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
# motion-lint の負例: (ディレクトリ, 落ちる決まり, 最少の件数)。c・d1・h・i・j は、拡張の前に素通りした 5 例
MOTION_CASES = [
    ("c-token", "縮小版", 1),
    ("d1-jsx", "縮小版", 1),
    ("h-autoplay", "自動再生", 2),
    ("i-infinite", "止める", 1),
    ("j-unrelated", "縮小版", 3),
    ("js-animate", "縮小版", 1),
    ("js-raf", "縮小版", 1),
    ("js-canvas", "縮小版", 1),
    ("skip", "飛ばす", 1),
    ("sound", "消音", 1),
    # 関係の無い語で通っていた 6 例（2026-11-26 の査読）: 色のトークン --muted、Service Worker の skipWaiting()、
    # 同じ html の CSS の prefers-reduced-motion、video の muted 属性、別のファイルの cancel()、定数で書いた長さ
    ("mute-token", "消音", 1),
    ("skip-sw", "飛ばす", 1),
    ("html-reduced", "縮小版", 1),
    ("video-muted", "消音", 1),
    ("reset-cancel", "止める", 1),
    ("const-duration", "飛ばす", 1),
]


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


def quiet_text(kind, text):
    """文書の写しを一時のファイルに書いて検査する（自己試験の変えた写し）。"""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        p = pathlib.Path(tmp) / "doc.md"
        p.write_text(text, encoding="utf-8")
        return quiet(kind, [str(p)])


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
        # 画面の型: 没入の型なら演出の実装の節と性能予算の演出の行が要る。型の外の値は落ちる。見出しの ** は外して読む
        src = EX_PLAN.read_text(encoding="utf-8")
        for label, row, wants in (("没入の型", "| 画面の型 | 没入の型 |", ("[演出の実装]", "[性能予算]")),
                                  ("見出しを太字にした没入の型", "| **画面の型** | `没入の型` |", ("[演出の実装]",)),
                                  ("型の外の値", "| 画面の型 | ゲームの型 |", ("[画面の型]",))):
            rc, out = quiet_text("plan", src.replace("| 作成日 | 2026-11-06 |", f"{row}\n| 作成日 | 2026-11-06 |", 1))
            checks.append((rc == 1 and all(w in out for w in wants), f"{label}の実装計画で {'・'.join(wants)} が出ない: {out[-300:]}"))
        rc, out = quiet("plan", [str(EX_PLAN)])
        checks.append((rc == 0 and "[画面の型]" not in out, f"画面の型の行（今の型）がある完成例が落ちた: {out[-300:]}"))
        rc, out = quiet_text("plan", src.replace("| 画面の型 | 今の型。受付票から写した |\n", "", 1))
        checks.append((rc == 1 and "FAIL" in out and "[画面の型]" in out, f"画面の型の行が無い実装計画が落ちない: {out[-300:]}"))
    elif kind == "self":
        rc, out = quiet("self", [str(EX_SELF)])
        checks.append((rc == 0, f"完成例が落ちた: {out[-300:]}"))
        rc, out = quiet("self", [str(FIX / "bad-self-check.md")])
        for rule in ("判定", "結果", "推測", "ゲートの出力"):
            checks.append((f"[{rule}]" in out, f"負例で「{rule}」が出ない"))
        # 没入の型の自己点検票は、演出の 12 項目の行・演出の計測の出力・記録とフレームの置き場が要る
        src = EX_SELF.read_text(encoding="utf-8")
        rc, out = quiet_text("self", src.replace("| 対象 |", "| 画面の型 | 没入の型 |\n| 対象 |", 1))
        wants = ("[演出の 12 項目]", "[演出の計測]", "[演出の記録]", "[フレームの一覧]")
        checks.append((rc == 1 and all(w in out for w in wants), f"没入の型の自己点検票で {'・'.join(wants)} が出ない: {out[-300:]}"))
    elif kind == "motion":
        rc, out = quiet("motion", [str(FIX / "good-app")])
        checks.append((rc == 0, f"正例が落ちた: {out[-300:]}"))
        rc, out = quiet("motion", [str(FIX / "bad-app")])
        checks.append((rc == 1 and "[縮小版]" in out and "[動き]" in out, f"負例が通った: {out[-300:]}"))
        rc, out = quiet("motion", [str(FIX / "motion" / "good-scene")])
        checks.append((rc == 0, f"正例の good-scene が落ちた: {out[-300:]}"))
        for case, rule, count in MOTION_CASES:
            rc, out = quiet("motion", [str(FIX / "motion" / case)])
            n = out.count(f"[{rule}]")
            checks.append((rc == 1 and n >= count, f"負例の {case} が「{rule}」で {count} 件落ちない（{n} 件）: {out[-300:]}"))
        rc, out = quiet("motion", [str(FIX / "motion" / "c-token")])
        checks.append(("--duration-2" in out, "負例の c-token で、上書きの無いトークンの名前が出ない"))
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
