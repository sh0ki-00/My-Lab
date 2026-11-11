#!/usr/bin/env python3
"""check-doc — 文書の型の検査。.company/rules/documents.md の、機械で見られる決まりを落とす。

種類の決め方: 表題の先頭「種類:」（「調査報告書:」は調査報告と同じ）か、表題の末尾の語
（〜手順書、〜運用設計書、〜要件定義書、〜ポストモーテム、〜調査報告書、〜仕様書）。どちらも無ければ種類の無い資料。
資料の型（仕様書、調査報告、設計書、完了報告、種類の無い資料）: 冒頭の 3 行の要約（引用ブロック、各行が文）、
節の冒頭の導入の文（表・図・箇条書きから始めない）、図と表の密度（本文 500 字に 1 つ）、図の直後の読み方、
用語の初出の括弧説明、見出しの深さ（4 階層まで）、種類ごとの必須の節。
現場の文書の型（手順書、運用設計書、要件定義書、ポストモーテム）: 資料の型は掛けず、表題の直下の文書情報の表と必須の節を見る。
種類ごとの中身の決まり:
  手順書: 手順の形（手順の節は番号付きの 1 行 1 操作。番号の無い段落が 3 行以上なら落とす）と、操作ごとの期待結果の行。
  調査報告: 比較の表に根拠か出典の列、出典の表に参照日の列、結論の節に確信度と「推奨が変わる条件」。
  要件定義書: 機能要件と非機能要件の表（ID、優先度、受け入れ基準か要求値、検証方法の列）、ID の空と重複、優先度の語、
    要件の文の曖昧語（など、適切に、速やかに…）、未決事項の表（担当、期限）。
  ポストモーテム: 影響の節の数字、タイムラインの表と時間帯の宣言、対策の表（担当、期限、優先度、状態）と担当・期限の空、
    人の注意に頼る対策、反事実の語（すべきだった、できたはず）。
  仕様書（新しい型のとき）: 代替案の表に却下の理由の列、未確定の表に担当と期限の列。
    2026-11-06 の型（完成の条件、全体像、将来の変化、実装の進め方、やらないこと、未確定、確認事項）も必須の節として受け付ける。
使い方: check_doc.py <ファイル>...   /   check_doc.py --selftest
出力: FAIL <ファイル>:<行> [<決まり>] <内容> を並べ、最後に RESULT: PASS|FAIL。1 件でも FAIL なら終了コード 1。
"""
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import mdparse  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
TERMS_FILE = HERE.parent / "doc-terms.txt"

DENSITY = 500
MAX_LEVEL = 4
STEP_PROSE = 3  # 手順書の手順の節に許す、番号の無い段落の行数。これ以上で落とす（理由は注意事項へ）
# 種類ごとの必須の節。複数の型があるときは、最も欠けの少ない型で見る
REQUIRED = {
    "仕様書": [
        ["背景", "利用者", "目標", "やらないこと", "振る舞い", "完成の条件", "代替案", "横断", "未確定"],
        ["完成の条件", "全体像", "将来の変化", "実装の進め方", "やらないこと", "未確定", "確認事項"],  # 2026-11-06 の型
    ],
    "設計書": [["背景", "目標", "設計", "代替案", "横断", "流出経路"]],
    "調査報告": [["問い", "範囲", "方法", "比較", "未確認", "結論", "出典"]],
    "手順書": [["目的", "前提", "手順", "確認", "切り戻し", "記録"]],
    "運用設計書": [["方針", "体制", "運用項目", "監視", "バックアップ", "障害", "変更"]],
    "要件定義書": [["目的", "指標", "範囲", "対象外", "前提", "制約", "業務要件", "機能要件", "非機能要件", "受け入れ", "追跡", "未決"]],
    "ポストモーテム": [["要約", "影響", "検知", "対応", "タイムライン", "原因", "教訓", "対策"]],
    "完了報告": [["確認", "未確認"]],
}
# 現場の文書の型で見る種類。資料の型（要約、導入の文、密度、図の読み方、用語）は掛けない
FIELD_KINDS = ("手順書", "運用設計書", "要件定義書", "ポストモーテム")
FIELD_INFO = {
    "手順書": "作業名、対象システム、作業者と確認者、承認、版",
    "運用設計書": "対象システム、対象環境、作成と承認、版",
    "要件定義書": "対象、決める人、作成者、状態、版",
    "ポストモーテム": "発生日、重大度、状態、著者、所有者",
}
FIELD_NOTE = {
    "手順書": "読み手の説明と用語の節は書かない",
    "運用設計書": "読み手の説明と用語の節は書かない",
    "要件定義書": "読み手の説明の節は書かず、用語は用語定義の節に置く",
    "ポストモーテム": "読み手の説明の節は書かず、前提と語は背景と用語の節に置く",
}
PREFIX_KIND = re.compile(r"^(手順書|運用設計書|調査報告書?|仕様書|要件定義書|ポストモーテム|設計書|完了報告)\s*[:：]")
SUFFIX_KIND = re.compile(r"(手順書|運用設計書|調査報告書|仕様書|要件定義書|ポストモーテム)$")
EXPECTED = re.compile(r"期待結果|期待する結果|確かめ方|確認結果")
STEP_ITEM = re.compile(r"^\d+[.)]\s")  # 字下げの無い、番号付きの操作の行
VAGUE = ["など", "適切に", "簡単に", "速やかに", "柔軟に", "迅速に", "可能な限り", "必要に応じて", "十分な", "十分に", "使いやすい", "最高の", "より良い"]
PRIORITY = ["Must", "Should", "Could", "Won't", "必須", "重要", "あれば良い", "今回はやらない"]
NOT_REQ_COL = ("ID", "番号", "項番", "備考", "根拠", "出典", "関連", "状態", "優先度", "検証", "分類", "大項目", "中項目", "小項目", "担当", "発案", "レベル")
COUNTERFACTUAL = ["すべきだった", "できたはず", "していれば", "すればよかった"]
ONLY_CARE = re.compile(r"^(注意|気を付け|気をつけ|周知|徹底)")
KIND_NAME = {"table": "表", "fence": "コードか図", "list": "箇条書き", "image": "画像", "hr": "区切り線"}


