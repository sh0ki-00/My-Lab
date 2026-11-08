#!/usr/bin/env python3
"""mdparse — Markdown を行の種類に分ける小さな解析器。

check_ja・check_doc・check_mermaid が共有する。行の種類は次のとおり。
frontmatter / comment / skipped / fence / code / mermaid / blank / heading / table / hr / image / list / quote / prose
skipped は、検査から外す印（<!-- check:off --> 〜 <!-- check:on -->、<!-- ja-ok -->）の中の行。本文として数えないが、節が空とも見ない。
"""
import re
from dataclasses import dataclass

CODE_SPAN = re.compile(r"`[^`\n]*`")
URL = re.compile(r"https?://[^\s）)、。]+")
LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
BOLD = re.compile(r"\*\*|__")
TAG = re.compile(r"<[^<>\n]{1,120}>")


@dataclass
class Line:
    no: int
    raw: str
    kind: str
    text: str = ""
    level: int = 0
    lang: str = ""
    in_quote: bool = False


def clean(text: str) -> str:
    """見出し・本文の行から記法を外し、読み手が読む文字だけにする。コードと URL と <…> は X に置き換える。"""
    t = CODE_SPAN.sub("X", text)
    t = URL.sub("X", t)
    t = LINK.sub(r"\1", t)
    t = BOLD.sub("", t)
    t = TAG.sub("X", t)
    return t.strip()


def parse(src: str) -> list:
    """本文を Line の列にする。"""
    lines = []
    raws = src.split("\n")
    fm_end = -1
    if raws and raws[0].strip() == "---":
        for j in range(1, min(len(raws), 80)):
            if raws[j].strip() == "---":
                fm_end = j
                break
    in_code = False
    in_comment = False
    skipping = False
    fence = ""
    lang = ""
    for idx, raw in enumerate(raws):
        no = idx + 1
        s = raw.rstrip("\r")
        st = s.strip()
        if idx <= fm_end:
            lines.append(Line(no, s, "frontmatter"))
            continue
        if in_comment:
            lines.append(Line(no, s, "comment"))
            if "-->" in st:
                in_comment = False
            continue
        if in_code:
            if st.startswith(fence):
                in_code = False
                lines.append(Line(no, s, "fence", lang=lang))
            else:
                lines.append(Line(no, s, "mermaid" if lang == "mermaid" else "code", lang=lang))
            continue
        # 検査から外す印。<!-- check:off --> 〜 <!-- check:on --> の区間と、<!-- ja-ok --> の行は注釈と同じに扱う
        # （ja-lint:off / ja-lint:on / ja-lint:ignore も同じ意味で読む。悪い文の見本を置くときに使う）
        # コードの中（`…`）に書かれた印は、印の説明なので印と見ない
        marker_src = CODE_SPAN.sub("", st)
        if re.search(r"<!--\s*(check|ja-lint):off\s*-->", marker_src):
            skipping = True
            lines.append(Line(no, s, "comment"))
            continue
        if re.search(r"<!--\s*(check|ja-lint):on\s*-->", marker_src):
            skipping = False
            lines.append(Line(no, s, "comment"))
            continue
        if skipping or re.search(r"<!--\s*(ja-ok|ja-lint:ignore)\s*-->", marker_src):
            lines.append(Line(no, s, "skipped"))
            continue
        if st.startswith("<!--"):
            lines.append(Line(no, s, "comment"))
            if "-->" not in st[4:]:
                in_comment = True
            continue
        m = re.match(r"^(`{3,}|~{3,})\s*([A-Za-z0-9_+-]*)", st)
        if m:
            in_code = True
            fence = m.group(1)
            lang = m.group(2).lower()
            lines.append(Line(no, s, "fence", lang=lang))
            continue
        if st == "":
            lines.append(Line(no, s, "blank"))
            continue
        hm = re.match(r"^(#{1,6})\s+(.*?)\s*#*$", st)
        if hm:
            lines.append(Line(no, s, "heading", clean(hm.group(2)), level=len(hm.group(1))))
            continue
        if st.startswith("|"):
            lines.append(Line(no, s, "table", clean(st.strip("|"))))
            continue
        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", st):
            lines.append(Line(no, s, "hr"))
            continue
        if st.startswith("!["):
            lines.append(Line(no, s, "image"))
            continue
        quote = False
        body = st
        if body.startswith(">"):
            quote = True
            body = re.sub(r"^(>\s?)+", "", body).strip()
            if body == "":
                lines.append(Line(no, s, "blank", in_quote=True))
                continue
        lm = re.match(r"^([-*+]|\d+[.)])\s+(.*)$", body)
        if lm:
            lines.append(Line(no, s, "list", clean(lm.group(2)), in_quote=quote))
            continue
        lines.append(Line(no, s, "quote" if quote else "prose", clean(body), in_quote=quote))
    return lines


def sentences(text: str):
    """文に分ける。(文, 終端記号があるか) の列を返す。終端記号は 。！？。"""
    out = []
    buf = ""
    for ch in text:
        buf += ch
        if ch in "。！？":
            if buf.strip():
                out.append((buf.strip(), True))
            buf = ""
    if buf.strip():
        out.append((buf.strip(), False))
    return out


def code_blocks(lines, lang=None):
    """(lang, 開始の行番号, 終了の行番号, 内容の Line の列) を返す。lang を与えればその種類だけ。"""
    blocks = []
    cur = None
    for ln in lines:
        if ln.kind == "fence":
            if cur is None:
                cur = [ln.lang, ln.no, None, []]
            else:
                cur[2] = ln.no
                if lang is None or cur[0] == lang:
                    blocks.append(tuple(cur))
                cur = None
        elif cur is not None and ln.kind in ("code", "mermaid"):
            cur[3].append(ln)
    return blocks


def length(text: str) -> int:
    """字数。空白は数えない。"""
    return len(re.sub(r"\s", "", text))
