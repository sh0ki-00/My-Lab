#!/usr/bin/env python3
"""check-mermaid — Mermaid の図の静的な検査。.company/rules/diagrams.md の、機械で見られる決まりを落とす。

見るもの: 図の種類（flowchart・sequenceDiagram・erDiagram・stateDiagram-v2・gantt だけ）、ノードの id（英数字だけ、end は不可）、
ラベルの引用符、subgraph と end の対応、ノード 12 個以内、引用符の数（奇数は崩れる）。
実際の描画は tools/render-mermaid.mjs が確かめる。
使い方: check_mermaid.py <ファイル>...   /   check_mermaid.py --selftest
"""
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import mdparse  # noqa: E402

ALLOWED = ("flowchart", "sequenceDiagram", "erDiagram", "stateDiagram-v2", "gantt")
MAX_NODES = 12
ID_OK = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
FLOW_SKIP = re.compile(r"^(direction\b|classDef\b|class\b|style\b|linkStyle\b|click\b)")
BRACKET = re.compile(r"\[+[^\]]*\]+|\(+[^)]*\)+|\{+[^}]*\}+|(?<=[A-Za-z0-9_])>[^\]]*\]")
ARROW_SPLIT = re.compile(r"\s*(?:[<xo]?[-=.]{2,}[>xo]?|&)\s*")
SEQ_OPEN = re.compile(r"^(loop|alt|opt|par|critical|break|rect|box)\b")
SEQ_SKIP = re.compile(r"^(Note\b|note\b|else\b|and\b|option\b|autonumber\b|activate\b|deactivate\b|title\b|end$)")
SEQ_MSG = re.compile(r"^([^\s:]+?)\s*-{1,2}(?:>>|>|x|\))\s*[+-]?\s*([^\s:]+?)\s*:")
ER_REL = re.compile(r"^(\S+)\s+[|}o{]+[-.]+[|}o{]+\s+(\S+)\s*:")
GANTT_SKIP = re.compile(r"^(title|dateFormat|axisFormat|section|excludes|todayMarker|tickInterval|weekday|inclusiveEndDates|%%)")


def check_flow(body, start):
    issues = []
    ids = set()
    sub = 0
    endc = 0
    for no, s in body:
        if re.match(r"^subgraph\b", s):
            sub += 1
            m = re.match(r"^subgraph\s+([^\s\[]+)\s*(\[.*\])?\s*$", s)
            if m and m.group(2):
                if not ID_OK.match(m.group(1)):
                    issues.append((no, "id", f"subgraph の id「{m.group(1)}」は英数字だけにする"))
                inner = m.group(2)[1:-1].strip()
                if not (inner.startswith('"') and inner.endswith('"')):
                    issues.append((no, "ラベル", "subgraph のラベルを引用符で囲む"))
            continue
        if s == "end":
            endc += 1
            continue
        if FLOW_SKIP.match(s):
            continue
        line = re.sub(r":::\w+", "", s)
        line = re.sub(r"\|[^|]*\|", "", line)
        line = re.sub(r"--\s+[^-]+?\s+-->", "-->", line)
        labels = []

        def keep(m):
            labels.append(m.group(0))
            return f"\x00{len(labels) - 1}\x00"

        line = BRACKET.sub(keep, line)
        for seg in ARROW_SPLIT.split(line):
            seg = seg.strip()
            if not seg:
                continue
            m = re.match(r"^([^\s\x00]+)\s*(?:\x00(\d+)\x00)?\s*$", seg)
            if not m:
                issues.append((no, "記法", f"読めない要素: {seg[:30]}"))
                continue
            nid, li = m.group(1), m.group(2)
            if nid.lower() == "end":
                issues.append((no, "id", "end は予約語。id に使わない"))
            elif not ID_OK.match(nid):
                issues.append((no, "id", f"id「{nid}」は英数字だけにする。表示名はラベルに書く"))
            ids.add(nid)
            if li is not None:
                inner = labels[int(li)].strip("[](){}>/\\").strip()
                if inner and not (inner.startswith('"') and inner.endswith('"')):
                    issues.append((no, "ラベル", f"ラベル {labels[int(li)][:24]} を引用符で囲む"))
    if sub != endc:
        issues.append((start, "subgraph", f"subgraph {sub} 個に対し end {endc} 個"))
    if len(ids) > MAX_NODES:
        issues.append((start, "ノード数", f"{len(ids)} 個。12 個以内にし、超えるなら全体図と詳細図に分ける"))
    return issues