def load_terms():
    terms = []
    if not TERMS_FILE.exists():
        return terms
    for line in TERMS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        terms.append(line.split("\t")[0].strip())
    return terms


def term_regex(term: str):
    if re.fullmatch(r"[A-Za-z0-9+/. -]+", term):
        return re.compile(rf"(?<![A-Za-z0-9+/]){re.escape(term)}(?![A-Za-z0-9+/])")
    return re.compile(re.escape(term))


def next_content(lines, i):
    for ln in lines[i + 1:]:
        if ln.kind in ("blank", "comment"):
            continue
        return ln
    return None


def kind_of(title: str):
    """表題から種類を決める。先頭の「種類:」を優先し、無ければ末尾の語で見る。「調査報告書」は「調査報告」に揃える。"""
    t = title.strip()
    m = PREFIX_KIND.match(t) or SUFFIX_KIND.search(t)
    return m.group(1).replace("調査報告書", "調査報告") if m else None


def sections(lines):
    """level 2 以上の見出しごとに、(見出しの行, 次の同じ階層以上の見出しまでの行) を返す。"""
    out = []
    for i, ln in enumerate(lines):
        if ln.kind == "heading" and ln.level >= 2:
            body = []
            for nx in lines[i + 1:]:
                if nx.kind == "heading" and nx.level <= ln.level:
                    break
                body.append(nx)
            out.append((ln, body))
    return out


def find_section(lines, *words):
    """見出しに語のどれかを含む最初の節。無ければ (None, [])。"""
    for h, body in sections(lines):
        if any(w in h.text for w in words):
            return h, body
    return None, []


def cells_of(raw: str):
    s = raw.strip()
    s = s[1:] if s.startswith("|") else s
    s = s[:-1] if s.endswith("|") else s
    return [c.strip().strip("`").strip() for c in s.split("|")]


def tables_in(body):
    """節の中の表を {no, header, rows:[(no, cells)]} の一覧で返す。"""
    tabs, cur = [], None
    for ln in body:
        if ln.kind != "table":
            cur = None
            continue
        cells = cells_of(ln.raw)
        if cur is None:
            cur = {"no": ln.no, "header": cells, "rows": []}
            tabs.append(cur)
        elif all(re.fullmatch(r":?-+:?", c) for c in cells if c):
            continue
        else:
            cur["rows"].append((ln.no, cells))
    return tabs


def col(header, *words):
    for i, h in enumerate(header):
        if any(w in h for w in words):
            return i
    return None


def body_text(body):
    return "".join(ln.text for ln in body if ln.kind in ("prose", "quote", "list", "table"))


def check_research(lines, issues):
    h, body = find_section(lines, "比較")
    if h is not None:
        tabs = tables_in(body)
        if not tabs:
            issues.append((h.no, "比較の表", "比較の節に表が無い。観点と候補を表にし、根拠の列を置く"))
        elif not any(col(t["header"], "根拠", "出典") is not None for t in tabs):
            issues.append((tabs[0]["no"], "比較の表", "比較の表に「根拠」か「出典」の列が無い。点だけのセルを置かない"))
    h, body = find_section(lines, "出典")
    if h is not None:
        tabs = tables_in(body)
        if not tabs or not any(col(t["header"], "参照日") is not None for t in tabs):
            issues.append((h.no, "出典の表", "出典は表にし、「参照日」の列を置く（Web の中身は変わるか消える）"))
    h, body = find_section(lines, "結論")
    if h is not None:
        text = body_text(body)
        if "確信度" not in text:
            issues.append((h.no, "確信度", "結論の節に確信度（高・中・低）が無い"))
        if "変わる条件" not in text and "変わるとき" not in text:
            issues.append((h.no, "変わる条件", "結論の節に「推奨が変わる条件」が無い"))


