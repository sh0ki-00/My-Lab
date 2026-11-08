#!/usr/bin/env python3
"""check-refs — 文書が指すパスの実在の検査。

対象: AGENTS.md、CLAUDE.md、README.md、.cursor/rules/*.mdc、router/*.md、.company/**/*.md、skills/**/*.md、.claude/agents/*.md。
見るもの: バッククォートの中の相対パス（/ を含むか、既知の拡張子で終わるもの）。<…>・*・~・http・tmp/ は見ない。
画面の文言（和文の句読点を含む語と、`予定11/05` のように月日で終わる語）もパスと見ない。
パスは、その文書のディレクトリからの相対、次にリポジトリの root からの相対で探す。
root は道具の場所で決める。My-Lab の tools/lib にあれば My-Lab。他のプロジェクトの tmp/tools/lib に写したときは、
tmp/ ではなくプロジェクトの直下にする（tools/project-verify.sh と同じ決め方）。写した一式（tmp/）も、ファイル名だけの参照の探し先にする。
後の段階で作る予定のパスは tools/planned-paths.txt に書く。FAIL にせず「予定」と報告だけする。
写した先では、写した一式の文書（tmp/skills/・tmp/.company/・tmp/tools/・tmp/samples/ の下と、tmp/claude-code.md・
tmp/cursor-user-rule.md・tmp/DEPLOYED.md）が指す My-Lab にしか無い物（LAB_ONLY: hooks/・.claude/・.cursor/・.github/・
docs/・router/・deploy.sh・install.sh・AGENTS.md）は、写していないので FAIL にせず「正本のみ」と数えるだけにする。
AI が写した先で書いた文書（tmp/flow/ など）とプロジェクト自身の文書では、これまでどおり FAIL にする。
使い方: check_refs.py [ファイル...]（引数が無ければ対象の全部）   /   check_refs.py --selftest
"""
import pathlib
import re
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent


def decide_root(lib_dir: pathlib.Path):
    """(root, kit) を返す。kit は一式の置き場（My-Lab か <プロジェクト>/tmp）。写しなら root はその 1 つ上。"""
    kit = lib_dir.parent.parent
    return (kit.parent if kit.name == "tmp" else kit), kit


ROOT, KIT = decide_root(HERE)
PLANNED_FILE = HERE.parent / "planned-paths.txt"
TARGETS = ["AGENTS.md", "CLAUDE.md", "README.md", ".cursor/rules/*.mdc", "router/*.md", ".company/**/*.md", "skills/**/*.md", ".claude/agents/*.md"]
TOKEN = re.compile(r"`([^`\s]+)`")
DATE_TAIL = re.compile(r"\d{1,2}/\d{1,2}$")  # 11/05 のような月日。画面の文言に出る
EXT = (".md", ".sh", ".json", ".yml", ".yaml", ".mjs", ".js", ".py", ".txt", ".toml", ".mdc")
# My-Lab にしかなく、deploy.sh が写さない物。末尾が / のものはその下の全部
LAB_ONLY = ("hooks/", ".claude/", ".cursor/", ".github/", "docs/", "router/", "deploy.sh", "install.sh", "AGENTS.md")
# deploy.sh が写す一式（kit の直下からの相対）。この文書は My-Lab で書かれ、My-Lab で参照を確かめてある
KIT_DIRS = {"skills", ".company", "tools", "samples"}
KIT_FILES = {"claude-code.md", "cursor-user-rule.md", "DEPLOYED.md"}


def load_planned():
    if not PLANNED_FILE.exists():
        return []
    return [l.strip() for l in PLANNED_FILE.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]


def looks_like_path(tok: str) -> bool:
    if any(c in tok for c in "<>*…{}$|=:,、。"):
        return False
    if DATE_TAIL.search(tok) and not tok.endswith(EXT):
        return False
    if tok.startswith(("~", "/", "http", "tmp/", "-", "node_modules", ".", "#")) and not tok.startswith((".company", ".claude", ".cursor", ".github", ".gitignore")):
        return False
    if "/" in tok:
        return True
    return tok.endswith(EXT)