def check_sequence(body, start):
    issues = []
    ids = set()
    opens = 0
    ends = 0
    for no, s in body:
        m = re.match(r"^(participant|actor)\s+(\S+)(\s+as\s+.*)?$", s)
        if m:
            ids.add(m.group(2))
            if not ID_OK.match(m.group(2)):
                issues.append((no, "id", f"参加者の id「{m.group(2)}」は英数字だけにする。表示名は as の後に書く"))
            continue
        if SEQ_OPEN.match(s):
            opens += 1
            continue
        if s == "end":
            ends += 1
            continue
        if SEQ_SKIP.match(s):
            continue
        m = SEQ_MSG.match(s)
        if m:
            ids.add(m.group(1))
            ids.add(m.group(2))
    if opens != ends:
        issues.append((start, "end の対応", f"loop/alt などの開き {opens} に対し end {ends}"))
    if len(ids) > MAX_NODES:
        issues.append((start, "ノード数", f"参加者 {len(ids)}。12 以内にする"))
    return issues


def check_er(body, start):
    issues = []
    ids = set()
    for no, s in body:
        m = ER_REL.match(s)
        if m:
            ids.update([m.group(1), m.group(2)])
            continue
        m = re.match(r"^(\S+)\s*\{$", s)
        if m:
            ids.add(m.group(1))
    for i in sorted(ids):
        if not re.match(r"^[A-Za-z][A-Za-z0-9_-]*$", i):
            issues.append((start, "id", f"実体の名前「{i}」は英数字だけにする"))
    if len(ids) > MAX_NODES:
        issues.append((start, "ノード数", f"実体 {len(ids)}。12 以内にする"))
    return issues


def check_state(body, start):
    issues = []
    ids = set()
    for no, s in body:
        m = re.match(r'^state\s+"[^"]*"\s+as\s+(\S+)', s)
        if m:
            ids.add(m.group(1))
            continue
        m = re.match(r"^state\s+(\S+)\s*\{", s)
        if m:
            ids.add(m.group(1))
            continue
        if re.match(r"^(note\b|end note|direction\b|\}|%%)", s):
            continue
        m = re.match(r"^(\S+)\s*-->\s*(\S+)", s)
        if m:
            for x in (m.group(1), m.group(2)):
                if x != "[*]":
                    ids.add(x.rstrip(":"))
    for i in sorted(ids):
        if not ID_OK.match(i):
            issues.append((start, "id", f"状態の id「{i}」は英数字だけにする。表示名は state \"…\" as id で書く"))
    if len(ids) > MAX_NODES:
        issues.append((start, "ノード数", f"状態 {len(ids)}。12 以内にする"))
    return issues


def check_gantt(body, start):
    tasks = [s for _no, s in body if ":" in s and not GANTT_SKIP.match(s)]
    if len(tasks) > MAX_NODES:
        return [(start, "ノード数", f"作業 {len(tasks)} 件。12 以内にする")]
    return []