def check_requirements(lines, issues):
    ids = {}
    for name in ("機能要件", "非機能要件"):
        h, body = find_section(lines, name)
        if h is None:
            continue
        tabs = tables_in(body)
        good = [t for t in tabs if col(t["header"], "ID", "番号", "項番") is not None and col(t["header"], "優先度") is not None
                and col(t["header"], "受け入れ", "要求値") is not None and col(t["header"], "検証") is not None]
        if not good:
            issues.append((h.no, "要件の表", f"{name}の節に、ID・優先度・受け入れ基準（か要求値）・検証方法の列を持つ表が無い"))
        for t in good:
            ci, cp = col(t["header"], "ID", "番号", "項番"), col(t["header"], "優先度")
            req_cols = [i for i, hd in enumerate(t["header"]) if not any(w in hd for w in NOT_REQ_COL)]
            for no, cells in t["rows"]:
                if len(cells) <= max(ci, cp):
                    continue
                rid = cells[ci]
                if not rid:
                    issues.append((no, "要件 ID", "要件の ID が空。1 要件 1 行で、固有の番号を付ける"))
                elif rid in ids:
                    issues.append((no, "要件 ID", f"ID「{rid}」が {ids[rid]} 行目と重なる。番号は使い回さない"))
                else:
                    ids[rid] = no
                if not any(p in cells[cp] for p in PRIORITY):
                    issues.append((no, "優先度", f"優先度「{cells[cp]}」。Must・Should・Could・Won't（必須・重要・あれば良い・今回はやらない）のどれかにする"))
                for i in req_cols:
                    if i >= len(cells):
                        continue
                    hit = next((w for w in VAGUE if w in mdparse.clean(cells[i])), None)
                    if hit:
                        issues.append((no, "曖昧語", f"「{hit}」は測れない。数値と条件に置き換える: {cells[i][:30]}"))
                        break
    h, body = find_section(lines, "未決")
    if h is not None:
        tabs = tables_in(body)
        if not tabs or not any(col(t["header"], "担当") is not None and col(t["header"], "期限") is not None for t in tabs):
            issues.append((h.no, "未決の表", "未決事項は表にし、担当と期限の列を置く。先送りを隠さない"))


def check_postmortem(lines, issues):
    h, body = find_section(lines, "影響")
    if h is not None and not re.search(r"\d", body_text(body)):
        issues.append((h.no, "影響の数字", "影響の節に数字が無い。期間、利用者数、問い合わせ数、失われた要求を書く。推定なら推定と書く"))
    h, body = find_section(lines, "タイムライン")
    if h is not None:
        tabs = tables_in(body)
        if not tabs:
            issues.append((h.no, "タイムライン", "タイムラインは表にする（時刻、出来事、根拠）"))
        else:
            declared = h.text + " ".join(" ".join(t["header"]) for t in tabs) + "".join(ln.text for ln in body if ln.kind in ("prose", "list"))
            if not re.search(r"JST|UTC|時間帯", declared):
                issues.append((h.no, "タイムライン", "時間帯（JST か UTC）を、見出しか表の頭か節の 1 文目で宣言する"))
    h, body = find_section(lines, "対策")
    if h is not None:
        tabs = tables_in(body)
        good = [t for t in tabs if all(col(t["header"], w) is not None for w in ("担当", "期限", "優先度", "状態"))]
        if not good:
            issues.append((h.no, "対策の表", "対策は、担当・期限・優先度・状態の列を持つ表にする"))
        for t in good:
            co, cd = col(t["header"], "担当"), col(t["header"], "期限")
            ca = col(t["header"], "対策", "内容", "アクション")
            ca = 0 if ca is None else ca
            for no, cells in t["rows"]:
                if len(cells) <= max(co, cd, ca):
                    continue
                if not cells[co] or not cells[cd]:
                    issues.append((no, "担当と期限", "対策の担当と期限を空にしない。担当は 1 人"))
                if ONLY_CARE.match(cells[ca]):
                    issues.append((no, "対策の形", f"「{cells[ca][:12]}」は人の注意に頼る対策。仕組みか手順に落とす"))
    for ln in lines:
        if ln.kind in ("prose", "list", "table", "quote"):
            hit = next((w for w in COUNTERFACTUAL if w in ln.text), None)
            if hit:
                issues.append((ln.no, "反事実", f"「{hit}」。〜すべきだった・〜できたはずの形で書かず、起きた事実と寄与した要因を書く"))