def find_by_name(root: pathlib.Path, name: str, kit=None) -> bool:
    """ファイル名だけの参照（verify-all.sh など）は、node_modules・tmp・.git を除く全体から探す。写しなら一式（kit）の中も探す。"""
    skip = {"node_modules", "tmp", ".git"}
    for base in [root] + ([kit] if kit and kit != root else []):
        for p in base.rglob(name):
            if not any(part in skip for part in p.relative_to(base).parts):
                return True
    return False


def is_planned(tok: str, planned) -> bool:
    return any(tok == p or (p.endswith("/") and tok.startswith(p)) for p in planned)


def is_lab_only(tok: str) -> bool:
    return any(tok == p or tok == p.rstrip("/") or (p.endswith("/") and tok.startswith(p)) for p in LAB_ONLY)


def is_kit_copy(path: pathlib.Path, root: pathlib.Path, kit) -> bool:
    """写した先（kit が root と違う）で、その文書が deploy.sh の写した一式の 1 本なら True。"""
    if kit is None:
        return False
    kit = pathlib.Path(kit).resolve()
    if kit == root:
        return False
    try:
        rel = path.resolve().relative_to(kit)
    except ValueError:
        return False
    return rel.parts[0] in KIT_DIRS if len(rel.parts) > 1 else rel.name in KIT_FILES


def check_file(path: pathlib.Path, root: pathlib.Path, planned, kit=None):
    """(issues, plans, lab_only) を返す。lab_only は写した一式の文書が指す、My-Lab にしか無い物。"""
    issues = []
    plans = []
    lab_only = []
    in_code = False
    root = root.resolve()  # macOS の /var と /private/var のような別名を揃える
    kit_copy = is_kit_copy(path, root, kit)
    for no, raw in enumerate(path.read_text(encoding="utf-8").split("\n"), 1):
        if raw.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        for tok in TOKEN.findall(raw):
            if not looks_like_path(tok):
                continue
            rel = tok.rstrip("/")
            apath = path.resolve()
            ancestors = [apath.parent] + [p for p in apath.parents if p != apath.parent and (p == root or root in p.parents)]
            cands = [a / rel for a in ancestors] + [root / rel]
            if any(c.exists() for c in cands):
                continue
            if "/" not in rel and find_by_name(root, rel, kit):
                continue
            if is_planned(tok, planned):
                plans.append((no, tok))
            elif kit_copy and is_lab_only(tok):
                lab_only.append((no, tok))
            else:
                issues.append((no, "参照", f"「{tok}」が無い"))
    return issues, plans, lab_only


def report(name, issues, plans, lab_only=()) -> bool:
    for no, tok in plans:
        print(f"PLAN {name}:{no} [予定] 「{tok}」は後の段階で作る（tools/planned-paths.txt）")
    for no, rule, detail in issues:
        print(f"FAIL {name}:{no} [{rule}] {detail}")
    extra = f"、正本のみ {len(lab_only)} 件" if lab_only else ""
    print(f"RESULT: {'PASS' if not issues else 'FAIL'} check-refs {name} ({len(issues)} 件、予定 {len(plans)} 件{extra})")
    return not issues