def check_block(start, content):
    """1 つの図を検査する。content は Line の列。"""
    body = []
    for ln in content:
        s = ln.raw.strip()
        if not s or s.startswith("%%"):
            continue
        body.append((ln.no, s))
    if not body:
        return [(start, "空の図", "図の中身が無い")]
    issues = []
    for no, s in body:
        if s.count('"') % 2:
            issues.append((no, "引用符", "引用符の数が奇数。描画が崩れる"))
    head = body[0][1]
    kind = head.split()[0]
    if kind not in ALLOWED:
        hint = "flowchart を使う" if kind == "graph" else "表にない種類は使わない（diagrams.md の表）"
        issues.append((start, "図の種類", f"「{kind}」。{hint}"))
        return issues
    rest = body[1:]
    if kind == "flowchart":
        if not re.match(r"^flowchart\s+(LR|RL|TD|TB|BT)\s*$", head):
            issues.append((start, "向き", "flowchart の向き（LR・TD など）を書く"))
        issues += check_flow(rest, start)
    elif kind == "sequenceDiagram":
        issues += check_sequence(rest, start)
    elif kind == "erDiagram":
        issues += check_er(rest, start)
    elif kind == "stateDiagram-v2":
        issues += check_state(rest, start)
    elif kind == "gantt":
        issues += check_gantt(rest, start)
    return issues


def check_text(src: str):
    issues = []
    lines = mdparse.parse(src)
    for _lang, start, _end, content in mdparse.code_blocks(lines, "mermaid"):
        issues += check_block(start, content)
    return issues


def report(name: str, issues, count: int) -> bool:
    for no, rule, detail in issues:
        print(f"FAIL {name}:{no} [{rule}] {detail}")
    verdict = "PASS" if not issues else "FAIL"
    print(f"RESULT: {verdict} check-mermaid {name} ({count} 図、{len(issues)} 件)")
    return not issues


def wrap(code: str) -> str:
    return f"# 題\n\n```mermaid\n{code}\n```\n"


GOOD = [
    'flowchart LR\n    subgraph repo["正本"]\n        A["読む"] --> B{"判断"}\n    end\n    B -->|はい| C(["終わり"])\n    B -->|いいえ| A',
    "sequenceDiagram\n    participant T as ツール\n    participant G as 判定本体\n    T->>G: コマンド\n    G-->>T: 判定\n    loop 再試行\n        T->>G: 再送\n    end",
    'erDiagram\n    ORDER ||--o{ ORDER_ITEM : "contains"\n    ORDER {\n        int id\n    }',
    'stateDiagram-v2\n    [*] --> Draft\n    Draft --> Review\n    state "承認済み" as Approved\n    Review --> Approved\n    Approved --> [*]',
    "gantt\n    title 計画\n    dateFormat YYYY-MM-DD\n    section 段階 0\n    骨格 :a1, 2026-11-06, 3d",
]

BAD = {
    "図の種類": 'graph LR\n    A["a"] --> B["b"]',
    "ラベル": "flowchart LR\n    A[注文] --> B[出荷]",
    "id": 'flowchart LR\n    a-b["x"] --> c["y"]',
    "subgraph": 'flowchart LR\n    subgraph s["箱"]\n    A["a"] --> B["b"]',
    "ノード数": "flowchart LR\n" + "\n".join(f'    N{i}["n"] --> N{i + 1}["n"]' for i in range(13)),
    "引用符": 'flowchart LR\n    A["a] --> B["b"]',
    "向き": 'flowchart\n    A["a"] --> B["b"]',
}


def selftest() -> bool:
    ok = True
    for code in GOOD:
        issues = check_text(wrap(code))
        if issues:
            ok = False
            print(f"FAIL selftest: 正例が落ちた: {issues} :: {code[:40]}")
    for rule, code in BAD.items():
        found = {r for _, r, _ in check_text(wrap(code))}
        if rule not in found:
            ok = False
            print(f"FAIL selftest: 負例「{rule}」が通った（検出: {sorted(found)}）")
    print(f"RESULT: {'PASS' if ok else 'FAIL'} check-mermaid --selftest ({len(GOOD) + len(BAD)} 例)")
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
        count = len(mdparse.code_blocks(mdparse.parse(src), "mermaid"))
        if not report(name, check_text(src), count):
            all_ok = False
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