def check_spec(lines, issues):
    h, body = find_section(lines, "代替案")
    if h is not None:
        tabs = tables_in(body)
        if not tabs or not any(col(t["header"], "却下", "理由") is not None for t in tabs):
            issues.append((h.no, "代替案の表", "代替案は表にし、却下の理由の列を置く"))
    h, body = find_section(lines, "未確定", "未解決")
    if h is not None:
        tabs = tables_in(body)
        if not tabs or not any(col(t["header"], "担当") is not None and col(t["header"], "期限") is not None for t in tabs):
            issues.append((h.no, "未確定の表", "未確定は表にし、担当と期限の列を置く"))


def check_text(src: str):
    issues = []
    lines = mdparse.parse(src)
    h1 = next((i for i, ln in enumerate(lines) if ln.kind == "heading" and ln.level == 1), None)
    if h1 is None:
        issues.append((0, "表題", "# の見出し（表題）が無い"))
        return issues

    title = lines[h1].text
    kind = kind_of(title)
    field_doc = kind in FIELD_KINDS

    # 1. 3 行の要約（引用ブロック）。現場の文書の型には掛けない
    if not field_doc:
        quote = []
        started = False
        for ln in lines[h1 + 1:]:
            if ln.kind == "heading":
                break
            if ln.in_quote and ln.kind in ("list", "quote"):
                quote.append(ln)
                started = True
            elif started and ln.kind != "blank":
                break
        content = [q for q in quote if not ("要約" in q.text and not q.text.endswith("。"))]
        if not quote:
            issues.append((lines[h1].no, "要約", "表題の下に 3 行の要約（引用ブロック > ）が無い"))
        elif len(content) != 3:
            issues.append((quote[0].no, "要約", f"要約が {len(content)} 行。何の文書か・結論・次にすることの 3 行にする"))
        else:
            for q in content:
                if not q.text.endswith(("。", "！", "？")):
                    issues.append((q.no, "要約", "要約の各行は文にする（。で終える）"))

    # 2. 見出しの深さ、空の節、節の冒頭の導入の文。導入の文は現場の文書の型には掛けず、手順書の手順の小節は番号付きの操作から始めてよい
    h2 = ""
    for i, ln in enumerate(lines):
        if ln.kind != "heading":
            continue
        if ln.level == 2:
            h2 = ln.text
        if ln.level > MAX_LEVEL:
            issues.append((ln.no, "見出しの深さ", f"{ln.level} 階層。4 階層までにする"))
        if ln.level == 1:
            continue
        step_sub = kind == "手順書" and ln.level >= 3 and "手順" in h2
        nxt = next_content(lines, i)
        if nxt is None:
            issues.append((ln.no, "空の節", "見出しの下に本文が無い"))
        elif nxt.kind == "heading":
            if nxt.level <= ln.level:
                issues.append((ln.no, "空の節", "見出しの直後が同じ階層の見出し。本文を書くか見出しを消す"))
        elif field_doc:
            pass
        elif nxt.kind in ("prose", "quote", "skipped"):
            pass
        elif nxt.kind == "list" and ("目次" in ln.text or step_sub):
            pass
        else:
            issues.append((ln.no, "導入の文", f"節が{KIND_NAME.get(nxt.kind, nxt.kind)}から始まる。1 文目に、その節の結論か要点を書く"))

    if not field_doc:
        # 3. 図と表の密度
        body = sum(mdparse.length(ln.text) for ln in lines if ln.kind in ("prose", "quote", "list"))
        mermaids = mdparse.code_blocks(lines, "mermaid")
        tables = 0
        prev_table = False
        for ln in lines:
            if ln.kind == "table" and not prev_table:
                tables += 1
            prev_table = ln.kind == "table"
        required = body // DENSITY
        if len(mermaids) + tables < required:
            issues.append((0, "図と表の密度", f"図 {len(mermaids)} と表 {tables}。本文 {body} 字には {required} 個以上"))

        # 4. 図の直後の読み方
        for _lang, start, end, _content in mermaids:
            idx = next(i for i, ln in enumerate(lines) if ln.no == end)
            following = [ln for ln in lines[idx + 1:] if ln.kind not in ("blank", "comment")][:3]
            if not any("読み方" in ln.text for ln in following if ln.kind in ("prose", "quote", "list")):
                issues.append((start, "図の読み方", "図の直後に「図の読み方: …」を 1〜2 文書く"))

        # 5. 用語の初出の括弧説明
        glossary = set()
        section = ""
        for ln in lines:
            if ln.kind == "heading":
                section = ln.text
            elif ln.kind == "table" and "用語" in section:
                first_cell = ln.text.split("|")[0].strip()
                if first_cell:
                    glossary.add(first_cell)
        # 表だけに出る語は初出と見ない。説明は、本文の初出の行か、それより前の行（表を含む）にあればよい

        def glossed(text, m):
            after = text[m.end():m.end() + 40]
            before = text[:m.start()]
            inside = before.count("（") > before.count("）") or before.count("(") > before.count(")")
            return re.match(r"\s*[（(]", after) is not None or inside

        for term in load_terms():
            if any(term in g for g in glossary):
                continue
            rx = term_regex(term)
            first_prose = None
            first_any = None
            gloss_at = None
            for ln in lines:
                if ln.kind not in ("prose", "quote", "list", "table"):
                    continue
                if not rx.search(ln.text):
                    continue
                if first_any is None:
                    first_any = ln
                if gloss_at is None and any(glossed(ln.text, mm) for mm in rx.finditer(ln.text)):
                    gloss_at = ln.no
                if first_prose is None and ln.kind != "table":
                    first_prose = ln
            if first_any is None:
                continue
            if gloss_at is None:
                issues.append(((first_prose or first_any).no, "用語の初出", f"「{term}」に括弧の説明がどこにも無い"))
            elif first_prose is not None and gloss_at > first_prose.no:
                issues.append((first_prose.no, "用語の初出", f"「{term}」の初出に括弧の説明が無い（説明は {gloss_at} 行目）"))

    # 6. 文書の種類ごとの必須の節。型が複数ある種類は、最も欠けの少ない型で見る
    headings = [ln.text for ln in lines if ln.kind == "heading" and ln.level >= 2]
    matched = None
    if kind is not None:
        best_alt, best_missing = None, None
        for alt in REQUIRED[kind]:
            missing = [k for k in alt if not any(k in h for h in headings)]
            if best_missing is None or len(missing) < len(best_missing):
                best_alt, best_missing = alt, missing
        matched = REQUIRED[kind].index(best_alt)
        for key in best_missing:
            issues.append((lines[h1].no, "必須の節", f"{kind}に「{key}」の節が無い"))

    # 7. 現場の文書の型は、表題の直下に文書情報の表を置く
    if field_doc:
        nxt = next_content(lines, h1)
        if nxt is None or nxt.kind != "table":
            issues.append((lines[h1].no, "文書情報", f"{kind}は表題の直下に文書情報の表（{FIELD_INFO[kind]}）を置く。{FIELD_NOTE[kind]}"))

    if kind == "手順書":
        # 8. 手順の形。手順の節（見出しに「手順」）は番号付きの 1 行 1 操作で書き、理由の段落は注意事項へ
        in_steps = False
        prose = []
        for ln in lines:
            if ln.kind == "heading" and ln.level == 2:
                in_steps = "手順" in ln.text
            elif in_steps and ln.kind == "prose":
                prose.append(ln)
        if len(prose) >= STEP_PROSE:
            issues.append((prose[STEP_PROSE - 1].no, "手順の形", f"手順の節に番号の無い段落が {len(prose)} 行。操作は番号付きの 1 行にし、コマンドと期待結果をその直下に置き、理由は注意事項に 1 行で添える"))

        # 9. 期待結果。手順と切り戻しの節では、番号付きの操作ごとに、直下に期待結果の行を置く
        h2 = h3 = ""
        pending = None
        msg = "操作「{}」の直下に期待結果の行が無い。「- 期待結果: 返る値や状態」を置く"
        for ln in lines:
            if ln.kind == "heading":
                if pending is not None:
                    issues.append((pending[0], "期待結果", msg.format(pending[1][:20])))
                    pending = None
                if ln.level == 2:
                    h2, h3 = ln.text, ""
                elif ln.level == 3:
                    h3 = ln.text
                continue
            if not any("手順" in h or "切り戻し" in h for h in (h2, h3)):
                continue
            if ln.kind == "list" and STEP_ITEM.match(ln.raw):
                if pending is not None:
                    issues.append((pending[0], "期待結果", msg.format(pending[1][:20])))
                pending = (ln.no, ln.text)
            elif pending is not None and ln.kind in ("list", "prose", "table") and EXPECTED.search(ln.text):
                pending = None
        if pending is not None:
            issues.append((pending[0], "期待結果", msg.format(pending[1][:20])))

    # 10〜13. 種類ごとの中身の決まり
    if kind == "調査報告":
        check_research(lines, issues)
    elif kind == "要件定義書":
        check_requirements(lines, issues)
    elif kind == "ポストモーテム":
        check_postmortem(lines, issues)
    elif kind == "仕様書" and matched == 0:
        check_spec(lines, issues)
    return issues