def selftest() -> bool:
    ok = True
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        (root / "tools").mkdir()
        (root / "tools" / "a.sh").write_text("x", encoding="utf-8")
        (root / "docs").mkdir()
        good = root / "good.md"
        good.write_text("`tools/a.sh` と `docs/` と `<名前>/x.md` と `~/.claude/x` と `tmp/x.md` と `git commit`。\n`予定11/05` と `出荷遅れ、予定11/05` と `11/05` は画面の文言。\n```\n`no/such.md`\n```\n", encoding="utf-8")
        issues, _, _ = check_file(good, root, [])
        if issues:
            ok = False
            print(f"FAIL selftest: 正例が落ちた: {issues}")
        bad = root / "bad.md"
        bad.write_text("`tools/none.sh` と `skills/later/SKILL.md`。\n", encoding="utf-8")  # 月日の除外が本物のパスを見逃さないこと
        issues, plans, _ = check_file(bad, root, ["skills/later/SKILL.md"])
        if len(issues) != 1 or len(plans) != 1:
            ok = False
            print(f"FAIL selftest: 負例の結果が違う: {issues} {plans}")
        # 写した先の形: <proj>/tmp/tools/lib の道具は root を <proj> にし、プロジェクトのファイルも一式のファイルも見つける
        proj = root / "proj"
        (proj / "src").mkdir(parents=True)
        (proj / "src" / "app.py").write_text("x", encoding="utf-8")
        (proj / "tmp" / "tools" / "lib").mkdir(parents=True)
        (proj / "tmp" / "tools" / "project-verify.sh").write_text("x", encoding="utf-8")
        (proj / "tmp" / "skills" / "secretary").mkdir(parents=True)
        (proj / "tmp" / "skills" / "secretary" / "SKILL.md").write_text("x", encoding="utf-8")
        r, k = decide_root(proj / "tmp" / "tools" / "lib")
        if (r, k) != (proj, proj / "tmp") or decide_root(root / "tools" / "lib") != (root, root):
            ok = False
            print(f"FAIL selftest: root の決め方が違う: {r} {k}")
        (proj / "tmp" / "flow" / "x").mkdir(parents=True)
        doc = proj / "tmp" / "flow" / "x" / "intake.md"
        doc.write_text("`src/app.py` と `skills/secretary/SKILL.md` と `project-verify.sh`。\n`src/none.py`。\n", encoding="utf-8")
        issues, _, _ = check_file(doc, r, [], k)
        if len(issues) != 1 or issues[0][0] != 2:
            ok = False
            print(f"FAIL selftest: 写した先の例の結果が違う: {issues}")
        # 写した一式の文書が指す My-Lab にしか無い物は「正本のみ」。AI が写した先で書いた文書では FAIL のまま
        lab_refs = "`hooks/guard-core.sh` と `.claude/settings.json` と `deploy.sh` と `AGENTS.md`。\n`src/none.py`。\n"
        kit_doc = proj / "tmp" / "claude-code.md"
        kit_doc.write_text(lab_refs, encoding="utf-8")
        issues, _, lab = check_file(kit_doc, r, [], k)
        if len(issues) != 1 or issues[0][0] != 2 or len(lab) != 4:
            ok = False
            print(f"FAIL selftest: 写した一式の文書の結果が違う: {issues} {lab}")
        doc.write_text(lab_refs, encoding="utf-8")
        issues, _, lab = check_file(doc, r, [], k)
        if len(issues) != 5 or lab:
            ok = False
            print(f"FAIL selftest: 写した先で書いた文書が My-Lab の物を見逃した: {issues} {lab}")
        issues, _, lab = check_file(kit_doc, root, [], root)  # My-Lab の中（kit が root と同じ）
        if len(issues) != 5 or lab:
            ok = False
            print(f"FAIL selftest: My-Lab の中で「正本のみ」を使った: {issues} {lab}")
    print(f"RESULT: {'PASS' if ok else 'FAIL'} check-refs --selftest (4 例)")
    return ok


def main(argv) -> int:
    if argv == ["--selftest"]:
        return 0 if selftest() else 1
    planned = load_planned()
    if argv:
        files = [pathlib.Path(a) for a in argv]
    else:
        files = []
        for pat in TARGETS:
            files += sorted(ROOT.glob(pat))
    all_ok = True
    for f in files:
        if not f.is_file() or "/evals/cases/" in f.as_posix() or "/templates/" in f.as_posix():
            continue
        issues, plans, lab_only = check_file(f, ROOT, planned, KIT)
        rel = f.relative_to(ROOT) if f.is_absolute() and str(f).startswith(str(ROOT)) else f
        if not report(str(rel), issues, plans, lab_only):
            all_ok = False
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
