#!/usr/bin/env python3
"""check-skill — スキルの形式検査（仕様書 8 章と 9.1 節）。

見るもの: frontmatter の name（ディレクトリ名と同じ。英小文字・数字・ハイフンで 64 字以内）と description（1〜1024 字）、
SKILL.md が 150 行以内、7 つの節、6 点（SKILL.md・references/・templates/・examples/・scripts/・evals/）が揃って空でないこと、
evals/run.sh と scripts/*.sh に実行権限があること、examples/ に完成例（.md）があること。
使い方: check_skill.py [skills/<名前>...]（引数が無ければ skills/ の全部）   /   check_skill.py --selftest
"""
import os
import pathlib
import re
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
SECTIONS = ["いつ使うか", "先に読むもの", "判断の観点", "手順", "出力と受け渡し", "禁止", "提出前の確認"]
POINTS = ["references", "templates", "examples", "scripts", "evals"]
MAX_LINES = 150
NAME_RX = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def frontmatter(text: str):
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None, "frontmatter が無い（1 行目が --- でない）"
    data = {}
    key = None
    for s in lines[1:]:
        if s.strip() == "---":
            return data, None
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):\s*(.*)$", s)
        if m:
            key = m.group(1)
            val = m.group(2).strip()
            if val in (">", ">-", "|", "|-"):
                val = ""
            data[key] = val
        elif key and s.startswith((" ", "\t")):
            data[key] = (data[key] + " " + s.strip()).strip()
    return None, "frontmatter が閉じていない（2 つ目の --- が無い）"


def check_skill(d: pathlib.Path):
    issues = []
    skill = d / "SKILL.md"
    if not skill.exists():
        return [(0, "SKILL.md", "無い")]
    text = skill.read_text(encoding="utf-8")
    n = len(text.splitlines())
    if n > MAX_LINES:
        issues.append((n, "行数", f"{n} 行。150 行以内にし、詳細は references/ に置く"))
    fm, err = frontmatter(text)
    if err:
        issues.append((1, "frontmatter", err))
    else:
        name = fm.get("name", "")
        if name != d.name:
            issues.append((1, "name", f"「{name}」がディレクトリ名「{d.name}」と違う"))
        if not NAME_RX.match(name) or len(name) > 64:
            issues.append((1, "name", "英小文字・数字・ハイフンで 64 字以内にする"))
        desc = fm.get("description", "")
        if not 1 <= len(desc) <= 1024:
            issues.append((1, "description", f"{len(desc)} 字。1〜1024 字にする"))
    headings = [m.group(1).strip() for m in re.finditer(r"^##\s+(.+)$", text, re.M)]
    for s in SECTIONS:
        if not any(h.startswith(s) for h in headings):
            issues.append((0, "節", f"「## {s}」が無い"))
    for p in POINTS:
        pd = d / p
        if not pd.is_dir():
            issues.append((0, "6 点", f"{p}/ が無い"))
            continue
        files = [f for f in pd.rglob("*") if f.is_file() and not f.name.startswith(".")]
        if not files:
            issues.append((0, "6 点", f"{p}/ が空"))
    run = d / "evals" / "run.sh"
    if (d / "evals").is_dir():
        if not run.exists():
            issues.append((0, "evals", "evals/run.sh が無い"))
        elif not os.access(run, os.X_OK):
            issues.append((0, "evals", "evals/run.sh に実行権限が無い"))
    if (d / "scripts").is_dir():
        for sh in sorted((d / "scripts").glob("*.sh")):
            if not os.access(sh, os.X_OK):
                issues.append((0, "scripts", f"scripts/{sh.name} に実行権限が無い"))
    if (d / "examples").is_dir() and not list((d / "examples").glob("*.md")):
        issues.append((0, "examples", "完成例（.md）が無い"))
    return issues


def report(d: pathlib.Path, issues) -> bool:
    name = str(d)
    for no, rule, detail in issues:
        where = f"{name}/SKILL.md:{no}" if no else name
        print(f"FAIL {where} [{rule}] {detail}")
    print(f"RESULT: {'PASS' if not issues else 'FAIL'} check-skill {name} ({len(issues)} 件)")
    return not issues


GOOD_SKILL = """---
name: {name}
description: 見本のスキル。検査の正例。
---
# 見本

## いつ使うか
## 先に読むもの
## 判断の観点
## 手順
## 出力と受け渡し
## 禁止
## 提出前の確認
"""


def make_skill(base: pathlib.Path, name: str, text: str, points=POINTS, exec_ok=True) -> pathlib.Path:
    d = base / name
    d.mkdir()
    (d / "SKILL.md").write_text(text, encoding="utf-8")
    for p in points:
        (d / p).mkdir()
        fname = {"evals": "run.sh", "scripts": "x-check.sh", "examples": "example.md"}.get(p, "a.md")
        f = d / p / fname
        f.write_text("x\n", encoding="utf-8")
        if fname.endswith(".sh") and exec_ok:
            f.chmod(0o755)
    return d


def selftest() -> bool:
    ok = True
    with tempfile.TemporaryDirectory() as tmp:
        base = pathlib.Path(tmp)
        good = make_skill(base, "good-skill", GOOD_SKILL.format(name="good-skill"))
        if check_skill(good):
            ok = False
            print(f"FAIL selftest: 正例が落ちた: {check_skill(good)}")
        cases = {
            "name": make_skill(base, "bad-name", GOOD_SKILL.format(name="other")),
            "節": make_skill(base, "bad-section", GOOD_SKILL.format(name="bad-section").replace("## 禁止\n", "")),
            "行数": make_skill(base, "bad-long", GOOD_SKILL.format(name="bad-long") + "x\n" * 150),
            "6 点": make_skill(base, "bad-points", GOOD_SKILL.format(name="bad-points"), points=["references"]),
            "evals": make_skill(base, "bad-exec", GOOD_SKILL.format(name="bad-exec"), exec_ok=False),
            "frontmatter": make_skill(base, "bad-fm", "# 見本\n"),
        }
        for rule, d in cases.items():
            found = {r for _, r, _ in check_skill(d)}
            if rule not in found:
                ok = False
                print(f"FAIL selftest: 負例「{rule}」が通った（検出: {sorted(found)}）")
    print(f"RESULT: {'PASS' if ok else 'FAIL'} check-skill --selftest (7 例)")
    return ok


def main(argv) -> int:
    if argv == ["--selftest"]:
        return 0 if selftest() else 1
    dirs = [pathlib.Path(a) for a in argv] if argv else sorted(p for p in (ROOT / "skills").glob("*") if p.is_dir())
    if not dirs:
        print("RESULT: PASS check-skill (スキルが 0 本)")
        return 0
    all_ok = True
    for d in dirs:
        if not report(d, check_skill(d)):
            all_ok = False
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