def report(name: str, issues) -> bool:
    for no, rule, detail in issues:
        where = f"{name}:{no}" if no else name
        print(f"FAIL {where} [{rule}] {detail}")
    verdict = "PASS" if not issues else "FAIL"
    print(f"RESULT: {verdict} check-doc {name} ({len(issues)} 件)")
    return not issues


GOOD_RESEARCH = """# 調査報告書: 見本

> **3 行でわかる要約**
> 1. これは検査の見本です。
> 2. 結論は、書く操作だけを止めることです。
> 3. 次に、問いの節を読みます。

## 1. 問いと背景

問いは 1 つで、hooks（コマンドの直前に走る検査）が止める範囲です。

| 番号 | 問い |
|---|---|
| 1 | 止める範囲はどこか |

## 2. 範囲と前提

範囲は守りの判定だけで、検証の道具は含みません。

## 3. 方法と期間

方法は、守りの表を読むことです。期間は 2026-11-11 の 1 時間です。

## 4. 比較

比較は 2 つの操作です。

| 操作 | 判定 | 根拠 |
|---|---|---|
| 読む | 許可 | 守りの表の 1 行目 |

## 5. 未確認と限界

試していないのは、符号化した命令です。

## 6. 結論と推奨

結論は、書く操作だけを止めることです。確信度は高で、推奨が変わる条件は守りの表が変わったときです。

## 7. 出典

出典は守りの表です。

| 番号 | 題名 | 参照日 |
|---|---|---|
| 1 | 守りの表 | 2026-11-11 |
"""

