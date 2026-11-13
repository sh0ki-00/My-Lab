#!/usr/bin/env python3
"""tools/lib/check_persona.py <ファイル>... — 資料に「秘書」「社長」の語が無いかを見る。

見る文書と見方:
  スキルの雛形と完成例（skills/<名前>/templates/ と examples/ の .md）
      1 つでもあれば FAIL。「」の中も図の中も数える。雛形の穴と例は、そのまま写されて資料になるため。
  それ以外の文書（check-file.sh が、写した先で AI が書く tmp/flow/・tmp/ISSUE_*・tmp/PR_* の資料だけを渡す）
      「」の中（人の言葉の引用）、`…` の中、``` の囲みの中（コードと記録）は数えない。
決まりの本文は .company/rules/documents.md の 5 節（写した先では tmp/.company/rules/documents.md）。
使い方: check_persona.py <ファイル>...   /   check_persona.py --selftest
出力: FAIL <ファイル>:<行> [秘書・社長の語] … の行と、最後に RESULT: PASS|FAIL check-persona の行。
      1 件でも FAIL なら終了コード 1。
"""
import pathlib
import re
import sys
import tempfile

WORDS = re.compile(r"秘書|(?<!副)社長")  # 副社長は実在の肩書なので数えない
STRICT = re.compile(r"(^|/)skills/[^/]+/(templates|examples)/")
HINT = "人は役目の語で書く（依頼者、読み手、対象の持ち主、取りまとめ役。.company/rules/documents.md の 5 節）"


def outside_quotes(line):
    """「」（入れ子を含む）と `…` の中を除いた文字列を返す。"""
    out = []
    depth = 0
    in_code = False
    for ch in line:
        if in_code:
            if ch == "`":
                in_code = False
            continue
        if depth == 0 and ch == "`":
            in_code = True
            continue
        if ch == "「":
            depth += 1
            continue
        if ch == "」" and depth > 0:
            depth -= 1
            continue
        if depth == 0:
            out.append(ch)
    return "".join(out)


def check(path):
    """[(行番号, 見つかった語の並び)] を返す。読めないときは行番号 0 で理由を返す。"""
    strict = bool(STRICT.search(str(path).replace("\\", "/")))
    try:
        text = pathlib.Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return [(0, f"読めない: {e}")]
    found = []
    fence = False
    for no, line in enumerate(text.split("\n"), 1):
        if line.lstrip().startswith("```"):
            fence = not fence
            if not strict:
                continue
        if strict:
            target = line
        elif fence:
            continue
        else:
            target = outside_quotes(line)
        words = WORDS.findall(target)
        if words:
            found.append((no, "・".join(dict.fromkeys(words))))
    return found


def main(files):
    total = 0
    for f in files:
        for no, words in check(f):
            total += 1
            if no == 0:
                print(f"FAIL {f} [秘書・社長の語] {words}")
            else:
                print(f"FAIL {f}:{no} [秘書・社長の語] 「{words}」がある。{HINT}")
    verdict = "FAIL" if total else "PASS"
    if len(files) == 1:
        print(f"RESULT: {verdict} check-persona {files[0]} ({total} 件)")
    else:
        print(f"RESULT: {verdict} check-persona ({len(files)} 本、{total} 件)")
    return 1 if total else 0


def selftest():
    cases = [
        # (置き場, 中身, 期待の件数)
        ("skills/demo/templates/report.md", "> 3. <依頼者にしてほしいこと>\n", 0),
        ("skills/demo/templates/report.md", "> 3. <社長にしてほしいこと>\n", 1),
        ("skills/demo/templates/record.md", "| 承認の言葉 | 「<社長の言葉をそのまま>」 |\n", 1),
        ("skills/demo/examples/flow.md", "```mermaid\nflowchart LR\n  Q[\"社長の問い\"] --> A\n```\n", 1),
        ("skills/demo/examples/runbooks/page.md", "| 取りまとめ役 | 影響の時間 |\n| 秘書 | 次の処置 |\n", 1),
        ("flow/demo/report.md", "依頼者の承認を得てから進める。\n", 0),
        ("flow/demo/report.md", "社長の承認を得てから進める。\n", 1),
        ("flow/demo/intake.md", "| 依頼の原文 | 「社長に見せる資料を作って」（依頼者、チャット） |\n", 0),
        ("flow/demo/intake.md", "| 依頼の原文 | 「「社長」と書かないで」と言われた（依頼者） |\n", 0),
        ("flow/demo/log.md", "コマンドは `grep 秘書` で、結果は 0 件だった。\n", 0),
        ("flow/demo/log.md", "```\n社長 2026-11-13 承認\n```\n本文は依頼者と書く。\n", 0),
        ("flow/demo/memo.md", "秘書室の会議は月曜。社長室にも伝える。\n", 1),
        ("flow/demo/source.md", "出典は Brad Porter（Amazon 副社長、当時）の記事。\n", 0),
        ("skills/demo/examples/source.md", "出典は Brad Porter（Amazon 副社長、当時）の記事。\n", 0),
    ]
    ok = True
    with tempfile.TemporaryDirectory() as tmp:
        base = pathlib.Path(tmp)
        for i, (rel, body, want) in enumerate(cases):
            p = base / f"c{i}" / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body, encoding="utf-8")
            got = len(check(p))
            if got != want:
                ok = False
                print(f"FAIL selftest check-persona: 例 {i}（{rel}）の件数 {got}（期待 {want}）")
    print(f"RESULT: {'PASS' if ok else 'FAIL'} check-persona --selftest ({len(cases)} 例)")
    return 0 if ok else 1


if __name__ == "__main__":
    if sys.argv[1:] == ["--selftest"]:
        sys.exit(selftest())
    if not sys.argv[1:]:
        print("使い方: check_persona.py <ファイル>...   /   check_persona.py --selftest")
        sys.exit(2)
    sys.exit(main(sys.argv[1:]))