GOOD_PROCEDURE = """# 見本の作業 手順書

| 項目 | 内容 |
|---|---|
| 作業名 | 見本の作業 |
| 作業者 / 確認者 | 秘書 / 社長 |

## 1. 目的

見本の作業を同じ順で行う。

## 2. 前提条件

- 作業用の場所がある。

## 3. 作業手順

1. ファイルを開く。
   - 期待結果: 中身が出る。
2. 1 行を書き足す。
   - 期待結果: 行数が 1 つ増える。

## 4. 作業後の確認

| # | 確認項目 | 期待結果 |
|---|---|---|
| 1 | 行数 | 1 つ増えている |

## 5. 切り戻し

1. 足した行を消す。
   - 期待結果: 行数が元に戻る。

## 6. 作業記録

```text
- 実施日時:
```
"""

GOOD_OPS = """# 見本 運用設計書

| 項目 | 内容 |
|---|---|
| 対象システム | 見本 |

## 1. 基本方針

- 依頼は Issue で受ける。

## 2. 運用体制

| 役割 | 担当 |
|---|---|
| 当番 | 秘書 |

## 3. 運用項目一覧

| No | 分類 | 運用項目 |
|---|---|---|
| 1 | 基盤運用 | 検証 |

## 4. 監視

| 監視項目 | 条件 |
|---|---|
| 検証 | FAIL |

## 5. バックアップ

| 対象 | 方式 |
|---|---|
| 記録 | git |

## 6. 障害時の処置

| レベル | 状態 |
|---|---|
| 1 | 止まる |

## 7. 変更管理

| 段階 | すること |
|---|---|
| 承認 | 社長 |
"""

GOOD_SPEC = """# 仕様書: 見本

> **3 行でわかる要約**
> 1. これは検査の見本です。
> 2. 結論は、見本の機能を 1 つ作ることです。
> 3. 次に、背景の節を読みます。

## 1. 背景と範囲

背景は、見本が無いことです。範囲は見本の機能だけです。

## 2. 利用者と場面

利用者は秘書で、場面は検査のときです。

## 3. 目標とやらないこと

目標は、検査が通ることです。やらないことは、本番で使うことです。

## 4. 振る舞いの詳細

振る舞いは、入力を受けて結果を返すことです。

| 入力 | 処理 | 出力 | 異常時 |
|---|---|---|---|
| 文書 | 検査 | 結果の行 | 読めなければ FAIL |

## 5. 完成の条件

完成の条件は、自己試験が通ることです。

| 条件 | 確かめ方 |
|---|---|
| 自己試験 | `--selftest` が PASS |

## 6. 代替案と却下の理由

代替案は 1 つです。

| 案 | 却下の理由 |
|---|---|
| 手で見る | 毎回ぶれる |

## 7. 横断事項

横断事項は安全です。秘密を書きません。

## 8. 未確定

未確定は 1 件です。

| 未確定 | 担当 | 期限 |
|---|---|---|
| 版の数え方 | 秘書 | 2026-11-30 |
"""

GOOD_REQ = """# 見本 要件定義書

| 項目 | 内容 |
|---|---|
| 対象 | 見本 |
| 決める人 | 社長 |
| 版 | 1.0（2026-11-11） |

## 1. 目的と背景

- 見本の機能を作り、検査の時間を減らす。

## 2. ゴールと管理指標

| 指標 | 現在 | 目標 |
|---|---|---|
| 検査の時間 | 10 分 | 1 分 |

## 3. 範囲と対象外

| 区分 | 内容 |
|---|---|
| 範囲 | 検査 |
| 対象外 | 本番の運用 |

## 4. 前提と制約

| 区分 | 内容 |
|---|---|
| 前提 | python3 がある |
| 制約 | 外部に送らない |

## 5. 業務要件

| ID | 要件 | 優先度 |
|---|---|---|
| BR-001 | 秘書は、文書を出す前に検査する | Must |

## 6. 機能要件

| ID | 要件文 | 優先度 | 受け入れ基準 | 検証方法 |
|---|---|---|---|---|
| FR-001 | 文書を受け取ったとき、検査は結果の行を返す | Must | 1 本の文書で RESULT の行が 1 行出る | 試験 |

## 7. 非機能要件

| ID | 項目 | 要求値 | 優先度 | 検証方法 |
|---|---|---|---|---|
| NFR-001 | 検査の時間 | 1 本 10 秒以内（p95） | Should | 試験 |

## 8. 受け入れ基準と検証方法

- 受け入れは、FR と NFR の検証方法を全部通すこと。

## 9. 追跡表

| 業務要件 | 機能要件 | 試験 |
|---|---|---|
| BR-001 | FR-001 | T-001 |

## 10. 未決事項

| 番号 | 内容 | 担当 | 期限 |
|---|---|---|---|
| OI-001 | 版の数え方 | 秘書 | 2026-11-30 |
"""

GOOD_PM = """# 見本 ポストモーテム

| 項目 | 内容 |
|---|---|
| 発生日 | 2026-11-11 |
| 重大度 | 2 |
| 状態 | 公開 |
| 著者 | SRE 役 |

## 1. 要約

検査の道具が 10 分止まり、秘書の作業が止まった。原因は道具の更新漏れである。

## 2. 影響

- 止まった時間は 10 分で、影響を受けた作業は 2 件である。

## 3. 検知

- 検知は、検査の FAIL の行による。検知までの時間は 2 分である。

## 4. 対応と復旧

- 当番が道具を入れ直し、復旧までの時間は 8 分である。

## 5. タイムライン（JST）

| 時刻 | 出来事 | 根拠 |
|---|---|---|
| 10:00 | 障害開始。検査が FAIL を出す | 検査の出力 |
| 10:10 | 復旧。検査が PASS に戻る | 検査の出力 |

## 6. 根本原因と引き金

- 根本原因は、道具の版を固定していなかったことである。引き金は道具の更新である。

## 7. 教訓

- うまくいったこと: FAIL の行で 2 分で気づけた。
- うまくいかなかったこと: 版の固定が無かった。
- 幸運だったこと（再現性なし）: 作業が 2 件しか無かった。

## 8. 再発防止の対策

| 対策 | 種類 | 優先度 | 担当 | 期限 | 追跡先 | 状態 |
|---|---|---|---|---|---|---|
| 道具の版を設定ファイルに固定する | 予防 | P1 | インフラ役 | 2026-11-20 | Issue 1 | TODO |
"""

GOODS = {
    "調査報告（資料の型）": GOOD_RESEARCH,
    "手順書（現場の型）": GOOD_PROCEDURE,
    "運用設計書（現場の型）": GOOD_OPS,
    "仕様書（資料の型）": GOOD_SPEC,
    "要件定義書（現場の型）": GOOD_REQ,
    "ポストモーテム（現場の型）": GOOD_PM,
}

SUMMARY = "# 題\n\n> 1. 要約です。\n> 2. 要約です。\n> 3. 要約です。\n\n"
BAD = {
    "要約": "# 題\n\n## 1. 目的\n\n本文です。\n",
    "導入の文": SUMMARY + "## 1. 目的\n\n| a | b |\n|---|---|\n| 1 | 2 |\n",
    "空の節": SUMMARY + "## 1. 目的\n\n## 2. 次\n\n本文です。\n",
    "図の読み方": SUMMARY + "## 1. 目的\n\n図です。\n\n```mermaid\nflowchart LR\n    A[\"a\"] --> B[\"b\"]\n```\n\n## 2. 次\n\n本文です。\n",
    "用語の初出": SUMMARY + "## 1. 目的\n\nhooks が止めます。\n",
    "見出しの深さ": SUMMARY + "## 1. 目的\n\n本文です。\n\n##### 深い\n\n本文です。\n",
    "図と表の密度": SUMMARY + "## 1. 目的\n\n" + ("長い本文です。" * 90) + "\n",
    "必須の節": "# 仕様書: 見本\n\n> 1. 要約です。\n> 2. 要約です。\n> 3. 要約です。\n\n## 1. 目的\n\n本文です。\n",
    "手順の形": "# 手順書: 見本\n\n| 項目 | 内容 |\n|---|---|\n| 作業名 | 見本 |\n\n## 1. 手順\n\n許可の正は設定ファイルです。\n\n優先度 6 が国外の遮断です。\n\nだから優先度 0 の許可が要ります。\n\n1. 足す。\n   - 期待結果: 増える。\n",
    "文書情報": "# 見本 手順書\n\n## 1. 目的\n\n本文です。\n",
    "期待結果": "# 見本 運用手順書\n\n| 項目 | 内容 |\n|---|---|\n| 作業名 | 見本 |\n\n## 1. 作業手順\n\n1. ファイルを開く。\n2. 書く。\n   - 期待結果: 行が増える。\n",
}
# 正例を 1 か所だけ変えた負例。(元, 置換前, 置換後)
BAD_FROM = {
    "比較の表": (GOOD_RESEARCH, "| 操作 | 判定 | 根拠 |\n|---|---|---|\n| 読む | 許可 | 守りの表の 1 行目 |", "| 操作 | 判定 |\n|---|---|\n| 読む | 許可 |"),
    "出典の表": (GOOD_RESEARCH, "| 番号 | 題名 | 参照日 |", "| 番号 | 題名 | URL |"),
    "確信度": (GOOD_RESEARCH, "確信度は高で、推奨が変わる条件は", "推奨が変わる条件は"),
    "変わる条件": (GOOD_RESEARCH, "確信度は高で、推奨が変わる条件は守りの表が変わったときです。", "確信度は高です。"),
    "代替案の表": (GOOD_SPEC, "| 案 | 却下の理由 |", "| 案 | 中身 |"),
    "未確定の表": (GOOD_SPEC, "| 未確定 | 担当 | 期限 |\n|---|---|---|\n| 版の数え方 | 秘書 | 2026-11-30 |", "| 未確定 | 備考 |\n|---|---|\n| 版の数え方 | あとで |"),
    "要件の表": (GOOD_REQ, "| ID | 要件文 | 優先度 | 受け入れ基準 | 検証方法 |\n|---|---|---|---|---|\n| FR-001 | 文書を受け取ったとき、検査は結果の行を返す | Must | 1 本の文書で RESULT の行が 1 行出る | 試験 |", "| ID | 要件文 | 優先度 |\n|---|---|---|\n| FR-001 | 文書を受け取ったとき、検査は結果の行を返す | Must |"),
    "曖昧語": (GOOD_REQ, "検査は結果の行を返す", "検査は速やかに結果の行を返す"),
    "優先度": (GOOD_REQ, "| Must | 1 本の文書で", "| 高 | 1 本の文書で"),
    "要件 ID": (GOOD_REQ, "| NFR-001 |", "| FR-001 |"),
    "未決の表": (GOOD_REQ, "| 番号 | 内容 | 担当 | 期限 |\n|---|---|---|---|\n| OI-001 | 版の数え方 | 秘書 | 2026-11-30 |", "| 番号 | 内容 |\n|---|---|\n| OI-001 | 版の数え方 |"),
    "影響の数字": (GOOD_PM, "- 止まった時間は 10 分で、影響を受けた作業は 2 件である。", "- 影響は小さかった。"),
    "タイムライン": (GOOD_PM, "## 5. タイムライン（JST）", "## 5. タイムライン"),
    "対策の表": (GOOD_PM, "| 対策 | 種類 | 優先度 | 担当 | 期限 | 追跡先 | 状態 |\n|---|---|---|---|---|---|---|\n| 道具の版を設定ファイルに固定する | 予防 | P1 | インフラ役 | 2026-11-20 | Issue 1 | TODO |", "| 対策 | 担当 |\n|---|---|\n| 道具の版を設定ファイルに固定する | インフラ役 |"),
    "担当と期限": (GOOD_PM, "| インフラ役 | 2026-11-20 |", "|  | 2026-11-20 |"),
    "対策の形": (GOOD_PM, "道具の版を設定ファイルに固定する", "注意して道具を更新する"),
    "反事実": (GOOD_PM, "引き金は道具の更新である。", "引き金は道具の更新である。版を固定していれば防げた。"),
}


def selftest() -> bool:
    ok = True
    for name, text in GOODS.items():
        issues = check_text(text)
        if issues:
            ok = False
            print(f"FAIL selftest: 正例「{name}」が落ちた: {issues}")
    bads = dict(BAD)
    for rule, (good, old, new) in BAD_FROM.items():
        if old not in good:
            ok = False
            print(f"FAIL selftest: 負例「{rule}」の置換元が正例に無い")
            continue
        bads[rule] = good.replace(old, new)
    for rule, text in bads.items():
        found = {r for _, r, _ in check_text(text)}
        if rule not in found:
            ok = False
            print(f"FAIL selftest: 負例「{rule}」が通った（検出: {sorted(found)}）")
    print(f"RESULT: {'PASS' if ok else 'FAIL'} check-doc --selftest ({len(GOODS) + len(bads)} 例)")
    return ok


def main(argv) -> int:
    if argv == ["--selftest"]:
        return 0 if selftest() else 1
    if not argv:
        print(__doc__)
        return 2
    all_ok = True
    for name in argv:
        try:
            src = pathlib.Path(name).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            print(f"FAIL {name} [読めない] {e}")
            all_ok = False
            continue
        if not report(name, check_text(src)):
            all_ok = False
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
